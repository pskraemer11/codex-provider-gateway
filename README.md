# Codex Provider Gateway

This repository combines two related but separate tools:

- `opencode-go-proxy` is a local, single-user Responses API adapter for Codex.
  It routes native Codex models, OpenCode Go models, and OpenCode Zen models.
  This part is a fork of the Codex Provider Gateway at https://github.com/kartikkabadi/opencode-go-proxy.
- `tools/codex-picker/` builds price- and benchmark-filtered Codex catalogs for
  direct OpenRouter routes, direct OpenCode Go/Zen routes, and the combined
  local Go/Zen proxy. It does not construct the complete Pareto frontier line,
  but selects a defined point on it which you can choose.

- The OpenRouter provider is used directly by Codex.
- OpenCode Go and Zen can be used through the local proxy, which translates the
  wire protocol per model family.

```text
Codex
├── model_provider=openrouter ────────────────> OpenRouter API
│
└── model_provider=opencode-proxy
    └── /v1/responses ──> opencode-go-proxy
                          ├── native Codex models
                          ├── OpenCode Go  ──> chat / responses / messages
                          └── OpenCode Zen ──> chat / responses / messages / Gemini
```

The toolchain produces the following catalogs. Counts are an example from the
31 October 2026 audit. For proxy routes, the live `/v1/models` response is
authoritative; the picker and direct-provider files are generated snapshots.

| Datei                 | Zweck                                   | Inhalt im Audit                       |
| --------------------- | --------------------------------------- | ------------------------------------: |
| `picker-catalog.json` | direkter OpenRouter-Provider            | 8 Modelle                             |
| `go-catalog.json`     | direkter OpenCode-Go-Provider           | 3 Modelle                             |
| `zen-catalog.json`    | direkter OpenCode-Zen-Provider          | 5 Modelle                             |
| `proxy-catalog.json`  | kombinierter Go/Zen-Proxy               | 8 Modelle                             |
| `merged-models.json`  | Proxy-Runtime, nicht vom Picker erzeugt | native Modelle plus 110 Go/Zen-Routen |

The picker writes `picker-catalog.json`, `go-catalog.json`, `zen-catalog.json`,
and `proxy-catalog.json`. The proxy writes the runtime files under its state
directory, including `merged-models.json`.

## Funktion

Codex sends Responses API requests to `POST /v1/responses`. The proxy accepts
both `/responses` and `/v1/responses`, then selects one of three destinations:

- Native Codex models are relayed unchanged to the configured ChatGPT backend.
- OpenCode Go models use a certified protocol family and explicit
  `opencode-go/<model-id>` slugs.
- OpenCode Zen models use `zen/<model-id>` slugs and are discovered dynamically.

The documented Go set currently contains 33 models: 5 Responses, 19 Chat
Completions, and 9 Anthropic Messages models. Four additional legacy IDs with a
verified protocol family are also accepted. The checked-in seed keeps startup
working offline. Runtime refresh only accepts documented or protocol-certified
IDs; an unknown ID is rejected before an upstream request is made.

Zen discovers its model list from OpenCode and uses models.dev metadata when
available. Families map to:

- Claude and Qwen models to Anthropic Messages
- Gemini models to the Gemini API
- GPT and Grok models to Responses
- all other Zen models to Chat Completions

Routing precedence is explicit:

1. `opencode-go/<id>` always selects Go.
2. `zen/<id>` always selects Zen.
3. A captured native slug selects the native Codex endpoint.
4. A bare Zen-only slug selects Zen.
5. A bare slug present in both Go and Zen stays on Go; use `zen/<id>` for the
   Zen route.

The proxy supports streaming and non-streaming requests, real-time SSE, tool
schemas, Codex `apply_patch`, reasoning replay, zstd request bodies, image
translation and captioning, and native-model coexistence. Unknown or malformed
models are rejected rather than silently substituted.

## Installation

Requirements: Python 3.11 or newer, `uv`, and a Codex installation that supports
custom providers and `model_catalog_json`.

### Proxy

Install the proxy persistently, then run the loopback-only adapter:

```powershell
$env:OPENCODE_GO_API_KEY = "your-key"

uv tool install --python 3.12 git+https://github.com/pskraemer11/opencode-go-proxy

opencode-go-proxy config enable
opencode-go-proxy --bind 127.0.0.1 --port 8787
```

For development from this checkout, use `uv tool install --editable . --python 3.12`.
That installation stays linked to this checkout; use the non-editable install
above when the command should survive moving or removing the checkout.
`uvx --from ...` is a one-off runner and does not provide the persistent
`opencode-go-proxy` command.

Fully restart Codex after enabling the provider, then select an explicit model:

```bash
codex -m opencode-go/gpt-6-luna
codex -m zen/gpt-6-luna
```

`config enable` writes one marker-delimited block in Codex's `config.toml`. It
sets `openai_base_url` and `model_catalog_json`, and manages the
`opencode-go` and `zen` provider tables. It preserves unrelated settings and
native ChatGPT authorization. Remove only the managed block with:

```bash
opencode-go-proxy config disable
```

On Windows, the optional autostart and health watchdog live in
`tools/codex-picker/`. The installer copies the watchdog into the user's local
app-data directory and the watchdog prefers the installed
`opencode-go-proxy` command. `uv run` remains only a development fallback when
the command is not installed. Preview Task Scheduler registration before
enabling it:

```powershell
pwsh -File tools/codex-picker/install-proxy-autostart.ps1 -WhatIf -ReplaceExisting
```

### Katalogpicker

The picker runs from a repository checkout; installing the proxy persistently
does not install the picker.

- Required: `ARTIFICIAL_ANALYSIS_API_KEY`
- Optional: `OPENROUTER_API_KEY` (the public model list works without it)
- Not needed by the current AA-only policy: `OPENROUTER_MANAGEMENT_KEY`

The picker uses `CODEX_HOME/.tmp/bundled-catalog.json` when present. Otherwise
it obtains a full model template from `codex debug models`; an explicit
`--template PATH` overrides both. The proxy URL defaults to
`http://127.0.0.1:8787/v1/models`, follows `OPENCODE_GO_PROXY_PORT`, and can be
overridden with `--proxy-url`.

Validate sources and selection against a live proxy without writing files:

```powershell
python tools/codex-picker/build_provider_catalogs.py --check
```

Build all catalogs and the audit:

```powershell
python tools/codex-picker/build_provider_catalogs.py
```

Writes to the active Codex home require a reachable proxy, unless
`--allow-cached-proxy` explicitly accepts the cached proxy catalog. The same
flag is required when `--check` should run without a live proxy. Existing
catalogs are backed up before replacement, and the Codex loader is checked
after writing.
Use `--provider openrouter|go|zen|proxy` for a single catalog and
`--max-input-price` or `--min-intelligence-score` for a different Pareto point.
The score threshold defaults to `> 50/100`; the calibration population always
contains all usable AA Intelligence values before provider prices are applied.

The Windows switcher toggles the root Codex provider between `openrouter` and
the local `opencode-proxy` configuration:

```powershell
pwsh -File tools/codex-picker/switch-provider.ps1 -Check
pwsh -File tools/codex-picker/switch-provider.ps1 -Target proxy
pwsh -File tools/codex-picker/switch-provider.ps1 -Target openrouter
```

The switcher expects the corresponding provider tables to exist. The managed
`config enable` path and the Windows switcher are separate setup paths: the
former manages `opencode-go`/`zen`, while the latter selects an
`opencode-proxy` provider and `proxy-catalog.json`. The switcher refuses a
target whose provider table is missing and replaces `config.toml` atomically.

Minimal user-owned provider tables for the switcher are:

```toml
[model_providers.openrouter]
name = "openrouter"
base_url = "https://openrouter.ai/api/v1"
wire_api = "responses"
env_key = "OPENROUTER_API_KEY"

[model_providers.opencode-proxy]
name = "OpenCode Go + Zen (local proxy)"
base_url = "http://127.0.0.1:8787/v1"
wire_api = "responses"
env_key = "OPENCODE_GO_API_KEY"
```

The picker does not create or modify these provider tables.

## Schnittstellen

| Client request              | Behavior                                                               |
| --------------------------- | ---------------------------------------------------------------------- |
| `POST /v1/responses`        | Responses requests for all routed models; translated per family        |
| `POST /v1/chat/completions` | Verbatim Chat Completions relay for Go and Zen Chat models             |
| `POST /v1/messages`         | OpenCode Go Messages models only; Zen uses `/v1/responses` translation |
| `GET /v1/models`            | Current merged native, Go, and Zen model list                          |
| `GET /health`               | Liveness and listener status                                           |
| `GET /state`                | Status, port, quota, usage, and current model                          |
| `GET /quota`                | Latest harvested provider quota snapshot                               |
| `GET /cache`                | Prefix-cache hit/miss statistics                                       |
| `GET /version`              | Proxy version and update state                                         |

The compact `/responses/compact` and `/v1/responses/compact` aliases are also
available. A model sent to an incompatible direct-format endpoint is rejected
instead of being silently translated to another response shape.

## Bedienung

The main operations commands are:

```bash
opencode-go-proxy doctor --json
opencode-go-proxy smoke-test
opencode-go-proxy refresh-runtime
opencode-go-proxy status --json
opencode-go-proxy support-bundle --output proxy-support.json
```

`doctor --fix` only repairs safe local directories and renders; it does not
rewrite `config.toml`. `smoke-test` sends one marker prompt through the local
proxy and can select a model with `--model`. `support-bundle` redacts
secret-shaped values before writing diagnostics.

The proxy listens on one HTTP port only. Important configuration defaults are:

| Flag              | Environment variable                                                                   | Default                         |
| ----------------- | -------------------------------------------------------------------------------------- | ------------------------------- |
| `--bind`          | `OPENCODE_GO_PROXY_BIND`                                                               | `127.0.0.1`                     |
| `--port`          | `OPENCODE_GO_PROXY_PORT`                                                               | `8787`                          |
| `--chat-base-url` | `OPENCODE_GO_BASE_URL`, then `OPENCODE_ZEN_BASE_URL`, then `CHAT_COMPLETIONS_BASE_URL` | `https://opencode.ai/zen/go/v1` |
| `--api-key-env`   | `OPENCODE_GO_PROXY_API_KEY_ENV`                                                        | `OPENCODE_GO_API_KEY`           |
| `--timeout-sec`   | `OPENCODE_GO_PROXY_TIMEOUT_SEC`                                                        | `180`                           |
| `--max-body-mb`   | `OPENCODE_GO_PROXY_MAX_BODY_MB`                                                        | `20`                            |

Keep the listener on loopback. A non-loopback bind fails closed unless
`OPENCODE_GO_PROXY_ALLOW_REMOTE=1` and a separate caller token are configured.
The caller token is never forwarded to an upstream provider. See
[SECURITY.md](SECURITY.md) for credential and network guidance.

## Katalog-Dateien

### Proxy

The proxy stores runtime state under `OPENCODE_GO_PROXY_STATE_DIR`, by default
`~/.codex/opencode-go-proxy/`. The important files are:

- `opencode-go-models.json`: compact Go catalog used for fast startup
- `opencode-go-catalog.json`: full-shape Go catalog
- `native-models.json`: captured native Codex models
- `zen-models.json`: captured Zen model list
- `zen-catalog.json`: persisted Zen model families
- `merged-models.json`: native, Go, and Zen entries served by `/v1/models`
- `user-models.json`, `model-picker.json`, `announced-models.json`: local
  add/hide/display overlays and announcement state

The checked-in `contrib/opencode-go-models.json` is the offline seed. Runtime
refresh never writes into `contrib/`. At startup the proxy renders the state
catalog immediately and refreshes it in the background with TTL gating. Full
catalog rendering follows Codex's version-specific `ModelsResponse` shape; the
`fetched_at`, `etag`, and `client_version` fields are proxy metadata, not a
`ModelsCache` requirement.

### Katalogpicker

The picker writes the four catalogs from the introduction plus
`provider-catalog-audit.json` into the active Codex home. It uses:

- OpenRouter prices from `/api/v1/models`
- OpenCode Go and Zen prices from their documentation tables
- Artificial Analysis Intelligence values from the live AA API
- a dated local AA snapshot only as a bounded fallback
- Go/Zen route names and families from the running proxy and its state catalog

Normal selection requires input price `< $0.25/M` and a calibrated AA
Intelligence score `> 50/100`. The score is Min-Max calibrated over all usable
values in the selected AA population before provider prices are applied. This
keeps the scale anchored to the overall model field instead of redefining
`0/100` from the currently price-eligible subset. If the live Intelligence
population is unavailable or all zero, the same rule is applied to the bounded
local snapshot. Missing or ambiguous benchmark identities remain `unverified`;
they are not converted to zero. Five explicitly requested free routes are
included only when the provider source confirms a `$0` input price. OpenRouter
Coding and Agentic indices are not used as a substitute for the AA Intelligence
score.

The audit records source URLs, retrieval timestamps, hashes, calibration
population, selection reason, exact identity match, and raw index values. See
[`tools/codex-picker/README.md`](tools/codex-picker/README.md) and
[`tools/codex-picker/METHODOLOGY.md`](tools/codex-picker/METHODOLOGY.md) for
the complete policy and CSV fields.

## Sicherheit

This project is an independent, single-user adapter. It is not affiliated with
OpenAI or OpenCode and does not provide pooled accounts, shared credentials,
subscription resale, or mechanisms to evade provider limits. Use your own
accounts and follow the current provider terms.

OpenCode credentials are resolved from the configured environment variable or,
on macOS, the keychain. Credential values are not written into traces, meters,
catalogs, or support bundles. Native Codex authorization is relayed only to the
configured native HTTPS endpoint; it is never converted into an OpenCode key.
Image URLs are restricted to `data:image/` and `https://`.

## Troubleshooting

| Symptom                                 | Check                                                                                 |
| --------------------------------------- | ------------------------------------------------------------------------------------- |
| `localhost:8787` refuses connections    | Start the proxy and check `GET /health`.                                              |
| Port 8787 is already in use             | Stop the other proxy instance; only one listener is supported.                        |
| API key not found                       | Set `OPENCODE_GO_API_KEY` or configure the macOS keychain entry.                      |
| Unknown model                           | Refresh the catalog with `opencode-go-proxy refresh-runtime` or inspect `/v1/models`. |
| Model metadata warning                  | Point `model_catalog_json` at a full-shape catalog such as `merged-models.json`.      |
| Desktop switch uses an unknown provider | Ensure the selected `opencode-proxy` or `openrouter` provider table exists.           |

The `codex debug models` output verifies the CLI catalog, not the Desktop
renderer. Desktop picker behavior should be checked in the installed Codex
version when changing catalog schemas.

## Entwicklung

From the repository root:

```bash
uv sync
uv run python -m pytest tests -v
uvx ruff check
uv build
```

The optional local Git gate is enabled per clone with
`git config core.hooksPath .githooks`. It runs the full test suite for code
changes on commit and always on push. The CI workflow runs tests, Ruff, and the
wheel build on `main`, `master`, pull requests, and release tags. A Windows job
parses the PowerShell scripts and runs temporary-config fixture tests. This
repository's CI is defined in `.github/workflows/ci.yml`.

## Lizenz

MIT. See [LICENSE](LICENSE).

## Links

[![CI](https://github.com/pskraemer11/opencode-go-proxy/actions/workflows/ci.yml/badge.svg)](https://github.com/pskraemer11/opencode-go-proxy/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Dependencies: zstandard](https://img.shields.io/badge/dependencies-zstandard-blue.svg)](#)

- [Upstream repository](https://github.com/kartikkabadi/opencode-go-proxy)
- [Picker documentation](tools/codex-picker/README.md)
- [Picker methodology](tools/codex-picker/METHODOLOGY.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Publishing](PUBLISHING.md)

Use your own [OpenCode Go](https://opencode.ai/docs/go) and
[OpenCode Zen](https://opencode.ai/zen) credentials in
[Codex](https://github.com/openai/codex) through this local adapter.
