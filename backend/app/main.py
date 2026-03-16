"""FastAPI 主应用"""
import logging
import os
from pathlib import Path

# 加载项目根目录 .env，保证即梦、阿里云 TTS 等环境变量在 worker 中可用（与 scripts/start-backend.sh 行为一致）
_root = Path(__file__).resolve().parent.parent.parent
_env_file = _root / ".env"
if _env_file.is_file():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file)
    except ImportError:
        pass

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from .config import get_settings
from .database import engine, Base, SessionLocal
from .routers import auth, tasks
from .models import User
from .auth import get_password_hash

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
settings = get_settings()

# 测试账号（本地/测试环境启动时自动创建）
TEST_USER_EMAIL = "test@test.com"
TEST_USER_PASSWORD = "123456"


def _ensure_test_user():
    """确保 test@test.com 存在且密码为 123456，便于本地登录（已存在则强制重置密码）。"""
    try:
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.email == TEST_USER_EMAIL).first()
            if u:
                u.password_hash = get_password_hash(TEST_USER_PASSWORD)
                u.credits = max(u.credits, 999)
                db.commit()
                logger.info("已重置测试账号 %s 密码为 %s", TEST_USER_EMAIL, TEST_USER_PASSWORD)
                return
            user = User(
                email=TEST_USER_EMAIL,
                password_hash=get_password_hash(TEST_USER_PASSWORD),
                plan="basic",
                credits=999,
            )
            db.add(user)
            db.commit()
            logger.info("已创建测试账号 %s（密码 %s）", TEST_USER_EMAIL, TEST_USER_PASSWORD)
        finally:
            db.close()
    except Exception as e:
        logger.warning("创建/重置测试账号失败（可忽略）: %s", e)


class _SkipTasksPollFilter(logging.Filter):
    """过滤掉 GET /api/tasks 200 的访问日志，减轻刷屏"""
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(getattr(record, "msg", ""))
        if "GET /api/tasks" in msg and "200" in msg:
            return False
        return True


# 对 uvicorn.access 生效（若存在）
_uvicorn_access = logging.getLogger("uvicorn.access")
_uvicorn_access.addFilter(_SkipTasksPollFilter())

# 创建表
try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    logger.warning("创建表时出错（若为首次可忽略）: %s", e)

# SQLite：为已有表补充「生成历史」字段（无 Alembic 时兼容旧库）
def _add_history_columns_if_missing():
    if "sqlite" not in settings.database_url:
        return
    try:
        from sqlalchemy import text
        for col in ("script_text", "scene_descriptions", "voice", "style", "bgm", "scene_urls"):
            try:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE video_tasks ADD COLUMN {col} TEXT"))
                logger.info("已为 video_tasks 添加列: %s", col)
            except Exception as e:
                if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                    pass
                else:
                    logger.debug("补充 video_tasks 列 %s 时跳过: %s", col, e)
    except Exception as e:
        logger.warning("补充 video_tasks 列时出错（可忽略）: %s", e)


_add_history_columns_if_missing()
_ensure_test_user()

app = FastAPI(
    title="AI 视频工厂 API",
    description="AI 视频生成 SaaS 平台",
    version="1.0.0",
)

_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# 上传目录
UPLOAD_DIR = "/tmp/ai_video_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 本地试用：图片与视频目录
STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")
STATIC_VIDEOS = os.path.join(STATIC_DIR, "videos")
STATIC_IMAGES = os.path.join(STATIC_DIR, "images")
STATIC_SCENES = os.path.join(STATIC_DIR, "scenes")
os.makedirs(STATIC_VIDEOS, exist_ok=True)
os.makedirs(STATIC_IMAGES, exist_ok=True)
os.makedirs(STATIC_SCENES, exist_ok=True)
app.mount("/static/videos", StaticFiles(directory=STATIC_VIDEOS), name="videos")
app.mount("/static/images", StaticFiles(directory=STATIC_IMAGES), name="images")
app.mount("/static/scenes", StaticFiles(directory=STATIC_SCENES), name="scenes")

app.include_router(auth.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")


@app.get("/")
def root():
    return {"message": "AI 视频工厂 API", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """记录 500 错误原因，便于排查"""
    logger.exception("Internal Server Error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误", "error": str(exc) if "sqlite" in settings.database_url else "请查看后端日志"},
    )
