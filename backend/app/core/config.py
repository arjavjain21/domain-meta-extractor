from pydantic_settings import BaseSettings
from typing import List, Optional
import os


class Settings(BaseSettings):
    # Project
    PROJECT_NAME: str = "Domain Meta Extractor"
    API_V1_STR: str = "/api/v1"

    # Environment
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://domain_user:temp12345@localhost:5432/domain_extractor"

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379"

    # Security
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8  # 8 days

    # CORS
    ALLOWED_HOSTS: List[str] = ["*"]

    # File uploads
    MAX_FILE_SIZE: int = 100 * 1024 * 1024  # 100MB
    UPLOAD_DIR: str = "uploads"
    RESULTS_DIR: str = "results"

    # Processing
    MAX_DOMAINS_PER_FILE: int = 10000
    DEFAULT_CONCURRENCY: int = 25
    MAX_CONCURRENCY: int = 100

    # Cache
    CACHE_EXPIRE_DAYS: int = 30
    REDIS_CACHE_EXPIRE_SECONDS: int = 3600  # 1 hour

    # Rate limiting
    RATE_LIMIT_PER_MINUTE: int = 60

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()