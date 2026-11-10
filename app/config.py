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
    admin_token: Optional[str] = None  # Admin token for bootstrap

    # Worker
    worker_poll_interval: int = 1  # seconds
    max_retries: int = 3
    workers_count: int = 4
    task_timeout: float = 120  # seconds per solve; on timeout the task fails

    # Liveness: the worker touches this file from its event loop, a probe
    # checks its age (python -m workers.heartbeat --check --max-age N)
    worker_heartbeat_file: str = "/tmp/worker-heartbeat"
    worker_heartbeat_interval: float = 10.0

    # Max HTTP request body; larger requests get 413 before the body is read
    max_body_bytes: int = 5 * 1024 * 1024

    # Client image limits, checked from the header before any pixel decode:
    # a 20000x20000 PNG is ~1.2 MB on the wire but ~4 GB in memory
    max_image_pixels: int = 4_000_000
    max_image_side: int = 4096

    # Quota: how many pending/processing tasks one API key may hold at once
    # (0 = no limit). Read from settings per request, never cached.
    max_active_tasks_per_key: int = 20

    # Retention cleanup (workers/cleanup.py). input_data is up to 5 MB of base64
    # per task and the volume is small, so finished tasks lose their input long
    # before the row itself is deleted.
    cleanup_interval_seconds: int = 600
    input_retention_hours: float = 1
    task_retention_days: float = 7

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