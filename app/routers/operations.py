"""運用（Campaign Operations）— アクティブキャンペーン管理"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import get_current_user
from app.models import Project, User, XAdsCredential
from app.services.x_ads_client import XAdsClient, XAdsApiError, micro_to_yen

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

JST = timezone(timedelta(hours=9))


def _build_client(cred: XAdsCredential) -> XAdsClient:
    return XAdsClient(
        api_key=cred.api_key,
        api_secret=cred.api_secret,
        access_token=cred.access_token,
        access_secret=cred.access_secret,
    )


# ─── Page ────────────────────────────────────────────────────────────────

@router.get("/operations", response_class=HTMLResponse)
def operations_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    projects = (
        db.query(Project)
        .filter(Project.user_id == user.id, Project.is_active.is_(True))
        .order_by(Project.name)
        .all()
    )
    return templates.TemplateResponse(
        "operations.html",
        {"request": request, "user": user, "projects": projects},
    )


# ─── API: キャンペーン一覧 + 統計 ──────────────────────────────────────

@router.get("/api/operations/campaigns")
def get_operations_campaigns(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """全アクティブ案件のキャンペーン一覧 + 今日/全体の広告費"""
    projects = (
        db.query(Project)
        .filter(Project.user_id == user.id, Project.is_active.is_(True))
        .order_by(Project.name)
        .all()
    )

    result = []
    for proj in projects:
        if not proj.credential:
            result.append({
                "project_id": proj.id,
                "project_name": proj.name,
                "error": "API認証情報が未設定です",
                "campaigns": [],
            })
            continue

        cred = proj.credential
        try:
            client = _build_client(cred)
            campaigns = client.get_campaigns(cred.ads_account_id)
        except XAdsApiError as e:
            result.append({
                "project_id": proj.id,
                "project_name": proj.name,
                "error": str(e),
                "campaigns": [],
            })
            continue

        if not campaigns:
            result.append({
                "project_id": proj.id,
                "project_name": proj.name,
                "error": None,
                "campaigns": [],
            })
            continue

        # 統計取得
        campaign_ids = [c["id"] for c in campaigns]
        now = datetime.now(JST)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # 全期間: 過去1年分（API上限）
        all_start = now - timedelta(days=365)

        today_stats = {}
        total_stats = {}
        try:
            today_data = client.get_campaign_stats(
                cred.ads_account_id,
                campaign_ids,
                start_time=today_start.isoformat(),
                end_time=now.isoformat(),
            )
            for item in today_data:
                cid = item.get("id")
                metrics = item.get("id_data", [{}])
                if metrics:
                    m = metrics[0].get("metrics", {})
                    billed = m.get("billed_charge_local_micro", [0])
                    if isinstance(billed, list):
                        billed = sum(billed) if billed else 0
                    today_stats[cid] = int(billed)
        except XAdsApiError as e:
            logger.warning("Stats (today) failed for %s: %s", proj.name, e)

        try:
            total_data = client.get_campaign_stats(
                cred.ads_account_id,
                campaign_ids,
                start_time=all_start.isoformat(),
                end_time=now.isoformat(),
            )
            for item in total_data:
                cid = item.get("id")
                metrics = item.get("id_data", [{}])
                if metrics:
                    m = metrics[0].get("metrics", {})
                    billed = m.get("billed_charge_local_micro", [0])
                    if isinstance(billed, list):
                        billed = sum(billed) if billed else 0
                    total_stats[cid] = int(billed)
        except XAdsApiError as e:
            logger.warning("Stats (total) failed for %s: %s", proj.name, e)

        campaign_list = []
        for c in campaigns:
            cid = c["id"]
            campaign_list.append({
                "id": cid,
                "name": c.get("name", ""),
                "entity_status": c.get("entity_status", "UNKNOWN"),
                "objective": c.get("objective", ""),
                "daily_budget": micro_to_yen(c.get("daily_budget_amount_local_micro", 0) or 0),
                "total_budget": micro_to_yen(c.get("total_budget_amount_local_micro", 0) or 0),
                "spend_today": micro_to_yen(today_stats.get(cid, 0)),
                "spend_total": micro_to_yen(total_stats.get(cid, 0)),
                "start_time": c.get("start_time"),
                "end_time": c.get("end_time"),
                "created_at": c.get("created_at"),
                "updated_at": c.get("updated_at"),
                "currency": c.get("currency", "JPY"),
            })

        result.append({
            "project_id": proj.id,
            "project_name": proj.name,
            "ads_account_id": cred.ads_account_id,
            "error": None,
            "campaigns": campaign_list,
        })

    return result


# ─── API: キャンペーンステータス更新 ─────────────────────────────────────

class StatusUpdate(BaseModel):
    entity_status: str  # ACTIVE or PAUSED
    project_id: int


@router.put("/api/operations/campaigns/{campaign_id}/status")
def update_campaign_status(
    campaign_id: str,
    body: StatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if body.entity_status not in ("ACTIVE", "PAUSED"):
        raise HTTPException(400, "entity_status must be ACTIVE or PAUSED")

    proj = db.query(Project).filter(
        Project.id == body.project_id,
        Project.user_id == user.id,
    ).first()
    if not proj:
        raise HTTPException(404, "案件が見つかりません")
    if not proj.credential:
        raise HTTPException(400, "API認証情報が未設定です")

    cred = proj.credential
    client = _build_client(cred)

    try:
        result = client.update_campaign(
            cred.ads_account_id,
            campaign_id,
            {"entity_status": body.entity_status},
        )
        return {
            "ok": True,
            "campaign_id": campaign_id,
            "entity_status": result.get("entity_status", body.entity_status),
        }
    except XAdsApiError as e:
        raise HTTPException(400, str(e))
