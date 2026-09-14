import pytest

from bot.handlers.download import _URL_RE


@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/reel/ABC123/",
        "https://instagram.com/p/ABC123/",
        "https://www.instagram.com/reel/ABC123",
        "https://x.com/user/status/1234567890",
        "https://twitter.com/user/status/1234567890",
        "https://x.com/user/status/1234567890/",
    ],
)
def test_url_regex_valid(url):
    assert _URL_RE.search(url) is not None


@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/profile/user/",
        "https://x.com/user",
        "https://twitter.com/user",
        "not a url",
        "https://example.com",
    ],
)
def test_url_regex_invalid(url):
    assert _URL_RE.search(url) is None


def test_url_regex_extract():
    text = (
        "Check this: https://www.instagram.com/reel/ABC123/ and this https://x.com/user/status/123/"
    )
    matches = [m.group(0) for m in _URL_RE.finditer(text)]
    assert len(matches) == 2
    assert matches[0] == "https://www.instagram.com/reel/ABC123"
    assert matches[1] == "https://x.com/user/status/123"
