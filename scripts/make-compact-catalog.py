"""Build the compact model catalog from the full-shape Codex catalog.

The full catalog duplicates per-model instruction text; the compact form
keeps it once in "shared_instructions" so catalog updates stay small. Read
contrib/opencode-go-catalog.json, drop the per-model instruction fields, and
write contrib/opencode-go-models.json.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FULL_PATH = REPO_ROOT / "contrib" / "opencode-go-catalog.json"
COMPACT_PATH = REPO_ROOT / "contrib" / "opencode-go-models.json"
CLIENT_VERSION = "0.147.0"

# auto_compact_token_limit is derived from context_window at render time, so
# the compact form never stores it (the same rule as _default_model_record).
DROPPED_KEYS = frozenset({"base_instructions", "model_messages", "auto_compact_token_limit"})


def compact_model(full_model: dict) -> dict:
    """Return one compact model record without per-model instruction fields."""
    record = {key: value for key, value in full_model.items() if key not in DROPPED_KEYS}
    record["effective_context_window_percent"] = 95
    record["apply_patch_tool_type"] = "freeform"
    record["shell_type"] = "shell_command"
    record["visibility"] = "list"
    record["supported_in_api"] = True
    record["additional_speed_tiers"] = []
    record["service_tiers"] = []
    record["availability_nux"] = None
    record["upgrade"] = None
    record["support_verbosity"] = False
    record["default_verbosity"] = "low"
    record["experimental_supported_tools"] = []
    record["use_responses_lite"] = False
    return record


def existing_model_count() -> int | None:
    """Return how many models the compact catalog holds, or None if absent."""
    if not COMPACT_PATH.exists():
        return None
    with open(COMPACT_PATH, encoding="utf-8") as f:
        existing = json.load(f)
    return len(existing.get("models", []))


def main() -> None:
    with open(FULL_PATH, encoding="utf-8") as f:
        full = json.load(f)
    models = full.get("models")
    if not models:
        raise SystemExit(f"{FULL_PATH} contains no models")
    shared_instructions = models[0]["base_instructions"]

    compact = {
        "fetched_at": full["fetched_at"],
        "etag": full["etag"],
        "shared_instructions": shared_instructions,
        "client_version": CLIENT_VERSION,
        "models": [compact_model(model) for model in models],
    }
    held = existing_model_count()
    produced = len(compact["models"])
    if held is not None and held > produced:
        raise SystemExit(
            f"refusing to shrink {COMPACT_PATH.name}: it holds {held} models but "
            f"{FULL_PATH.name} only produced {produced}. Update the full-shape "
            f"catalog first, or delete {COMPACT_PATH.name} on purpose."
        )
    with open(COMPACT_PATH, "w", encoding="utf-8") as f:
        json.dump(compact, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {COMPACT_PATH} ({produced} models, {COMPACT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
