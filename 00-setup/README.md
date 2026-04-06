# 00 — 準備編

Azure リソースのデプロイを行います。

## 前提条件

- Azure CLI（`az login` 済み）
- Azure サブスクリプション（Contributor 権限）

## 1. インフラデプロイ

```bash
# リソースグループ作成
az group create -n rg-ragworkshop -l eastus2

# デプロイ（ローカル開発用 RBAC 付き）
az deployment group create \
  -g rg-ragworkshop \
  -f 00-setup/infra/main.bicep \
  -p prefix=ragws \
  -p foundryLocation=eastus2 \
  -p userPrincipalId=$(az ad signed-in-user show --query id -o tsv)
```

> `foundryLocation` はモデルが利用可能なリージョンを指定してください。

## 2. 環境変数の設定

```bash
cp .env.sample .env
# デプロイ出力を参考に .env を編集
```

## 作成されるリソース

| リソース | 用途 |
|----------|------|
| Microsoft Foundry (AIServices) | GPT-4o / Embedding モデル |
| Azure AI Search | ハイブリッド検索 + セマンティックリランカー |
| Azure Blob Storage | ドキュメント保管 |

準備が完了したら **[01-rag](../01-rag/)** に進んでください。
