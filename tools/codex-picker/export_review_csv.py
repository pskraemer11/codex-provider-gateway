"""Export the complete price-filtered candidate audit as a human-readable CSV."""

from __future__ import annotations

import argparse
import csv
import json
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from catalog_rules import finite_number

CSV_FIELDS = (
    "audit_generated_at",
    "provider",
    "model_id",
    "input_price_min_usd_per_1m",
    "input_price_max_usd_per_1m",
    "calibrated_score_0_100",
    "score_method",
    "benchmark_source",
    "transport_source",
    "identity_match",
    "selected",
    "selection_reason",
    "input_price_limit_strictly_below_usd_per_1m",
    "score_limit_strictly_above_0_100",
    "price_source",
    "aa_index_values_json",
    "aa_snapshot_index_values_json",
    "openrouter_aa_index_values_json",
)


def _decimal_text(value: Any, *, field: str) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"invalid decimal in {field}") from None
    if not number.is_finite() or number < 0:
        raise ValueError(f"invalid non-negative finite decimal in {field}")
    return format(number, "f")


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _spreadsheet_safe_text(value: str) -> str:
    stripped = value.lstrip(" \t\r\n")
    if value.startswith(("\t", "\r", "\n")) or (stripped and stripped[0] in "=+-@"):
        return f"'{value}"
    return value


def rows_from_audit(payload: dict[str, Any]) -> list[dict[str, str]]:
    candidates = payload.get("evaluated_candidates")
    criteria = payload.get("criteria")
    if not isinstance(candidates, list) or not isinstance(criteria, dict):
        raise ValueError("audit is missing evaluated_candidates or criteria")
    try:
        price_limit = Decimal(str(criteria.get("input_price_usd_per_million_strictly_less_than")))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("audit input-price criterion is invalid") from None
    if not price_limit.is_finite() or price_limit <= 0:
        raise ValueError("audit input-price criterion must be a positive finite decimal")
    score_limit = finite_number(criteria.get("calibrated_score_strictly_greater_than"))
    if score_limit is None or not 0 <= score_limit <= 100:
        raise ValueError("audit score criterion is invalid")

    generated_at = payload.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at:
        raise ValueError("audit generated_at timestamp is missing")

    output: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("audit candidate must be an object")
        provider, model_id = candidate.get("provider"), candidate.get("id")
        if not isinstance(provider, str) or not isinstance(model_id, str):
            raise ValueError("audit candidate is missing provider or model id")
        key = provider, model_id
        if key in seen:
            raise ValueError(f"duplicate audit candidate: {provider}/{model_id}")
        seen.add(key)

        price_min = candidate.get("input_price_min", candidate.get("input_price"))
        price_max = candidate.get("input_price_max", candidate.get("input_price"))
        price_min_text = _decimal_text(price_min, field="input_price_min")
        price_max_text = _decimal_text(price_max, field="input_price_max")
        price_low, price_high = Decimal(price_min_text), Decimal(price_max_text)
        if price_low > price_high or price_high >= price_limit:
            raise ValueError(f"candidate is outside the strict input-price limit: {provider}/{model_id}")

        score = candidate.get("score")
        score_text = "" if score is None else str(score)
        selected = candidate.get("selected")
        if not isinstance(selected, bool):
            raise ValueError(f"candidate selected flag is not boolean: {provider}/{model_id}")
        selection_reason = candidate.get("selection_reason")
        if selected and selection_reason == "user_pinned_free_exception":
            if price_low != 0 or price_high != 0 or score is not None:
                raise ValueError(f"free exception has non-zero price or a fabricated score: {provider}/{model_id}")
        elif selected and (score is None or float(score) <= score_limit):
            raise ValueError(f"selected non-exception does not pass score threshold: {provider}/{model_id}")
        if score is not None and not 0 <= float(score) <= 100:
            raise ValueError(f"calibrated score is outside 0..100: {provider}/{model_id}")

        output.append(
            {
                "audit_generated_at": generated_at,
                "provider": provider,
                "model_id": model_id,
                "input_price_min_usd_per_1m": price_min_text,
                "input_price_max_usd_per_1m": price_max_text,
                "calibrated_score_0_100": score_text,
                "score_method": str(candidate.get("score_method") or "unverified"),
                "benchmark_source": str(candidate.get("benchmark_source") or "unverified"),
                "transport_source": str(candidate.get("transport_source") or "unverified"),
                "identity_match": _json_text(candidate.get("identity_match")),
                "selected": str(selected).lower(),
                "selection_reason": str(selection_reason or ""),
                "input_price_limit_strictly_below_usd_per_1m": str(price_limit),
                "score_limit_strictly_above_0_100": str(score_limit),
                "price_source": str(candidate.get("price_source") or ""),
                "aa_index_values_json": _json_text(candidate.get("aa_index_values")),
                "aa_snapshot_index_values_json": _json_text(candidate.get("aa_snapshot_index_values")),
                "openrouter_aa_index_values_json": _json_text(candidate.get("openrouter_aa_index_values")),
            }
        )
    return output


def export_review_csv(audit_path: Path, output_path: Path, *, overwrite: bool = False) -> int:
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("audit file must contain a JSON object")
    rows = rows_from_audit(payload)
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing review CSV: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="raise")
        writer.writeheader()
        writer.writerows({field: _spreadsheet_safe_text(value) for field, value in row.items()} for row in rows)
    return len(rows)


def main() -> int:
    codex_dir = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    parser = argparse.ArgumentParser(description="Export the Codex picker audit candidates to CSV.")
    parser.add_argument("--audit", type=Path, default=codex_dir / "provider-catalog-audit.json")
    parser.add_argument("--out", type=Path, help="CSV path; defaults to this directory with the audit date")
    parser.add_argument("--overwrite", action="store_true", help="replace an existing CSV explicitly")
    args = parser.parse_args()
    try:
        payload = json.loads(args.audit.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("audit file must contain a JSON object")
        generated_at = payload.get("generated_at")
        if not isinstance(generated_at, str) or len(generated_at) < 10:
            raise ValueError("audit generated_at timestamp is missing")
        output_path = args.out or Path(__file__).with_name(f"provider-selection-review-{generated_at[:10]}.csv")
        count = export_review_csv(args.audit, output_path, overwrite=args.overwrite)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        parser.error(str(error))
    print(f"CSV: {output_path} ({count} Kandidaten; Preise USD/1M Input-Token)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
