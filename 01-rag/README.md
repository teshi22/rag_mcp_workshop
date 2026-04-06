# 01 — 通常 RAG 編

Azure AI Search × Responses API による RAG（検索拡張生成）アプリを動かします。

## 構成

```
Blob Storage → [インデクサー] → Azure AI Search
               (チャンク分割 + ベクトル化)

ユーザー → Streamlit (App Service)
              ├→ Azure AI Search（ハイブリッド検索 + セマンティックリランカー）
              └→ Microsoft Foundry（Responses API で回答生成）
```

## 1. インデックス作成

```bash
cd 01-rag/scripts
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# ドキュメントをアップロード
python upload_docs.py

# AI Search インデックス作成
python create_index.py
```

## 2. ローカルで動かす

```bash
cd 01-rag/app
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

streamlit run app.py
```

> ルートの `.env` に環境変数が設定されている必要があります。

## 3. Azure にデプロイする

```bash
export AZURE_RESOURCE_GROUP=rg-ragworkshop
export PREFIX=ragws
bash 01-rag/deploy.sh
```

`deploy.sh` は以下を実行します:

1. App Service のインフラを追加デプロイ（Bicep `deployAppService=true`）
2. アプリコードを App Service に zip デプロイ

デプロイ完了後、`https://<PREFIX>-app.azurewebsites.net` でアクセスできます。

## 試してみる

- 「Azure リソースの命名規則を教えてください」
- 「セキュリティポリシーの概要を教えて」
- 「インシデント発生時の対応フローは？」

完了したら **[02-mcp](../02-mcp/)** に進んでください。
