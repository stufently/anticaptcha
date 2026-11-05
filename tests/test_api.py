"""Tests for anticaptcha service"""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db, Base, engine
from sqlalchemy.orm import Session
from app.models.task import Task
from app.models.api_key import APIKey, User


# Test database
TEST_DATABASE_URL = "sqlite:///./test.db"


@pytest.fixture
def client():
    """Create test client"""
    return TestClient(app)


@pytest.fixture
def db():
    """Create test database session"""
    # Create tables
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    try:
        yield db
    finally:
        db.close()
        # Cleanup
        Base.metadata.drop_all(bind=engine)


def test_root_endpoint(client):
    """Test root endpoint"""
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "anticaptcha"


def test_health_endpoint(client):
    """Test health endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_create_user(client, db):
    """Test user creation"""
    response = client.post(
        "/api/v1/user",
        json={"username": "testuser", "password": "testpass"}
    )
    assert response.status_code == 200
    assert response.json()["username"] == "testuser"


def test_create_api_key(client, db):
    """Test API key generation"""
    # Create user first
    user_response = client.post(
        "/api/v1/user",
        json={"username": "testuser", "password": "testpass"}
    )
    user_id = user_response.json()["id"]
    
    # Generate API key
    response = client.post(f"/api/v1/api-key/{user_id}")
    assert response.status_code == 200
    assert "key" in response.json()
    assert response.json()["key"].startswith("ac_")


def test_create_task_without_api_key(client):
    """Test task creation without API key"""
    response = client.post(
        "/api/v1/task",
        json={
            "type": "image_text",
            "input_data": {"image": "test"}
        }
    )
    assert response.status_code == 422  # Missing header


if __name__ == "__main__":
    pytest.main([__file__, "-v"])