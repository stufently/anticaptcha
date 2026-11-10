"""Authentication endpoints for user and API key management"""
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.api_key import User, APIKey
from app.schemas.user import UserCreate, UserResponse, APIKeyResponse
import hashlib
import secrets
from typing import List, Optional

router = APIRouter()


def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    """Hash password with SHA-256 and salt"""
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return hashed, salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    """Verify password against hash"""
    hashed, _ = hash_password(password, salt)
    return hashed == password_hash


def get_current_user(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)) -> User:
    """Get current user from API key"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    
    # Extract API key from "Bearer <key>"
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization format")
    
    api_key_value = parts[1]
    
    # Find API key
    key_hash = APIKey.hash_key(api_key_value)
    api_key = db.query(APIKey).filter(APIKey.key_hash == key_hash, APIKey.is_active == True).first()
    
    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    # Get user
    user = db.query(User).filter(User.id == api_key.user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    
    return user


@router.post("/user", response_model=UserResponse, tags=["auth"])
def create_user(
    user_data: UserCreate,
    db: Session = Depends(get_db)
):
    """Create a new user (first user becomes admin)"""
    # Check if user exists
    if db.query(User).filter(User.username == user_data.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")

    # Hash password with salt
    password_hash, salt = hash_password(user_data.password)

    # First user becomes admin
    is_first_user = db.query(User).count() == 0

    # Create user
    user = User(
        username=user_data.username,
        password_hash=password_hash,
        password_salt=salt,
        is_admin=is_first_user
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Generate a new API key for user (requires auth, admin can create for any user)"""
    # Only admin can create keys for other users
    if current_user.id != user_id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Can only create API keys for yourself")
    
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