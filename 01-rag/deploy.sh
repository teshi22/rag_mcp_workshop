#!/bin/bash
# 01-rag: 受講生ごとの App Service デプロイスクリプト
# 使い方:
#   bash 01-rag/deploy.sh
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
PLAN_NAME="${PREFIX}-plan"

echo "=== デプロイ設定 ==="
echo "RESOURCE_GROUP: $AZURE_RESOURCE_GROUP"
echo "APP_NAME:       $APP_NAME"
echo "SEARCH_INDEX:   ${AZURE_SEARCH_INDEX:-rag-index}"
echo ""

echo "🏗️  App Service Plan を作成（既存の場合はスキップ）..."
az appservice plan create \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --name "$PLAN_NAME" \
    --sku B1 \
    --is-linux \
    --output none 2>/dev/null || true

echo "🌐 Web App '$APP_NAME' を作成..."
az webapp create \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --plan "$PLAN_NAME" \
    --name "$APP_NAME" \
    --runtime "PYTHON:3.11" \
    --output none

echo "🔑 マネージド ID を有効化し RBAC を割り当て..."
PRINCIPAL_ID=$(az webapp identity assign \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --name "$APP_NAME" \
    --query principalId -o tsv)

FOUNDRY_ID=$(az cognitiveservices account show \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --name "${PREFIX}-ai" \
    --query id -o tsv)

SEARCH_ID=$(az resource show \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --resource-type "Microsoft.Search/searchServices" \
    --name "${PREFIX}-search" \
    --query id -o tsv)

# App → Foundry: Azure AI User
az role assignment create \
    --assignee-object-id "$PRINCIPAL_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "Azure AI User" \
    --scope "$FOUNDRY_ID" \
    --output none 2>/dev/null || true

# App → AI Search: Search Index Data Reader
az role assignment create \
    --assignee-object-id "$PRINCIPAL_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "Search Index Data Reader" \
    --scope "$SEARCH_ID" \
    --output none 2>/dev/null || true

echo "⚙️  アプリ設定を反映..."
az webapp config appsettings set \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --name "$APP_NAME" \
    --settings \
        AZURE_OPENAI_ENDPOINT="$AZURE_OPENAI_ENDPOINT" \
        AZURE_OPENAI_MODEL="${AZURE_OPENAI_MODEL:-gpt-4.1}" \
        AZURE_OPENAI_EMBEDDING_MODEL="${AZURE_OPENAI_EMBEDDING_MODEL:-text-embedding-3-small}" \
        AZURE_SEARCH_ENDPOINT="$AZURE_SEARCH_ENDPOINT" \
        AZURE_SEARCH_INDEX="${AZURE_SEARCH_INDEX:-rag-index}" \
    --output none

echo "📦 アプリコードをデプロイ..."
cd "$SCRIPT_DIR"
zip -rq /tmp/rag-app-deploy.zip app/ -x "*.pyc" "__pycache__/*" ".env" "*.venv*"

az webapp deploy \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --name "$APP_NAME" \
    --src-path /tmp/rag-app-deploy.zip \
    --type zip

az webapp config set \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --name "$APP_NAME" \
    --startup-file "pip install -r app/requirements.txt && python -m streamlit run app/app.py --server.port 8000 --server.address 0.0.0.0" \
    --output none

rm -f /tmp/rag-app-deploy.zip

echo ""
echo "✅ デプロイ完了: https://${APP_NAME}.azurewebsites.net"
