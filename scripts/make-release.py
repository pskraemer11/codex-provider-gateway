"""Cut a release: bump versions, write the changelog section, commit, tag, push.

Usage:
    python scripts/make-release.py <version> --remote <name> [--dry-run]

<version> may be given with or without a leading "v". The script:

1. Asserts a clean working tree on branch main (skipped in --dry-run).
2. Bumps `version` in pyproject.toml and `__version__` in
   src/opencode_go_proxy/__init__.py.
3. Builds a CHANGELOG section from `git log --oneline <last-tag>..HEAD`,
   classified by commit prefix: feat: -> Added, fix: -> Fixed, everything
   else -> Changed. Inserts it under the [Unreleased] heading when one
   exists, else at the top of the file.
4. Updates the "Current version" line in PUBLISHING.md.
5. Appends the [<version>]: release anchor at the CHANGELOG bottom (skipped
   when already present).
6. Commits "release: v<version>", tags v<version>, and pushes main plus the
   tag to the explicitly selected remote. Before any write, every push URL for
   that remote must match the Repository URL in pyproject.toml.

--dry-run prints every planned change and exits 0 without writing anything.
"""

from __future__ import annotations

import argparse
import datetime
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
INIT_PATH = REPO_ROOT / "src" / "opencode_go_proxy" / "__init__.py"
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"
PUBLISHING_PATH = REPO_ROOT / "PUBLISHING.md"
MAIN_BRANCH = "main"

VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
PYPROJECT_VERSION_PATTERN = re.compile(r'^(version = ")([^"]+)(")', re.MULTILINE)
INIT_VERSION_PATTERN = re.compile(r'^(__version__ = ")([^"]+)(")', re.MULTILINE)
PUBLISHING_VERSION_PATTERN = re.compile(r"^(- Current version: `)([^`]+)(`)", re.MULTILINE)
UNRELEASED_HEADING_PATTERN = re.compile(r"^## \[?Unreleased\]?$", re.MULTILINE)
CHANGELOG_TITLE_PATTERN = re.compile(r"^# Changelog$", re.MULTILINE)
FEAT_PREFIX_PATTERN = re.compile(r"^feat(?:\([^)]*\))?:")
FIX_PREFIX_PATTERN = re.compile(r"^fix(?:\([^)]*\))?:")


def run_git(arguments: list[str]) -> str:
    """Run a git command and return its trimmed stdout, or exit on failure."""
    try:
        process = subprocess.run(
            ["git", *arguments], check=False, capture_output=True, text=True
        )
    except OSError as exc:
        raise SystemExit(f"failed to run git {' '.join(arguments)}: {exc}") from exc
    if process.returncode != 0:
        message = process.stderr.strip() or process.stdout.strip()
        raise SystemExit(f"git {' '.join(arguments)} failed ({process.returncode}): {message}")
    return process.stdout.strip()


def normalize_github_repository_url(url: str) -> str:
    """Return a credential-free GitHub repository identity from a remote URL."""
    value = url.strip()
    scp_prefix = "git@github.com:"
    if value.lower().startswith(scp_prefix):
        value = "https://github.com/" + value[len(scp_prefix) :]
    else:
        parsed = urlsplit(value)
        if parsed.scheme.lower() == "ssh":
            if parsed.netloc.lower() != "git@github.com" or parsed.query or parsed.fragment:
                raise SystemExit("expected a GitHub repository URL")
            value = "https://github.com" + parsed.path

    parsed = urlsplit(value)
    if (
        parsed.scheme.lower() != "https"
        or parsed.netloc.lower() != "github.com"
        or parsed.query
        or parsed.fragment
    ):
        raise SystemExit("expected a GitHub repository URL")

    path = parsed.path.strip("/")
    path = path.removesuffix(".git")
    parts = path.split("/")
    if len(parts) != 2 or any(not part or part in {".", ".."} for part in parts):
        raise SystemExit("expected a GitHub repository URL")
    return f"github.com/{parts[0]}/{parts[1]}".casefold()


def project_repository_url() -> str:
    """Read and validate the canonical Repository URL from project metadata."""
    try:
        project = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
        repository_url = project["project"]["urls"]["Repository"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise SystemExit(f"could not read project Repository URL from {PYPROJECT_PATH}") from exc
    if not isinstance(repository_url, str):
        raise SystemExit(f"project Repository URL in {PYPROJECT_PATH} must be a string")
    normalize_github_repository_url(repository_url)
    return repository_url


def validate_release_remote(remote_name: str, repository_url: str) -> str:
    """Require every push URL on the selected remote to match the project repo."""
    expected = normalize_github_repository_url(repository_url)
    try:
        output = run_git(["remote", "get-url", "--push", "--all", remote_name])
    except SystemExit as exc:
        raise SystemExit(f"could not inspect push URL(s) for remote {remote_name!r}") from exc

    push_urls = [line.strip() for line in output.splitlines() if line.strip()]
    if not push_urls:
        raise SystemExit(f"remote {remote_name!r} has no push URL")
    targets = [normalize_github_repository_url(url) for url in push_urls]
    if any(target != expected for target in targets):
        configured = ", ".join(sorted(set(targets)))
        raise SystemExit(
            f"release remote {remote_name!r} does not match the project repository "
            f"({expected}); configured push target(s): {configured}"
        )
    return expected


def release_anchor(version: str, repository_url: str) -> str:
    """Build a release link for the repository declared in project metadata."""
    repository = normalize_github_repository_url(repository_url)
    return f"[{version}]: https://{repository}/releases/tag/v{version}"


def working_tree_is_clean() -> bool:
    return not run_git(["status", "--porcelain"])


def current_branch() -> str:
    return run_git(["branch", "--show-current"])


def last_release_tag() -> str | None:
    """Return the most recent reachable tag, or None when the repo has no tags."""
    try:
        return run_git(["describe", "--tags", "--abbrev=0"])
    except SystemExit:
        return None


def commit_subjects_since(tag: str | None) -> list[str]:
    """Return commit subjects since `tag` (full history when no tag exists)."""
    range_spec = f"{tag}..HEAD" if tag else "HEAD"
    lines = run_git(["log", "--oneline", "--no-decorate", range_spec]).splitlines()
    subjects = []
    for line in lines:
        if " " in line:
            subjects.append(line.split(" ", 1)[1])
    return subjects


def classify_change(subject: str) -> str:
    """Map a conventional-commit subject to its changelog group."""
    if FEAT_PREFIX_PATTERN.match(subject):
        return "Added"
    if FIX_PREFIX_PATTERN.match(subject):
        return "Fixed"
    return "Changed"


def changelog_section(version: str, subjects: list[str]) -> str:
    """Build the markdown section for one release, omitting empty groups."""
    release_date = datetime.datetime.now(tz=datetime.UTC).date().isoformat()
    lines = [f"## [{version}] - {release_date}"]
    for group_name in ("Added", "Fixed", "Changed"):
        entries = [subject for subject in subjects if classify_change(subject) == group_name]
        if entries:
            lines.extend(["", f"### {group_name}", ""])
            lines.extend(f"- {subject}" for subject in entries)
    return "\n".join(lines)


def read_current_version() -> str:
    text = PYPROJECT_PATH.read_text(encoding="utf-8")
    match = PYPROJECT_VERSION_PATTERN.search(text)
    if not match:
        raise SystemExit(f"could not find version in {PYPROJECT_PATH}")
    return match.group(2)


def print_version_bump_plan(version: str) -> None:
    """Print the version-bump plan; exits when the target equals the current version."""
    current = read_current_version()
    if version == current:
        raise SystemExit(f"{version} is already the current version; nothing to release")
    print(f"version: {current} -> {version}")
    print(f"{PYPROJECT_PATH.name}: version = {current!r} -> {version!r}")
    print(f"{INIT_PATH.name}: __version__ = {current!r} -> {version!r}")
    print(f"{PUBLISHING_PATH.name}: Current version: {current!r} -> {version!r}")


def write_version_bumps(version: str) -> None:
    """Apply the version bump to pyproject.toml, __init__.py, and PUBLISHING.md."""
    def replace(match: re.Match[str]) -> str:
        return match.group(1) + version + match.group(3)

    for path, pattern in (
        (PYPROJECT_PATH, PYPROJECT_VERSION_PATTERN),
        (INIT_PATH, INIT_VERSION_PATTERN),
        (PUBLISHING_PATH, PUBLISHING_VERSION_PATTERN),
    ):
        text = path.read_text(encoding="utf-8")
        updated, count = pattern.subn(replace, text, count=1)
        if count != 1:
            raise SystemExit(f"could not find version line in {path}")
        path.write_text(updated, encoding="utf-8")
        print(f"bumped {path.name} to {version}")


def print_changelog_plan(version: str, section: str, repository_url: str) -> None:
    """Print where the changelog section and anchor would land."""
    changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    if UNRELEASED_HEADING_PATTERN.search(changelog):
        print(f"{CHANGELOG_PATH.name}: insert new section under [Unreleased]")
    else:
        print(f"{CHANGELOG_PATH.name}: insert new section at top")
    print(section)
    anchor = release_anchor(version, repository_url)
    if release_anchor_exists(changelog, version):
        print(f"{CHANGELOG_PATH.name}: anchor [{version}]: already present, skipped")
    else:
        print(f"{CHANGELOG_PATH.name}: append {anchor}")


def release_anchor_exists(changelog: str, version: str) -> bool:
    return re.search(rf"^\[{re.escape(version)}\]:", changelog, re.MULTILINE) is not None


def write_changelog(version: str, section: str, repository_url: str) -> None:
    """Insert the release section and append its anchor, then write the file."""
    changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    if UNRELEASED_HEADING_PATTERN.search(changelog):
        changelog = UNRELEASED_HEADING_PATTERN.sub(
            f"## [Unreleased]\n\n{section}", changelog, count=1
        )
    else:
        changelog = CHANGELOG_TITLE_PATTERN.sub(
            f"# Changelog\n\n{section}", changelog, count=1
        )
    if not release_anchor_exists(changelog, version):
        anchor = release_anchor(version, repository_url)
        changelog = changelog.rstrip("\n") + "\n\n" + anchor + "\n"
    CHANGELOG_PATH.write_text(changelog, encoding="utf-8")
    print(f"updated {CHANGELOG_PATH.name} for {version}")


def main(arguments: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Cut a release: bump versions, changelog, commit, tag, push."
    )
    parser.add_argument("version", help="target version, e.g. 0.4.9 or v0.4.9")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the plan without writing anything"
    )
    parser.add_argument(
        "--remote",
        required=True,
        help="Git remote whose push URL(s) must match project.urls.Repository",
    )
    args = parser.parse_args(arguments)

    version = args.version.removeprefix("v")
    if not VERSION_PATTERN.fullmatch(version):
        parser.error(f"invalid version {args.version!r}; expected X.Y.Z (leading v optional)")

    dry_run = args.dry_run
    repository_url = project_repository_url()
    release_target = validate_release_remote(args.remote, repository_url)
    print(f"release target: {args.remote} ({release_target})")
    if not dry_run:
        if not working_tree_is_clean():
            raise SystemExit("working tree is not clean; commit or stash before releasing")
        if current_branch() != MAIN_BRANCH:
            raise SystemExit(f"not on {MAIN_BRANCH}; releases happen from {MAIN_BRANCH}")

    print_version_bump_plan(version)
    tag = last_release_tag()
    subjects = commit_subjects_since(tag)
    section = changelog_section(version, subjects)
    print_changelog_plan(version, section, repository_url)

    if dry_run:
        print("git commit: release: v" + version)
        print(f"git tag: v{version}")
        print(f"git push: {args.remote} {MAIN_BRANCH}, {args.remote} v{version}")
        print("DRY RUN: no changes were written")
        return

    write_version_bumps(version)
    write_changelog(version, section, repository_url)

    release_files = [
        "pyproject.toml",
        "src/opencode_go_proxy/__init__.py",
        "CHANGELOG.md",
        "PUBLISHING.md",
    ]
    run_git(["add", *release_files])
    run_git(["commit", "-m", f"release: v{version}"])
    run_git(["tag", "-a", f"v{version}", "-m", f"release: v{version}"])
    run_git(["push", args.remote, MAIN_BRANCH])
    run_git(["push", args.remote, f"v{version}"])
    print(f"released v{version}: committed, tagged, and pushed to {args.remote}")


if __name__ == "__main__":
    main(sys.argv[1:])
