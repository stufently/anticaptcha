"""CLI tools for anticaptcha administration"""
import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models.api_key import User, APIKey


def create_key(username: str):
    """Create API key for user"""
    db = SessionLocal()
    try:
        # Find user
        user = db.query(User).filter(User.username == username).first()
        if not user:
            print(f"Error: User '{username}' not found")
            sys.exit(1)
        
        # Generate key
        raw_key = APIKey.generate_key()
        key_hash = APIKey.hash_key(raw_key)
        
        api_key = APIKey(
            user_id=user.id,
            key_hash=key_hash
        )
        
        db.add(api_key)
        db.commit()
        
        print(f"API key created for user '{username}':")
        print(raw_key)
        
    finally:
        db.close()


def create_user(username: str, password: str, admin: bool = False):
    """Create new user"""
    db = SessionLocal()
    try:
        # Check if exists
        if db.query(User).filter(User.username == username).first():
            print(f"Error: User '{username}' already exists")
            sys.exit(1)
        
        # Hash password
        import hashlib
        import secrets
        salt = secrets.token_hex(16)
        password_hash = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
        
        user = User(
            username=username,
            password_hash=password_hash,
            password_salt=salt,
            is_admin=admin
        )
        
        db.add(user)
        db.commit()
        
        print(f"User '{username}' created (admin={admin})")
        
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="AntiCAPTCHA CLI")
    subparsers = parser.add_subparsers(dest="command")
    
    # create-key
    key_parser = subparsers.add_parser("create-key", help="Create API key for user")
    key_parser.add_argument("username", help="Username")
    
    # create-user
    user_parser = subparsers.add_parser("create-user", help="Create new user")
    user_parser.add_argument("username", help="Username")
    user_parser.add_argument("password", help="Password")
    user_parser.add_argument("--admin", action="store_true", help="Make user admin")
    
    args = parser.parse_args()
    
    if args.command == "create-key":
        create_key(args.username)
    elif args.command == "create-user":
        create_user(args.username, args.password, args.admin)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()