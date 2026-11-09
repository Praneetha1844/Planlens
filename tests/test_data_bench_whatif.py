"""Data generator, benchmark harness and what-if adapter (no database needed)."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from planlens.advisor import IndexColumn, IndexSuggestion
from planlens.bench import (
    FIELDS,
    BenchQuery,
    load_queries,
    run_benchmark,
    summarise,
    write_csv,
)
from planlens.datagen import generate
from planlens.whatif import check_query, evaluate_index, explain_cost

ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


# ---- data generator --------------------------------------------------------------------


def test_generation_is_deterministic_and_consistent(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    counts = generate(a, scale=0.002, seed=7)
    assert generate(b, scale=0.002, seed=7) == counts
    for name in ("customers", "products", "orders", "order_items"):
        assert (a / f"{name}.csv").read_bytes() == (b / f"{name}.csv").read_bytes()
    generate(tmp_path / "c", scale=0.002, seed=8)
    assert (a / "orders.csv").read_bytes() != (tmp_path / "c" / "orders.csv").read_bytes()


def test_foreign_keys_and_totals_hold(tmp_path: Path) -> None:
    counts = generate(tmp_path, scale=0.002, seed=1)
    orders = read(tmp_path / "orders.csv")
    items = read(tmp_path / "order_items.csv")
    assert len(orders) == counts["orders"]
    assert len(items) == counts["order_items"]
    assert all(1 <= int(o["customer_id"]) <= counts["customers"] for o in orders)
    assert all(1 <= int(i["product_id"]) <= counts["products"] for i in items)
    order_ids = {o["id"] for o in orders}
    assert all(i["order_id"] in order_ids for i in items)
    first = orders[0]
    cents = sum(
        round(float(i["unit_price"]) * 100) * int(i["quantity"])
        for i in items
        if i["order_id"] == first["id"]
    )
    assert round(float(first["total"]) * 100) == cents


def test_minimum_one_row_and_invalid_scale(tmp_path: Path) -> None:
    counts = generate(tmp_path, scale=0.00001)
    assert min(counts.values()) >= 1
    with pytest.raises(ValueError):
        generate(tmp_path, scale=0)


# ---- benchmark harness -----------------------------------------------------------------


def test_bundled_queries_load_and_validate() -> None:
    queries = load_queries(ROOT / "benchmark" / "queries")
    assert len(queries) == 5
    assert all(q.index_ddl.upper().startswith("CREATE INDEX") for q in queries)
    assert {"customer_orders", "order_items_join"} <= {q.name for q in queries}


def test_query_without_header_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "q.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(ValueError, match="planlens-index"):
        load_queries(tmp_path)


@pytest.mark.parametrize(
    "header",
    [
        "DROP TABLE orders",
        "CREATE INDEX i ON t (a); DROP TABLE t",
        "CREATE UNIQUE INDEX i ON t (a)",
    ],
)
def test_unsafe_index_statements_are_rejected(tmp_path: Path, header: str) -> None:
    (tmp_path / "q.sql").write_text(f"-- planlens-index: {header}\nSELECT 1;", encoding="utf-8")
    with pytest.raises(ValueError):
        load_queries(tmp_path)


def test_non_select_query_is_rejected(tmp_path: Path) -> None:
    text = "-- planlens-index: CREATE INDEX i ON t (a);\nDELETE FROM t;"
    (tmp_path / "q.sql").write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        load_queries(tmp_path)


class ScriptedCursor:
    """Records statements and answers EXPLAIN calls with canned JSON plans."""

    def __init__(self, times: list[float]) -> None:
        self.statements: list[str] = []
        self._times = list(times)
        self._row: Sequence[Any] | None = None

    def execute(self, query: str, params: Sequence[object] | None = None) -> None:
        self.statements.append(query)
        if query.startswith("EXPLAIN"):
            millis = self._times.pop(0)
            plan = {"Plan": {"Node Type": "Seq Scan", "Total Cost": 10.0}, "Execution Time": millis}
            self._row = ([plan],)

    def fetchone(self) -> Sequence[Any] | None:
        return self._row


class ScriptedConnection:
    def __init__(self, cursor: ScriptedCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> ScriptedCursor:
        return self._cursor


def test_benchmark_runs_before_creates_index_runs_after_and_drops_it(tmp_path: Path) -> None:
    cursor = ScriptedCursor(times=[10.0, 12.0, 1.0, 3.0])
    query = BenchQuery("q1", "SELECT 1", "CREATE INDEX idx_t_a ON t (a);")
    rows = run_benchmark(ScriptedConnection(cursor), [query], repeat=2)

    assert [(r["phase"], r["run"], r["execution_ms"]) for r in rows] == [
        ("before", 1, 10.0),
        ("before", 2, 12.0),
        ("after", 1, 1.0),
        ("after", 2, 3.0),
    ]
    kinds = [s.split()[0] for s in cursor.statements]
    assert kinds == ["EXPLAIN", "EXPLAIN", "CREATE", "ANALYZE", "EXPLAIN", "EXPLAIN", "DROP"]
    assert cursor.statements[-1] == "DROP INDEX IF EXISTS idx_t_a"

    out = tmp_path / "results.csv"
    write_csv(rows, out)
    assert list(read(out)[0].keys()) == list(FIELDS)
    assert summarise(rows) == [
        {"query": "q1", "phase": "after", "runs": 2, "median_ms": 2.0},
        {"query": "q1", "phase": "before", "runs": 2, "median_ms": 11.0},
    ]


def test_index_is_dropped_even_if_a_run_fails() -> None:
    cursor = ScriptedCursor(times=[5.0])  # second EXPLAIN raises IndexError (no canned time)
    query = BenchQuery("q1", "SELECT 1", "CREATE INDEX idx_t_a ON t (a);")
    with pytest.raises(IndexError):
        run_benchmark(ScriptedConnection(cursor), [query], repeat=1)
    assert cursor.statements[-1] == "DROP INDEX IF EXISTS idx_t_a"


def test_repeat_must_be_positive() -> None:
    with pytest.raises(ValueError):
        run_benchmark(ScriptedConnection(ScriptedCursor([])), [], repeat=0)


# ---- hypopg what-if adapter ------------------------------------------------------------


class WhatIfCursor:
    """Answers EXPLAIN with a base cost first, then a lower cost once an index is created."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self._cost = 1000.0
        self._row: Sequence[Any] | None = None

    def execute(self, query: str, params: Sequence[object] | None = None) -> None:
        self.statements.append(query)
        if "hypopg_create_index" in query:
            self._cost = 100.0
        if query.startswith("EXPLAIN"):
            plan = [{"Plan": {"Node Type": "Seq Scan", "Total Cost": self._cost}}]
            self._row = (plan,)

    def fetchone(self) -> Sequence[Any] | None:
        return self._row


def test_what_if_compares_cost_and_always_resets() -> None:
    cursor = WhatIfCursor()
    suggestion = IndexSuggestion(table="orders", columns=(IndexColumn("customer_id"),))
    result = evaluate_index(cursor, "SELECT * FROM orders WHERE customer_id = 1;", suggestion)
    assert (result.base_cost, result.with_index_cost) == (1000.0, 100.0)
    assert result.improvement == pytest.approx(0.9)
    resets = [s for s in cursor.statements if s == "SELECT hypopg_reset()"]
    assert len(resets) == 2
    assert cursor.statements[-1] == "SELECT hypopg_reset()"


@pytest.mark.parametrize(
    "sql",
    ["DELETE FROM t", "SELECT 1; DROP TABLE t", "", "UPDATE t SET a = 1"],
)
def test_what_if_rejects_non_read_only_queries(sql: str) -> None:
    with pytest.raises(ValueError):
        check_query(sql)
    with pytest.raises(ValueError):
        explain_cost(WhatIfCursor(), sql)


def test_check_query_strips_trailing_semicolon() -> None:
    assert check_query("  SELECT 1 ; ") == "SELECT 1"
