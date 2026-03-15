"""应用配置"""
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import field_validator
from functools import lru_cache


class Settings(BaseSettings):
    # 数据库
    database_url: str = "postgresql://postgres:postgres@localhost:5432/ai_video_factory"
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    
    # JWT
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    
    # S3/MinIO
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "ai-videos"
    s3_region: str = "us-east-1"
    
    # DeepSeek API (文案生成，兼容 OpenAI 接口)
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    # OpenAI (可选，备用)
    openai_api_key: Optional[str] = None
    openai_base_url: str = "https://api.openai.com/v1"
    
    # Stripe
    stripe_secret_key: Optional[str] = None
    stripe_webhook_secret: Optional[str] = None
    
    # 应用
    api_base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001"

    # 本地试用：不连 Redis 时在进程内执行任务，并用本地目录存视频
    inline_worker: bool = False  # 设置 INLINE_WORKER=1 启用
    local_video_dir: str = "./static/videos"

    @field_validator("inline_worker", mode="before")
    @classmethod
    def parse_inline_worker(cls, v):
        if isinstance(v, str) and v.strip() in ("1", "true", "True", "yes"):
            return True
        return v

    # 套餐额度
    plan_basic_credits: int = 20
    plan_pro_credits: int = 100
    plan_studio_credits: int = 500

    class Config:
        # 从 backend/ 或项目根启动时都能读到根目录 .env
        env_file = (".env", "../.env")
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
