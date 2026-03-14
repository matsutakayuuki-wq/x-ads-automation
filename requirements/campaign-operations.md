# 運用ページ（Campaign Operations）

## Goal
案件ごとにアクティブなキャンペーンを一覧表示し、広告費（今日/全体）を確認でき、キャンペーンの一時停止/再開をUI上で行える運用ページを追加する。

## Current State
- `XAdsClient.get_campaigns(account_id)` — キャンペーン一覧取得は実装済み
- キャンペーン更新（pause/resume）、統計取得は未実装
- ナビゲーションに「運用」項目なし

## Technical Approach

### 1. X Ads API Client 拡張 (`app/services/x_ads_client.py`)
- `update_campaign(account_id, campaign_id, params)` — PUT `/accounts/{id}/campaigns/{campaign_id}`
  - entity_status: ACTIVE / PAUSED で制御
- `get_campaign_stats(account_id, campaign_ids, start_time, end_time)` — GET `/stats/accounts/{id}`
  - entity=CAMPAIGN, metric_groups=BILLING (billed_charge_local_micro)
  - 今日分と全期間分の2回コール

### 2. Backend Router (`app/routers/operations.py`)
- `GET /operations` — 運用ページHTML
  - 全アクティブProjectをDBから取得、テンプレートに渡す
- `GET /api/operations/campaigns` — 全案件のキャンペーン一覧+統計JSON
  - 各Project → credential → X Ads API → campaigns取得
  - 統計も取得して結合
- `PUT /api/operations/campaigns/{campaign_id}/status` — キャンペーン停止/再開
  - body: { entity_status: "PAUSED" | "ACTIVE", project_id: int }

### 3. Template (`app/templates/operations.html`)
- 案件ごとにグループ化表示（projects.htmlと同じレイアウト方針）
- 各キャンペーンカード: 名前、ステータスバッジ、今日の広告費、全体の広告費、停止/再開ボタン
- ローディング表示（API取得に時間がかかるため）
- 案件名クリックで案件詳細へ遷移

### 4. Navigation (`app/templates/base.html`)
- 「入稿履歴」の下に「運用」ナビアイテム追加

### 5. main.py
- `operations` routerをinclude

## Affected Files
- `app/services/x_ads_client.py` — 2メソッド追加
- `app/routers/operations.py` — 新規作成
- `app/templates/operations.html` — 新規作成
- `app/templates/base.html` — ナビ項目追加
- `main.py` — router include追加

## Risk Assessment
- X Ads Stats API のレスポンス形式は実際のレスポンスを見て調整が必要な可能性あり
- 複数案件がある場合、API呼び出しが直列になり遅い → フロントエンドで非同期ロード
- マイクロ通貨変換（÷1,000,000）の丸め処理に注意
