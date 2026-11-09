"""Report renderers and the command line."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from planlens.advisor import suggest_indexes
from planlens.cli import main
from planlens.findings import analyze
from planlens.plan import Plan, parse_explain
from planlens.report import render_html, render_json, render_markdown


def test_markdown_report_lists_findings_and_ddl(plan_of: Callable[[str], Plan]) -> None:
    plan = plan_of("seq_scan_filter")
    text = render_markdown(plan, analyze(plan), suggest_indexes(plan))
    assert "# Planlens report" in text
    assert "seq_scan_selective" in text
    assert "CREATE INDEX CONCURRENTLY idx_orders_status_created_at" in text
    assert "not a predicted speedup" in text
    assert "EXPLAIN ANALYZE" in text


def test_markdown_report_for_a_clean_plan(plan_of: Callable[[str], Plan]) -> None:
    plan = plan_of("healthy_index_scan")
    text = render_markdown(plan, analyze(plan), suggest_indexes(plan))
    assert "No anti-patterns detected" in text
    assert "No index suggestions" in text


def test_html_report_escapes_plan_text() -> None:
    hostile = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "<script>alert(1)</script>",
            "Alias": "t",
            "Total Cost": 5000,
            "Plan Rows": 1,
            "Filter": "(x = 1)",
        }
    }
    plan = parse_explain(hostile)
    page = render_html(plan, analyze(plan), suggest_indexes(plan))
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_json_report_is_valid_json(plan_of: Callable[[str], Plan]) -> None:
    plan = plan_of("sort_spill")
    document = json.loads(render_json(plan, analyze(plan), suggest_indexes(plan)))
    assert document["findings"][0]["code"] == "sort_spill"
    assert document["suggestions"][0]["columns"] == [{"name": "created_at", "descending": True}]
    assert "disclaimer" in document


def test_cli_analyze_prints_markdown(capsys: pytest.CaptureFixture[str]) -> None:
    fixture = Path(__file__).parent / "fixtures" / "seq_scan_filter.json"
    assert main(["analyze", str(fixture)]) == 0
    assert "seq_scan_selective" in capsys.readouterr().out


def test_cli_analyze_writes_a_file(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "sort_spill.json"
    out = tmp_path / "report.json"
    assert main(["analyze", str(fixture), "--format", "json", "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["findings"]


def test_cli_existing_index_suppresses_suggestion(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "seq_scan_filter.json"
    out = tmp_path / "report.json"
    args = ["analyze", str(fixture), "--format", "json", "--out", str(out)]
    assert main([*args, "--existing", "orders:status,created_at"]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["suggestions"] == []


FIXTURE = str(Path(__file__).parent / "fixtures" / "seq_scan_filter.json")


@pytest.mark.parametrize(
    ("extra", "fragment"),
    [
        (["--existing", "no-colon"], "--existing expects"),
        (["--min-rows", "0"], ">= 1"),
        (["--mismatch-factor", "1"], "mismatch_factor"),
    ],
)
def test_cli_rejects_bad_options_with_exit_code_2(
    extra: list[str], fragment: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["analyze", FIXTURE, *extra]) == 2
    assert fragment in capsys.readouterr().err


def test_cli_reports_missing_and_invalid_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["analyze", str(tmp_path / "nope.json")]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert main(["analyze", str(bad)]) == 2
    assert capsys.readouterr().err.count("error:") == 2


def test_cli_bench_requires_confirmation(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["bench", "--dsn", "postgresql://x/y"]) == 2
    assert "--yes" in capsys.readouterr().err
