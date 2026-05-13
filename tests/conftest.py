import pytest
import pytest_asyncio
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from server.main import app
from server.models import Base, get_db
from server import broadcaster

# ---------------------------------------------------------------------------
# Test database setup
# ---------------------------------------------------------------------------

TEST_DB_URL = "sqlite:///./test_messenger.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(autouse=True)
def clear_broadcaster():
    broadcaster._subscribers.clear()
    yield


@pytest_asyncio.fixture
async def async_client():
    from httpx import ASGITransport
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

# ---------------------------------------------------------------------------
# Shared Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_helper():
    def _auth(token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}
    return _auth

@pytest.fixture
def register_and_login_async():
    async def _register_and_login(client: httpx.AsyncClient, username="alice", password="secret123") -> str:
        await client.post("/register", json={"username": username, "password": password})
        response = await client.post("/login", json={"username": username, "password": password})
        return response.json()["access_token"]
    return _register_and_login

@pytest.fixture
def db_session():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()
