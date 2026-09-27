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

    monkeypatch.setenv("MAX_FILE_SIZE_MB", "50")
    monkeypatch.setenv("MAX_DURATION_SECONDS", "0")
    settings = Settings()
    with pytest.raises(RuntimeError, match="MAX_DURATION_SECONDS must be >= 1"):
        settings.validate()


def test_settings_refuses_to_start_as_a_public_bot_without_an_explicit_opt_in(monkeypatch):
    """An empty allow-list used to be a warning, and a warning nobody reads is a public bot.

    One typo -- a missing value, a stray comma, a space instead of a comma -- parsed to an
    empty list, and AuthMiddleware treats an empty list as "no restriction", so the whole
    allow-list was one keystroke away from being switched off. The safe direction has to
    be the one that needs no action.
    """
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.delenv("ALLOWED_USERS", raising=False)
    monkeypatch.delenv("ALLOW_PUBLIC", raising=False)

    with pytest.raises(RuntimeError, match="ALLOWED_USERS is empty"):
        Settings().validate()


def test_settings_refuses_to_start_when_an_allow_list_entry_is_malformed(monkeypatch):
    """A dropped entry is a shorter allow-list than the operator wrote, which is the bug."""
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("ALLOWED_USERS", "123, not-an-id, 456")
    monkeypatch.delenv("ALLOW_PUBLIC", raising=False)

    with pytest.raises(RuntimeError, match="not-an-id"):
        Settings().validate()


def test_settings_still_logs_a_warning_for_a_deliberately_public_bot(monkeypatch, caplog):
    """ALLOW_PUBLIC=1 is the opt-in, and taking it should still leave a line in the log."""
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.delenv("ALLOWED_USERS", raising=False)
    monkeypatch.setenv("ALLOW_PUBLIC", "1")

    settings = Settings()
    with caplog.at_level(logging.WARNING):
        settings.validate()

    assert settings.ALLOWED_USERS == []
    assert "ALLOW_PUBLIC=1; bot is public" in caplog.text


@pytest.mark.parametrize("opt_in", ["", "0", "true", "yes", "2", " 1", "1 "])
def test_only_a_bare_one_opts_into_a_public_bot(monkeypatch, opt_in):
    """Anything short of the exact string leaves the bot refusing to start."""
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.delenv("ALLOWED_USERS", raising=False)
    monkeypatch.setenv("ALLOW_PUBLIC", opt_in)

    settings = Settings()
    if opt_in.strip() == "1":
        settings.validate()
    else:
        with pytest.raises(RuntimeError, match="ALLOWED_USERS is empty"):
            settings.validate()


def test_allow_public_does_not_excuse_a_malformed_allow_list(monkeypatch):
    """The opt-in is for an empty list, not a licence to ignore what was written."""
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("ALLOWED_USERS", "123,oops")
    monkeypatch.setenv("ALLOW_PUBLIC", "1")

    with pytest.raises(RuntimeError, match="oops"):
        Settings().validate()


# Every one of these parsed to an empty ALLOWED_USERS before, which AuthMiddleware
# reads as "no restriction". Each has to stop the bot now.
@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        ",",
        ",,",
        " , ",
        "123,abc",
        "123 456",
        "abc",
        "123,,abc",
        "123.0",
        "0x10",
        "+",
    ],
)
def test_every_malformed_allowed_users_value_fails_loudly(monkeypatch, value):
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("ALLOWED_USERS", value)
    monkeypatch.delenv("ALLOW_PUBLIC", raising=False)

    with pytest.raises(RuntimeError, match="ALLOWED_USERS"):
        Settings().validate()


def test_a_malformed_allow_list_is_parsed_but_never_silently_shortened(monkeypatch):
    """The parser still drops the bad entry; validate() is what refuses to proceed."""
    monkeypatch.setenv("ALLOWED_USERS", "123, 456, 4560")
    clean = Settings()
    assert clean.ALLOWED_USERS == [123, 456, 4560]
    assert clean._malformed_user_ids == []

    monkeypatch.setenv("ALLOWED_USERS", "123, 456, four-fifty-six")
    dirty = Settings()
    assert dirty.ALLOWED_USERS == [123, 456]
    assert dirty._malformed_user_ids == ["four-fifty-six"]


@pytest.mark.parametrize(
    "token",
    [
        "your_token_here",
        "123456:",
        "123 456:ABC",
        "123:ABC:DEF",
        "123:abc def",
        "@my_bot",
    ],
)
def test_settings_validation_rejects_malformed_bot_token(monkeypatch, token):
    monkeypatch.setenv("BOT_TOKEN", token)
    with pytest.raises(RuntimeError, match="BOT_TOKEN is malformed"):
        Settings().validate()


@pytest.mark.parametrize("token", ["123:ABC", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"])
def test_settings_validation_accepts_well_formed_bot_token(monkeypatch, token):
    monkeypatch.setenv("BOT_TOKEN", token)
    monkeypatch.setenv("CONCURRENT_DOWNLOADS", "2")
    monkeypatch.setenv("MAX_FILE_SIZE_MB", "50")
    monkeypatch.setenv("ALLOWED_USERS", "1")
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("HEALTH_PORT", raising=False)
    Settings().validate()


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
