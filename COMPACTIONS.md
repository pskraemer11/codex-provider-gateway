# Compactions

=============== Compaction 31.10.2026 / 14:13 ================
## Objective
- **Current:** Move Windows proxy lifecycle into this repo, make the Go/Zen switch path health-aware, centralize the Picker cap, and correct the catalog-schema guidance.
- **Completed:** Added watchdog, opt-in Task Scheduler installer, and provider switcher under `tools/codex-picker`; centralized strict `$0.25/M`; updated docs and AA snapshot interpretation.

## Important Details
- **Decisions:** Autostart is for the interactive Windows user at logon, with a detached proxy and five-minute health check. This also covers CLI `--profile go/zen` without relying on the Desktop switcher. Task registration, config switching, model inference, and GitHub push were not performed.
- **Catalog research:** Local CLI is `codex-cli 0.166.0`; `model_catalog_json` follows version-matched `ModelsResponse`, while `ModelsCache` is separate internal cache storage. The Desktop picker behavior on this machine is unverified. See [README.md](README.md) and [Codex catalog docs](https://learn.chatgpt.com/docs/model-catalogs).
- **AA snapshot:** The selected 2026-10-13 file has 699 records from AA `/language/models/free` (`tier=free` API metadata), not a free-price model list. The repo `.lnk` is not read by Python; the current ancestor lookup finds the sibling JSON. `--aa-snapshot` overrides it.
- **Price policy:** Historical cap `$0.50/M` was reduced to strict `<$0.25/M`, excluding one model. `catalog_rules.INPUT_PRICE_LIMIT` is now the source used by filtering, audit/CSV, and displayed criteria.
- **Review finding (P2):** `switch-provider.ps1` accepts a catalog `slug` without a safe-character check and interpolates it into a TOML string/replacement. A crafted catalog value could alter config on an explicit switch. Validate/escape slugs before public use.

## Work State
### Completed / Active / Blocked
- Completed: 48 focused Picker tests passed; full suite had 1,013 pass, 6 skipped, and one unrelated backup-count failure that passed when rerun alone. Ruff check passed. PowerShell parser passed for all three scripts; installer and watchdog WhatIf previews passed without task registration or proxy start.
- Active: A bounded real-live test remains for the user. No live provider call or catalog build was run. The full suite was not repeated after the isolated pass.
- Gaps: Ruff format check flags two pre-existing formatting hunks; `git diff --check HEAD` flags trailing whitespace in user-edited README lines. No independent reviewer, actual Windows task registration, Desktop picker UI test, or model inference was performed.

## Next Move
1. For a read-only live source check, start the proxy with `pwsh -NoProfile -File .\tools\codex-picker\watchdog-proxy.ps1 -Port 8787`, verify `/health`, then run `python .\tools\codex-picker\build_provider_catalogs.py --check`. For one real routed prompt, `uv run --project . --locked opencode-go-proxy smoke-test` consumes OpenCode Go quota. Before public use, resolve the slug-escaping finding and obtain independent review.

## Relevant Files
- `tools/codex-picker/watchdog-proxy.ps1`: health/start behavior for the current checkout.
- `tools/codex-picker/install-proxy-autostart.ps1`: explicit task registration/removal; never run in this session.
- `tools/codex-picker/switch-provider.ps1`: Desktop root-config provider switch and health gate.
- `tools/codex-picker/catalog_rules.py`, `build_provider_catalogs.py`, `export_review_csv.py`: shared price cap and display/audit use.
- [CHANGELOG.md](CHANGELOG.md): file-level update summary.

## Important Context
- Worktree already contained staged and unstaged user edits. They were preserved; no unrelated paths were staged, reset, or reverted.
- The new PowerShell files remain untracked, and the Task Scheduler tasks remain as they were before the WhatIf preview.

=============== Compaction 31.10.2026 / Publishing-Dokumentationsreview ================
## Objective
- **Current:** Check repository identity, publishing instructions, and contributor guidance for consistency before publishing the Picker-enhanced fork.
- **Completed:** Read-only review of `PUBLISHING.md`, `README.md`, `CONTRIBUTING.md`, `pyproject.toml`, the Picker README, and `scripts/make-release.py`; compared configured Git remotes and the public GitHub fork page.

## Findings
- The GitHub repo is still correctly marked as forked from `kartikkabadi/opencode-go-proxy`; retaining that provenance link is appropriate, even though this checkout adds a distinct Picker/autostart scope.
- The current clone has `fork` pointing to `pskraemer11/opencode-go-proxy` and `origin` pointing to the upstream `kartikkabadi/opencode-go-proxy`.
- `PUBLISHING.md`, all three `pyproject.toml` project URLs, README CI/install/update/systemd/release links, and the CONTRIBUTING clone command still point to upstream. `CONTRIBUTING.md` does not currently document this fork as its checkout target and tells readers to fork again.
- `CONTRIBUTING.md` says “stdlib only (no dependencies)” although `pyproject.toml` declares `zstandard>=0.22`; it also omits Picker/Windows workflow setup.
- **P1 release blocker:** `scripts/make-release.py` hard-codes `REMOTE = "origin"` and a release-anchor URL under the upstream repo. Its release path commits, tags, and pushes `main` and the tag to that remote. In this checkout, that means the release automation targets upstream, not the user's fork. Do not run it until its destination is made explicit and verified.
- Review verdict: **Block** for release/publication readiness until canonical links and release destination are corrected. This review did not alter the docs or release script; only this compaction was appended.

## Validation and Next Move
- Read-only evidence: `git status -sb`, `git remote -v`, document/source inspection, and the public GitHub fork page. No tests or push were run.
- Next: with user authorization, update canonical repo links and contributor setup, make release target selection safe, then verify with focused release-script tests and a dry-run that does not push.

=============== Compaction 31.10.2026 / Implementation und Change Review ================
## Objective
- **Current:** Resolve the reviewed publication/link inconsistencies, harden release destination selection, and fix the provider-switcher catalog-slug injection finding.
- **Completed:** Updated repository-facing docs and metadata to the fork, made release destinations explicit and validated, and made switcher TOML writes safe and root-scoped.

## Resolved Findings
- Release automation now requires `--remote`, validates every configured push URL against `project.urls.Repository`, derives release links from that repository, and recognizes both `## Unreleased` and `## [Unreleased]` changelog headings.
- `README.md`, `CONTRIBUTING.md`, `PUBLISHING.md`, package URLs, and the Changelog's Unreleased comparison identify this fork as canonical while retaining the original repo as upstream attribution. Historical release links remain attached to upstream releases.
- Contributor setup now clones this fork, documents `zstandard`, the actual verification commands, the optional local hook, and the checkout-only Picker/Windows tools.
- The switcher rejects non-string, empty, oversized, and control-character slugs; JSON/TOML-safe serialization and literal string replacement prevent interpolation. Reads/writes are restricted to unique root-level assignments, including directly quoted keys; profile tables and multiline string content remain unchanged.

## Verification and Review
- `tests/test_make_release.py`: 12 passed; `uvx ruff check scripts/make-release.py tests/test_make_release.py`: passed.
- `scripts/make-release.py 0.4.11 --remote fork --dry-run`: selected `github.com/pskraemer11/opencode-go-proxy`, showed the correct Changelog insertion and release anchor, and wrote nothing.
- The prior switcher injection was reproduced against a disposable config before the fix. After the fix, PowerShell parsing and a temporary-config smoke passed: bare/single-quoted/double-quoted root keys, multiline text, `$&` in the config path, and profile values were preserved; Python `tomllib` parsed the result; the newline-injection slug was rejected without changing config.
- Final scoped Change Review: **Looks good**. No remaining P1-P3 findings in this scope. The full application suite and live Go/Zen provider inference were not run; no task registration, real Codex config change, release, commit, or push occurred.

## Worktree Preservation / Next Move
- Existing staged and unstaged Picker edits and generated CSV/XLSX/snapshot artifacts were preserved; no staging or cleanup was performed. `tests/test_make_release.py` is a new focused regression test file; no persistent switcher test file was added.
- Next: the user's separate Smoke-Live provider check can exercise the running integration; it was intentionally left to the user and no provider quota was consumed here.

=============== Compaction 02.11.2026 / 17:27 ================
## Objective
- **Current:** Review why OpenCode Go and Zen models appear in the catalog but allegedly do not connect through the local proxy.
- **Completed:** Read-only source, runtime, log, config, catalog, test, and documentation review; no provider request was initiated for this review.

## Important Details
- **Current routing bypass (P1 setup defect):** Codex currently uses `model_provider = "openrouter"` and `picker-catalog.json`; `openai_base_url` is unset and `config status` reports disabled. A displayed catalog therefore does not imply proxy traffic. Backups show the proxy was active at 15:55 and OpenRouter was restored at 16:08.
- **Go works:** `opencode-go/gpt-6-luna` reached `https://opencode.ai/zen/go/v1/responses` and completed with `opencode-go.done`; metering records HTTP 200. The blanket claim that Go routing cannot connect is disproved.
- **Zen connects but is quota-blocked:** `zen/deepseek-v4.1-flash-free` reached `https://opencode.ai/zen/v1/chat/completions`; OpenCode returned HTTP 429 `FreeUsageLimitError`. This is an account/quota condition, not a failed proxy connection.
- **Bare-Zen defect (P1/P2):** `route_target("gpt-5.6-terra")` can select Zen, but `ensure_zen_slug()` then rejects the same bare slug with HTTP 400. Live log confirms this contradiction. Tests cover routing and prefixed Zen separately, but not app-level dispatch of a bare Zen-only ID.
- **Native capture:** `native-models.json` is empty because `codex debug models` rendered the active OpenRouter catalog. Empty native capture can make bare slugs fall into Zen classification.
- **Setup and diagnostics:** `config enable` and `switch-provider.ps1 -Target proxy` produce different provider states; `doctor` validates `openai_base_url` but not the active `model_provider`. The packaged skill also describes obsolete fallback and non-loopback behavior.

## Work State
### Completed / Active / Blocked
- Completed: Full suite passed (`1043 passed, 6 skipped, 16 subtests`); Ruff check passed. Review findings are documented here.
- Active: No source or Codex configuration was changed.
- Blocked: Implementation awaits an explicit fix request.

## Next Move
1. Add an app-level bare-Zen regression test and normalize or reject the slug at one routing boundary.
2. Make `doctor` and setup guidance validate provider selection, and add a non-empty-capture guard.

## Relevant Files
- `src/opencode_go_proxy/routing.py`, `zen_upstream.py`, `app.py`: contradictory bare-Zen routing.
- `src/opencode_go_proxy/config_manager.py`, `ops.py`, `tools/codex-picker/switch-provider.ps1`: divergent setup and incomplete diagnostics.
- `src/opencode_go_proxy/native_models.py`: empty capture from the active non-native catalog.
- `skills/opencode-go-proxy/SKILL.md`: stale operational contract.

## Important Context
- Review evidence includes local proxy logs, usage metering, config backups, current `config.toml`, state catalogs, and the full test suite. Credentials and raw authorization values were not exposed.

=============== Compaction 03.11.2026 / Provider-Auth, Doctor, Native-Capture, Updater, Schwelle 45 ================
## Objective
- **Current:** Resolve the three runtime findings from the 02.11. review plus the `opencode-proxy` provider-table contradiction and the open `PLANUNG.md` items.
- **Completed:** Provider tables emit `requires_openai_auth`; `doctor` validates both setup paths and the catalogued model; native capture uses the bundled catalog; the update check follows the fork with a tag fallback; the picker threshold is `45`; docs, skill, changelog and PLANUNG are updated.

## Important Details
- **Provider auth:** `config_manager._block_lines` and the switcher's `[model_providers.opencode-proxy]` now set `requires_openai_auth = true` and no `env_key`. Rationale: Codex Desktop refuses plugin toggles with HTTP 432 when the active provider is `env_key`-keyed. `doctor.check_provider_auth` warns for proxy-routed tables only — a direct `opencode-go` table pointing at `opencode.ai` keeps `env_key` legitimately.
- **Doctor config check:** `check_config` parses `config.toml` with `tomllib`, accepts the managed root `openai_base_url` path *and* the switcher path (`model_provider` + table whose `base_url` is loopback:8787), then fails when the selected `model` is absent from `model_catalog_json`.
- **Native capture:** `codex debug models` renders the configured `model_catalog_json` (3 zen-free routes while the proxy catalog was active) and collapsed the native set to 0. `codex debug models --bundled` returns the binary's 12 models; 10 survive the Go-collision filter (`gpt-5.6-luna`, `gpt-6-luna` are Go-owned). The picker's template fallback uses the same flag.
- **Threshold:** `catalog_rules.MIN_CALIBRATED_SCORE = 45.0`. `zen/gpt-6-luna` has AA raw 27.8 → calibrated ≈45.14, so the old `>50` policy dropped the actively selected model from `proxy-catalog.json`. Rebuild produced 8 proxy routes including `zen/gpt-6-luna` and `opencode-go/gpt-6-luna` (47.0).
- **Updater:** release channel is the fork `pskraemer11/codex-provider-gateway`. The fork has tags but no GitHub releases (`/releases/latest` → 404), so `_fetch_latest_release` falls back to `/tags?per_page=1` and synthesizes the tag URL.

## Work State
### Completed / Active / Blocked
- Completed: focused suite `192 passed, 1 skipped`; full suite `1061 passed, 6 skipped, 16 subtests`; `uvx ruff==0.17.3 check .` clean; changed files format-clean; PowerShell fixture tests pass. Live: `proxy-catalog.json` (8), `native-models.json` (10), `merged-models.json` (120 = 78 zen + 32 go + 10 native), `/v1/models` 120, `doctor --json` `ok: true`, `switch-provider.ps1 -Check` ok, `update --force` → up to date against fork tag `v0.4.10`.
- Active: none.
- Blocked: none.

## Verification Notes
- The first full-suite run had one failure, `test_catalog_local.py::test_models_endpoint_grows_after_refresh_without_restart`; it passed alone, in its file, and in the repeated full suite. Cause is the Windows file-time granularity behind `protocol._CATALOG_CACHE`'s `st_mtime_ns` key: two renders inside one timestamp tick share the key. Pre-existing flake, not caused by this change.
- `uvx ruff==0.17.3 format --check .` reports 65 pre-existing unformatted files (e.g. `tests/test_streaming.py`, `tests/test_vision.py`) that were not touched here; the 12 changed Python files are format-clean. The subproject gate runs `ruff check`, not `format --check`.
- `switch-provider.ps1` diagnostics use `Write-Output` so `-Check` output is capturable by the fixture test; `Write-Host` bypassed the pipeline.
- No live model inference was issued (no provider quota consumed). The proxy started for the catalog rebuild was stopped again afterwards.

## Next Move
1. Codex Desktop UI check of the picker with the rebuilt `proxy-catalog.json`; the CLI evidence does not prove UI behaviour.
2. Re-check `COMPACTIONS` claims about quota/logs with current redacted data before acting on them.

## Relevant Files
- `src/opencode_go_proxy/config_manager.py`, `ops.py`, `native_models.py`, `updates.py`: the four code changes.
- `tools/codex-picker/catalog_rules.py`, `build_provider_catalogs.py`, `switch-provider.ps1`: threshold, bundled template, check reporting.
- `~/.codex/config.toml`: `[model_providers.opencode-proxy]` fixed, backup `config.toml.backup-20261103-150702-before-provider-auth`.
- `PLANUNG.md`, `CHANGELOG.md`, `README.md`, `README_de.md`, `skills/opencode-go-proxy/SKILL.md`, picker `README.md`/`METHODOLOGY.md`, `docs/OpenCode Go und Zen in Codex 20261025.md`.

## Important Context
- Unrelated working-tree changes were preserved, including the deletion of `docs/Codex vs. OpenCoden Vergleich bzgl Sicherheit.md` and the modified `zen_upstream.py`, watchdog/installer scripts and `Status Quo … 20261103.md`.
- `staging/fix_proxy_provider.py` is the one-off config script (gitignored directory).

=============== Compaction 03.11.2026 / Katalog-Redaktion, Preis-Default 0.30 ================
## Objective
- **Current:** Editorial pass over the generated catalogs plus a wider default price window.
- **Completed:** `description` uses `Auswahl: <reason>`; visible text and console abbreviate Artificial Analysis as `AA`; `INPUT_PRICE_LIMIT` is `0.30`; `--help` documents the input format of both selection options.

## Important Details
- **Scope of the AA abbreviation:** catalog `description`, transport labels (`AA Data API`, `dated AA snapshot`), `benchmark_source=AA` in the description, builder error messages (`AA: …`), and the picker docs. Machine provenance in the audit stays `artificial-analysis` / `artificial-analysis-data-api` / `artificial-analysis-local-snapshot`, because `export_review_csv.py` and the CSV contract pass those values through unchanged.
- **Default price window:** `catalog_rules.INPUT_PRICE_LIMIT = Decimal("0.30")`, strict `<`. Score policy unchanged at calibrated `> 45/100`. The builder interpolates both defaults into `--help` so the text cannot drift from the constants.
- **Selection effect:** rebuild kept 8 proxy routes (3 go, 5 zen, 8 openrouter). Evaluated cheap candidates grew from 129→149 (OpenRouter) and 14→15 (Zen) without a new qualifying model.
- **Rolling AA snapshot:** every successful live fetch is written atomically to `tools/codex-picker/data/artificial-analysis-live-snapshot.json` (748,054 bytes, git-ignored). `load_aa_population()` owns the order live → rolling snapshot → dated snapshot; `--check` passes `persist_live_snapshot=False`, so the documented "writes nothing" contract holds. The audit gains `sources.artificial_analysis.snapshot` (write receipt), `artificial_analysis_live_snapshot`, and `artificial_analysis_dated_snapshot`.
- **Reasoning levels:** AA rows are grouped by base model (`-low` … `-max`, `-reasoning`, `-non-reasoning`, `-minimal` stripped) and the highest Intelligence value wins, for both the per-model score and the calibration population (live 94 → 47 values). The base slug is not always the strongest level (`gemini-3-5-flash-medium` beat its base in the 2026-10-13 snapshot). Product suffixes such as `-pro` stay separate.
- **One entry per base model:** each catalog lists a model once per provider route; reasoning intensity stays `supported_reasoning_levels`/`default_reasoning_level`. `_dedupe_reasoning_variants()` keys on `(vendor, base)` — `opencode-go/` and `zen/` are distinct billing routes and are not merged — and records dropped ids in `deduplicated_reasoning_variants`. An earlier cross-provider key briefly reduced `proxy-catalog.json` from 8 to 6 models; the corrected key restored 8/3/5/8.
- **Threshold reconciliation:** the user's 8-model OpenRouter catalog is an AA v4.3 figure at `> 50/100`. Live v5 at `> 50/100` gives 5 (3 scored + 2 free), at `> 45/100` gives 8. Live-first is confirmed as policy; the score threshold is the adjustment knob if a future population yields too few models.

## Work State
- Completed: full suite `1079 passed, 6 skipped, 16 subtests`; `uvx ruff==0.17.3 check .` clean; the changed Python files format-clean; live rebuild written to `~/.codex/{picker,go,zen,proxy}-catalog.json` plus `provider-catalog-audit.json` with backups `*.backup-20261103-161902`; proxy catalog 8 entries with no duplicate `(vendor, base)` pair; calibration population 47 models (1.8..59.4); snapshot sha256 `96daf691…` matched the effective fallback; loader verify exit 0.
- Active: none. Blocked: none.

## Next Move
1. Optional: decide whether the audit's machine value `benchmark_source=artificial-analysis` should also become `AA`; that changes the CSV contract.
2. Codex Desktop UI check with the rebuilt catalog.

## Relevant Files
- `tools/codex-picker/catalog_rules.py`, `build_provider_catalogs.py`, `tests/test_codex_picker_selection.py`, `CHANGELOG.md`, `PLANUNG.md`, `README.md`, `README_de.md`, picker `README.md`/`METHODOLOGY.md`.

=============== Compaction 05.11.2026 / 17:57 ================
## Objective
- **Current:** Free-Tier-Modelle aus allen Katalogen entfernen, Schwellen auf Input < `$0.50/M` und Score > `40/100` zuruecksetzen, Kataloge neu bauen.
- **Completed:** Free-Regel plus Test, Pinning-Ausnahme entfernt, vier Kataloge neu geschrieben, Codex-Thread-Reparatur abgeschlossen.

## Important Details
- **Decision:** Free-Routen sind im Harness grundsaetzlich unbrauchbar. Gemessen am 05.11.: `zen/deepseek-v4.1-flash-free` antwortet `429 FreeUsageLimitError` (Retry 30.162 s), andere Free-Modelle `403 FreeTierError` ("can only be used from within OpenCode"). Ein `$0`-Inputpreis macht sie deshalb nicht waehlbar; die fruehere Ausnahme `PINNED_FREE_MODELS` / `user_pinned_free_exception` war die Ursache des toten Picker-Eintrags.
- **Decision:** Schwellen stehen in `catalog_rules.py`, nicht im Aufruf. Sonst faellt ein spaeterer Rebuild still auf `$0.30`/`45` zurueck. `is_free_variant()` prueft providerbezogen: OpenRouter `:free` plus `openrouter/free`, Zen `-free`.
- **Bug/Finding:** `_selection_reason()` prueft jetzt zuerst die Free-Regel; das Audit traegt `criteria.free_variants.excluded_counts` statt `explicit_free_exceptions`. `export_review_csv.py` verliert die Ausnahme-Pruefung, weil es keine Ausnahme mehr gibt.
- **Codex-Threads:** 22 Threads mit Provider `opencode-go` und 25 mit `zen/*-free` wurden per `repair-threads.py` auf `opencode-proxy` umgeschrieben (Sicherungen `state_5.sqlite.bak-20261105-164438` und `-164945`). Die Modellspalte wird von Codex beim Start neu abgeleitet; nur der Provider bleibt stabil.

## Work State
### Completed
- Kataloge: picker 8, go 5, zen 2, proxy 7 Modelle; kein `free`-Slug mehr; Audit-Counter openrouter 5 / go 0 / zen 9 ausgeschlossen.
- Volle Suite `1084 passed, 6 skipped, 16 subtests`; `ruff check` clean; Loader-Verify exit 0; Katalog-Backups `*.backup-20261105-175143`.
- Proxy-Katalog beginnt mit `opencode-go/mimo-v2.6-pro` (Score 48.3), der konfigurierte Default `opencode-go/mimo-v2.6-flash` bleibt enthalten.

### Active
- Keine offene Implementierung. Ein Plan fuer ein Plugin am `session.compaction`-Ereignis liegt zur Entscheidung vor.

### Blocked
- Nichts.

## Next Move
1. Codex Desktop neu starten und den Picker pruefen: sieben Eintraege, keine Free-Modelle, Default weiterhin `opencode-go/mimo-v2.6-flash`.
2. Plugin-Entscheidung: Ziel COMPACTIONS.md, Sidecar oder Zeiger-plus-Sidecar.

## Relevant Files
- `tools/codex-picker/catalog_rules.py`: `is_free_variant`, `INPUT_PRICE_LIMIT=0.50`, `MIN_CALIBRATED_SCORE=40.0`.
- `tools/codex-picker/build_provider_catalogs.py`: Free-Ausschluss vor Preis-/Score-Pruefung, Audit-Regel, Report-Zeile.
- `tools/codex-picker/export_review_csv.py`: Ausnahme-Pruefung entfernt.
- `tests/test_codex_picker_selection.py`, `tests/test_codex_picker_csv.py`: Grenzwerte, Free-Regel, Sortierung.
- `tools/codex-picker/README.md`, `METHODOLOGY.md`: Preis-/Score-Historie und Free-Politik.
- `tools/codex-picker/repair-threads.py`: Thread-Reparatur mit Sicherung und `--include-free`.

## Important Context
- `mimo-v2.6` ohne Suffix existiert im Go-Tarif nicht; nur `-flash` und `-pro`.
- Die Free-Sperre gilt fuer Harnesses, nicht fuer OpenCode selbst.
- Der Proxy lief waehrend des Baus; der Katalog ist live geprueft, nicht aus dem Cache.

=============== Korrektur 05.11.2026 / 18:12 ================
## Korrektur zum Block 17:57
- **Befund:** Die Free-Sperre gilt nur fuer das OpenCode-Gateway (`go`, `zen`), nicht fuer OpenRouter. `[model_providers.openrouter]` zeigt direkt auf `openrouter.ai/api/v1` mit eigenem Key; `cohere/north-mini-code:free` und `openrouter/free` antworten dort **HTTP 200** (geprueft 05.11.2026). Die 403/429-Antworten kamen ausschliesslich von `opencode.ai`.
- **Regel korrigiert:** `is_free_variant()` prueft nur noch `go` und `zen` auf `-free`. OpenRouter-Free-Modelle laufen durch den normalen Preis-/Score-Filter; der Audit-Zaehler steht bei `openrouter 0, go 0, zen 9`.
- **Kataloge neu gebaut** (`*.backup-20261105-181120`): picker 8, go 5, zen 2, proxy 7 — unveraendert, weil kein Free-Modell einen Score hat.
- **Nebenbefund:** Der authentifizierte OpenRouter-Katalog liefert 323 Modelle, die oeffentliche Liste 452. Acht `:free`-Modelle (u. a. `google/gemma-4-26b-a4b-it:free`, `nvidia/nemotron-3-ultra-550b-a55b:free`) werden diesem Konto gar nicht angeboten. Die fuenf sichtbaren Free-Modelle bleiben `unverified` und werden deshalb nicht ausgewaehlt.
- **Offen (Nutzerentscheidung):** Sollen unverifizierte OpenRouter-Free-Modelle wieder als ausdrueckliche Ausnahme in den Picker, oder bleibt die Regel "ohne Benchmark keine Auswahl"?

## Next Move
1. Entscheidung zur Free-Ausnahme bei OpenRouter.
2. Codex neu starten und Picker pruefen.

## Relevant Files
- `tools/codex-picker/catalog_rules.py`, `build_provider_catalogs.py`, `tests/test_codex_picker_selection.py`, `README.md`, `METHODOLOGY.md`, `CHANGELOG.md`.

=============== Compaction 05.11.2026 / 18:50 ================
## Objective
- **Current:** Abschluss der Katalogarbeit: Rebuild auf dem neuen Stand, Commit im Fork, Push vorbereiten.
- **Completed:** `--include-unverified-free` samt Hilfe, README, Tests und Audit-Feld; Kataloge neu gebaut; Doku aktualisiert.

## Important Details
- **Decision:** Free-Modelle sind auf dem direkten OpenRouter-Weg erlaubt, aber nur per Opt-in und nur bei verifiziertem `$0`-Inputpreis. Sie bleiben `unverified`, `score: null`, stehen hinter allen bewerteten Modellen und tragen `selection_reason=unverified_free_exception`. Go und Zen bleiben gesperrt.
- **Finding (Instabilitaet):** Die authentifizierte OpenRouter-Modellliste schwankt zwischen 323 und 454 Eintraegen — 18:31 mit 454 (13 Free), 18:45 mit 323 (5 Free), gleicher Befehl und gleicher Key. Die acht bewerteten Modelle sind stabil, nur die Free-Menge schwankt. Ursache ist eine Kontofilterung bzw. ein Edge-Cache bei OpenRouter, kein Builder-Fehler.
- **Konsequenz:** Ein Rebuild kann weniger Free-Eintraege liefern, ohne dass sich am Code etwas geaendert hat. Wer die Free-Modelle im Picker will, muß `--include-unverified-free` mitgeben; die Zahl ist nicht reproduzierbar.
- **Abgrenzung Ori:** `ori harness setup codex` verworfen — Windows-Desktop unverifiziert, Konflikt mit dem Go-Proxy, umgeht den kuratierten Filter. `ori codex` waere der risikoarme Test, Ori ist aber nicht installiert.

## Work State
### Completed
- Kataloge: picker 13 (8 bewertet + 5 free), go 5, zen 2, proxy 7; Backups `*.backup-20261105-184533`; Loader-Verify exit 0.
- Suite `1090 passed, 6 skipped, 16 subtests`; `ruff check` clean.
- `switch-provider.ps1 -Check`: `catalog: ok` fuer `opencode-go/mimo-v2.6-flash`.

### Active
- Commit im Fork auf `main`; Push bleibt beim Nutzer.

### Blocked
- Keiner.

## Next Move
1. Commit `main` im Fork, danach `git push fork main` durch den Nutzer.
2. Bei jedem Rebuild `--include-unverified-free` mitgeben, sonst verschwinden die Free-Eintraege wieder.

## Relevant Files
- `tools/codex-picker/catalog_rules.py`: `is_free_variant` (Gateway) und `is_free_offer` (Angebot).
- `tools/codex-picker/build_provider_catalogs.py`: Flag, Auswahlgrund, Audit `criteria.free_variants.unverified_free_exception`.
- `tools/codex-picker/export_review_csv.py`: Ausnahme nur bei `$0` und ohne Score.
- `tools/codex-picker/repair-threads.py`: Codex-Thread-Reparatur mit Sicherung.
- `tests/test_codex_picker_selection.py`, `tests/test_codex_picker_csv.py`, `tools/codex-picker/README.md`, `METHODOLOGY.md`, `CHANGELOG.md`.

## Important Context
- Push-Ziel ist ausschliesslich `fork` (`pskraemer11/codex-provider-gateway`); `origin` bleibt Referenz.
- Der Proxy lief waehrend aller Builds; die Kataloge sind live geprueft.



