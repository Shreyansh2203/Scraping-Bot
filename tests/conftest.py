import pytest

# Every name core/config.py reads. Kept in step with the source by
# test_every_variable_the_settings_reads_is_isolated in tests/test_repo_config.py.
ISOLATED_ENV_VARS = (
    "ALLOW_PUBLIC",
    "ALLOWED_USERS",
    "BOT_MODE",
    "BOT_TOKEN",
    "CONCURRENT_DOWNLOADS",
    "DOWNLOAD_DIR",
    "FFPROBE_TIMEOUT",
    "HEALTH_BIND",
    "HEALTH_PORT",
    "MAX_DISK_USAGE_PERCENT",
    "MAX_DURATION_SECONDS",
    "MAX_FILE_SIZE_MB",
    "PORT",
    "REDIS_URL",
    "RENDER_EXTERNAL_HOSTNAME",
    "SUBPROCESS_TIMEOUT",
    "WEBHOOK_URL",
)


@pytest.fixture(autouse=True)
def _isolate_bot_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ISOLATED_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
