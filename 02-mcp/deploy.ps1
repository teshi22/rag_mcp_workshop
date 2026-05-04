# 02-mcp: 受講生ごとの Azure Functions (MCP) + App Service デプロイスクリプト (PowerShell)
# 使い方:
#   .\02-mcp\deploy.ps1
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
$PlanName = "$Prefix-$StudentId-plan"  # 01-rag で作成済みのものを再利用
$FuncName = "$Prefix-$StudentId-func"
$FuncStorage = ("$Prefix$StudentId" + "funcstor").Replace("-", "").ToLower()
$SearchIndex = if ($envVars["AZURE_SEARCH_INDEX"]) { $envVars["AZURE_SEARCH_INDEX"] } else { "rag-index" }
$Model = if ($envVars["AZURE_OPENAI_MODEL"]) { $envVars["AZURE_OPENAI_MODEL"] } else { "gpt-4.1" }
$EmbModel = if ($envVars["AZURE_OPENAI_EMBEDDING_MODEL"]) { $envVars["AZURE_OPENAI_EMBEDDING_MODEL"] } else { "text-embedding-3-small" }

# リージョンは Resource Group から取得
$Location = az group show --name $ResourceGroup --query location -o tsv

Write-Host "`n=== デプロイ設定 ==="
Write-Host "RESOURCE_GROUP: $ResourceGroup"
Write-Host "APP_NAME:       $AppName"
Write-Host "FUNC_NAME:      $FuncName"
Write-Host "SEARCH_INDEX:   $SearchIndex"
Write-Host ""

Write-Host "🏗️  Function 用 Storage Account を作成（既存の場合はスキップ）..."
az storage account create `
    --resource-group $ResourceGroup `
    --name $FuncStorage `
    --location $Location `
    --sku Standard_LRS `
    --kind StorageV2 `
    --allow-shared-key-access false `
    --public-network-access Enabled `
    --output none 2>$null

Write-Host "🌐 Storage のパブリック網経由アクセスを許可..."
az storage account update `
    --resource-group $ResourceGroup `
    --name $FuncStorage `
    --public-network-access Enabled `
    --default-action Allow `
    --output none

$StorageId = az storage account show `
    --resource-group $ResourceGroup `
    --name $FuncStorage `
    --query id -o tsv

Write-Host "🔑 デプロイ実行ユーザーに Storage Blob Data Contributor を付与..."
$UserOid = az ad signed-in-user show --query id -o tsv
az role assignment create `
    --assignee-object-id $UserOid `
    --assignee-principal-type User `
    --role "Storage Blob Data Contributor" `
    --scope $StorageId `
    --output none 2>$null

# RBAC 反映待ち（最大 60 秒）
Write-Host "⏳ RBAC 反映を待機..."
for ($i = 0; $i -lt 12; $i++) {
    az storage container exists `
        --name app-package `
        --account-name $FuncStorage `
        --auth-mode login `
        --output none 2>$null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 5
}

Write-Host "📦 デプロイパッケージ用コンテナを作成..."
az storage container create `
    --name app-package `
    --account-name $FuncStorage `
    --auth-mode login `
    --output none 2>$null

Write-Host "🌐 Function App '$FuncName' を作成（既存の場合はスキップ）..."
az functionapp create `
    --resource-group $ResourceGroup `
    --name $FuncName `
    --storage-account $FuncStorage `
    --deployment-storage-auth-type SystemAssignedIdentity `
    --deployment-storage-name $FuncStorage `
    --deployment-storage-container-name app-package `
    --flexconsumption-location $Location `
    --runtime python `
    --runtime-version 3.11 `
    --instance-memory 2048 `
    --disable-app-insights true `
    --output none 2>$null

Write-Host "🔑 Function のマネージド ID を有効化し RBAC を割り当て..."
$FuncPrincipalId = az functionapp identity assign `
    --resource-group $ResourceGroup `
    --name $FuncName `
    --query principalId -o tsv

$SearchId = az resource show `
    --resource-group $ResourceGroup `
    --resource-type "Microsoft.Search/searchServices" `
    --name "$Prefix-search" `
    --query id -o tsv

# Function → AI Search: Search Index Data Reader
az role assignment create `
    --assignee-object-id $FuncPrincipalId `
    --assignee-principal-type ServicePrincipal `
    --role "Search Index Data Reader" `
    --scope $SearchId `
    --output none 2>$null

# Function → Function 用 Storage: Storage Blob Data Owner
az role assignment create `
    --assignee-object-id $FuncPrincipalId `
    --assignee-principal-type ServicePrincipal `
    --role "Storage Blob Data Owner" `
    --scope $StorageId `
    --output none 2>$null

Write-Host "⚙️  Function のアプリ設定を反映..."
az functionapp config appsettings set `
    --resource-group $ResourceGroup `
    --name $FuncName `
    --settings `
        AzureWebJobsStorage__accountName=$FuncStorage `
        AzureWebJobsStorage__credential=managedidentity `
        AZURE_SEARCH_ENDPOINT=$($envVars["AZURE_SEARCH_ENDPOINT"]) `
        AZURE_SEARCH_INDEX=$SearchIndex `
    --output none

az functionapp config appsettings delete `
    --resource-group $ResourceGroup `
    --name $FuncName `
    --setting-names AzureWebJobsStorage `
    --output none 2>$null

Write-Host "📦 MCP サーバーを Azure Functions にデプロイ..."
Push-Location (Join-Path $ScriptDir "mcp")
try {
    func azure functionapp publish $FuncName
} finally {
    Pop-Location
}

Write-Host "`n🏗️  App Service Plan を作成（01-rag で作成済みの場合はスキップ）..."
az appservice plan create `
    --resource-group $ResourceGroup `
    --name $PlanName `
    --sku B1 `
    --is-linux `
    --output none 2>$null

Write-Host "🌐 Web App '$AppName' を作成（01-rag で作成済みの場合はスキップ）..."
az webapp create `
    --resource-group $ResourceGroup `
    --plan $PlanName `
    --name $AppName `
    --runtime "PYTHON:3.11" `
    --output none 2>$null

Write-Host "🔑 Web App のマネージド ID を有効化し RBAC を割り当て..."
$AppPrincipalId = az webapp identity assign `
    --resource-group $ResourceGroup `
    --name $AppName `
    --query principalId -o tsv

$FoundryId = az cognitiveservices account show `
    --resource-group $ResourceGroup `
    --name "$Prefix-ai" `
    --query id -o tsv

# App → Foundry: Azure AI User
az role assignment create `
    --assignee-object-id $AppPrincipalId `
    --assignee-principal-type ServicePrincipal `
    --role "Azure AI User" `
    --scope $FoundryId `
    --output none 2>$null

# App → AI Search: Search Index Data Reader
az role assignment create `
    --assignee-object-id $AppPrincipalId `
    --assignee-principal-type ServicePrincipal `
    --role "Search Index Data Reader" `
    --scope $SearchId `
    --output none 2>$null

Write-Host "⚙️  Web App のアプリ設定を反映..."
$McpSystemKey = az functionapp keys list `
    --resource-group $ResourceGroup `
    --name $FuncName `
    --query "systemKeys.mcp_extension" -o tsv
$McpServerUrl = "https://$FuncName.azurewebsites.net/runtime/webhooks/mcp/mcp?code=$McpSystemKey"
az webapp config appsettings set `
    --resource-group $ResourceGroup `
    --name $AppName `
    --settings `
        AZURE_OPENAI_ENDPOINT=$($envVars["AZURE_OPENAI_ENDPOINT"]) `
        AZURE_OPENAI_MODEL=$Model `
        AZURE_OPENAI_EMBEDDING_MODEL=$EmbModel `
        AZURE_SEARCH_ENDPOINT=$($envVars["AZURE_SEARCH_ENDPOINT"]) `
        AZURE_SEARCH_INDEX=$SearchIndex `
        MCP_SERVER_URL=$McpServerUrl `
    --output none

Write-Host "📦 アプリコードをデプロイ..."
$ZipPath = Join-Path $env:TEMP "mcp-app-deploy.zip"
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
