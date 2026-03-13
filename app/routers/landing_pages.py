"""LP（ランディングページ）ストック管理"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import LandingPage, Project, User
from app.schemas import (
    LandingPageBulkCreate,
    LandingPageCreate,
    LandingPageResponse,
    LandingPageUpdate,
)

router = APIRouter(tags=["landing_pages"])
templates = Jinja2Templates(directory="app/templates")


def _get_user_project(db: Session, user: User, project_id: int) -> Project:
    project = db.query(Project).filter(
        Project.id == project_id, Project.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(404, "案件が見つかりません")
    return project


def _get_user_lp(db: Session, user: User, lp_id: int) -> LandingPage:
    lp = db.query(LandingPage).join(Project).filter(
        LandingPage.id == lp_id, Project.user_id == user.id
    ).first()
    if not lp:
        raise HTTPException(404, "LPが見つかりません")
    return lp


# ── HTML Page ──────────────────────────────────────────────────────────────
@router.get("/lp", response_class=HTMLResponse)
def lp_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    projects = db.query(Project).filter(Project.user_id == user.id).order_by(
        Project.created_at.desc()
    ).all()
    return templates.TemplateResponse("lp.html", {
        "request": request,
        "user": user,
        "projects": projects,
    })


# ── API ────────────────────────────────────────────────────────────────────
@router.get("/api/projects/{project_id}/landing-pages")
def list_landing_pages(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _get_user_project(db, user, project_id)
    lps = db.query(LandingPage).filter(
        LandingPage.project_id == project_id
    ).order_by(LandingPage.created_at.desc()).all()
    return [LandingPageResponse.model_validate(lp) for lp in lps]


@router.post("/api/projects/{project_id}/landing-pages")
def create_landing_page(
    project_id: int,
    data: LandingPageCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _get_user_project(db, user, project_id)
    lp = LandingPage(
        project_id=project_id,
        name=data.name or "",
        url=data.url,
        description=data.description,
    )
    db.add(lp)
    db.commit()
    db.refresh(lp)
    return LandingPageResponse.model_validate(lp)


@router.post("/api/projects/{project_id}/landing-pages/bulk")
def bulk_create_landing_pages(
    project_id: int,
    data: LandingPageBulkCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """複数LPを一括登録"""
    _get_user_project(db, user, project_id)
    created = []
    for i, url in enumerate(data.urls):
        url = url.strip()
        if not url:
            continue
        name = ""
        if data.names and i < len(data.names):
            name = data.names[i] or ""
        lp = LandingPage(project_id=project_id, name=name, url=url)
        db.add(lp)
        created.append(lp)
    db.commit()
    for lp in created:
        db.refresh(lp)
    return [LandingPageResponse.model_validate(lp) for lp in created]


@router.put("/api/landing-pages/{lp_id}")
def update_landing_page(
    lp_id: int,
    data: LandingPageUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    lp = _get_user_lp(db, user, lp_id)
    if data.name is not None:
        lp.name = data.name
    if data.url is not None:
        lp.url = data.url
    if data.description is not None:
        lp.description = data.description
    if data.is_used is not None:
        lp.is_used = data.is_used
    db.commit()
    db.refresh(lp)
    return LandingPageResponse.model_validate(lp)


@router.delete("/api/landing-pages/{lp_id}")
def delete_landing_page(
    lp_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    lp = _get_user_lp(db, user, lp_id)
    db.delete(lp)
    db.commit()
    return {"ok": True}
