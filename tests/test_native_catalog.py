"""Native model capture and merged-catalog rendering."""

import json
import os
import shutil
from unittest import mock

from opencode_go_proxy import catalog, native_models
from opencode_go_proxy.meter import state_dir
from support import write_python_executable

NATIVE_FIXTURE = {
    "models": [
        {
            "slug": "gpt-5.6-luna",
            "display_name": "GPT-5.6-Luna",
            "description": "Luna.",
            "default_reasoning_level": "medium",
            "supported_reasoning_levels": [
                {"effort": "low", "description": "fast"},
                {"effort": "medium", "description": "balanced"},
                {"effort": "max", "description": "max"},
            ],
            "multi_agent_version": "v1",
            "context_window": 272000,
            "shell_type": "shell_command",
            "visibility": "list",
        },
        {
            "slug": "gpt-5.6-terra",
            "display_name": "GPT-5.6-Terra",
            "description": "Terra.",
            "default_reasoning_level": "high",
            "supported_reasoning_levels": [
                {"effort": "high", "description": "deep"},
                {"effort": "ultra", "description": "ultra"},
            ],
            "multi_agent_version": "v2",
            "context_window": 272000,
            "shell_type": "shell_command",
            "visibility": "list",
        },
    ]
}


def _write_fake_codex_bin(bin_path, payload=None) -> str:
    """Write a fake codex binary; return the path to invoke (a shim on Windows)."""
    script = (
        "import json, sys\n"
        "if sys.argv[1] == '--version':\n"
        "    print('codex-cli 0.146.0-test')\n"
        "else:\n"
        "    print('" + json.dumps(NATIVE_FIXTURE if payload is None else payload) + "')\n"
    )
    return write_python_executable(bin_path, script)


def _seed_native_capture(models: list[dict] | None = None) -> None:
    state = state_dir()
    os.makedirs(state, exist_ok=True)
    with open(os.path.join(state, native_models.NATIVE_CATALOG_NAME), "w") as handle:
        json.dump(
            {
                "captured_at": "2026-08-13T00:00:00Z",
                "captured_with": "codex-cli 0.146.0-test",
                "models": models if models is not None else NATIVE_FIXTURE["models"],
            },
            handle,
        )


def test_capture_runs_fake_codex_and_writes_snapshot(tmp_path) -> None:
    codex_bin = _write_fake_codex_bin(tmp_path / "codex")
    with mock.patch.dict(os.environ, {native_models.CODEX_BIN_ENV: codex_bin}):
        snapshot = native_models.capture_native_models()
    assert [m["slug"] for m in snapshot["models"]] == ["gpt-5.6-luna", "gpt-5.6-terra"]
    assert snapshot["captured_with"] == "codex-cli 0.146.0-test"
    assert snapshot["captured_at"]

    with open(native_models.native_models_path(), encoding="utf-8") as fh:
        saved = json.load(fh)
    luna = saved["models"][0]
    assert luna["slug"] == "gpt-5.6-luna"
    assert luna["multi_agent_version"] == "v1"
    assert luna["context_window"] == 272000
    # Only the kept keys are projected into the snapshot.
    assert "shell_type" not in luna
    assert "visibility" not in luna


def test_capture_excludes_prefixed_and_opencode_go_slugs(tmp_path) -> None:
    # codex debug models renders the configured catalog: prefixed
    # opencode-go entries and bare opencode-go slugs (once the merged
    # catalog is configured) must never become "native".
    polluted = {
        "models": [
            {"slug": "gpt-5.6-luna", "display_name": "Luna"},
            {"slug": "opencode-go/deepseek-v4-flash", "display_name": "Prefixed"},
            {"slug": "opencode-go-messages/qwen3.7-max", "display_name": "Prefixed2"},
            {"slug": "deepseek-v4-flash", "display_name": "Bare opencode-go"},
        ]
    }
    codex_bin = _write_fake_codex_bin(tmp_path / "codex", polluted)
    with mock.patch.dict(os.environ, {native_models.CODEX_BIN_ENV: codex_bin}):
        snapshot = native_models.capture_native_models()
    assert {m["slug"] for m in snapshot["models"]} == {"gpt-5.6-luna"}


def test_dry_run_prints_and_does_not_write(tmp_path, capsys) -> None:
    codex_bin = _write_fake_codex_bin(tmp_path / "codex")
    with mock.patch.dict(os.environ, {native_models.CODEX_BIN_ENV: codex_bin}):
        rc = native_models.native_capture_cmd(["--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "2 native models" in out
    assert "max" in out and "ultra" in out
    assert not os.path.exists(native_models.native_models_path())


def test_capture_writes_and_prints_target(tmp_path, capsys) -> None:
    codex_bin = _write_fake_codex_bin(tmp_path / "codex")
    with mock.patch.dict(os.environ, {native_models.CODEX_BIN_ENV: codex_bin}):
        rc = native_models.native_capture_cmd([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "captured 2 native models" in out
    assert os.path.exists(native_models.native_models_path())


def test_missing_bin_errors_cleanly(capsys) -> None:
    with mock.patch.object(native_models, "_codex_bin_candidates", return_value=()):
        with mock.patch.object(shutil, "which", return_value=None):
            with mock.patch.dict(
                os.environ, {native_models.CODEX_BIN_ENV: "/nonexistent/codex-bin"}
            ):
                rc = native_models.native_capture_cmd(["--dry-run"])
    assert rc == 1
    assert "error" in capsys.readouterr().err


def test_invalid_override_falls_back_to_path_codex(tmp_path, monkeypatch) -> None:
    codex_bin = _write_fake_codex_bin(tmp_path / "codex")
    monkeypatch.setenv(native_models.CODEX_BIN_ENV, "/nonexistent/codex-bin")
    monkeypatch.setattr(native_models, "_codex_bin_candidates", lambda: ())
    monkeypatch.setattr(shutil, "which", lambda command: codex_bin if command == "codex" else None)

    snapshot = native_models.capture_native_models(dry_run=True)

    assert [model["slug"] for model in snapshot["models"]] == ["gpt-5.6-luna", "gpt-5.6-terra"]


def test_missing_capture_loads_empty() -> None:
    capture = native_models.load_native_capture()
    assert capture["models"] == []
    assert native_models.native_slugs(capture) == set()
    assert native_models.native_effort_vocabulary(capture) == set()


def test_merged_catalog_contains_native_and_opencode_go_entries() -> None:
    _seed_native_capture()
    merged = catalog.render_merged_catalog()
    slugs = {m["slug"] for m in merged["models"]}
    assert "gpt-5.6-luna" in slugs  # native entry, captured slug
    assert "gpt-5.6-terra" in slugs
    assert "opencode-go/deepseek-v4-flash" in slugs
    luna = next(m for m in merged["models"] if m["slug"] == "gpt-5.6-luna")
    assert luna["multi_agent_version"] == "v1"
    assert luna["context_window"] == 272000
    # Native entries are rendered into the full canonical shape.
    assert luna["model_messages"]
    assert luna["auto_compact_token_limit"] > 0
    assert os.path.exists(catalog.merged_models_path())


def test_merged_catalog_without_capture_is_opencode_go_only() -> None:
    merged = catalog.render_merged_catalog()
    slugs = {m["slug"] for m in merged["models"]}
    assert "gpt-5.6-luna" not in slugs
    assert "opencode-go/deepseek-v4-flash" in slugs


def test_effort_clamp_drops_unknown_efforts() -> None:
    state = state_dir()
    os.makedirs(state, exist_ok=True)
    compact = {
        "fetched_at": "2026-08-13T00:00:00Z",
        "etag": "test",
        "shared_instructions": "",
        "client_version": "0.147.0",
        "models": [
            {
                "slug": "deepseek-v4-flash",
                "display_name": "DeepSeek V4 Flash",
                "context_window": 100000,
                "supported_reasoning_levels": [
                    {"effort": "low", "description": "ok"},
                    {"effort": "medium", "description": "ok"},
                    {"effort": "ultra-super", "description": "not native"},
                ],
            }
        ],
    }
    with open(os.path.join(state, catalog.STATE_COMPACT_NAME), "w") as handle:
        json.dump(compact, handle)
    _seed_native_capture()  # effort vocabulary: low, medium, max, high, ultra
    merged = catalog.render_merged_catalog()
    clamped = next(
        m for m in merged["models"] if m["slug"] == "opencode-go/deepseek-v4-flash"
    )
    efforts = [level["effort"] for level in clamped["supported_reasoning_levels"]]
    assert efforts == ["low", "medium"]


def test_effort_clamp_skipped_without_capture() -> None:
    state = state_dir()
    os.makedirs(state, exist_ok=True)
    compact = {
        "fetched_at": "2026-08-13T00:00:00Z",
        "etag": "test",
        "shared_instructions": "",
        "client_version": "0.147.0",
        "models": [
            {
                "slug": "deepseek-v4-flash",
                "display_name": "DeepSeek V4 Flash",
                "supported_reasoning_levels": [{"effort": "ultra-super", "description": "x"}],
            }
        ],
    }
    with open(os.path.join(state, catalog.STATE_COMPACT_NAME), "w") as handle:
        json.dump(compact, handle)
    merged = catalog.render_merged_catalog()
    entry = next(
        m for m in merged["models"] if m["slug"] == "opencode-go/deepseek-v4-flash"
    )
    assert [level["effort"] for level in entry["supported_reasoning_levels"]] == ["ultra-super"]
