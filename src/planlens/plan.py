"""Typed plan tree parsed from `EXPLAIN (FORMAT JSON)` output."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

SCAN_TYPES = frozenset(
    {
        "Seq Scan",
        "Index Scan",
        "Index Only Scan",
        "Bitmap Heap Scan",
        "Bitmap Index Scan",
        "Tid Scan",
        "Sample Scan",
    }
)


class PlanParseError(ValueError):
    """The input is not a recognisable EXPLAIN (FORMAT JSON) document."""


@dataclass
class PlanNode:
    """One node of the plan. Row counts follow Postgres: they are averages per loop."""

    node_type: str
    relation: str | None = None
    schema: str | None = None
    alias: str | None = None
    index_name: str | None = None
    join_type: str | None = None
    parent_relationship: str | None = None
    filter: str | None = None
    index_cond: str | None = None
    hash_cond: str | None = None
    merge_cond: str | None = None
    join_filter: str | None = None
    sort_keys: tuple[str, ...] = ()
    sort_method: str | None = None
    sort_space_used_kb: float | None = None
    sort_space_type: str | None = None
    startup_cost: float = 0.0
    total_cost: float = 0.0
    plan_rows: float = 0.0
    actual_rows: float | None = None
    actual_loops: int | None = None
    rows_removed_by_filter: float | None = None
    children: list[PlanNode] = field(default_factory=list)
    path: str = ""

    @property
    def label(self) -> str:
        """Short human name, e.g. `Seq Scan on orders`."""
        text = self.node_type
        if self.relation:
            text += f" on {self.relation}"
            if self.alias and self.alias != self.relation:
                text += f" {self.alias}"
        return text

    @property
    def is_scan(self) -> bool:
        return self.node_type in SCAN_TYPES

    @property
    def has_actuals(self) -> bool:
        return self.actual_rows is not None

    @property
    def total_actual_rows(self) -> float | None:
        """Actual rows across all loops, or None for a plain EXPLAIN."""
        if self.actual_rows is None:
            return None
        return self.actual_rows * (self.actual_loops or 1)

    def walk(self) -> Iterator[PlanNode]:
        """Yield this node and all descendants, parents first."""
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass
class Plan:
    """A parsed plan plus the timing information Postgres reports at the top level."""

    root: PlanNode
    planning_time_ms: float | None = None
    execution_time_ms: float | None = None

    @property
    def analyzed(self) -> bool:
        """True when the plan came from EXPLAIN ANALYZE (it carries actual row counts)."""
        return self.root.has_actuals

    def nodes(self) -> Iterator[PlanNode]:
        return self.root.walk()


def _number(raw: dict[str, Any], key: str) -> float | None:
    value = raw.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise PlanParseError(f"'{key}' must be a number, got {value!r}")
    return float(value)


def _text(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise PlanParseError(f"'{key}' must be a string, got {value!r}")
    return value


def _build(raw: Any, parent_path: str) -> PlanNode:
    if not isinstance(raw, dict):
        raise PlanParseError("a plan node must be a JSON object")
    node_type = raw.get("Node Type")
    if not isinstance(node_type, str) or not node_type:
        raise PlanParseError("plan node is missing 'Node Type'")

    sort_key = raw.get("Sort Key") or []
    if not isinstance(sort_key, list) or not all(isinstance(k, str) for k in sort_key):
        raise PlanParseError("'Sort Key' must be a list of strings")
    loops = _number(raw, "Actual Loops")

    node = PlanNode(
        node_type=node_type,
        relation=_text(raw, "Relation Name"),
        schema=_text(raw, "Schema"),
        alias=_text(raw, "Alias"),
        index_name=_text(raw, "Index Name"),
        join_type=_text(raw, "Join Type"),
        parent_relationship=_text(raw, "Parent Relationship"),
        filter=_text(raw, "Filter"),
        index_cond=_text(raw, "Index Cond"),
        hash_cond=_text(raw, "Hash Cond"),
        merge_cond=_text(raw, "Merge Cond"),
        join_filter=_text(raw, "Join Filter"),
        sort_keys=tuple(sort_key),
        sort_method=_text(raw, "Sort Method"),
        sort_space_used_kb=_number(raw, "Sort Space Used"),
        sort_space_type=_text(raw, "Sort Space Type"),
        startup_cost=_number(raw, "Startup Cost") or 0.0,
        total_cost=_number(raw, "Total Cost") or 0.0,
        plan_rows=_number(raw, "Plan Rows") or 0.0,
        actual_rows=_number(raw, "Actual Rows"),
        actual_loops=None if loops is None else int(loops),
        rows_removed_by_filter=_number(raw, "Rows Removed by Filter"),
    )
    suffix = {"Outer": " (outer)", "Inner": " (inner)"}.get(node.parent_relationship or "", "")
    node.path = f"{parent_path} > {node.label}{suffix}" if parent_path else node.label

    children = raw.get("Plans") or []
    if not isinstance(children, list):
        raise PlanParseError("'Plans' must be a list")
    node.children = [_build(child, node.path) for child in children]
    _disambiguate_siblings(node.children)
    return node


def _rebase(node: PlanNode, old: str, new: str) -> None:
    """Replace the leading `old` of this subtree's paths with `new`."""
    node.path = new + node.path[len(old) :]
    for child in node.children:
        _rebase(child, old, new)


def _disambiguate_siblings(children: list[PlanNode]) -> None:
    """Give siblings that share a path (e.g. two scans of one table under an Append) a ` #n` suffix.

    Paths identify nodes in findings and in the advisor, so they must be unique.
    """
    counts: dict[str, int] = {}
    for child in children:
        counts[child.path] = counts.get(child.path, 0) + 1
    seen: dict[str, int] = {}
    for child in children:
        old = child.path
        if counts[old] > 1:
            seen[old] = seen.get(old, 0) + 1
            _rebase(child, old, f"{old} #{seen[old]}")


def parse_explain(data: str | bytes | list[Any] | dict[str, Any]) -> Plan:
    """Parse the output of `EXPLAIN (FORMAT JSON)` or `EXPLAIN (ANALYZE, FORMAT JSON)`.

    Accepts the raw JSON text or the already-decoded value. Raises `PlanParseError` for
    anything else, including invalid JSON.
    """
    document: Any = data
    if isinstance(data, str | bytes):
        try:
            document = json.loads(data)
        except json.JSONDecodeError as exc:
            raise PlanParseError(f"input is not valid JSON: {exc}") from exc
    if isinstance(document, list):
        if not document:
            raise PlanParseError("the EXPLAIN document is an empty list")
        document = document[0]
    if not isinstance(document, dict) or not isinstance(document.get("Plan"), dict):
        raise PlanParseError("expected an object with a 'Plan' key (EXPLAIN FORMAT JSON)")
    return Plan(
        root=_build(document["Plan"], ""),
        planning_time_ms=_number(document, "Planning Time"),
        execution_time_ms=_number(document, "Execution Time"),
    )
