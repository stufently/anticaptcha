"""Configuration settings for anticaptcha service"""
from pydantic_settings import BaseSettings
from pathlib import Path
from typing import Optional


class Settings(BaseSettings):
    """Application settings"""

    # Database
    database_path: str = "data/anticaptcha.db"

    # API
    api_prefix: str = "/api/v1"
    api_key_header: str = "X-API-Key"
    admin_token: Optional[str] = None  # Admin token for bootstrap

    # Worker
    worker_poll_interval: int = 1  # seconds
    max_retries: int = 3
    workers_count: int = 4

    # ML Models
    models_dir: str = "models"
    yolo_model: str = "yolov8n-cls.pt"

    # Browser
    headless: bool = True
    browser_timeout: int = 30  # seconds

    # Logging
    log_level: str = "INFO"

    # Vision LLM
    vision_model: str = "kimi-k2.5"
    bailian_api_key: Optional[str] = None  # BAILIAN_CODING_PLAN_API_KEY

    class Config:
        env_file = ".env"
        env_prefix = "ANTICAPTCHA_"


settings = Settings()