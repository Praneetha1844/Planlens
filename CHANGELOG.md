# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0]

### Added
- Parser for `EXPLAIN (FORMAT JSON)` into a typed plan tree, with readable node paths.
- Reader for `Filter`, `Join Filter` and `Sort Key` expressions.
- Six detectors: selective sequential scan, missing join index, sort spill, high-loop nested loop, row-estimate mismatch and redundant sort.
- Heuristic btree index advisor: column ordering, direction, de-duplication, existing-index suppression, safe identifier quoting and DDL generation.
- Markdown, HTML (escaped) and JSON reports.
- Optional hypopg what-if cost comparison.
- Seeded synthetic data generator, demo schema, five slow-query examples and a before/after benchmark harness.
- Command line: `planlens analyze`, `gen` and `bench`.
- Test suite on hand-written plan fixtures; architecture notes, SQL notes, data model and four ADRs.

### Known limits
- Fixtures are hand-written, not captured from a server.
- No benchmark results are published.
