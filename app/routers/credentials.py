"""X Ads API 認証情報管理"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_current_user_or_redirect
from app.database import get_db
from app.models import User, XAdsCredential
from app.schemas import CredentialCreate, CredentialResponse, CredentialUpdate

router = APIRouter(tags=["credentials"])
templates = Jinja2Templates(directory="app/templates")


def _get_user_credential(db: Session, user: User, credential_id: int) -> XAdsCredential:
    """ユーザーの認証情報を取得（所有者チェック付き）"""
    cred = db.query(XAdsCredential).filter(
        XAdsCredential.id == credential_id,
        XAdsCredential.user_id == user.id,
    ).first()
    if not cred:
        raise HTTPException(status_code=404, detail="認証情報が見つかりません")
    return cred


# --- ページ ---
@router.get("/credentials", response_class=HTMLResponse)
def credentials_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_or_redirect),
):
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    credentials = db.query(XAdsCredential).filter(
        XAdsCredential.user_id == user.id
    ).order_by(XAdsCredential.created_at.desc()).all()
    return templates.TemplateResponse("credentials.html", {
        "request": request,
        "user": user,
        "credentials": credentials,
    })


# --- API ---
@router.get("/api/credentials")
def list_credentials(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    creds = db.query(XAdsCredential).filter(
        XAdsCredential.user_id == user.id
    ).order_by(XAdsCredential.created_at.desc()).all()
    return [CredentialResponse.model_validate(c) for c in creds]


@router.post("/api/credentials")
def create_credential(
    data: CredentialCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cred = XAdsCredential(
        user_id=user.id,
        name=data.name,
        ads_account_id=data.ads_account_id,
    )
    cred.api_key = data.api_key
    cred.api_secret = data.api_secret
    cred.access_token = data.access_token
    cred.access_secret = data.access_secret
    db.add(cred)
    db.commit()
    db.refresh(cred)
    return CredentialResponse.model_validate(cred)


@router.put("/api/credentials/{credential_id}")
def update_credential(
    credential_id: int,
    data: CredentialUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cred = _get_user_credential(db, user, credential_id)

    if data.name is not None:
        cred.name = data.name
    if data.ads_account_id is not None:
        cred.ads_account_id = data.ads_account_id
    if data.api_key is not None:
        cred.api_key = data.api_key
    if data.api_secret is not None:
        cred.api_secret = data.api_secret
    if data.access_token is not None:
        cred.access_token = data.access_token
    if data.access_secret is not None:
        cred.access_secret = data.access_secret
    if data.is_active is not None:
        cred.is_active = data.is_active

    db.commit()
    db.refresh(cred)
    return CredentialResponse.model_validate(cred)


@router.delete("/api/credentials/{credential_id}")
def delete_credential(
    credential_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cred = _get_user_credential(db, user, credential_id)
    db.delete(cred)
    db.commit()
    return {"ok": True}


@router.post("/api/credentials/{credential_id}/verify")
def verify_credential(
    credential_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """API認証情報を検証（X Ads APIに接続テスト）"""
    cred = _get_user_credential(db, user, credential_id)

    from app.services.x_ads_client import XAdsClient, XAdsApiError

    try:
        client = XAdsClient(
            api_key=cred.api_key,
            api_secret=cred.api_secret,
            access_token=cred.access_token,
            access_secret=cred.access_secret,
        )
        account = client.get_account(cred.ads_account_id)
        return {
            "ok": True,
            "account": {
                "id": account.get("id"),
                "name": account.get("name"),
                "approval_status": account.get("approval_status"),
                "currency": account.get("currency"),
            },
        }
    except XAdsApiError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"接続エラー: {str(e)}"}


@router.get("/api/credentials/{credential_id}/funding-instruments")
def get_funding_instruments(
    credential_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """支払い方法一覧を取得"""
    cred = _get_user_credential(db, user, credential_id)

    from app.services.x_ads_client import XAdsClient, XAdsApiError

    try:
        client = XAdsClient(
            api_key=cred.api_key,
            api_secret=cred.api_secret,
            access_token=cred.access_token,
            access_secret=cred.access_secret,
        )
        instruments = client.get_funding_instruments(cred.ads_account_id)
        return {"ok": True, "data": instruments}
    except XAdsApiError as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/credentials/{credential_id}/test-line-item")
def test_line_item(
    credential_id: int,
    request_body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Line Item作成テスト（デバッグ用）- 最小パラメータから段階的にテスト"""
    cred = _get_user_credential(db, user, credential_id)

    from app.services.x_ads_client import XAdsClient, XAdsApiError

    client = XAdsClient(
        api_key=cred.api_key,
        api_secret=cred.api_secret,
        access_token=cred.access_token,
        access_secret=cred.access_secret,
    )
    account_id = cred.ads_account_id

    # リクエストボディのparamsをそのまま送信
    params = request_body.get("params", {})
    try:
        result = client.create_line_item(account_id, params)
        return {"ok": True, "data": result}
    except XAdsApiError as e:
        return {"ok": False, "error": str(e), "status_code": e.status_code, "errors": e.errors}


@router.get("/api/credentials/{credential_id}/targeting-locations")
def get_targeting_locations(
    credential_id: int,
    location_type: str = "COUNTRIES",
    q: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """ロケーションターゲティング選択肢を取得"""
    cred = _get_user_credential(db, user, credential_id)

    from app.services.x_ads_client import XAdsClient, XAdsApiError

    try:
        client = XAdsClient(
            api_key=cred.api_key,
            api_secret=cred.api_secret,
            access_token=cred.access_token,
            access_secret=cred.access_secret,
        )
        locations = client.get_targeting_locations(query=q, location_type=location_type)
        return {"ok": True, "data": locations}
    except XAdsApiError as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/credentials/{credential_id}/conversion-tags")
def get_conversion_tags(
    credential_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """コンバージョンタグ一覧を取得"""
    cred = _get_user_credential(db, user, credential_id)

    from app.services.x_ads_client import XAdsClient, XAdsApiError

    try:
        client = XAdsClient(
            api_key=cred.api_key,
            api_secret=cred.api_secret,
            access_token=cred.access_token,
            access_secret=cred.access_secret,
        )
        tags = client.get_conversion_tags(cred.ads_account_id)
        return {"ok": True, "data": tags}
    except XAdsApiError as e:
        return {"ok": False, "error": str(e)}
