# AGENTS.md

Agent guidance for this repository. Applies to all agents working here.

## Remotes: fork is the only push target

This checkout has two remotes with different roles:

| Remote   | Role                                                             |
| -------- | ---------------------------------------------------------------- |
| `fork`   | Configured user fork; only target when the user performs a push. |
| `origin` | Upstream read-only reference; never push or open PRs against it. |

- The agent does not push. If the user performs a push, use `fork` (for example,
  `git push fork main`); never push to `origin` or open PRs against it.
- Feature branches must track `fork/*`, not `origin/*`. If an old branch still
  shows `[origin/main]` in `git branch -vv`, clear it with
  `git branch --unset-upstream <branch>` before working on it.
- The update check and install source use the fork as well (`RELEASE_REPO` in
  `updates.py`, `_UPDATE_SOURCE_URL` in `ops.py`). Keep fork references
  consistent when renaming or moving the repository.

## Git hooks (test gate)

`.githooks/` holds a local test gate. It is not part of upstream and is
activated per clone, because `core.hooksPath` is local Git configuration:

```sh
git config core.hooksPath .githooks
```

- `pre-commit` runs Ruff and the full suite, but only when a
  staged path starts with `src/`, `tests/`, `contrib/`, `scripts/` or `tools/`. The
  prefix check decides *whether* the full suite runs, never *which* tests:
  coverage stays complete, so it cannot hide a break. Commit `f9d0dfa` changed
  only `src/opencode_go_proxy/go_models.py`; a changed-file test selection
  would have run nothing at all.
- `pre-push` always runs both.

The commands are not hardcoded: `.githooks/test-gate.conf` holds the prefixes,
the interpreter and the two commands. The hooks are therefore section 3 of the
templates under `~/.agents/references/githooks/`, with the secret scan and the
domain guard left out. `GITHOOKS_TEST_GATE=0` skips the gate for invocations
that start the hook for another purpose, such as a CI privacy check.

The upstream CI cannot replace this gate: `.github/workflows/ci.yml` triggers
on push to `main`/`master`, on tags, and on pull requests. A push to a local
branch starts nothing.

`.gitattributes` pins `.githooks/*` to LF. With `core.autocrlf=true` a CRLF
shebang would turn the interpreter into `bash\r` and the hooks would fail
silently.

Emergency exit is `--no-verify`, for documented emergencies only.

## Agent skills

### Issue tracker

Work is tracked as GitHub issues on this repo. The map for large planning efforts is a single issue labelled `wayfinder:map` with child tickets. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` at the repo root (created lazily when terms are resolved), plus `docs/adr/` for architectural decisions. See `docs/agents/domain.md`.
