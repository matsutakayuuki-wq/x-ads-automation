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
                resp = self.session.post(url, params=params, json=json_body)
            elif method.upper() == "PUT":
                resp = self.session.put(url, params=params, json=json_body)
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
                raise XAdsApiError(
                    f"API Error {resp.status_code}: {'; '.join(error_msgs) or resp.text[:200]}",
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

    def get_campaigns(self, account_id: str) -> list[dict]:
        """キャンペーン一覧"""
        data = self._request("GET", f"/accounts/{account_id}/campaigns")
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

    def create_tweet(self, account_id: str, text: str, as_user_id: str | None = None) -> dict:
        """広告専用ツイート（ダークポスト）を作成

        nullcast=true でタイムラインに表示されないツイートを作成
        """
        params: dict[str, Any] = {
            "text": text,
            "nullcast": "true",
        }
        if as_user_id:
            params["as_user_id"] = as_user_id
        data = self._request("POST", f"/accounts/{account_id}/tweet", params=params)
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
