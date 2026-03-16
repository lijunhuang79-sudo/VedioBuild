"""任务路由"""
import logging
import os
import time
import uuid
import threading
import secrets
import urllib.parse
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from typing import Optional, List
import json

from ..database import get_db
from ..models import User, VideoTask, TaskStatus
from ..schemas import TaskCreate, TaskResponse, TaskListResponse
from ..auth import get_current_user, get_optional_user
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

# 临时下载链接 token：token -> {user_id, task_id, expiry}，一次性使用
_download_tokens: dict[str, dict] = {}
_DOWNLOAD_TOKEN_TTL = 120  # 2 分钟


def _parse_scene_descriptions(raw: Optional[str]) -> Optional[list]:
    """解析 scene_descriptions：JSON 数组且长度恰好为 6，否则返回 None。"""
    if not raw or not raw.strip():
        return None
    try:
        import json
        arr = json.loads(raw)
        if isinstance(arr, list) and len(arr) == 6 and all(isinstance(s, str) for s in arr):
            return [str(s).strip()[:200] for s in arr]
    except (ValueError, TypeError):
        pass
    return None


@router.post("", response_model=TaskResponse)
def create_task(
    theme: str = Form(...),
    template: str = Form("default"),
    voice: Optional[str] = Form(None),
    style: Optional[str] = Form(None),
    bgm: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    script_text: Optional[str] = Form(None),
    scene_descriptions_json: Optional[str] = Form(None, alias="scene_descriptions"),
    reuse_from_task_id: Optional[str] = Form(None),
    scene_image_0: Optional[UploadFile] = File(None),
    scene_image_1: Optional[UploadFile] = File(None),
    scene_image_2: Optional[UploadFile] = File(None),
    scene_image_3: Optional[UploadFile] = File(None),
    scene_image_4: Optional[UploadFile] = File(None),
    scene_image_5: Optional[UploadFile] = File(None),
    regenerate_scene_index_with_jimeng: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建视频生成任务。可选 script_text + scene_descriptions（6 条）；reuse_from_task_id 时复用该任务的 6 张场景图；scene_image_N 可单独替换第 N+1 镜背景图；regenerate_scene_index_with_jimeng=1..6 时仅用即梦重绘第 N 镜背景。"""
    if current_user.credits <= 0:
        raise HTTPException(status_code=402, detail="额度不足，请先购买套餐")

    reuse_scene_urls = None
    if reuse_from_task_id and str(reuse_from_task_id).strip():
        old = db.query(VideoTask).filter(
            VideoTask.task_id == reuse_from_task_id.strip(),
            VideoTask.user_id == current_user.id,
        ).first()
        if old and old.scene_urls:
            try:
                urls = json.loads(old.scene_urls)
                if isinstance(urls, list) and len(urls) == 6:
                    reuse_scene_urls = urls
                    logger.info("create_task: 复用任务 %s 的 6 张场景图", reuse_from_task_id[:8])
            except (ValueError, TypeError):
                pass

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
        scene_list = _parse_scene_descriptions(scene_descriptions_json)
        task = VideoTask(
            user_id=current_user.id,
            task_id=task_id,
            theme=theme,
            template=template,
            image_url=image_url,
            script_text=script_text.strip() if script_text else None,
            scene_descriptions=json.dumps(scene_list, ensure_ascii=False) if scene_list else None,
            voice=voice,
            style=style,
            bgm=bgm,
            status=TaskStatus.PENDING.value,
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        current_user.credits -= 1
        db.commit()

        # 自定义旁白：单独替换某镜背景图（scene_image_0..5 对应第 1..6 镜）
        custom_scene_image_paths = None
        scene_uploads = [scene_image_0, scene_image_1, scene_image_2, scene_image_3, scene_image_4, scene_image_5]
        if any(f and getattr(f, "filename", None) for f in scene_uploads):
            static_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "static"))
            task_scenes_dir = os.path.join(static_root, "scenes_uploads", task_id)
            os.makedirs(task_scenes_dir, exist_ok=True)
            paths = []
            for i, f in enumerate(scene_uploads):
                if f and getattr(f, "filename", None):
                    ext = (os.path.splitext(f.filename or "")[1] or ".png").lower()
                    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
                        ext = ".png"
                    dest = os.path.join(task_scenes_dir, f"{i}.png")
                    try:
                        with open(dest, "wb") as out:
                            out.write(f.file.read())
                        paths.append(dest)
                    except Exception as e:
                        logger.warning("保存第 %d 镜背景图失败: %s", i + 1, e)
                        paths.append(None)
                else:
                    paths.append(None)
            if len(paths) == 6:
                custom_scene_image_paths = paths
                logger.info("已保存 %d 张自定义场景图到 %s", sum(1 for p in paths if p), task_scenes_dir)

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
            # 仅用即梦重绘第 N 镜：1~6 对应第1镜~第6镜，传 0-based 给 worker
            jimeng_scene_index = None
            if regenerate_scene_index_with_jimeng and str(regenerate_scene_index_with_jimeng).strip():
                try:
                    n = int(str(regenerate_scene_index_with_jimeng).strip())
                    if 1 <= n <= 6:
                        jimeng_scene_index = n - 1
                except ValueError:
                    pass
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
                    script_text=script_text.strip() if script_text else None,
                    scene_descriptions=scene_list,
                    reuse_scene_urls=reuse_scene_urls,
                    custom_scene_image_paths=custom_scene_image_paths,
                    regenerate_scene_index_with_jimeng=jimeng_scene_index,
                )
            threading.Thread(target=run_inline, daemon=True).start()
        else:
            jimeng_scene_index = None
            if regenerate_scene_index_with_jimeng and str(regenerate_scene_index_with_jimeng).strip():
                try:
                    n = int(str(regenerate_scene_index_with_jimeng).strip())
                    if 1 <= n <= 6:
                        jimeng_scene_index = n - 1
                except ValueError:
                    pass
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
                    "script_text": script_text.strip() if script_text else None,
                    "scene_descriptions": scene_list,
                    "reuse_scene_urls": reuse_scene_urls,
                    "custom_scene_image_paths": None,
                    "regenerate_scene_index_with_jimeng": jimeng_scene_index,
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


def _get_task_video_path(task: VideoTask) -> Optional[str]:
    """根据 task.video_url 解析出本地视频文件路径，不存在则返回 None"""
    if not task or not task.video_url or task.status != TaskStatus.COMPLETED.value:
        return None
    url = (task.video_url or "").strip()
    if "/static/videos/" not in url:
        return None
    parts = url.split("/static/videos/")
    if len(parts) < 2:
        return None
    fname = parts[-1].split("?")[0].strip()
    if not fname or ".." in fname:
        return None
    static_videos = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "static", "videos"))
    path = os.path.join(static_videos, fname)
    return path if os.path.isfile(path) else None


def _serve_task_video(task: VideoTask):
    path = _get_task_video_path(task)
    if not path:
        raise HTTPException(status_code=404, detail="视频文件不存在或尚未生成完成")
    raw_name = (task.theme or "AI视频").replace("/", "_").replace("\\", "_")[:50] + ".mp4"
    # 文件名仅保留 ASCII 避免 HTTP 头 latin-1 编码错误；非 ASCII 用 filename*=UTF-8''
    ascii_name = "".join(c if ord(c) < 128 else "_" for c in raw_name).strip("_")
    if not ascii_name or ascii_name == ".mp4":
        ascii_name = "video.mp4"
    disp = f"attachment; filename=\"{ascii_name}\""
    if raw_name != ascii_name:
        disp += f"; filename*=UTF-8''{urllib.parse.quote(raw_name)}"
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=ascii_name,
        headers={"Content-Disposition": disp},
    )


@router.post("/{task_id}/download-link")
def create_download_link(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """生成一次性下载链接（供手机等通过地址栏打开触发保存）"""
    task = db.query(VideoTask).filter(
        VideoTask.task_id == task_id,
        VideoTask.user_id == current_user.id,
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not _get_task_video_path(task):
        raise HTTPException(status_code=404, detail="视频文件不存在或尚未生成完成")
    token = secrets.token_urlsafe(32)
    now = time.time()
    _download_tokens[token] = {
        "user_id": current_user.id,
        "task_id": task_id,
        "expiry": now + _DOWNLOAD_TOKEN_TTL,
    }
    # 定期清理过期 token
    for k, v in list(_download_tokens.items()):
        if v.get("expiry", 0) < now:
            _download_tokens.pop(k, None)
    return {"download_url": f"/api/tasks/{task_id}/download?token={token}"}


@router.get("/{task_id}/download")
def download_task_video(
    request: Request,
    task_id: str,
    token: Optional[str] = Query(None),
    current_user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """下载任务视频（支持 Bearer 或一次性 ?token=，返回 attachment 触发保存）"""
    task = None
    if token:
        info = _download_tokens.pop(token, None)
        if not info or info.get("expiry", 0) < time.time():
            raise HTTPException(status_code=404, detail="下载链接已失效，请重新点击下载")
        if info.get("task_id") != task_id:
            raise HTTPException(status_code=404, detail="链接不匹配")
        task = db.query(VideoTask).filter(
            VideoTask.task_id == task_id,
            VideoTask.user_id == info["user_id"],
        ).first()
    else:
        if not current_user:
            raise HTTPException(
                status_code=401,
                detail="请登录或使用有效下载链接",
                headers={"WWW-Authenticate": "Bearer"},
            )
        task = db.query(VideoTask).filter(
            VideoTask.task_id == task_id,
            VideoTask.user_id == current_user.id,
        ).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _serve_task_video(task)


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
    scene_list = None
    if task.scene_descriptions:
        try:
            scene_list = json.loads(task.scene_descriptions)
            if not isinstance(scene_list, list) or len(scene_list) != 6:
                scene_list = None
        except (ValueError, TypeError):
            scene_list = None
    return TaskResponse(
        id=task.id,
        task_id=task.task_id,
        theme=task.theme,
        template=task.template,
        status=task.status,
        video_url=task.video_url,
        error_message=task.error_message,
        created_at=task.created_at,
        script_text=task.script_text,
        scene_descriptions=scene_list,
        voice=task.voice,
        style=task.style,
        bgm=task.bgm,
    )


@router.delete("/{task_id}")
def delete_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除任务（仅限本人；若为本地视频则一并删除文件）"""
    task = db.query(VideoTask).filter(
        VideoTask.task_id == task_id,
        VideoTask.user_id == current_user.id,
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    path = _get_task_video_path(task)
    if path:
        try:
            os.unlink(path)
        except OSError as e:
            logger.warning("delete_task: 删除本地视频文件失败 path=%s err=%s", path, e)
    db.delete(task)
    db.commit()
    return {"ok": True, "detail": "已删除"}


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

    def _scene_list(raw):
        if not raw:
            return None
        try:
            lst = json.loads(raw)
            return lst if isinstance(lst, list) and len(lst) == 6 else None
        except (ValueError, TypeError):
            return None

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
                script_text=t.script_text,
                scene_descriptions=_scene_list(t.scene_descriptions),
                voice=t.voice,
                style=t.style,
                bgm=t.bgm,
            )
            for t in tasks
        ],
        total=total,
    )
