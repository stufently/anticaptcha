"""CLI tools for anticaptcha administration"""
import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models.api_key import User, APIKey
from app.models.task import Task

# Tasks the worker may still pick up or is solving right now.
ACTIVE_TASK_STATUSES = ("pending", "processing")


def _fail(message: str):
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


def create_key(username: str):
    """Create API key for user"""
    db = SessionLocal()
    try:
        # Lookup and insert in one write transaction: a parallel delete-user
        # must not commit in between and leave a key without its user.
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        # Find user
        user = db.query(User).filter(User.username == username).first()
        if not user:
            db.rollback()
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


def list_keys(username: str):
    """Print id, state and creation time of the user's keys (never the keys)"""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            _fail(f"User '{username}' not found")
        keys = db.query(APIKey).filter(APIKey.user_id == user.id).order_by(APIKey.id).all()
        if not keys:
            print(f"User '{username}' has no API keys")
            return
        for key in keys:
            state = "active" if key.is_active else "revoked"
            print(f"id={key.id} {state} created_at={key.created_at}")
    finally:
        db.close()


def revoke_key(key_id: int = None, username: str = None):
    """Deactivate one key by id, or every active key of a user.

    The row stays: its tasks keep a valid api_key_id, and the hash of a revoked
    key can never authenticate again (auth filters on is_active).
    """
    db = SessionLocal()
    try:
        # Read and update under one write lock, like delete-user.
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        if key_id is not None:
            key = db.query(APIKey).filter(APIKey.id == key_id).first()
            if not key:
                db.rollback()
                _fail(f"API key id={key_id} not found")
            if not key.is_active:
                db.rollback()
                print(f"API key id={key_id} is already revoked")
                return
            key.is_active = False
            db.commit()
            print(f"API key id={key_id} revoked")
            return

        user = db.query(User).filter(User.username == username).first()
        if not user:
            db.rollback()
            _fail(f"User '{username}' not found")
        keys = db.query(APIKey).filter(
            APIKey.user_id == user.id, APIKey.is_active == True  # noqa: E712
        ).all()
        for key in keys:
            key.is_active = False
        db.commit()
        print(f"Revoked {len(keys)} API key(s) of user '{username}'")
    finally:
        db.close()


def delete_user(username: str, yes: bool = False):
    """Delete a user together with its API keys and their tasks.

    tasks.api_key_id is NOT NULL, so a task cannot outlive its key: the tasks go
    first, then the keys, then the user, in one write transaction. A user with
    pending/processing tasks is refused - the worker may be solving one of them
    right now; revoke the keys, wait for the tasks to finish and retry.
    """
    if not yes:
        _fail(f"refusing to delete user '{username}' without --yes "
              "(deletes the user, all its API keys and their tasks)")
    db = SessionLocal()
    try:
        # Take the SQLite write lock up front: neither the API (new task) nor
        # the worker (claiming a pending task) can slip in between the check
        # for active tasks and the deletes.
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        user = db.query(User).filter(User.username == username).first()
        if not user:
            db.rollback()
            _fail(f"User '{username}' not found")
        key_ids = [k.id for k in db.query(APIKey.id).filter(APIKey.user_id == user.id)]
        tasks = db.query(Task).filter(Task.api_key_id.in_(key_ids))
        active = tasks.filter(Task.status.in_(ACTIVE_TASK_STATUSES)).count()
        if active:
            db.rollback()
            _fail(f"user '{username}' has {active} pending/processing task(s); "
                  f"run 'revoke-key --user {username}', wait for them to finish "
                  "and retry")
        task_count = tasks.delete(synchronize_session=False)
        key_count = db.query(APIKey).filter(APIKey.user_id == user.id).delete(
            synchronize_session=False
        )
        db.query(User).filter(User.id == user.id).delete(synchronize_session=False)
        db.commit()
        print(f"User '{username}' deleted with {key_count} API key(s) "
              f"and {task_count} task(s)")
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
    
    # list-keys
    list_parser = subparsers.add_parser(
        "list-keys", help="List API key ids of a user (keys themselves are not shown)"
    )
    list_parser.add_argument("username", help="Username")

    # revoke-key
    revoke_parser = subparsers.add_parser(
        "revoke-key", help="Revoke one API key by id, or all keys of a user"
    )
    target = revoke_parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--id", type=int, dest="key_id", help="API key id (see list-keys)")
    target.add_argument("--user", dest="username", help="Revoke every active key of this user")

    # delete-user
    delete_parser = subparsers.add_parser(
        "delete-user", help="Delete a user, its API keys and their tasks"
    )
    delete_parser.add_argument("username", help="Username")
    delete_parser.add_argument("--yes", action="store_true", help="Confirm the deletion")

    args = parser.parse_args()
    
    if args.command == "create-key":
        create_key(args.username)
    elif args.command == "create-user":
        create_user(args.username, args.password, args.admin)
    elif args.command == "list-keys":
        list_keys(args.username)
    elif args.command == "revoke-key":
        revoke_key(key_id=args.key_id, username=args.username)
    elif args.command == "delete-user":
        delete_user(args.username, yes=args.yes)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()