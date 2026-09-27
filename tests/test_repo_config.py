"""Gates on the configuration this repository ships rather than imports.

`render.yaml`, `render.yaml`'s comments, and `.release-please-config.json` are all
consumed by a third party at deploy or release time, which means nothing in the test
suite or the type checker would notice when they drift away from the code and the
README. These assertions are deliberately written without a YAML dependency: the
structures being read are a list of mappings and a list of sections.
"""

import json
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Variables Render supplies at runtime. core/config.py reads PORT in preference to
# HEALTH_PORT and derives the webhook URL from RENDER_EXTERNAL_HOSTNAME.
RENDER_INJECTED = {"PORT", "RENDER_EXTERNAL_HOSTNAME"}

# Variables the README documents that the blueprint deliberately does not declare.
# Each maps to the reason, and render.yaml has to state the same reason in a comment.
DELIBERATELY_ABSENT = {
    "HEALTH_PORT": "superseded by the injected PORT",
    "BOT_MODE": "webhook is the correct mode on Render",
    "WEBHOOK_URL": "derived from the injected RENDER_EXTERNAL_HOSTNAME",
}

# The Conventional Commit types this repository uses, and therefore the ones
# release-please has to have a section for.
REQUIRED_CHANGELOG_TYPES = {
    "feat",
    "fix",
    "refactor",
    "docs",
    "chore",
    "chore(deps)",
    "test",
    "ci",
    "build",
    "perf",
    "style",
}


def _read(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8")


def _render_env_keys() -> set[str]:
    keys: set[str] = set()
    in_env_vars = False
    for line in _read("render.yaml").splitlines():
        if re.match(r"^\s*envVars:\s*$", line):
            in_env_vars = True
            continue
        if in_env_vars and re.match(r"^\s*-\s+key:\s*\S+", line):
            keys.add(re.search(r"key:\s*(\S+)", line).group(1))  # type: ignore[union-attr]
        elif in_env_vars and line.strip() and not line.startswith(" " * 8):
            in_env_vars = False
    return keys


def _readme_env_keys() -> set[str]:
    table = _read("README.md").split("## Configuration", 1)[1].split("\n## ", 1)[0]
    keys: set[str] = set()
    for line in table.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 2:
            name = cells[0].strip("`")
            if re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
                keys.add(name)
    return keys


def test_every_documented_variable_is_declared_or_accounted_for() -> None:
    unaccounted = (
        _readme_env_keys() - _render_env_keys() - RENDER_INJECTED - set(DELIBERATELY_ABSENT)
    )
    assert not unaccounted, (
        f"the README documents {sorted(unaccounted)} but render.yaml neither declares them "
        "nor explains why they are absent"
    )


def _render_comments() -> str:
    """All comment lines in render.yaml, whitespace-collapsed so that a reason that
    wraps across two comment lines still reads as one string."""
    comment = "\n".join(
        line.lstrip().lstrip("#").strip() for line in _read("render.yaml").splitlines()
    )
    return re.sub(r"\s+", " ", comment)


def test_render_yaml_explains_every_deliberate_omission() -> None:
    comment = _render_comments()
    for name, reason in DELIBERATELY_ABSENT.items():
        assert name in comment, f"render.yaml does not mention the omitted {name}"
        assert (
            re.sub(r"\s+", " ", reason) in comment
        ), f"render.yaml does not give the reason {name} is omitted"


def test_render_yaml_explains_the_render_injected_variables() -> None:
    comment = _render_comments()
    for name in RENDER_INJECTED:
        assert name in comment, f"render.yaml does not mention the Render-injected {name}"


def test_allow_list_is_prompted_for_and_never_hardcoded() -> None:
    render = _read("render.yaml")
    block = render.split("- key: ALLOWED_USERS", 1)[1].split("- key:", 1)[0]
    assert "sync: false" in block, "ALLOWED_USERS must be left to the Render dashboard"
    # value: "" would make the bot public, and would overwrite a value entered in the
    # dashboard on every sync. This is the one line in the file that must not come back.
    assert not re.search(
        r"^\s*value:\s*", block, re.MULTILINE
    ), "ALLOWED_USERS must not carry a value in render.yaml"


def test_bot_token_is_prompted_for_and_never_hardcoded() -> None:
    render = _read("render.yaml")
    block = render.split("- key: BOT_TOKEN", 1)[1].split("- key:", 1)[0]
    assert "sync: false" in block
    assert not re.search(r"^\s*value:\s*", block, re.MULTILINE)


def test_release_please_manifest_matches_the_package_version() -> None:
    manifest = json.loads(_read(".release-please-manifest.json"))
    pyproject = tomllib.loads(_read("pyproject.toml"))
    assert (
        manifest["."] == pyproject["project"]["version"]
    ), "the release-please manifest and pyproject.toml disagree on the version"


def test_release_please_targets_this_project() -> None:
    config = json.loads(_read(".release-please-config.json"))
    package = config["packages"]["."]
    assert package["package-name"] == "scraping-bot"
    assert package["release-type"] == "python"
    assert (REPO_ROOT / package["changelog-path"]).exists()


def test_changelog_sections_cover_every_commit_type_this_repo_uses() -> None:
    config = json.loads(_read(".release-please-config.json"))
    mapped = {section["type"] for section in config["changelog-sections"]}
    missing = REQUIRED_CHANGELOG_TYPES - mapped
    assert not missing, f"changelog-sections has no section for {sorted(missing)}"


def test_contributing_documents_the_same_commit_types() -> None:
    contributing = _read("CONTRIBUTING.md")
    table = contributing.split("| Type | Section in the changelog", 1)[1]
    documented = set(re.findall(r"^\| `([a-z()]+)` \|", table, re.MULTILINE))
    assert documented == REQUIRED_CHANGELOG_TYPES, (
        f"CONTRIBUTING.md documents {sorted(documented)} but the release config covers "
        f"{sorted(REQUIRED_CHANGELOG_TYPES)}"
    )
