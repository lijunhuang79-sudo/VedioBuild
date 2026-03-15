"""认证路由"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import OperationalError, IntegrityError

from ..database import get_db
logger = logging.getLogger(__name__)
from ..models import User
from ..schemas import UserCreate, UserResponse, TokenResponse
from ..auth import (
    get_password_hash,
    create_access_token,
    get_user_by_email,
    verify_password,
    get_current_user,
)
from ..config import get_settings

router = APIRouter(prefix="/auth", tags=["认证"])
settings = get_settings()


def get_plan_credits(plan: str) -> int:
    return {
        "basic": settings.plan_basic_credits,
        "pro": settings.plan_pro_credits,
        "studio": settings.plan_studio_credits,
    }.get(plan, settings.plan_basic_credits)


@router.post("/register", response_model=TokenResponse)
def register(data: UserCreate, db: Session = Depends(get_db)):
    """用户注册"""
    user = None
    try:
        if get_user_by_email(db, data.email):
            raise HTTPException(status_code=400, detail="邮箱已被注册")
        user = User(
            email=data.email,
            password_hash=get_password_hash(data.password),
            plan="basic",
            credits=get_plan_credits("basic"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    except HTTPException:
        raise
    except IntegrityError as e:
        logger.warning("注册重复邮箱: %s", e)
        raise HTTPException(status_code=400, detail="该邮箱已被注册")
    except OperationalError as e:
        logger.exception("数据库连接失败: %s", e)
        raise HTTPException(
            status_code=503,
            detail="数据库不可用，请用 scripts/start-backend.sh 启动后端（使用 SQLite）",
        )
    except Exception as e:
        logger.exception("注册失败: %s", e)
        raise HTTPException(status_code=500, detail="注册失败，请稍后重试")

    try:
        token = create_access_token(data={"sub": str(user.id)})
        return TokenResponse(
            access_token=token,
            user=UserResponse(
                id=user.id,
                email=user.email,
                plan=user.plan,
                credits=user.credits,
                created_at=user.created_at,
            ),
        )
    except Exception as e:
        logger.exception("注册返回时出错: %s", e)
        # 开发/本地时在详情中带上原因，便于排查
        detail = "注册失败，请稍后重试"
        if "sqlite" in settings.database_url.lower():
            detail = f"注册失败: {e!s}"
        raise HTTPException(status_code=500, detail=detail)


def _do_login(user, token: str) -> TokenResponse:
    return TokenResponse(
        access_token=token,
        user=UserResponse(
            id=user.id,
            email=user.email,
            plan=user.plan,
            credits=user.credits,
            created_at=user.created_at,
        ),
    )


@router.post("/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """用户登录（OAuth2 表单）"""
    user = get_user_by_email(db, form.username)
    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    token = create_access_token(data={"sub": str(user.id)})
    return _do_login(user, token)


@router.post("/login-json", response_model=TokenResponse)
def login_json(data: UserCreate, db: Session = Depends(get_db)):
    """用户登录（JSON body，便于前端直接调用）"""
    user = get_user_by_email(db, data.email)
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    token = create_access_token(data={"sub": str(user.id)})
    return _do_login(user, token)


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        plan=current_user.plan,
        credits=current_user.credits,
        created_at=current_user.created_at,
    )
