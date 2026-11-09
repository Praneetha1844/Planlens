"""Benchmark harness: time a query before and after applying its index.

Each `.sql` file in a queries directory carries one header line naming the index to test:

    -- planlens-index: CREATE INDEX idx_orders_customer_id ON orders (customer_id);

For every query the harness runs `EXPLAIN (ANALYZE, FORMAT JSON)` `repeat` times, creates the
index, runs it `repeat` times again, then drops the index. Every run is written to the CSV; the
repository ships no results. Use a disposable database: the harness creates and drops indexes.

The connection must be in autocommit mode (`CREATE INDEX CONCURRENTLY` cannot run in a
transaction). Warm-cache effects are not controlled; look at the spread, not one number.
"""

from __future__ import annotations

import csv
import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .plan import parse_explain
from .whatif import check_query

FIELDS = ("query", "phase", "run", "execution_ms", "plan_cost", "index_ddl")

_HEADER = re.compile(r"^--\s*planlens-index:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_DDL = re.compile(
    r"^CREATE INDEX (?:CONCURRENTLY )?(?P<name>[A-Za-z_][A-Za-z0-9_]*) ON "
    r"(?P<table>[A-Za-z_\".][\w\".]*) \([\w\" ,]+\);?$",
    re.IGNORECASE,
)


class Cursor(Protocol):
    """The slice of a DB-API cursor this module uses."""

    def execute(self, query: str, params: Sequence[object] | None = None) -> object: ...

    def fetchone(self) -> Sequence[Any] | None: ...


class Connection(Protocol):
    def cursor(self) -> Any: ...


@dataclass(frozen=True)
class BenchQuery:
    """A query and the single index to compare it against."""

    name: str
    sql: str
    index_ddl: str

    @property
    def index_name(self) -> str:
        return _parse_ddl(self.index_ddl)[0]

    @property
    def table(self) -> str:
        return _parse_ddl(self.index_ddl)[1]


def _parse_ddl(ddl: str) -> tuple[str, str]:
    match = _DDL.match(ddl.strip())
    if not match:
        raise ValueError(f"unsupported index statement (expected a plain CREATE INDEX): {ddl!r}")
    return match["name"], match["table"]


def load_queries(directory: Path) -> list[BenchQuery]:
    """Load every `*.sql` file, requiring a `planlens-index` header and a read-only query."""
    if not directory.is_dir():
        raise FileNotFoundError(f"queries directory not found: {directory}")
    queries: list[BenchQuery] = []
    for path in sorted(directory.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        header = _HEADER.search(text)
        if not header:
            raise ValueError(f"{path.name}: missing a '-- planlens-index: CREATE INDEX ...' header")
        ddl = header.group(1)
        _parse_ddl(ddl)  # validate early
        body = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("--")
        )
        queries.append(BenchQuery(name=path.stem, sql=check_query(body), index_ddl=ddl))
    if not queries:
        raise FileNotFoundError(f"no .sql files in {directory}")
    return queries


def _timed_run(cursor: Cursor, sql: str) -> tuple[float, float]:
    cursor.execute(f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}")
    row = cursor.fetchone()
    if not row:
        raise RuntimeError("EXPLAIN returned no rows")
    plan = parse_explain(row[0])
    if plan.execution_time_ms is None:
        raise RuntimeError("EXPLAIN ANALYZE output had no 'Execution Time'")
    return plan.execution_time_ms, plan.root.total_cost


def run_benchmark(
    connection: Connection, queries: list[BenchQuery], *, repeat: int = 5
) -> list[dict[str, object]]:
    """Run every query `repeat` times before and after its index. Returns one row per run."""
    if repeat < 1:
        raise ValueError("repeat must be >= 1")
    rows: list[dict[str, object]] = []
    cursor = connection.cursor()
    for query in queries:
        for phase in ("before", "after"):
            if phase == "after":
                cursor.execute(query.index_ddl.rstrip(";"))
                cursor.execute(f"ANALYZE {query.table}")
            try:
                for run in range(1, repeat + 1):
                    millis, cost = _timed_run(cursor, query.sql)
                    rows.append(
                        {
                            "query": query.name,
                            "phase": phase,
                            "run": run,
                            "execution_ms": round(millis, 3),
                            "plan_cost": round(cost, 2),
                            "index_ddl": query.index_ddl if phase == "after" else "",
                        }
                    )
            finally:
                if phase == "after":
                    cursor.execute(f"DROP INDEX IF EXISTS {query.index_name}")
    return rows


def write_csv(rows: list[dict[str, object]], out: Path) -> None:
    """Write benchmark rows with a header."""
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def summarise(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Median execution time per query and phase, for a quick look at the CSV."""
    grouped: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        key = (str(row["query"]), str(row["phase"]))
        grouped.setdefault(key, []).append(float(str(row["execution_ms"])))
    return [
        {"query": q, "phase": p, "runs": len(v), "median_ms": round(statistics.median(v), 3)}
        for (q, p), v in sorted(grouped.items())
    ]
