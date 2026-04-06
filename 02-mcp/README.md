# 02 — MCP 編

01-rag のアプリを MCP（Model Context Protocol）対応に更新し、Azure Functions で MCP サーバーをデプロイします。
社内ドキュメントと Microsoft 公式ドキュメントの両方を活用するエージェントパターンを体験します。

## 構成

```
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
```

## 前提条件

- [00-setup](../00-setup/) と [01-rag](../01-rag/) が完了していること
- Azure Functions Core Tools v4+

## ローカルで動かす

### 1. MCP サーバー（Azure Functions）を起動

```bash
cd 02-mcp/mcp
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# local.settings.json に AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_INDEX を設定
func start
```

### 2. Streamlit アプリを起動

```bash
cd 02-mcp/app
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

streamlit run app.py
```

サイドバーで「AI エージェント + MCP」を選択してください。

## Azure にデプロイする

```bash
export AZURE_RESOURCE_GROUP=rg-ragworkshop
export PREFIX=ragws
bash 02-mcp/deploy.sh
```

`deploy.sh` は以下を実行します:

1. Azure Functions のインフラを追加デプロイ
2. MCP サーバーコードを Azure Functions にデプロイ
3. アプリコードを MCP 対応版に更新デプロイ

## MCP サーバー一覧

| MCP サーバー | 用途 | エンドポイント |
|---|---|---|
| Azure Functions（自作） | 社内ドキュメント検索 | `http://localhost:7071/runtime/webhooks/mcp/mcp`（ローカル） |
| Microsoft Learn（外部） | 公式ドキュメント検索 | `https://learn.microsoft.com/api/mcp` |

## 試してみる

- 「社内の Azure 命名規則を教えて」（社内ドキュメント検索）
- 「Azure Functions の Python でのデプロイ方法は？」（公式ドキュメント検索）
- 「社内のセキュリティポリシーと Azure のベストプラクティスを比較して」（両方を横断）
