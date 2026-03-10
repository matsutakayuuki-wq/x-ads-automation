"""ユーザー登録・ログイン・ログアウト"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import COOKIE_NAME, MAX_AGE, create_session_cookie, get_user_id_from_cookie
from app.config import settings
from app.database import get_db
from app.models import User

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="app/templates")


# --- ページ ---
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    user_id = get_user_id_from_cookie(request)
    if user_id:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    user_id = get_user_id_from_cookie(request)
    if user_id:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("register.html", {"request": request})


# --- API ---
class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


@router.post("/api/login")
def api_login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not user.check_password(data.password):
        raise HTTPException(status_code=401, detail="メールアドレスまたはパスワードが正しくありません")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="このアカウントは無効です")

    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key=COOKIE_NAME,
        value=create_session_cookie(user.id),
        max_age=MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/api/register")
def api_register(data: RegisterRequest, db: Session = Depends(get_db)):
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="パスワードは6文字以上にしてください")

    existing = db.query(User).filter(
        (User.username == data.username) | (User.email == data.email)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="このユーザー名またはメールアドレスは既に使われています")

    admin_names = [n.strip() for n in settings.ADMIN_USERNAMES.split(",") if n.strip()]
    is_admin = data.username in admin_names

    if db.query(User).count() == 0:
        is_admin = True

    user = User(username=data.username, email=data.email, is_admin=is_admin)
    user.set_password(data.password)
    db.add(user)
    db.commit()
    db.refresh(user)

    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key=COOKIE_NAME,
        value=create_session_cookie(user.id),
        max_age=MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


class ProfileUpdateRequest(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None


@router.put("/api/profile")
def api_update_profile(
    data: ProfileUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_cookie(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="ログインが必要です")
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()  # noqa: E712
    if not user:
        raise HTTPException(status_code=401, detail="ログインが必要です")

    if data.username and data.username != user.username:
        existing = db.query(User).filter(User.username == data.username).first()
        if existing:
            raise HTTPException(status_code=400, detail="このユーザー名は既に使われています")
        user.username = data.username

    if data.email and data.email != user.email:
        existing = db.query(User).filter(User.email == data.email).first()
        if existing:
            raise HTTPException(status_code=400, detail="このメールアドレスは既に使われています")
        user.email = data.email

    db.commit()
    return {"ok": True, "username": user.username, "email": user.email}


@router.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response
