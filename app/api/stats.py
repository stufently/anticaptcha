"""Statistics endpoints"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.task import Task
from app.models.stats import Stats
from pydantic import BaseModel

router = APIRouter()


class StatsResponse(BaseModel):
    """Statistics response"""
    total_tasks: int
    solved_tasks: int
    failed_tasks: int
    pending_tasks: int
    success_rate: float
    average_solve_time_seconds: float


@router.get("/stats", response_model=StatsResponse, tags=["stats"])
def get_stats(db: Session = Depends(get_db)):
    """Get solving statistics"""
    # Get task counts
    total = db.query(Task).count()
    solved = db.query(Task).filter(Task.status == "solved").count()
    failed = db.query(Task).filter(Task.status == "failed").count()
    pending = db.query(Task).filter(Task.status == "pending").count()
    
    # Calculate success rate
    completed = solved + failed
    success_rate = (solved / completed * 100) if completed > 0 else 0.0
    
    # Get global stats
    stats = db.query(Stats).first()
    total_solve_time = stats.total_solve_time_seconds if stats else 0
    avg_solve_time = (total_solve_time / solved) if solved > 0 else 0.0
    
    return StatsResponse(
        total_tasks=total,
        solved_tasks=solved,
        failed_tasks=failed,
        pending_tasks=pending,
        success_rate=round(success_rate, 2),
        average_solve_time_seconds=round(avg_solve_time, 2)
    )