"""Index suggestions derived from the plan fixtures."""

from __future__ import annotations

from collections.abc import Callable

from planlens.advisor import IndexColumn, IndexSuggestion, quote_ident, suggest_indexes
from planlens.plan import Plan


def test_equality_column_comes_before_range_column(plan_of: Callable[[str], Plan]) -> None:
    (suggestion,) = suggest_indexes(plan_of("seq_scan_filter"))
    assert suggestion.table == "orders"
    assert [c.name for c in suggestion.columns] == ["status", "created_at"]
    assert suggestion.score == 0.95
    assert suggestion.ddl == (
        "CREATE INDEX CONCURRENTLY idx_orders_status_created_at "
        "ON public.orders (status, created_at);"
    )


def test_join_key_suggestion_for_inner_seq_scan(plan_of: Callable[[str], Plan]) -> None:
    suggestions = suggest_indexes(plan_of("nested_loop_seq"))
    top = suggestions[0]
    assert (top.table, [c.name for c in top.columns]) == ("order_items", ["order_id"])
    assert top.score == 1.0
    assert any(s.table == "orders" and s.columns == (IndexColumn("customer_id"),)
               for s in suggestions)  # fmt: skip
    assert [s.score for s in suggestions] == sorted((s.score for s in suggestions), reverse=True)


def test_sort_suggestion_keeps_direction(plan_of: Callable[[str], Plan]) -> None:
    (suggestion,) = suggest_indexes(plan_of("sort_spill"))
    assert suggestion.columns == (IndexColumn("created_at", descending=True),)
    assert suggestion.ddl.endswith("(created_at DESC);")
    assert suggestion.hypopg_ddl == "CREATE INDEX ON public.orders (created_at DESC)"


def test_estimated_plans_score_lower_than_measured(plan_of: Callable[[str], Plan]) -> None:
    (estimated,) = suggest_indexes(plan_of("seq_scan_estimate_only"))
    assert estimated.score == 0.25
    assert [c.name for c in estimated.columns] == ["customer_id"]


def test_existing_index_suppresses_suggestion(plan_of: Callable[[str], Plan]) -> None:
    plan = plan_of("seq_scan_filter")
    assert suggest_indexes(plan, existing=[("orders", ("status", "created_at", "total"))]) == []
    assert suggest_indexes(plan, existing=[("orders", ("status",))]) != []
    assert suggest_indexes(plan, existing=[("ORDERS", ("STATUS", "CREATED_AT"))]) == []


def test_prefix_candidates_are_merged_into_the_longer_one(plan_of: Callable[[str], Plan]) -> None:
    suggestions = suggest_indexes(plan_of("nested_loop_seq"))
    names = [tuple(c.name for c in s.columns) for s in suggestions]
    assert len(names) == len(set(names))


def test_no_findings_means_no_suggestions(plan_of: Callable[[str], Plan]) -> None:
    assert suggest_indexes(plan_of("healthy_index_scan")) == []
    assert suggest_indexes(plan_of("estimate_mismatch")) == []


def test_quote_ident() -> None:
    assert quote_ident("orders") == "orders"
    assert quote_ident("Order") == '"Order"'
    assert quote_ident("order") == '"order"'
    assert quote_ident('we"ird') == '"we""ird"'


def test_long_names_are_shortened_deterministically() -> None:
    suggestion = IndexSuggestion(
        table="t" * 40, columns=(IndexColumn("c" * 30), IndexColumn("d" * 30))
    )
    assert len(suggestion.name) <= 63
    assert suggestion.name == suggestion.name  # stable across calls
    assert suggestion.name.startswith("idx_ttt")
