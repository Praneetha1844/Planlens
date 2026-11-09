"""Extract column predicates from the expression strings Postgres prints in plans.

Postgres renders conditions as text, for example
`((o.status = 'open'::text) AND (o.created_at >= '2024-06-01'::date))`. This module reads
the common shapes (column compared with a constant, `IS NULL`, `= ANY`, column = column) and
marks everything else as unusable for index suggestions. It is a tolerant reader, not a SQL
parser; see docs/ADR 0002.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CASTS = re.compile(
    r"::(?:character varying|timestamp without time zone|timestamp with time zone|"
    r"double precision|bigint|integer|smallint|numeric|text|date|boolean|real|name|uuid|"
    r"varchar|bpchar|timestamptz|timestamp|jsonb|json)(?:\[\])?"
)
_ATOM = re.compile(
    r"^(?P<lhs>[A-Za-z_\"][\w\".]*)\s*"
    r"(?P<op>IS NOT NULL|IS NULL|<=|>=|<>|!=|=|<|>|~~\*|~~|!~~)\s*(?P<rhs>.*)$"
)
_IDENT = re.compile(r"^[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)?$")
_RESERVED_RHS = frozenset({"NULL", "TRUE", "FALSE"})
_RANGE_OPS = frozenset({"<", "<=", ">", ">="})


@dataclass(frozen=True)
class Predicate:
    """One condition. `kind` says whether a btree index can use it as a leading column."""

    kind: str  # equality | range | join | other | or | expression
    column: str | None = None
    qualifier: str | None = None
    op: str | None = None
    rhs_column: str | None = None
    rhs_qualifier: str | None = None
    text: str = ""


@dataclass(frozen=True)
class ColumnRef:
    """A possibly qualified column, e.g. `o.created_at`."""

    column: str
    qualifier: str | None = None


def _wrapped(text: str) -> bool:
    """True if the first '(' is closed by the final ')' of the string."""
    if not (text.startswith("(") and text.endswith(")")):
        return False
    depth = 0
    quoted = False
    for index, char in enumerate(text):
        if char == "'":
            quoted = not quoted
        elif not quoted:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return index == len(text) - 1
    return False


def strip_outer_parens(text: str) -> str:
    """Remove parentheses that wrap the whole expression."""
    text = text.strip()
    while _wrapped(text):
        text = text[1:-1].strip()
    return text


def split_top_level(text: str, keyword: str) -> list[str]:
    """Split on ` KEYWORD ` outside parentheses and single quotes."""
    token = f" {keyword} "
    parts: list[str] = []
    depth = 0
    quoted = False
    start = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char == "'":
            quoted = not quoted
        elif not quoted:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif depth == 0 and text.startswith(token, index):
                parts.append(text[start:index])
                index += len(token)
                start = index
                continue
        index += 1
    parts.append(text[start:])
    return parts


def _normalise(text: str) -> str:
    return _CASTS.sub("", text).replace("(", "").replace(")", "").strip()


def _split_ref(token: str) -> ColumnRef:
    token = token.replace('"', "")
    if "." in token:
        qualifier, _, column = token.rpartition(".")
        return ColumnRef(column=column, qualifier=qualifier.rpartition(".")[2])
    return ColumnRef(column=token)


def _atom(text: str) -> Predicate:
    cleaned = _normalise(text)
    match = _ATOM.match(cleaned)
    if not match:
        return Predicate(kind="expression", text=text)
    left = _split_ref(match["lhs"])
    op = match["op"]
    rhs = match["rhs"].strip()
    if op in {"IS NULL", "IS NOT NULL"}:
        kind = "equality" if op == "IS NULL" else "other"
        return Predicate(kind=kind, column=left.column, qualifier=left.qualifier, op=op, text=text)
    if _IDENT.match(rhs) and rhs.upper() not in _RESERVED_RHS:
        right = _split_ref(rhs)
        return Predicate(
            kind="join" if op == "=" else "other",
            column=left.column,
            qualifier=left.qualifier,
            op=op,
            rhs_column=right.column,
            rhs_qualifier=right.qualifier,
            text=text,
        )
    kind = "equality" if op == "=" else "range" if op in _RANGE_OPS else "other"
    return Predicate(kind=kind, column=left.column, qualifier=left.qualifier, op=op, text=text)


def parse_predicates(expression: str | None) -> list[Predicate]:
    """Split a plan condition into AND-ed predicates and classify each one."""
    if not expression:
        return []
    predicates: list[Predicate] = []
    for part in split_top_level(strip_outer_parens(expression), "AND"):
        clause = strip_outer_parens(part)
        if len(split_top_level(clause, "OR")) > 1:
            predicates.append(Predicate(kind="or", text=clause))
        else:
            predicates.append(_atom(clause))
    return predicates


@dataclass(frozen=True)
class SortKey:
    """One entry of a Sort node's key, e.g. `o.created_at DESC`."""

    column: str | None
    qualifier: str | None
    descending: bool
    text: str


_DIRECTION = re.compile(r"\s+(ASC|DESC)\b|\s+NULLS (?:FIRST|LAST)\b", re.IGNORECASE)


def parse_sort_key(text: str) -> SortKey:
    """Parse one `Sort Key` entry. Expressions yield `column=None`."""
    descending = bool(re.search(r"\sDESC\b", text, re.IGNORECASE))
    bare = _normalise(_DIRECTION.sub("", text))
    if not _IDENT.match(bare):
        return SortKey(column=None, qualifier=None, descending=descending, text=text)
    ref = _split_ref(bare)
    return SortKey(
        column=ref.column, qualifier=ref.qualifier, descending=descending, text=text
    )
