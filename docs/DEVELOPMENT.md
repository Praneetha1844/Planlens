# Development guide

## Setup

Python 3.12 or newer.

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,db]"
make check          # ruff, mypy (strict), pytest
```

The test suite needs no database and no network: plans are hand-written JSON in `tests/fixtures`, and the benchmark and hypopg tests use scripted cursors.

## Adding a detector

1. Write `detect_<name>(plan: Plan, limits: Thresholds) -> list[Finding]` in `findings.py` and give it a code constant.
2. Add it to `DETECTORS`.
3. Give every finding a `node_path` taken from `node.path`, a plain-English message, a suggestion and a `confidence` (`measured` or `estimated`).
4. Add a hand-written fixture or an inline plan in the tests, covering the case that should fire, the case that should not, and any threshold you added.
5. Document it in the README table and in [SQL_NOTES.md](SQL_NOTES.md).

If the finding should lead to an index, handle its code in `advisor.suggest_indexes`.

## Adding a fixture

Write a small JSON file in the shape of `EXPLAIN (FORMAT JSON)` output and keep the numbers illustrative. Label it as hand-written in `tests/fixtures/README.md`. Prefer capturing a real plan from PostgreSQL when you have one, and say which version it came from.

## Conventions

- Typed code; `ruff` and strict `mypy` must be clean.
- The core library stays dependency-free. Database code goes behind the `db` extra and uses the small cursor protocols in `bench.py` and `whatif.py`.
- Conventional commit prefixes (`feat`, `fix`, `docs`, `test`, `chore`, `ci`).
- Never publish benchmark numbers that were not measured, and never commit credentials.

## Running the benchmark

See [benchmark/README.md](../benchmark/README.md). The harness creates and drops indexes, so point it only at a disposable database.
