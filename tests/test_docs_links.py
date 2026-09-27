"""Checks the relative links and in-document anchors in the Markdown docs.

Documentation that points at a file that moved, or a section that got renamed, is a
silent rot that no other gate would catch. This walks the same links a reader would
follow, so the fix is always "update the doc" rather than "delete the assertion".
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = ("README.md", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md")

# [text](target) and [text](target "title"), ignoring images and inline code.
LINK = re.compile(r"(?<!\!)\[(?P<text>[^\]]*)\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^\s*```")


def _slug(heading: str) -> str:
    """GitHub's heading slug: lowercase, punctuation dropped, spaces to hyphens."""
    slug = heading.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    return slug.replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    return {slug for _, slug in _headings(path)}


def _headings(path: Path) -> list[tuple[int, str]]:
    headings: list[tuple[int, str]] = []
    in_fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r"^(#{1,6})\s+(.*?)\s*#*$", line)
        if match:
            headings.append((len(match.group(1)), _slug(match.group(2))))
    return headings


def _targets(text: str) -> list[str]:
    in_fence = False
    found = []
    for line in text.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            found.extend(m.group("target") for m in LINK.finditer(line))
    return found


def _documented_paths(doc: str) -> list[str]:
    return [target for target in _targets(_read(doc)) if not _is_external(target)]


def _read(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8")


def _is_external(target: str) -> bool:
    return target.startswith(("http://", "https://", "mailto:"))


@pytest.mark.parametrize("doc", DOCS)
def test_relative_links_resolve(doc: str) -> None:
    missing = [
        target
        for target in _documented_paths(doc)
        if not (REPO_ROOT / target.split("#", 1)[0]).exists()
    ]
    assert not missing, f"{doc} links to {missing}, which do not exist in the repository"


@pytest.mark.parametrize("doc", DOCS)
def test_same_document_anchors_exist(doc: str) -> None:
    anchors = _anchors(REPO_ROOT / doc)
    dangling = [
        target
        for target in _documented_paths(doc)
        if target.startswith("#") and target[1:] not in anchors
    ]
    assert not dangling, f"{doc} links to {dangling}, which are not headings in the file"


def test_readme_table_of_contents_matches_the_headings() -> None:
    readme = _read("README.md")
    toc = readme.split("## Table of contents", 1)[1].split("\n## ", 1)[0]
    listed = {target[1:] for target in _targets(toc)}
    # Level 1 is the document title, and the table of contents does not list itself.
    headings = {slug for level, slug in _headings(REPO_ROOT / "README.md") if level >= 2} - {
        "table-of-contents"
    }
    assert listed <= headings, f"the table of contents lists {sorted(listed - headings)}"
    assert (
        headings <= listed
    ), f"README has sections missing from the table of contents: {sorted(headings - listed)}"


def test_cross_document_anchors_exist() -> None:
    for doc in DOCS:
        for target in _documented_paths(doc):
            path_part, _, fragment = target.partition("#")
            if not fragment or not path_part:
                continue
            other = REPO_ROOT / path_part
            if other.suffix == ".md":
                assert fragment in _anchors(other), f"{doc} links to {target}, no such heading"
