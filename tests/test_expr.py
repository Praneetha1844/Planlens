"""Reading predicates and sort keys from Postgres-printed expressions."""

from __future__ import annotations

import pytest

from planlens.expr import (
    parse_predicates,
    parse_sort_key,
    split_top_level,
    strip_outer_parens,
)


def test_equality_with_cast_and_qualifier() -> None:
    (pred,) = parse_predicates("((o.status)::text = 'open'::text)")
    assert (pred.kind, pred.qualifier, pred.column, pred.op) == ("equality", "o", "status", "=")


def test_and_splits_into_equality_and_range() -> None:
    preds = parse_predicates("((status = 'open'::text) AND (created_at >= '2024-06-01'::date))")
    assert [(p.kind, p.column) for p in preds] == [("equality", "status"), ("range", "created_at")]


@pytest.mark.parametrize("op", ["<", "<=", ">", ">="])
def test_range_operators(op: str) -> None:
    (pred,) = parse_predicates(f"(price {op} 100)")
    assert pred.kind == "range"


def test_in_list_counts_as_equality() -> None:
    (pred,) = parse_predicates("(status = ANY ('{open,paid}'::text[]))")
    assert pred.kind == "equality"
    assert pred.column == "status"


def test_is_null_is_equality_and_is_not_null_is_not() -> None:
    assert parse_predicates("(deleted_at IS NULL)")[0].kind == "equality"
    assert parse_predicates("(deleted_at IS NOT NULL)")[0].kind == "other"


def test_column_equals_column_is_a_join() -> None:
    (pred,) = parse_predicates("(i.order_id = o.id)")
    assert pred.kind == "join"
    assert (pred.qualifier, pred.column) == ("i", "order_id")
    assert (pred.rhs_qualifier, pred.rhs_column) == ("o", "id")


def test_or_function_and_like_are_not_index_candidates() -> None:
    assert parse_predicates("((a = 1) OR (b = 2))")[0].kind == "or"
    assert parse_predicates("(lower(name) = 'x'::text)")[0].kind == "expression"
    assert parse_predicates("(name ~~ 'ab%'::text)")[0].kind == "other"
    assert parse_predicates("(a <> 3)")[0].kind == "other"


def test_boolean_and_null_literals_are_not_columns() -> None:
    assert parse_predicates("(active = true)")[0].kind == "equality"


def test_empty_expression_gives_no_predicates() -> None:
    assert parse_predicates(None) == []
    assert parse_predicates("") == []


def test_and_inside_quotes_or_parentheses_does_not_split() -> None:
    assert len(parse_predicates("(note = 'a AND b'::text)")) == 1
    assert len(split_top_level("(a = 1 AND b = 2) AND c = 3", "AND")) == 2


def test_strip_outer_parens_only_removes_wrapping_pairs() -> None:
    assert strip_outer_parens("((a = 1))") == "a = 1"
    assert strip_outer_parens("(a = 1) AND (b = 2)") == "(a = 1) AND (b = 2)"


def test_sort_keys() -> None:
    desc = parse_sort_key("orders.created_at DESC")
    assert (desc.qualifier, desc.column, desc.descending) == ("orders", "created_at", True)
    asc = parse_sort_key("id")
    assert (asc.qualifier, asc.column, asc.descending) == (None, "id", False)
    nulls = parse_sort_key("created_at DESC NULLS LAST")
    assert (nulls.column, nulls.descending) == ("created_at", True)
    assert parse_sort_key("(sum(amount)) DESC").column is None
