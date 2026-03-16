"""運用（Campaign Operations）— アクティブキャンペーン管理"""
from __future__ import annotations

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
from app.services.x_ads_client import XAdsClient, XAdsApiError

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

JST = timezone(timedelta(hours=9))


def _safe_micro_to_yen(value) -> int:
    """None/文字列/不正値でもクラッシュしない micro→yen 変換"""
    if value is None:
        return 0
    try:
        return int(value) // 1_000_000
    except (TypeError, ValueError):
        return 0


def _parse_stats(stats_data: list[dict]) -> dict[str, int]:
    """Stats APIレスポンスからキャンペーンID→billed_charge_local_micro のマップを返す"""
    result: dict[str, int] = {}
    if not stats_data:
        return result
    for item in stats_data:
        cid = item.get("id")
        if not cid:
            continue
        try:
            id_data = item.get("id_data", [])
            if not id_data:
                continue
            metrics = id_data[0].get("metrics", {})
            billed = metrics.get("billed_charge_local_micro")
            if billed is None:
                continue
            if isinstance(billed, list):
                billed = sum(int(b) for b in billed if b is not None) if billed else 0
            result[cid] = int(billed)
        except Exception as e:
            logger.debug("Stats parse error for campaign %s: %s", cid, e)
    return result


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
        except Exception as e:
            logger.warning("get_campaigns failed for %s: %s", proj.name, e)
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
        campaign_ids = [c.get("id") for c in campaigns if c.get("id")]
        now = datetime.now(JST)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        all_start = now - timedelta(days=365)

        today_stats: dict[str, int] = {}
        total_stats: dict[str, int] = {}

        if campaign_ids:
            try:
                today_data = client.get_campaign_stats(
                    cred.ads_account_id,
                    campaign_ids,
                    start_time=today_start.isoformat(),
                    end_time=now.isoformat(),
                )
                today_stats = _parse_stats(today_data)
            except Exception as e:
                logger.warning("Stats (today) failed for %s: %s", proj.name, e)

            try:
                total_data = client.get_campaign_stats(
                    cred.ads_account_id,
                    campaign_ids,
                    start_time=all_start.isoformat(),
                    end_time=now.isoformat(),
                )
                total_stats = _parse_stats(total_data)
            except Exception as e:
                logger.warning("Stats (total) failed for %s: %s", proj.name, e)

        campaign_list = []
        for c in campaigns:
            cid = c.get("id", "")
            try:
                daily_budget = _safe_micro_to_yen(c.get("daily_budget_amount_local_micro"))
                total_budget = _safe_micro_to_yen(c.get("total_budget_amount_local_micro"))
            except Exception:
                daily_budget = 0
                total_budget = 0
            campaign_list.append({
                "id": cid,
                "name": c.get("name", ""),
                "entity_status": c.get("entity_status", "UNKNOWN"),
                "objective": c.get("objective", ""),
                "daily_budget": daily_budget,
                "total_budget": total_budget,
                "spend_today": _safe_micro_to_yen(today_stats.get(cid)),
                "spend_total": _safe_micro_to_yen(total_stats.get(cid)),
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


# ─── API: 診断（デバッグ用） ──────────────────────────────────────────

@router.get("/api/operations/debug/{project_id}")
def debug_project_campaigns(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """X Ads APIの生レスポンスを返す（デバッグ用）"""
    proj = db.query(Project).filter(
        Project.id == project_id, Project.user_id == user.id
    ).first()
    if not proj:
        return {"error": "案件が見つかりません"}
    if not proj.credential:
        return {"error": "API認証情報が未設定", "credential_id": proj.credential_id}

    cred = proj.credential
    info = {
        "project_name": proj.name,
        "ads_account_id": cred.ads_account_id,
        "credential_name": cred.name,
    }

    try:
        client = _build_client(cred)
    except Exception as e:
        return {**info, "error": f"クライアント構築失敗: {e}"}

    # 生のAPIレスポンスを取得
    try:
        raw = client._request("GET", f"/accounts/{cred.ads_account_id}/campaigns")
        info["raw_response_keys"] = list(raw.keys()) if isinstance(raw, dict) else str(type(raw))
        info["data_type"] = raw.get("data_type")
        info["total_count"] = raw.get("total_count")
        data = raw.get("data")
        if isinstance(data, list):
            info["campaigns_count"] = len(data)
            info["campaigns"] = [
                {
                    "id": c.get("id"),
                    "name": c.get("name"),
                    "entity_status": c.get("entity_status"),
                }
                for c in data[:20]
            ]
        else:
            info["data_raw"] = str(data)[:1000]
    except Exception as e:
        info["api_error"] = str(e)
        info["api_error_type"] = type(e).__name__

    return info


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
    except Exception as e:
        logger.warning("update_campaign failed: %s", e)
        raise HTTPException(400, str(e))
