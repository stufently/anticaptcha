"""API Key and User models"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import secrets
import hashlib


class User(Base):
    """User model"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(64), nullable=False)
    password_salt = Column(String(32), nullable=True)  # Salt for password hashing
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)  # Admin flag
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    api_keys = relationship("APIKey", back_populates="user")

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username})>"


class APIKey(Base):
    """API Key for authentication"""
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    key_hash = Column(String(64), unique=True, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    user = relationship("User", back_populates="api_keys")
    tasks = relationship("Task", backref="api_key")

    def __repr__(self):
        return f"<APIKey(id={self.id}, user_id={self.user_id})>"

    @staticmethod
    def generate_key() -> str:
        """Generate a new API key"""
        return f"ac_{secrets.token_hex(16)}"
    
    @staticmethod
    def hash_key(key: str) -> str:
        """Hash an API key for storage"""
        return hashlib.sha256(key.encode()).hexdigest()