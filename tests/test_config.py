"""Environment-based configuration behavior."""

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from customerops_ai.core.config import Settings


def test_environment_overrides_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("CUSTOMEROPS_APP_NAME=From file\n", encoding="utf-8")
    monkeypatch.setenv("CUSTOMEROPS_APP_NAME", "From environment")
    monkeypatch.setenv("CUSTOMEROPS_ENVIRONMENT", "test")

    assert Settings().app_name == "From environment"


def test_invalid_environment_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CUSTOMEROPS_ENVIRONMENT", "invalid")

    with pytest.raises(ValidationError, match="environment"):
        Settings()


def test_database_url_handles_reserved_password_characters() -> None:
    password = SecretStr("fictional:test@value/%")
    settings = Settings(database_password=password)
    assert settings.database_url.password == password.get_secret_value()
    assert password.get_secret_value() not in repr(settings)
    assert password.get_secret_value() not in str(settings.database_url)


def test_database_password_is_required_only_for_database_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CUSTOMEROPS_DATABASE_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="CUSTOMEROPS_DATABASE_PASSWORD"):
        _ = Settings().database_url


def test_empty_database_password_is_rejected() -> None:
    with pytest.raises(ValidationError, match="database_password"):
        Settings(database_password=SecretStr(""))


def test_agent_model_and_key_may_be_disabled_with_blank_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("CUSTOMEROPS_AGENT_MODEL", "")
    assert Settings().openai_api_key is None
    assert Settings().agent_model is None


def test_authentication_mapping_rejects_raw_tokens() -> None:
    from uuid import uuid4

    with pytest.raises(ValidationError, match="SHA-256"):
        Settings(auth_token_customers={"fictional-raw-token": uuid4()})
