"""入稿ワークフローのオーケストレーション"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import (
    Project,
    SubmissionBatch,
    SubmissionCampaign,
    XAdsCredential,
    now_jst,
)
from app.services.x_ads_client import XAdsClient, XAdsApiError, yen_to_micro

logger = logging.getLogger(__name__)

# Excel/UI のプレースメント名 → X Ads API のプレースメント名マッピング
PLACEMENT_MAP = {
    # Excel形式（日本語UI由来）
    "TIMELINES": "TWITTER_TIMELINE",
    "SEARCH_RESULTS": "TWITTER_SEARCH",
    "PROFILES": "TWITTER_PROFILE",
    "REPLIES": "TWITTER_REPLIES",
    "MEDIA_VIEWER": "TWITTER_MEDIA_VIEWER",
    # そのまま使えるAPI形式
    "ALL_ON_TWITTER": "ALL_ON_TWITTER",
    "PUBLISHER_NETWORK": "PUBLISHER_NETWORK",
    "TAP_BANNER": "TAP_BANNER",
    "TAP_FULL": "TAP_FULL",
    "TAP_FULL_LANDSCAPE": "TAP_FULL_LANDSCAPE",
    "TAP_MRECT": "TAP_MRECT",
    "TAP_NATIVE": "TAP_NATIVE",
    "TWITTER_MEDIA_VIEWER": "TWITTER_MEDIA_VIEWER",
    "TWITTER_PROFILE": "TWITTER_PROFILE",
    "TWITTER_REPLIES": "TWITTER_REPLIES",
    "TWITTER_SEARCH": "TWITTER_SEARCH",
    "TWITTER_TIMELINE": "TWITTER_TIMELINE",
}

JST = timezone(timedelta(hours=9))


def _normalize_placements(raw: str) -> str:
    """プレースメント文字列をAPI形式に変換。
    入力: JSON配列 / セミコロン区切り / カンマ区切り
    出力: カンマ区切りのAPI形式
    """
    # JSON配列を試す
    try:
        items = json.loads(raw)
        if isinstance(items, list):
            mapped = [PLACEMENT_MAP.get(p.strip(), p.strip()) for p in items]
            return ",".join(mapped)
    except (json.JSONDecodeError, TypeError):
        pass

    # セミコロン区切り or カンマ区切り
    if ";" in raw:
        items = [p.strip() for p in raw.split(";") if p.strip()]
    else:
        items = [p.strip() for p in raw.split(",") if p.strip()]

    mapped = [PLACEMENT_MAP.get(p, p) for p in items]
    return ",".join(mapped)


def _default_start_time() -> str:
    """開始時刻のデフォルト（現在時刻 + 5分、ISO 8601形式）"""
    dt = datetime.now(JST) + timedelta(minutes=5)
    return dt.strftime("%Y-%m-%dT%H:%M:%S+09:00")


class SubmissionService:
    def __init__(self, db: Session):
        self.db = db

    def create_batch(
        self,
        user_id: int,
        project_id: int,
        name: str,
        campaigns_data: list[dict],
        submission_method: str = "api",
    ) -> SubmissionBatch:
        """入稿バッチを作成（campaign レコードも一緒に作成）"""
        batch = SubmissionBatch(
            user_id=user_id,
            project_id=project_id,
            name=name,
            status="draft",
            submission_method=submission_method,
            total_campaigns=len(campaigns_data),
        )
        self.db.add(batch)
        self.db.flush()  # batch.id を取得

        for i, cd in enumerate(campaigns_data):
            campaign = SubmissionCampaign(
                batch_id=batch.id,
                sort_order=i,
                campaign_name=cd["campaign_name"],
                campaign_objective=cd.get("campaign_objective", "WEBSITE_CLICKS"),
                campaign_daily_budget=cd.get("campaign_daily_budget"),
                campaign_total_budget=cd.get("campaign_total_budget"),
                campaign_budget_optimization=cd.get("campaign_budget_optimization"),
                funding_instrument_id=cd["funding_instrument_id"],
                line_item_name=cd.get("line_item_name"),
                bid_amount=cd.get("bid_amount"),
                bid_strategy=cd.get("bid_strategy", "AUTO"),
                placements=cd.get("placements"),
                start_time=cd.get("start_time"),
                end_time=cd.get("end_time"),
                target_platforms=cd.get("target_platforms"),
                target_gender=cd.get("target_gender"),
                target_age_ranges=cd.get("target_age_ranges"),
                target_locations=cd.get("target_locations"),
                target_languages=cd.get("target_languages"),
                target_audiences=cd.get("target_audiences"),
                conversion_tag_id=cd.get("conversion_tag_id"),
                audience_expansion=cd.get("audience_expansion"),
                tweet_ids=cd.get("tweet_ids"),
                tweet_text=cd.get("tweet_text"),
                media_asset_ids=cd.get("media_asset_ids"),
                website_card_title=cd.get("website_card_title"),
                website_card_url=cd.get("website_card_url"),
                website_card_cta=cd.get("website_card_cta"),
            )
            self.db.add(campaign)

        self.db.commit()
        self.db.refresh(batch)
        return batch

    def execute_submission(self, batch_id: int) -> SubmissionBatch:
        """バッチ内の全キャンペーンをX Ads APIで入稿"""
        batch = self.db.query(SubmissionBatch).filter(
            SubmissionBatch.id == batch_id
        ).first()
        if not batch:
            raise ValueError("Batch not found")

        # プロジェクトと認証情報を取得
        project = self.db.query(Project).filter(Project.id == batch.project_id).first()
        if not project or not project.credential_id:
            batch.status = "failed"
            batch.error_summary = "Project or credential not configured"
            self.db.commit()
            return batch

        credential = self.db.query(XAdsCredential).filter(
            XAdsCredential.id == project.credential_id
        ).first()
        if not credential:
            batch.status = "failed"
            batch.error_summary = "Credential not found"
            self.db.commit()
            return batch

        # X Ads APIクライアント作成
        client = XAdsClient(
            api_key=credential.api_key,
            api_secret=credential.api_secret,
            access_token=credential.access_token,
            access_secret=credential.access_secret,
        )
        account_id = credential.ads_account_id

        batch.status = "submitting"
        batch.submitted_at = now_jst()
        self.db.commit()

        succeeded = 0
        failed = 0

        for campaign in batch.campaigns:
            if campaign.status == "success":
                succeeded += 1
                continue  # リトライ時にスキップ

            try:
                self._submit_single_campaign(client, campaign, account_id)
                campaign.status = "success"
                succeeded += 1
            except Exception as e:
                campaign.status = "failed"
                campaign.error_message = str(e)
                failed += 1
                logger.error("Campaign '%s' failed: %s", campaign.campaign_name, str(e))

            self.db.commit()

        # バッチステータス更新
        batch.succeeded_campaigns = succeeded
        batch.failed_campaigns = failed
        batch.completed_at = now_jst()

        if failed == 0:
            batch.status = "completed"
        elif succeeded == 0:
            batch.status = "failed"
        else:
            batch.status = "partial_failure"

        self.db.commit()
        self.db.refresh(batch)
        return batch

    def _submit_single_campaign(
        self, client: XAdsClient, campaign: SubmissionCampaign, account_id: str
    ) -> None:
        """1キャンペーン分の入稿（Campaign → LineItem → Targeting → PromotedTweet）"""

        # --- Step 1: Campaign 作成 ---
        if not campaign.api_campaign_id:
            params: dict = {
                "name": campaign.campaign_name,
                "funding_instrument_id": campaign.funding_instrument_id,
                "entity_status": "PAUSED",
                "standard_delivery": "true",
            }

            # Objective の設定
            # X Ads API では campaign レベルではなく line_item レベルで objective を設定
            # budget_optimization が CAMPAIGN の場合のみ campaign レベルで設定
            if campaign.campaign_budget_optimization:
                params["budget_optimization"] = campaign.campaign_budget_optimization

            if campaign.campaign_daily_budget:
                params["daily_budget_amount_local_micro"] = yen_to_micro(campaign.campaign_daily_budget)
            if campaign.campaign_total_budget:
                params["total_budget_amount_local_micro"] = yen_to_micro(campaign.campaign_total_budget)

            result = client.create_campaign(account_id, params)
            campaign.api_campaign_id = result.get("id")
            campaign.api_response_raw = json.dumps(result, ensure_ascii=False)
            self.db.flush()
            logger.info("Campaign created: %s", campaign.api_campaign_id)

        # --- Step 2: Line Item 作成 ---
        if not campaign.api_line_item_id:
            # X Ads API v12 では WEBSITE_CONVERSIONS を objective に直接指定すると500エラー
            # 代わりに objective=WEBSITE_CLICKS + goal=WEBSITE_CONVERSIONS を使う
            api_objective = campaign.campaign_objective
            api_goal = None
            if campaign.campaign_objective == "WEBSITE_CONVERSIONS":
                api_objective = "WEBSITE_CLICKS"
                api_goal = "WEBSITE_CONVERSIONS"

            li_params: dict = {
                "campaign_id": campaign.api_campaign_id,
                "name": campaign.line_item_name or campaign.campaign_name,
                "product_type": "PROMOTED_TWEETS",
                "objective": api_objective,
                "entity_status": "PAUSED",
                "bid_strategy": campaign.bid_strategy,
            }

            # goal の設定（WEBSITE_CONVERSIONS等）
            if api_goal:
                li_params["goal"] = api_goal

            if campaign.bid_amount and campaign.bid_strategy != "AUTO":
                li_params["bid_amount_local_micro"] = yen_to_micro(campaign.bid_amount)

            # コンバージョンタグ（WEBSITE_CONVERSIONS の場合に必要）
            if campaign.conversion_tag_id:
                li_params["primary_web_event_tag"] = campaign.conversion_tag_id

            # Placements（Excel形式 → API形式に変換）
            if campaign.placements:
                li_params["placements"] = _normalize_placements(campaign.placements)
            else:
                # デフォルト: ALL_ON_TWITTER
                li_params["placements"] = "ALL_ON_TWITTER"

            # start_time は必須。未指定なら「今すぐ」（+5分）
            if campaign.start_time:
                li_params["start_time"] = campaign.start_time
            else:
                li_params["start_time"] = _default_start_time()

            if campaign.end_time:
                li_params["end_time"] = campaign.end_time

            # Audience Expansion
            if campaign.audience_expansion:
                li_params["audience_expansion"] = campaign.audience_expansion

            result = client.create_line_item(account_id, li_params)
            campaign.api_line_item_id = result.get("id")
            self.db.flush()
            logger.info("Line item created: %s", campaign.api_line_item_id)

        # --- Step 3: Targeting Criteria ---
        targeting_ids = []
        line_item_id = campaign.api_line_item_id

        # Gender
        if campaign.target_gender and campaign.target_gender != "ANY":
            gender_val = "1" if campaign.target_gender == "MALE" else "2"
            try:
                r = client.create_targeting_criteria(account_id, line_item_id, {
                    "targeting_type": "GENDER",
                    "targeting_value": gender_val,
                })
                targeting_ids.append(r.get("id", ""))
            except XAdsApiError as e:
                logger.warning("Gender targeting failed: %s", e)

        # Age Ranges
        if campaign.target_age_ranges:
            try:
                ages = json.loads(campaign.target_age_ranges)
                for age in ages:
                    try:
                        r = client.create_targeting_criteria(account_id, line_item_id, {
                            "targeting_type": "AGE",
                            "targeting_value": age,
                        })
                        targeting_ids.append(r.get("id", ""))
                    except XAdsApiError as e:
                        logger.warning("Age targeting failed for %s: %s", age, e)
            except (json.JSONDecodeError, TypeError):
                pass

        # Platforms
        if campaign.target_platforms:
            try:
                platforms = json.loads(campaign.target_platforms)
                for plat in platforms:
                    try:
                        r = client.create_targeting_criteria(account_id, line_item_id, {
                            "targeting_type": "PLATFORM",
                            "targeting_value": plat,
                        })
                        targeting_ids.append(r.get("id", ""))
                    except XAdsApiError as e:
                        logger.warning("Platform targeting failed for %s: %s", plat, e)
            except (json.JSONDecodeError, TypeError):
                pass

        # Locations
        if campaign.target_locations:
            try:
                locations = json.loads(campaign.target_locations)
                for loc in locations:
                    try:
                        r = client.create_targeting_criteria(account_id, line_item_id, {
                            "targeting_type": "LOCATION",
                            "targeting_value": loc,
                        })
                        targeting_ids.append(r.get("id", ""))
                    except XAdsApiError as e:
                        logger.warning("Location targeting failed for %s: %s", loc, e)
            except (json.JSONDecodeError, TypeError):
                pass

        # Languages
        if campaign.target_languages:
            try:
                languages = json.loads(campaign.target_languages)
                for lang in languages:
                    try:
                        r = client.create_targeting_criteria(account_id, line_item_id, {
                            "targeting_type": "LANGUAGE",
                            "targeting_value": lang,
                        })
                        targeting_ids.append(r.get("id", ""))
                    except XAdsApiError as e:
                        logger.warning("Language targeting failed for %s: %s", lang, e)
            except (json.JSONDecodeError, TypeError):
                pass

        # Conversion Tag
        if campaign.conversion_tag_id:
            try:
                r = client.create_targeting_criteria(account_id, line_item_id, {
                    "targeting_type": "EVENT",
                    "targeting_value": campaign.conversion_tag_id,
                })
                targeting_ids.append(r.get("id", ""))
            except XAdsApiError:
                pass  # コンバージョンタグはtargetingではなく別設定の場合もある

        if targeting_ids:
            campaign.api_targeting_ids = json.dumps(targeting_ids)
            self.db.flush()

        # --- Step 4a: メディアアップロード（必要な場合） ---
        uploaded_media_ids: list[str] = []
        first_media_key: str | None = None
        if campaign.media_asset_ids and not campaign.api_tweet_id:
            try:
                asset_ids = json.loads(campaign.media_asset_ids)
            except (json.JSONDecodeError, TypeError):
                asset_ids = []

            if asset_ids:
                from app.models import MediaAsset
                from pathlib import Path
                for asset_id in asset_ids:
                    try:
                        asset = self.db.query(MediaAsset).filter(
                            MediaAsset.id == int(asset_id)
                        ).first()
                        if not asset:
                            continue
                        file_path = str(Path("data/media") / str(asset.user_id) / asset.filename)
                        result = client.upload_media(file_path, asset.mime_type)
                        uploaded_media_ids.append(result["media_id_string"])
                        if not first_media_key and result.get("media_key"):
                            first_media_key = result["media_key"]
                        logger.info("Media uploaded: %s -> %s", asset.original_filename, result["media_id_string"])
                    except Exception as e:
                        logger.warning("Media upload failed for asset %s: %s", asset_id, e)

        # --- Step 4b: Website Card作成（必要な場合） ---
        card_uri: str | None = campaign.card_uri
        if campaign.website_card_url and not card_uri and not campaign.api_tweet_id:
            try:
                card_result = client.create_website_card(
                    account_id=account_id,
                    name=campaign.campaign_name + " - Card",
                    website_title=campaign.website_card_title or campaign.campaign_name,
                    website_url=campaign.website_card_url,
                    website_cta=campaign.website_card_cta or "LEARN_MORE",
                    media_key=first_media_key,
                )
                card_uri = card_result.get("card_uri")
                campaign.card_uri = card_uri
                self.db.flush()
                logger.info("Website card created: %s", card_uri)
            except XAdsApiError as e:
                logger.warning("Website card creation failed: %s", e)

        # --- Step 4c: ダークポスト作成（必要な場合） ---
        if campaign.tweet_text and not campaign.api_tweet_id:
            try:
                tweet_result = client.create_tweet(
                    account_id,
                    campaign.tweet_text,
                    media_ids=uploaded_media_ids if uploaded_media_ids else None,
                    card_uri=card_uri,
                )
                campaign.api_tweet_id = tweet_result.get("id") or tweet_result.get("id_str")
                self.db.flush()
                logger.info("Dark post created: %s", campaign.api_tweet_id)
            except XAdsApiError as e:
                logger.warning("Tweet creation failed: %s", e)

        # --- Step 5: Promoted Tweet 紐付け ---
        tweet_ids_to_promote = []

        # ダークポストで作成したツイート
        if campaign.api_tweet_id:
            tweet_ids_to_promote.append(campaign.api_tweet_id)

        # 既存のツイートID
        if campaign.tweet_ids:
            try:
                existing_ids = json.loads(campaign.tweet_ids)
                tweet_ids_to_promote.extend(existing_ids)
            except (json.JSONDecodeError, TypeError):
                # カンマ区切りの場合
                tweet_ids_to_promote.extend(
                    [tid.strip() for tid in campaign.tweet_ids.split(",") if tid.strip()]
                )

        if tweet_ids_to_promote and not campaign.api_promoted_tweet_id:
            result = client.create_promoted_tweet(account_id, line_item_id, tweet_ids_to_promote)
            # result は list の場合と dict の場合がある
            if isinstance(result, list) and result:
                campaign.api_promoted_tweet_id = result[0].get("id", "")
            elif isinstance(result, dict):
                campaign.api_promoted_tweet_id = result.get("id", "")
            self.db.flush()
            logger.info("Promoted tweet created: %s", campaign.api_promoted_tweet_id)

    def retry_failed(self, batch_id: int) -> SubmissionBatch:
        """失敗したキャンペーンのみリトライ"""
        batch = self.db.query(SubmissionBatch).filter(
            SubmissionBatch.id == batch_id
        ).first()
        if not batch:
            raise ValueError("Batch not found")

        # 失敗したキャンペーンのステータスをリセット
        for campaign in batch.campaigns:
            if campaign.status == "failed":
                campaign.status = "pending"
                campaign.error_message = None

        self.db.commit()
        return self.execute_submission(batch_id)
