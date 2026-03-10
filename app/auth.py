"""ユーザー認証ヘルパー（Cookie セッション方式）"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User

COOKIE_NAME = "session"
MAX_AGE = 60 * 60 * 24 * 30  # 30日

_serializer = URLSafeSerializer(settings.SECRET_KEY, salt="user-session")


def create_session_cookie(user_id: int) -> str:
    """ユーザーIDを署名してCookie用文字列を返す"""
    return _serializer.dumps({"uid": user_id})


def get_user_id_from_cookie(request: Request) -> int | None:
    """リクエストのCookieからユーザーIDを取得（無効なら None）"""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        data = _serializer.loads(token)
        return data.get("uid")
    except BadSignature:
        return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """ログイン中のユーザーを返す。未ログインなら 401（API用）"""
    user_id = get_user_id_from_cookie(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="ログインが必要です")
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()  # noqa: E712
    if not user:
        raise HTTPException(status_code=401, detail="ログインが必要です")
    return user


def get_current_user_or_redirect(request: Request, db: Session = Depends(get_db)) -> User | None:
    """ログイン中のユーザーを返す。未ログインなら None（ページ用）"""
    user_id = get_user_id_from_cookie(request)
    if user_id is None:
        return None
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()  # noqa: E712
    return user
