#!/bin/bash
# Azure App Service デプロイスクリプト
# 注意: Windows から Linux App Service へのデプロイ時、
#        zip 圧縮・展開で失敗する可能性あります。WSL の使用を推奨。

set -e

RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:?環境変数 AZURE_RESOURCE_GROUP を設定してください}"
APP_NAME="${APP_SERVICE_NAME:?環境変数 APP_SERVICE_NAME を設定してください}"

echo "📦 デプロイ用 zip を作成..."
zip -r deploy.zip app/ -x "*.pyc" "__pycache__/*" ".env"

echo "🚀 App Service にデプロイ..."
az webapp deploy \
    --resource-group "$RESOURCE_GROUP" \
    --name "$APP_NAME" \
    --src-path deploy.zip \
    --type zip

echo "⚙️  スタートアップコマンドを設定..."
az webapp config set \
    --resource-group "$RESOURCE_GROUP" \
    --name "$APP_NAME" \
    --startup-file "pip install -r app/requirements.txt && python -m streamlit run app/app.py --server.port 8000 --server.address 0.0.0.0"

rm deploy.zip

echo "✅ デプロイ完了: https://${APP_NAME}.azurewebsites.net"
