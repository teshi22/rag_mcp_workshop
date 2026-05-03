# RAG + MCP Workshop

Azure AI Search × Responses API による RAG 構成と、MCP（Model Context Protocol）を使った AI エージェントパターンのハンズオンです。

## ワークショップの流れ

| # | フォルダ | 対象者 | 内容 |
|---|---------|--------|------|
| 0 | [00-setup](./00-setup/) | 管理者 | **準備編** — Azure 共有リソースのデプロイ |
| 1 | [01-rag](./01-rag/) | 受講生 | **通常 RAG 編** — インデックス作成、RAG アプリの起動・デプロイ |
| 2 | [02-mcp](./02-mcp/) | 受講生 | **MCP 編** — アプリを MCP 対応に更新、Azure Functions で MCP サーバーをデプロイ |

## リソース構成

```mermaid
graph TB
    subgraph Azure["Azure リソースグループ"]
        subgraph Foundry["Microsoft Foundry（AIServices）"]
            GPT["GPT-4.1"]:::shared
            Emb["text-embedding-3-small"]:::shared
        end

        subgraph StorageAccount["Azure Blob Storage"]
            Container["documents-&lt;student-id&gt;"]:::per_student
        end

        subgraph SearchService["Azure AI Search"]
            Index["rag-index-&lt;student-id&gt;"]:::per_student
        end

        subgraph AppServicePlan["App Service Plan（&lt;prefix&gt;-&lt;student-id&gt;-plan / Linux B1）"]
            WebApp["Web App<br/>&lt;prefix&gt;-&lt;student-id&gt;-app<br/>Python 3.11 / Streamlit"]:::per_student
        end

        subgraph FuncPlan["Functions Plan"]
            Func["Azure Functions<br/>MCP サーバー"]:::per_student
        end
    end

    User["ユーザー"]
    Learn["Microsoft Learn MCP<br/>learn.microsoft.com/api/mcp"]

    Container -- "インデクサー<br/>チャンク分割+ベクトル化" --> Index
    Index -. "ベクトル化" .-> Emb

    User --> WebApp
    WebApp -- "01-rag: ハイブリッド検索 +<br/>セマンティックリランカー" --> Index
    WebApp -- "Responses API" --> GPT
    WebApp -. "02-mcp: MCP Client" .-> Func
    WebApp -. "02-mcp: MCP Client" .-> Learn
    Func -- "検索クエリ" --> Index

    classDef per_student fill:#ffd6a5,stroke:#e8890c,color:#000
    classDef shared fill:#d6e4ff,stroke:#4a7dff,color:#000

    style Azure fill:#f0f0f0,stroke:#999,color:#000
    style Foundry fill:#d6e4ff,stroke:#4a7dff,color:#000
    style StorageAccount fill:#d6e4ff,stroke:#4a7dff,color:#000
    style SearchService fill:#d6e4ff,stroke:#4a7dff,color:#000
    style AppServicePlan fill:#ffd6a5,stroke:#e8890c,color:#000
    style FuncPlan fill:#d6e4ff,stroke:#4a7dff,color:#000
```

- 🔵 青 = 共有リソース（管理者が 00-setup でデプロイ）
- 🟠 オレンジ = 受講生ごとに作成（`.env` の `STUDENT_ID` で分離）

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
