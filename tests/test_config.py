import pytest
from core.config import Settings


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.delenv("DOWNLOAD_DIR", raising=False)
    monkeypatch.delenv("STATE_FILE", raising=False)
    monkeypatch.delenv("CONCURRENT_DOWNLOADS", raising=False)
    monkeypatch.delenv("MAX_FILE_SIZE_MB", raising=False)
    monkeypatch.delenv("ALLOWED_USERS", raising=False)

    settings = Settings()

    assert settings.BOT_TOKEN == ""
    assert settings.CONCURRENT_DOWNLOADS == 2
    assert settings.MAX_FILE_SIZE_MB == 50
    assert settings.ALLOWED_USERS == []


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("DOWNLOAD_DIR", "/tmp/downloads")
    monkeypatch.setenv("STATE_FILE", "/tmp/state.json")
    monkeypatch.setenv("CONCURRENT_DOWNLOADS", "5")
    monkeypatch.setenv("MAX_FILE_SIZE_MB", "100")
    monkeypatch.setenv("ALLOWED_USERS", "123,456")

    settings = Settings()

    assert settings.BOT_TOKEN == "123:ABC"
    assert settings.CONCURRENT_DOWNLOADS == 5
    assert settings.MAX_FILE_SIZE_MB == 100
    assert settings.ALLOWED_USERS == [123, 456]


def test_settings_validation(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "")
    settings = Settings()

    with pytest.raises(RuntimeError, match="BOT_TOKEN is not set"):
        settings.validate()


def test_settings_validation_success(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    settings = Settings()

    settings.validate()  # Should not raise
