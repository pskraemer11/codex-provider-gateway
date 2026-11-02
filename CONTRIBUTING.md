# Contributing

This repository is the Picker-enhanced fork published at
[`pskraemer11/codex-provider-gateway`](https://github.com/pskraemer11/codex-provider-gateway).
The source project is [`kartikkabadi/opencode-go-proxy`](https://github.com/kartikkabadi/opencode-go-proxy).
Contributions described here target this fork; use the `upstream` remote only
when deliberately preparing a separate contribution to the source project.

## Setup

```bash
git clone https://github.com/pskraemer11/codex-provider-gateway.git
cd codex-provider-gateway
git remote add upstream https://github.com/kartikkabadi/opencode-go-proxy.git
uv sync
```

## Development and verification

Run the same core checks used by this repository's CI:

```bash
uv run python -m pytest tests -v
uvx ruff check
uv build
```

The optional local Git test gate can be enabled for this clone with:

```bash
git config core.hooksPath .githooks
```

## Code style and project structure

- Supported Python runtime: 3.11 and newer.
- Declare runtime dependencies in `pyproject.toml`; the proxy currently uses
  `zstandard` for compressed request bodies. `uv sync` installs the project and
  its development dependencies.
- Keep proxy implementation in `src/opencode_go_proxy/` and tests in `tests/`.
  Follow the existing module boundaries and keep changes focused.
- Route network calls through the existing tracing conventions, including
  `trace()` where used by the module.
- The Codex Picker and Windows lifecycle scripts are repository tools, not part
  of the `uvx`-installed CLI package. Their inputs, credentials, checks, and
  opt-in Task Scheduler setup are documented in
  [`tools/codex-picker/README.md`](tools/codex-picker/README.md).

## Pull requests

1. Create a topic branch from `main` in this repository and target this fork
   with the pull request.
2. Add or update tests for changed behavior.
3. Run the verification commands above and report any skipped checks.
4. Keep the diff focused and reference related issues in the pull request.

## Reporting issues

Include the relevant details:

- Codex version (`codex --version`)
- Proxy version (`opencode-go-proxy --version`)
- Affected workflow: OpenCode Go, OpenCode Zen, native OpenAI routing, or Picker
  catalog generation (include data-source dates for catalog issues)
- Trace output (stderr JSON lines; redact API keys first)
- Minimal reproduction steps

## Security

See [SECURITY.md](SECURITY.md). Do not open public issues for security vulnerabilities.
