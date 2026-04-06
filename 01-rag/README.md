# 01 — 通常 RAG 編

Azure AI Search × Responses API による RAG（検索拡張生成）アプリを動かします。

## 構成

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

        subgraph AppServicePlan["App Service Plan（&lt;prefix&gt;-plan / Linux B1）"]
            WebApp["Web App<br/>&lt;prefix&gt;-&lt;student-id&gt;-app<br/>Python 3.11 / Streamlit"]:::per_student
        end
    end

    User["ユーザー"]

    Container -- "インデクサー<br/>チャンク分割+ベクトル化" --> Index
    Index -. "ベクトル化" .-> Emb

    User --> WebApp
    WebApp -- "ハイブリッド検索 +<br/>セマンティックリランカー" --> Index
    WebApp -- "Responses API" --> GPT

    classDef per_student fill:#ffd6a5,stroke:#e8890c,color:#000
    classDef shared fill:#d6e4ff,stroke:#4a7dff,color:#000

    style Azure fill:#f0f0f0,stroke:#999,color:#000
    style Foundry fill:#d6e4ff,stroke:#4a7dff,color:#000
    style StorageAccount fill:#d6e4ff,stroke:#4a7dff,color:#000
    style SearchService fill:#d6e4ff,stroke:#4a7dff,color:#000
    style AppServicePlan fill:#d6e4ff,stroke:#4a7dff,color:#000
```

- 🔵 青 = 共有リソース（管理者がデプロイ）
- 🟠 オレンジ = 受講生ごとに作成

## 1. 環境変数の設定

リポジトリルートに `.env` ファイルを作成し、以下の値を設定してください。
インフラ共通の値は管理者から提供されます。`AZURE_SEARCH_INDEX` は **受講生ごとにユニークな値** を設定してください。

```bash
cp .env.sample .env
```

| 変数 | 説明 | 備考 |
|------|------|------|
| `AZURE_OPENAI_ENDPOINT` | Foundry のエンドポイント | 管理者から提供 |
| `AZURE_OPENAI_MODEL` | チャットモデルのデプロイ名 | 管理者から提供 |
| `AZURE_OPENAI_EMBEDDING_MODEL` | Embedding モデルのデプロイ名 | 管理者から提供 |
| `AZURE_SEARCH_ENDPOINT` | AI Search のエンドポイント | 管理者から提供 |
| `AZURE_SEARCH_INDEX` | 検索インデックス名 | **受講生ごとにユニーク**（例: `rag-index-<student-id>`） |
| `AZURE_STORAGE_ACCOUNT_NAME` | Storage アカウント名 | 管理者から提供 |
| `AZURE_STORAGE_CONTAINER` | Blob コンテナ名 | **受講生ごとにユニーク**（例: `documents-<student-id>`） |
| `AZURE_SUBSCRIPTION_ID` | サブスクリプション ID | 管理者から提供 |
| `AZURE_RESOURCE_GROUP` | リソースグループ名 | 管理者から提供 |
| `PREFIX` | インフラのプレフィックス | 管理者から提供 |
| `STUDENT_ID` | 受講生の識別子 | **受講生ごとにユニーク**（例: `tk01`） |

## 2. インデックス作成

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

## 3. ローカルで動かす

```bash
cd 01-rag/app
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

streamlit run app.py
```

## 4. Azure にデプロイする

`.env` の設定がすべて完了していれば、スクリプトを実行するだけでデプロイできます。

### Linux / macOS

```bash
bash 01-rag/deploy.sh
```

### Windows (PowerShell)

```powershell
.\01-rag\deploy.ps1
```

デプロイスクリプトは以下を実行します:

1. 共有の App Service Plan を作成（初回のみ）
2. 受講生ごとの Web App `<prefix>-<student-id>-app` を作成
3. `.env` の設定値をアプリ設定に反映
4. アプリコードを zip デプロイ

デプロイ完了後、`https://<prefix>-<student-id>-app.azurewebsites.net` でアクセスできます。

## 試してみる

- 「Azure リソースの命名規則を教えてください」
- 「セキュリティポリシーの概要を教えて」
- 「インシデント発生時の対応フローは？」

完了したら **[02-mcp](../02-mcp/)** に進んでください。
