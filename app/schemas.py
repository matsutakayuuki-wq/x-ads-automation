from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


# =============================================================================
# Credential
# =============================================================================

class CredentialCreate(BaseModel):
    name: str
    ads_account_id: str
    api_key: str
    api_secret: str
    access_token: str
    access_secret: str


class CredentialUpdate(BaseModel):
    name: Optional[str] = None
    ads_account_id: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    access_token: Optional[str] = None
    access_secret: Optional[str] = None
    is_active: Optional[bool] = None


class CredentialResponse(BaseModel):
    id: int
    name: str
    ads_account_id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# =============================================================================
# Project
# =============================================================================

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    credential_id: Optional[int] = None
    funding_instrument_id: Optional[str] = None
    conversion_tag_id: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    credential_id: Optional[int] = None
    funding_instrument_id: Optional[str] = None
    conversion_tag_id: Optional[str] = None
    is_active: Optional[bool] = None


class ProjectResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    credential_id: Optional[int]
    funding_instrument_id: Optional[str]
    conversion_tag_id: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# =============================================================================
# Audience
# =============================================================================

class AudienceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    default_objective: str = "WEBSITE_CLICKS"
    default_placements: Optional[str] = None
    default_platforms: Optional[str] = None
    default_gender: Optional[str] = None
    default_age_ranges: Optional[str] = None
    default_locations: Optional[str] = None
    default_languages: Optional[str] = None
    default_bid_strategy: str = "AUTO"
    default_daily_budget: Optional[int] = None
    default_bid_amount: Optional[int] = None
    currency: str = "JPY"
    default_audience_expansion: Optional[str] = None


class AudienceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    default_objective: Optional[str] = None
    default_placements: Optional[str] = None
    default_platforms: Optional[str] = None
    default_gender: Optional[str] = None
    default_age_ranges: Optional[str] = None
    default_locations: Optional[str] = None
    default_languages: Optional[str] = None
    default_bid_strategy: Optional[str] = None
    default_daily_budget: Optional[int] = None
    default_bid_amount: Optional[int] = None
    currency: Optional[str] = None
    default_audience_expansion: Optional[str] = None
    is_active: Optional[bool] = None


class AudienceResponse(BaseModel):
    id: int
    project_id: int
    name: str
    description: Optional[str]
    default_objective: str
    default_placements: Optional[str]
    default_platforms: Optional[str]
    default_gender: Optional[str]
    default_age_ranges: Optional[str]
    default_locations: Optional[str]
    default_languages: Optional[str]
    default_bid_strategy: str
    default_daily_budget: Optional[int]
    default_bid_amount: Optional[int]
    currency: str
    default_audience_expansion: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# =============================================================================
# Submission
# =============================================================================

class CampaignInput(BaseModel):
    """新規入稿時の1キャンペーン分の入力データ"""
    campaign_name: str
    campaign_objective: str = "WEBSITE_CLICKS"
    campaign_daily_budget: Optional[int] = None  # JPY
    campaign_total_budget: Optional[int] = None  # JPY
    campaign_budget_optimization: Optional[str] = None
    funding_instrument_id: str

    line_item_name: Optional[str] = None
    bid_amount: Optional[int] = None  # JPY
    bid_strategy: str = "AUTO"
    placements: Optional[str] = None  # JSON
    start_time: Optional[str] = None
    end_time: Optional[str] = None

    target_platforms: Optional[str] = None
    target_gender: Optional[str] = None
    target_age_ranges: Optional[str] = None
    target_locations: Optional[str] = None
    target_languages: Optional[str] = None
    target_audiences: Optional[str] = None
    conversion_tag_id: Optional[str] = None
    audience_expansion: Optional[str] = None

    tweet_ids: Optional[str] = None  # JSON
    tweet_text: Optional[str] = None
    media_asset_ids: Optional[str] = None  # JSON
    website_card_title: Optional[str] = None
    website_card_url: Optional[str] = None
    website_card_cta: Optional[str] = None


class SubmissionCreate(BaseModel):
    """入稿バッチ作成リクエスト"""
    project_id: int
    name: str
    campaigns: List[CampaignInput]


class SubmissionCampaignResponse(BaseModel):
    id: int
    sort_order: int
    campaign_name: str
    campaign_objective: str
    campaign_daily_budget: Optional[int]
    funding_instrument_id: str
    line_item_name: Optional[str]
    bid_amount: Optional[int]
    bid_strategy: str
    status: str
    api_campaign_id: Optional[str]
    api_line_item_id: Optional[str]
    api_promoted_tweet_id: Optional[str]
    error_message: Optional[str]
    tweet_ids: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class SubmissionBatchResponse(BaseModel):
    id: int
    name: str
    project_id: Optional[int]
    status: str
    submission_method: str
    total_campaigns: int
    succeeded_campaigns: int
    failed_campaigns: int
    error_summary: Optional[str]
    submitted_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class SubmissionBatchDetailResponse(SubmissionBatchResponse):
    campaigns: List[SubmissionCampaignResponse] = []


# =============================================================================
# MediaAsset
# =============================================================================

class MediaAssetResponse(BaseModel):
    id: int
    filename: str
    original_filename: str
    mime_type: str
    file_size: int
    width: Optional[int]
    height: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}


# =============================================================================
# LandingPage
# =============================================================================

class LandingPageCreate(BaseModel):
    name: Optional[str] = ""
    url: str
    description: Optional[str] = None


class LandingPageBulkCreate(BaseModel):
    """複数LPを一括登録（URLリスト）"""
    urls: list[str]
    names: Optional[list[str]] = None


class LandingPageUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None
    is_used: Optional[bool] = None


class LandingPageResponse(BaseModel):
    id: int
    project_id: int
    name: Optional[str]
    url: str
    description: Optional[str]
    is_used: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
