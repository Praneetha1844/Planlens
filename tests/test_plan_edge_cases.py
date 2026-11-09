"""Edge cases found while reviewing the parser and detectors. Plans here are hand-written."""

from __future__ import annotations

from typing import Any

import pytest

from planlens.findings import ESTIMATE_MISMATCH, Thresholds, analyze
from planlens.plan import parse_explain
from planlens.whatif import check_query


def scan(rows_plan: float, rows_actual: float, loops: int = 1, **extra: Any) -> dict[str, Any]:
    """A Seq Scan node with actual row data."""
    return {
        "Node Type": "Seq Scan",
        "Relation Name": "orders",
        "Alias": "orders",
        "Total Cost": 100.0,
        "Plan Rows": rows_plan,
        "Actual Rows": rows_actual,
        "Actual Loops": loops,
        **extra,
    }


def wrap(root: dict[str, Any]) -> Any:
    return parse_explain([{"Plan": root, "Execution Time": 1.0}])


def mismatch_messages(plan: Any) -> list[str]:
    return [f.message for f in analyze(plan) if f.code == ESTIMATE_MISMATCH]


# ---- node paths must be unique ---------------------------------------------------------


def test_sibling_nodes_with_the_same_label_get_distinct_paths() -> None:
    first = {**scan(10, 10), "Plans": [{"Node Type": "Result", "Total Cost": 1.0}]}
    second = scan(10, 10)
    plan = wrap({"Node Type": "Append", "Total Cost": 10.0, "Plans": [first, second]})
    a, b = plan.root.children
    assert a.path == "Append > Seq Scan on orders #1"
    assert b.path == "Append > Seq Scan on orders #2"
    assert a.children[0].path == "Append > Seq Scan on orders #1 > Result"
    assert len({node.path for node in plan.nodes()}) == 3


def test_distinct_siblings_keep_plain_paths() -> None:
    other = {**scan(10, 10), "Relation Name": "customers", "Alias": "customers"}
    plan = wrap({"Node Type": "Append", "Total Cost": 10.0, "Plans": [scan(10, 10), other]})
    assert [c.path for c in plan.root.children] == [
        "Append > Seq Scan on orders",
        "Append > Seq Scan on customers",
    ]


# ---- estimate mismatch false positives -------------------------------------------------


def test_node_that_never_ran_is_not_compared_with_its_estimate() -> None:
    root = {
        "Node Type": "Nested Loop",
        "Total Cost": 500.0,
        "Plan Rows": 1,
        "Actual Rows": 0,
        "Actual Loops": 1,
        "Plans": [scan(5000, 0, loops=0, **{"Parent Relationship": "Inner"})],
    }
    assert mismatch_messages(wrap(root)) == []


def test_overestimate_is_reported_when_the_node_did_run() -> None:
    (message,) = mismatch_messages(wrap(scan(5000, 1)))
    assert "overestimated" in message


def test_fewer_rows_than_planned_below_a_limit_is_expected() -> None:
    root = {
        "Node Type": "Limit",
        "Total Cost": 10.0,
        "Plan Rows": 10,
        "Actual Rows": 10,
        "Actual Loops": 1,
        "Plans": [scan(5000, 10)],
    }
    assert mismatch_messages(wrap(root)) == []


def test_underestimate_below_a_limit_is_still_reported() -> None:
    root = {
        "Node Type": "Limit",
        "Total Cost": 10.0,
        "Plan Rows": 10,
        "Actual Rows": 10,
        "Actual Loops": 1,
        "Plans": [scan(10, 5000)],
    }
    (message,) = mismatch_messages(wrap(root))
    assert "underestimated" in message


# ---- thresholds ------------------------------------------------------------------------


@pytest.mark.parametrize("kwargs", [{"high_loops": 0}, {"estimate_only_cost": -1.0}])
def test_more_invalid_thresholds_raise(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        Thresholds(**kwargs)  # type: ignore[arg-type]


# ---- read-only query check -------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "WITH gone AS (DELETE FROM orders RETURNING id) SELECT * FROM gone",
        "SELECT * FROM orders FOR UPDATE",
        "SELECT * FROM orders; DROP TABLE orders",
    ],
)
def test_data_modifying_or_locking_queries_are_rejected(sql: str) -> None:
    with pytest.raises(ValueError):
        check_query(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM orders WHERE note = 'please update me'",
        'SELECT "update" FROM orders',
        "WITH recent AS (SELECT id FROM orders) SELECT * FROM recent",
    ],
)
def test_keywords_inside_literals_and_plain_ctes_are_allowed(sql: str) -> None:
    assert check_query(sql) == sql
