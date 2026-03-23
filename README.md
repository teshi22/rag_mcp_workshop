# RAG + MCP Workshop

Azure AI Search × Responses API による RAG 構成と、MCP（Model Context Protocol）を使った AI エージェントパターンのサンプルです。

## 構成図

```
[RAG モード]
ユーザー → Streamlit (App Service)
              ├→ Azure AI Search（ハイブリッド検索 + セマンティックリランカー）
              └→ Microsoft Foundry（Responses API で回答生成）

[AI エージェント + MCP モード — マルチ MCP サーバー]
ユーザー → Streamlit → Responses API（function tools 付き）
                            ↓ tool call
                       MCP Client (mcp SDK)
                       ┌────────┴────────┐
          Azure Functions MCP Server    Microsoft Learn MCP
          (社内ドキュメント検索)          (公式ドキュメント検索)
                ↓                             ↓
          Azure AI Search           learn.microsoft.com/api/mcp
                            ↑ tool results
                       Responses API（続行）→ ユーザー

Blob Storage → [インデクサー] → Azure AI Search
               (チャンク分割 + ベクトル化)
```

## ディレクトリ構成

```
app/
  app.py                Streamlit アプリ（RAG / Agent+MCP 切替対応）
  requirements.txt      アプリ用パッケージ
mcp/
  function_app.py       Azure Functions MCP サーバー（検索ツール）
  host.json             Functions + MCP 拡張設定
  requirements.txt      MCP サーバー用パッケージ
  local.settings.json   ローカル開発用設定
scripts/
  create_index.py       AI Search インデックス・インデクサー作成
  upload_docs.py        Blob Storage へドキュメントアップロード
  deploy.sh             App Service デプロイスクリプト
  requirements.txt      スクリプト用パッケージ
data/                   サンプル社内ドキュメント（Azure 運用ガイドライン等）
infra/
  main.bicep            Azure リソース一括デプロイ（Bicep）
  main.bicepparam       パラメータファイル
```

## 前提条件

- Python 3.11+
- Azure CLI（`az login` 済み）
- Azure サブスクリプション（Contributor 権限）
- Azure Functions Core Tools v4+（MCP サーバーのローカル実行に必要）

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

## 3. アプリ起動（RAG モード）

```bash
# 仮想環境の作成・有効化
cd app
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 起動
streamlit run app.py
```

サイドバーで「RAG」モードを選択すると、AI Search への直接検索 → Responses API による回答生成が行われます。

## 3.5. MCP サーバー起動（Agent + MCP モード）

Agent + MCP モードでは以下 2 つの MCP サーバーを利用します。

| MCP サーバー | 用途 | エンドポイント |
|---|---|---|
| Azure Functions（自作） | 社内ドキュメント検索 | `http://localhost:7071/runtime/webhooks/mcp/mcp`（ローカル）<br>Azure Functions URL（デプロイ後） |
| Microsoft Learn（外部） | 公式ドキュメント検索 | `https://learn.microsoft.com/api/mcp`（認証不要） |

### Azure Functions MCP サーバーのローカル起動

```bash
# 仮想環境の作成・有効化
cd mcp
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# local.settings.json に環境変数を設定
# AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_INDEX を .env と同じ値に設定

# MCP サーバー起動
func start
```

Microsoft Learn MCP はパブリックエンドポイントのため、起動不要です。

Streamlit アプリのサイドバーで「AI エージェント + MCP」を選択すると、Responses API がエージェントとして両方の MCP ツールを呼び出し、社内ルールと公式ドキュメントを組み合わせて回答を生成します。

## 4. App Service / Functions へデプロイ

インフラデプロイ時にパラメータを指定すると、App Service や Azure Functions が一括作成されます。

```bash
az deployment group create \
  -g rg-ragworkshop \
  -f infra/main.bicep \
  -p prefix=ragws \
  -p foundryLocation=eastus2 \
  -p deployAppService=true \
  -p deployFunctions=true
```

アプリコードのデプロイは `scripts/deploy.sh` で行います。

```bash
export AZURE_RESOURCE_GROUP=rg-ragworkshop
export APP_SERVICE_NAME=ragws-app
bash scripts/deploy.sh
```

Azure Functions（MCP サーバー）のデプロイ:

```bash
cd mcp
func azure functionapp publish ragws-func
```

## 認証

`DefaultAzureCredential` を使用（API キー不要）:

| 環境 | 認証方式 |
|------|----------|
| ローカル開発 | `az login` の資格情報 |
| Azure App Service | システム割り当てマネージド ID |
| Azure Functions | システム割り当てマネージド ID |

## ワークショップテーマ

| テーマ | 内容 |
|--------|------|
| ① RAG 基盤 | 検索 → プロンプト組立 → 回答生成の流れを理解。Streamlit の「RAG」モードで体験 |
| ② MCP 連携 | Azure Functions で自作 MCP サーバーを実装し、外部 MCP（Microsoft Learn）と組み合わせたマルチ MCP エージェントパターンを理解。「AI エージェント + MCP」モードで体験 |

### ② MCP 連携の質問例

- **社内ドキュメント検索**: 「Azure リソースの命名規則を教えて」「セキュリティポリシーの概要は？」
- **公式ドキュメント検索**: 「Azure Functions の Python でのデプロイ方法は？」
- **両方を横断**: 「社内の命名規則と Azure の公式推奨を比較して」
