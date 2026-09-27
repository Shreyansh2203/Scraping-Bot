"""Guards on the deployment contract the code and the docs agree on.

Nothing here runs the image; these assert the declarations that the CI container job
then exercises for real. The point is to fail fast and locally when a documented
requirement drifts away from the Dockerfile, rather than discovering it in a release.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8")


def _logical_lines(text: str) -> list[str]:
    """Join shell line continuations so a multi-line RUN is one logical line."""
    logical: list[str] = []
    buffer = ""
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        buffer = f"{buffer} {stripped}" if buffer else stripped
        if buffer.endswith("\\"):
            buffer = buffer[:-1].rstrip()
            continue
        logical.append(buffer)
        buffer = ""
    if buffer:
        logical.append(buffer)
    return logical


def _apt_install_packages(dockerfile: str) -> set[str]:
    for line in _logical_lines(dockerfile):
        if "apt-get install" not in line:
            continue
        install = line.split("apt-get install", 1)[1]
        install = install.split("&&", 1)[0]
        return {token for token in install.split() if not token.startswith("-")}
    return set()


def _final_user(dockerfile: str) -> str | None:
    user = None
    for line in _logical_lines(dockerfile):
        if line.upper().startswith("USER "):
            user = line.split(None, 1)[1].strip()
    return user


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return _read("Dockerfile")


def test_dockerfile_installs_ffmpeg(dockerfile: str) -> None:
    assert "ffmpeg" in _apt_install_packages(dockerfile), (
        "the Dockerfile no longer installs ffmpeg; yt-dlp needs it to merge separate "
        "audio and video streams, and DownloaderWrapper._build_command silently drops "
        "to the pre-merged 'best' format selector when it is missing"
    )


def test_readme_documented_ffmpeg_requirement_matches_the_image() -> None:
    readme = _read("README.md")
    requirements = readme.split("## Requirements", 1)[1].split("\n## ", 1)[0]
    assert "ffmpeg" in requirements.lower(), "README no longer documents ffmpeg as a requirement"
    assert "ffmpeg" in _apt_install_packages(_read("Dockerfile"))


def test_image_runs_as_a_non_root_user(dockerfile: str) -> None:
    user = _final_user(dockerfile)
    assert user is not None, "the Dockerfile never switches away from root"
    assert user not in {"root", "0"}, f"the image runs as {user!r}; it is meant to run as botuser"


def test_image_binds_the_health_server_on_all_interfaces(dockerfile: str) -> None:
    # core/config.py binds 127.0.0.1 by default, which is unreachable from outside the
    # container, so the image has to override it or /health never answers on Render.
    env_lines = [
        line.split(None, 1)[1]
        for line in _logical_lines(dockerfile)
        if line.upper().startswith("ENV ")
    ]
    assert any(
        pair.split("=", 1)[0] == "HEALTH_BIND" and pair.split("=", 1)[1] == "0.0.0.0"
        for line in env_lines
        for pair in line.split()
    ), "the image does not set HEALTH_BIND=0.0.0.0, so /health stays on loopback"
