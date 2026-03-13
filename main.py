import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import init_db

_log_handlers: list = [logging.StreamHandler()]
try:
    Path("logs").mkdir(exist_ok=True)
    _log_handlers.append(logging.FileHandler("logs/app.log", encoding="utf-8"))
except OSError:
    pass  # Railway等ファイル書き込み不可の環境ではコンソールのみ

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=_log_handlers,
)
# SQLAlchemy のSQL文ログを抑制（アプリログが埋もれるのを防ぐ）
logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s ...", settings.APP_NAME)

    if settings.DATABASE_URL.startswith("sqlite"):
        Path("data").mkdir(exist_ok=True)
    Path("data/browser_sessions").mkdir(parents=True, exist_ok=True)
    Path("data/temp_excel").mkdir(parents=True, exist_ok=True)
    Path("data/media").mkdir(parents=True, exist_ok=True)
    init_db()
    logger.info("Database initialized.")

    # Lightweight schema migrations for SQLite
    _run_migrations()

    yield

    logger.info("Application shutdown complete.")


def _run_migrations():
    """既存テーブルに不足カラムを追加する軽量マイグレーション"""
    from sqlalchemy import inspect, text
    from app.database import engine

    def _ensure_column(conn, inspector, table: str, column: str, col_def: str):
        """テーブルにカラムが無ければ ALTER TABLE で追加"""
        if table not in inspector.get_table_names():
            return
        cols = [c["name"] for c in inspector.get_columns(table)]
        if column not in cols:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"))
            conn.commit()
            logger.info("Migration: added %s.%s column", table, column)

    with engine.connect() as conn:
        inspector = inspect(engine)

        # landing_pages.is_used
        _ensure_column(conn, inspector, "landing_pages", "is_used",
                        "BOOLEAN NOT NULL DEFAULT 0")

        # submission_campaigns: メディア・Website Card 関連カラム (前回追加漏れ)
        _ensure_column(conn, inspector, "submission_campaigns", "media_asset_ids",
                        "TEXT")
        _ensure_column(conn, inspector, "submission_campaigns", "card_uri",
                        "TEXT")
        _ensure_column(conn, inspector, "submission_campaigns", "website_card_title",
                        "TEXT")
        _ensure_column(conn, inspector, "submission_campaigns", "website_card_url",
                        "TEXT")
        _ensure_column(conn, inspector, "submission_campaigns", "website_card_cta",
                        "VARCHAR(50)")


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

# ユーザー認証ミドルウェア
from app.middleware import AuthMiddleware  # noqa: E402

app.add_middleware(AuthMiddleware)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

from app.routers import admin, auth, browser, credentials, dashboard, excel, landing_pages, media, projects, submissions  # noqa: E402

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(credentials.router)
app.include_router(projects.router)
app.include_router(submissions.router)
app.include_router(excel.router)
app.include_router(browser.router)
app.include_router(media.router)
app.include_router(landing_pages.router)
app.include_router(admin.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
