# RAG + MCP Workshop

Azure AI Search × Responses API による RAG 構成と、MCP（Model Context Protocol）を使った AI エージェントパターンのハンズオンです。

## ワークショップの流れ

| # | フォルダ | 内容 |
|---|---------|------|
| 0 | [00-setup](./00-setup/) | **準備編** — Azure リソースのデプロイ、ドキュメントアップロード、インデックス作成 |
| 1 | [01-rag](./01-rag/) | **通常 RAG 編** — AI Search × Responses API による検索拡張生成。App Service へのデプロイも実施 |
| 2 | [02-mcp](./02-mcp/) | **MCP 編** — Azure Functions で MCP サーバーを構築し、マルチ MCP エージェントパターンを体験 |

## 全体構成図

```
[01-rag: RAG モード]
ユーザー → Streamlit (App Service)
              ├→ Azure AI Search（ハイブリッド検索 + セマンティックリランカー）
              └→ Microsoft Foundry（Responses API で回答生成）

[02-mcp: AI エージェント + MCP モード]
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

- Python 3.11+
- Azure CLI（`az login` 済み）
- Azure サブスクリプション（Contributor 権限）
- Azure Functions Core Tools v4+（MCP 編で使用）

## 認証

`DefaultAzureCredential` を使用（API キー不要）:

| 環境 | 認証方式 |
|------|----------|
| ローカル開発 | `az login` の資格情報 |
| Azure App Service | システム割り当てマネージド ID |
| Azure Functions | システム割り当てマネージド ID |
