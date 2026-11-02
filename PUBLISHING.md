# Publishing

This fork is published on GitHub as
[`pskraemer11/codex-provider-gateway`](https://github.com/pskraemer11/codex-provider-gateway).
It began as a fork of
[`kartikkabadi/opencode-go-proxy`](https://github.com/kartikkabadi/opencode-go-proxy);
that repository is the upstream source, not this project's publishing target.

## Release surface

- Package: `opencode-go-proxy`
- Current version: `0.4.10`
- CLI entry point: `opencode-go-proxy`
- Python: `>=3.11`
- Build backend: `uv_build`
- Verification: `uv run python -m pytest tests -v`,
  `uvx ruff check`, `uv build`

## Install

```bash
uvx --from git+https://github.com/pskraemer11/codex-provider-gateway opencode-go-proxy
```

No PyPI, no AUR. `uvx` from git is the only install path.

## Release flow

1. Preview the release from a clean checkout of `main` with
   `python scripts/make-release.py 0.4.11 --remote fork --dry-run`.
   Replace `0.4.11` with the intended next version and `fork` with the local
   remote name. The script requires an
   explicit remote and verifies that every push URL points to the repository
   recorded in `pyproject.toml` before proceeding. It asserts a clean tree on
   `main`, bumps
   `pyproject.toml` and `src/opencode_go_proxy/__init__.py`, writes the
   `CHANGELOG.md` section from commits since the last tag, updates the
   "Current version" line here, commits `release: v<version>`, tags
   `v<version>`, and pushes both to the selected remote. Run the same command
   without `--dry-run` only after reviewing the preview:

   ```bash
   python scripts/make-release.py 0.4.11 --remote fork
   ```

2. The tag push to this repository triggers CI (`.github/workflows/ci.yml`):
   the `test` job runs the suite,
   `uv build` produces the wheel, and the `release` job attaches
   `dist/*.whl` to a GitHub release with auto-generated notes
   (`softprops/action-gh-release`). No other distribution step exists.

## License

MIT. See [LICENSE](LICENSE).
