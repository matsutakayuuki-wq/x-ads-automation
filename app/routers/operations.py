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


# ─── Helpers ─────────────────────────────────────────────────────────────

def _safe_micro_to_yen(value) -> int:
    if value is None:
        return 0
    try:
        return int(value) // 1_000_000
    except (TypeError, ValueError):
        return 0


def _fmt_time(dt: datetime) -> str:
    """X Ads API 用の ISO 8601 フォーマット（マイクロ秒なし）"""
    return dt.replace(microsecond=0).isoformat()


def _parse_stats(stats_data) -> dict[str, int]:
    """Stats APIレスポンスから campaign_id → billed micro のマップ"""
    result: dict[str, int] = {}
    if not stats_data or not isinstance(stats_data, list):
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
) -> tuple[dict[str, int], list[str]]:
    """Stats API をバッチ呼び出し。(stats_map, errors) を返す"""
    merged: dict[str, int] = {}
    errors: list[str] = []
    for i in range(0, len(campaign_ids), STATS_BATCH_SIZE):
        batch = campaign_ids[i : i + STATS_BATCH_SIZE]
        try:
            data = client.get_campaign_stats(
                account_id, batch, start_time=start_time, end_time=end_time,
            )
            merged.update(_parse_stats(data))
        except Exception as e:
            msg = f"batch[{i}:{i+len(batch)}] {type(e).__name__}: {e}"
            logger.warning("Stats batch failed: %s", msg)
            errors.append(msg)
    return merged, errors


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
    """直近7日間で広告費が発生したキャンペーン + 配信中を返す"""
    projects = (
        db.query(Project)
        .filter(Project.user_id == user.id, Project.is_active.is_(True))
        .order_by(Project.name)
        .all()
    )

    now = datetime.now(JST)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    # 全期間: 過去2年分（X Ads API上限付近）
    all_start = datetime(2024, 1, 1, tzinfo=JST)

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

        # ── 直近7日間の広告費（フィルタリング用） ──
        week_stats, week_errors = _fetch_stats_batched(
            client, cred.ads_account_id, campaign_ids,
            start_time=_fmt_time(week_start), end_time=_fmt_time(now),
        )

        # フィルタ: 7日間で広告費 > 0 or 配信中(ACTIVE)
        active_ids = set()
        for c in campaigns:
            cid = c.get("id")
            if not cid:
                continue
            if week_stats.get(cid, 0) > 0:
                active_ids.add(cid)
            elif c.get("entity_status") == "ACTIVE":
                active_ids.add(cid)

        if not active_ids:
            continue

        active_ids_list = list(active_ids)

        # ── 今日の広告費 ──
        today_stats, today_errors = _fetch_stats_batched(
            client, cred.ads_account_id, active_ids_list,
            start_time=_fmt_time(today_start), end_time=_fmt_time(now),
        )

        # ── 全期間の広告費 ──
        total_stats, total_errors = _fetch_stats_batched(
            client, cred.ads_account_id, active_ids_list,
            start_time=_fmt_time(all_start), end_time=_fmt_time(now),
        )

        # キャンペーンリスト構築
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
                "spend_today": _safe_micro_to_yen(today_stats.get(cid)),
                "spend_total": _safe_micro_to_yen(total_stats.get(cid)),
                "start_time": c.get("start_time"),
                "end_time": c.get("end_time"),
                "currency": c.get("currency", "JPY"),
            })

        proj_entry = {
            "project_id": proj.id,
            "project_name": proj.name,
            "ads_account_id": cred.ads_account_id,
            "error": None,
            "_stats_debug": {
                "week_stats_count": len(week_stats),
                "week_nonzero": sum(1 for v in week_stats.values() if v > 0),
                "today_stats_count": len(today_stats),
                "total_stats_count": len(total_stats),
                "total_nonzero": sum(1 for v in total_stats.values() if v > 0),
                "sample_week": dict(list(week_stats.items())[:3]),
                "errors": week_errors + today_errors + total_errors,
                "time_range": {
                    "week_start": _fmt_time(week_start),
                    "today_start": _fmt_time(today_start),
                    "all_start": _fmt_time(all_start),
                    "now": _fmt_time(now),
                },
            },
            "campaigns": campaign_list,
        }

        if campaign_list:
            result.append(proj_entry)

    return result


# ─── API: 診断 ───────────────────────────────────────────────────────────

@router.get("/api/operations/debug")
def debug_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Stats API の生レスポンスを返す"""
    projects = (
        db.query(Project)
        .filter(Project.user_id == user.id, Project.is_active.is_(True))
        .all()
    )
    for proj in projects:
        if not proj.credential:
            return {"error": "認証情報なし"}
        cred = proj.credential
        try:
            client = _build_client(cred)
        except Exception as e:
            return {"error": f"クライアント構築失敗: {type(e).__name__}: {e}"}

        # 最初の3キャンペーンでStats テスト
        try:
            campaigns = client.get_campaigns(cred.ads_account_id)
            if not campaigns:
                return {"error": "キャンペーン0件"}
            test_ids = [c["id"] for c in campaigns[:3]]
        except Exception as e:
            return {"campaigns_error": f"{type(e).__name__}: {e}"}

        now = datetime.now(JST)
        week_ago = now - timedelta(days=7)

        # 生レスポンスをそのまま返す
        try:
            raw = client._request(
                "GET", f"/stats/accounts/{cred.ads_account_id}",
                params={
                    "entity": "CAMPAIGN",
                    "entity_ids": ",".join(test_ids),
                    "start_time": _fmt_time(week_ago),
                    "end_time": _fmt_time(now),
                    "granularity": "TOTAL",
                    "metric_groups": "BILLING",
                    "placement": "ALL_ON_TWITTER",
                },
            )
            return {
                "test_campaign_ids": test_ids,
                "time_range": {
                    "start": _fmt_time(week_ago),
                    "end": _fmt_time(now),
                },
                "raw_response": raw,
            }
        except Exception as e:
            return {
                "stats_error": f"{type(e).__name__}: {e}",
                "test_campaign_ids": test_ids,
                "time_range": {
                    "start": _fmt_time(week_ago),
                    "end": _fmt_time(now),
                },
            }


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
