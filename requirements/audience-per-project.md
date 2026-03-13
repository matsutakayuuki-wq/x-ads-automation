# 案件ごとに複数オーディエンス対応

## Goal
1つの案件(Project)に複数のオーディエンス(Audience)を紐付け、ターゲティング設定をオーディエンス単位で管理できるようにする。

## Current State
- Project テーブルに直接 default_* ターゲティングフィールドがある
- 案件一覧ページは案件名がカード見出し
- LP管理は project_id に紐付き（これは維持）

## Changes

### 1. DB Schema
- 新テーブル `audiences` 作成
  - project_id (FK → projects)
  - name (オーディエンス名 = カード見出し)
  - ターゲティング系フィールド（Project から移動）: objective, placements, platforms, gender, age_ranges, locations, languages, bid_strategy, daily_budget, bid_amount, currency, audience_expansion
  - is_active, created_at, updated_at
- Project テーブルからターゲティング系フィールドを削除（name, description, credential_id, funding_instrument_id, conversion_tag_id のみ残す）

### 2. 案件一覧 (projects.html)
- 案件名をセクション見出しとして表示
- その下にオーディエンスカードをグリッド表示（太字=オーディエンス名）
- 各案件セクションに「+ オーディエンス追加」ボタン

### 3. 案件詳細 (project_detail.html)
- 基本情報（案件名、認証情報、支払いID等）のみ
- オーディエンス一覧セクション追加（各オーディエンスのターゲティング編集）

### 4. 入稿ページ (submission_new.html)
- Step1: 案件選択 → オーディエンス選択の2段階
- オーディエンス選択でデフォルト値がキャンペーンに適用される

### 5. LP管理 (lp.html)
- 変更なし（既に project_id ベース）

### 6. マイグレーション
- 既存 Project のターゲティングデータ → audiences テーブルに移行
- 既存 submission_batches の project_id は維持

## Affected Files
- app/models.py (Audience モデル追加、Project からフィールド削除)
- app/schemas.py (AudienceCreate/Update/Response 追加)
- app/routers/projects.py (Audience CRUD エンドポイント追加)
- app/templates/projects.html (UI変更)
- app/templates/project_detail.html (UI変更)
- app/templates/submission_new.html (オーディエンス選択追加)
- main.py (マイグレーション追加)
