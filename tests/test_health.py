import json

import pytest
from aiohttp import ClientSession, ClientTimeout

from bot.main import __version__, health_handler, start_health_server
from core.config import Settings


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


async def test_health_server_listens_on_all_ipv4_interfaces(monkeypatch, mock_downloader):
    monkeypatch.setenv("HEALTH_BIND", "0.0.0.0")
    settings = Settings()
    runner = await start_health_server(None, mock_downloader, port=0, bind=settings.HEALTH_BIND)
    try:
        [(host, port)] = runner.addresses
        assert host == "0.0.0.0"
        async with ClientSession(timeout=ClientTimeout(total=5)) as session:
            async with session.get(f"http://127.0.0.1:{port}/health") as response:
                assert response.status == 200
                assert (await response.json())["status"] == "ok"
    finally:
        await runner.cleanup()
