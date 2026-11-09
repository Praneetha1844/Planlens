# Glossary

| Term | Meaning |
|---|---|
| **Plan** | The tree of operations PostgreSQL chooses to run a query. |
| **Node** | One operation in a plan, such as a Seq Scan or a Nested Loop. |
| **Node path** | A readable, unique address for a node, for example `Nested Loop > Seq Scan on order_items i (inner)`. |
| **EXPLAIN** | Shows the planner's chosen plan and cost estimates without running the query. |
| **EXPLAIN ANALYZE** | Runs the query and adds measured rows, loops and times. It executes the statement. |
| **Plan Rows / Actual Rows** | The planner's estimate and the measured count. Both are averages per loop. |
| **Loops** | How many times a node ran. Total rows are `Actual Rows` times `Actual Loops`. |
| **Seq Scan** | Reads every row of a table. |
| **Index Scan / Index Only Scan** | Uses an index to find rows (and, for index-only, to return them). |
| **Nested Loop** | For each outer row, probes the inner side. Fast with an index, slow with a sequential scan. |
| **Work_mem** | Memory a sort or hash may use before spilling to disk. |
| **Sort spill** | A sort that did not fit in `work_mem` and used temporary files (`Sort Space Type: Disk`). |
| **Selectivity** | The fraction of rows a condition keeps. A selective filter keeps few rows. |
| **btree index** | The default index type. Supports equality and range lookups and ordered scans. |
| **Equality column / range column** | A column compared with `=` versus `<`, `>`, `BETWEEN`. In a composite index, equality columns come first, then one range column. |
| **Finding** | One anti-pattern the detectors report, tied to a node. |
| **Confidence** | `measured` when the plan has `ANALYZE` data, `estimated` when it does not. |
| **Score** | A heuristic ranking between 0 and 1 for an index suggestion. Not a predicted speedup. |
| **hypopg** | A PostgreSQL extension that creates hypothetical indexes visible only to the planner. |
| **Fixture** | A hand-written plan used in tests. |
