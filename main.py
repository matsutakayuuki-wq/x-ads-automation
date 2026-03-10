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
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s ...", settings.APP_NAME)

    if settings.DATABASE_URL.startswith("sqlite"):
        Path("data").mkdir(exist_ok=True)
    init_db()
    logger.info("Database initialized.")

    yield

    logger.info("Application shutdown complete.")


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

# ユーザー認証ミドルウェア
from app.middleware import AuthMiddleware  # noqa: E402

app.add_middleware(AuthMiddleware)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

from app.routers import admin, auth, credentials, dashboard, excel, projects, submissions  # noqa: E402

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(credentials.router)
app.include_router(projects.router)
app.include_router(submissions.router)
app.include_router(excel.router)
app.include_router(admin.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
