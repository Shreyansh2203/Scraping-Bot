import pytest


@pytest.fixture(autouse=True)
def _reset_asyncio_mode():
    pass
