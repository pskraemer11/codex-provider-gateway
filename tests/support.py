"""Cross-platform helpers shared by the test suite.

Two platform gaps the suite used to assume away:

* POSIX executes a shebang script directly; Windows cannot. Fake ``codex``
  binaries are therefore written as a ``.py`` file plus a ``.cmd`` shim that
  invokes this interpreter, and callers point at the returned path.
* ``st_mode`` permission bits are a POSIX concept. NTFS reports synthesized
  modes, so 0600 assertions only mean something where POSIX permissions
  exist.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

POSIX_PERMISSIONS = os.name == "posix"

# Environment variables that point the proxy at per-test fixtures. Scrubbing
# the environment must keep them, or mid-test lookups silently fall back to
# the developer's real ~/.codex state.
ISOLATION_VARS = (
    "CODEX_MODEL_CATALOG",
    "OPENCODE_GO_PROXY_CONFIG_PATH",
    "OPENCODE_GO_PROXY_STATE_DIR",
)


def isolated_env(**overrides: str) -> dict[str, str]:
    """A scrubbed environment that keeps the suite's isolation knobs."""
    env = {key: os.environ[key] for key in ISOLATION_VARS if key in os.environ}
    env.update(overrides)
    return env


def write_python_executable(path: Path, source: str) -> str:
    """Write Python *source* as an executable and return the path to invoke.

    POSIX: *path* receives the source (with a shebang supplied when the
    source has none) and the executable bit. Windows: the source lands next
    to *path* as ``<name>.py`` and ``<name>.cmd`` forwards every argument to
    the interpreter running the tests, because CreateProcess cannot launch a
    shebang script.
    """
    body = source if source.startswith("#!") else "#!/usr/bin/env python3\n" + source
    path.parent.mkdir(parents=True, exist_ok=True)
    if POSIX_PERMISSIONS:
        path.write_text(body)
        path.chmod(0o755)
        return str(path)
    script = path.with_name(path.name + ".py")
    script.write_text(body)
    shim = path.with_name(path.name + ".cmd")
    shim.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n')
    return str(shim)
