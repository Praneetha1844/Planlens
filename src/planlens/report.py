"""Render findings and index suggestions as Markdown, HTML or JSON."""

from __future__ import annotations

import html
import json
from dataclasses import asdict

from .advisor import SCORE_NOTE, IndexSuggestion
from .findings import Finding
from .plan import Plan

DISCLAIMER = (
    "Findings are heuristics over one plan. Confirm any change by measuring "
    "(see `planlens bench`) before applying it to a production database."
)


def _summary(plan: Plan) -> list[tuple[str, str]]:
    plan_type = "EXPLAIN ANALYZE (measured rows)" if plan.analyzed else "EXPLAIN (estimates only)"
    rows = [
        ("Plan type", plan_type),
        ("Root node", plan.root.label),
        ("Estimated total cost", f"{plan.root.total_cost:,.2f}"),
    ]
    if plan.execution_time_ms is not None:
        rows.append(("Execution time (ms)", f"{plan.execution_time_ms:,.3f}"))
    if plan.planning_time_ms is not None:
        rows.append(("Planning time (ms)", f"{plan.planning_time_ms:,.3f}"))
    return rows


def render_markdown(
    plan: Plan, findings: list[Finding], suggestions: list[IndexSuggestion]
) -> str:
    """Return a Markdown report."""
    lines = ["# Planlens report", "", "| | |", "|---|---|"]
    lines += [f"| {key} | {value} |" for key, value in _summary(plan)]
    lines += ["", "## Findings", ""]
    if not findings:
        lines.append("No anti-patterns detected by the enabled detectors.")
    for number, f in enumerate(findings, start=1):
        lines += [
            f"{number}. **{f.code}** ({f.severity}, {f.confidence})",
            f"   - Where: `{f.node_path}`",
            f"   - {f.message}",
            f"   - Suggestion: {f.suggestion}",
        ]
    lines += ["", "## Suggested indexes", ""]
    if not suggestions:
        lines.append("No index suggestions.")
    for s in suggestions:
        lines += [
            f"- `{s.name}` on `{s.table}`, score {s.score:.2f}: {'; '.join(s.reasons)}",
            "",
            "  ```sql",
            f"  {s.ddl}",
            "  ```",
        ]
    lines += ["", f"_Score: {SCORE_NOTE}._", "", f"> {DISCLAIMER}", ""]
    return "\n".join(lines)


def render_html(plan: Plan, findings: list[Finding], suggestions: list[IndexSuggestion]) -> str:
    """Return a standalone HTML page. All plan-derived text is escaped."""
    esc = html.escape
    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Planlens report</title>",
        "<style>"
        "body{font-family:system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem}"
        "code,pre{background:#f3f3f3;padding:.1rem .3rem;border-radius:3px}"
        "pre{padding:.6rem;overflow-x:auto}"
        "td,th{text-align:left;padding:.2rem .8rem .2rem 0}"
        "</style>",
        "</head><body>",
        "<h1>Planlens report</h1>",
        "<table>",
    ]
    parts += [f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in _summary(plan)]
    parts += ["</table>", "<h2>Findings</h2>"]
    if not findings:
        parts.append("<p>No anti-patterns detected by the enabled detectors.</p>")
    else:
        parts.append("<ol>")
        for f in findings:
            parts.append(
                f"<li><strong>{esc(f.code)}</strong> ({esc(f.severity)}, {esc(f.confidence)})"
                f"<br>Where: <code>{esc(f.node_path)}</code><br>{esc(f.message)}"
                f"<br>Suggestion: {esc(f.suggestion)}</li>"
            )
        parts.append("</ol>")
    parts.append("<h2>Suggested indexes</h2>")
    if not suggestions:
        parts.append("<p>No index suggestions.</p>")
    for s in suggestions:
        parts.append(
            f"<h3><code>{esc(s.name)}</code> on <code>{esc(s.table)}</code> "
            f"(score {s.score:.2f})</h3><p>{esc('; '.join(s.reasons))}</p>"
            f"<pre>{esc(s.ddl)}</pre>"
        )
    parts += [
        f"<p><em>Score: {esc(SCORE_NOTE)}.</em></p>",
        f"<p>{esc(DISCLAIMER)}</p>",
        "</body></html>",
    ]
    return "\n".join(parts)


def render_json(plan: Plan, findings: list[Finding], suggestions: list[IndexSuggestion]) -> str:
    """Return a machine-readable report."""
    document = {
        "summary": dict(_summary(plan)),
        "findings": [asdict(f) for f in findings],
        "suggestions": [
            {
                "name": s.name,
                "table": s.table,
                "columns": [{"name": c.name, "descending": c.descending} for c in s.columns],
                "reasons": list(s.reasons),
                "score": s.score,
                "score_note": SCORE_NOTE,
                "ddl": s.ddl,
            }
            for s in suggestions
        ],
        "disclaimer": DISCLAIMER,
    }
    return json.dumps(document, indent=2)
