"""ダッシュボード"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import get_current_user_or_redirect
from app.database import get_db
from app.models import Project, SubmissionBatch, XAdsCredential, User

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return RedirectResponse(url="/dashboard", status_code=302)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_or_redirect),
):
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    credentials_count = db.query(XAdsCredential).filter(
        XAdsCredential.user_id == user.id
    ).count()
    projects_count = db.query(Project).filter(
        Project.user_id == user.id
    ).count()
    total_batches = db.query(SubmissionBatch).filter(
        SubmissionBatch.user_id == user.id
    ).count()
    completed_batches = db.query(SubmissionBatch).filter(
        SubmissionBatch.user_id == user.id,
        SubmissionBatch.status == "completed",
    ).count()

    recent_batches = (
        db.query(SubmissionBatch)
        .filter(SubmissionBatch.user_id == user.id)
        .order_by(SubmissionBatch.created_at.desc())
        .limit(10)
        .all()
    )

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "credentials_count": credentials_count,
        "projects_count": projects_count,
        "total_batches": total_batches,
        "completed_batches": completed_batches,
        "recent_batches": recent_batches,
    })
