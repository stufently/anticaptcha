"""Task model for CAPTCHA solving tasks"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.sql import func
from sqlalchemy import ForeignKey
from app.database import Base


class Task(Base):
    """CAPTCHA solving task"""
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=False)
    
    # Task details
    type = Column(String(50), nullable=False)  # recaptcha_v2, recaptcha_v3, hcaptcha, image_text, turnstile
    status = Column(String(20), default="pending")  # pending, processing, solved, failed
    
    # Input/Output
    input_data = Column(Text, nullable=False)  # JSON string with captcha parameters
    result = Column(Text)  # JSON string with solution
    
    # Timing
    created_at = Column(DateTime, server_default=func.now())
    started_at = Column(DateTime)
    solved_at = Column(DateTime)
    
    # Error handling
    error_message = Column(Text)
    retries = Column(Integer, default=0)
    
    def __repr__(self):
        return f"<Task(id={self.id}, type={self.type}, status={self.status})>"