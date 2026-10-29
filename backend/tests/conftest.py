import os
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

_test_database = Path(tempfile.gettempdir()) / f"parking-test-{uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_test_database.as_posix()}"
os.environ["SECRET_KEY"] = "test-only-secret-key"

from app.database import Base, SessionLocal, engine
from app.main import app


@pytest.fixture
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(client):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_database():
    yield
    engine.dispose()
    _test_database.unlink(missing_ok=True)