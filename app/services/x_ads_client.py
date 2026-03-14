"""X Ads API クライアント（OAuth 1.0a）"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from requests_oauthlib import OAuth1Session

logger = logging.getLogger(__name__)

# X Ads API バージョン
API_VERSION = "12"
BASE_URL = f"https://ads-api.x.com/{API_VERSION}"


def yen_to_micro(yen: int) -> int:
    """JPY金額をマイクロ通貨に変換"""
    return yen * 1_000_000


def micro_to_yen(micro: int) -> int:
    """マイクロ通貨をJPY金額に変換"""
    return micro // 1_000_000


class XAdsApiError(Exception):
    """X Ads API エラー"""
    def __init__(self, message: str, status_code: int = 0, errors: list | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.errors = errors or []


class XAdsClient:
    """X Ads API クライアント"""

    def __init__(self, api_key: str, api_secret: str, access_token: str, access_secret: str):
        self.session = OAuth1Session(
            client_key=api_key,
            client_secret=api_secret,
            resource_owner_key=access_token,
            resource_owner_secret=access_secret,
        )

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> dict:
        """API リクエスト共通処理"""
        url = f"{BASE_URL}/{path.lstrip('/')}"
        logger.info("X Ads API %s %s", method, url)

        try:
            if method.upper() == "GET":
                resp = self.session.get(url, params=params)
            elif method.upper() == "POST":
                # X Ads API はPOSTパラメータをリクエストボディ（form-encoded）で送信
                if json_body:
                    resp = self.session.post(url, json=json_body)
                else:
                    resp = self.session.post(url, data=params)
            elif method.upper() == "PUT":
                if json_body:
                    resp = self.session.put(url, json=json_body)
                else:
                    resp = self.session.put(url, data=params)
            elif method.upper() == "DELETE":
                resp = self.session.delete(url, params=params)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            # レートリミットチェック
            remaining = resp.headers.get("x-rate-limit-remaining")
            if remaining and int(remaining) < 5:
                reset_time = int(resp.headers.get("x-rate-limit-reset", 0))
                wait = max(0, reset_time - int(time.time())) + 1
                logger.warning("Rate limit nearly exhausted. Waiting %d seconds.", wait)
                time.sleep(min(wait, 60))

            # レスポンス解析
            if resp.status_code == 204:
                return {"data": None}

            try:
                data = resp.json()
            except Exception:
                raise XAdsApiError(
                    f"Invalid JSON response: {resp.text[:500]}",
                    status_code=resp.status_code,
                )

            if resp.status_code >= 400:
                errors = data.get("errors", [])
                error_msgs = [e.get("message", str(e)) for e in errors]
                detail = "; ".join(error_msgs) or resp.text[:500]
                logger.error(
                    "X Ads API %s %s -> %d: %s | request_params=%s",
                    method, url, resp.status_code, detail,
                    json.dumps(params, ensure_ascii=False)[:500] if params else "none",
                )
                raise XAdsApiError(
                    f"API Error {resp.status_code}: {detail}",
                    status_code=resp.status_code,
                    errors=errors,
                )

            logger.debug("Response: %s", json.dumps(data, ensure_ascii=False)[:500])
            return data

        except XAdsApiError:
            raise
        except Exception as e:
            logger.error("X Ads API request failed: %s", str(e))
            raise XAdsApiError(f"Request failed: {str(e)}")

    # =========================================================================
    # Account
    # =========================================================================

    def get_accounts(self) -> list[dict]:
        """広告アカウント一覧取得"""
        data = self._request("GET", "/accounts")
        return data.get("data", [])

    def get_account(self, account_id: str) -> dict:
        """広告アカウント情報取得"""
        data = self._request("GET", f"/accounts/{account_id}")
        return data.get("data", {})

    # =========================================================================
    # Funding Instruments（支払い方法）
    # =========================================================================

    def get_funding_instruments(self, account_id: str) -> list[dict]:
        """支払い方法一覧"""
        data = self._request("GET", f"/accounts/{account_id}/funding_instruments")
        return data.get("data", [])

    # =========================================================================
    # Conversion Tags
    # =========================================================================

    def get_conversion_tags(self, account_id: str) -> list[dict]:
        """コンバージョンタグ一覧"""
        try:
            data = self._request(
                "GET",
                f"/accounts/{account_id}/web_event_tags",
            )
            return data.get("data", [])
        except XAdsApiError:
            # フォールバック: 古いエンドポイント
            try:
                data = self._request(
                    "GET",
                    f"/accounts/{account_id}/conversion_event_tags",
                )
                return data.get("data", [])
            except XAdsApiError:
                return []

    # =========================================================================
    # Campaign
    # =========================================================================

    def create_campaign(self, account_id: str, params: dict) -> dict:
        """キャンペーン作成

        params:
            name, funding_instrument_id, entity_status,
            daily_budget_amount_local_micro, total_budget_amount_local_micro,
            objective (WEBSITE_CLICKS etc), budget_optimization,
            start_time, end_time
        """
        data = self._request("POST", f"/accounts/{account_id}/campaigns", params=params)
        return data.get("data", {})

    def get_campaigns(self, account_id: str, **extra_params) -> list[dict]:
        """キャンペーン一覧"""
        params = extra_params or None
        data = self._request("GET", f"/accounts/{account_id}/campaigns", params=params)
        return data.get("data", [])

    def update_campaign(self, account_id: str, campaign_id: str, params: dict) -> dict:
        """キャンペーン更新（ステータス変更等）

        params:
            entity_status: ACTIVE / PAUSED / DRAFT
        """
        data = self._request("PUT", f"/accounts/{account_id}/campaigns/{campaign_id}", params=params)
        return data.get("data", {})

    def get_campaign_stats(
        self,
        account_id: str,
        campaign_ids: list[str],
        start_time: str,
        end_time: str,
        granularity: str = "TOTAL",
    ) -> list[dict]:
        """キャンペーン統計取得

        start_time/end_time: ISO 8601 (e.g. 2026-03-14T00:00:00+09:00)
        granularity: TOTAL / DAY / HOUR
        Returns: list of stats per campaign
        """
        params = {
            "entity": "CAMPAIGN",
            "entity_ids": ",".join(campaign_ids),
            "start_time": start_time,
            "end_time": end_time,
            "granularity": granularity,
            "metric_groups": "BILLING",
        }
        data = self._request("GET", f"/stats/accounts/{account_id}", params=params)
        return data.get("data", [])

    # =========================================================================
    # Line Item（アドセット）
    # =========================================================================

    def create_line_item(self, account_id: str, params: dict) -> dict:
        """ラインアイテム作成

        params:
            campaign_id, name, bid_amount_local_micro, bid_strategy,
            product_type, placements[], objective,
            entity_status, start_time, end_time,
            audience_expansion (EXPANDED/NARROW)
        """
        data = self._request("POST", f"/accounts/{account_id}/line_items", params=params)
        return data.get("data", {})

    # =========================================================================
    # Targeting Criteria
    # =========================================================================

    def create_targeting_criteria(self, account_id: str, line_item_id: str, params: dict) -> dict:
        """ターゲティング条件を1つ設定

        params:
            targeting_type, targeting_value
        """
        params["line_item_id"] = line_item_id
        data = self._request("POST", f"/accounts/{account_id}/targeting_criteria", params=params)
        return data.get("data", {})

    def create_targeting_criteria_batch(
        self, account_id: str, line_item_id: str, criteria_list: list[dict]
    ) -> list[dict]:
        """複数のターゲティング条件をまとめて設定"""
        results = []
        for criteria in criteria_list:
            try:
                result = self.create_targeting_criteria(account_id, line_item_id, criteria)
                results.append(result)
            except XAdsApiError as e:
                logger.warning("Targeting criteria failed: %s", str(e))
                results.append({"error": str(e)})
        return results

    # =========================================================================
    # Promoted Tweet
    # =========================================================================

    def create_promoted_tweet(self, account_id: str, line_item_id: str, tweet_ids: list[str]) -> dict:
        """ツイートを広告に紐付け"""
        params = {
            "line_item_id": line_item_id,
            "tweet_ids": ",".join(tweet_ids),
        }
        data = self._request("POST", f"/accounts/{account_id}/promoted_tweets", params=params)
        return data.get("data", {})

    # =========================================================================
    # Tweet Creation
    # =========================================================================

    def create_tweet(
        self,
        account_id: str,
        text: str,
        as_user_id: str | None = None,
        media_ids: list[str] | None = None,
        card_uri: str | None = None,
    ) -> dict:
        """広告専用ツイート（ダークポスト）を作成

        nullcast=true でタイムラインに表示されないツイートを作成
        media_ids: メディアIDリスト（カンマ区切りでAPIに送信）
        card_uri: Website Card URI
        """
        params: dict[str, Any] = {
            "text": text,
            "nullcast": "true",
        }
        if as_user_id:
            params["as_user_id"] = as_user_id
        if media_ids:
            params["media_ids"] = ",".join(media_ids)
        if card_uri:
            params["card_uri"] = card_uri
        data = self._request("POST", f"/accounts/{account_id}/tweet", params=params)
        return data.get("data", {})

    # =========================================================================
    # Media Upload（メディアアップロード）
    # =========================================================================

    UPLOAD_URL = "https://upload.twitter.com/1.1/media/upload.json"

    def upload_media(self, file_path: str, mime_type: str) -> dict:
        """メディアファイルをX APIにアップロード（チャンクアップロード）

        Returns: {"media_id_string": "...", "media_key": "..."}
        """
        import os
        file_size = os.path.getsize(file_path)
        media_category = "tweet_image"
        if mime_type.startswith("video/"):
            media_category = "tweet_video"
        elif mime_type == "image/gif":
            media_category = "tweet_gif"

        # Step 1: INIT
        init_params = {
            "command": "INIT",
            "total_bytes": str(file_size),
            "media_type": mime_type,
            "media_category": media_category,
        }
        logger.info("Media upload INIT: %s (%d bytes, %s)", file_path, file_size, mime_type)
        resp = self.session.post(self.UPLOAD_URL, data=init_params)
        if resp.status_code >= 400:
            raise XAdsApiError(f"Media INIT failed: {resp.text[:500]}", resp.status_code)
        init_data = resp.json()
        media_id = init_data["media_id_string"]

        # Step 2: APPEND (chunked)
        CHUNK_SIZE = 4 * 1024 * 1024  # 4MB
        with open(file_path, "rb") as f:
            segment = 0
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                resp = self.session.post(
                    self.UPLOAD_URL,
                    data={"command": "APPEND", "media_id": media_id, "segment_index": str(segment)},
                    files={"media_data": chunk},
                )
                if resp.status_code >= 400:
                    raise XAdsApiError(f"Media APPEND failed: {resp.text[:500]}", resp.status_code)
                segment += 1

        # Step 3: FINALIZE
        resp = self.session.post(
            self.UPLOAD_URL,
            data={"command": "FINALIZE", "media_id": media_id},
        )
        if resp.status_code >= 400:
            raise XAdsApiError(f"Media FINALIZE failed: {resp.text[:500]}", resp.status_code)
        finalize_data = resp.json()

        # Step 4: STATUS polling (for video/gif)
        processing_info = finalize_data.get("processing_info")
        while processing_info and processing_info.get("state") in ("pending", "in_progress"):
            wait_secs = processing_info.get("check_after_secs", 5)
            logger.info("Media processing... waiting %ds", wait_secs)
            time.sleep(wait_secs)
            resp = self.session.get(
                self.UPLOAD_URL,
                params={"command": "STATUS", "media_id": media_id},
            )
            if resp.status_code >= 400:
                raise XAdsApiError(f"Media STATUS failed: {resp.text[:500]}", resp.status_code)
            status_data = resp.json()
            processing_info = status_data.get("processing_info")
            if processing_info and processing_info.get("state") == "failed":
                error = processing_info.get("error", {})
                raise XAdsApiError(f"Media processing failed: {error.get('message', 'Unknown')}")

        result = {
            "media_id_string": media_id,
        }
        # media_key is available in the response
        if "media_key" in finalize_data:
            result["media_key"] = finalize_data["media_key"]
        elif "media_key" in init_data:
            result["media_key"] = init_data["media_key"]

        logger.info("Media upload complete: media_id=%s", media_id)
        return result

    # =========================================================================
    # Website Card
    # =========================================================================

    def create_website_card(
        self,
        account_id: str,
        name: str,
        website_title: str,
        website_url: str,
        website_cta: str = "LEARN_MORE",
        media_key: str | None = None,
    ) -> dict:
        """Website Card（リンク付きカード広告）を作成

        Returns: {"card_uri": "card://...", ...}
        """
        params: dict[str, str] = {
            "name": name,
            "website_title": website_title,
            "website_url": website_url,
            "website_cta": website_cta,
        }
        if media_key:
            params["media_key"] = media_key
        data = self._request("POST", f"/accounts/{account_id}/cards/website", params=params)
        return data.get("data", {})

    # =========================================================================
    # Targeting Options（利用可能なターゲティング値の取得）
    # =========================================================================

    def get_targeting_locations(self, query: str = "", location_type: str = "COUNTRIES") -> list[dict]:
        """ロケーションターゲティングの選択肢を検索"""
        params = {"location_type": location_type}
        if query:
            params["q"] = query
        data = self._request("GET", "/targeting_criteria/locations", params=params)
        return data.get("data", [])

    def get_targeting_interests(self) -> list[dict]:
        """インタレストターゲティングの選択肢"""
        data = self._request("GET", "/targeting_criteria/interests")
        return data.get("data", [])
