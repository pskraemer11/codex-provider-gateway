from __future__ import annotations

import csv
import importlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PICKER_DIR = Path(__file__).resolve().parents[1] / "tools" / "codex-picker"
sys.path.insert(0, str(PICKER_DIR))
EXPORTER_SCRIPT = PICKER_DIR / "export_review_csv.py"
SPEC = importlib.util.spec_from_file_location("export_review_csv", EXPORTER_SCRIPT)
assert SPEC is not None and SPEC.loader is not None
exporter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = exporter
SPEC.loader.exec_module(exporter)
export_review_csv = exporter.export_review_csv
catalog_rules = importlib.import_module("catalog_rules")


def test_csv_exporter_uses_the_shared_price_cap(tmp_path: Path) -> None:
    audit = tmp_path / "audit.json"
    output = tmp_path / "review.csv"
    write_audit(
        audit,
        [
            {
                "provider": "openrouter",
                "id": "example/model",
                "input_price": "0.10",
                "score": None,
                "selected": False,
                "selection_reason": "",
            }
        ],
    )

    assert export_review_csv(audit, output) == 1
    with output.open(encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["input_price_limit_strictly_below_usd_per_1m"] == str(catalog_rules.INPUT_PRICE_LIMIT)


def write_audit(
    path: Path,
    candidates: list[dict],
    *,
    price_limit: str = str(catalog_rules.INPUT_PRICE_LIMIT),
    score_limit: float = 70.0,
) -> None:
    payload = {
        "generated_at": "2026-10-31T21:43:20Z",
        "criteria": {
            "input_price_usd_per_million_strictly_less_than": price_limit,
            "calibrated_score_strictly_greater_than": score_limit,
        },
        "evaluated_candidates": candidates,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_csv_preserves_score_price_provenance_and_blank_unverified_score(tmp_path: Path) -> None:
    audit = tmp_path / "audit.json"
    output = tmp_path / "review.csv"
    write_audit(
        audit,
        [
            {
                "provider": "openrouter",
                "id": "example/qualified",
                "input_price": "0.10",
                "score": 80.125,
                "score_method": "AA Intelligence Index",
                "benchmark_source": "artificial-analysis",
                "transport_source": "AA API",
                "identity_match": "exact",
                "selected": True,
                "selection_reason": "price_and_calibrated_score",
                "price_source": "openrouter-models-api",
                "aa_index_values": {"intelligence": 42.5},
            },
            {
                "provider": "zen",
                "id": "zen/example-unverified",
                "input_price_min": "0",
                "input_price_max": "0",
                "score": None,
                "score_method": "unverified",
                "benchmark_source": "unverified",
                "transport_source": "unverified",
                "selected": False,
                "selection_reason": "",
                "price_source": "opencode-console-docs",
            },
        ],
    )

    assert export_review_csv(audit, output) == 2
    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows[0]["input_price_min_usd_per_1m"] == "0.10"
    assert rows[0]["input_price_max_usd_per_1m"] == "0.10"
    assert rows[0]["calibrated_score_0_100"] == "80.125"
    assert json.loads(rows[0]["aa_index_values_json"]) == {"intelligence": 42.5}
    assert rows[1]["calibrated_score_0_100"] == ""
    assert rows[1]["selection_reason"] == ""
    assert rows[1]["benchmark_source"] == "unverified"


def test_csv_uses_configured_audit_price_and_score_limits(tmp_path: Path) -> None:
    audit = tmp_path / "custom-audit.json"
    output = tmp_path / "custom-review.csv"
    write_audit(
        audit,
        [
            {
                "provider": "zen",
                "id": "example/custom-qualified",
                "input_price": "0.149",
                "score": 74.5,
                "selected": True,
                "selection_reason": "price_and_calibrated_score",
            }
        ],
        price_limit="0.15",
        score_limit=74.0,
    )

    assert export_review_csv(audit, output) == 1
    with output.open(encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))

    assert row["input_price_limit_strictly_below_usd_per_1m"] == "0.15"
    assert row["score_limit_strictly_above_0_100"] == "74.0"


def test_csv_rejects_duplicates_and_invalid_selected_scores(tmp_path: Path) -> None:
    audit = tmp_path / "audit.json"
    duplicate = {
        "provider": "zen",
        "id": "example/model",
        "input_price_min": "0.10",
        "input_price_max": "0.10",
        "score": 71,
        "selected": True,
        "selection_reason": "price_and_calibrated_score",
    }
    write_audit(audit, [duplicate, duplicate])

    with pytest.raises(ValueError, match="duplicate audit candidate"):
        export_review_csv(audit, tmp_path / "duplicate.csv")

    write_audit(audit, [{**duplicate, "score": 70}])
    with pytest.raises(ValueError, match="does not pass score threshold"):
        export_review_csv(audit, tmp_path / "bad-score.csv")


def test_csv_refuses_to_overwrite_without_explicit_flag(tmp_path: Path) -> None:
    audit = tmp_path / "audit.json"
    output = tmp_path / "review.csv"
    write_audit(audit, [])
    output.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        export_review_csv(audit, output)

    assert output.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("model_id", ["=1+1", "+SUM(A1:A2)", "-1+1", "@SUM(A1:A2)", " \t=1+1"])
def test_csv_escapes_spreadsheet_formula_like_fields(tmp_path: Path, model_id: str) -> None:
    audit = tmp_path / "audit.json"
    output = tmp_path / "review.csv"
    write_audit(
        audit,
        [
            {
                "provider": "openrouter",
                "id": model_id,
                "input_price": "0.10",
                "score": None,
                "selected": False,
                "selection_reason": "",
            }
        ],
    )

    assert export_review_csv(audit, output) == 1
    with output.open(encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))

    assert row["model_id"] == f"'{model_id}"


def test_csv_accepts_the_opt_in_unverified_free_exception(tmp_path: Path) -> None:
    audit = tmp_path / "audit.json"
    output = tmp_path / "review.csv"
    write_audit(
        audit,
        [
            {
                "provider": "openrouter",
                "id": "cohere/north-mini-code:free",
                "input_price": "0",
                "score": None,
                "score_method": "unverified",
                "benchmark_source": "unverified",
                "transport_source": "unverified",
                "selected": True,
                "selection_reason": "unverified_free_exception",
                "price_source": "openrouter-models-api",
            }
        ],
    )

    assert export_review_csv(audit, output) == 1
    with output.open(encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))

    assert row["selection_reason"] == "unverified_free_exception"
    assert row["calibrated_score_0_100"] == ""
    assert row["input_price_min_usd_per_1m"] == "0"


def test_csv_rejects_an_unverified_free_exception_with_a_price(tmp_path: Path) -> None:
    audit = tmp_path / "audit.json"
    output = tmp_path / "review.csv"
    write_audit(
        audit,
        [
            {
                "provider": "openrouter",
                "id": "cohere/north-mini-code:free",
                "input_price": "0.01",
                "score": None,
                "selected": True,
                "selection_reason": "unverified_free_exception",
            }
        ],
    )

    with pytest.raises(ValueError, match="unverified free exception"):
        export_review_csv(audit, output)
