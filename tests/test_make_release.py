import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "make-release.py"
SPEC = importlib.util.spec_from_file_location("make_release", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
make_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(make_release)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/pskraemer11/opencode-go-proxy",
        "https://github.com/pskraemer11/opencode-go-proxy.git",
        "git@github.com:pskraemer11/opencode-go-proxy.git",
        "ssh://git@github.com/pskraemer11/opencode-go-proxy.git",
    ],
)
def test_normalize_github_repository_url(url):
    assert (
        make_release.normalize_github_repository_url(url)
        == "github.com/pskraemer11/opencode-go-proxy"
    )


def test_normalize_github_repository_url_rejects_non_repository_urls():
    with pytest.raises(SystemExit, match="GitHub repository URL"):
        make_release.normalize_github_repository_url(
            "https://github.com/pskraemer11/opencode-go-proxy/tree/main"
        )


def test_release_remote_must_match_project_repository(monkeypatch):
    monkeypatch.setattr(
        make_release,
        "run_git",
        lambda arguments: "https://github.com/kartikkabadi/opencode-go-proxy.git",
    )

    with pytest.raises(SystemExit, match="does not match the project repository"):
        make_release.validate_release_remote(
            "origin", "https://github.com/pskraemer11/opencode-go-proxy"
        )


def test_release_remote_accepts_matching_push_url(monkeypatch):
    commands = []
    monkeypatch.setattr(
        make_release,
        "run_git",
        lambda arguments: commands.append(arguments)
        or "ssh://git@github.com/pskraemer11/opencode-go-proxy.git",
    )

    assert make_release.validate_release_remote(
        "fork", "https://github.com/pskraemer11/opencode-go-proxy"
    ) == "github.com/pskraemer11/opencode-go-proxy"
    assert commands == [["remote", "get-url", "--push", "--all", "fork"]]


def test_release_remote_rejects_any_mismatched_push_url(monkeypatch):
    monkeypatch.setattr(
        make_release,
        "run_git",
        lambda arguments: "\n".join(
            [
                "https://github.com/pskraemer11/opencode-go-proxy.git",
                "https://github.com/kartikkabadi/opencode-go-proxy.git",
            ]
        ),
    )

    with pytest.raises(SystemExit, match="does not match the project repository"):
        make_release.validate_release_remote(
            "fork", "https://github.com/pskraemer11/opencode-go-proxy"
        )


def test_release_anchor_uses_project_repository():
    assert make_release.release_anchor(
        "0.4.11", "https://github.com/pskraemer11/opencode-go-proxy"
    ) == "[0.4.11]: https://github.com/pskraemer11/opencode-go-proxy/releases/tag/v0.4.11"


def test_project_repository_url_is_the_fork():
    assert make_release.normalize_github_repository_url(
        make_release.project_repository_url()
    ) == "github.com/pskraemer11/opencode-go-proxy"


def test_write_changelog_inserts_release_under_unreleased_heading(tmp_path, monkeypatch):
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(
        "# Changelog\n\n## Unreleased\n\n### Added\n\n- pending change\n\n"
        "## [0.4.10] - 2026-08-14\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(make_release, "CHANGELOG_PATH", changelog_path)

    make_release.write_changelog(
        "0.4.11",
        "## [0.4.11] - 2026-10-31\n\n### Added\n\n- released change",
        "https://github.com/pskraemer11/opencode-go-proxy",
    )

    updated = changelog_path.read_text(encoding="utf-8")
    assert updated.index("## [Unreleased]") < updated.index("## [0.4.11]")
    assert updated.index("## [0.4.11]") < updated.index("## [0.4.10]")
    assert "[0.4.11]: https://github.com/pskraemer11/opencode-go-proxy/releases/tag/v0.4.11" in updated


def test_release_cli_requires_explicit_remote_for_dry_run():
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "0.4.11", "--dry-run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--remote" in result.stderr
