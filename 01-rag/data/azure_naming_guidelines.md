# Azure リソース命名規則・利用ガイドライン

## 目的
本ドキュメントは、社内で Azure リソースを作成する際の命名規則および利用ガイドラインを定めるものです。

## リソース命名規則

### 基本フォーマット
```
{プロジェクト略称}-{環境}-{リソース種別}-{連番}
```

### 例
| リソース | 命名例 |
|----------|--------|
| リソースグループ | `rg-myapp-prod` |
| App Service | `app-myapp-prod-001` |
| Azure Functions | `func-myapp-prod-001` |
| Storage Account | `stmyappprod001`（ハイフン不可、24文字以内） |
| Key Vault | `kv-myapp-prod` |
| SQL Database | `sql-myapp-prod` |

### 環境識別子
| 環境 | 識別子 |
|------|--------|
| 本番 | `prod` |
| ステージング | `stg` |
| 開発 | `dev` |
| テスト | `test` |

## 利用可能リージョン
- **本番環境**: Japan East（東日本）を第一候補、Japan West（西日本）を DR 用とする
- **開発・テスト環境**: Japan East または East US 2（コスト最適化のため）
- その他のリージョンを使用する場合はクラウド推進チームの承認が必要

## タグ付けルール（必須）
すべてのリソースに以下のタグを付与すること：

| タグ名 | 値の例 | 説明 |
|--------|--------|------|
| `Project` | `myapp` | プロジェクト名 |
| `Environment` | `prod` | 環境 |
| `Owner` | `yamada@example.com` | 管理責任者 |
| `CostCenter` | `CC-1234` | コストセンター |
| `CreatedDate` | `2026-01-15` | 作成日 |

## リソースグループの方針
- プロジェクト × 環境ごとに 1 リソースグループを作成する
- 例: `rg-myapp-prod`, `rg-myapp-dev`
- リソースグループ間の依存関係は極力避けること
