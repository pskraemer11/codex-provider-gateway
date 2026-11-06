# Changelog

## Unreleased

### Changed

- **Agent guidance (06.11.2026):** `AGENTS.md` now describes the fork and
  upstream roles without concrete repository URLs. General working, privacy and
  Git rules live in `$HOME/AGENTS.md`; the agent does not push.
- `go_models.py` documents that `mimo-v2.6` without a suffix is not a Go
  model. The gateway answers `Upstream request failed: Model is unavailable.`
  (checked 2026-11-05), while `mimo-v2.6-flash` and `mimo-v2.6-pro` return 200
  with `billing_source: go`. Only those two variants are certified, so the list
  must not grow a third entry on a later rebase.
- Free-tier routes of the OpenCode gateway never enter a generated Go or Zen
  catalog any more. `catalog_rules.is_free_variant` excludes `-free` routes for
  `go` and `zen`; the former `PINNED_FREE_MODELS` /
  `user_pinned_free_exception` path is removed. Reason: Codex as a harness
  receives `403 FreeTierError` or `429 FreeUsageLimitError` from opencode.ai
  (measured 2026-11-05). OpenRouter is reached directly at
  `openrouter.ai/api/v1` and is not affected: its `:free` models answered
  HTTP 200 and stay eligible under the normal filter. The builder counts the
  excluded gateway routes per provider in
  `criteria.free_variants.excluded_counts` and prints the total.
- `INPUT_PRICE_LIMIT` is `$0.50/M` and `MIN_CALIBRATED_SCORE` is `40.0` again.
  Both stay in `catalog_rules.py` rather than in the invocation, so a rebuild
  cannot silently fall back to the previous `$0.30`/`45` values.

### Added

- **actionlint CI:** `.github/workflows/actionlint.yml` checks all GitHub Actions workflows on pushes and pull requests with the pinned official image `rhysd/actionlint:1.7.12`, including shellcheck and pyflakes.
- `--include-router-models` adds `openrouter/auto` and `openrouter/pareto-code`
  as `router_model_exception`: variable price (`-1`, shown as "variabler
  Preis"), no score, ranked after free routes. Codex cannot send OpenRouter
  `plugins[]`, so `cost_tier` and `min_coding_score` only apply when stored
  account-wide; a Pareto `max_price` disables the explicit `min_coding_score`
  threshold but keeps score-based selection at or below that price. The audit
  records `criteria.router_models`.
- `--include-unverified-free` keeps OpenRouter `:free` routes that have a
  verified `$0` input price but no benchmark score. They enter the catalog as
  `selection_reason=unverified_free_exception`, stay `score: null`, and rank
  below scored models. The flag never applies to Go or Zen, which remain
  blocked. Default stays strict: no benchmark, no entry.
- Every successful AA fetch is persisted as a rolling snapshot
  at `tools/codex-picker/data/artificial-analysis-live-snapshot.json`
  (git-ignored, atomically replaced, overwritten on the next build). When the
  live fetch fails for any reason — missing key, network error, rejected
  response — the builder falls back to that snapshot and then to the dated
  snapshot; `--check` reads the rolling snapshot but never writes it. The audit
  records the write (`sources.artificial_analysis.snapshot`), the effective
  fallback, and both snapshot files.
- `ARTIFICIAL_ANALYSIS_LIVE_SNAPSHOT` points the rolling snapshot at another
  path.

### Fixed

- The protocol catalog cache now keys on `mtime_ns` plus file size. Windows file
  times can repeat within one clock tick, so a same-tick rewrite could serve
  stale slugs (the `test_catalog_local` flake). The image-model cache in
  `vision.py` uses the same fingerprint.
- The Windows watchdog now probes the installed `opencode-go-proxy` launcher
  before using it. A stale uv-tool shim fails with
  `ModuleNotFoundError: No module named 'opencode_go_proxy'`; the watchdog
  records that and falls back to `uv run` from the checkout instead of waiting
  60 seconds for a proxy that never starts. This was the cause of the Codex
  Desktop "Reconnection - waiting for network" loop after a reboot or a stopped
  proxy.
- The duplicate-port guard now ignores orphaned TCP entries whose owning process
  no longer exists (PID 0, `TIME_WAIT`), so a restart is not blocked by stale
  sockets left behind by the previous proxy process.
- `--help` now states the actual behaviour of three options: `--template`
  falls back to `codex debug models --bundled` (which bypasses
  `model_catalog_json`), `--no-verify` only applies when writing into
  `CODEX_HOME`, and `--allow-cached-proxy` permits the cached proxy catalog
  without disabling the live/cache consistency check.
- Repository-local Ruff configuration and version pins keep local, hook, and
  CI checks aligned instead of inheriting a parent workspace configuration; test
  import ordering is normalized under the new project root.
- The local test gate now scopes Pytest to `tests`. Safe Ruff modernizations
  replace redundant suffix, timestamp, and dict-value handling, and combine
  deeply nested test context managers.
- Windows scheduled tasks now start the watchdog through `wscript.exe` and the
  installed `hidden-run.vbs` instead of launching `pwsh.exe` directly. This
  restores the console-flash fix for the five-minute health check while keeping
  the current LocalAppData watchdog and autostart repair.
- Codex CLI discovery now ignores a stale `OPENCODE_GO_PROXY_CODEX_BIN`
  override, checks the standard Windows and standalone install locations, and
  falls back to `codex` on `PATH`. Native catalog capture and app-tool capture
  share the same resolution.
- Config backups now reserve their filenames atomically and add a deterministic
  numeric suffix when two backups receive the same timestamp. This prevents a
  fast enable/disable sequence from overwriting an earlier backup on Windows.
- The Windows provider switcher now recognizes provider tables in CRLF
  `config.toml` files. The PowerShell fixture writes CRLF explicitly so this
  compatibility path remains covered.
- `/v1/chat/completions` now rejects Zen Claude, Gemini, and GPT/Grok models
  before any upstream call when their protocol family is not Chat Completions.
- The catalog picker no longer depends on an undocumented bundled catalog:
  it accepts `--template`, uses the Codex temporary catalog when available,
  and otherwise obtains a template from `codex debug models`.
- Picker proxy discovery is configurable with `--proxy-url` and follows
  `OPENCODE_GO_PROXY_PORT`. `--check` now fails unless the proxy is live or
  `--allow-cached-proxy` is explicit.
- The Windows provider switcher validates the target provider table and
  replaces `config.toml` atomically. The watchdog prefers the persistently
  installed proxy command, and the installer places its script in local
  app-data for checkout-independent autostart.
- Health checks accept only a JSON payload with `status: "ok"`, and malformed
  config files with multiple managed END markers are rejected unchanged.
- The runtime-refresh test now resolves checked-in `contrib/` files from the
  repository rather than the process working directory, so the suite is
  independent of where pytest is started.
- The picker README now documents the real catalog location, current API
  credentials, template fallback, live-check behavior, and persistent watchdog
  startup.
- The Codex Picker defines the strict `$0.25/M` input-price cap once and uses
  it for filtering, audit/CSV validation, and displayed criteria. Methodology
  records its history from `$0.50/M` and the one model excluded when the cap
  was lowered.
- Corrected the model-catalog documentation: local `model_catalog_json` uses
  the version-specific Codex `ModelsResponse`; similarly named cache metadata
  is separate internal storage. Desktop “Custom” behavior is not attributed to
  a bare catalog without a matching client/UI reproduction.
- Clarified that the 699-row 2026-10-13 AA snapshot comes from the Artificial
  Analysis Free API endpoint and is only an Intelligence-index fallback, not a
  list of provider models with zero token prices.
- The Codex Picker treats an all-zero AA Intelligence population as unavailable
  and falls back only to a valid dated AA snapshot. Selection now uses the
  calibrated AA Intelligence Index exclusively; the 60/40 Coding/Agentic
  composite and OpenRouter Coding fallback are not used. Intelligence values
  are Min-Max calibrated over all usable values in the selected AA population
  before provider prices are applied, and
  spreadsheet-formula-like CSV cells are escaped.
- `opencode-go-proxy smoke-test` selects a currently advertised `opencode-go/`
  model when no model is supplied, instead of failing against a stale default
  after catalog filtering. `--model` can select an explicit route.

### Added

- Added `PLANUNG.md` with the open proxy findings and HTTP-dispatch regression
  coverage for bare Zen-only Free IDs; the previously expected-failing path is
  now fixed and passing with local fake upstreams.
- `README_de.md` provides a complete German parallel version of the README,
  with language links in both directions.
- Public issue forms for reproducible bug reports and focused feature requests,
  with a template chooser that routes security reports to private advisories.
- CI now includes a Windows job that parses every Picker PowerShell script and
  exercises provider switching and watchdog startup with temporary fixtures.
- Windows proxy lifecycle scripts now live in `tools/codex-picker/`: a logon
  autostart and periodic health-watchdog installer, plus a provider switcher
  that waits for `/health`. All three expose an explicit `-Help` switch, so
  `-Help` and `--help` show detailed comment-based help without exposing the
  previous internal remaining-arguments parameter. The Windows fixture test
  verifies both help forms and each documented option. Task registration remains
  an explicit user action and is not run by this change.
- The provider-catalog builder accepts CLI overrides for the strict input-price
  ceiling and minimum scaled AA Intelligence Index score; defaults are
  `$0.25/M` and a strict score `> 45`.
- Local test gate under `.githooks/`, activated per clone with
  `git config core.hooksPath .githooks`. `pre-commit` runs Ruff and the full
  suite when a staged path starts with `src/`, `tests/`, `contrib/` or
  `scripts/`; `pre-push` always runs both. The prefix check decides whether the
  suite runs, never which tests, so it cannot narrow coverage. Prefixes,
  interpreter and commands live in `.githooks/test-gate.conf`, so the hooks are
  section 3 of the templates in `~/.agents/references/githooks/` without the
  secret scan and domain guard. `GITHOOKS_TEST_GATE=0` skips the gate for
  invocations that start the hook for another purpose, such as a CI privacy
  check. Upstream CI cannot replace this gate because
  its workflow ignores local branches.
- Shared Codex catalog builder under `tools/codex-picker/` for OpenRouter,
  OpenCode Go, Zen, and the combined proxy. The ordinary filter is input price
  `< $0.25/M` and calibrated AA Intelligence score `>45`; the five explicitly pinned free routes
  require verified `$0` input price and remain `unverified` when benchmark data
  is missing. DeepSeek V4.1 Flash 1017 is preferred only when it qualifies.
- `tools/codex-picker/METHODOLOGY.md` documents the calibration and score
  policy; `export_review_csv.py` writes the dated audit as a CSV. The
  2026-10-31 review file contains the evaluated candidates with input-price
  ranges, calibrated scores, selection decisions, raw indices, and provenance.
  It is explicitly marked as a non-live reconstruction because the subsequent
  Artificial Analysis API rebuild was rate-limited; the complete local AA
  snapshot and the one field-name-recovered Intelligence value are recorded.

### Security

- Validate the actual client address and require a separate caller token for
  explicitly enabled non-loopback access.
- Refuse insecure non-loopback startup configurations.
- The Windows provider switcher validates catalog slugs, serializes TOML
  strings safely, and limits reads/writes to unambiguous root-level settings;
  profile and table values are left untouched.

### Changed

- Repository housekeeping: the stale `origin/main` tracking on
  `feat/certify-documented-go-models` was cleared with
  `git branch --unset-upstream`, so feature branches no longer point at the
  read-only upstream. `AGENTS.md` records `fork` as the only push target and
  `origin` as the upstream reference.
- The proxy catalog now orders all `opencode-go/` routes before all `zen/`
  routes; within each group the existing score/price order applies. Codex
  renders the picker from the catalog `priority` field, so the three Go models
  appear first and the five Zen models follow.
- README and README_de now document the Windows watchdog installation end to
  end: installer command, the two scheduled tasks, manual verification, log
  location, and the repair for a stale uv-tool launcher.
- The canonical fork references now use
  `pskraemer11/codex-provider-gateway`, matching the renamed GitHub repository.
  README headings and its catalog summary table are now consistently English.
- Picker calibration now uses the complete usable live AA Intelligence
  population before price filtering, and the default normalized quality
  threshold is `> 45/100`. This prevents the 0–100 scale from being redefined
  by the current set of cheap candidates. The dated AA snapshot follows the
  same rule when used as a fallback. The `45` default keeps `zen/gpt-6-luna`
  (AA raw 27.8, calibrated ≈ 45.1) in the proxy catalog, which is the model the
  root Codex selection points at.
- `config enable` and the Windows provider switcher now emit
  `requires_openai_auth = true` and no `env_key` for `opencode-go`, `zen`, and
  `opencode-proxy`. Codex Desktop refuses plugin toggles with HTTP 432 when the
  active provider is keyed by `env_key`; the proxy ignores the incoming bearer
  either way.
- Native capture reads `codex debug models --bundled` instead of the plain
  command, which renders the configured `model_catalog_json` and reduced the
  native snapshot to zero entries while a proxy catalog was active. The picker's
  template fallback uses the same flag.
- The update check follows the fork release channel
  `pskraemer11/codex-provider-gateway` and falls back to `/tags?per_page=1` when
  the repository has tags but no published GitHub release.
- Bare Zen-only model IDs now pass through the Zen handler after routing selects
  Zen; Go/Zen collisions remain routed to Go.
- The picker labels AA Intelligence scores in model names/descriptions and displays them to one decimal. Pinned Free routes
  show an available score or `unverified`; raw audit precision is unchanged.
- Catalog descriptions read `Auswahl: <reason>` instead of `Auswahlgrund <reason>`,
  and abbreviate the benchmark source as `AA` (transport labels `AA Data API` /
  `dated AA snapshot`). Machine-readable audit values such as
  `benchmark_source=artificial-analysis` and the calibration source keys are
  unchanged.
- The default input-price cap is now `$0.30/M` (strictly below) instead of
  `$0.25/M`; the calibrated AA threshold stays `> 45/100`.
- Threshold reconciliation: the 8-model OpenRouter catalog from the v4.3
  workbook uses `> 50/100`. Against the live v5 population `> 50/100` yields
  only 5 OpenRouter models (3 scored + 2 pinned free), while `> 45/100` yields
  8. The v4.3 count therefore does not transfer to v5. Live-first stays the
  policy; if a future AA population yields too few models, the score threshold
  is the knob to adjust.
- AA values are selected per model family: the highest Intelligence value across
  the reasoning levels (`-low` … `-max`, `-reasoning`, `-non-reasoning`,
  `-minimal`), with one value per base model in the calibration population.
  Previously only the exact slug row counted, which understated models whose
  strongest level is a suffixed variant and double-counted effort variants in the
  Min-Max scale. Product suffixes such as `-pro` remain separate families.
- Each catalog keeps one entry per base model; reasoning intensity stays the
  entry's `supported_reasoning_levels`/`default_reasoning_level` sub-selection.
  A provider that advertises effort-suffixed routes as separate models is
  deduplicated (best score, then lower price, then base slug) and the dropped
  ids are listed in `deduplicated_reasoning_variants` in the audit.
- `--help` now states the accepted format for both selection options:
  `--max-input-price` takes a decimal in USD per 1M input tokens without a
  currency symbol (e.g. `0.30`), `--min-intelligence-score` takes a number from
  0 to 100 on the normalized scale (e.g. `45`).

- Reject unknown or malformed model IDs before routing instead of silently
  substituting `deepseek-v4-flash`.
- `doctor` now follows both setup paths (root `openai_base_url` from
  `config enable`, and root `model_provider` with its
  `[model_providers.<name>]` table from the switcher), fails when the selected
  `model` is absent from `model_catalog_json`, and warns when the active proxy
  provider still sets `env_key`. A provider table decides by its `base_url`, not
  by its name, so a renamed switcher target still passes while a known proxy
  name pointing upstream reports "does not route through the proxy".
  `switch-provider.ps1 -Check` reports a stale catalog and the provider-auth
  shape as well.
- Avoid reverse-DNS lookup delays while starting the local listener.
- Clarify the project's independent, single-user credential and policy boundary.
- Publishing and contribution guidance now identify this fork as the canonical
  repository while preserving upstream attribution. Release automation requires
  an explicit remote and validates every push URL against `project.urls.Repository`.

### Fixed

- Update check: a cache age that comes out slightly negative (filesystem
  timestamps are coarser than `time.time()`) is now clamped to zero instead of
  outranking the freshness window, so a just-written cache is served while
  `OPENCODE_GO_PROXY_UPDATE_TTL_HOURS=0` still disables caching.
- Test suite on Windows: scrubbed environments keep the per-test state dir,
  fake `codex` binaries run through an interpreter shim, and POSIX-only mode
  assertions are guarded, so the suite passes on NTFS as well as on Linux.
- Local fork: the five models certified in `go_models.py` are also present in
  the checked-in seed catalog, and the documented-model counts follow them, so
  the documented set stays a subset of `contrib/opencode-go-models.json`.
- `scripts/make-compact-catalog.py` refuses to shrink the seed catalog: when
  the full-shape input produces fewer models than `contrib/opencode-go-models.json`
  already holds, it exits with a message instead of rewriting the file.
- The documented-catalog test is split into a count check and a seed-coverage
  check, so a half-updated catalog reports both breaks in one run instead of
  revealing them one after the other.
- `tests/test_make_compact_catalog.py` exercises the generator against a
  temporary directory: the shrink guard, genuine growth, a missing target file
  and a full-shape catalog without models. The script accepts its paths as
  arguments so it can be driven without touching `contrib/`.

## Session update (31.10.2026)

Change-review rationale, work state, and the next step are recorded in
[`COMPACTIONS.md`](COMPACTIONS.md).

| Date   | File                                             | Change                                                                   |
| ------ | ------------------------------------------------ | ------------------------------------------------------------------------ |
| 31.10. | `tools/codex-picker/watchdog-proxy.ps1`          | **added:** hidden health watchdog starts this checkout independently.    |
| 31.10. | `tools/codex-picker/install-proxy-autostart.ps1` | **added:** opt-in logon and five-minute health tasks with WhatIf.        |
| 31.10. | `tools/codex-picker/switch-provider.ps1`         | **added:** proxy target requires health before config change.            |
| 31.10. | Picker rules, builder, exporter, and tests       | **changed:** one strict `$0.25/M` cap drives selection and reporting.    |
| 31.10. | Picker methodology and READMEs                   | **docs:** price history, AA snapshot, Windows lifecycle, catalog schema. |
| 31.10. | `CHANGELOG.md`                                   | **docs:** corrects the unsupported ModelsCache requirement claim.        |

## [0.4.10] - 2026-08-14

## [0.4.8] - 2026-08-14

### Added

- `opencode-go-proxy update` command: checks the latest GitHub release
  (`--json` for machines, exits 3 when an update exists), and `update --apply`
  re-installs a `uv tool` install from the newest tag or prints the exact
  pinned `uvx` one-liner otherwise. Never touches a running proxy.
- Menu bar pin bumped to `@v0.4.8`; version strings across the package now
  read 0.4.8.

## [0.4.7] - 2026-08-14

### Added

- `GET /version` (and `/v1/version`): the running version, git commit, and an
  update block checked against the latest GitHub release (24-hour TTL cache
  under the state dir, `?force=1` bypasses it). `GET /state` gains `version`
  and `update` fields; older clients are unaffected.

## [0.4.6] - 2026-08-14

### Added

- `scripts/make-release.py`: one-command release (bump, changelog section,
  commit, tag, push; `--dry-run` prints the plan). CHANGELOG anchor links,
  PUBLISHING.md refreshed, README gains an Updating section covering the menu
  bar, the `update` CLI, and manual/systemd installs.

## [0.4.5] - 2026-08-14

### Added

- Menu bar update support: a Version row, an Update Available row with a
  one-click apply (confirm → new pin saved → proxy restarts), Check for
  Updates, and a UserDefaults pin override so proxy updates no longer require
  rebuilding the menu bar app.

## [0.4.4] - 2026-08-14

### Fixed

- Catalog self-cleaning: a bare OpenCode Go slug the gateway rejects twice with
  `ModelError: not supported` is hidden from the picker (two-strike rule,
  in-memory per process lifetime; a later successful turn restores it).

## [0.4.3] - 2026-08-14

### Fixed

- Streaming fallback: when Go rejects an unknown model before the first
  streamed event, the identical request is re-dispatched through Zen and the
  Zen stream is relayed.

## [0.4.2] - 2026-08-14

### Fixed

- Non-streaming fallback: when Go answers `ModelError: not supported` for a
  bare slug that Zen serves, the identical request is retried through Zen and
  the Zen response (or error envelope) is returned. Go keeps ownership of
  colliding slugs it actually serves.

## [0.4.1] - 2026-08-14

### Fixed

- Zen-only bare slugs route to Zen, and Zen rows that collide with Go display
  names get a `(Zen)` suffix in the catalog so the picker stays unambiguous.
  Bare collisions both catalogs share keep routing to OpenCode Go.

## [0.4.0] - 2026-08-14

### Added

- OpenCode Zen support: the proxy now serves both OpenCode Go and OpenCode Zen.
  Zen models are auto-discovered from `https://opencode.ai/zen/v1/models` (no
  auth), merged with models.dev metadata, and appear in the catalog and
  `/v1/models` as `zen/<id>` slugs. Requests route per family — claude/qwen to
  Anthropic Messages (`/zen/v1/messages`, `x-api-key`), gemini to the Gemini API
  (`/zen/v1/models/<id>`, `x-goog-api-key`), gpt/grok to the Responses API
  (`/zen/v1/responses`, relayed verbatim), everything else to
  chat/completions — with each family's stream translated back to one uniform
  Responses stream. Auth uses the same key as Go
  (`OPENCODE_GO_API_KEY` / `opencode-go-api-key` keychain) with the header
  mapped per family. Zen turns meter with `provider="zen"` so they never count
  against the Go quota. Free models (`deepseek-v4-flash-free`, `mimo-v2.5-free`,
  `big-pickle`) need no credits.
- Usage in the menu bar: `GET /state` gains `usage.go` (OpenCode Go usage
  polled from `https://opencode.ai/zen/go/v1/usage` with a 60s TTL, `null` on
  fetch failure), `usage.goLimits` (fixed Go dollar budgets: $60/month,
  $30/week, $12 per rolling 5 hours), and `usage.zen` (today's turns/tokens and
  a seven-entry last-7-day token rollup from the local meter), alongside the
  existing all-provider keys.

## [0.3.1] - 2026-08-14

### Fixed

- Catalog `availability_nux` is emitted in the `{message: string} | null`
  object form the Codex app schema expects instead of a bare string;
  string-form nux arriving from upstream records is normalized, with empty
  strings mapped to `null`.

## [0.3.0] - 2026-08-13

### Added

- Native model coexistence: models from your logged-in Codex account
  (`codex debug models`, filtered of every `opencode-go/` slug) are merged
  with the OpenCode Go catalog and served by `/v1/models`. Native slugs route
  verbatim to `https://chatgpt.com/backend-api/codex`
  (`OPENCODE_GO_PROXY_NATIVE_BASE_URL` overrides); everything else translates
  to OpenCode Go as before. Official OAuth and API setups are untouched.
- App tool capture: `codex_app` tool definitions are snapshotted via
  `codex debug prompt-input` and merged into session-spawn requests
  (`contrib/codex-app-tools.json` fallback); `web_search_preview` translates
  to a chat function instead of being dropped.
- Compaction requests with query strings now route correctly (404 fixed).
- Multi-agent config v2 (`multi_agent_version: "v2"`) with agent sync, an
  `install-skills` ops command, and a `refresh-runtime` command (native
  recapture + merged re-render) that the menu bar's Refresh Catalog calls.
- macOS launchd agent removed (`contrib/launchd/`); the menu bar app owns the
  proxy process on macOS.

### Changed

- `MODEL_ALIASES` is gone: unknown non-native slugs fall back to the default
  model, same as before.
- Meter events carry a `provider` tag (`native` vs `opencode-go`).


- Ops contracts match the codex-router reference (plan 010): `smoke-test` posts
  a marker prompt through the local proxy at `http://127.0.0.1:8787/v1/responses`
  and asserts the marker comes back (custom base via `--base-url` or
  `OPENCODE_GO_PROXY_BASE_URL`); `support-bundle` emits a single JSON document
  (schemaVersion 1, mode 0600) with version, generatedAt, env summary, redacted
  config snapshot, meter tail, log tail, catalog model count, and doctor checks
  instead of a tar.gz; `doctor` gains reference-style `ok`/`warn`/`fail` checks
  (config file presence, catalog readability, port free/owned, log writability,
  best-effort upstream reachability) plus `--fix`, which repairs only what is
  safe without writing config.toml.
- Session-model inheritance matches the reference (plan 009): only
  `create_thread` calls get the session model injected and
  `chatgptWorkCloud` targets are skipped; `send_message_to_thread` is no
  longer rewritten.
- Catalog discovery sends an identifying `User-Agent`
  (`opencode-go-proxy/<version>`) because models.dev answers 403 to
  urllib's default UA (plan 009).
- Image routing (plan 009): a non-tools image turn keeps the requested
  model when the catalog marks it image-capable (`input_modalities`
  contains `image`), otherwise it falls back to `CODEX_IMAGE_MODEL` /
  `mimo-v2.5`; the image-plus-tools caption path is unchanged.
- Image fallback (plan 009b): when the upstream rejects a non-tools image
  turn at runtime with a caption-fallback 4xx (400/404/415/422), the proxy
  captions the images through the vision module and retries the same
  requested model once instead of failing the turn. The split-turn
  (image plus tools) caption path and the verbatim `/chat/completions`
  passthrough are unchanged.
- Usage meter events now match the codex-router reference schema (plan 008):
  `at` is ISO 8601 UTC, token and duration fields are camelCase
  (`inputTokens` / `outputTokens` / `totalTokens` / `durationMs`), and every
  event carries `meteringVersion: "opencode-go-proxy/1"` plus
  `provider: "opencode-go"`. The legacy snake_case/epoch spelling was dropped
  rather than double-written because no live consumer reads the file today
  (the menu bar is reworked in a later plan); if a consumer needs the old
  fields, they return additively.

- Rate-limit harvesting (plan 011): OpenAI-style (`x-ratelimit-*`) and
  Anthropic-style (`anthropic-ratelimit-*`) response headers from upstream 200s
  are parsed into per-provider quota snapshots (`limit` / `remaining` / `resetAt`
  / `sampledAt`), the latest snapshot per provider is kept, and persisted
  atomically to `quota-state.json` in the state dir. `GET /quota` (and
  `/v1/quota`) returns the state; a headerless upstream degrades to an empty
  snapshot.
- Config manager (plan 012): `config enable|disable|status [--json]` owns a
  marker-commented block in `~/.codex/config.toml` (`# BEGIN
  opencode-go-proxy-managed` to `# END opencode-go-proxy-managed`). Enable
  writes `openai_base_url` plus `model_catalog_json` (state-dir catalog) and
  refuses to replace user-owned values; disable removes only the block and
  deletes the file when the block was its only content. Codex Voice realtime
  keys (`experimental_realtime_webrtc_call_base_url` and
  `experimental_realtime_ws_base_url`) are added only when the user has not
  set them, so Voice stays on native endpoints. Tests and CI run against a
  temp file via `OPENCODE_GO_PROXY_CONFIG_PATH`; the real config.toml is a
  gated deploy step.

### Added

- Base-URL overrides (plan 010): the upstream chat base resolves as the
  `--chat-base-url` flag, then `OPENCODE_GO_BASE_URL`, then
  `OPENCODE_ZEN_BASE_URL`, then the legacy `CHAT_COMPLETIONS_BASE_URL`, then the
  built-in default.
- Ops install/status (plan 010): `install` and its `setup` alias copy the
  launchd plist into `~/Library/LaunchAgents` and load the agent on macOS,
  gated on an explicit `--yes` flag (running it is a deploy step); `status`
  reports running state, port ownership, launchd state, and log paths.
- Doctor/keychain seam (plan 010): `secrets.api_key_source()` reports where the
  key would resolve (env or keychain service) without reading the value, so
  doctor never prints the credential.
- Correctness contract (plan 007): an upstream 200 that streams no
  text, tool call, or reasoning is retried once with the identical request
  (terminal events held, ids reused); a second empty stream answers
  `response.error` code `empty_completion`. Upstream `input_tokens: 0` is
  estimated as `max(1000, ceil(prompt_bytes / 3.3))` capped at the model's
  context window and surfaced as `estimatedInputTokens` (kill switch
  `OPENCODE_GO_PROXY_ESTIMATE_ZERO_INPUT=0`; self-disables once the upstream
  reports real tokens again). The keepalive comment thread now runs until the
  stream truly ends, with writes serialized so comments never interleave into
  data frames.
- Auth transport guard (plan 006): zero-config protection for the loopback
  listener - a missing Host header answers `400 invalid_host`, a non-loopback
  Host answers `403 invalid_host` unless `OPENCODE_GO_PROXY_ALLOW_REMOTE=1`,
  requests carrying Origin / Referer / Sec-Fetch-Site answer
  `403 browser_request_rejected`, non-JSON POSTs to the API paths answer
  `415 unsupported_media_type`, and OPTIONS stays unhandled so browser
  preflight is blocked.
- Protocol surface (plan 005): `/v1/chat/completions` (and `/chat/completions`)
  is a verbatim passthrough - non-stream relays the upstream status and JSON
  body byte-for-byte (including the upstream's own error body), stream relays
  the upstream SSE unchanged with the same 15s keepalive comment mechanism the
  responses stream uses and stops on client disconnect; `/v1/messages` (and
  `/messages`) answer an explicit `400 invalid_request_error`; the WebSocket
  426 rejection now has a test asserting the exact response body.
- Vision bridge module (plan 004): `vision.describe()` returns structured
  `Evidence` (summary / text / layout / unreadable); the caption engine auto-picks the
  cheapest image-capable catalog model or a probed local runtime (Ollama, llama.cpp
  server, LM Studio); non-cached caption reads are metered with `kind=vision`; the old
  caption path now lives entirely in `vision.py`.
- Catalog contract with overlay and runtime reload (plan 003): `render_full_catalog`
  projects each model through the canonical key set Codex reads in
  `merged-models.json` (`multi_agent_version` at the model top level, plus
  `comp_hash`, `availability_nux`, and `approvals`/`collaboration_modes`/
  `permissions`/`token_budget`/`auto_review` in `model_messages`), backed by a
  key-set parity test against a sampled fixture.
- Runtime catalog lives under the state dir (`OPENCODE_GO_PROXY_STATE_DIR`,
  default `~/.codex/opencode-go-proxy/`); refresh never writes the repo's
  `contrib/` files, and startup renders the state-dir compact (or the seed)
  instantly while discovery runs in the background.
- `known_models()` replaces the frozen `KNOWN_MODELS`: the live slug set is
  cached by catalog file mtime, so `/v1/models` and model routing pick up a
  refreshed catalog without a restart (`reload_known_models()` forces it).
- User overlay for custom models: `user-models.json` (add / hide / edit display)
  plus hidden-model flags from `model-picker.json`, seven-day `availability_nux`
  announcements tracked in `announced-models.json`.
- Menu bar state contract (plan 013): `GET /state` (and `/v1/state`) returns
  one JSON document - `status`, `port`, `upstream`, the latest quota snapshot
  by `sampledAt` (`{provider, remaining, limit?, resetAt?}` or `null`),
  `usage` with `todayTurns` / `todayTokens` / a stable seven-entry `last7d`
  token list (local calendar days, oldest first), and `model` (most recent
  meter event, else the default). A missing or corrupt meter/quota file
  degrades to zeros or `null`. The Swift menu bar renders the Standard tier
  from that contract: quota card with reset countdown, today's turns/tokens,
  a 7-day usage bar list, and model/upstream rows, keeping the single-port
  guard and existing controls.

## [0.2.0] - 2026-08-10

### Added

- Prefix-cache support for OpenCode Go models: streaming requests now set
  `stream_options.include_usage`, the proxy parses the upstream's cache accounting
  (`prompt_cache_hit_tokens` / `prompt_tokens_details.cached_tokens`), surfaces it to
  Codex in `usage.input_tokens_details.cached_tokens`, logs it per request, and
  exposes aggregate hit/miss/ratio on a `/cache` (and `/metrics`) endpoint.
- `CacheTracker` in `src/cache.py`: thread-safe per-model hit/miss/ratio accounting.
- Key resolution falls back to `OPENCODE_API_KEY` and the `codex-router-opencode-go`
  keychain service, in addition to `OPENCODE_GO_API_KEY` / `opencode-go-api-key`.
- Spawned threads inherit the session model: `create_thread` and
  `send_message_to_thread` function calls get the parent thread's model injected
  when the caller omits one.
- Honest usage meter in `src/meter.py`: append-only `usage-events.jsonl` in the state
  dir with per-turn status, duration, tokens and retries. Truncated streams record
  `streamAborted` and never count as success; empty completions record
  `emptyCompletion`. Metering failures never break a live request.
- Upstream retry with bounded exponential backoff on transient failures
  (429/5xx/network/timeout), configured via `OPENCODE_GO_PROXY_MAX_RETRIES`
  (default 2) and `OPENCODE_GO_PROXY_RETRY_BASE_MS`.
- Ops CLI commands: `opencode-go-proxy doctor` (self-check), `smoke-test` (real
  upstream probe) and `support-bundle` (namespaced tarball of logs, config and
  meter, with secret values redacted).
- Agent skill `skills/opencode-go-proxy/SKILL.md`: orientation for operating the
  proxy (start/stop, ops commands, prefix caching, config, reliability).
- Caption latency: identical screenshot bytes are captioned once per hour (in-process
  byte-keyed cache, 256-entry bound), so repeat tool calls on the same screen skip the
  upstream round trip.
- Caption engine: `OPENCODE_GO_PROXY_CAPTION_MODEL=auto` picks the cheapest
  image-capable catalog model (an enabled local runtime first);
  `CODEX_IMAGE_MODEL` overrides, and `mimo-v2.5` is the fallback when the picked
  engine rejects image input (4xx).
- Caption images are sent with `detail: low` (`OPENCODE_GO_PROXY_CAPTION_DETAIL=none`
  disables); if the upstream rejects the detail value, the proxy retries once with a
  `sips`-downscaled JPEG (or the original URL) and no detail.
- Tests: cache parsing (both DeepSeek and OpenAI usage shapes), tracker accounting,
  `/cache` endpoint, streaming `stream_options`, cache passthrough to Codex,
  meter recording, upstream retry behavior, and the ops commands.

### Changed

- Native macOS menu bar app in `macos/MenuBarApp` (Swift/AppKit, SwiftPM): short status
  icon, live health check, start/stop of the proxy as a child process, open logs,
  reveal log file, copy port. It refuses to Start when port 8787 is already owned
  (single-port guard). Build with `swift build` in `macos/MenuBarApp` (macOS 13+).
- README: document that the proxy exposes a single HTTP port (`OPENCODE_GO_PROXY_PORT`,
  default 8787) with no admin/control channel, how to verify what is listening
  (`lsof -nP -iTCP:8787 -sTCP:LISTEN`), and how to shorten the Codex provider label
  (edit `[model_providers.opencode-go] name` in `~/.codex/config.toml`).

### Fixed

- zstd request bodies: the Codex desktop app sends `/v1/responses` bodies
  zstd-compressed whenever it is authenticated; the proxy now decompresses
  `Content-Encoding: zstd` (and gzip) so the desktop app works. Unsupported
  encodings return an explicit 400 instead of crashing on a magic byte.
- The reference catalog `contrib/opencode-go-catalog.json` was extended with
  `fetched_at`, `etag`, and `client_version` metadata. This was originally
  described as a required `ModelsCache` wrapper for Codex 0.142+ Desktop, but
  that requirement and its causal link to the “Custom” label were not supported
  by the versioned Codex `ModelsResponse` source; see the corrected model-catalog
  guidance in the current README.
- SIGTERM graceful shutdown: `serve_forever` now runs on a background thread so the signal
  handler's `server.shutdown()` no longer deadlocks on the main thread, leaving the process
  unkillable via SIGTERM (launchd/systemd stop, menu bar Stop).
- WebSocket upgrade requests (Codex desktop app realtime) are answered with an explicit
  `HTTP/1.1 426 Upgrade Required` instead of the previous HTTP/1.0 404, which surfaced as
  "WebSocket protocol error: HTTP version must be 1.1 or higher" before the app fell back
  to HTTP streaming.
- Image caption budget: default timeout 60s -> 30s, and caption sub-calls no longer
  retry transient failures, so a bad caption leg costs at most ~30s instead of stacking
  retries.

## [0.1.2] - 2026-06-21

Bug fixes + removed AUR packaging.

### Fixed

- `call_upstream_chat` now catches `json.JSONDecodeError` — invalid JSON from upstream returns 502 instead of crashing
- Streaming crash: if `handle_streaming_request` raised after SSE headers sent, sends `response.error` SSE event instead of corrupted HTTP response
- Streaming + missing API key: `resolve_api_key` moved before `response.created` so error event reaches client
- README launchd path: `~/Library/.codex/logs` → `~/.codex/logs` (matches plist)
- LICENSE copyright year 2025 → 2026

### Removed

- AUR package (`aur/opencode-go-proxy-git/`) — not launching on AUR
- PyPI — not launching on PyPI; `uvx --from git+...` is the install path

## [0.1.1] - 2026-06-21

Graceful shutdown + launchd service file.

### Added

- SIGTERM handler for graceful shutdown on `launchctl bootout` / `systemctl stop`
- launchd plist at `contrib/launchd/com.opencode-go.proxy.plist`
- README: launchd setup instructions with copy + bootstrap commands

## [0.1.0] - 2026-06-21

Initial public release.

### Added

- Responses `input` to chat `messages` translation
- `instructions` and `developer` roles mapped to system messages
- Function tool schema passthrough
- Custom/freeform tool adaptation (Codex `apply_patch` works)
- `reasoning_content` replay across tool-call turns
- Real-time SSE streaming
- Image captioning via MiMo V2.5 when tools are present
- SSRF protection on image URLs (`data:image/` and `https://` only)
- Configurable body cap, bind address guard
- macOS keychain credential resolution
- Local health and model-list endpoints
- Reference model catalog with all 13 OpenCode Go models
- systemd user service at `contrib/systemd/`
- 41 tests (unit + integration) covering protocol, credentials, HTTP round-trip, alias map, tool calls, streaming tool calls, streaming error handling, streaming crash recovery, invalid upstream JSON, SSRF, and image captioning

### Security

- SSRF validation on image URLs
- Non-negative Content-Length validation
- Generic error messages to client (full bodies only in trace logs)
- No path reflection in 404 responses
- Bind address guard warns on non-localhost

[Unreleased]: https://github.com/pskraemer11/codex-provider-gateway/compare/v0.4.10...HEAD
[0.4.0]: https://github.com/kartikkabadi/opencode-go-proxy/releases/tag/v0.4.0
[0.3.1]: https://github.com/kartikkabadi/opencode-go-proxy/releases/tag/v0.3.1
[0.3.0]: https://github.com/kartikkabadi/opencode-go-proxy/releases/tag/v0.3.0
[0.1.2]: https://github.com/kartikkabadi/opencode-go-proxy/releases/tag/v0.1.2
[0.1.1]: https://github.com/kartikkabadi/opencode-go-proxy/releases/tag/v0.1.1
[0.1.0]: https://github.com/kartikkabadi/opencode-go-proxy/releases/tag/v0.1.0
[0.4.8]: https://github.com/kartikkabadi/opencode-go-proxy/releases/tag/v0.4.8
[0.4.7]: https://github.com/kartikkabadi/opencode-go-proxy/releases/tag/v0.4.7
[0.4.6]: https://github.com/kartikkabadi/opencode-go-proxy/releases/tag/v0.4.6
[0.4.5]: https://github.com/kartikkabadi/opencode-go-proxy/releases/tag/v0.4.5
[0.4.4]: https://github.com/kartikkabadi/opencode-go-proxy/releases/tag/v0.4.4
[0.4.3]: https://github.com/kartikkabadi/opencode-go-proxy/releases/tag/v0.4.3
[0.4.2]: https://github.com/kartikkabadi/opencode-go-proxy/releases/tag/v0.4.2
[0.4.1]: https://github.com/kartikkabadi/opencode-go-proxy/releases/tag/v0.4.1

[0.4.10]: https://github.com/kartikkabadi/opencode-go-proxy/releases/tag/v0.4.10
