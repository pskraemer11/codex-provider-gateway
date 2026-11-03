---
name: opencode-go-proxy
description: Orientation for using the opencode-go-proxy bridge, which lets the Codex app use OpenCode Go and OpenCode Zen through a local Python service with one runtime dependency (zstandard). Explains how traffic flows, how Go/zen/ prefixes and bare slugs route, how unknown models are rejected, how to start and stop the proxy (CLI, single port 8787) including the non-loopback bind guard, the operational commands (doctor, smoke-test, support-bundle), how prefix caching works and how to check the hit ratio, and the config and API-key resolution. Use when working on or operating opencode-go-proxy, or when the Codex app is pointed at 127.0.0.1:8787.
---

# OpenCode Go Proxy

The proxy bridges Codex's Responses API to OpenCode Go and OpenCode Zen upstreams in one local process on port 8787. It has one runtime dependency (zstandard); the rest is stdlib. It is single-port.

```text
Codex app -> POST /v1/responses -> opencode-go-proxy (127.0.0.1:8787)
          -> opencode-go/<id>  -> OpenCode Go
          -> zen/<id>          -> OpenCode Zen
          -> gpt-*/o* (native) -> ChatGPT backend passthrough
```

Native models, Go routes (`opencode-go/<id>`) and Zen routes (`zen/<id>`) share the one port; the slug decides the upstream.

## Start and stop

- The proxy is controlled by a native macOS menu bar app (branch icon) on macOS. It shows live status, Start/Stop, logs, and copy-port, and it stops the child proxy on Quit. It refuses to Start if port 8787 is already owned (single-port guard). No launchd agent on macOS; `opencode-go-proxy install` points at the menu bar app.
- CLI (from a checkout or a pin): `uv run opencode-go-proxy --bind 127.0.0.1 --port 8787` or `uvx --from git+https://github.com/pskraemer11/codex-provider-gateway opencode-go-proxy --port 8787`.
- One proxy per port. A non-loopback `--bind` (e.g. `0.0.0.0`) is a startup error unless `OPENCODE_GO_PROXY_ALLOW_REMOTE=1` and `OPENCODE_GO_PROXY_CALLER_TOKEN` carries at least 32 characters. `guards.validate_bind_security` refuses the start otherwise; it does not merely warn.
- Stop any older launchd agent before starting the menu bar app (`launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.opencode-go.proxy.plist`).

## Operational commands

- `opencode-go-proxy doctor` - read-only self-check (API key present, Codex config routes through the proxy and its selected model is catalogued, provider auth shape, catalog readable, port ownership, /health 200, meter writable, logs present, upstream reachable). `--json` for machine output; non-zero exit on any failure.
- `opencode-go-proxy smoke-test` - one tiny real chat-completion to upstream; non-zero on failure.
- `opencode-go-proxy support-bundle [--output FILE]` - tarball of version, logs, meter, and redacted config (secret values masked, never bundled raw).
- `opencode-go-proxy agents-sync` - writes one Codex agent TOML per opencode-go model into ~/.codex/agents (`router_opencode_go_<slug>`) so subagents use the same models; removes agent files this proxy wrote whose model left the catalog.
- `opencode-go-proxy install-skills [--dry-run]` - copies `skills/opencode-go-proxy/SKILL.md` from the repository/installation root into `~/.codex/skills/opencode-go-proxy/` with an ownership marker. `OPENCODE_GO_PROXY_SKILL_SOURCE` points it at another source file; `OPENCODE_GO_PROXY_SKILLS_DIR` changes the destination.
- `opencode-go-proxy --refresh-catalog` - re-discover the certified Go models from the OpenCode Go `GET /models` endpoint and rewrite `contrib/opencode-go-catalog.json` / `-compact.json` (TTL-gated; `--force` bypasses the TTL).
- `opencode-go-proxy refresh-runtime` - re-capture the native set (`codex debug models --bundled`) and force a runtime render under the state dir.

## Models: native, Go, Zen

The merged catalog lists native, Go, and Zen models. Routing order is fixed:

1. `opencode-go/<id>` goes to OpenCode Go.
2. `zen/<id>` goes to OpenCode Zen.
3. A bare slug that is in the captured native set goes to the ChatGPT backend passthrough (`gpt-*`, `o*`, `codex-auto-review`).
4. A bare slug that Zen owns and Go does not goes to Zen (the picker emits these without a prefix).
5. Any other bare slug goes to OpenCode Go. A bare Go/Zen collision therefore resolves to Go.

An unknown slug is rejected with HTTP 400 and `error.type = model_not_found` (`unknown model '<slug>'; refresh the catalog or add it to user-models.json`). There is no silent fallback to a default model. A missing `model` field uses the default model.

Native capture reads `codex debug models --bundled`, not the plain command: the plain command renders whatever `model_catalog_json` currently points at, so a configured proxy catalog would leave the native snapshot empty and break rule 3.

## Threads and automations

The app's codex_app tools (threads, automations, spawn_agent, handoff, fork) are available in chat sessions: the proxy snapshots the app's tool list and merges the missing thread/automation tools into requests that did not carry them. No extra config.

## Prefix caching
OpenCode Go bills cached reads cheaply, so request prefixes are kept byte-stable: the system prompt is always first, history is appended in order, and streaming sets `stream_options.include_usage` so the upstream reports its cache accounting. First request of a new context always misses (cold); later requests in a session typically hit 99%+.

Check the ratio: `curl http://127.0.0.1:8787/cache` (per-model and totals). Per-request: grep for `"cache"` in the stderr log.

## API key

Resolved in order: `OPENCODE_GO_API_KEY`, `OPENCODE_API_KEY`, then macOS keychain services `opencode-go-api-key` and `codex-router-opencode-go`. Never print or commit the key.

## Reliability

- Truncated streams are never counted as success: the meter (`usage-events.jsonl`) records `streamAborted` with status 502.
- Transient upstream failures (429/5xx/network/timeout) are retried with bounded backoff (`OPENCODE_GO_PROXY_MAX_RETRIES`, default 2) before surfacing an error.
- The WebSocket upgrade the Codex desktop app attempts for realtime is answered with `HTTP/1.1 426`; the app falls back to HTTP streaming. That is by design, not an error.

## Config

- `opencode-go-proxy config enable` writes one managed block into `~/.codex/config.toml`: `openai_base_url` (the proxy), `model_catalog_json` (the merged native + Go + Zen catalog in the state dir), the `multi_agent_v2` feature (only when the installed codex binary accepts it), and inert `[model_providers.opencode-go]` and `[model_providers.zen]` blocks (`base_url` 8787, `wire_api` "responses", `requires_openai_auth = true`). User-owned keys are never replaced; `config disable` removes the block.
- `requires_openai_auth = true` without `env_key` is deliberate: it keeps the ChatGPT session as the credential so Codex Desktop plugin toggles do not fail with HTTP 432. The proxy ignores the incoming bearer and uses its own key.
- `doctor` checks both setup paths (managed root `openai_base_url` and a root `model_provider` with its provider table), verifies that the selected `model` exists in `model_catalog_json`, and warns when the active proxy provider sets `env_key` or omits `requires_openai_auth`.
- Bind is guarded: a non-loopback listener (e.g. `--bind 0.0.0.0`) refuses to start unless `OPENCODE_GO_PROXY_ALLOW_REMOTE=1` and `OPENCODE_GO_PROXY_CALLER_TOKEN` is at least 32 characters. Remote requests then need the matching `X-OpenCode-Go-Proxy-Token` header.
