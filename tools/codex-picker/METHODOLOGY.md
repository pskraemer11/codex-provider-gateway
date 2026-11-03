# Picker quality/price methodology

This document describes the values exported by `provider-selection-review-*.csv`.
The CSV has one row per evaluated direct-provider model ID (`openrouter`, `go`,
or `zen`); it does not duplicate Zen routes for the combined `proxy` catalog.
Prices are USD per one million input tokens. An empty score means `unverified`,
not zero.

## Price policy history

The initial working input-price cap was `$0.50/M`. After reviewing the model
catalog, it was lowered to `$0.25/M`, which excluded one model. The current
default is strictly below `$0.30/M`; a model priced at exactly `$0.30/M` does
not qualify. `catalog_rules.INPUT_PRICE_LIMIT` is the single source used by
selection, audit reporting, CSV validation, and the builder's printed criteria.

The initial quality threshold was `> 70/100` on a scale calibrated only over
price-eligible candidates. That scale moved whenever the cheap candidate set
changed. The current policy calibrates first over the complete usable AA
Intelligence population and applies provider price and quality filters
afterwards. The threshold is `> 45/100`; `catalog_rules.MIN_CALIBRATED_SCORE`
is the single source used by selection, CLI defaults, audit reporting, and the
builder's printed criteria. `45` keeps `zen/gpt-6-luna` (AA raw 27.8,
calibrated ≈ 45.1) in the proxy catalog, which is the model the root Codex
selection points at.

## Price evidence

- OpenRouter: prompt/input price from `/api/v1/models`, multiplied by one million.
- OpenCode Go: input-price tiers and model quota from the official Go documentation.
- OpenCode Zen: input-price tiers from the official Console model/pricing documentation.

For Go and Zen, the audit records the minimum and maximum published input price
for a route. Normal selection requires the maximum listed price to be strictly
below `$0.30/M`; the CSV exposes both values. The filter does not use average
per-task costs.

## Benchmark score

Raw AA values are associated only by exact model ID or a unique, canonicalized
model-ID component. Ambiguous or missing matches remain unverified.

AA lists one row per reasoning level (`-low`, `-medium`, `-high`, `-xhigh`,
`-max`, `-reasoning`, `-non-reasoning`, `-minimal`). Each family is collapsed to
its **highest** Intelligence value, because a catalog route selects the model,
not a specific effort. The base slug is often but not always the strongest level
(`gemini-3-5-flash-medium` beat its base row in the 2026-10-13 snapshot). The
calibration population therefore holds one value per base model, not one per
effort variant. Product suffixes that are not reasoning levels (for example
`-pro`) stay separate families.

The AA Intelligence Index is calibrated to a 0–100 Min-Max scale over all
usable values in the selected AA population before provider prices are applied:
the observed minimum maps to 0 and the observed maximum to 100. Values outside
that range clamp to 0 or 100. A population with fewer than two values is
unverified, and a population in which every value is zero is treated as
suspicious rather than scored. A model's individual live value is ignored when
the live Intelligence population is rejected. Equal values therefore receive
the same calibrated score. The source population order is:

1. Live AA Data API Intelligence values.
2. The rolling live snapshot `data/artificial-analysis-live-snapshot.json`,
   written after every successful fetch and at most 31 days old. It is used when
   the live fetch fails for any reason (missing key, network error, rejected
   response) or its Intelligence population is absent or all zero.
3. The dated local AA snapshot, at most 31 days old, as the last resort.

Absolute AA Intelligence values and calibrated scores are different units. An
absolute 95th-percentile value such as `45.3` cannot be compared directly with
a calibrated threshold such as `45/100`; the latter corresponds to a raw value
derived from the observed minimum and maximum. Quantile statistics are useful
for reviewing the distribution, but price and provider identity are applied
only after the full-population calibration.

The local snapshot used by this checkout is
`artificial-analysis-free-snapshot-20261013.json`: 699 records, retrieved
2026-10-13 21:07:46 UTC, from `https://artificialanalysis.ai/api/v2/language/models/free`
with AA API tier metadata `free`. That endpoint/tier identifies the AA data
access source; it does not classify those records as provider models with
zero token prices. This snapshot supplies only a fallback Intelligence-index
calibration population, using the same full-population rule as live AA.
OpenRouter, Go, and Zen prices are still sourced from
their respective provider catalogs/docs, and the explicitly pinned `$0` routes
are handled separately. On this workstation, the builder's default ancestor
lookup finds the JSON file in the sibling `automatisierter Benchmark-Abgleich`
project. The Windows `.lnk` in this repo's `data/` directory is only an Explorer
shortcut and is not read by Python. Use `--aa-snapshot` or
`ARTIFICIAL_ANALYSIS_FREE_SNAPSHOT` to point another checkout at a JSON file.

The final score is the calibrated AA Intelligence Index only. The 60/40
Coding/Agentic composite and the OpenRouter Coding fallback are deliberately
removed because their mixed scales introduce vintage bias. Models without a
usable Intelligence value remain `unverified` and are not selected. The
CSV preserves the final calibrated score, `score_method`, benchmark/transport
source, identity match, and the raw index dictionaries used for each candidate.

## Selection and explicit exceptions

A normal candidate is selected only when input price is strictly below
`$0.30/M` and calibrated score is strictly greater than `45/100`. Missing
benchmark values are never substituted with zero.

Each catalog lists a model once per provider route. The reasoning intensity is
not a separate model: it stays the entry's `supported_reasoning_levels` and
`default_reasoning_level` sub-selection. If a provider exposes effort-suffixed
slugs as separate routes, the builder keeps the best-scored one (then the
cheaper, then the shorter slug) and records the dropped ids in
`deduplicated_reasoning_variants`. `opencode-go/` and `zen/` are different
billing routes and are never merged into each other.

Five explicitly requested free routes are the only score exceptions. They are
selected only when the provider source confirms exactly `$0` input price and
remain `score: null`, `benchmark_source=unverified`, and
`selection_reason=user_pinned_free_exception` when no benchmark is available:

- OpenRouter: `cohere/north-mini-code:free`, `openrouter/free`
- Zen: `glm-5.3-flash-free`, `deepseek-v4.1-flash-free`,
  `mimo-v2.6-flash-free`

`deepseek/deepseek-v4.1-flash-1017` is the preferred OpenRouter default only
when it passes the ordinary price and score filters. Similar Go/Zen IDs are not
treated as the same route.

AA describes its Coding Agent Index as a composite of
FrontierCode v1.1, Terminal-Bench 4.0, and SWE-Atlas-QnA-AA. The user reports
that this composite is not downloadable through the AA API. It is therefore
not substituted for the API's Intelligence/Coding/Agentic indices and is not
inferred from dashboard Pareto positions or per-task cost.

## CSV interpretation

The exporter consumes `provider-catalog-audit.json` and writes every evaluated
candidate below the input-price cap, selected or not. Provider plus model ID is
the row key. `selected` and `selection_reason` show the decision; raw index
values are JSON objects within their cells. An empty `calibrated_score_0_100`
is intentionally missing/unverified. `input_price_min_usd_per_1m` and
`input_price_max_usd_per_1m` are never cost-per-task values. Before writing,
formula-like text cells are prefixed with an apostrophe so spreadsheet software
opens externally sourced values as text rather than formulas.

The `provider-selection-review-2026-10-31.csv` report is explicitly a
non-live reconstruction. Its provider prices come from the successful
`2026-10-30T23:40:51Z` audit; the AA API was rate-limited during the attempted
live rebuild. The report records the complete-snapshot provenance and the one
additional Intelligence value recovered by field name from the original
`2026-10-30` CSV.
