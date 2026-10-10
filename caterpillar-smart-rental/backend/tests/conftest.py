"""Each test runs startup, requests and services against one temporary file DB."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


@pytest.fixture
def test_app(tmp_path):
    application = create_app(Settings(
        database_url=f"sqlite:///{(tmp_path / 'fleetsignal.db').as_posix()}",
        data_dir=Path(__file__).resolve().parents[2] / "data",
        demo_mode=True,
    ))
    # Startup runs once, using the same resources request dependencies will use.
    with TestClient(application, raise_server_exceptions=True) as test_client:
        yield application, test_client


@pytest.fixture
def db_session(test_app):
    application, _client = test_app
    session = application.state.session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(test_app):
    _application, test_client = test_app
    yield test_client
