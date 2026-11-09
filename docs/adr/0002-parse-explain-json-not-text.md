# ADR 0002: Parse `EXPLAIN (FORMAT JSON)`, not the text format

Status: accepted

## Context

`EXPLAIN` can print a human-readable text tree or structured output (JSON, YAML, XML). The text format is what people usually paste, and it is what `psql` shows by default.

## Decision

Accept only `EXPLAIN (FORMAT JSON)` output, and parse it into typed dataclasses.

## Reasons

- **Stable structure.** JSON has named fields (`Node Type`, `Relation Name`, `Plan Rows`, `Actual Loops`, `Rows Removed by Filter`). The text format is aimed at people; its layout changes between versions, and parsing it needs regular expressions that break quietly.
- **Machine-readable semantics.** Parent/child relationships, inner/outer sides and per-loop counts are explicit in JSON.
- **Validation is straightforward.** Malformed input raises `PlanParseError` with a specific message instead of producing a half-parsed tree.

## Consequences

- Users must request JSON (`EXPLAIN (ANALYZE, FORMAT JSON)`). The README shows how.
- Conditions inside the JSON (`Filter`, `Join Filter`, `Sort Key`) are still **strings** printed by PostgreSQL's deparser, for example `((status = 'open'::text) AND (created_at >= '2024-06-01'::date))`. `expr.py` is therefore a tolerant text reader for the common shapes. It removes casts and parentheses, splits on top-level `AND`, and treats `OR`, function calls and unfamiliar operators as non-indexable instead of guessing.
- Deparser output can vary by version and by type, so unusual expressions may be classified as `expression` and skipped. This is the safe failure: a missed suggestion, not a wrong one.
- Text-format plans are not supported. A converter could be added later.

## Revisit when

Real plans from several PostgreSQL versions are available as fixtures, which would show how often the reader misclassifies real expressions.
