"""Anti-pattern detectors, run against the hand-written plan fixtures."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from planlens.findings import (
    ESTIMATE_MISMATCH,
    MISSING_JOIN_INDEX,
    REDUNDANT_SORT,
    SEQ_SCAN_SELECTIVE,
    SORT_SPILL,
    Thresholds,
    analyze,
)
from planlens.plan import Plan


def codes(plan: Plan, limits: Thresholds | None = None) -> list[str]:
    return [f.code for f in analyze(plan, limits)]


def test_seq_scan_discarding_most_rows(plan_of: Callable[[str], Plan]) -> None:
    (finding,) = analyze(plan_of("seq_scan_filter"))
    assert finding.code == SEQ_SCAN_SELECTIVE
    assert finding.severity == "high"
    assert finding.confidence == "measured"
    assert finding.details["rows_scanned"] == 100000
    assert "95%" in finding.message


def test_seq_scan_without_analyze_is_flagged_as_estimated(
    plan_of: Callable[[str], Plan],
) -> None:
    (finding,) = analyze(plan_of("seq_scan_estimate_only"))
    assert finding.code == SEQ_SCAN_SELECTIVE
    assert finding.confidence == "estimated"
    assert "ANALYZE" in finding.message


def test_small_scans_are_ignored(plan_of: Callable[[str], Plan]) -> None:
    assert codes(plan_of("seq_scan_filter"), Thresholds(min_rows_scanned=1_000_000)) == []


def test_nested_loop_over_seq_scan(plan_of: Callable[[str], Plan]) -> None:
    findings = analyze(plan_of("nested_loop_seq"))
    join = next(f for f in findings if f.code == MISSING_JOIN_INDEX)
    assert join.node_path.endswith("Seq Scan on order_items i (inner)")
    assert join.details["inner_loops"] == 150
    assert "i.order_id = o.id" in join.message
    # the outer scan of orders is also a selective sequential scan
    assert SEQ_SCAN_SELECTIVE in [f.code for f in findings]


def test_join_threshold_is_respected(plan_of: Callable[[str], Plan]) -> None:
    assert MISSING_JOIN_INDEX not in codes(
        plan_of("nested_loop_seq"), Thresholds(nested_loop_loops=1_000)
    )


def test_sort_spill(plan_of: Callable[[str], Plan]) -> None:
    (finding,) = analyze(plan_of("sort_spill"))
    assert finding.code == SORT_SPILL
    assert "14,240 kB" in finding.message


def test_estimate_mismatch_reports_direction_and_ratio(plan_of: Callable[[str], Plan]) -> None:
    (finding,) = analyze(plan_of("estimate_mismatch"))
    assert finding.code == ESTIMATE_MISMATCH
    assert "underestimated" in finding.message
    assert finding.details["ratio"] == 400


def test_mismatch_factor_is_configurable(plan_of: Callable[[str], Plan]) -> None:
    assert codes(plan_of("estimate_mismatch"), Thresholds(mismatch_factor=1000)) == []


def test_sort_on_sort_is_redundant(plan_of: Callable[[str], Plan]) -> None:
    (finding,) = analyze(plan_of("redundant_sort"))
    assert finding.code == REDUNDANT_SORT
    assert "customers.name" in finding.message


def test_healthy_plan_has_no_findings(plan_of: Callable[[str], Plan]) -> None:
    assert analyze(plan_of("healthy_index_scan")) == []


def test_findings_are_ordered_most_severe_first(plan_of: Callable[[str], Plan]) -> None:
    severities = [f.severity for f in analyze(plan_of("nested_loop_seq"))]
    assert severities == sorted(severities, key={"high": 0, "medium": 1, "low": 2}.__getitem__)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_filtered_fraction": 0},
        {"min_filtered_fraction": 1.5},
        {"mismatch_factor": 1},
        {"min_rows_scanned": 0},
        {"nested_loop_loops": 0},
    ],
)
def test_invalid_thresholds_raise(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        Thresholds(**kwargs)  # type: ignore[arg-type]
