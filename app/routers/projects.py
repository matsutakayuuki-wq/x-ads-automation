"""案件管理 & オーディエンス管理"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_current_user_or_redirect
from app.database import get_db
from app.models import Audience, Project, User, XAdsCredential
from app.schemas import (
    AudienceCreate,
    AudienceResponse,
    AudienceUpdate,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
)

router = APIRouter(tags=["projects"])
templates = Jinja2Templates(directory="app/templates")


def _get_user_project(db: Session, user: User, project_id: int) -> Project:
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="案件が見つかりません")
    return project


def _get_user_audience(db: Session, user: User, audience_id: int) -> Audience:
    audience = db.query(Audience).join(Project).filter(
        Audience.id == audience_id,
        Project.user_id == user.id,
    ).first()
    if not audience:
        raise HTTPException(status_code=404, detail="オーディエンスが見つかりません")
    return audience


# --- ページ ---
@router.get("/projects", response_class=HTMLResponse)
def projects_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_or_redirect),
):
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    projects = db.query(Project).filter(
        Project.user_id == user.id
    ).order_by(Project.created_at.desc()).all()
    credentials = db.query(XAdsCredential).filter(
        XAdsCredential.user_id == user.id, XAdsCredential.is_active == True  # noqa: E712
    ).all()
    return templates.TemplateResponse("projects.html", {
        "request": request,
        "user": user,
        "projects": projects,
        "credentials": credentials,
    })


@router.get("/projects/{project_id}", response_class=HTMLResponse)
def project_detail_page(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_or_redirect),
):
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    project = _get_user_project(db, user, project_id)
    credentials = db.query(XAdsCredential).filter(
        XAdsCredential.user_id == user.id, XAdsCredential.is_active == True  # noqa: E712
    ).all()
    return templates.TemplateResponse("project_detail.html", {
        "request": request,
        "user": user,
        "project": project,
        "credentials": credentials,
    })


# --- Project API ---
@router.get("/api/projects")
def list_projects(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    projects = db.query(Project).filter(
        Project.user_id == user.id
    ).order_by(Project.created_at.desc()).all()
    return [ProjectResponse.model_validate(p) for p in projects]


@router.post("/api/projects")
def create_project(
    data: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if data.credential_id:
        cred = db.query(XAdsCredential).filter(
            XAdsCredential.id == data.credential_id,
            XAdsCredential.user_id == user.id,
        ).first()
        if not cred:
            raise HTTPException(status_code=400, detail="無効な認証情報です")

    project = Project(
        user_id=user.id,
        **data.model_dump(),
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return ProjectResponse.model_validate(project)


@router.get("/api/projects/{project_id}")
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = _get_user_project(db, user, project_id)
    return ProjectResponse.model_validate(project)


@router.put("/api/projects/{project_id}")
def update_project(
    project_id: int,
    data: ProjectUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = _get_user_project(db, user, project_id)

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(project, key, value)

    db.commit()
    db.refresh(project)
    return ProjectResponse.model_validate(project)


@router.delete("/api/projects/{project_id}")
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = _get_user_project(db, user, project_id)
    db.delete(project)
    db.commit()
    return {"ok": True}


# --- Audience API ---
@router.get("/api/projects/{project_id}/audiences")
def list_audiences(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = _get_user_project(db, user, project_id)
    return [AudienceResponse.model_validate(a) for a in project.audiences]


@router.post("/api/projects/{project_id}/audiences")
def create_audience(
    project_id: int,
    data: AudienceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = _get_user_project(db, user, project_id)
    audience = Audience(
        project_id=project.id,
        **data.model_dump(),
    )
    db.add(audience)
    db.commit()
    db.refresh(audience)
    return AudienceResponse.model_validate(audience)


@router.get("/api/audiences/{audience_id}")
def get_audience(
    audience_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    audience = _get_user_audience(db, user, audience_id)
    return AudienceResponse.model_validate(audience)


@router.put("/api/audiences/{audience_id}")
def update_audience(
    audience_id: int,
    data: AudienceUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    audience = _get_user_audience(db, user, audience_id)

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(audience, key, value)

    db.commit()
    db.refresh(audience)
    return AudienceResponse.model_validate(audience)


@router.delete("/api/audiences/{audience_id}")
def delete_audience(
    audience_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    audience = _get_user_audience(db, user, audience_id)
    db.delete(audience)
    db.commit()
    return {"ok": True}
