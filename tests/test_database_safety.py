"""Reject unsafe database targets before integration fixtures can change schemas."""

import pytest

from customerops_ai.core.config import Settings
from tests.integration.conftest import test_database_url as validate_test_url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://localhost/customerops",
        "sqlite+aiosqlite:///customerops_test",
        "postgresql+asyncpg://localhost/",
    ],
)
def test_integration_target_requires_separate_postgres_test_database(url: str) -> None:
    with pytest.raises(ValueError):
        validate_test_url(url, Settings())


def test_integration_target_cannot_match_development_database() -> None:
    with pytest.raises(ValueError, match="differ"):
        validate_test_url(
            "postgresql+asyncpg://localhost/customerops_test",
            Settings(database_name="customerops_test"),
        )
