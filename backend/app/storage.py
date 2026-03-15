"""对象存储 (S3/MinIO)"""
import uuid
from pathlib import Path
import boto3
from botocore.config import Config
from .config import get_settings

settings = get_settings()

s3_client = boto3.client(
    "s3",
    endpoint_url=settings.s3_endpoint_url,
    aws_access_key_id=settings.s3_access_key,
    aws_secret_access_key=settings.s3_secret_key,
    region_name=settings.s3_region,
    config=Config(signature_version="s3v4"),
)


def ensure_bucket_exists():
    """确保 bucket 存在"""
    try:
        s3_client.head_bucket(Bucket=settings.s3_bucket)
    except Exception:
        s3_client.create_bucket(Bucket=settings.s3_bucket)


def upload_file(file_path: str, user_id: int, prefix: str = "videos") -> str:
    """上传文件到 S3/MinIO，返回下载 URL"""
    ensure_bucket_exists()
    ext = Path(file_path).suffix
    key = f"{prefix}/{user_id}/{uuid.uuid4()}{ext}"
    s3_client.upload_file(file_path, settings.s3_bucket, key)
    return f"{settings.s3_endpoint_url}/{settings.s3_bucket}/{key}"


def get_presigned_url(key: str, expires_in: int = 3600) -> str:
    """生成预签名下载 URL"""
    return s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=expires_in,
    )
