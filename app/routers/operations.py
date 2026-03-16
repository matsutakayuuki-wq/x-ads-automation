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
STATS_BATCH_SIZE = 20  # X Ads Stats API の entity_ids 上限


def _safe_micro_to_yen(value) -> int:
    if value is None:
        return 0
    try:
        return int(value) // 1_000_000
    except (TypeError, ValueError):
        return 0


def _parse_stats(stats_data: list[dict]) -> dict[str, int]:
    """Stats APIレスポンスから campaign_id → billed_charge_local_micro のマップを返す"""
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


def _fetch_stats_batched(
    client: XAdsClient,
    account_id: str,
    campaign_ids: list[str],
    start_time: str,
    end_time: str,
) -> dict[str, int]:
    """campaign_ids を STATS_BATCH_SIZE ずつ分割して Stats API を呼び出す"""
    merged: dict[str, int] = {}
    for i in range(0, len(campaign_ids), STATS_BATCH_SIZE):
        batch = campaign_ids[i : i + STATS_BATCH_SIZE]
        try:
            data = client.get_campaign_stats(
                account_id, batch, start_time=start_time, end_time=end_time,
            )
            merged.update(_parse_stats(data))
        except Exception as e:
            logger.warning("Stats batch failed (ids %d-%d): %s", i, i + len(batch), e)
    return merged


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
    """直近7日間で広告費が発生したキャンペーンを案件別に返す"""
    projects = (
        db.query(Project)
        .filter(Project.user_id == user.id, Project.is_active.is_(True))
        .order_by(Project.name)
        .all()
    )

    now = datetime.now(JST)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)

    result = []
    for proj in projects:
        if not proj.credential:
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
            continue

        campaign_ids = [c.get("id") for c in campaigns if c.get("id")]
        if not campaign_ids:
            continue

        # 直近7日間の広告費（フィルタ用 + 「全体」表示用）
        week_stats = _fetch_stats_batched(
            client, cred.ads_account_id, campaign_ids,
            start_time=week_start.isoformat(), end_time=now.isoformat(),
        )

        # 直近7日で広告費が発生したキャンペーンIDだけ抽出
        active_ids = {cid for cid, v in week_stats.items() if v > 0}

        # 配信中(ACTIVE)のキャンペーンも含める（広告費0でも運用中なので）
        for c in campaigns:
            if c.get("entity_status") == "ACTIVE" and c.get("id"):
                active_ids.add(c["id"])

        if not active_ids:
            continue

        # 今日の広告費
        today_ids = list(active_ids)
        today_stats = _fetch_stats_batched(
            client, cred.ads_account_id, today_ids,
            start_time=today_start.isoformat(), end_time=now.isoformat(),
        )

        # キャンペーンリスト構築（active_ids に含まれるもののみ）
        campaign_map = {c.get("id"): c for c in campaigns}
        campaign_list = []
        for cid in sorted(active_ids):
            c = campaign_map.get(cid)
            if not c:
                continue
            campaign_list.append({
                "id": cid,
                "name": c.get("name", ""),
                "entity_status": c.get("entity_status", "UNKNOWN"),
                "objective": c.get("objective", ""),
                "daily_budget": _safe_micro_to_yen(c.get("daily_budget_amount_local_micro")),
                "total_budget": _safe_micro_to_yen(c.get("total_budget_amount_local_micro")),
                "spend_today": _safe_micro_to_yen(today_stats.get(cid)),
                "spend_week": _safe_micro_to_yen(week_stats.get(cid)),
                "start_time": c.get("start_time"),
                "end_time": c.get("end_time"),
                "created_at": c.get("created_at"),
                "updated_at": c.get("updated_at"),
                "currency": c.get("currency", "JPY"),
            })

        if campaign_list:
            result.append({
                "project_id": proj.id,
                "project_name": proj.name,
                "ads_account_id": cred.ads_account_id,
                "error": None,
                "campaigns": campaign_list,
            })

    return result


# ─── API: 診断 ───────────────────────────────────────────────────────────

@router.get("/api/operations/debug")
def debug_all_campaigns(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Stats API の生レスポンスを確認するデバッグ用"""
    projects = (
        db.query(Project)
        .filter(Project.user_id == user.id, Project.is_active.is_(True))
        .all()
    )
    results = []
    for proj in projects:
        info: dict = {"project_id": proj.id, "project_name": proj.name}
        if not proj.credential:
            info["error"] = "API認証情報が未設定"
            results.append(info)
            continue

        cred = proj.credential
        info["ads_account_id"] = cred.ads_account_id

        try:
            client = _build_client(cred)
        except Exception as e:
            info["error"] = f"クライアント構築失敗: {type(e).__name__}: {e}"
            results.append(info)
            continue

        # キャンペーン取得
        try:
            campaigns_raw = client._request("GET", f"/accounts/{cred.ads_account_id}/campaigns")
            data = campaigns_raw.get("data", [])
            info["campaigns_count"] = len(data) if isinstance(data, list) else 0
        except Exception as e:
            info["campaigns_error"] = f"{type(e).__name__}: {e}"
            results.append(info)
            continue

        # Stats テスト（最初の5件のみ）
        if isinstance(data, list) and data:
            test_ids = [c.get("id") for c in data[:5] if c.get("id")]
            if test_ids:
                now = datetime.now(JST)
                week_ago = now - timedelta(days=7)
                try:
                    stats_raw = client._request(
                        "GET", f"/stats/accounts/{cred.ads_account_id}",
                        params={
                            "entity": "CAMPAIGN",
                            "entity_ids": ",".join(test_ids),
                            "start_time": week_ago.isoformat(),
                            "end_time": now.isoformat(),
                            "granularity": "TOTAL",
                            "metric_groups": "BILLING",
                        },
                    )
                    info["stats_raw_keys"] = list(stats_raw.keys()) if isinstance(stats_raw, dict) else str(type(stats_raw))
                    stats_data = stats_raw.get("data", [])
                    info["stats_count"] = len(stats_data) if isinstance(stats_data, list) else 0
                    if isinstance(stats_data, list) and stats_data:
                        info["stats_sample"] = stats_data[0]
                except Exception as e:
                    info["stats_error"] = f"{type(e).__name__}: {e}"

        results.append(info)
    return results


# ─── API: キャンペーンステータス更新 ─────────────────────────────────────

class StatusUpdate(BaseModel):
    entity_status: str
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
