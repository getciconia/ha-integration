# Contributing

Thanks for helping! Bug reports and pull requests are welcome.

- **Bugs**: open an issue with the bug report form and attach the
  integration's diagnostics (Settings → Devices & services → Ciconia →
  ⋮ → Download diagnostics; the token and positions are removed).
- **Pull requests**: keep them small and focused. CI must pass:
  `ruff check .`, `ruff format --check .`, `mypy` and `pytest --cov`
  (coverage stays at 95 % or more). See [DEVELOPMENT.md](DEVELOPMENT.md).
- **New sensors** need a matching field in the Ciconia API, so open an issue
  first so we can talk about it.

Security problems: see [SECURITY.md](SECURITY.md).
