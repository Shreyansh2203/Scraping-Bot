"""Process-wide isolation for the test suite.

`Settings` reads its entire configuration from `os.getenv`, so the presence of any of
those variables in the shell that launched pytest changes what the suite observes. Each
test sets the variables it cares about with `monkeypatch`, but nothing removed the ones
it did not care about. A developer with `HEALTH_BIND=0.0.0.0`, `WEBHOOK_URL` or
`SUBPROCESS_TIMEOUT` exported in their shell got failures in `tests/test_config.py`
that reproduced for nobody else and looked like a real regression.

The fixture below removes all of them for the duration of each test, so the suite
observes only what the test itself asked for. `tests/test_repo_config.py` fails if
`core/config.py` grows a variable this list does not cover.
"""

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
    "MAX_DURATION_SECONDS",
    "MAX_FILE_SIZE_MB",
    "PORT",
    "RENDER_EXTERNAL_HOSTNAME",
    "SUBPROCESS_TIMEOUT",
    "WEBHOOK_URL",
)


@pytest.fixture(autouse=True)
def _isolate_bot_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ISOLATED_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
