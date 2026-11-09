# Command-line reference

```
planlens [--version] {analyze,gen,bench} ...
```

Exit codes: `0` success, `2` invalid input or usage (message on stderr). `argparse` itself exits with `2` on unknown options.

## `planlens analyze PLAN`

Analyse an `EXPLAIN (FORMAT JSON)` file (`-` reads standard input) and print a report.

| Option | Default | Meaning |
|---|---|---|
| `--format {md,html,json}` | `md` | Output format |
| `--out FILE` | stdout | Write the report to a file |
| `--existing TABLE:COL,COL` | none | An index that already exists. Repeatable. A suggestion whose columns are a prefix of an existing index is dropped. |
| `--min-rows N` | `10000` | Rows a sequential scan must read before it is flagged |
| `--mismatch-factor X` | `10` | Ratio between planned and actual rows that counts as a mismatch (must be above 1) |

Examples:

```bash
planlens analyze plan.json
planlens analyze plan.json --format html --out report.html
psql "$DSN" -XAt -c "EXPLAIN (ANALYZE, FORMAT JSON) SELECT ..." | planlens analyze -
planlens analyze plan.json --existing orders:customer_id --existing orders:status,created_at
```

Other thresholds (`min_filtered_fraction`, `estimate_only_cost`, `min_rows_for_mismatch`, `nested_loop_loops`, `high_loops`) are available through the library: see [API.md](API.md).

### JSON report

```json
{
  "summary": {"Plan type": "...", "Root node": "...", "Estimated total cost": "..."},
  "findings": [
    {"code": "seq_scan_selective", "severity": "high", "node_path": "Seq Scan on orders",
     "message": "...", "suggestion": "...", "confidence": "measured", "details": {}}
  ],
  "suggestions": [
    {"name": "idx_orders_status", "table": "orders",
     "columns": [{"name": "status", "descending": false}],
     "reasons": ["..."], "score": 0.9, "score_note": "...", "ddl": "CREATE INDEX CONCURRENTLY ..."}
  ],
  "disclaimer": "..."
}
```

- `severity` is `high`, `medium` or `low`; `confidence` is `measured` (the plan has `ANALYZE` data) or `estimated`.
- `node_path` identifies the node in the plan tree. Siblings that would share a path get a ` #1`, ` #2` suffix.
- `score` is a heuristic ranking between 0 and 1, not a predicted speedup.
- `ddl` uses `CREATE INDEX CONCURRENTLY`, which cannot run inside a transaction block.

## `planlens gen`

Write seeded demo data as CSV for the schema in `sql/schema.sql`.

| Option | Default | Meaning |
|---|---|---|
| `--out DIR` | `data` | Output directory (created if needed) |
| `--scale X` | `1.0` | Multiplier for row counts (must be above 0). At 1.0: 10,000 customers, 500 products, 100,000 orders, about 300,000 items |
| `--seed N` | `42` | The same scale and seed always produce the same files |

## `planlens bench`

Time each query before and after creating its index, then drop the index. **Creates and drops indexes**, so use a disposable database.

| Option | Default | Meaning |
|---|---|---|
| `--dsn DSN` | required | PostgreSQL connection string |
| `--queries DIR` | `benchmark/queries` | Directory of `.sql` files, each with a `-- planlens-index: CREATE INDEX ...` header |
| `--out FILE` | `results.csv` | CSV with one row per run |
| `--repeat N` | `5` | Runs per query and phase |
| `--yes` | off | Required: confirms the database is disposable |

Requires the `db` extra (`pip install "planlens[db]"`). The CSV columns are `query, phase, run, execution_ms, plan_cost, index_ddl`. The repository ships no results.

Rules enforced before any connection is used: every query file needs the header, the header must be a plain `CREATE INDEX` on one table, and the query must be read-only (see the limitations in the [README](../README.md#limitations)).
