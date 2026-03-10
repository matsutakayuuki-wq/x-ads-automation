"""Excel 生成・ダウンロード"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Project, SubmissionBatch, User

router = APIRouter(tags=["excel"])


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

    generator = ExcelGenerator()
    output = generator.generate(batch, project)

    filename = f"xads_{batch.name.replace(' ', '_')}_{batch.id}.xlsx"

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
