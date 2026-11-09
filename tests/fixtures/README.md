# Plan fixtures

These JSON files are **hand-written samples** in the shape of PostgreSQL's
`EXPLAIN (FORMAT JSON)` output. They were not captured from a real server, and their numbers
are illustrative. They exist so the analyser can be tested without a database.

| File | Shape it exercises |
|---|---|
| `seq_scan_filter.json` | Seq Scan discarding most rows (equality + range filter), with ANALYZE data |
| `seq_scan_estimate_only.json` | Seq Scan with a filter and no ANALYZE data |
| `nested_loop_seq.json` | Nested Loop whose inner side is a Seq Scan run 150 times |
| `sort_spill.json` | Sort that spilled to disk under a Limit |
| `estimate_mismatch.json` | Planner estimate far below the actual row count |
| `redundant_sort.json` | A Sort directly on top of another Sort |
| `healthy_index_scan.json` | An index scan that should produce no findings |
