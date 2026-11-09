"""Parsing EXPLAIN (FORMAT JSON) into a plan tree."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from planlens.plan import Plan, PlanParseError, parse_explain


def test_parses_single_node_with_actuals(plan_of: Callable[[str], Plan]) -> None:
    plan = plan_of("seq_scan_filter")
    assert plan.analyzed
    assert plan.root.node_type == "Seq Scan"
    assert plan.root.relation == "orders"
    assert plan.root.rows_removed_by_filter == 95037
    assert plan.execution_time_ms == 18.9
    assert plan.planning_time_ms == 0.12


def test_plain_explain_has_no_actuals(plan_of: Callable[[str], Plan]) -> None:
    plan = plan_of("seq_scan_estimate_only")
    assert not plan.analyzed
    assert plan.root.total_actual_rows is None
    assert plan.execution_time_ms is None


def test_children_and_paths(plan_of: Callable[[str], Plan]) -> None:
    plan = plan_of("nested_loop_seq")
    outer, inner = plan.root.children
    assert outer.parent_relationship == "Outer"
    assert inner.parent_relationship == "Inner"
    assert inner.path == "Nested Loop > Seq Scan on order_items i (inner)"
    assert [n.node_type for n in plan.nodes()] == ["Nested Loop", "Seq Scan", "Seq Scan"]


def test_total_actual_rows_multiplies_by_loops(plan_of: Callable[[str], Plan]) -> None:
    inner = plan_of("nested_loop_seq").root.children[1]
    assert inner.total_actual_rows == 300000 * 150


def test_sort_fields(plan_of: Callable[[str], Plan]) -> None:
    sort = plan_of("sort_spill").root.children[0]
    assert sort.sort_keys == ("orders.created_at DESC",)
    assert sort.sort_space_type == "Disk"
    assert sort.sort_space_used_kb == 14240


def test_accepts_decoded_values_and_bare_objects() -> None:
    raw = {"Plan": {"Node Type": "Result", "Total Cost": 0.01}}
    assert parse_explain(raw).root.node_type == "Result"
    assert parse_explain([raw]).root.node_type == "Result"
    assert parse_explain(json.dumps([raw]).encode()).root.node_type == "Result"


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        "[]",
        "{}",
        '{"Plan": []}',
        '[{"Plan": {"Total Cost": 1}}]',
        '[{"Plan": {"Node Type": "Seq Scan", "Total Cost": "high"}}]',
        '[{"Plan": {"Node Type": "Sort", "Sort Key": "x"}}]',
        '[{"Plan": {"Node Type": "Append", "Plans": 3}}]',
        '[{"Plan": {"Node Type": "Append", "Plans": [1]}}]',
    ],
)
def test_rejects_malformed_input(bad: str) -> None:
    with pytest.raises(PlanParseError):
        parse_explain(bad)
