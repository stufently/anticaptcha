#!/usr/bin/env python3
"""Initialize database with default user and API key"""
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from app.database import SessionLocal, init_db
from app.models.user import User
from app.models.api_key import APIKey
from app.models.stats import Stats
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def main():
    """Initialize database with default data"""
    print("🔧 Initializing database...")
    
    # Create tables
    init_db()
    print("✅ Tables created")
    
    db = SessionLocal()
    
    try:
        # Check if default user exists
        existing_user = db.query(User).filter(User.username == "admin").first()
        
        if existing_user:
            print("ℹ️  Default user already exists")
        else:
            # Create default user
            user = User(
                username="admin",
                password_hash=pwd_context.hash("admin123")
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            print(f"✅ Created user: {user.username}")
            
            # Generate API key
            raw_key = APIKey.generate_key()
            key_hash = APIKey.hash_key(raw_key)
            
            api_key = APIKey(
                user_id=user.id,
                key_hash=key_hash
            )
            db.add(api_key)
            db.commit()
            print(f"🔑 API Key: {raw_key}")
            print("⚠️  Save this key! It won't be shown again.")
        
        # Create stats record
        if not db.query(Stats).first():
            stats = Stats()
            db.add(stats)
            db.commit()
            print("✅ Created stats record")
        
        print("\n✅ Database initialization complete!")
        
        if not existing_user:
            print("\n📋 Default credentials:")
            print("   Username: admin")
            print("   Password: admin123")
    
    finally:
        db.close()


if __name__ == "__main__":
    main()