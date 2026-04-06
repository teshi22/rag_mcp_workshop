#!/bin/bash
# 02-mcp: App Service + Azure Functions デプロイスクリプト
# 使い方:
#   export AZURE_RESOURCE_GROUP=rg-ragworkshop
#   export PREFIX=ragws
#   bash 02-mcp/deploy.sh

set -euo pipefail

RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:?環境変数 AZURE_RESOURCE_GROUP を設定してください}"
PREFIX="${PREFIX:?環境変数 PREFIX を設定してください}"
APP_NAME="${PREFIX}-app"
FUNC_NAME="${PREFIX}-func"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🏗️  Azure Functions インフラを追加デプロイ..."
az deployment group create \
    --resource-group "$RESOURCE_GROUP" \
    --template-file "$REPO_ROOT/00-setup/infra/main.bicep" \
    --parameters prefix="$PREFIX" \
    --parameters deployAppService=true \
    --parameters deployFunctions=true \
    --query "properties.outputs" \
    --output table

echo ""
echo "📦 MCP サーバーを Azure Functions にデプロイ..."
cd "$SCRIPT_DIR/mcp"
func azure functionapp publish "$FUNC_NAME"

echo ""
echo "📦 アプリコードを MCP 対応版に更新..."
cd "$SCRIPT_DIR"
zip -r /tmp/mcp-app-deploy.zip app/ -x "*.pyc" "__pycache__/*" ".env" "*.venv*"

az webapp deploy \
    --resource-group "$RESOURCE_GROUP" \
    --name "$APP_NAME" \
    --src-path /tmp/mcp-app-deploy.zip \
    --type zip

az webapp config set \
    --resource-group "$RESOURCE_GROUP" \
    --name "$APP_NAME" \
    --startup-file "pip install -r app/requirements.txt && python -m streamlit run app/app.py --server.port 8000 --server.address 0.0.0.0"

rm -f /tmp/mcp-app-deploy.zip

echo ""
echo "✅ デプロイ完了"
echo "   App: https://${APP_NAME}.azurewebsites.net"
echo "   MCP: https://${FUNC_NAME}.azurewebsites.net/runtime/webhooks/mcp/mcp"
