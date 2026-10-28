"""Coverage for scripts/make-compact-catalog.py, especially its shrink guard.

The script has a hyphen in its name, so it cannot be imported normally, and it
derives its paths from __file__. It is therefore loaded by path and driven with
explicit paths, which keeps the guard testable without touching contrib/.
"""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "make-compact-catalog.py"
)


def load_generator() -> ModuleType:
    """Load the hyphenated script as a module without registering it."""
    spec = importlib.util.spec_from_file_location("make_compact_catalog", SCRIPT_PATH)
    assert spec is not None
    loader = spec.loader
    assert loader is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def write_full_catalog(path: Path, count: int) -> None:
    """Write a minimal full-shape catalog holding `count` models."""
    models = [
        {
            "slug": f"model-{index}",
            "base_instructions": "shared instructions",
            "model_messages": {"x": "y"},
            "auto_compact_token_limit": 1000,
            "context_window": 200000,
        }
        for index in range(count)
    ]
    path.write_text(
        json.dumps(
            {
                "fetched_at": "2026-10-28T00:00:00Z",
                "etag": 'W/"test"',
                "models": models,
            }
        ),
        encoding="utf-8",
    )


def write_compact_catalog(path: Path, count: int) -> None:
    """Write a compact catalog; only the model count matters for the guard."""
    path.write_text(
        json.dumps({"models": [{"slug": f"seed-{index}"} for index in range(count)]}),
        encoding="utf-8",
    )


def test_generator_refuses_to_shrink_the_compact_catalog(tmp_path: Path) -> None:
    generator = load_generator()
    full = tmp_path / "full.json"
    compact = tmp_path / "compact.json"
    write_full_catalog(full, 3)
    write_compact_catalog(compact, 5)
    before = compact.read_bytes()

    with pytest.raises(SystemExit) as excinfo:
        generator.main(full_path=full, compact_path=compact)

    message = str(excinfo.value)
    assert "refusing to shrink" in message
    assert "holds 5 models" in message
    assert "only produced 3" in message
    assert compact.read_bytes() == before


def test_generator_writes_when_the_compact_catalog_grows(tmp_path: Path) -> None:
    generator = load_generator()
    full = tmp_path / "full.json"
    compact = tmp_path / "compact.json"
    write_full_catalog(full, 5)
    write_compact_catalog(compact, 2)

    generator.main(full_path=full, compact_path=compact)

    written = json.loads(compact.read_text(encoding="utf-8"))
    assert len(written["models"]) == 5
    assert written["shared_instructions"] == "shared instructions"
    assert "base_instructions" not in written["models"][0]


def test_generator_writes_when_no_compact_catalog_exists(tmp_path: Path) -> None:
    generator = load_generator()
    full = tmp_path / "full.json"
    compact = tmp_path / "compact.json"
    write_full_catalog(full, 2)

    generator.main(full_path=full, compact_path=compact)

    written = json.loads(compact.read_text(encoding="utf-8"))
    assert len(written["models"]) == 2


def test_generator_rejects_a_full_catalog_without_models(tmp_path: Path) -> None:
    generator = load_generator()
    full = tmp_path / "full.json"
    compact = tmp_path / "compact.json"
    full.write_text(json.dumps({"models": []}), encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        generator.main(full_path=full, compact_path=compact)

    assert "contains no models" in str(excinfo.value)
    assert not compact.exists()
