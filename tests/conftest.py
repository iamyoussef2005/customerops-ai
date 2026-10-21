"""Isolated HTTP client fixtures."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from customerops_ai.core.config import Settings
from customerops_ai.main import create_app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    """Exercise an application with controlled settings and a full lifespan."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CUSTOMEROPS_APP_NAME", "CustomerOps AI Test")
    monkeypatch.setenv("CUSTOMEROPS_ENVIRONMENT", "test")
    monkeypatch.delenv("CUSTOMEROPS_DATABASE_PASSWORD", raising=False)
    with TestClient(create_app(Settings())) as test_client:
        yield test_client


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--require-database",
        action="store_true",
        default=False,
        help="Fail instead of skip when CUSTOMEROPS_TEST_DATABASE_URL is missing",
    )
