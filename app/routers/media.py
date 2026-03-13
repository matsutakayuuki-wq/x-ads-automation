"""メディアライブラリ管理"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_current_user_or_redirect
from app.database import get_db
from app.models import MediaAsset, User
from app.schemas import MediaAssetResponse

router = APIRouter(tags=["media"])
templates = Jinja2Templates(directory="app/templates")

MEDIA_DIR = Path("data/media")
ALLOWED_MIME = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "video/mp4", "video/quicktime", "video/webm",
}
MAX_FILE_SIZE = 512 * 1024 * 1024  # 512MB


def _user_media_dir(user_id: int) -> Path:
    d = MEDIA_DIR / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- ページ ---
@router.get("/media", response_class=HTMLResponse)
def media_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_or_redirect),
):
    if not user:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/login", status_code=302)
    assets = db.query(MediaAsset).filter(
        MediaAsset.user_id == user.id
    ).order_by(MediaAsset.created_at.desc()).all()
    # テンプレート内で tojson フィルターを使用するため、
    # SQLAlchemy オブジェクトを JSON シリアライズ可能な辞書に変換する
    assets_data = [
        {
            "id": a.id,
            "filename": a.filename,
            "original_filename": a.original_filename,
            "mime_type": a.mime_type,
            "file_size": a.file_size,
            "width": a.width,
            "height": a.height,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in assets
    ]
    return templates.TemplateResponse("media.html", {
        "request": request, "user": user, "assets": assets_data,
    })


# --- API ---
@router.get("/api/media")
def list_media(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    assets = db.query(MediaAsset).filter(
        MediaAsset.user_id == user.id
    ).order_by(MediaAsset.created_at.desc()).all()
    return [MediaAssetResponse.model_validate(a) for a in assets]


@router.post("/api/media/upload")
async def upload_media(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(400, f"非対応のファイル形式: {file.content_type}")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, "ファイルサイズが大きすぎます（上限512MB）")

    ext = os.path.splitext(file.filename or "file")[1] or ".bin"
    filename = f"{uuid.uuid4().hex}{ext}"
    save_path = _user_media_dir(user.id) / filename
    save_path.write_bytes(content)

    # 画像サイズ取得
    width, height = None, None
    if file.content_type and file.content_type.startswith("image/"):
        try:
            from PIL import Image
            from io import BytesIO
            img = Image.open(BytesIO(content))
            width, height = img.size
        except Exception:
            pass

    asset = MediaAsset(
        user_id=user.id,
        filename=filename,
        original_filename=file.filename or "unknown",
        mime_type=file.content_type or "application/octet-stream",
        file_size=len(content),
        width=width,
        height=height,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return MediaAssetResponse.model_validate(asset)


@router.delete("/api/media/{media_id}")
def delete_media(
    media_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    asset = db.query(MediaAsset).filter(
        MediaAsset.id == media_id, MediaAsset.user_id == user.id
    ).first()
    if not asset:
        raise HTTPException(404, "メディアが見つかりません")

    file_path = _user_media_dir(user.id) / asset.filename
    if file_path.exists():
        file_path.unlink()

    db.delete(asset)
    db.commit()
    return {"ok": True}


@router.get("/api/media/{media_id}/file")
def serve_media(
    media_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    asset = db.query(MediaAsset).filter(
        MediaAsset.id == media_id, MediaAsset.user_id == user.id
    ).first()
    if not asset:
        raise HTTPException(404, "メディアが見つかりません")

    file_path = _user_media_dir(user.id) / asset.filename
    if not file_path.exists():
        raise HTTPException(404, "ファイルが見つかりません")

    return FileResponse(
        path=str(file_path),
        media_type=asset.mime_type,
        filename=asset.original_filename,
    )
