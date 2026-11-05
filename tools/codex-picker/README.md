# Codex provider catalog builder

This tool generates Codex catalogs filtered by price and benchmark for OpenRouter,
OpenCode Go, OpenCode Zen, and the combined Go/Zen proxy.
It selects a minimum quality and a maximum input price, making it a fixed point on the Pareto frontier.

If you want a different point that is optimal for you, simply create a known catalog.
The generated catalogs are written to the active Codex home by default; the
combined desktop catalog depends on the routes announced by the proxy.

The Windows PowerShell provider switcher, proxy health watchdog, and Task
Scheduler installer now live here. See [Windows proxy autostart](#windows-proxy-autostart).
Each script provides detailed comment-based help through `-?`, `-Help`, or
`--help`, including every parameter and usage example.

From this repository root, run:

```powershell
python tools/codex-picker/build_provider_catalogs.py --check
python tools/codex-picker/build_provider_catalogs.py
```

`--check` fetches source data, requires a reachable live proxy, and validates
the selection without writing catalogs. Add `--allow-cached-proxy` only when an
offline check against the last saved proxy catalog is intentional. A write to
the active Codex home requires the same live verification by default; generated
catalogs are backed up before replacement, and the Codex loader is verified
after writing. API credentials are read only from
`ARTIFICIAL_ANALYSIS_API_KEY` and the optional `OPENROUTER_API_KEY`.

`--include-unverified-free` keeps OpenRouter's `:free` routes that cost nothing
but have no benchmark score. They enter the catalog only at a verified `$0`
input price, stay `unverified` (no score, ranked below scored models) and are
marked with `selection_reason=unverified_free_exception`. Without the flag the
default stays strict: no benchmark, no entry. The flag never applies to Go or
Zen.

Free models cannot run through the OpenCode Go/Zen proxy: as a harness, Codex
receives `403 FreeTierError` or `429 FreeUsageLimitError` from `opencode.ai`.
Only the direct OpenRouter provider, which talks to `openrouter.ai/api/v1` with
its own key, can use them.

`--include-router-models` adds the two OpenRouter routers
`openrouter/auto` and `openrouter/pareto-code`. They are not models: the price
is variable (`-1` in the API) and there is no benchmark. Codex cannot send
OpenRouter `plugins[]`, so `cost_tier` and `min_coding_score` take effect only
when they are stored account-wide — Workspace → Routing for the Auto Router,
Settings → Tools → Plugins for the Pareto Router. Note that a Pareto
`max_price` overrides `min_coding_score`. The catalog entry carries the note;
the catalog cannot enforce the value.

The picker uses `CODEX_HOME/.tmp/bundled-catalog.json` when it exists. If that
file is absent, it obtains a full model template from `codex debug models
--bundled`, which ignores the configured `model_catalog_json` and therefore
returns the native models instead of the proxy routes.
Pass `--template PATH` to use a specific catalog, `--proxy-url URL` for a
non-default proxy endpoint, or `--codex-bin PATH` for a non-standard Codex CLI.
The default proxy URL follows `OPENCODE_GO_PROXY_PORT` and otherwise uses
`http://127.0.0.1:8787/v1/models`.

The initial working input-price cap was `$0.50/M`. After catalog review it was
lowered to `$0.25/M`, then set to `$0.30/M`, and since 2026-11-05 the default is
the strict cap of `$0.50/M`.
The ordinary
selection requires input price strictly below that cap and a calibrated AA
Intelligence score strictly above `40/100`. The `40` default keeps
`zen/gpt-6-luna` (AA raw 27.8, calibrated ≈ 45.1) selectable with margin, which
is the model the root Codex selection points at; `--min-intelligence-score`
raises it again.
The dated AA snapshot from the
AA Free API is a benchmark-data fallback (not a free-model
price list) and is used only when the live Intelligence population is absent
or all zero; the 60/40 Coding/Agentic composite and OpenRouter Coding fallback
are not used. Every successful live fetch is also written to
`data/artificial-analysis-live-snapshot.json` (rolling, overwritten on the next
build, git-ignored) and used as the first fallback when the live fetch fails for
any reason — missing key, network error, or a rejected response. The dated
snapshot remains the second fallback. `--check` reads but never writes the
rolling snapshot. Intelligence is Min-Max calibrated over all usable values in the
selected AA population before provider prices are applied, with one value per
base model (the highest reasoning level). The price and score
filters therefore run after calibration, and a missing score is never converted
to zero. Each catalog lists a model once per provider route; the reasoning
intensity stays the entry's `supported_reasoning_levels`/`default_reasoning_level`
sub-selection, and effort-suffixed duplicate routes are collapsed. Free-tier
routes of the OpenCode gateway (Go and Zen) are never included: Codex receives
`403 FreeTierError` or `429 FreeUsageLimitError` for them, so they cannot run
outside OpenCode itself. The rule lives in `catalog_rules.is_free_variant` and
matches `-free` routes for `go` and `zen` only. OpenRouter is reached directly
at `openrouter.ai/api/v1` with its own key, so its `:free` models stay eligible
under the normal filter (HTTP 200 measured 2026-11-05) and keep OpenRouter's
own rate limits. The former `user_pinned_free_exception` is gone.

`deepseek/deepseek-v4.1-flash-1017` is the preferred OpenRouter model only if it
passes the normal filters and appears in the generated catalog. Similar-looking
Go/Zen IDs are not treated as the same provider/model route. The Artificial
Analysis Coding Agent Index is a composite distinct from its Intelligence,
Coding, and Agentic indices; it is not used by this picker, and neither it nor
per-task Pareto costs are inferred from the other metrics.

For the full calibration, source definitions, exception policy, and CSV column
meanings, see [METHODOLOGY.md](METHODOLOGY.md). Export the most
recent Codex-home audit with:

```powershell
python tools/codex-picker/export_review_csv.py
```

By default the exporter writes a dated CSV beside this README. It refuses to
overwrite an existing report unless `--overwrite` is supplied.

The current human-review snapshot is
[`provider-selection-review-2026-10-31.csv`](provider-selection-review-2026-10-31.csv).
It contains one row for each evaluated candidate below the input-price cap,
including unselected models and the exact raw index values/provenance in JSON
cells. It predates the full-population score policy and is retained as
historical review evidence. This dated report is a non-live reconstruction from the successful
2026-10-30 audit because the subsequent AA API rebuild was
rate-limited; its provenance is recorded in the audit JSON.

## Windows proxy autostart

`watchdog-proxy.ps1` checks `http://127.0.0.1:8787/health` and starts the proxy
when needed. It prefers the persistently installed `opencode-go-proxy` command
and uses `uv run` from this checkout only as a development fallback. The
installer copies the watchdog into `%LOCALAPPDATA%\opencode-go-proxy\bin` and
configures a current-user logon task plus a five-minute health watchdog. Both
tasks run through `wscript.exe` and the installed `hidden-run.vbs`, which starts
PowerShell with a hidden window and prevents a console flash on each check.
The proxy runs separately from Codex and remains available after Codex closes.
Switching to the proxy with `switch-provider.ps1` also waits for `/health` before
changing Codex configuration. The switcher validates that the target provider
table exists and writes `config.toml` atomically.

Preview task registration without changing Task Scheduler:

```powershell
pwsh -File tools/codex-picker/install-proxy-autostart.ps1 -WhatIf -ReplaceExisting
```

If either legacy task name already exists, the installer refuses to replace it
unless `-ReplaceExisting` is explicitly supplied. Task registration or
replacement is a separate user-run step; building a catalog does not install it.
