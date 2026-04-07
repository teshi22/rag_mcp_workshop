# 01-rag: 受講生ごとの App Service デプロイスクリプト (PowerShell)
# 使い方:
#   .\01-rag\deploy.ps1
# .env に必要な値がすべて設定されていること

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$EnvFile = Join-Path $RepoRoot ".env"

if (-not (Test-Path $EnvFile)) {
    Write-Error ".env ファイルが見つかりません: $EnvFile"
    exit 1
}

# .env を読み込み
$envVars = @{}
Get-Content $EnvFile | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
        $envVars[$Matches[1].Trim()] = $Matches[2].Trim()
    }
}

# 必須変数チェック
foreach ($key in @("AZURE_RESOURCE_GROUP", "PREFIX", "STUDENT_ID", "AZURE_OPENAI_ENDPOINT", "AZURE_SEARCH_ENDPOINT")) {
    if (-not $envVars[$key]) { throw ".env に $key を設定してください" }
}

$ResourceGroup = $envVars["AZURE_RESOURCE_GROUP"]
$Prefix = $envVars["PREFIX"]
$StudentId = $envVars["STUDENT_ID"]
$AppName = "$Prefix-$StudentId-app"
$PlanName = "$Prefix-plan"
$SearchIndex = if ($envVars["AZURE_SEARCH_INDEX"]) { $envVars["AZURE_SEARCH_INDEX"] } else { "rag-index" }
$Model = if ($envVars["AZURE_OPENAI_MODEL"]) { $envVars["AZURE_OPENAI_MODEL"] } else { "gpt-4.1" }
$EmbModel = if ($envVars["AZURE_OPENAI_EMBEDDING_MODEL"]) { $envVars["AZURE_OPENAI_EMBEDDING_MODEL"] } else { "text-embedding-3-small" }

Write-Host "`n=== デプロイ設定 ==="
Write-Host "RESOURCE_GROUP: $ResourceGroup"
Write-Host "APP_NAME:       $AppName"
Write-Host "SEARCH_INDEX:   $SearchIndex"
Write-Host ""

Write-Host "🏗️  App Service Plan を作成（既存の場合はスキップ）..."
az appservice plan create `
    --resource-group $ResourceGroup `
    --name $PlanName `
    --sku B1 `
    --is-linux `
    --output none 2>$null

Write-Host "🌐 Web App '$AppName' を作成..."
az webapp create `
    --resource-group $ResourceGroup `
    --plan $PlanName `
    --name $AppName `
    --runtime "PYTHON:3.11" `
    --output none

Write-Host "🔑 マネージド ID を有効化し RBAC を割り当て..."
$PrincipalId = az webapp identity assign `
    --resource-group $ResourceGroup `
    --name $AppName `
    --query principalId -o tsv

$FoundryId = az cognitiveservices account show `
    --resource-group $ResourceGroup `
    --name "$Prefix-ai" `
    --query id -o tsv

$SearchId = az resource show `
    --resource-group $ResourceGroup `
    --resource-type "Microsoft.Search/searchServices" `
    --name "$Prefix-search" `
    --query id -o tsv

# App → Foundry: Cognitive Services OpenAI User
az role assignment create `
    --assignee-object-id $PrincipalId `
    --assignee-principal-type ServicePrincipal `
    --role "Cognitive Services OpenAI User" `
    --scope $FoundryId `
    --output none 2>$null

# App → AI Search: Search Index Data Reader
az role assignment create `
    --assignee-object-id $PrincipalId `
    --assignee-principal-type ServicePrincipal `
    --role "Search Index Data Reader" `
    --scope $SearchId `
    --output none 2>$null

Write-Host "⚙️  アプリ設定を反映..."
az webapp config appsettings set `
    --resource-group $ResourceGroup `
    --name $AppName `
    --settings `
        AZURE_OPENAI_ENDPOINT=$($envVars["AZURE_OPENAI_ENDPOINT"]) `
        AZURE_OPENAI_MODEL=$Model `
        AZURE_OPENAI_EMBEDDING_MODEL=$EmbModel `
        AZURE_SEARCH_ENDPOINT=$($envVars["AZURE_SEARCH_ENDPOINT"]) `
        AZURE_SEARCH_INDEX=$SearchIndex `
    --output none

Write-Host "📦 アプリコードをデプロイ..."
$ZipPath = Join-Path $env:TEMP "rag-app-deploy.zip"
if (Test-Path $ZipPath) { Remove-Item $ZipPath }
Compress-Archive -Path "$ScriptDir/app/*" -DestinationPath $ZipPath

az webapp deploy `
    --resource-group $ResourceGroup `
    --name $AppName `
    --src-path $ZipPath `
    --type zip

az webapp config set `
    --resource-group $ResourceGroup `
    --name $AppName `
    --startup-file "pip install -r app/requirements.txt && python -m streamlit run app/app.py --server.port 8000 --server.address 0.0.0.0" `
    --output none

Remove-Item $ZipPath -ErrorAction SilentlyContinue

Write-Host "`n✅ デプロイ完了: https://$AppName.azurewebsites.net"
