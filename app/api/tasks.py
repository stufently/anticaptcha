"""Task endpoints for CAPTCHA solving"""
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.task import Task
from app.models.api_key import APIKey, User
from app.schemas.task import TaskCreate, TaskResponse, TaskResult, TaskStatus
from app.config import settings
import json
from typing import Optional

router = APIRouter()

# Statuses that occupy a slot of the per-key quota: the task is either waiting
# for the worker or being solved right now.
ACTIVE_STATUSES = ("pending", "processing")


def get_api_key_and_user(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    db: Session = Depends(get_db)
) -> tuple[APIKey, User]:
    """Validate API key from Authorization header and return both API key and user"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    
    # Extract token from "Bearer <token>"
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization format")
    
    token = parts[1]
    
    # Check if it's API key (not admin token)
    key_hash = APIKey.hash_key(token)
    api_key = db.query(APIKey).filter(
        APIKey.key_hash == key_hash,
        APIKey.is_active == True
    ).first()

    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    
    # Get user
    user = db.query(User).filter(User.id == api_key.user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    return api_key, user


@router.post("/task", response_model=TaskResponse, tags=["tasks"])
def create_task(
    task_data: TaskCreate,
    auth_data: tuple[APIKey, User] = Depends(get_api_key_and_user),
    db: Session = Depends(get_db)
):
    """Create a new CAPTCHA solving task"""
    api_key, current_user = auth_data

    limit = settings.max_active_tasks_per_key
    if limit > 0:
        # Take the write lock BEFORE counting: a check-then-insert without it lets
        # concurrent creates all read the old count and all insert (measured: five
        # rows for a limit of one). BEGIN IMMEDIATE on this session's connection
        # keeps the count and the insert in one transaction; the SELECTs that
        # validated the API key do not start a transaction of their own in
        # pysqlite, so this does not fail with "transaction within a transaction".
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        active = db.execute(
            select(func.count())
            .select_from(Task)
            .where(
                Task.api_key_id == api_key.id,
                Task.status.in_(ACTIVE_STATUSES),
            )
        ).scalar_one()
        if active >= limit:
            db.rollback()
            raise HTTPException(
                status_code=429,
                detail=f"Too many active tasks for this API key: limit is {limit}",
            )

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
    auth_data: tuple[APIKey, User] = Depends(get_api_key_and_user),
    db: Session = Depends(get_db)
):
    """Get task result by ID (only tasks created with the caller's API key)"""
    api_key, _ = auth_data
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