"""Pydantic 模型"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr


# ============ 用户 ============
class UserCreate(BaseModel):
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    plan: str
    credits: int
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ============ 任务 ============
class TaskCreate(BaseModel):
    theme: str
    template: str = "default"


class TaskResponse(BaseModel):
    id: int
    task_id: str
    theme: str
    template: str
    status: str
    video_url: Optional[str]
    error_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    total: int
