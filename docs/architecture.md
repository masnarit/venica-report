# Venica 経営管理自動レポートシステム — 設計書

## 1. 全体アーキテクチャ

```
GitHub Actions (定期実行)
  ├── 毎朝9時    → daily_report.py  → Gmail（日次経営レポート）
  ├── 毎週月曜   → weekly_cs.py     → Gmail（週次CSレビュー）
  └── 毎月1日    → monthly_payment.py → Gmail + Sheets（月次支払集計）

データソース
  ├── Shopify Admin API  → 売上・注文・商品・Shopify在庫
  ├── OPENLOGI API       → 倉庫在庫
  └── Google Drive       → 請求書PDF（OCR解析）

中間データ層（Google Sheets）
  ├── inventory_adjustments  在庫調整テーブル（手動更新）
  ├── sales_targets          月次売上目標（手動更新）
  ├── product_master         商品マスタ・カテゴリ設定
  ├── cs_keywords            CS分類キーワード辞書
  └── report_log             実行ログ

出力
  └── Gmail（HTML形式レポート）
```

---

## 2. Google Sheetsシート設計

### シートブック名：`venica-master`

#### シート①：`inventory_adjustments`（在庫調整テーブル）

| 列 | 列名 | 型 | 説明 |
|----|------|----|------|
| A | sku | string | SKUコード（必須） |
| B | product_name | string | 商品名（参考用） |
| C | popup_reserved | integer | POPUP引当数 |
| D | photo_loan | integer | 撮影貸出数 |
| E | pr_loan | integer | PR貸出数 |
| F | wholesale_reserved | integer | 卸引当数 |
| G | defective | integer | 不良数 |
| H | return_checking | integer | 返品確認中数 |
| I | internal_reserved | integer | 社内確保数 |
| J | note | string | 備考 |
| K | updated_at | datetime | 最終更新日時 |

**計算式：**
```
実販売可能在庫 = OPENLOGI在庫
              - popup_reserved
              - photo_loan
              - pr_loan
              - wholesale_reserved
              - defective
              - return_checking
              - internal_reserved
```

#### シート②：`sales_targets`（売上目標）

| 列 | 列名 | 説明 |
|----|------|------|
| A | year_month | YYYY-MM形式 |
| B | target_amount | 月次目標売上（円） |
| C | note | 備考 |

#### シート③：`product_master`（商品マスタ）

| 列 | 列名 | 説明 |
|----|------|------|
| A | sku | SKUコード |
| B | product_name | 商品名 |
| C | category | カテゴリ（tops/bottoms/outerwear/accessories/etc） |
| D | price | 定価 |
| E | launch_date | 販売開始日 |
| F | is_active | 販売中フラグ |

#### シート④：`cs_keywords`（CS分類キーワード）

| 列 | 列名 | 説明 |
|----|------|------|
| A | category | 分類カテゴリ名 |
| B | keywords | カンマ区切りキーワード |

デフォルト設定：
- 配送：届かない,遅延,追跡,配達,発送,運送
- サイズ：サイズ,大きい,小さい,丈,身幅,着丈
- 返品交換：返品,交換,返却,返送
- 不良：不良,傷,汚れ,破れ,穴,縫製
- 決済：支払,決済,クレジット,エラー,請求
- その他：（上記以外）

#### シート⑤：`report_log`（実行ログ）

| 列 | 列名 | 説明 |
|----|------|------|
| A | executed_at | 実行日時 |
| B | report_type | daily/weekly/monthly |
| C | status | success/error |
| D | message | エラーメッセージなど |
| E | email_sent_to | 送信先メール |

---

## 3. 必要API一覧

| API | 用途 | 認証方式 | 備考 |
|-----|------|---------|------|
| Shopify Admin API | 売上・注文・在庫取得 | APIキー + シークレット | Private App推奨 |
| OPENLOGI API | 倉庫在庫取得 | APIキー | |
| Google Sheets API | マスタデータ読み書き | OAuth2 サービスアカウント | |
| Gmail API | レポートメール送信 | OAuth2 サービスアカウント | ドメイン委任必要 |
| Google Drive API | 請求書PDF取得 | OAuth2 サービスアカウント | |
| Claude API (Anthropic) | 経営コメント自動生成 | APIキー | オプション |

---

## 4. 日次バッチ設計（daily_report.py）

```
09:00 JST トリガー（GitHub Actions）
  │
  ├─ 1. Shopify APIから前日売上・注文データ取得
  │       └─ 注文リスト、売上合計、商品別販売数
  │
  ├─ 2. OPENLOGI APIから在庫データ取得
  │       └─ SKU別在庫数
  │
  ├─ 3. Google Sheetsから調整データ取得
  │       ├─ inventory_adjustments（在庫調整値）
  │       └─ sales_targets（月次目標）
  │
  ├─ 4. 在庫計算
  │       └─ 実販売可能在庫 = OPENLOGI在庫 - 調整値合計
  │
  ├─ 5. KPI計算
  │       ├─ 前日売上・前日比・月次累計・目標比
  │       ├─ 売れ筋TOP10
  │       ├─ カテゴリ別売上
  │       └─ 初速分析（7/14/30日）
  │
  ├─ 6. アラート判定
  │       ├─ 欠品リスク（実販売可能在庫 ≤ 3日分）
  │       ├─ 滞留在庫（30日以上動きなし）
  │       └─ 在庫差異（Shopify在庫とOPENLOGI在庫の乖離）
  │
  ├─ 7. AIコメント生成（Claude API）
  │
  ├─ 8. HTMLレポート生成
  │
  ├─ 9. Gmail送信
  │
  └─ 10. 実行ログをGoogle Sheetsに記録
```

---

## 5. 実装ロードマップ

### Phase 1：基盤構築（Week 1）
- [ ] GitHubリポジトリ作成・GitHub Secrets設定
- [ ] Google Cloud Projectセットアップ（サービスアカウント作成）
- [ ] Google Sheetsテンプレート作成・初期データ入力
- [ ] `src/config.py` `src/sheets_client.py` 実装

### Phase 2：データ取得層（Week 2）
- [ ] `src/shopify_client.py` 実装・テスト
- [ ] `src/openlogi_client.py` 実装・テスト
- [ ] `src/inventory.py`（在庫計算ロジック）実装

### Phase 3：日次レポート（Week 2-3）
- [ ] `src/daily_report.py` 実装
- [ ] `templates/daily_report.html` 作成
- [ ] `src/gmail_client.py` 実装
- [ ] GitHub Actions `daily_report.yml` 設定・テスト

### Phase 4：週次CSレビュー（Week 3）
- [ ] `src/weekly_cs.py` 実装
- [ ] `src/cs_classifier.py` 実装
- [ ] GitHub Actions `weekly_cs.yml` 設定・テスト

### Phase 5：月次支払集計（Week 4）
- [ ] `src/monthly_payment.py` 実装
- [ ] `src/drive_client.py`（PDF OCR）実装
- [ ] GitHub Actions `monthly_payment.yml` 設定・テスト

### Phase 6：AIコメント・仕上げ（Week 4-5）
- [ ] `src/ai_comment.py`（Claude API連携）実装
- [ ] エラーハンドリング強化
- [ ] README最終化・運用ドキュメント整備
