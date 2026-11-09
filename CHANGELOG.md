# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- Sibling plan nodes that share a label (for example two scans of one table under an `Append`) now get unique paths, so findings and index suggestions can no longer attach to the wrong node.
- `estimate_mismatch` no longer reports nodes that never ran (`Actual Loops: 0`) or nodes that produced fewer rows than planned below a `LIMIT`.
- `bench` and the what-if adapter reject data-modifying and locking statements (for example `WITH ... DELETE ...` and `FOR UPDATE`), which `EXPLAIN ANALYZE` would have executed.
- `bench` drops its index with the table's schema and also when `ANALYZE` fails.
- `Thresholds` validates `high_loops` and `estimate_only_cost`.

### Added
- Documentation: index, CLI reference, library API reference, development guide, glossary and `SECURITY.md`.
- Project URLs in package metadata and a `.dockerignore`.

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
