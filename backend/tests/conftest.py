import os, tempfile
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from main import app
from db import Base, get_db
from security import verify_admin 

@pytest.fixture(scope="session")
def tmp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path

@pytest.fixture(scope="session")
def test_engine(tmp_db_path):
    url = f"sqlite:///{tmp_db_path}"
    engine = create_engine(url, connect_args={"check_same_thread": False})

    # SQLite force foreign key constraints
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    return engine

@pytest.fixture(scope="session")
def TestingSessionLocal(test_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

@pytest.fixture(scope="session", autouse=True)
def override_di(TestingSessionLocal):
    def _get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[verify_admin] = lambda: None

@pytest.fixture
def client(monkeypatch):
    os.environ["ADMIN_API_KEY"] = "test-key"
    # Mock LLM scoring function
    def fake_score(answer_text, guideline):
        if not answer_text or not guideline:
            return None, None
        return (4.5, "mock rationale") if "good" in answer_text.lower() else (1.0, "mock rationale")
    monkeypatch.setattr("llm_scorer.score_answer", fake_score)
    monkeypatch.setattr("main.score_answer", fake_score) 
    return TestClient(app)
