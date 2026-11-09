"""Optional what-if evaluation with the `hypopg` extension.

hypopg creates hypothetical indexes that exist only in planner memory, so the planner's cost
for a query can be compared with and without a suggested index, without building anything.
It needs a PostgreSQL server with the extension installed and a DB-API cursor (for example
from `psycopg`). Costs are planner estimates, not measured times, and `EXPLAIN ANALYZE` is not
used. See docs/adr/0001-heuristics-before-hypopg.md.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from .advisor import IndexSuggestion
from .plan import parse_explain

_READ_ONLY = re.compile(r"^\s*(SELECT|WITH|VALUES|TABLE)\b", re.IGNORECASE)
_LITERALS = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"")
# EXPLAIN ANALYZE executes the statement, so a data-modifying CTE (WITH ... DELETE ...) or
# SELECT ... FOR UPDATE must not get through just because the text starts with WITH or SELECT.
_MODIFYING = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE|GRANT|REVOKE|COPY|CALL|VACUUM|"
    r"REINDEX|REFRESH)\b",
    re.IGNORECASE,
)


class Cursor(Protocol):
    """The slice of a DB-API cursor this module uses."""

    def execute(self, query: str, params: Sequence[object] | None = None) -> object: ...

    def fetchone(self) -> Sequence[object] | None: ...


@dataclass(frozen=True)
class WhatIfResult:
    """Planner cost of one query without and with a hypothetical index."""

    base_cost: float
    with_index_cost: float

    @property
    def improvement(self) -> float:
        """Fractional cost reduction (0.4 means 40% cheaper). Negative if the plan got worse."""
        return 0.0 if self.base_cost <= 0 else 1.0 - self.with_index_cost / self.base_cost


def check_query(sql: str) -> str:
    """Return `sql` without a trailing semicolon, or raise if it is not one read-only statement."""
    text = sql.strip().rstrip(";").strip()
    if not _READ_ONLY.match(text) or ";" in text:
        raise ValueError("query must be a single SELECT, WITH, VALUES or TABLE statement")
    if _MODIFYING.search(_LITERALS.sub("''", text)):
        raise ValueError(
            "query contains a data-modifying or locking keyword (INSERT, UPDATE, DELETE, ...); "
            "only plain read-only queries are accepted"
        )
    return text


def explain_cost(cursor: Cursor, sql: str) -> float:
    """Planner total cost of `sql` (plain EXPLAIN, nothing is executed)."""
    cursor.execute(f"EXPLAIN (FORMAT JSON) {check_query(sql)}")
    row = cursor.fetchone()
    if not row:
        raise RuntimeError("EXPLAIN returned no rows")
    value = row[0]
    if not isinstance(value, str | bytes | list | dict):
        raise RuntimeError(f"unexpected EXPLAIN result type: {type(value).__name__}")
    return parse_explain(value).root.total_cost


def evaluate_index(cursor: Cursor, sql: str, suggestion: IndexSuggestion) -> WhatIfResult:
    """Compare planner cost with and without `suggestion`. Always resets hypopg afterwards."""
    cursor.execute("SELECT hypopg_reset()")
    try:
        base = explain_cost(cursor, sql)
        cursor.execute("SELECT * FROM hypopg_create_index(%s)", (suggestion.hypopg_ddl,))
        with_index = explain_cost(cursor, sql)
    finally:
        cursor.execute("SELECT hypopg_reset()")
    return WhatIfResult(base_cost=base, with_index_cost=with_index)
