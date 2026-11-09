# Benchmark

Demo schema, seeded data and five slow-query examples for trying Planlens on a real PostgreSQL
server. **No results are published in this repository.** Run it yourself to get numbers for
your hardware and PostgreSQL version.

## Set up a disposable database

```bash
docker compose up -d db                       # PostgreSQL on localhost:5433
planlens gen --scale 1 --seed 42 --out data   # ~100k orders, ~300k items
psql "postgresql://planlens:planlens@localhost:5433/planlens" -f sql/schema.sql -f sql/load.sql
```

## Analyse a query's plan

```bash
psql "$DSN" -XAt -c "EXPLAIN (ANALYZE, FORMAT JSON) $(cat benchmark/queries/customer_orders.sql)" \
  > plan.json            # strip the comment lines first if psql complains
planlens analyze plan.json
```

## Time before and after an index

```bash
planlens bench --dsn "$DSN" --queries benchmark/queries --out results.csv --repeat 5 --yes
```

`--yes` is required because the harness creates and drops indexes. Every run is written to the
CSV (`query, phase, run, execution_ms, plan_cost, index_ddl`); a median per query and phase is
printed to the terminal.

## Query headers

Each file starts with `-- planlens-index: CREATE INDEX ...`, the single index to compare
against. The statement must be a plain `CREATE INDEX` on one table; anything else is rejected.

## Reading the results

- Run more than once. The first run after loading data is affected by cold caches.
- A smaller plan cost does not guarantee a faster query, and the reverse. `category_price_filter`
  is included because `products` is small and the planner may keep a sequential scan.
- Results depend on data volume, `work_mem`, hardware and PostgreSQL version.
