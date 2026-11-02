import json
import os
from pathlib import Path
from unittest import mock

from support import POSIX_PERMISSIONS

from opencode_go_proxy import updates


def test_update_cache_creates_parent_and_uses_private_permissions(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENCODE_GO_PROXY_STATE_DIR", str(tmp_path / "fresh" / "state"))
    payload = {"latest": "1.2.3"}
    updates._write_cache(payload)
    path = Path(updates._cache_path())
    assert json.loads(path.read_text()) == payload
    if POSIX_PERMISSIONS:
        assert path.stat().st_mode & 0o777 == 0o600
    path.chmod(0o644)
    updates._write_cache({"latest": "1.2.4"})
    if POSIX_PERMISSIONS:
        assert path.stat().st_mode & 0o777 == 0o600


def test_failed_replace_preserves_previous_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_GO_PROXY_STATE_DIR", str(tmp_path))
    path = Path(updates._cache_path())
    path.write_text('{"latest":"old"}')
    with mock.patch.object(os, "replace", side_effect=OSError("disk failure")):
        updates._write_cache({"latest": "new"})
    assert json.loads(path.read_text()) == {"latest": "old"}
    assert not list(tmp_path.glob(".update-check-*"))
