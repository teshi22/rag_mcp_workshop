# RAG + MCP Workshop

Azure AI Search × Responses API による最小限の RAG 構成サンプルです。

## 構成図

```
ユーザー → Streamlit (App Service)
              ├→ Azure AI Search（ハイブリッド検索 + セマンティックリランカー）
              └→ Microsoft Foundry（Responses API で回答生成）

Blob Storage → [インデクサー] → Azure AI Search
               (チャンク分割 + ベクトル化)
```

## ディレクトリ構成

```
app/
  app.py                Streamlit RAG アプリ（メイン）
  requirements.txt      アプリ用パッケージ
scripts/
  create_index.py       AI Search インデックス・インデクサー作成
  upload_docs.py        Blob Storage へドキュメントアップロード
  deploy.sh             App Service デプロイスクリプト
  requirements.txt      スクリプト用パッケージ
data/                   サンプルドキュメント
infra/
  main.bicep            Azure リソース一括デプロイ（Bicep）
  main.bicepparam       パラメータファイル
```

## 前提条件

- Python 3.11+
- Azure CLI（`az login` 済み）
- Azure サブスクリプション（Contributor 権限）

## 1. インフラデプロイ

```bash
# リソースグループ作成
az group create -n rg-ragworkshop -l eastus2

# デプロイ（ローカル開発用 RBAC 付き）
az deployment group create \
  -g rg-ragworkshop \
  -f infra/main.bicep \
  -p prefix=ragws \
  -p foundryLocation=eastus2 \
  -p userPrincipalId=$(az ad signed-in-user show --query id -o tsv)
```

> `infra/main.bicepparam` を編集してパラメータファイルで渡すことも可能です。
> Foundry のモデルが利用可能なリージョンは `foundryLocation` パラメータで指定できます。

## 2. スクリプト実行（インデックス作成）

```bash
# 環境変数（デプロイ出力を参考に .env を作成）
cp .env.sample .env
# .env を編集

# 仮想環境の作成・有効化
cd scripts
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# ドキュメントをアップロード
python upload_docs.py

# AI Search インデックス作成
python create_index.py
```

## 3. アプリ起動

```bash
# 仮想環境の作成・有効化
cd app
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 起動
streamlit run app.py
```

## 認証

`DefaultAzureCredential` を使用（API キー不要）:

| 環境 | 認証方式 |
|------|----------|
| ローカル開発 | `az login` の資格情報 |
| Azure App Service | システム割り当てマネージド ID |

## ワークショップテーマ

| テーマ | 内容 |
|--------|------|
| ① RAG 基盤 | 本サンプルで実装。検索 → プロンプト組立 → 回答生成の流れを理解 |
| ② MCP 連携 | Azure Functions で MCP サーバーを実装し、エージェントパターンを理解（後日追加） |
