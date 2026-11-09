# ADR 0004: Hand-written plan fixtures

Status: accepted, with a known gap

## Context

The detectors and the advisor are tested against plans. Real plans come from a running PostgreSQL server and depend on its version, data and settings.

## Decision

Write small plan fixtures by hand in the shape of `EXPLAIN (FORMAT JSON)` output, one per anti-pattern plus a healthy plan and an estimate-only plan. Label them as hand-written samples ([tests/fixtures/README.md](../../tests/fixtures/README.md)). Keep the numbers round and illustrative.

## Reasons

- Each fixture isolates one behaviour, so a failing test points at one detector.
- The suite runs without a database, in seconds.
- The expected result is known by construction (for example, 100,000 rows scanned and 95% discarded).

## Consequences

- **The suite checks the logic, not agreement with real PostgreSQL.** A fixture can be shaped the way the author expects PostgreSQL to print it, and be wrong. Field names follow the documented JSON format, but the expression strings and node shapes have not been validated against captured output.
- Fixture numbers are not benchmarks and must not be quoted as results.
- The detectors' thresholds have not been tuned on real workloads.

## Follow-up

Capture plans from the demo schema on several PostgreSQL versions, add them as a second set of fixtures, and compare the reader's output with what the server prints. Until then, treat parsing of unusual expressions as unverified.
