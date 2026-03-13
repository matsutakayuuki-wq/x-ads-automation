"""Excel 生成・ダウンロード"""
from __future__ import annotations

import logging
import re
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Project, SubmissionBatch, User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["excel"])


def _safe_filename(name: str, batch_id: int) -> tuple[str, str]:
    """バッチ名からHTTPヘッダー安全なファイル名を生成。

    Returns:
        (ascii_filename, utf8_encoded_filename)
    """
    # スラッシュ等のファイル名不正文字をアンダースコアに置換
    safe = re.sub(r'[/\\:*?"<>|]', '_', name.replace(' ', '_'))
    full_name = f"xads_{safe}_{batch_id}.xlsx"
    # ASCII フォールバック (非ASCII を除去)
    ascii_name = f"xads_batch_{batch_id}.xlsx"
    # RFC 5987 UTF-8 エンコード
    encoded = urllib.parse.quote(full_name)
    return ascii_name, encoded


@router.get("/api/submissions/{batch_id}/excel")
def download_excel(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """入稿バッチの Excel ファイルをダウンロード"""
    batch = db.query(SubmissionBatch).filter(
        SubmissionBatch.id == batch_id,
        SubmissionBatch.user_id == user.id,
    ).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    project = None
    if batch.project_id:
        project = db.query(Project).filter(Project.id == batch.project_id).first()

    from app.services.excel_generator import ExcelGenerator

    try:
        generator = ExcelGenerator()
        output = generator.generate(batch, project)
    except Exception as e:
        logger.error("Excel generation failed for batch %d: %s", batch_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Excel生成に失敗しました: {e}")

    ascii_name, encoded_name = _safe_filename(batch.name, batch.id)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{ascii_name}\"; "
                f"filename*=UTF-8''{encoded_name}"
            )
        },
    )


@router.get("/api/excel/template")
def download_template(
    user: User = Depends(get_current_user),
):
    """空のテンプレート Excel をダウンロード"""
    from app.services.excel_generator import ExcelGenerator, EXCEL_COLUMNS
    from openpyxl import Workbook
    from io import BytesIO

    wb = Workbook()
    ws = wb.active
    ws.title = "Campaigns"

    for col_idx, header in enumerate(EXCEL_COLUMNS, 1):
        ws.cell(row=1, column=col_idx, value=header)

    ws.freeze_panes = "A2"

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="xads_template.xlsx"'},
    )
