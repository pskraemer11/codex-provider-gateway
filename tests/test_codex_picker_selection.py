from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "codex-picker" / "catalog_rules.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("catalog_rules", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
catalog_rules = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = catalog_rules
SPEC.loader.exec_module(catalog_rules)
BUILDER_SCRIPT = SCRIPT.with_name("build_provider_catalogs.py")
BUILDER_SPEC = importlib.util.spec_from_file_location("build_provider_catalogs", BUILDER_SCRIPT)
assert BUILDER_SPEC is not None and BUILDER_SPEC.loader is not None
builder = importlib.util.module_from_spec(BUILDER_SPEC)
sys.modules[BUILDER_SPEC.name] = builder
BUILDER_SPEC.loader.exec_module(builder)


def test_calibration_maps_observed_worst_and_best_to_zero_and_hundred() -> None:
    population = (10, 20, 30, 40, 50)
    assert catalog_rules.calibrate_score(10, population) == 0
    assert catalog_rules.calibrate_score(30, population) == 50
    assert catalog_rules.calibrate_score(50, population) == 100


def test_calibration_equal_values_use_midpoint() -> None:
    assert catalog_rules.calibrate_score(42, (42, 42)) == 50
    assert catalog_rules.calibrate_score(42, (42,)) is None


def test_intelligence_index_takes_precedence_over_other_indices() -> None:
    score, method = catalog_rules.score_candidate(
        primary={"intelligence": 70, "coding": 10, "agentic": 10},
        fallback={"intelligence": 100, "coding": 50, "agentic": 50},
        ranges={"intelligence": tuple(range(0, 101, 10)), "coding": (0, 50), "agentic": (0, 50)},
    )
    assert score == 70
    assert method == "AA Intelligence Index"


def test_missing_intelligence_does_not_use_coding_agentic_composite() -> None:
    score, method = catalog_rules.score_candidate(
        primary={"coding": 40, "agentic": 80},
        fallback={},
        ranges={"coding": (0, 20, 40, 60, 80, 100), "agentic": (0, 20, 40, 60, 80, 100)},
    )
    assert score is None
    assert method == "unverified"


def test_openrouter_aa_transport_does_not_fill_missing_intelligence() -> None:
    score, method = catalog_rules.score_candidate(
        primary={"coding": 80},
        fallback={"agentic": 50},
        ranges={"coding": (0, 20, 40, 60, 80, 100), "agentic": (0, 25, 50, 75, 100)},
    )
    assert score is None
    assert method == "unverified"


def test_coding_agentic_pair_does_not_precede_missing_intelligence() -> None:
    score, method = catalog_rules.score_candidate(
        primary={"coding": 40, "agentic": 80},
        fallback={"intelligence": 100},
        ranges={
            "intelligence": tuple(range(0, 101, 10)),
            "coding": tuple(range(0, 101, 10)),
            "agentic": tuple(range(0, 101, 10)),
        },
    )

    assert score is None
    assert method == "unverified"


def test_snapshot_coding_agentic_value_does_not_create_score() -> None:
    score, method = catalog_rules.score_candidate(
        primary={"coding": 80},
        fallback={"intelligence": 100, "agentic": 20},
        ranges={"coding": (0, 20, 40, 60, 80, 100), "agentic": (0, 20, 40, 60, 80, 100)},
        snapshot={"coding": 10, "agentic": 60},
    )

    assert score is None
    assert method == "unverified"


def test_snapshot_intelligence_is_used_when_live_intelligence_population_is_absent() -> None:
    score, method = catalog_rules.score_candidate(
        primary={},
        fallback={"intelligence": 100},
        ranges={"intelligence": (10, 30, 50)},
        snapshot={"intelligence": 30},
    )

    assert score == 50
    assert method == "AA Intelligence Index (dated AA snapshot fallback)"


def test_openrouter_coding_is_not_a_score_fallback() -> None:
    score, method = catalog_rules.score_candidate(
        primary={},
        fallback={"coding": 80},
        ranges={"coding": tuple(range(0, 101, 10)), "agentic": tuple(range(0, 101, 10))},
    )
    assert score is None
    assert method == "unverified"


def test_no_score_when_all_approved_sources_are_missing() -> None:
    score, method = catalog_rules.score_candidate(
        primary={}, fallback={"agentic": 80}, ranges={"agentic": tuple(range(0, 101, 10))}
    )
    assert score is None
    assert method == "unverified"


def test_openrouter_intelligence_alone_is_not_an_approved_score_fallback() -> None:
    score, method = catalog_rules.score_candidate(
        primary={},
        fallback={"intelligence": 100},
        ranges={"intelligence": tuple(range(0, 101, 10))},
    )

    assert score is None
    assert method == "unverified"


def test_filter_uses_strict_price_and_score_boundaries() -> None:
    assert catalog_rules.qualifies_model("0.249999", 70.001)
    assert catalog_rules.qualifies_model("0.249999", 99)
    assert not catalog_rules.qualifies_model("0.25", 99)
    assert not catalog_rules.qualifies_model("0.10", 70)
    assert not catalog_rules.qualifies_model(None, 90)
    assert not catalog_rules.qualifies_model("0.10", None)
    assert not catalog_rules.qualifies_model("0.022", 65.81818181818182)


def test_filter_uses_cli_configurable_strict_price_and_score_boundaries() -> None:
    assert catalog_rules.qualifies_model(
        "0.149", 75, input_price_limit=Decimal("0.15"), min_calibrated_score=74
    )
    assert not catalog_rules.qualifies_model(
        "0.15", 75, input_price_limit=Decimal("0.15"), min_calibrated_score=74
    )
    assert not catalog_rules.qualifies_model(
        "0.149", 74, input_price_limit=Decimal("0.15"), min_calibrated_score=74
    )


def test_picker_price_cap_is_shared_and_reported() -> None:
    assert catalog_rules.INPUT_PRICE_LIMIT == Decimal("0.25")
    assert builder.INPUT_PRICE_LIMIT is catalog_rules.INPUT_PRICE_LIMIT
    assert builder.selection_criteria_text() == (
        "Kriterien: Input < $0.25/M Token und kalibrierter AA-Intelligence-Score > 70/100"
    )
    assert builder.selection_criteria_text(Decimal("0.15"), 74) == (
        "Kriterien: Input < $0.15/M Token und kalibrierter AA-Intelligence-Score > 74/100"
    )


def test_explicit_free_route_pins_require_verified_zero_input_price() -> None:
    openrouter_pins = ("cohere/north-mini-code:free", "openrouter/free")
    zen_pins = ("glm-5.3-flash-free", "deepseek-v4.1-flash-free", "mimo-v2.6-flash-free")

    for identifier in openrouter_pins:
        assert builder._selection_reason("openrouter", identifier, Decimal("0"), None) == ("user_pinned_free_exception")
    for identifier in zen_pins:
        assert builder._selection_reason("zen", identifier, Decimal("0"), None) == "user_pinned_free_exception"

    assert builder._selection_reason("openrouter", openrouter_pins[0], Decimal("0.001"), None) is None
    assert builder._selection_reason("openrouter", "recursive/flint-v1.0:free", Decimal("0"), None) is None
    assert builder._selection_reason("go", "deepseek-v4.1-flash-free", Decimal("0"), None) is None


def test_catalog_sort_prefers_selected_deepseek_1017_and_ranks_unverified_free_last() -> None:
    preferred = {"id": "deepseek/deepseek-v4.1-flash-1017", "score": 70.0, "price": "0.022"}
    scored = {"id": "moonshotai/kimi-k3", "score": 90.0, "price": "0.239"}
    unverified_free = {"id": "cohere/north-mini-code:free", "score": None, "price": "0"}

    assert builder._candidate_sort_key("openrouter", preferred) < builder._candidate_sort_key("openrouter", scored)
    assert builder._candidate_sort_key("openrouter", scored) < builder._candidate_sort_key(
        "openrouter", unverified_free
    )


def test_min_max_calibration_maps_values_between_population_bounds() -> None:
    assert catalog_rules.calibrate_score(20, (0, 20, 20, 40, 60, 80, 100)) == 20


def test_min_max_calibration_clamps_outside_population_bounds() -> None:
    population = (0, 0, 20, 40, 60, 80, 100, 100)

    assert catalog_rules.calibrate_score(0, population) == 0
    assert catalog_rules.calibrate_score(100, population) == 100
    assert catalog_rules.calibrate_score(-1, population) == 0
    assert catalog_rules.calibrate_score(101, population) == 100


def test_cross_provider_identity_requires_one_exact_canonical_model_component() -> None:
    assert (
        catalog_rules.unique_model_component("zen/gpt-6.1-sol", ["openai/gpt-6.1-sol", "google/gemini-3.8-flash"])
        == "openai/gpt-6.1-sol"
    )
    assert (
        catalog_rules.unique_model_component("zen/model-v4.1", ["provider/model-v4-1", "provider/model-v4.1"]) is None
    )
    assert catalog_rules.unique_model_component("zen/model-v5", ["provider/model-v5.1"]) is None


def test_artificial_analysis_endpoint_is_the_supported_post_migration_path() -> None:
    assert builder.AA_URL == "https://artificialanalysis.ai/api/v2/language/models/free"
    assert "/api/v2/data/" not in builder.AA_URL


def test_direct_go_catalog_keeps_provider_prefix_while_zen_uses_bare_id() -> None:
    assert builder._direct_provider_identifier("go", "deepseek-v4.1-flash") == "opencode-go/deepseek-v4.1-flash"
    assert builder._direct_provider_identifier("zen", "gpt-6-luna") == "gpt-6-luna"


def test_artificial_analysis_v2_free_response_is_paginated_and_validated(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_get_json(url, headers=None):
        from urllib.parse import parse_qs, urlparse

        assert headers is not None
        page = int(parse_qs(urlparse(url).query)["page"][0])
        calls.append((url, headers))
        return {
            "tier": "free",
            "intelligence_index_version": 5,
            "pagination": {
                "page": page,
                "page_size": 200,
                "total_pages": 2,
                "has_more": page == 1,
            },
            "data": [
                {
                    "id": f"aa-id-{page}",
                    "slug": f"model-{page}",
                    "evaluations": {
                        "artificial_analysis_intelligence_index": 40 + page,
                        "artificial_analysis_coding_index": None,
                        "artificial_analysis_agentic_index": None,
                    },
                }
            ],
        }, f"hash-{page}"

    monkeypatch.setattr(builder, "_get_json", fake_get_json)
    rows, provenance = builder.fetch_aa_models("test-key")

    assert [row["slug"] for row in rows] == ["model-1", "model-2"]
    assert all(url.startswith(builder.AA_URL + "?page=") for url, _headers in calls)
    assert all(headers == {"x-api-key": "test-key"} for _url, headers in calls)
    assert provenance["page_count"] == 2
    assert provenance["row_count"] == 2
    assert provenance["intelligence_index_version"] == 5


def test_calibration_populations_use_only_live_intelligence() -> None:
    aa_rows = [
        {"evaluations": {"artificial_analysis_intelligence_index": 20}},
        {"evaluations": {"artificial_analysis_intelligence_index": 80}},
    ]
    or_metrics = {
        "example/model-a": {"coding": 10, "agentic": 30},
        "example/model-b": {"coding": 90, "agentic": 70},
    }

    populations, sources = builder.calibration_populations(aa_rows, [], or_metrics)

    assert populations == {"intelligence": (20.0, 80.0)}
    assert sources == {"intelligence": "artificial-analysis-data-api"}


def test_calibration_population_can_be_limited_to_price_eligible_candidates() -> None:
    aa_rows = [
        {"slug": "example/expensive", "evaluations": {"artificial_analysis_intelligence_index": 100}},
        {"slug": "example/model-a", "evaluations": {"artificial_analysis_intelligence_index": 20}},
        {"slug": "example/model-b", "evaluations": {"artificial_analysis_intelligence_index": 80}},
    ]

    populations, sources = builder.calibration_populations(
        aa_rows,
        [],
        eligible_ids={"example/model-a", "example/model-b"},
    )

    assert populations == {"intelligence": (20.0, 80.0)}
    assert sources == {"intelligence": "artificial-analysis-data-api"}


def test_snapshot_populations_precede_openrouter_transport_for_missing_live_indices() -> None:
    aa_rows = [
        {"evaluations": {"artificial_analysis_intelligence_index": 20}},
        {"evaluations": {"artificial_analysis_intelligence_index": 80}},
    ]
    snapshot_rows = [
        {"evaluations": {"artificial_analysis_coding_index": 10, "artificial_analysis_agentic_index": 30}},
        {"evaluations": {"artificial_analysis_coding_index": 90, "artificial_analysis_agentic_index": 70}},
    ]
    or_metrics = {"example/model": {"coding": 5, "agentic": 5}}

    populations, sources = builder.calibration_populations(aa_rows, snapshot_rows, or_metrics)

    assert "coding" not in populations
    assert "agentic" not in populations
    assert sources == {"intelligence": "artificial-analysis-data-api"}


def test_all_zero_live_populations_fall_back_to_nonzero_snapshot_values() -> None:
    aa_rows = [
        {
            "evaluations": {
                "artificial_analysis_intelligence_index": 0,
                "artificial_analysis_coding_index": 0,
                "artificial_analysis_agentic_index": 0,
            }
        }
        for _ in range(2)
    ]
    snapshot_rows = [
        {
            "evaluations": {
                "artificial_analysis_intelligence_index": intelligence,
                "artificial_analysis_coding_index": coding,
                "artificial_analysis_agentic_index": agentic,
            }
        }
        for intelligence, coding, agentic in ((20, 10, 30), (80, 90, 70))
    ]

    populations, sources = builder.calibration_populations(aa_rows, snapshot_rows, {})

    assert populations == {"intelligence": (20.0, 80.0)}
    assert sources == {"intelligence": "artificial-analysis-local-snapshot"}


def test_all_zero_sources_without_a_valid_fallback_remain_unavailable() -> None:
    all_zero_rows = [
        {
            "evaluations": {
                "artificial_analysis_intelligence_index": 0,
                "artificial_analysis_coding_index": 0,
                "artificial_analysis_agentic_index": 0,
            }
        }
        for _ in range(2)
    ]
    all_zero_or = {"example/model": {"coding": 0, "agentic": 0}}

    populations, sources = builder.calibration_populations(all_zero_rows, all_zero_rows, all_zero_or)

    assert populations == {}
    assert sources == {}


def test_live_aa_values_are_ignored_when_calibration_uses_snapshot_population() -> None:
    population_sources = {"intelligence": "artificial-analysis-local-snapshot"}
    primary = builder.usable_live_indices({"intelligence": 0}, population_sources)
    snapshot = builder.usable_snapshot_indices({"intelligence": 80}, population_sources)

    score, method = catalog_rules.score_candidate(
        primary,
        {},
        {"intelligence": (20.0, 80.0)},
        snapshot,
    )

    assert score == 100
    assert method == "AA Intelligence Index (dated AA snapshot fallback)"


def test_snapshot_can_supply_intelligence_population_only_when_live_is_empty() -> None:
    aa_rows = [{"evaluations": {}}]
    snapshot_rows = [
        {
            "evaluations": {
                "artificial_analysis_intelligence_index": 20,
                "artificial_analysis_coding_index": 10,
                "artificial_analysis_agentic_index": 30,
            }
        },
        {
            "evaluations": {
                "artificial_analysis_intelligence_index": 80,
                "artificial_analysis_coding_index": 90,
                "artificial_analysis_agentic_index": 70,
            }
        },
    ]
    or_metrics = {"example/model": {"intelligence": 100, "coding": 100, "agentic": 100}}

    populations, sources = builder.calibration_populations(aa_rows, snapshot_rows, or_metrics)

    assert populations["intelligence"] == (20.0, 80.0)
    assert sources["intelligence"] == "artificial-analysis-local-snapshot"


def test_live_aa_index_automatically_disables_snapshot_for_that_index() -> None:
    active = builder.usable_snapshot_indices(
        {"intelligence": 99, "coding": 25, "agentic": 75},
        {
            "intelligence": "artificial-analysis-data-api",
            "coding": "artificial-analysis-data-api",
            "agentic": "artificial-analysis-local-snapshot",
        },
    )

    assert active == {"agentic": 75}


def test_aa_snapshot_loader_checks_schema_age_and_content_hash(tmp_path) -> None:
    snapshot_path = tmp_path / "artificial-analysis-free-snapshot.json"
    payload = {
        "meta": {
            "source_url": builder.AA_URL,
            "tier": "free",
            "has_more_final": False,
            "page_size": 200,
            "pages": 1,
            "records": 1,
            "intelligence_index_version": 4.3,
            "retrieved_at_utc": datetime.now(UTC).isoformat(),
        },
        "data": [
            {
                "id": "aa-id-1",
                "slug": "model-1",
                "evaluations": {"artificial_analysis_coding_index": 42},
            }
        ],
    }
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    rows, provenance = builder.fetch_aa_snapshot(snapshot_path)

    assert len(rows) == 1
    assert provenance["status"] == "ok"
    assert provenance["row_count"] == 1
    assert len(provenance["sha256"]) == 64


def test_aa_snapshot_loader_rejects_stale_snapshot_values(tmp_path) -> None:
    snapshot_path = tmp_path / "stale-snapshot.json"
    payload = {
        "meta": {
            "source_url": builder.AA_URL,
            "tier": "free",
            "has_more_final": False,
            "page_size": 200,
            "pages": 1,
            "records": 1,
            "intelligence_index_version": 4.3,
            "retrieved_at_utc": "2020-01-01T00:00:00Z",
        },
        "data": [{"id": "aa-id-1", "slug": "model-1", "evaluations": {}}],
    }
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    rows, provenance = builder.fetch_aa_snapshot(snapshot_path)

    assert rows == []
    assert provenance["status"] == "stale"


def test_openrouter_benchmark_transport_prefers_management_key(monkeypatch) -> None:
    seen_headers: list[str] = []

    def fake_get_json(url, headers=None):
        from urllib.parse import parse_qs, urlparse

        task = parse_qs(urlparse(url).query)["task_type"][0]
        assert headers is not None
        seen_headers.append(headers["Authorization"])
        field = f"{task}_index"
        return {
            "meta": {"source": "artificial-analysis", "task_type": task, "model_count": 1},
            "data": [{"source": "artificial-analysis", "model_permaslug": "example/model-v1", field: 50}],
        }, "hash"

    monkeypatch.setattr(builder, "_get_json", fake_get_json)
    metrics, provenance = builder.fetch_openrouter_aa_indices("management-test-key", "regular-test-key")

    assert provenance["credential_env"] == "OPENROUTER_MANAGEMENT_KEY"
    assert seen_headers == ["Bearer management-test-key"] * 3
    assert metrics["example/model-v1"] == {"intelligence": 50, "coding": 50, "agentic": 50}


def test_openrouter_benchmark_transport_falls_back_to_regular_api_key(monkeypatch) -> None:
    seen_headers: list[str] = []

    def fake_get_json(url, headers=None):
        from urllib.parse import parse_qs, urlparse

        task = parse_qs(urlparse(url).query)["task_type"][0]
        assert headers is not None
        seen_headers.append(headers["Authorization"])
        return {
            "meta": {"source": "artificial-analysis", "task_type": task, "model_count": 0},
            "data": [],
        }, "hash"

    monkeypatch.setattr(builder, "_get_json", fake_get_json)
    metrics, provenance = builder.fetch_openrouter_aa_indices(None, "regular-test-key")

    assert provenance["credential_env"] == "OPENROUTER_API_KEY"
    assert seen_headers == ["Bearer regular-test-key"] * 3
    assert metrics == {}


@pytest.mark.parametrize("model_count", [None, "1", True, 2])
def test_openrouter_benchmark_transport_rejects_invalid_model_count(monkeypatch, model_count) -> None:
    def fake_get_json(url, headers=None):
        from urllib.parse import parse_qs, urlparse

        task = parse_qs(urlparse(url).query)["task_type"][0]
        meta = {"source": "artificial-analysis", "task_type": task}
        if model_count is not None:
            meta["model_count"] = model_count
        field = f"{task}_index"
        return {
            "meta": meta,
            "data": [{"source": "artificial-analysis", "model_permaslug": "example/model-v1", field: 50}],
        }, "hash"

    monkeypatch.setattr(builder, "_get_json", fake_get_json)

    with pytest.raises(builder.CatalogError, match="model_count"):
        builder.fetch_openrouter_aa_indices("management-test-key", None)


def test_console_price_parser_uses_exact_model_ids_and_current_discount_price() -> None:
    html = """<table><tr><th>Model</th><th>Model ID</th></tr>
      <tr><td>Mistral Large 4</td><td>mistral-large-4</td></tr>
      <tr><td>Claude Haiku 5.5</td><td>claude-haiku-5-5</td></tr></table>
      <table><tr><th>Model</th><th>Input</th><th>Output</th><th>Cached Read</th><th>Cached Write</th></tr>
      <tr><td>Mistral Large 4 (50% off)</td><td><del>$1.36</del> $0.68</td><td>$2.09</td><td>$0.07</td><td>-</td></tr>
      <tr><td>Claude Haiku 5.5 (≤ 100K tokens)</td><td>$0.10</td><td>$0.50</td><td>$0.01</td><td>$0.125</td></tr></table>"""

    ids, tiers = builder.parse_console_price_tables(html)

    assert ids["mistral large 4"] == "mistral-large-4"
    assert [(tier.model_name, tier.input_price) for tier in tiers] == [
        ("Mistral Large 4", Decimal("0.68")),
        ("Claude Haiku 5.5", Decimal("0.10")),
    ]


def test_go_price_parser_keeps_input_price_and_monthly_limit() -> None:
    html = """<table><tr><th>Plan</th><th>Price</th><th>Included usage</th></tr>
      <tr><td>Go</td><td>$10/month</td><td>Lower-cost access</td></tr></table>
      <table><tr><th>Model</th><th>Input</th><th>Output</th><th>Cached Read</th>
      <th>Cached Write</th><th>Monthly limit</th></tr>
      <tr><td>GPT 6 Luna (≤ 272K tokens)</td><td>$0.10</td><td>$0.50</td>
      <td>$0.01</td><td>$0.125</td><td>$15</td></tr></table>"""

    tiers = builder.parse_go_price_table(html)

    assert tiers == [builder.PriceTier("GPT 6 Luna", Decimal("0.10"), "$15")]
    assert builder.parse_go_plan_prices(html) == {"Go": "$10/month"}
