"""Task endpoints for CAPTCHA solving"""
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.task import Task
from app.models.api_key import APIKey
from app.schemas.task import TaskCreate, TaskResponse, TaskResult, TaskStatus
from app.config import settings
import json

router = APIRouter()


def get_api_key(
    api_key: str = Header(..., alias=settings.api_key_header),
    db: Session = Depends(get_db)
) -> APIKey:
    """Validate API key from header"""
    key_hash = APIKey.hash_key(api_key)
    db_key = db.query(APIKey).filter(
        APIKey.key_hash == key_hash,
        APIKey.is_active == True
    ).first()
    
    if not db_key:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    
    return db_key


@router.post("/task", response_model=TaskResponse, tags=["tasks"])
def create_task(
    task_data: TaskCreate,
    api_key: APIKey = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """Create a new CAPTCHA solving task"""
    # Create task
    task = Task(
        api_key_id=api_key.id,
        type=task_data.type.value,
        input_data=json.dumps(task_data.input_data),
        status=TaskStatus.PENDING.value
    )
    
    db.add(task)
    db.commit()
    db.refresh(task)
    
    return TaskResponse(task_id=task.id, status=TaskStatus(task.status))


@router.get("/task/{task_id}", response_model=TaskResult, tags=["tasks"])
def get_task(
    task_id: int,
    api_key: APIKey = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """Get task result by ID"""
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.api_key_id == api_key.id
    ).first()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return TaskResult(
        task_id=task.id,
        status=TaskStatus(task.status),
        result=json.loads(task.result) if task.result else None,
        error=task.error_message,
        created_at=task.created_at,
        solved_at=task.solved_at
    )