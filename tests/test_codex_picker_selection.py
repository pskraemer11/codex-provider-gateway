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


def test_default_proxy_url_follows_proxy_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCODE_GO_PROXY_MODELS_URL", raising=False)
    monkeypatch.setenv("OPENCODE_GO_PROXY_PORT", "8899")
    assert builder.default_proxy_models_url() == "http://127.0.0.1:8899/v1/models"


def test_fetch_proxy_catalog_uses_explicit_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    state = tmp_path / "opencode-go-proxy"
    state.mkdir()
    monkeypatch.setenv("OPENCODE_GO_PROXY_STATE_DIR", str(state))
    (state / "merged-models.json").write_text(
        json.dumps({"models": [{"slug": "opencode-go/example"}, {"slug": "zen/example"}]}),
        encoding="utf-8",
    )
    requested: list[str] = []

    def fake_get_json(url: str) -> tuple[dict, str]:
        requested.append(url)
        return {"data": [{"id": "opencode-go/example"}, {"id": "zen/example"}]}, "live-hash"

    monkeypatch.setattr(builder, "_get_json", fake_get_json)
    entries, source = builder.fetch_proxy_catalog(tmp_path, "http://127.0.0.1:8899/v1/models")

    assert requested == ["http://127.0.0.1:8899/v1/models"]
    assert [entry["slug"] for entry in entries] == ["opencode-go/example", "zen/example"]
    assert source["url"] == requested[0]
    assert source["live_verified"] is True


def test_native_template_uses_explicit_file(tmp_path: Path) -> None:
    template = tmp_path / "template.json"
    template.write_text(json.dumps({"models": [{"slug": "native-example"}]}), encoding="utf-8")

    models, source = builder.load_native_catalog_template(template, codex_dir=tmp_path)

    assert models == [{"slug": "native-example"}]
    assert source["source"] == "file"
    assert source["path"] == str(template)


def test_native_template_falls_back_to_codex_debug_models(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> object:
        calls.append(command)
        return type("Result", (), {"returncode": 0, "stdout": '{"models":[{"slug":"native-example"}]}', "stderr": ""})()

    monkeypatch.setattr(builder.subprocess, "run", fake_run)
    models, source = builder.load_native_catalog_template(None, codex_dir=tmp_path, codex_bin="codex-test")

    assert calls == [["codex-test", "debug", "models", "--bundled"]]
    assert models == [{"slug": "native-example"}]
    assert source["source"] == "codex-debug-models-bundled"


def _cached_proxy_audit() -> dict:
    diagnostic = {
        "under_price_limit": 0,
        "direct_aa_identity_match": 0,
        "score_available": 0,
        "selected": 0,
        "highest_score": None,
    }
    return {
        "sources": {
            "artificial_analysis": {"row_count": 0, "page_count": 0},
            "openrouter_models": {"row_count": 0},
            "opencode_proxy": {"cached_provider_model_count": 0, "live_verified": False},
            "artificial_analysis_snapshot": {"status": "unavailable"},
        },
        "selection_diagnostics": {provider: dict(diagnostic) for provider in ("openrouter", "go", "zen")},
        "calibration_populations": {},
        "evaluated_candidates": [],
        "models": [],
    }


@pytest.mark.parametrize(("allow_cached", "expected"), [(False, 1), (True, 0)])
def test_check_requires_live_proxy_unless_cache_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    allow_cached: bool,
    expected: int,
) -> None:
    catalogs = {provider: {"models": []} for provider in ("openrouter", "go", "zen", "proxy")}

    def fake_build(**kwargs: object) -> tuple[dict, dict]:
        return catalogs, _cached_proxy_audit()

    argv = ["build_provider_catalogs.py", "--check"]
    if allow_cached:
        argv.append("--allow-cached-proxy")
    monkeypatch.setattr(builder, "build_catalog_data", fake_build)
    monkeypatch.setattr(sys, "argv", argv)

    assert builder.main() == expected
    output = capsys.readouterr().out
    if expected:
        assert "Live-Pruefung verlangt" in output
    else:
        assert "Warnung: lokaler Proxy nicht erreichbar" in output


def test_check_reports_excluded_free_variants(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    catalogs = {provider: {"models": []} for provider in ("openrouter", "go", "zen", "proxy")}
    audit = _cached_proxy_audit()
    audit["sources"]["opencode_proxy"]["live_verified"] = True
    audit["criteria"] = {
        "free_variants": {
            "excluded_counts": {"openrouter": 2, "go": 0, "zen": 3},
        }
    }
    audit["evaluated_candidates"] = [{"provider": "zen", "id": "zen/scored-model", "score": 68.765}]
    monkeypatch.setattr(builder, "build_catalog_data", lambda **kwargs: (catalogs, audit))
    monkeypatch.setattr(sys, "argv", ["build_provider_catalogs.py", "--check", "--provider", "zen"])

    assert builder.main() == 0
    output = capsys.readouterr().out
    assert "zen/scored-model=68.8/100" in output
    assert "Free-Tier ausgeschlossen: openrouter 2, go 0, zen 3" in output


@pytest.mark.parametrize(
    ("identifier", "selection_reason", "input_price"),
    [
        ("zen/scored-model", "price_and_calibrated_score", "0.12"),
        ("zen/cheap-model", "price_and_calibrated_score", "0.02"),
    ],
)
def test_model_selection_score_display_uses_one_decimal_for_each_price_tier(
    identifier: str, selection_reason: str, input_price: str
) -> None:
    entry = builder._make_entry(
        provider="zen",
        identifier=identifier,
        source_model=None,
        template={"slug": "template"},
        label="Zen model",
        prices=[Decimal(input_price)],
        limits=[],
        score=72.56,
        method="AA Intelligence Index",
        transport="AA Data API",
        price_source="OpenCode Console documentation",
        selection_reason=selection_reason,
    )

    assert "Intelligence-Score 72.6/100" in entry["display_name"]
    assert "AA-Intelligence-Score 72.6/100" in entry["description"]
    assert f"Auswahl: {selection_reason}" in entry["description"]
    assert "Auswahlgrund" not in entry["description"]
    assert "benchmark_source=AA" in entry["description"]
    assert "artificial-analysis" not in entry["description"]
    assert "Artificial Analysis" not in entry["description"]


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
    assert catalog_rules.qualifies_model("0.499999", 40.001)
    assert catalog_rules.qualifies_model("0.499999", 99)
    assert not catalog_rules.qualifies_model("0.50", 99)
    assert not catalog_rules.qualifies_model("0.10", 40)
    assert not catalog_rules.qualifies_model(None, 90)
    assert not catalog_rules.qualifies_model("0.10", None)
    assert not catalog_rules.qualifies_model("0.022", 39.999)


def test_filter_uses_cli_configurable_strict_price_and_score_boundaries() -> None:
    assert catalog_rules.qualifies_model("0.149", 75, input_price_limit=Decimal("0.15"), min_calibrated_score=74)
    assert not catalog_rules.qualifies_model("0.15", 75, input_price_limit=Decimal("0.15"), min_calibrated_score=74)
    assert not catalog_rules.qualifies_model("0.149", 74, input_price_limit=Decimal("0.15"), min_calibrated_score=74)


def test_picker_price_cap_is_shared_and_reported() -> None:
    assert catalog_rules.INPUT_PRICE_LIMIT == Decimal("0.50")
    assert builder.INPUT_PRICE_LIMIT is catalog_rules.INPUT_PRICE_LIMIT
    assert catalog_rules.MIN_CALIBRATED_SCORE == 40.0
    assert builder.MIN_CALIBRATED_SCORE == catalog_rules.MIN_CALIBRATED_SCORE
    assert builder.selection_criteria_text() == (
        "Kriterien: Input < $0.50/M Token und kalibrierter AA-Intelligence-Score > 40/100"
    )
    assert builder.selection_criteria_text(Decimal("0.15"), 74) == (
        "Kriterien: Input < $0.15/M Token und kalibrierter AA-Intelligence-Score > 74/100"
    )


def test_gateway_free_routes_are_never_selected() -> None:
    for identifier in ("glm-5.3-flash-free", "deepseek-v4.1-flash-free", "mimo-v2.6-flash-free"):
        assert builder._selection_reason("zen", identifier, Decimal("0"), 100.0) is None
    # Free heisst nicht automatisch gesperrt: nur das OpenCode-Gateway ist dicht.
    assert (
        builder._selection_reason("zen", "deepseek-v4.1-flash", Decimal("0.10"), 80.0) == "price_and_calibrated_score"
    )


def test_openrouter_free_routes_stay_usable_because_they_bypass_the_gateway() -> None:
    # Direkter OpenRouter-Key: am 05.11.2026 mit HTTP 200 belegt.
    assert builder._selection_reason("openrouter", "cohere/north-mini-code:free", Decimal("0"), 100.0) == (
        "price_and_calibrated_score"
    )
    assert builder._selection_reason("openrouter", "openrouter/free", Decimal("0"), 100.0) == (
        "price_and_calibrated_score"
    )


def test_unverified_free_exception_is_opt_in_and_openrouter_only() -> None:
    free = "cohere/north-mini-code:free"

    assert builder._selection_reason("openrouter", free, Decimal("0"), None) is None
    assert (
        builder._selection_reason("openrouter", free, Decimal("0"), None, include_unverified_free=True)
        == "unverified_free_exception"
    )
    # Go und Zen bleiben gesperrt, auch mit Flag.
    assert (
        builder._selection_reason("zen", "glm-5.3-flash-free", Decimal("0"), None, include_unverified_free=True) is None
    )
    # Nur bei verifiziertem $0-Inputpreis.
    assert builder._selection_reason("openrouter", free, Decimal("0.01"), None, include_unverified_free=True) is None
    # Unverifiziert, aber keine Free-Route.
    assert (
        builder._selection_reason(
            "openrouter", "moonshotai/kimi-k3-lite", Decimal("0.10"), None, include_unverified_free=True
        )
        is None
    )


def test_include_unverified_free_flag_reaches_the_builder(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: dict[str, object] = {}
    catalogs = {provider: {"models": []} for provider in ("openrouter", "go", "zen", "proxy")}

    def fake_build(**kwargs: object) -> tuple[dict, dict]:
        captured.update(kwargs)
        return catalogs, _cached_proxy_audit()

    monkeypatch.setattr(builder, "build_catalog_data", fake_build)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_provider_catalogs.py",
            "--check",
            "--provider",
            "openrouter",
            "--allow-cached-proxy",
            "--include-unverified-free",
        ],
    )

    assert builder.main() == 0
    capsys.readouterr()
    assert captured["include_unverified_free"] is True


def test_include_unverified_free_defaults_to_false(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: dict[str, object] = {}
    catalogs = {provider: {"models": []} for provider in ("openrouter", "go", "zen", "proxy")}

    def fake_build(**kwargs: object) -> tuple[dict, dict]:
        captured.update(kwargs)
        return catalogs, _cached_proxy_audit()

    monkeypatch.setattr(builder, "build_catalog_data", fake_build)
    monkeypatch.setattr(
        sys, "argv", ["build_provider_catalogs.py", "--check", "--provider", "openrouter", "--allow-cached-proxy"]
    )

    assert builder.main() == 0
    capsys.readouterr()
    assert captured["include_unverified_free"] is False


def test_free_variant_rule_matches_only_the_gateway_suffix() -> None:
    assert catalog_rules.is_free_variant("zen", "deepseek-v4.1-flash-free")
    assert catalog_rules.is_free_variant("go", "some-model-free")
    assert not catalog_rules.is_free_variant("zen", "deepseek-v4.1-flash")
    assert not catalog_rules.is_free_variant("openrouter", "cohere/north-mini-code:free")
    assert not catalog_rules.is_free_variant("openrouter", "openrouter/free")
    assert not catalog_rules.is_free_variant("openrouter", "moonshotai/kimi-k3")


def test_catalog_sort_prefers_selected_deepseek_1017_and_ranks_unverified_last() -> None:
    preferred = {"id": "deepseek/deepseek-v4.1-flash-1017", "score": 70.0, "price": "0.022"}
    scored = {"id": "moonshotai/kimi-k3", "score": 90.0, "price": "0.239"}
    unverified = {"id": "moonshotai/kimi-k3-lite", "score": None, "price": "0.10"}

    assert builder._candidate_sort_key("openrouter", preferred) < builder._candidate_sort_key("openrouter", scored)
    assert builder._candidate_sort_key("openrouter", scored) < builder._candidate_sort_key("openrouter", unverified)


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


def test_aa_model_base_strips_reasoning_suffixes_only() -> None:
    assert catalog_rules.aa_model_base("gpt-6-luna") == "gpt-6-luna"
    assert catalog_rules.aa_model_base("gpt-6-luna-xhigh") == "gpt-6-luna"
    assert catalog_rules.aa_model_base("gpt-6-luna-non-reasoning") == "gpt-6-luna"
    assert catalog_rules.aa_model_base("gpt-6-luna-max") == "gpt-6-luna"
    # A real product suffix is not a reasoning level.
    assert catalog_rules.aa_model_base("gpt-6-luna-pro") == "gpt-6-luna-pro"


def test_calibration_population_keeps_only_the_highest_reasoning_level() -> None:
    rows = [
        {"slug": "model-a", "evaluations": {"artificial_analysis_intelligence_index": 10}},
        {"slug": "model-a-high", "evaluations": {"artificial_analysis_intelligence_index": 30}},
        {"slug": "model-a-low", "evaluations": {"artificial_analysis_intelligence_index": 20}},
        {"slug": "model-b", "evaluations": {"artificial_analysis_intelligence_index": 50}},
    ]

    populations, sources = builder.calibration_populations(rows, [])

    assert populations["intelligence"] == (30.0, 50.0)
    assert sources["intelligence"] == "artificial-analysis-data-api"


def test_source_metrics_selects_the_family_maximum_over_the_base_row() -> None:
    rows = [
        {"slug": "model-a", "evaluations": {"artificial_analysis_intelligence_index": 10}},
        {"slug": "model-a-xhigh", "evaluations": {"artificial_analysis_intelligence_index": 30}},
        {"slug": "model-a-low", "evaluations": {"artificial_analysis_intelligence_index": 5}},
    ]

    primary, snapshot, _, join = builder._source_metrics("zen/model-a", rows, [], {})

    assert primary == {"intelligence": 30.0}
    assert snapshot == {}
    assert "reasoning-family maximum (model-a-xhigh)" in join


def test_source_metrics_labels_an_exact_slug_when_it_is_already_the_maximum() -> None:
    rows = [
        {"slug": "model-a", "evaluations": {"artificial_analysis_intelligence_index": 30}},
        {"slug": "model-a-high", "evaluations": {"artificial_analysis_intelligence_index": 20}},
    ]

    primary, _, _, join = builder._source_metrics("zen/model-a", rows, [], {})

    assert primary == {"intelligence": 30.0}
    assert join.startswith("AA=exact slug")


def test_source_metrics_does_not_merge_a_product_variant_into_the_family() -> None:
    rows = [
        {"slug": "model-a", "evaluations": {"artificial_analysis_intelligence_index": 10}},
        {"slug": "model-a-pro", "evaluations": {"artificial_analysis_intelligence_index": 90}},
    ]

    primary, _, _, join = builder._source_metrics("zen/model-a", rows, [], {})

    assert primary == {"intelligence": 10.0}
    assert join.startswith("AA=exact slug")


@pytest.mark.parametrize(
    ("family", "rows", "expected"),
    [
        (
            "glm-4-6",
            {"glm-4-6": 14.9, "glm-4-6-reasoning": 18.5},
            18.5,
        ),
        (
            "claude-4-5-haiku",
            {"claude-4-5-haiku": 15.4, "claude-4-5-haiku-reasoning": 16.9},
            16.9,
        ),
        (
            "gpt-oss-20b",
            {"gpt-oss-20b": 9.0, "gpt-oss-20b-low": 10.0, "gpt-oss-20b-high": None},
            10.0,
        ),
        (
            "gemini-3-8-flash",
            {"gemini-3-8-flash": 30.5, "gemini-3-8-flash-medium": 30.0, "gemini-3-8-flash-low": 22.3},
            30.5,
        ),
        (
            "glm-5-3",
            {"glm-5-3": 44.8, "glm-5-3-low": 34.3},
            44.8,
        ),
    ],
)
def test_reasoning_family_patterns_from_the_workbook(family, rows, expected) -> None:
    aa_rows = [
        {
            "slug": slug,
            "evaluations": {
                "artificial_analysis_intelligence_index": value,
            },
        }
        for slug, value in rows.items()
    ]

    primary, _, _, join = builder._source_metrics(f"zen/{family}", aa_rows, [], {})

    assert primary == {"intelligence": expected}
    assert "unverified" not in join.split(";")[0]


def test_proxy_catalog_lists_all_go_routes_before_zen() -> None:
    items = [
        {"id": "zen/model-b", "score": 90.0, "price": "0.10", "entry": {}},
        {"id": "opencode-go/model-a", "score": 50.0, "price": "0.10", "entry": {}},
        {"id": "zen/model-c", "score": None, "price": "0", "entry": {}},
        {"id": "opencode-go/model-d", "score": None, "price": "0", "entry": {}},
    ]

    ordered = sorted(items, key=lambda item: builder._candidate_sort_key("proxy", item))

    assert [item["id"] for item in ordered] == [
        "opencode-go/model-a",
        "opencode-go/model-d",
        "zen/model-b",
        "zen/model-c",
    ]


def test_openrouter_catalog_keeps_score_order_without_route_groups() -> None:
    items = [
        {"id": "vendor/low", "score": 50.0, "price": "0.10", "entry": {}},
        {"id": "vendor/high", "score": 90.0, "price": "0.10", "entry": {}},
    ]

    ordered = sorted(items, key=lambda item: builder._candidate_sort_key("openrouter", item))

    assert [item["id"] for item in ordered] == ["vendor/high", "vendor/low"]


def test_catalog_keeps_one_entry_per_base_model_and_drops_effort_variants() -> None:
    items = [
        {"id": "openai/model-a", "score": 50.0, "price": "0.10", "entry": {"slug": "openai/model-a"}},
        {"id": "openai/model-a-high", "score": 60.0, "price": "0.10", "entry": {"slug": "openai/model-a-high"}},
        {"id": "openai/model-a-pro", "score": 70.0, "price": "0.10", "entry": {"slug": "openai/model-a-pro"}},
    ]

    kept, dropped = builder._dedupe_reasoning_variants(items)

    assert [item["id"] for item in kept] == ["openai/model-a-high", "openai/model-a-pro"]
    assert [item["id"] for item in dropped] == ["openai/model-a"]


def test_reasoning_variant_tie_break_prefers_the_cheaper_base_slug() -> None:
    items = [
        {"id": "openai/model-a", "score": 50.0, "price": "0.10", "entry": {"slug": "openai/model-a"}},
        {"id": "openai/model-a-high", "score": 50.0, "price": "0.20", "entry": {"slug": "openai/model-a-high"}},
    ]

    kept, dropped = builder._dedupe_reasoning_variants(items)

    assert [item["id"] for item in kept] == ["openai/model-a"]
    assert [item["id"] for item in dropped] == ["openai/model-a-high"]


def test_dedupe_keeps_go_and_zen_as_distinct_routes() -> None:
    items = [
        {"id": "opencode-go/model-a", "score": 50.0, "price": "0.10", "entry": {"slug": "opencode-go/model-a"}},
        {"id": "zen/model-a", "score": 50.0, "price": "0.10", "entry": {"slug": "zen/model-a"}},
        {
            "id": "opencode-go/model-a-high",
            "score": 60.0,
            "price": "0.10",
            "entry": {"slug": "opencode-go/model-a-high"},
        },
    ]

    kept, dropped = builder._dedupe_reasoning_variants(items)

    assert sorted(item["id"] for item in kept) == ["opencode-go/model-a-high", "zen/model-a"]
    assert [item["id"] for item in dropped] == ["opencode-go/model-a"]


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


def test_calibration_population_uses_all_live_values_before_price_filtering() -> None:
    aa_rows = [
        {"slug": "example/expensive", "evaluations": {"artificial_analysis_intelligence_index": 100}},
        {"slug": "example/model-a", "evaluations": {"artificial_analysis_intelligence_index": 20}},
        {"slug": "example/model-b", "evaluations": {"artificial_analysis_intelligence_index": 80}},
    ]

    populations, sources = builder.calibration_populations(aa_rows, [])

    assert populations == {"intelligence": (20.0, 80.0, 100.0)}
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


def _aa_live_source() -> dict:
    return {
        "url": builder.AA_URL,
        "retrieved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "page_count": 1,
        "page_size": 200,
        "row_count": 1,
        "tier": "free",
        "intelligence_index_version": 5,
        "sha256_by_page": ["a" * 64],
    }


def _aa_live_rows() -> list[dict]:
    return [
        {
            "id": "aa-id-1",
            "slug": "model-1",
            "evaluations": {"artificial_analysis_intelligence_index": 50},
        }
    ]


def test_write_aa_snapshot_round_trips_through_the_snapshot_loader(tmp_path) -> None:
    snapshot_path = tmp_path / "artificial-analysis-live-snapshot.json"
    rows = _aa_live_rows()

    written = builder.write_aa_snapshot(snapshot_path, rows, _aa_live_source())

    assert written["bytes"] > 0
    assert len(written["sha256"]) == 64
    loaded, provenance = builder.fetch_aa_snapshot(snapshot_path)
    assert loaded == rows
    assert provenance["status"] == "ok"
    assert provenance["row_count"] == 1
    assert provenance["intelligence_index_version"] == 5


def test_load_aa_population_persists_a_successful_live_fetch(monkeypatch, tmp_path) -> None:
    live_rows = _aa_live_rows()
    monkeypatch.setattr(builder, "fetch_aa_models", lambda key: (live_rows, _aa_live_source()))
    live_path = tmp_path / "live.json"

    population = builder.load_aa_population(
        live_snapshot_path=live_path,
        dated_snapshot_path=tmp_path / "dated.json",
        api_key="test-key",
    )

    assert population.rows == live_rows
    assert population.source["snapshot"]["status"] == "written"
    assert live_path.is_file()
    assert population.snapshot_rows == live_rows
    assert population.snapshot_source["file_name"] == live_path.name


def test_load_aa_population_skips_persisting_in_check_mode(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(builder, "fetch_aa_models", lambda key: (_aa_live_rows(), _aa_live_source()))
    live_path = tmp_path / "live.json"

    population = builder.load_aa_population(
        live_snapshot_path=live_path,
        dated_snapshot_path=tmp_path / "dated.json",
        api_key="test-key",
        persist_live_snapshot=False,
    )

    assert population.source["snapshot"]["status"] == "skipped"
    assert not live_path.exists()


def test_load_aa_population_falls_back_to_the_rolling_snapshot(monkeypatch, tmp_path) -> None:
    live_path = tmp_path / "live.json"
    builder.write_aa_snapshot(live_path, _aa_live_rows(), _aa_live_source())

    def fail(key: str):
        raise builder.CatalogError("AA: HTTP 503")

    monkeypatch.setattr(builder, "fetch_aa_models", fail)

    population = builder.load_aa_population(
        live_snapshot_path=live_path,
        dated_snapshot_path=tmp_path / "dated.json",
        api_key="test-key",
    )

    assert population.rows == []
    assert population.source["status"] == "unavailable"
    assert "503" in population.source["reason"]
    assert [row["slug"] for row in population.snapshot_rows] == ["model-1"]
    assert population.snapshot_source["status"] == "ok"
    populations, sources = builder.calibration_populations(population.rows, population.snapshot_rows)
    assert sources["intelligence"] == "artificial-analysis-local-snapshot"
    assert populations["intelligence"] == (50.0,)


def test_load_aa_population_without_api_key_uses_the_rolling_snapshot(tmp_path) -> None:
    live_path = tmp_path / "live.json"
    builder.write_aa_snapshot(live_path, _aa_live_rows(), _aa_live_source())

    population = builder.load_aa_population(
        live_snapshot_path=live_path,
        dated_snapshot_path=tmp_path / "dated.json",
        api_key=None,
    )

    assert population.rows == []
    assert "ARTIFICIAL_ANALYSIS_API_KEY" in population.source["reason"]
    assert population.snapshot_rows == _aa_live_rows()


def test_load_aa_population_prefers_the_rolling_snapshot_over_the_dated_one(tmp_path) -> None:
    live_path = tmp_path / "live.json"
    dated_path = tmp_path / "dated.json"
    builder.write_aa_snapshot(live_path, _aa_live_rows(), _aa_live_source())
    dated_rows = [{"id": "old", "slug": "old-model", "evaluations": {}}]
    builder.write_aa_snapshot(dated_path, dated_rows, _aa_live_source())

    population = builder.load_aa_population(
        live_snapshot_path=live_path,
        dated_snapshot_path=dated_path,
        api_key=None,
    )

    assert population.snapshot_rows == _aa_live_rows()
    assert population.dated_snapshot_source["file_name"] == dated_path.name


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
