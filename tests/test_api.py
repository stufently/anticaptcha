"""Tests for anticaptcha service API"""
import pytest
import os
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set test database before importing app
TEST_DB = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
TEST_DB.close()
os.environ['ANTICAPTCHA_DATABASE_PATH'] = TEST_DB.name
os.environ['ANTICAPTCHA_ADMIN_TOKEN'] = 'test-admin-token-12345'

from app.main import app
from app.database import Base, get_db
from app.models.api_key import User, APIKey
from app.config import settings

# Test database setup
TEST_DATABASE_URL = f"sqlite:///{TEST_DB.name}"
test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="function")
def db_session():
    """Create test database session"""
    Base.metadata.create_all(bind=test_engine)
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def client(db_session):
    """Create test client with test database"""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin_headers():
    """Headers with admin token"""
    return {"Authorization": f"Bearer {settings.admin_token}"}


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


def test_create_user_without_auth(client):
    """Test user creation without auth returns 401"""
    response = client.post(
        "/api/v1/user",
        json={"username": "testuser", "password": "testpass"}
    )
    assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"


def test_create_user_with_admin_token(client, admin_headers):
    """Test user creation with admin token"""
    response = client.post(
        "/api/v1/user",
        json={"username": "testuser", "password": "testpass"},
        headers=admin_headers
    )
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["username"] == "testuser"
    assert "id" in data
    assert data["is_active"] is True


def test_create_api_key_without_auth(client, db_session):
    """Test API key creation without auth returns 401"""
    # Create user first
    user = User(username="testuser", password_hash="hash", password_salt="salt")
    db_session.add(user)
    db_session.commit()
    
    response = client.post(f"/api/v1/api-key/{user.id}")
    assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"


def test_create_api_key_with_admin_token(client, db_session, admin_headers):
    """Test API key creation with admin token"""
    # Create user first
    user = User(username="testuser", password_hash="hash", password_salt="salt")
    db_session.add(user)
    db_session.commit()
    
    response = client.post(f"/api/v1/api-key/{user.id}", headers=admin_headers)
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert "key" in data
    assert data["key"].startswith("ac_")


def test_create_task_without_api_key(client):
    """Test task creation without API key returns 401"""
    response = client.post(
        "/api/v1/task",
        json={
            "captcha_type": "recaptcha_v2",
            "page_url": "https://example.com"
        }
    )
    assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"


def test_create_task_with_api_key(client, db_session, admin_headers):
    """Test task creation with valid API key"""
    # Create user and API key
    user = User(username="testuser", password_hash="hash", password_salt="salt")
    db_session.add(user)
    db_session.commit()
    
    # Create API key using admin token
    response = client.post(f"/api/v1/api-key/{user.id}", headers=admin_headers)
    assert response.status_code == 200
    api_key = response.json()["key"]
    
    # Create task with API key
    headers = {"Authorization": f"Bearer {api_key}"}
    response = client.post(
        "/api/v1/task",
        json={
            "captcha_type": "recaptcha_v2",
            "page_url": "https://example.com",
            "site_key": "test-site-key"
        },
        headers=headers
    )
    # Should accept the task (200 or 201)
    assert response.status_code in [200, 201], f"Expected 200/201, got {response.status_code}: {response.text}"
    data = response.json()
    assert "task_id" in data


def test_invalid_api_key(client):
    """Test task creation with invalid API key returns 401"""
    headers = {"Authorization": "Bearer invalid-key-12345"}
    response = client.post(
        "/api/v1/task",
        json={
            "captcha_type": "recaptcha_v2",
            "page_url": "https://example.com"
        },
        headers=headers
    )
    assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"


def test_invalid_admin_token(client):
    """Test user creation with invalid admin token returns 401"""
    headers = {"Authorization": "Bearer invalid-admin-token"}
    response = client.post(
        "/api/v1/user",
        json={"username": "testuser", "password": "testpass"},
        headers=headers
    )
    assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"


def test_create_duplicate_user(client, admin_headers):
    """Test creating duplicate username returns 400"""
    # Create first user
    response = client.post(
        "/api/v1/user",
        json={"username": "duplicate", "password": "pass1"},
        headers=admin_headers
    )
    assert response.status_code == 200
    
    # Try to create duplicate
    response = client.post(
        "/api/v1/user",
        json={"username": "duplicate", "password": "pass2"},
        headers=admin_headers
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


def cleanup():
    """Cleanup test database"""
    try:
        os.unlink(TEST_DB.name)
    except:
        pass


if __name__ == "__main__":
    try:
        pytest.main([__file__, "-v"])
    finally:
        cleanup()