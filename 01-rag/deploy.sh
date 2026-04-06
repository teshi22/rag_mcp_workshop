#!/bin/bash
# 01-rag: App Service デプロイスクリプト
# 使い方:
#   export AZURE_RESOURCE_GROUP=rg-ragworkshop
#   export PREFIX=ragws
#   bash 01-rag/deploy.sh

set -euo pipefail

RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:?環境変数 AZURE_RESOURCE_GROUP を設定してください}"
PREFIX="${PREFIX:?環境変数 PREFIX を設定してください}"
APP_NAME="${PREFIX}-app"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🏗️  App Service インフラをデプロイ..."
az deployment group create \
    --resource-group "$RESOURCE_GROUP" \
    --template-file "$REPO_ROOT/00-setup/infra/main.bicep" \
    --parameters prefix="$PREFIX" \
    --parameters deployAppService=true \
    --query "properties.outputs" \
    --output table

echo ""
echo "📦 アプリコードをデプロイ..."
cd "$SCRIPT_DIR"
zip -r /tmp/rag-app-deploy.zip app/ -x "*.pyc" "__pycache__/*" ".env" "*.venv*"

az webapp deploy \
    --resource-group "$RESOURCE_GROUP" \
    --name "$APP_NAME" \
    --src-path /tmp/rag-app-deploy.zip \
    --type zip

az webapp config set \
    --resource-group "$RESOURCE_GROUP" \
    --name "$APP_NAME" \
    --startup-file "pip install -r app/requirements.txt && python -m streamlit run app/app.py --server.port 8000 --server.address 0.0.0.0"

rm -f /tmp/rag-app-deploy.zip

echo ""
echo "✅ デプロイ完了: https://${APP_NAME}.azurewebsites.net"
