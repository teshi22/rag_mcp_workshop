# 00 — 準備編

Azure リソースのデプロイを行います。

## 前提条件

- Azure CLI（`az login` 済み）
- Azure サブスクリプション（Contributor 権限）

## ユーザー設定値

以下の値をご自身の環境に合わせて決めてから、手順に進んでください。

| 変数 | 説明 | 例 |
|------|------|----|
| `<resource-group>` | リソースグループ名 | `rg-ragworkshop` |
| `<location>` | リソースグループのリージョン | `japaneast` |
| `<prefix>` | リソース名のプレフィックス（**グローバルで一意**にすること） | `ragws-tk01` |
| `<foundry-location>` | Foundry（モデル）のリージョン | `japaneast` |

> **`<prefix>` について** — Storage アカウント名はグローバルで一意である必要があるため、自分のイニシャルや数字を付けてください。英小文字・数字・ハイフンのみ使用可能です。

## 1. インフラデプロイ

```bash
# リソースグループ作成
az group create -n <resource-group> -l <location>

# デプロイ（ローカル開発用 RBAC 付き）
az deployment group create \
  -g <resource-group> \
  -f 00-setup/infra/main.bicep \
  -p prefix=<prefix> \
  -p foundryLocation=<foundry-location> \
  -p userPrincipalId=$(az ad signed-in-user show --query id -o tsv)
```

## 2. 環境変数の設定

```bash
cp .env.sample .env
# デプロイ出力を参考に .env を編集
```

## 作成されるリソース

| リソース | 用途 |
|----------|------|
| Microsoft Foundry (AIServices) | GPT-4.1 / Embedding モデル |
| Azure AI Search | ハイブリッド検索 + セマンティックリランカー |
| Azure Blob Storage | ドキュメント保管 |

準備が完了したら **[01-rag](../01-rag/)** に進んでください。
