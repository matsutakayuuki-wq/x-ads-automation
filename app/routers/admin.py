"""管理者画面"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_current_user_or_redirect
from app.database import get_db
from app.models import Project, SubmissionBatch, SubmissionCampaign, User, XAdsCredential

router = APIRouter(tags=["admin"])
templates = Jinja2Templates(directory="app/templates")


def _require_admin(user: User):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")


@router.get("/admin", response_class=HTMLResponse)
def admin_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_or_redirect),
):
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    _require_admin(user)

    users = db.query(User).order_by(User.created_at.desc()).all()
    total_batches = db.query(SubmissionBatch).count()
    total_campaigns = db.query(SubmissionCampaign).count()
    succeeded_campaigns = db.query(SubmissionCampaign).filter(
        SubmissionCampaign.status == "success"
    ).count()

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "user": user,
        "users": users,
        "total_batches": total_batches,
        "total_campaigns": total_campaigns,
        "succeeded_campaigns": succeeded_campaigns,
    })


@router.post("/api/admin/users/{user_id}/toggle-active")
def toggle_user_active(
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_admin(user)
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == user.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
    target.is_active = not target.is_active
    db.commit()
    return {"ok": True, "is_active": target.is_active}


@router.post("/api/admin/users/{user_id}/toggle-admin")
def toggle_user_admin(
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_admin(user)
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == user.id:
        raise HTTPException(status_code=400, detail="Cannot change your own admin status")
    target.is_admin = not target.is_admin
    db.commit()
    return {"ok": True, "is_admin": target.is_admin}
