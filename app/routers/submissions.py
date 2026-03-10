"""入稿管理（バッチ作成・実行・履歴）"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_current_user_or_redirect
from app.database import get_db
from app.models import Project, SubmissionBatch, SubmissionCampaign, User, XAdsCredential
from app.schemas import (
    SubmissionBatchDetailResponse,
    SubmissionBatchResponse,
    SubmissionCampaignResponse,
    SubmissionCreate,
)

router = APIRouter(tags=["submissions"])
templates = Jinja2Templates(directory="app/templates")


# --- ページ ---

@router.get("/submissions", response_class=HTMLResponse)
def submissions_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_or_redirect),
):
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    batches = db.query(SubmissionBatch).filter(
        SubmissionBatch.user_id == user.id
    ).order_by(SubmissionBatch.created_at.desc()).all()
    return templates.TemplateResponse("submissions.html", {
        "request": request,
        "user": user,
        "batches": batches,
    })


@router.get("/submissions/new", response_class=HTMLResponse)
def submission_new_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_or_redirect),
):
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    projects = db.query(Project).filter(
        Project.user_id == user.id, Project.is_active == True  # noqa: E712
    ).order_by(Project.name).all()
    return templates.TemplateResponse("submission_new.html", {
        "request": request,
        "user": user,
        "projects": projects,
    })


@router.get("/submissions/{batch_id}", response_class=HTMLResponse)
def submission_detail_page(
    batch_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_or_redirect),
):
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    batch = db.query(SubmissionBatch).filter(
        SubmissionBatch.id == batch_id,
        SubmissionBatch.user_id == user.id,
    ).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return templates.TemplateResponse("submission_detail.html", {
        "request": request,
        "user": user,
        "batch": batch,
    })


# --- API ---

@router.get("/api/submissions")
def list_submissions(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """入稿バッチ一覧"""
    batches = db.query(SubmissionBatch).filter(
        SubmissionBatch.user_id == user.id
    ).order_by(SubmissionBatch.created_at.desc()).all()
    return [SubmissionBatchResponse.model_validate(b) for b in batches]


@router.post("/api/submissions")
def create_submission(
    data: SubmissionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """入稿バッチ作成（キャンペーンレコードも一緒に作成）"""
    # プロジェクト所有者チェック
    project = db.query(Project).filter(
        Project.id == data.project_id,
        Project.user_id == user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    from app.services.submission_service import SubmissionService

    service = SubmissionService(db)
    batch = service.create_batch(
        user_id=user.id,
        project_id=data.project_id,
        name=data.name,
        campaigns_data=[c.model_dump() for c in data.campaigns],
    )
    return SubmissionBatchResponse.model_validate(batch)


@router.post("/api/submissions/{batch_id}/submit")
def execute_submission(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """入稿実行（X Ads APIに送信）"""
    batch = db.query(SubmissionBatch).filter(
        SubmissionBatch.id == batch_id,
        SubmissionBatch.user_id == user.id,
    ).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    from app.services.submission_service import SubmissionService

    service = SubmissionService(db)
    try:
        result = service.execute_submission(batch_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return SubmissionBatchDetailResponse(
        **SubmissionBatchResponse.model_validate(result).model_dump(),
        campaigns=[SubmissionCampaignResponse.model_validate(c) for c in result.campaigns],
    )


@router.post("/api/submissions/{batch_id}/retry")
def retry_submission(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """失敗したキャンペーンをリトライ"""
    batch = db.query(SubmissionBatch).filter(
        SubmissionBatch.id == batch_id,
        SubmissionBatch.user_id == user.id,
    ).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    from app.services.submission_service import SubmissionService

    service = SubmissionService(db)
    result = service.retry_failed(batch_id)
    return SubmissionBatchDetailResponse(
        **SubmissionBatchResponse.model_validate(result).model_dump(),
        campaigns=[SubmissionCampaignResponse.model_validate(c) for c in result.campaigns],
    )


@router.get("/api/submissions/{batch_id}")
def get_submission(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """バッチ詳細取得"""
    batch = db.query(SubmissionBatch).filter(
        SubmissionBatch.id == batch_id,
        SubmissionBatch.user_id == user.id,
    ).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    return SubmissionBatchDetailResponse(
        **SubmissionBatchResponse.model_validate(batch).model_dump(),
        campaigns=[SubmissionCampaignResponse.model_validate(c) for c in batch.campaigns],
    )


@router.delete("/api/submissions/{batch_id}")
def delete_submission(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """ドラフトバッチを削除"""
    batch = db.query(SubmissionBatch).filter(
        SubmissionBatch.id == batch_id,
        SubmissionBatch.user_id == user.id,
    ).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.status not in ("draft", "failed"):
        raise HTTPException(status_code=400, detail="Can only delete draft or failed batches")
    db.delete(batch)
    db.commit()
    return {"ok": True}
