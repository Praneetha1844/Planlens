# SQL notes

Background used by Planlens: how a plan relates to relational algebra, how the PostgreSQL planner costs a plan, and the principles behind the index suggestions. These are working notes, not a substitute for the PostgreSQL documentation (chapters on *Using EXPLAIN*, *Planner/Optimizer* and *Indexes*).

## 1. Plan nodes as relational algebra

A plan is a tree of physical operators. Each corresponds to a logical operation from relational algebra (σ selection, π projection, ⋈ join, γ grouping, δ duplicate elimination, τ ordering).

| Plan node | Logical operation | Physical idea |
|---|---|---|
| `Seq Scan` with `Filter` | σ(condition) over a relation | Read every page of the table, test the condition on each row |
| `Index Scan`, `Index Only Scan` | σ over a relation | Use a btree to find matching rows without reading the whole table |
| `Bitmap Index Scan` + `Bitmap Heap Scan` | σ, possibly combining several indexes with AND / OR | Build a bitmap of matching pages first, then read them in physical order |
| `Nested Loop` | R ⋈ S | For each outer row, probe the inner side. Cheap if the outer side is small and the inner side has an index |
| `Hash Join` | R ⋈ S (equality) | Build a hash table on one input, probe it with the other |
| `Merge Join` | R ⋈ S (equality) | Walk two inputs sorted on the join key together |
| `Sort` | τ (ordering; an extension of the basic algebra) | In memory (quicksort) or on disk (external merge) when it exceeds `work_mem` |
| `Aggregate`, `HashAggregate`, `GroupAggregate` | γ | Hash or sort to form groups |
| `Unique` | δ | Remove adjacent duplicates in sorted input |
| `Limit` | Top-N cut-off | Stops pulling rows early; may let the planner prefer a plan with a low startup cost |

Projection (π) is not a separate node: the planner carries only the needed columns (`Plan Width`).

A join order is an algebra rewrite: ⋈ is commutative and associative, so the planner searches orderings and picks the cheapest by estimated cost.

## 2. Reading a plan

- **Cost** is a pair `startup..total` in arbitrary planner units; a parent's cost includes its children.
- **`Plan Rows`** is the estimate; **`Actual Rows`** (with `ANALYZE`) is measured. Both are **per loop**: a node with `Actual Loops: 150` ran 150 times, so total rows = `Actual Rows × Actual Loops`. Planlens applies this multiplication.
- **`Rows Removed by Filter`** counts rows read and then discarded by a filter. A large number next to a small `Actual Rows` is the signature of a missing index.
- **Inner / outer**: in a join node, the first child is the outer side; the second is the inner side, which a nested loop executes once per outer row.

## 3. Cost model basics

PostgreSQL estimates cost from table statistics and a few configurable constants. Defaults:

| Parameter | Default | Meaning |
|---|---|---|
| `seq_page_cost` | 1.0 | Reading a page sequentially |
| `random_page_cost` | 4.0 | Reading a page at a random location (often lowered on SSDs) |
| `cpu_tuple_cost` | 0.01 | Processing one row |
| `cpu_index_tuple_cost` | 0.005 | Processing one index entry |
| `cpu_operator_cost` | 0.0025 | Evaluating one operator or function |

For a sequential scan the total cost is approximately

```
pages × seq_page_cost + rows × cpu_tuple_cost + rows × (number of filter operators) × cpu_operator_cost
```

An index scan is charged for walking the index plus (mostly random) heap page fetches, so it wins when the filter is selective and loses when it matches a large share of the table. That is why a tiny table can stay a sequential scan even with an index.

**Selectivity** (the fraction of rows a condition keeps) comes from `pg_statistic`: most-common values, histograms and the null fraction, refreshed by `ANALYZE`. Two known weak spots:

- Conditions on several columns are assumed **independent**, so correlated columns (city and country) are underestimated. `CREATE STATISTICS` (extended statistics) can describe the correlation.
- Stale statistics after bulk changes skew every estimate. Run `ANALYZE` after loading or deleting large amounts of data.

Large gaps between `Plan Rows` and `Actual Rows` (the `estimate_mismatch` finding) usually point to one of these.

## 4. Index selection principles

These are the rules the advisor encodes, and where it stops.

1. **Index what the query filters, joins or sorts on.** Foreign keys are not indexed automatically in PostgreSQL; a join from the referenced side to the referencing table often needs an index on the foreign-key column.
2. **Equality columns before range columns.** A btree can use a prefix of equality conditions plus one range condition on the next column. Columns after the first range column cannot narrow the scan. `(status, created_at)` serves `status = 'open' AND created_at >= ...`; `(created_at, status)` mostly does not.
3. **Selectivity matters.** An index on a column with few distinct values (a boolean, a four-value status) helps only when the sought value is rare. Combining it with a more selective column, or with a partial index, is usually better.
4. **Order for sorting.** A btree can be scanned forwards or backwards, so one direction serves both `ASC` and `DESC` for a single column. For multiple sort columns with mixed directions the index needs the same mixed directions.
5. **Every index costs writes and space.** Inserts, updates of indexed columns and deletes maintain each index. More indexes means slower writes, more disk and more vacuum work. Drop unused indexes (`pg_stat_user_indexes`).
6. **A longer index can replace a shorter one.** An index on `(a, b)` serves lookups on `a`; a separate index on `(a)` is usually redundant. The advisor removes such prefix duplicates.
7. **Build safely.** `CREATE INDEX CONCURRENTLY` avoids blocking writes but is slower and cannot run in a transaction. It can leave an invalid index if it fails; check `pg_index.indisvalid`.
8. **Verify.** After creating an index, run `ANALYZE` and compare the plan and timing. The planner may still choose a sequential scan, and that can be correct.

What Planlens does **not** suggest: partial indexes, covering indexes (`INCLUDE`) for index-only scans, expression indexes, multicolumn indexes for `OR` conditions, and non-btree access methods (GIN for arrays and full text, GiST and BRIN for ranges and very large ordered tables).

## 5. Why each detector exists

| Detector | Reasoning |
|---|---|
| `seq_scan_selective` | Reading every row to keep a few is wasted I/O; a selective filter is the textbook case for an index. Needs `Rows Removed by Filter` to be sure. |
| `missing_join_index` | A nested loop over an unindexed inner table costs outer rows × table size. An index on the join column turns each probe into a lookup. |
| `sort_spill` | An external merge sort writes to disk. Either the data needs less sorting (an index that already returns rows in order) or the sort needs more memory. |
| `nested_loop_high_loops` | Even cheap probes add up at hundreds of thousands of loops; usually the planner under-estimated the outer side. |
| `estimate_mismatch` | Every later decision depends on row estimates, so a 10× error can change join order and method. |
| `redundant_sort` | A sort whose output is immediately re-sorted does work that is thrown away. |
