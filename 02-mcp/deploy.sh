#!/bin/bash
# 02-mcp: 受講生ごとの Azure Functions (MCP) + App Service デプロイスクリプト
# 使い方:
#   bash 02-mcp/deploy.sh
# .env に必要な値がすべて設定されていること

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "❌ .env ファイルが見つかりません: $ENV_FILE"
    exit 1
fi

# .env を読み込み
set -a
source "$ENV_FILE"
set +a

# 必須変数チェック
: "${AZURE_RESOURCE_GROUP:?❌ .env に AZURE_RESOURCE_GROUP を設定してください}"
: "${PREFIX:?❌ .env に PREFIX を設定してください}"
: "${STUDENT_ID:?❌ .env に STUDENT_ID を設定してください}"
: "${AZURE_OPENAI_ENDPOINT:?❌ .env に AZURE_OPENAI_ENDPOINT を設定してください}"
: "${AZURE_SEARCH_ENDPOINT:?❌ .env に AZURE_SEARCH_ENDPOINT を設定してください}"

APP_NAME="${PREFIX}-${STUDENT_ID}-app"
PLAN_NAME="${PREFIX}-${STUDENT_ID}-plan"  # 01-rag で作成済みのものを再利用
FUNC_NAME="${PREFIX}-${STUDENT_ID}-func"
FUNC_STORAGE="$(echo "${PREFIX}${STUDENT_ID}funcstor" | tr -d '-' | tr '[:upper:]' '[:lower:]')"

# リージョンは Resource Group から取得
LOCATION=$(az group show --name "$AZURE_RESOURCE_GROUP" --query location -o tsv)

echo "=== デプロイ設定 ==="
echo "RESOURCE_GROUP: $AZURE_RESOURCE_GROUP"
echo "APP_NAME:       $APP_NAME"
echo "FUNC_NAME:      $FUNC_NAME"
echo "SEARCH_INDEX:   ${AZURE_SEARCH_INDEX:-rag-index}"
echo ""

echo "🏗️  Function 用 Storage Account を作成（既存の場合はスキップ）..."
az storage account create \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --name "$FUNC_STORAGE" \
    --location "$LOCATION" \
    --sku Standard_LRS \
    --kind StorageV2 \
    --allow-shared-key-access false \
    --output none 2>/dev/null || true

STORAGE_ID=$(az storage account show \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --name "$FUNC_STORAGE" \
    --query id -o tsv)

echo "🔑 デプロイ実行ユーザーに Storage Blob Data Contributor を付与..."
USER_OID=$(az ad signed-in-user show --query id -o tsv)
az role assignment create \
    --assignee-object-id "$USER_OID" \
    --assignee-principal-type User \
    --role "Storage Blob Data Contributor" \
    --scope "$STORAGE_ID" \
    --output none 2>/dev/null || true

# RBAC 反映待ち（最大 60 秒）
echo "⏳ RBAC 反映を待機..."
for i in {1..12}; do
    if az storage container exists \
        --name app-package \
        --account-name "$FUNC_STORAGE" \
        --auth-mode login \
        --output none 2>/dev/null; then
        break
    fi
    sleep 5
done

echo "📦 デプロイパッケージ用コンテナを作成..."
az storage container create \
    --name app-package \
    --account-name "$FUNC_STORAGE" \
    --auth-mode login \
    --output none 2>/dev/null || true

echo "🌐 Function App '$FUNC_NAME' を作成（既存の場合はスキップ）..."
az functionapp create \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --name "$FUNC_NAME" \
    --storage-account "$FUNC_STORAGE" \
    --deployment-storage-auth-type SystemAssignedIdentity \
    --deployment-storage-name "$FUNC_STORAGE" \
    --deployment-storage-container-name app-package \
    --flexconsumption-location "$LOCATION" \
    --runtime python \
    --runtime-version 3.11 \
    --instance-memory 2048 \
    --disable-app-insights true \
    --output none 2>/dev/null || true

echo "🔑 Function のマネージド ID を有効化し RBAC を割り当て..."
FUNC_PRINCIPAL_ID=$(az functionapp identity assign \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --name "$FUNC_NAME" \
    --query principalId -o tsv)

SEARCH_ID=$(az resource show \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --resource-type "Microsoft.Search/searchServices" \
    --name "${PREFIX}-search" \
    --query id -o tsv)

# Function → AI Search: Search Index Data Reader
az role assignment create \
    --assignee-object-id "$FUNC_PRINCIPAL_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "Search Index Data Reader" \
    --scope "$SEARCH_ID" \
    --output none 2>/dev/null || true

# Function → Function 用 Storage: Storage Blob Data Owner
az role assignment create \
    --assignee-object-id "$FUNC_PRINCIPAL_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "Storage Blob Data Owner" \
    --scope "$STORAGE_ID" \
    --output none 2>/dev/null || true

echo "⚙️  Function のアプリ設定を反映..."
az functionapp config appsettings set \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --name "$FUNC_NAME" \
    --settings \
        AzureWebJobsStorage__accountName="$FUNC_STORAGE" \
        AzureWebJobsStorage__credential=managedidentity \
        AZURE_SEARCH_ENDPOINT="$AZURE_SEARCH_ENDPOINT" \
        AZURE_SEARCH_INDEX="${AZURE_SEARCH_INDEX:-rag-index}" \
    --output none

az functionapp config appsettings delete \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --name "$FUNC_NAME" \
    --setting-names AzureWebJobsStorage \
    --output none 2>/dev/null || true

echo "📦 MCP サーバーを Azure Functions にデプロイ..."
cd "$SCRIPT_DIR/mcp"
func azure functionapp publish "$FUNC_NAME"

echo ""
echo "🏗️  App Service Plan を作成（01-rag で作成済みの場合はスキップ）..."
az appservice plan create \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --name "$PLAN_NAME" \
    --sku B1 \
    --is-linux \
    --output none 2>/dev/null || true

echo "🌐 Web App '$APP_NAME' を作成（01-rag で作成済みの場合はスキップ）..."
az webapp create \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --plan "$PLAN_NAME" \
    --name "$APP_NAME" \
    --runtime "PYTHON:3.11" \
    --output none 2>/dev/null || true

echo "🔑 Web App のマネージド ID を有効化し RBAC を割り当て..."
APP_PRINCIPAL_ID=$(az webapp identity assign \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --name "$APP_NAME" \
    --query principalId -o tsv)

FOUNDRY_ID=$(az cognitiveservices account show \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --name "${PREFIX}-ai" \
    --query id -o tsv)

# App → Foundry: Azure AI User
az role assignment create \
    --assignee-object-id "$APP_PRINCIPAL_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "Azure AI User" \
    --scope "$FOUNDRY_ID" \
    --output none 2>/dev/null || true

# App → AI Search: Search Index Data Reader
az role assignment create \
    --assignee-object-id "$APP_PRINCIPAL_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "Search Index Data Reader" \
    --scope "$SEARCH_ID" \
    --output none 2>/dev/null || true

echo "⚙️  Web App のアプリ設定を反映..."
MCP_SYSTEM_KEY=$(az functionapp keys list \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --name "$FUNC_NAME" \
    --query "systemKeys.mcp_extension" -o tsv)
MCP_SERVER_URL="https://${FUNC_NAME}.azurewebsites.net/runtime/webhooks/mcp/mcp?code=${MCP_SYSTEM_KEY}"
az webapp config appsettings set \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --name "$APP_NAME" \
    --settings \
        AZURE_OPENAI_ENDPOINT="$AZURE_OPENAI_ENDPOINT" \
        AZURE_OPENAI_MODEL="${AZURE_OPENAI_MODEL:-gpt-4.1}" \
        AZURE_OPENAI_EMBEDDING_MODEL="${AZURE_OPENAI_EMBEDDING_MODEL:-text-embedding-3-small}" \
        AZURE_SEARCH_ENDPOINT="$AZURE_SEARCH_ENDPOINT" \
        AZURE_SEARCH_INDEX="${AZURE_SEARCH_INDEX:-rag-index}" \
        MCP_SERVER_URL="$MCP_SERVER_URL" \
    --output none

echo "📦 アプリコードをデプロイ..."
cd "$SCRIPT_DIR"
zip -rq /tmp/mcp-app-deploy.zip app/ -x "*.pyc" "__pycache__/*" ".env" "*.venv*"

az webapp deploy \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --name "$APP_NAME" \
    --src-path /tmp/mcp-app-deploy.zip \
    --type zip

az webapp config set \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --name "$APP_NAME" \
    --startup-file "pip install -r app/requirements.txt && python -m streamlit run app/app.py --server.port 8000 --server.address 0.0.0.0" \
    --output none

rm -f /tmp/mcp-app-deploy.zip

echo ""
echo "✅ デプロイ完了: https://${APP_NAME}.azurewebsites.net"
