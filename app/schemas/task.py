"""Task schemas for API"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum


class TaskType(str, Enum):
    """CAPTCHA types"""
    RECAPTCHA_V2 = "recaptcha_v2"
    RECAPTCHA_V3 = "recaptcha_v3"
    HCAPTCHA = "hcaptcha"
    IMAGE_TEXT = "image_text"
    TURNSTILE = "turnstile"
    YANDEX_SMARTCAPTCHA = "yandex_smartcaptcha"


class TaskStatus(str, Enum):
    """Task statuses"""
    PENDING = "pending"
    PROCESSING = "processing"
    SOLVED = "solved"
    FAILED = "failed"


class TaskCreate(BaseModel):
    """Request schema for creating a task"""
    type: TaskType
    input_data: Dict[str, Any] = Field(..., description="CAPTCHA parameters as JSON")
    
    class Config:
        json_schema_extra = {
            "example": {
                "type": "recaptcha_v2",
                "input_data": {
                    "site_key": "6Le-wvkSAAAAAPBMRTvw0Q4Muexq9bi0DJwx_mJ-",
                    "page_url": "https://example.com"
                }
            }
        }


class TaskResult(BaseModel):
    """Response schema for task result"""
    task_id: int
    status: TaskStatus
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime
    solved_at: Optional[datetime] = None


class TaskResponse(BaseModel):
    """Response schema for task creation"""
    task_id: int
    status: TaskStatus = TaskStatus.PENDING
    
    class Config:
        json_schema_extra = {
            "example": {
                "task_id": 123,
                "status": "pending"
            }
        }
