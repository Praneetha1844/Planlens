# ADR 0001: Heuristics first, hypopg as an optional check

Status: accepted

## Context

To recommend an index we must predict whether it would help a query. Three approaches exist:

1. **Heuristics over the plan.** Rules such as "a scan that discards 90% of its rows suggests an index on the filter columns."
2. **What-if planning with `hypopg`.** Create a hypothetical index in planner memory and compare planner cost with and without it.
3. **Build the index and measure.** The only way to get real timings.

## Decision

Make heuristics the default. They run on a plan alone, with no database connection, so Planlens can analyse a plan pasted from a ticket or a log. Provide hypopg and real measurement as optional, separate steps:

- `planlens.whatif` compares planner **costs** through a cursor. It needs a server with the extension, and uses plain `EXPLAIN` so nothing runs.
- `planlens bench` builds the index, times the query before and after, and drops the index. It needs a disposable database and an explicit `--yes`.

The advisor's `score` is documented as a ranking signal ("share of plan cost under the node, scaled by rows discarded"), never as a predicted speedup.

## Consequences

- The tool works offline and can be tested with fixtures.
- Suggestions can be wrong: the heuristics ignore the workload, write cost and data skew. Reports and the README say so.
- hypopg costs are planner estimates; they share the planner's statistics errors. They cannot detect that an index would be unused because of stale statistics.
- hypopg is not available on every managed PostgreSQL service, which is another reason it cannot be a requirement.
- Real timing is noisy (cache state, hardware). The harness records every run rather than one number.

## Revisit when

A reliable way to estimate speedup from the plan alone exists, or when reading `pg_stat_statements` makes workload-aware ranking possible.
