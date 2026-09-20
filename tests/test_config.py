import logging

import pytest

from core.config import Settings


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.delenv("DOWNLOAD_DIR", raising=False)
    monkeypatch.delenv("CONCURRENT_DOWNLOADS", raising=False)
    monkeypatch.delenv("MAX_FILE_SIZE_MB", raising=False)
    monkeypatch.delenv("ALLOWED_USERS", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("HEALTH_PORT", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_HOSTNAME", raising=False)

    settings = Settings()

    assert settings.BOT_TOKEN == ""
    assert settings.CONCURRENT_DOWNLOADS == 2
    assert settings.MAX_FILE_SIZE_MB == 50
    assert settings.ALLOWED_USERS == []
    assert settings.WEBHOOK_URL == ""


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("DOWNLOAD_DIR", "/tmp/downloads")
    monkeypatch.setenv("CONCURRENT_DOWNLOADS", "5")
    monkeypatch.setenv("MAX_FILE_SIZE_MB", "100")
    monkeypatch.setenv("ALLOWED_USERS", "123,456")
    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "my-bot.onrender.com")

    settings = Settings()

    assert settings.BOT_TOKEN == "123:ABC"
    assert settings.CONCURRENT_DOWNLOADS == 5
    assert settings.MAX_FILE_SIZE_MB == 100
    assert settings.ALLOWED_USERS == [123, 456]
    assert settings.WEBHOOK_URL == "https://my-bot.onrender.com/webhook"


def test_settings_bot_mode_polling(monkeypatch):
    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "my-bot.onrender.com")
    monkeypatch.setenv("BOT_MODE", "polling")
    settings = Settings()
    assert settings.WEBHOOK_URL == ""


def test_settings_explicit_webhook_url(monkeypatch):
    monkeypatch.setenv("WEBHOOK_URL", "https://custom.domain.com/webhook")
    settings = Settings()
    assert settings.WEBHOOK_URL == "https://custom.domain.com/webhook"


def test_settings_safe_int_fallback(monkeypatch, caplog):
    monkeypatch.setenv("CONCURRENT_DOWNLOADS", "invalid_number")
    with caplog.at_level(logging.WARNING):
        settings = Settings()
        assert settings.CONCURRENT_DOWNLOADS == 2
    assert "Invalid integer value 'invalid_number'" in caplog.text


def test_settings_parse_allowed_users_with_invalid(monkeypatch, caplog):
    monkeypatch.setenv("ALLOWED_USERS", "123, invalid_id, 456")
    with caplog.at_level(logging.WARNING):
        settings = Settings()
        assert settings.ALLOWED_USERS == [123, 456]
    assert "Invalid user ID 'invalid_id'" in caplog.text


def test_settings_validation_errors(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "")
    settings = Settings()
    with pytest.raises(RuntimeError, match="BOT_TOKEN is not set"):
        settings.validate()

    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("CONCURRENT_DOWNLOADS", "0")
    settings = Settings()
    with pytest.raises(RuntimeError, match="CONCURRENT_DOWNLOADS must be >= 1"):
        settings.validate()

    monkeypatch.setenv("CONCURRENT_DOWNLOADS", "2")
    monkeypatch.setenv("MAX_FILE_SIZE_MB", "0")
    settings = Settings()
    with pytest.raises(RuntimeError, match="MAX_FILE_SIZE_MB must be >= 1"):
        settings.validate()


def test_settings_validation_public_bot_warning(monkeypatch, caplog):
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.delenv("ALLOWED_USERS", raising=False)
    settings = Settings()
    with caplog.at_level(logging.WARNING):
        settings.validate()
    assert "ALLOWED_USERS is empty; bot is public" in caplog.text


@pytest.mark.parametrize(
    ("port", "health_port", "expected"),
    [
        (None, None, 8080),
        (None, "8081", 8081),
        ("10000", None, 10000),
        ("10000", "8081", 10000),
    ],
)
def test_health_port_precedence(monkeypatch, port, health_port, expected):
    for name, value in (("PORT", port), ("HEALTH_PORT", health_port)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)

    assert Settings().HEALTH_PORT == expected


@pytest.mark.parametrize("name", ["PORT", "HEALTH_PORT"])
@pytest.mark.parametrize("value", ["0", "65536"])
def test_health_port_validation(monkeypatch, name, value):
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("HEALTH_PORT", raising=False)
    monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match="HEALTH_PORT must be between 1 and 65535"):
        Settings().validate()
