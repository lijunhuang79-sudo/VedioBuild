"""Celery 配置 - 供 backend 提交任务用"""
from celery import Celery
from .config import get_settings

settings = get_settings()

celery_app = Celery(
    "ai_video_factory",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)
