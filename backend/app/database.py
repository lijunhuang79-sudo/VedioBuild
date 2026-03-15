"""数据库连接"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from .config import get_settings

settings = get_settings()

# 支持 SQLite（本地试用）和 PostgreSQL
_db_url = settings.database_url
if _db_url.startswith("sqlite"):
    engine = create_engine(_db_url, connect_args={"check_same_thread": False})
else:
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg2://")
    engine = create_engine(_db_url, pool_pre_ping=True, echo=False)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
