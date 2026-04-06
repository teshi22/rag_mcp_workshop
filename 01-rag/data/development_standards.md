# 開発標準ガイドライン

## 目的
Azure 上のアプリケーション開発における共通ルールを定めます。

## IaC（Infrastructure as Code）

### Bicep テンプレート規約
- Azure リソースの作成は必ず Bicep テンプレートで行うこと（手動作成禁止）
- テンプレートは `infra/` ディレクトリに配置
- パラメータファイル（`.bicepparam`）で環境ごとの値を管理
- シークレットはパラメータに直接記載せず、Key Vault 参照を使用

### モジュール構成
```
infra/
  main.bicep           エントリーポイント
  main.bicepparam      パラメータファイル
  modules/
    app-service.bicep   App Service モジュール
    database.bicep      データベースモジュール
    monitoring.bicep    監視モジュール
```

## CI/CD パイプライン

### GitHub Actions 標準構成
- すべてのプロジェクトで GitHub Actions を使用
- `main` ブランチへのマージで本番デプロイ
- `develop` ブランチへのマージでステージングデプロイ

### 必須ステップ
1. **Lint**: コードの静的解析
2. **Test**: ユニットテスト（カバレッジ 80% 以上）
3. **Build**: アプリケーションビルド
4. **Bicep Validate**: `az deployment group validate` によるテンプレート検証
5. **Deploy**: 環境へのデプロイ
6. **Smoke Test**: デプロイ後の疎通確認

### ブランチ戦略
- Git Flow をベースとする
- `main`: 本番環境に対応
- `develop`: 開発統合ブランチ
- `feature/*`: 機能開発ブランチ
- Pull Request 必須、レビュアー 1 名以上

## アプリケーション開発

### 認証の実装
- `DefaultAzureCredential` を使用（ローカル: az login、Azure: マネージド ID）
- ハードコードされた認証情報は一切禁止
- 環境変数にシークレットを直接設定しない（Key Vault 参照を使用）

### ログ出力
- 構造化ログ（JSON 形式）を推奨
- ログレベル: ERROR / WARN / INFO / DEBUG
- 本番環境は INFO 以上を出力
- Application Insights SDK を統合し、分散トレーシングを有効化

### エラーハンドリング
- 外部サービス呼び出しにはリトライ（指数バックオフ）を実装
- タイムアウトを必ず設定（デフォルト: 30 秒）
- エラーレスポンスにスタックトレースを含めないこと

## コードレビュー基準
- セキュリティ: 認証情報のハードコード、SQL インジェクション等のチェック
- パフォーマンス: N+1 クエリ、不要なループの有無
- 可読性: 適切な命名、コメントの過不足
- テスト: 新規機能にはテストが必須
