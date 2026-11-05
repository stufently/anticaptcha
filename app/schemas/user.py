"""User and API key schemas"""
from pydantic import BaseModel
from datetime import datetime
from typing import List


class APIKeyResponse(BaseModel):
    """Response schema for API key"""
    id: int
    key: str
    is_active: bool
    created_at: datetime


class UserCreate(BaseModel):
    """Request schema for creating user"""
    username: str
    password: str


class UserResponse(BaseModel):
    """Response schema for user"""
    id: int
    username: str
    is_active: bool
    created_at: datetime
    api_keys: List[APIKeyResponse] = []