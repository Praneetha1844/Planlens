# Library API

The core library uses only the standard library. `psycopg` is needed only for `bench` and the optional hypopg adapter.

```python
from planlens.plan import parse_explain
from planlens.findings import analyze, Thresholds
from planlens.advisor import suggest_indexes
from planlens.report import render_markdown

plan = parse_explain(open("plan.json", encoding="utf-8").read())
limits = Thresholds(min_rows_scanned=50_000)
findings = analyze(plan, limits)
suggestions = suggest_indexes(plan, findings, existing=[("orders", ("customer_id",))])
print(render_markdown(plan, findings, suggestions))
```

## `planlens.plan`

| Name | Description |
|---|---|
| `parse_explain(data)` | Accepts JSON text, bytes, or the decoded list or dict. Returns a `Plan`. Raises `PlanParseError` for anything else. |
| `Plan` | `root`, `planning_time_ms`, `execution_time_ms`, `analyzed`, `nodes()` |
| `PlanNode` | Fields from the Postgres JSON (`node_type`, `relation`, `alias`, `filter`, `join_filter`, `sort_keys`, `plan_rows`, `actual_rows`, `actual_loops`, ...), plus `children`, a unique `path`, `label`, `is_scan`, `total_actual_rows` and `walk()` |

Row counts keep Postgres's meaning: averages **per loop**. `total_actual_rows` multiplies by the loop count.

## `planlens.findings`

`analyze(plan, limits=None)` runs the six detectors and returns `Finding` objects, most severe first.

| Threshold | Default | Used by |
|---|---|---|
| `min_rows_scanned` | 10,000 | `seq_scan_selective` |
| `min_filtered_fraction` | 0.9 (range 0 to 1) | `seq_scan_selective` |
| `estimate_only_cost` | 1,000 | `seq_scan_selective` on plans without `ANALYZE` |
| `mismatch_factor` | 10 (above 1) | `estimate_mismatch` |
| `min_rows_for_mismatch` | 100 | `estimate_mismatch` |
| `nested_loop_loops` | 100 | `missing_join_index` |
| `high_loops` | 100,000 | `nested_loop_high_loops` |

`Thresholds` validates its values and raises `ValueError` for impossible ones.

## `planlens.advisor`

`suggest_indexes(plan, findings=None, *, existing=(), limits=None)` returns `IndexSuggestion` objects ordered by score. Each has `table`, `schema`, `columns` (`IndexColumn(name, descending)`), `reasons`, `score`, `node_paths`, `name` (deterministic, at most 63 characters), `ddl` and `hypopg_ddl`. Identifiers are quoted unless they are plain lower-case non-reserved names.

## `planlens.report`

`render_markdown`, `render_html` (all plan-derived text is escaped) and `render_json`, each taking `(plan, findings, suggestions)`.

## `planlens.whatif` (optional, needs `hypopg`)

`evaluate_index(cursor, sql, suggestion)` compares planner cost with and without a hypothetical index and always resets hypopg afterwards. `check_query(sql)` returns the statement without a trailing semicolon, or raises `ValueError` if it is not a single read-only query.

## `planlens.bench` (optional, needs `psycopg`)

`load_queries(directory)`, `run_benchmark(connection, queries, repeat=5)`, `summarise(rows)` and `write_csv(rows, path)`. The connection must be in autocommit mode.

## `planlens.datagen`

`generate(out_dir, scale=1.0, seed=42)` writes four CSV files and returns the row counts.
