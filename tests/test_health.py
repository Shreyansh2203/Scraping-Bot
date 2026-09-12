import json

import pytest

from bot.main import __version__, health_handler


@pytest.fixture
def mock_downloader(tmp_path):
    class FakeDownloader:
        concurrent = 2
        output_dir = tmp_path / "downloads"
        state_file = tmp_path / "state.json"

    return FakeDownloader()


async def test_health_handler(mock_downloader):
    request = type("Request", (), {})()
    request.app = {"downloader": mock_downloader}

    response = await health_handler(request)
    assert response.status == 200

    data = json.loads(response.body.decode())
    assert data["status"] == "ok"
    assert data["version"] == __version__
    assert data["concurrent"] == 2
    assert "downloads" in data["output_dir"]
