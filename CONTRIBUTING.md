# Contributing to LedgerLens Core

Thanks for your interest in contributing to the LedgerLens detection engine.

## Getting started

```bash
pip install -r requirements.txt
cp .env.example .env
pytest
```

## Development workflow

- `python cli.py generate-data` — generate a synthetic labelled dataset
- `python cli.py train` — train the ensemble on synthetic data
- `python cli.py serve --reload` — run the local API while iterating

## Before opening a PR

- `pytest` passes
- `ruff check .` passes
- New features include tests
- Documentation (`README.md`) is updated for any user-facing change

## Cross-repo changes

If a change affects the `RiskScore` schema, the `Trade`/`Asset`/`OrderBookEvent`
schemas, or any of the environment variables listed in `.env.example`, call
this out in your PR description — these are shared contracts with
`ledgerlens-api`, `ledgerlens-contracts`, and `ledgerlens-dashboard`. See the
"LedgerLens Organization" section of `README.md` for details.
