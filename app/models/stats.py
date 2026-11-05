"""Statistics model"""
from sqlalchemy import Column, Integer, DateTime
from sqlalchemy.sql import func
from app.database import Base


class Stats(Base):
    """Global statistics for CAPTCHA solving"""
    __tablename__ = "stats"

    id = Column(Integer, primary_key=True, index=True)
    
    # Task counts
    total_tasks = Column(Integer, default=0)
    solved_tasks = Column(Integer, default=0)
    failed_tasks = Column(Integer, default=0)
    
    # Timing
    total_solve_time_seconds = Column(Integer, default=0)
    
    # Timestamp
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<Stats(total={self.total_tasks}, solved={self.solved_tasks})>"