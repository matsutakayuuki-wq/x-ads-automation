from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone, timedelta
from typing import List, Optional

# 日本標準時（JST = UTC+9）
JST = timezone(timedelta(hours=9))


def now_jst() -> datetime:
    """現在の日本時間を返す"""
    return datetime.now(JST)


from cryptography.fernet import Fernet
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.database import Base


# --- Fernet 暗号化ヘルパー ---

def _get_fernet() -> Fernet:
    return Fernet(settings.ENCRYPTION_KEY.encode())


def encrypt_value(value: str) -> str:
    if not value:
        return value
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_value(value: str) -> str:
    if not value:
        return value
    return _get_fernet().decrypt(value.encode()).decode()


# =============================================================================
# 1. User（ユーザー管理）
# =============================================================================

class User(Base):
    """ログインユーザー"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_jst)

    credentials: Mapped[List[XAdsCredential]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    projects: Mapped[List[Project]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    submission_batches: Mapped[List[SubmissionBatch]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def set_password(self, password: str):
        salt = os.urandom(32)
        key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
        self.password_hash = salt.hex() + ":" + key.hex()

    def check_password(self, password: str) -> bool:
        try:
            salt_hex, key_hex = self.password_hash.split(":")
            salt = bytes.fromhex(salt_hex)
            expected_key = bytes.fromhex(key_hex)
            actual_key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
            return actual_key == expected_key
        except Exception:
            return False


# =============================================================================
# 2. XAdsCredential（X Ads API 認証情報）
# =============================================================================

class XAdsCredential(Base):
    """X Ads API 認証情報（1ユーザーに複数可）"""
    __tablename__ = "x_ads_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    ads_account_id: Mapped[str] = mapped_column(String(50), nullable=False)

    # 暗号化されたAPI認証情報
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    api_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    access_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_jst)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_jst, onupdate=now_jst
    )

    user: Mapped[User] = relationship(back_populates="credentials")
    projects: Mapped[List[Project]] = relationship(back_populates="credential")

    # --- 暗号化プロパティ ---
    @property
    def api_key(self) -> str:
        return decrypt_value(self.api_key_encrypted)

    @api_key.setter
    def api_key(self, value: str):
        self.api_key_encrypted = encrypt_value(value)

    @property
    def api_secret(self) -> str:
        return decrypt_value(self.api_secret_encrypted)

    @api_secret.setter
    def api_secret(self, value: str):
        self.api_secret_encrypted = encrypt_value(value)

    @property
    def access_token(self) -> str:
        return decrypt_value(self.access_token_encrypted)

    @access_token.setter
    def access_token(self, value: str):
        self.access_token_encrypted = encrypt_value(value)

    @property
    def access_secret(self) -> str:
        return decrypt_value(self.access_secret_encrypted)

    @access_secret.setter
    def access_secret(self, value: str):
        self.access_secret_encrypted = encrypt_value(value)


# =============================================================================
# 3. Project（案件設定）
# =============================================================================

class Project(Base):
    """案件設定（支払い情報・デフォルトターゲティング等を事前に固定）"""
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    credential_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("x_ads_credentials.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # X Ads 固定設定
    funding_instrument_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    conversion_tag_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # デフォルトターゲティング
    default_objective: Mapped[str] = mapped_column(String(50), default="WEBSITE_CLICKS")
    default_placements: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    default_platforms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    default_gender: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    default_age_ranges: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    default_locations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    default_languages: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    default_bid_strategy: Mapped[str] = mapped_column(String(50), default="AUTO")
    default_daily_budget: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # JPY
    default_bid_amount: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # JPY
    currency: Mapped[str] = mapped_column(String(10), default="JPY")

    # 類似オーディエンス拡張
    default_audience_expansion: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_jst)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_jst, onupdate=now_jst
    )

    user: Mapped[User] = relationship(back_populates="projects")
    credential: Mapped[Optional[XAdsCredential]] = relationship(back_populates="projects")
    submission_batches: Mapped[List[SubmissionBatch]] = relationship(
        back_populates="project"
    )


# =============================================================================
# 4. SubmissionBatch（入稿バッチ）
# =============================================================================

class SubmissionBatch(Base):
    """入稿バッチ（複数キャンペーンをまとめて入稿）"""
    __tablename__ = "submission_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    # draft, submitting, completed, partial_failure, failed
    submission_method: Mapped[str] = mapped_column(String(20), default="api")
    # api, excel

    total_campaigns: Mapped[int] = mapped_column(Integer, default=0)
    succeeded_campaigns: Mapped[int] = mapped_column(Integer, default=0)
    failed_campaigns: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_jst)

    user: Mapped[User] = relationship(back_populates="submission_batches")
    project: Mapped[Optional[Project]] = relationship(back_populates="submission_batches")
    campaigns: Mapped[List[SubmissionCampaign]] = relationship(
        back_populates="batch", cascade="all, delete-orphan",
        order_by="SubmissionCampaign.sort_order"
    )


# =============================================================================
# 5. SubmissionCampaign（個別キャンペーン入稿データ）
# =============================================================================

class SubmissionCampaign(Base):
    """個別キャンペーン入稿データ（1行 = 1キャンペーン + 1アドセット）"""
    __tablename__ = "submission_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("submission_batches.id", ondelete="CASCADE"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    # --- Campaign ---
    campaign_name: Mapped[str] = mapped_column(String(500), nullable=False)
    campaign_objective: Mapped[str] = mapped_column(String(50), nullable=False, default="WEBSITE_CLICKS")
    campaign_daily_budget: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # JPY
    campaign_total_budget: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # JPY
    campaign_budget_optimization: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    funding_instrument_id: Mapped[str] = mapped_column(String(100), nullable=False)

    # --- Line Item (Ad Group) ---
    line_item_name: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    bid_amount: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # JPY
    bid_strategy: Mapped[str] = mapped_column(String(50), default="AUTO")
    placements: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    start_time: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)  # ISO 8601
    end_time: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)  # ISO 8601

    # --- Targeting (JSON) ---
    target_platforms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target_gender: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    target_age_ranges: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target_locations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target_languages: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target_audiences: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    conversion_tag_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # 類似オーディエンス拡張
    audience_expansion: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # --- Tweet ---
    tweet_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    tweet_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # ダークポスト用

    # --- API結果 ---
    status: Mapped[str] = mapped_column(String(30), default="pending")
    # pending, submitting, success, failed, skipped
    api_campaign_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    api_line_item_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    api_targeting_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    api_promoted_tweet_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    api_tweet_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    api_response_raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_jst)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_jst, onupdate=now_jst
    )

    batch: Mapped[SubmissionBatch] = relationship(back_populates="campaigns")
