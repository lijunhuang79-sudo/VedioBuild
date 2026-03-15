"""任务路由"""
import logging
import os
import uuid
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from typing import Optional

from ..database import get_db
from ..models import User, VideoTask, TaskStatus
from ..schemas import TaskCreate, TaskResponse, TaskListResponse
from ..auth import get_current_user
from ..config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# 仅非本地试用时才需要 S3
if not settings.inline_worker:
    from ..storage import upload_file

# 仅在不使用 inline_worker 时连接 Celery
if not settings.inline_worker:
    from ..celery_app import celery_app

router = APIRouter(prefix="/tasks", tags=["任务"])


@router.post("", response_model=TaskResponse)
def create_task(
    theme: str = Form(...),
    template: str = Form("default"),
    voice: Optional[str] = Form(None),
    style: Optional[str] = Form(None),
    bgm: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建视频生成任务"""
    if current_user.credits <= 0:
        raise HTTPException(status_code=402, detail="额度不足，请先购买套餐")

    image_url = None
    logger.info("create_task: 收到请求 theme=%s 带图=%s 文件名=%s", theme[:20] if theme else "", image is not None, getattr(image, "filename", None))
    if image:
        import tempfile
        ext = (os.path.splitext(image.filename or "image.png")[1] or ".png").lower()
        if ext == ".heic":
            ext = ".heic"  # 保留 heic，Pillow+pillow-heif 可读
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(image.file.read())
            tmp_path = tmp.name
        try:
            if settings.inline_worker:
                # 与 main.py 一致：backend/static/images（main 挂载的是 backend/static）
                static_images = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "static", "images"))
                os.makedirs(static_images, exist_ok=True)
                fname = f"{uuid.uuid4()}{ext}"
                dest = os.path.join(static_images, fname)
                import shutil
                shutil.copy2(tmp_path, dest)
                image_url = f"{settings.api_base_url.rstrip('/')}/static/images/{fname}"
                logger.info("create_task: 已保存上传图片 -> %s", dest)
            else:
                image_url = upload_file(tmp_path, current_user.id, prefix="images")
        except Exception as e:
            logger.warning("create_task: 上传图片失败 -> %s", e)
            image_url = None
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    try:
        task_id = str(uuid.uuid4())
        task = VideoTask(
            user_id=current_user.id,
            task_id=task_id,
            theme=theme,
            template=template,
            image_url=image_url,
            status=TaskStatus.PENDING.value,
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        current_user.credits -= 1
        db.commit()

        # 立即标记为「生成中」，前端不会一直停在「排队中」
        if settings.inline_worker:
            task.status = TaskStatus.PROCESSING.value
            db.commit()
            db.refresh(task)

        if settings.inline_worker:
            # 只传原始类型，避免子线程里访问 current_user 导致 DetachedInstanceError
            user_id = int(current_user.id)
            # 本地试用时传图片本地绝对路径，worker 直接读文件
            image_path = None
            if image_url:
                static_images = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "static", "images"))
                parts = (image_url or "").split("/")
                if parts:
                    fname = parts[-1].split("?")[0].strip()
                    if fname:
                        image_path = os.path.abspath(os.path.join(static_images, fname))
                        if not os.path.isfile(image_path):
                            logger.warning("create_task: image_path 不存在 %s", image_path)
                            image_path = None
            logger.info("create_task: image_url=%s image_path=%s", image_url or "(无)", image_path or "(无)")
            def run_inline():
                import sys
                root = Path(__file__).resolve().parent.parent.parent.parent
                sys.path.insert(0, str(root))
                from worker.tasks import generate_video_task
                generate_video_task(
                    task_id=task_id,
                    user_id=user_id,
                    theme=theme,
                    template=template,
                    image_url=image_url,
                    image_path=image_path,
                    voice=voice,
                    style=style,
                    bgm=bgm,
                )
            threading.Thread(target=run_inline, daemon=True).start()
        else:
            celery_app.send_task(
                "worker.tasks.generate_video_task",
                kwargs={
                    "task_id": task_id,
                    "user_id": current_user.id,
                    "theme": theme,
                    "template": template,
                    "image_url": image_url,
                    "voice": voice,
                    "style": style,
                    "bgm": bgm,
                },
            )

        return TaskResponse(
            id=task.id,
            task_id=task.task_id,
            theme=task.theme,
            template=task.template,
            status=task.status,
            video_url=task.video_url,
            error_message=task.error_message,
            created_at=task.created_at,
        )
    except OperationalError as e:
        logger.exception("创建任务时数据库错误: %s", e)
        raise HTTPException(status_code=503, detail="数据库暂时不可用，请稍后重试")
    except Exception as e:
        logger.exception("创建任务失败: %s", e)
        raise HTTPException(status_code=500, detail=f"创建任务失败: {str(e)}")


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取任务状态"""
    task = db.query(VideoTask).filter(
        VideoTask.task_id == task_id,
        VideoTask.user_id == current_user.id,
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return TaskResponse(
        id=task.id,
        task_id=task.task_id,
        theme=task.theme,
        template=task.template,
        status=task.status,
        video_url=task.video_url,
        error_message=task.error_message,
        created_at=task.created_at,
    )


@router.get("", response_model=TaskListResponse)
def list_tasks(
    skip: int = 0,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """任务列表"""
    query = db.query(VideoTask).filter(VideoTask.user_id == current_user.id)
    total = query.count()
    tasks = query.order_by(VideoTask.created_at.desc()).offset(skip).limit(limit).all()
    return TaskListResponse(
        tasks=[
            TaskResponse(
                id=t.id,
                task_id=t.task_id,
                theme=t.theme,
                template=t.template,
                status=t.status,
                video_url=t.video_url,
                error_message=t.error_message,
                created_at=t.created_at,
            )
            for t in tasks
        ],
        total=total,
    )
