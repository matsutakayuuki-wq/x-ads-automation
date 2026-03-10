"""認証ミドルウェア。

ログインしていないユーザーをログインページにリダイレクトする。
APIアクセス（/api/...）で未認証の場合は 401 を返す。
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from app.auth import get_user_id_from_cookie

# 認証不要のパス
PUBLIC_PATHS = {"/login", "/register", "/api/login", "/api/register", "/docs", "/openapi.json", "/redoc"}
PUBLIC_PREFIXES = ("/static/",)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 公開パスはスキップ
        if path in PUBLIC_PATHS:
            return await call_next(request)
        for prefix in PUBLIC_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        # ログインチェック
        user_id = get_user_id_from_cookie(request)
        if user_id is None:
            if path.startswith("/api/"):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "ログインが必要です"},
                )
            return RedirectResponse(url="/login", status_code=302)

        return await call_next(request)
