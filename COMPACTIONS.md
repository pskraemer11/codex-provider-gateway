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
