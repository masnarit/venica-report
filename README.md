# Venica 経営管理自動レポートシステム

ShopifyとOPENLOGIのデータを自動集計し、毎朝Gmailで経営レポートを送信するシステムです。
GitHub Actionsで動作するため、PCを起動しておく必要はありません。

---

## できること

| レポート | 頻度 | 内容 |
|---------|------|------|
| 日次経営レポート | 毎朝9時 | 売上KPI・在庫・アラート・AIコメント |
| 週次CSレビュー | 毎週月曜9時 | 問い合わせ分類・前週比 |
| 月次支払集計 | 毎月1日9時 | 請求書PDF解析・費目別集計 |

---

## セットアップ手順

### 必要なもの（事前準備）

- GitHubアカウント（無料）
- Google Workspace（Gmail / Sheets / Drive）
- Shopifyストア
- OPENLOGIアカウント

---

### STEP 1：このリポジトリをGitHubにコピーする

1. GitHubにログイン
2. 画面右上の「＋」→「New repository」をクリック
3. Repository name に `venica-report` と入力
4. 「Create repository」をクリック
5. このフォルダの中身をすべてアップロード（または `git push`）

---

### STEP 2：Google Cloud Projectを作成する

1. [Google Cloud Console](https://console.cloud.google.com/) を開く
2. 「プロジェクトを作成」→ プロジェクト名：`venica-report`
3. 左メニュー「APIとサービス」→「ライブラリ」で以下を有効化：
   - **Google Sheets API**
   - **Gmail API**
   - **Google Drive API**

---

### STEP 3：サービスアカウントを作成する

1. 「APIとサービス」→「認証情報」→「認証情報を作成」→「サービスアカウント」
2. 名前：`venica-report-bot` → 作成して続行 → 完了
3. 作成されたサービスアカウントをクリック
4. 「キー」タブ →「鍵を追加」→「新しい鍵を作成」→「JSON」→ダウンロード
5. ダウンロードした `xxx.json` ファイルをBase64エンコードする：

```bash
# ターミナル（Mac）で実行
base64 -i サービスアカウント.json | tr -d '\n'
```

出力された長い文字列をコピーしておく（後でGitHub Secretsに貼り付ける）

---

### STEP 4：Gmailのドメイン委任を設定する

> この設定はGoogle Workspace管理者が行います。

1. [Google Workspace管理コンソール](https://admin.google.com/) を開く
2. 「セキュリティ」→「APIの制御」→「ドメイン全体の委任を管理」
3. 「新しく追加」をクリック
4. クライアントID：サービスアカウントの「クライアントID」を貼り付け
5. OAuthスコープ（以下をすべてカンマ区切りで入力）：

```
https://www.googleapis.com/auth/gmail.send,https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/drive.readonly
```

---

### STEP 5：Google Sheetsを準備する

1. [Google Sheets](https://sheets.google.com) で新しいスプレッドシートを作成
2. 名前：`venica-master`
3. 以下の5つのシートを作成（シート名は**完全一致**で入力）：

| シート名 | 用途 |
|---------|------|
| `inventory_adjustments` | 在庫調整テーブル（毎日更新） |
| `sales_targets` | 月次売上目標 |
| `product_master` | 商品マスタ・カテゴリ |
| `cs_keywords` | CS分類キーワード |
| `report_log` | 実行ログ（自動書き込み） |

4. `data/` フォルダのサンプルCSVを参考に、各シートにヘッダー行と初期データを入力
5. スプレッドシートのURLから**スプレッドシートID**をコピー：
   ```
   https://docs.google.com/spreadsheets/d/【ここがID】/edit
   ```
6. スプレッドシートを**サービスアカウントのメールアドレスと共有**（編集権限）
   - サービスアカウントのメール：`venica-report-bot@venica-report.iam.gserviceaccount.com` （環境により異なる）

---

### STEP 6：Shopify APIキーを取得する

1. Shopify管理画面 →「設定」→「アプリと販売チャネル」
2. 「アプリを開発」→「カスタムアプリを作成」
3. アプリ名：`venica-report`
4. Admin API アクセストークンに以下の権限を付与：
   - `read_orders`
   - `read_products`
   - `read_inventory`
5. インストール後、**Admin APIアクセストークン**をコピー

---

### STEP 7：GitHub Secretsに設定する

GitHubリポジトリの「Settings」→「Secrets and variables」→「Actions」→「New repository secret」で以下を追加：

| Secret名 | 値 |
|---------|---|
| `SHOPIFY_SHOP_DOMAIN` | `your-shop.myshopify.com` |
| `SHOPIFY_ACCESS_TOKEN` | ShopifyのAPIトークン |
| `OPENLOGI_API_KEY` | OPENLOGIのAPIキー |
| `OPENLOGI_WAREHOUSE_ID` | OPENLOGIの倉庫ID（任意） |
| `GOOGLE_SERVICE_ACCOUNT_JSON_B64` | STEP 3でコピーしたBase64文字列 |
| `GOOGLE_SPREADSHEET_ID` | STEP 5でコピーしたスプレッドシートID |
| `GMAIL_SENDER` | 送信元メールアドレス |
| `GMAIL_RECIPIENTS` | 送信先（複数の場合カンマ区切り） |
| `ANTHROPIC_API_KEY` | Claude APIキー（任意・AIコメント用） |
| `INVOICE_FOLDER_ID` | 請求書PDFのDriveフォルダID（月次集計用） |

---

### STEP 8：動作確認

1. GitHubリポジトリの「Actions」タブを開く
2. 「日次経営レポート」をクリック
3. 右側の「Run workflow」→「Run workflow」をクリック
4. ログが緑色（✓）になれば成功
5. 設定したメールアドレスにレポートが届いていることを確認

---

## 日常の運用方法

### 在庫調整の更新（毎日 or 必要時）

`inventory_adjustments` シートを直接編集するだけです。

| 調整項目 | 更新タイミング |
|---------|-------------|
| POPUP引当 | POPUP開催前後 |
| 撮影貸出 | 撮影前後 |
| PR貸出 | インフルエンサーへ発送/返却時 |
| 卸引当 | 卸受注時 |
| 不良 | 不良品確認時 |
| 返品確認中 | 返品受け取り〜検品完了まで |
| 社内確保 | 展示会・サンプル確保時 |

### 月次目標の更新

`sales_targets` シートに `YYYY-MM` 形式で目標金額を入力します。

```
2026-06  |  4000000  |  6月目標
```

### 売上目標が未設定の場合

目標比の列は「未設定」と表示されます（エラーにはなりません）。

---

## ファイル構成

```
venica-report/
├── .github/
│   └── workflows/
│       ├── daily_report.yml      毎朝9時の日次レポート
│       ├── weekly_cs.yml         毎週月曜のCSレビュー
│       └── monthly_payment.yml   毎月1日の支払集計
├── src/
│   ├── config.py                 環境変数・設定の読み込み
│   ├── shopify_client.py         Shopify APIクライアント
│   ├── openlogi_client.py        OPENLOGI APIクライアント
│   ├── sheets_client.py          Google Sheetsクライアント
│   ├── gmail_client.py           Gmail送信クライアント
│   ├── drive_client.py           Google Drive / PDF解析
│   ├── inventory.py              在庫計算ロジック
│   ├── cs_classifier.py          CS問い合わせ分類
│   ├── ai_comment.py             AIコメント生成（Claude API）
│   ├── daily_report.py           日次レポート本体
│   ├── weekly_cs.py              週次CSレビュー本体
│   └── monthly_payment.py        月次支払集計本体
├── templates/
│   ├── daily_report.html         日次レポートHTMLテンプレート
│   ├── weekly_cs.html            週次CSレポートHTMLテンプレート
│   └── monthly_payment.html      月次支払集計HTMLテンプレート
├── data/
│   ├── sample_inventory_adjustments.csv
│   ├── sample_sales_targets.csv
│   ├── sample_product_master.csv
│   └── sample_cs_keywords.csv
├── docs/
│   └── architecture.md           設計書
├── .env.example                  環境変数サンプル
├── requirements.txt              Pythonライブラリ一覧
└── README.md                     このファイル
```

---

## 在庫計算の仕組み

VenicaではShopifyとOPENLOGIを意図的に非同期運用しています。
そのため、**OPENLOGI在庫を正**として、調整値を差し引いて実販売可能在庫を算出します。

```
実販売可能在庫 = OPENLOGI在庫
              - POPUP引当
              - 撮影貸出
              - PR貸出
              - 卸引当
              - 不良
              - 返品確認中
              - 社内確保
```

Shopify在庫は**参考値・差異チェック**にのみ使用します。

---

## エラーが起きたときの確認手順

### 1. GitHub Actionsのログを確認

「Actions」タブ → 失敗したワークフロー → ログを確認

よくあるエラー：
- `EnvironmentError: 必須の環境変数が設定されていません` → GitHub Secretsの設定漏れ
- `401 Unauthorized` → APIキーが間違っている
- `403 Forbidden` → スプレッドシートの共有設定が未完了

### 2. Google SheetsのログシートでStatusを確認

`report_log` シートの `status` 列が `error` の場合、`message` 列にエラー内容が記録されています。

### 3. よくある問題と対処法

| 症状 | 原因 | 対処 |
|------|------|------|
| メールが届かない | ドメイン委任未設定 | STEP 4を再確認 |
| 在庫が0表示 | OPENLOGI APIキー誤り | OPENLOGIのAPI設定を確認 |
| 目標比が表示されない | sales_targetsに当月未入力 | シートに今月の目標を追加 |
| PDF解析できない | pdfplumber未インストール | monthly_payment.ymlを確認 |

---

## ローカルでテスト実行する場合

```bash
# 1. .envファイルを作成
cp .env.example .env
# .envに各値を入力

# 2. ライブラリインストール
pip install -r requirements.txt

# 3. テスト実行
cd src
python daily_report.py
```

---

## サポート・カスタマイズ

- 送信先メールの変更：GitHub Secrets の `GMAIL_RECIPIENTS` を更新
- 目標金額の変更：Google Sheets の `sales_targets` シートを更新
- 在庫アラート閾値の変更：GitHub の「Variables」（Secrets ではなく）で `STOCK_ALERT_DAYS` を変更
- 新しいCSカテゴリの追加：Google Sheets の `cs_keywords` シートを更新
