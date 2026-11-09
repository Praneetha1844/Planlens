"""Anti-pattern detectors. Each one reads the plan tree and returns plain-English findings.

The detectors are heuristics over a single plan. A finding says "this shape is often slow",
not "this query is slow": confirm with measurements. See docs/SQL_NOTES.md.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .expr import parse_predicates
from .plan import Plan, PlanNode

SEQ_SCAN_SELECTIVE = "seq_scan_selective"
MISSING_JOIN_INDEX = "missing_join_index"
SORT_SPILL = "sort_spill"
NESTED_LOOP_HIGH_LOOPS = "nested_loop_high_loops"
ESTIMATE_MISMATCH = "estimate_mismatch"
REDUNDANT_SORT = "redundant_sort"


@dataclass(frozen=True)
class Thresholds:
    """Tunable limits for the detectors. Defaults are conservative starting points."""

    min_rows_scanned: int = 10_000
    min_filtered_fraction: float = 0.9
    estimate_only_cost: float = 1_000.0
    mismatch_factor: float = 10.0
    min_rows_for_mismatch: int = 100
    nested_loop_loops: int = 100
    high_loops: int = 100_000

    def __post_init__(self) -> None:
        if not 0 < self.min_filtered_fraction <= 1:
            raise ValueError("min_filtered_fraction must be in (0, 1]")
        if self.mismatch_factor <= 1:
            raise ValueError("mismatch_factor must be > 1")
        if (
            min(
                self.min_rows_scanned,
                self.min_rows_for_mismatch,
                self.nested_loop_loops,
                self.high_loops,
            )
            < 1
        ):
            raise ValueError("row and loop thresholds must be >= 1")
        if self.estimate_only_cost < 0:
            raise ValueError("estimate_only_cost must be >= 0")


@dataclass(frozen=True)
class Finding:
    """One detected anti-pattern, tied to a node in the plan."""

    code: str
    severity: str  # high | medium | low
    node_path: str
    message: str
    suggestion: str
    confidence: str = "measured"  # measured (EXPLAIN ANALYZE) or estimated
    details: dict[str, float | str] = field(default_factory=dict)


def _inner_child(node: PlanNode) -> PlanNode | None:
    for child in node.children:
        if child.parent_relationship == "Inner":
            return child
    return node.children[1] if len(node.children) == 2 else None


def _outer_child(node: PlanNode) -> PlanNode | None:
    for child in node.children:
        if child.parent_relationship == "Outer":
            return child
    return node.children[0] if len(node.children) == 2 else None


def detect_seq_scan_selective(plan: Plan, limits: Thresholds) -> list[Finding]:
    """A sequential scan that throws away most of what it reads."""
    findings: list[Finding] = []
    for node in plan.nodes():
        if node.node_type != "Seq Scan" or not node.filter:
            continue
        table = node.relation or "the table"
        if node.has_actuals and node.rows_removed_by_filter is not None:
            loops = node.actual_loops or 1
            kept = (node.actual_rows or 0.0) * loops
            removed = node.rows_removed_by_filter * loops
            scanned = kept + removed
            if scanned < limits.min_rows_scanned:
                continue
            if removed / scanned < limits.min_filtered_fraction:
                continue
            fraction = removed / scanned
            findings.append(
                Finding(
                    code=SEQ_SCAN_SELECTIVE,
                    severity="high",
                    node_path=node.path,
                    message=(
                        f"Sequential scan of {table} read {scanned:,.0f} rows and discarded "
                        f"{fraction:.0%} of them with the filter {node.filter}."
                    ),
                    suggestion=f"An index on the filtered column(s) of {table} may avoid the scan.",
                    details={"rows_scanned": scanned, "fraction_discarded": round(fraction, 4)},
                )
            )
        elif not node.has_actuals and node.total_cost >= limits.estimate_only_cost:
            findings.append(
                Finding(
                    code=SEQ_SCAN_SELECTIVE,
                    severity="medium",
                    node_path=node.path,
                    message=(
                        f"Sequential scan of {table} with a filter and an estimated cost of "
                        f"{node.total_cost:,.0f}. This plan has no ANALYZE data, so selectivity "
                        "is unknown."
                    ),
                    suggestion="Re-run with EXPLAIN (ANALYZE, FORMAT JSON) to see rows discarded.",
                    confidence="estimated",
                    details={"total_cost": node.total_cost},
                )
            )
    return findings


def detect_missing_join_index(plan: Plan, limits: Thresholds) -> list[Finding]:
    """A nested loop that rescans an unindexed inner table once per outer row."""
    findings: list[Finding] = []
    for node in plan.nodes():
        if node.node_type != "Nested Loop":
            continue
        inner = _inner_child(node)
        outer = _outer_child(node)
        if inner is None or inner.node_type != "Seq Scan":
            continue
        if inner.has_actuals:
            loops = float(inner.actual_loops or 1)
            confidence = "measured"
        elif outer is not None:
            loops = outer.plan_rows
            confidence = "estimated"
        else:
            continue
        if loops < limits.nested_loop_loops:
            continue
        keys = ", ".join(
            p.text for p in parse_predicates(node.join_filter) if p.kind == "join"
        ) or "the join condition"
        findings.append(
            Finding(
                code=MISSING_JOIN_INDEX,
                severity="high",
                node_path=inner.path,
                message=(
                    f"Nested loop scans {inner.relation or 'the inner table'} sequentially "
                    f"about {loops:,.0f} times to satisfy {keys}."
                ),
                suggestion="Index the inner table's join column so each probe is an index lookup.",
                confidence=confidence,
                details={"inner_loops": loops},
            )
        )
    return findings


def detect_sort_spill(plan: Plan, limits: Thresholds) -> list[Finding]:
    """A sort that did not fit in work_mem and wrote to disk."""
    del limits
    findings: list[Finding] = []
    for node in plan.nodes():
        if node.node_type != "Sort":
            continue
        spilled = (node.sort_space_type or "").lower() == "disk" or (
            node.sort_method or ""
        ).lower().startswith("external")
        if not spilled:
            continue
        used = node.sort_space_used_kb
        size = f" ({used:,.0f} kB)" if used is not None else ""
        findings.append(
            Finding(
                code=SORT_SPILL,
                severity="medium",
                node_path=node.path,
                message=f"Sort on {', '.join(node.sort_keys) or 'its keys'} spilled to disk{size}.",
                suggestion=(
                    "An index matching the sort order can remove the sort; otherwise raise "
                    "work_mem for this query."
                ),
                details={"sort_space_used_kb": used or 0.0},
            )
        )
    return findings


def detect_nested_loop_high_loops(plan: Plan, limits: Thresholds) -> list[Finding]:
    """A nested loop whose inner side runs very many times even though it uses an index."""
    findings: list[Finding] = []
    for node in plan.nodes():
        if node.node_type != "Nested Loop":
            continue
        inner = _inner_child(node)
        if inner is None or not inner.has_actuals or inner.node_type == "Seq Scan":
            continue
        loops = inner.actual_loops or 1
        if loops < limits.high_loops:
            continue
        findings.append(
            Finding(
                code=NESTED_LOOP_HIGH_LOOPS,
                severity="low",
                node_path=node.path,
                message=f"The inner side of this nested loop ran {loops:,} times.",
                suggestion=(
                    "Check whether the planner's row estimate for the outer side was too low; "
                    "a hash or merge join may suit this size better."
                ),
                details={"inner_loops": float(loops)},
            )
        )
    return findings


def detect_estimate_mismatch(plan: Plan, limits: Thresholds) -> list[Finding]:
    """Planner row estimate far from reality, per loop, in either direction."""
    findings: list[Finding] = []
    under_limit = {
        id(descendant)
        for limit in plan.nodes()
        if limit.node_type == "Limit"
        for child in limit.children
        for descendant in child.walk()
    }
    for node in plan.nodes():
        if not node.has_actuals or node.actual_rows is None:
            continue
        if node.actual_loops == 0:  # never executed, so there is nothing to compare
            continue
        if node.actual_rows < node.plan_rows and id(node) in under_limit:
            continue  # a LIMIT stops its input early, so fewer rows than planned is expected
        high = max(node.actual_rows, node.plan_rows)
        low = max(min(node.actual_rows, node.plan_rows), 1.0)
        if high < limits.min_rows_for_mismatch or high / low < limits.mismatch_factor:
            continue
        ratio = high / low
        direction = "under" if node.actual_rows > node.plan_rows else "over"
        findings.append(
            Finding(
                code=ESTIMATE_MISMATCH,
                severity="medium",
                node_path=node.path,
                message=(
                    f"The planner {direction}estimated rows by {ratio:,.0f}x "
                    f"(estimated {node.plan_rows:,.0f}, actual {node.actual_rows:,.0f} per loop)."
                ),
                suggestion=(
                    "Run ANALYZE on the table, raise the statistics target for the filtered "
                    "column, or add extended statistics for correlated columns."
                ),
                details={"estimated": node.plan_rows, "actual": node.actual_rows, "ratio": ratio},
            )
        )
    return findings


def detect_redundant_sort(plan: Plan, limits: Thresholds) -> list[Finding]:
    """A Sort fed directly by another Sort. Only this clear case is flagged (heuristic)."""
    del limits
    findings: list[Finding] = []
    for node in plan.nodes():
        if node.node_type != "Sort" or len(node.children) != 1:
            continue
        child = node.children[0]
        if child.node_type != "Sort":
            continue
        findings.append(
            Finding(
                code=REDUNDANT_SORT,
                severity="low",
                node_path=node.path,
                message=(
                    f"Sort on {', '.join(node.sort_keys)} sits directly on another Sort "
                    f"({', '.join(child.sort_keys)}); the inner sort's order is discarded."
                ),
                suggestion="Remove the redundant ORDER BY (often in a subquery or view).",
                details={},
            )
        )
    return findings


DETECTORS: tuple[Callable[[Plan, Thresholds], list[Finding]], ...] = (
    detect_seq_scan_selective,
    detect_missing_join_index,
    detect_sort_spill,
    detect_nested_loop_high_loops,
    detect_estimate_mismatch,
    detect_redundant_sort,
)

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def analyze(plan: Plan, limits: Thresholds | None = None) -> list[Finding]:
    """Run every detector and return findings, most severe first."""
    limits = limits or Thresholds()
    found = [f for detector in DETECTORS for f in detector(plan, limits)]
    return sorted(found, key=lambda f: (_SEVERITY_ORDER[f.severity], f.node_path))
