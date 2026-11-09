"""Heuristic index advisor.

Candidates come from three places in a plan: filters on sequentially scanned tables, join keys
on the inner side of nested loops, and the sort keys of a Sort that spilled to disk. Column
order follows the usual btree rule: equality columns first, then at most one range column.

The `score` is a heuristic ranking signal (how much of the plan's cost sits under the node the
index would help, scaled by how much that node discards). It is NOT a predicted speedup. Use
`planlens.whatif` (hypopg) or `planlens.bench` to measure.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from .expr import Predicate, parse_predicates, parse_sort_key
from .findings import (
    MISSING_JOIN_INDEX,
    SEQ_SCAN_SELECTIVE,
    SORT_SPILL,
    Finding,
    Thresholds,
    analyze,
)
from .plan import Plan, PlanNode

SCORE_NOTE = "heuristic ranking score between 0 and 1, not a predicted speedup"
MAX_IDENTIFIER = 63  # PostgreSQL's identifier length limit

_PLAIN = re.compile(r"^[a-z_][a-z0-9_]*$")
# shortcut: a short list of common reserved words, not the full PostgreSQL keyword table
_RESERVED = frozenset(
    {"all", "and", "as", "by", "case", "check", "column", "default", "desc", "distinct", "end",
     "for", "from", "group", "having", "in", "index", "into", "is", "join", "like", "limit",
     "not", "null", "on", "or", "order", "select", "table", "then", "to", "user", "using",
     "when", "where", "with"}
)  # fmt: skip


def quote_ident(name: str) -> str:
    """Quote an identifier unless it is a plain lower-case name that is not reserved."""
    if _PLAIN.match(name) and name not in _RESERVED:
        return name
    return '"' + name.replace('"', '""') + '"'


@dataclass(frozen=True)
class IndexColumn:
    """One indexed column and its direction."""

    name: str
    descending: bool = False


@dataclass(frozen=True)
class IndexSuggestion:
    """A proposed btree index and why it was proposed."""

    table: str
    columns: tuple[IndexColumn, ...]
    schema: str | None = None
    reasons: tuple[str, ...] = ()
    score: float = 0.0
    node_paths: tuple[str, ...] = field(default_factory=tuple)

    @property
    def qualified_table(self) -> str:
        table = quote_ident(self.table)
        return f"{quote_ident(self.schema)}.{table}" if self.schema else table

    @property
    def name(self) -> str:
        """A deterministic index name within PostgreSQL's 63-character limit."""
        raw = "idx_" + "_".join([self.table, *(c.name for c in self.columns)])
        raw = re.sub(r"[^a-z0-9_]", "_", raw.lower())
        if len(raw) <= MAX_IDENTIFIER:
            return raw
        digest = hashlib.sha1(raw.encode()).hexdigest()[:8]
        return f"{raw[: MAX_IDENTIFIER - 9]}_{digest}"

    def _column_list(self) -> str:
        return ", ".join(
            quote_ident(c.name) + (" DESC" if c.descending else "") for c in self.columns
        )

    @property
    def ddl(self) -> str:
        """Statement to run on a real database. CONCURRENTLY avoids blocking writes."""
        return (
            f"CREATE INDEX CONCURRENTLY {self.name} ON {self.qualified_table} "
            f"({self._column_list()});"
        )

    @property
    def hypopg_ddl(self) -> str:
        """Form accepted by `hypopg_create_index` (no name, no CONCURRENTLY, no semicolon)."""
        return f"CREATE INDEX ON {self.qualified_table} ({self._column_list()})"


def _alias_of(node: PlanNode) -> str | None:
    return node.alias or node.relation


def _ordered_unique(items: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for item in items:
        seen.setdefault(item, None)
    return list(seen)


def _usable(preds: list[Predicate], alias: str | None) -> list[Predicate]:
    return [p for p in preds if p.column and (p.qualifier is None or p.qualifier == alias)]


def _filter_columns(node: PlanNode) -> list[str]:
    """Equality columns first, then at most one range column."""
    usable = _usable(parse_predicates(node.filter), _alias_of(node))
    equality = _ordered_unique(p.column for p in usable if p.kind == "equality" and p.column)
    ranges = [
        p.column
        for p in usable
        if p.kind == "range" and p.column and p.column not in equality
    ]
    return equality + ranges[:1]


def _share(node: PlanNode, root_cost: float) -> float:
    return min(1.0, node.total_cost / root_cost) if root_cost > 0 else 0.0


def _from_seq_scan(finding: Finding, node: PlanNode, root_cost: float) -> IndexSuggestion | None:
    columns = _filter_columns(node)
    if not columns or not node.relation:
        return None
    discarded = float(finding.details.get("fraction_discarded", 0.5))
    score = _share(node, root_cost) * discarded
    if finding.confidence == "estimated":
        score *= 0.5
    return IndexSuggestion(
        table=node.relation,
        schema=node.schema,
        columns=tuple(IndexColumn(c) for c in columns),
        reasons=(f"filter on {', '.join(columns)} of {node.label}",),
        score=round(score, 2),
        node_paths=(node.path,),
    )


def _from_join(
    inner: PlanNode, parent: PlanNode | None, root_cost: float
) -> IndexSuggestion | None:
    if parent is None or not inner.relation:
        return None
    alias = _alias_of(inner)
    join_columns: list[str] = []
    for pred in parse_predicates(parent.join_filter):
        if pred.kind != "join":
            continue
        if pred.qualifier == alias and pred.column:
            join_columns.append(pred.column)
        elif pred.rhs_qualifier == alias and pred.rhs_column:
            join_columns.append(pred.rhs_column)
    if not join_columns:
        return None
    columns = _ordered_unique([*join_columns, *_filter_columns(inner)])
    return IndexSuggestion(
        table=inner.relation,
        schema=inner.schema,
        columns=tuple(IndexColumn(c) for c in columns),
        reasons=(f"join key {', '.join(join_columns)} probed by a nested loop",),
        score=round(_share(parent, root_cost), 2),
        node_paths=(inner.path,),
    )


def _from_sort(node: PlanNode, root_cost: float) -> IndexSuggestion | None:
    scans = [n for n in node.walk() if n.is_scan and n.relation]
    aliases = {_alias_of(n) for n in scans}
    if len(aliases) != 1:
        return None
    scan = scans[0]
    keys = [parse_sort_key(k) for k in node.sort_keys]
    if not keys or any(k.column is None for k in keys):
        return None
    if any(k.qualifier not in (None, _alias_of(scan)) for k in keys):
        return None
    assert scan.relation is not None  # filtered above
    return IndexSuggestion(
        table=scan.relation,
        schema=scan.schema,
        columns=tuple(IndexColumn(k.column or "", k.descending) for k in keys),
        reasons=(f"sort order {', '.join(node.sort_keys)} spilled to disk",),
        score=round(_share(node, root_cost), 2),
        node_paths=(node.path,),
    )


def _already_indexed(
    suggestion: IndexSuggestion, existing: list[tuple[str, tuple[str, ...]]]
) -> bool:
    """True if an existing index on the table starts with the suggested columns."""
    wanted = tuple(c.name.lower() for c in suggestion.columns)
    return any(
        table == suggestion.table.lower() and columns[: len(wanted)] == wanted
        for table, columns in existing
    )


def _is_prefix(shorter: tuple[IndexColumn, ...], longer: tuple[IndexColumn, ...]) -> bool:
    return len(shorter) < len(longer) and longer[: len(shorter)] == shorter


def suggest_indexes(
    plan: Plan,
    findings: list[Finding] | None = None,
    *,
    existing: Iterable[tuple[str, tuple[str, ...]]] = (),
    limits: Thresholds | None = None,
) -> list[IndexSuggestion]:
    """Propose indexes for the problems found in `plan`.

    `existing` lists indexes the table already has as `(table, (column, ...))`; a suggestion
    whose columns are a prefix of an existing index is dropped. Results are ordered by score.
    """
    found = findings if findings is not None else analyze(plan, limits)
    by_path = {node.path: node for node in plan.nodes()}
    parents = {child.path: node for node in plan.nodes() for child in node.children}
    root_cost = plan.root.total_cost

    candidates: list[IndexSuggestion] = []
    for finding in found:
        node = by_path.get(finding.node_path)
        if node is None:
            continue
        if finding.code == SEQ_SCAN_SELECTIVE:
            made = _from_seq_scan(finding, node, root_cost)
        elif finding.code == MISSING_JOIN_INDEX:
            made = _from_join(node, parents.get(node.path), root_cost)
        elif finding.code == SORT_SPILL:
            made = _from_sort(node, root_cost)
        else:
            made = None
        if made is not None:
            candidates.append(made)

    merged: dict[tuple[str | None, str, tuple[IndexColumn, ...]], IndexSuggestion] = {}
    for cand in candidates:
        key = (cand.schema, cand.table, cand.columns)
        prior = merged.get(key)
        if prior is None:
            merged[key] = cand
        else:
            merged[key] = IndexSuggestion(
                table=cand.table,
                schema=cand.schema,
                columns=cand.columns,
                reasons=prior.reasons + cand.reasons,
                score=max(prior.score, cand.score),
                node_paths=prior.node_paths + cand.node_paths,
            )

    kept = [
        s
        for s in merged.values()
        if not any(
            o.table == s.table and o.schema == s.schema and _is_prefix(s.columns, o.columns)
            for o in merged.values()
        )
    ]
    have = [(table.lower(), tuple(c.lower() for c in cols)) for table, cols in existing]
    kept = [s for s in kept if not _already_indexed(s, have)]
    return sorted(kept, key=lambda s: (-s.score, s.table, [c.name for c in s.columns]))
