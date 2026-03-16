"""数据库模型"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum

from .database import Base


class PlanType(str, enum.Enum):
    BASIC = "basic"
    PRO = "pro"
    STUDIO = "studio"


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    plan = Column(String(20), default=PlanType.BASIC.value)
    credits = Column(Integer, default=20)  # 剩余额度
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tasks = relationship("VideoTask", back_populates="user")


class VideoTask(Base):
    __tablename__ = "video_tasks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    task_id = Column(String(64), unique=True, index=True)  # Celery task id
    
    # 输入
    image_url = Column(String(512))  # 上传的图片 URL
    theme = Column(String(256))  # 用户输入的主题
    template = Column(String(64), default="default")  # 视频模板
    script_text = Column(Text)  # 自定义旁白全文，用于生成历史「再用一次」
    scene_descriptions = Column(Text)  # JSON 数组 6 条场景描述
    voice = Column(String(64))
    style = Column(String(64))
    bgm = Column(String(64))

    # 输出
    video_url = Column(String(512))  # 生成的视频 URL
    scene_urls = Column(Text)  # JSON 数组 6 张场景图 URL，用于「再用一次」时复用同一套场景
    status = Column(String(20), default=TaskStatus.PENDING.value)
    error_message = Column(Text)  # 失败时的错误信息
    
    # 元数据
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)

    user = relationship("User", back_populates="tasks")
