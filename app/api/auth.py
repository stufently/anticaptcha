"""Authentication endpoints for user and API key management"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.api_key import User, APIKey
from app.schemas.user import UserCreate, UserResponse, APIKeyResponse
import hashlib
from typing import List

router = APIRouter()


def hash_password(password: str) -> str:
    """Hash password with SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against hash"""
    return hash_password(password) == password_hash


@router.post("/user", response_model=UserResponse, tags=["auth"])
def create_user(
    user_data: UserCreate,
    db: Session = Depends(get_db)
):
    """Create a new user"""
    # Check if user exists
    if db.query(User).filter(User.username == user_data.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    
    # Validate password length (bcrypt limit)
    if len(user_data.password.encode('utf-8')) > 72:
        raise HTTPException(status_code=400, detail="Password too long (max 72 bytes)")
    
    # Create user
    user = User(
        username=user_data.username,
        password_hash=hash_password(user_data.password)
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    return UserResponse(
        id=user.id,
        username=user.username,
        is_active=user.is_active,
        created_at=user.created_at,
        api_keys=[]
    )


@router.post("/api-key/{user_id}", response_model=APIKeyResponse, tags=["auth"])
def create_api_key(
    user_id: int,
    db: Session = Depends(get_db)
):
    """Generate a new API key for user"""
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Generate key
    raw_key = APIKey.generate_key()
    key_hash = APIKey.hash_key(raw_key)
    
    api_key = APIKey(
        user_id=user_id,
        key_hash=key_hash
    )
    
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    
    # Return raw key (only shown once)
    return APIKeyResponse(
        id=api_key.id,
        key=raw_key,
        is_active=api_key.is_active,
        created_at=api_key.created_at
    )


@router.get("/api-keys/{user_id}", response_model=List[APIKeyResponse], tags=["auth"])
def list_api_keys(
    user_id: int,
    db: Session = Depends(get_db)
):
    """List all API keys for user (without raw keys)"""
    api_keys = db.query(APIKey).filter(APIKey.user_id == user_id).all()
    
    return [
        APIKeyResponse(
            id=ak.id,
            key="***hidden***",  # Don't show raw keys
            is_active=ak.is_active,
            created_at=ak.created_at
        )
        for ak in api_keys
    ]