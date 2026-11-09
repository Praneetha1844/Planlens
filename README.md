# Planlens

> Read a PostgreSQL `EXPLAIN (FORMAT JSON)` plan, point out the anti-patterns in plain English, and suggest the indexes that might fix them.

**Status: v0.1.0.** The analyser, advisor, report renderers, data generator and benchmark harness are implemented, with a test suite that runs on hand-written plan fixtures and needs no database. Benchmarks are **not yet published**: the repository ships the harness and the queries, not results.

## What it does

```
EXPLAIN (ANALYZE, FORMAT JSON) ...  ->  planlens analyze  ->  findings + index suggestions
```

1. **Parse** the JSON plan into a typed tree ([ADR 0002](docs/adr/0002-parse-explain-json-not-text.md)).
2. **Detect** six anti-patterns, each reported with the plan-node path and an explanation:

| Code | What it flags |
|---|---|
| `seq_scan_selective` | A sequential scan that discards most of the rows it reads |
| `missing_join_index` | A nested loop that rescans an unindexed inner table once per outer row |
| `sort_spill` | A sort that did not fit in `work_mem` and wrote to disk |
| `nested_loop_high_loops` | An indexed nested loop whose inner side ran a very large number of times |
| `estimate_mismatch` | Planner row estimate far from the actual count (either direction) |
| `redundant_sort` | A Sort fed directly by another Sort |

3. **Suggest** btree indexes: equality columns first, then at most one range column; join keys for nested-loop inner scans; sort keys (with direction) for spilled sorts. Existing indexes can be supplied so they are not re-suggested.
4. **Render** the result as Markdown, HTML or JSON.

> **Read this before acting on a suggestion.** Detectors are heuristics over one plan. The index `score` is a ranking signal, not a predicted speedup. Measure with `planlens bench`, or compare planner costs with the optional hypopg adapter, before changing a production database. See [ADR 0001](docs/adr/0001-heuristics-before-hypopg.md).

## Quick start

Requires Python 3.12. The core library has no runtime dependencies.

```bash
pip install -e ".[dev]"           # add ,db for the benchmark harness and hypopg adapter
make check                        # ruff, mypy, pytest

planlens analyze tests/fixtures/seq_scan_filter.json
planlens analyze plan.json --format html --out report.html
planlens analyze plan.json --existing orders:customer_id --format json
```

Get a plan from your database:

```sql
EXPLAIN (ANALYZE, FORMAT JSON) SELECT id, total FROM orders WHERE status = 'open';
```

Use `ANALYZE` when you can: without it Postgres reports only estimates, and findings are marked `estimated`. `EXPLAIN ANALYZE` **executes** the query, so wrap writes in a transaction you roll back.

### Example output (from a hand-written fixture)

```
1. seq_scan_selective (high, measured)
   - Where: `Seq Scan on orders`
   - Sequential scan of orders read 100,000 rows and discarded 95% of them with the filter
     ((status = 'open'::text) AND (created_at >= '2024-06-01'::date)).
   - Suggestion: An index on the filtered column(s) of orders may avoid the scan.

CREATE INDEX CONCURRENTLY idx_orders_status_created_at ON public.orders (status, created_at);
```

The fixture is an illustrative sample, not output captured from a server (see [tests/fixtures](tests/fixtures/README.md)).

## Demo data and benchmark

`planlens gen` writes seeded CSV data for a four-table schema ([data model](docs/DATA_MODEL.md)); `sql/` creates and loads it; `benchmark/queries/` holds five slow-query examples, each naming the index to compare against.

```bash
docker compose up -d db
planlens gen --scale 1 --seed 42 --out data
psql "postgresql://planlens:planlens@localhost:5433/planlens" -f sql/schema.sql -f sql/load.sql
planlens bench --dsn "postgresql://planlens:planlens@localhost:5433/planlens" --yes
```

See [benchmark/README.md](benchmark/README.md). The harness creates and drops indexes, so use a disposable database; `--yes` is required.

## Architecture

```mermaid
flowchart LR
  J[EXPLAIN JSON] --> P[plan.py<br/>typed tree]
  P --> F[findings.py<br/>6 detectors]
  P --> E[expr.py<br/>predicates, sort keys]
  E --> A[advisor.py<br/>index suggestions]
  F --> A
  F --> R[report.py<br/>md / html / json]
  A --> R
  A -.optional.-> W[whatif.py<br/>hypopg cost]
  A -.optional.-> B[bench.py<br/>before / after timing]
```

More in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Background on plans, costs and index design: [docs/SQL_NOTES.md](docs/SQL_NOTES.md).

## Project structure

```
src/planlens/
  plan.py        typed plan tree and EXPLAIN JSON parser
  expr.py        predicates and sort keys from Postgres expression strings
  findings.py    detectors and thresholds
  advisor.py     index suggestions, DDL, naming and quoting
  report.py      Markdown / HTML / JSON renderers
  whatif.py      optional hypopg cost comparison
  bench.py       before / after benchmark harness
  datagen.py     seeded synthetic data
  cli.py         analyze | gen | bench
sql/             demo schema and loader
benchmark/       five slow-query examples
tests/           pytest suite and hand-written plan fixtures
docs/            architecture, SQL notes, data model, ADRs
```

## Limitations

- **Heuristics, not an optimiser.** Detectors look at one plan; they cannot see your workload, write cost, table sizes beyond the plan, or other queries that share an index.
- Only **btree** indexes are suggested. No expression, partial, covering (`INCLUDE`), GIN, GiST or BRIN indexes.
- Conditions are read with a tolerant text reader. Function calls, `OR`, `LIKE` and other expressions are skipped rather than guessed at.
- Sort-index suggestions are made only when the sort sits over a single table and its keys are plain columns.
- `redundant_sort` flags only a Sort directly on another Sort.
- Estimated plans (no `ANALYZE`) carry less information; their findings are labelled and scored lower.
- The score is a ranking heuristic, not a speedup prediction. The hypopg adapter compares planner estimates, not real timings.
- Identifier quoting uses a short list of reserved words, not the full PostgreSQL keyword table.
- Plan fixtures are hand-written, so the test suite checks the logic, not agreement with a real PostgreSQL server. The benchmark harness and the Docker Compose file are written but have not been run in CI.

## Roadmap

See [CHANGELOG.md](CHANGELOG.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#extending). Next: capture real plans from several PostgreSQL versions as fixtures, publish a first benchmark run with its methodology and spread, add partial and covering index suggestions, and read `pg_indexes` directly to find existing indexes.

## License

[MIT](LICENSE) © 2026 Praneetha Potharaju
