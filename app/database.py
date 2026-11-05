"""Database connection and session management"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pathlib import Path
from app.config import settings

# Ensure data directory exists
Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{settings.database_path}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency to get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database tables"""
    from app.models import task, api_key  # Import models to register them
    Base.metadata.create_all(bind=engine)