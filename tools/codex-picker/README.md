# Codex provider catalog builder

This tool generates Codex catalogs filtered by price and benchmark for OpenRouter,
OpenCode Go, OpenCode Zen, and the combined Go/Zen proxy.
It selects a minimum quality and a maximum input price, making it a fixed point on the Pareto frontier.

If you want a different point that is optimal for you, simply create a known catalog.
It is saved along with the proxy, since the combined desktop catalog depends on the routes announced
by the proxy.

The Windows PowerShell provider switcher, proxy health watchdog, and Task
Scheduler installer now live here. See [Windows proxy autostart](#windows-proxy-autostart).

From this repository root, run:

```powershell
python tools/codex-picker/build_provider_catalogs.py --check
python tools/codex-picker/build_provider_catalogs.py
```

`--check` fetches source data and validates the selection without writing
catalogs. A write to the active Codex home requires a reachable local proxy;
generated catalogs are backed up before replacement, and the Codex loader is
verified after writing. API credentials are read only from
`ARTIFICIAL_ANALYSIS_API_KEY`, `OPENROUTER_API_KEY`, and optionally
`OPENROUTER_MANAGEMENT_KEY` environment variables.

The initial working input-price cap was `$0.50/M`. After catalog review it was
lowered to the current strict cap of `$0.25/M`, excluding one model. The ordinary
selection requires input price strictly below that cap and a calibrated AA
Intelligence score strictly above `70/100`. The dated AA snapshot from the
Artificial Analysis Free API is a benchmark-data fallback (not a free-model
price list) and is used only when the live Intelligence population is absent
or all zero; the 60/40 Coding/Agentic composite and OpenRouter Coding fallback
are not used. Intelligence is Min-Max calibrated over the price-eligible
candidate population; a missing score is never converted to zero. Five explicitly requested free routes are included only
when their provider source confirms `$0` input price, and remain marked
`unverified` when no benchmark is available:

- OpenRouter: `cohere/north-mini-code:free`, `openrouter/free`
- Zen: `glm-5.3-flash-free`, `deepseek-v4.1-flash-free`,
  `mimo-v2.6-flash-free`

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
cells. The five selected free routes have blank scores and an explicit exception
reason. This dated report is a non-live reconstruction from the successful
2026-10-30 audit because the subsequent Artificial Analysis API rebuild was
rate-limited; its provenance is recorded in the audit JSON.

## Windows proxy autostart

`watchdog-proxy.ps1` checks `http://127.0.0.1:8787/health` and starts the proxy
from this repository checkout with `uv run` when needed. The installer configures
a hidden current-user logon task plus a five-minute health watchdog. The proxy
runs separately from Codex and remains available after Codex closes. Switching
to the proxy with `switch-provider.ps1` also waits for `/health` before changing
Codex configuration.

Preview task registration without changing Task Scheduler:

```powershell
pwsh -File tools/codex-picker/install-proxy-autostart.ps1 -WhatIf -ReplaceExisting
```

If either legacy task name already exists, the installer refuses to replace it
unless `-ReplaceExisting` is explicitly supplied. Task registration or
replacement is a separate user-run step; building a catalog does not install it.
