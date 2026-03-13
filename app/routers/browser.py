"""ブラウザセッション管理 & Ads Editor アップロード"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Project, SubmissionBatch, User, XAdsCredential, now_jst

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/browser", tags=["browser"])

# メモリ上のログインセッション管理
_active_login_sessions: dict[int, object] = {}


# ---------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------

@router.get("/session/{credential_id}/status")
def session_status(
    credential_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """セッション状態を確認"""
    cred = db.query(XAdsCredential).filter(
        XAdsCredential.id == credential_id,
        XAdsCredential.user_id == user.id,
    ).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")

    from app.services.browser_uploader import SESSIONS_DIR
    session_file = SESSIONS_DIR / str(credential_id) / "state.json"

    return {
        "credential_id": credential_id,
        "session_exists": session_file.exists(),
    }


@router.post("/session/{credential_id}/login")
async def start_login_session(
    credential_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """ログイン用ブラウザを起動（ヘッド付き）"""
    cred = db.query(XAdsCredential).filter(
        XAdsCredential.id == credential_id,
        XAdsCredential.user_id == user.id,
    ).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")

    from app.services.browser_uploader import XAdsEditorUploader

    uploader = XAdsEditorUploader(credential_id)
    await uploader.launch_for_login()
    _active_login_sessions[credential_id] = uploader

    return {
        "ok": True,
        "message": "Browser opened. Please login to ads.x.com, then click Save Session.",
    }


@router.post("/session/{credential_id}/save")
async def save_login_session(
    credential_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """ログインセッションを保存してブラウザを閉じる"""
    cred = db.query(XAdsCredential).filter(
        XAdsCredential.id == credential_id,
        XAdsCredential.user_id == user.id,
    ).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")

    uploader = _active_login_sessions.get(credential_id)
    if not uploader:
        raise HTTPException(status_code=400, detail="No active login session")

    await uploader.save_session()
    await uploader.close()
    del _active_login_sessions[credential_id]

    return {"ok": True, "message": "Session saved successfully"}


@router.post("/session/{credential_id}/check")
async def check_session(
    credential_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """セッションが有効か検証"""
    cred = db.query(XAdsCredential).filter(
        XAdsCredential.id == credential_id,
        XAdsCredential.user_id == user.id,
    ).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")

    from app.services.browser_uploader import XAdsEditorUploader

    uploader = XAdsEditorUploader(credential_id)
    is_valid = await uploader.check_session_valid()

    return {
        "credential_id": credential_id,
        "session_valid": is_valid,
    }


# ---------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------

@router.post("/upload/{batch_id}")
async def upload_excel_to_ads_editor(
    batch_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """ExcelファイルをX Ads Editorにアップロード"""
    batch = db.query(SubmissionBatch).filter(
        SubmissionBatch.id == batch_id,
        SubmissionBatch.user_id == user.id,
    ).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    # 二重アップロード防止
    if batch.upload_status == "uploading":
        raise HTTPException(
            status_code=409,
            detail="このバッチは現在アップロード中です。完了をお待ちください。",
        )

    project = db.query(Project).filter(Project.id == batch.project_id).first()
    if not project or not project.credential_id:
        raise HTTPException(
            status_code=400,
            detail="Project credential not configured",
        )

    credential = db.query(XAdsCredential).filter(
        XAdsCredential.id == project.credential_id,
    ).first()
    if not credential:
        raise HTTPException(status_code=400, detail="Credential not found")

    from app.services.browser_uploader import XAdsEditorUploader

    uploader = XAdsEditorUploader(credential.id)
    if not uploader.session_exists:
        raise HTTPException(
            status_code=400,
            detail="No browser session. Please login first from API Settings.",
        )

    batch.upload_status = "uploading"
    batch.upload_error = None
    db.commit()

    background_tasks.add_task(
        _background_upload,
        batch_id=batch.id,
        credential_id=credential.id,
        ads_account_id=credential.ads_account_id,
        project_id=project.id,
    )

    return {
        "ok": True,
        "message": "Upload started",
        "batch_id": batch.id,
    }


@router.get("/upload/{batch_id}/status")
def upload_status(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """アップロード進捗を取得"""
    batch = db.query(SubmissionBatch).filter(
        SubmissionBatch.id == batch_id,
        SubmissionBatch.user_id == user.id,
    ).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    return {
        "batch_id": batch.id,
        "upload_status": batch.upload_status,
        "upload_error": batch.upload_error,
    }


# ---------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------

async def _background_upload(
    batch_id: int,
    credential_id: int,
    ads_account_id: str,
    project_id: int,
):
    """バックグラウンドでポスト作成 → Excel生成 → ブラウザアップロード"""
    from app.database import SessionLocal
    from app.services.browser_uploader import (
        BrowserSessionError,
        SessionExpiredError,
        XAdsEditorUploader,
    )
    from app.services.excel_generator import ExcelGenerator

    db = SessionLocal()
    try:
        batch = db.query(SubmissionBatch).filter(
            SubmissionBatch.id == batch_id
        ).first()
        project = db.query(Project).filter(Project.id == project_id).first()

        # ----------------------------------------------------------
        # Pre-step: tweet_text がある場合、ブラウザ経由でダークポストを
        #           作成して tweet_ids にセットする（Excel に反映するため）
        # ----------------------------------------------------------
        await _create_tweets_via_browser(
            db, batch, credential_id, ads_account_id,
        )

        # ----------------------------------------------------------
        # Validation: ツイートIDが無いキャンペーンがあればエラー
        # tweet_text があるのに tweet_ids が空 → ポスト作成に失敗
        # tweet_text も tweet_ids もない → 入力ミス
        # ----------------------------------------------------------
        db.refresh(batch)
        missing_tweet_campaigns = []
        for campaign in batch.campaigns:
            has_tweet_ids = bool(campaign.tweet_ids and campaign.tweet_ids.strip()
                                and campaign.tweet_ids != "[]")
            has_tweet_text = bool(campaign.tweet_text and campaign.tweet_text.strip())
            if not has_tweet_ids:
                if has_tweet_text:
                    missing_tweet_campaigns.append(
                        f"'{campaign.campaign_name}' (ポスト作成失敗)"
                    )
                else:
                    missing_tweet_campaigns.append(
                        f"'{campaign.campaign_name}' (ツイートID未設定)"
                    )

        if missing_tweet_campaigns:
            error_msg = (
                "以下のキャンペーンにツイートIDがありません（CR作成不可）: "
                + ", ".join(missing_tweet_campaigns)
            )
            logger.error(error_msg)
            batch.upload_status = "upload_failed"
            batch.upload_error = error_msg
            db.commit()
            return

        # Excel生成 → 一時ファイル保存
        generator = ExcelGenerator()
        output = generator.generate(batch, project)

        excel_dir = Path("data/temp_excel")
        excel_dir.mkdir(parents=True, exist_ok=True)
        excel_path = excel_dir / f"upload_{batch_id}.xlsx"
        with open(excel_path, "wb") as f:
            f.write(output.read())

        # ブラウザアップロード
        uploader = XAdsEditorUploader(credential_id)
        result = await uploader.upload_excel(str(excel_path), ads_account_id)

        if result["success"]:
            batch.upload_status = "uploaded"
            batch.upload_error = None
            # バッチ全体のステータスも更新（API入稿と同じ形式）
            batch.status = "completed"
            batch.succeeded_campaigns = batch.total_campaigns
            batch.failed_campaigns = 0
            batch.submitted_at = batch.submitted_at or now_jst()
            batch.completed_at = now_jst()
            # 各キャンペーンのステータスも更新
            for campaign in batch.campaigns:
                if campaign.status != "success":
                    campaign.status = "success"
        else:
            batch.upload_status = "upload_failed"
            batch.upload_error = result.get("message", "Unknown error")

        db.commit()

        # 一時ファイル削除
        excel_path.unlink(missing_ok=True)

    except SessionExpiredError:
        batch.upload_status = "session_expired"
        batch.upload_error = "Session expired. Please re-login from API Settings."
        db.commit()
    except BrowserSessionError as e:
        batch.upload_status = "upload_failed"
        batch.upload_error = str(e)
        db.commit()
    except Exception as e:
        logger.error("Background upload error: %s", e, exc_info=True)
        if batch:
            batch.upload_status = "upload_failed"
            batch.upload_error = f"Unexpected error: {str(e)}"
            db.commit()
    finally:
        db.close()


async def _create_tweets_via_browser(
    db: "Session",
    batch: SubmissionBatch,
    credential_id: int,
    ads_account_id: str,
):
    """バッチ内の各キャンペーンについて、tweet_text があり tweet_ids が空の場合
    広告マネージャーのComposer画面からダークポストを作成し、取得した tweet ID を
    campaign.tweet_ids にセットする。Excel生成前に呼ぶこと。

    ブラウザは1つのセッションで全ポストを作成する（パフォーマンス最適化）。
    """
    import json
    from app.models import MediaAsset
    from app.services.browser_uploader import (
        BrowserSessionError,
        SessionExpiredError,
        XAdsEditorUploader,
    )

    # Step 1: ポスト作成が必要なキャンペーンを収集
    campaigns_to_create: list[tuple] = []  # (campaign, post_data)

    for campaign in batch.campaigns:
        # tweet_text がなければスキップ
        if not campaign.tweet_text:
            continue
        # 既に tweet_ids がセット済みならスキップ
        if campaign.tweet_ids and campaign.tweet_ids.strip():
            continue
        # 既に API で作成済みならそれを使う
        if campaign.api_tweet_id:
            campaign.tweet_ids = json.dumps([campaign.api_tweet_id])
            db.flush()
            logger.info(
                "Campaign %d: reusing existing api_tweet_id %s",
                campaign.id, campaign.api_tweet_id,
            )
            continue

        # メディアファイルパスを取得
        media_file_paths: list[str] = []
        if campaign.media_asset_ids:
            try:
                asset_ids = json.loads(campaign.media_asset_ids)
            except (json.JSONDecodeError, TypeError):
                asset_ids = []

            for asset_id in asset_ids:
                asset = db.query(MediaAsset).filter(
                    MediaAsset.id == int(asset_id)
                ).first()
                if asset:
                    file_path = str(
                        Path("data/media")
                        / str(asset.user_id)
                        / asset.filename
                    )
                    media_file_paths.append(file_path)

        post_data = {
            "tweet_text": campaign.tweet_text,
            "media_file_paths": media_file_paths if media_file_paths else None,
            "ad_name": campaign.campaign_name or "",
            "website_url": campaign.website_card_url or "",
        }
        campaigns_to_create.append((campaign, post_data))

    if not campaigns_to_create:
        logger.info("No tweets to create via browser")
        return

    # Step 2: 1つのブラウザセッションで全ポストを作成
    try:
        uploader = XAdsEditorUploader(credential_id)
        posts_data = [post_data for _, post_data in campaigns_to_create]
        results = await uploader.create_posts_batch(
            ads_account_id=ads_account_id,
            posts=posts_data,
        )

        # Step 3: 結果をキャンペーンに反映
        for (campaign, _), result in zip(campaigns_to_create, results):
            if result["success"] and result.get("tweet_id"):
                tweet_id = result["tweet_id"]
                campaign.api_tweet_id = tweet_id
                campaign.tweet_ids = json.dumps([tweet_id])
                db.flush()
                logger.info(
                    "Campaign %d: post created via browser, tweet_id=%s",
                    campaign.id, tweet_id,
                )
            else:
                logger.error(
                    "Campaign %d: browser post creation failed: %s",
                    campaign.id, result.get("message"),
                )

        # 成功分をコミット
        db.commit()

    except SessionExpiredError:
        # セッション期限切れは上位で適切にハンドリングさせるため再送出
        raise
    except BrowserSessionError as e:
        logger.error("Browser post creation error: %s", e)
        db.commit()  # 部分的に成功したものはコミット
    except Exception as e:
        logger.error("Unexpected error creating posts: %s", e, exc_info=True)
        db.commit()  # 部分的に成功したものはコミット
