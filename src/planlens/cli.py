"""Command line interface: `planlens analyze | gen | bench`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .advisor import suggest_indexes
from .findings import Thresholds, analyze
from .plan import PlanParseError, parse_explain
from .report import render_html, render_json, render_markdown

RENDERERS = {"md": render_markdown, "html": render_html, "json": render_json}


def _parse_existing(values: list[str]) -> list[tuple[str, tuple[str, ...]]]:
    """Turn `table:col1,col2` arguments into (table, (col1, col2)) pairs."""
    parsed: list[tuple[str, tuple[str, ...]]] = []
    for value in values:
        table, sep, cols = value.partition(":")
        columns = tuple(c.strip() for c in cols.split(",") if c.strip())
        if not table or not sep or not columns:
            raise ValueError(f"--existing expects table:col1,col2 but got {value!r}")
        parsed.append((table, columns))
    return parsed


def _cmd_analyze(args: argparse.Namespace) -> int:
    try:
        text = sys.stdin.read() if args.plan == "-" else Path(args.plan).read_text(encoding="utf-8")
        plan = parse_explain(text)
        limits = Thresholds(
            min_rows_scanned=args.min_rows, mismatch_factor=args.mismatch_factor
        )
        existing = _parse_existing(args.existing)
    except (OSError, PlanParseError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    found = analyze(plan, limits)
    suggestions = suggest_indexes(plan, found, existing=existing, limits=limits)
    output = RENDERERS[args.format](plan, found, suggestions)
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
    else:
        print(output)
    return 0


def _cmd_gen(args: argparse.Namespace) -> int:
    from .datagen import generate

    try:
        counts = generate(Path(args.out), scale=args.scale, seed=args.seed)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for table, rows in counts.items():
        print(f"{table}: {rows} rows")
    return 0


def _cmd_bench(args: argparse.Namespace) -> int:
    from .bench import load_queries, run_benchmark, summarise, write_csv

    if not args.yes:
        print(
            "error: bench creates and drops indexes in the target database; "
            "pass --yes to confirm it is a disposable one.",
            file=sys.stderr,
        )
        return 2
    try:
        import psycopg
    except ImportError:
        print("error: install the db extra: pip install 'planlens[db]'", file=sys.stderr)
        return 2
    try:
        queries = load_queries(Path(args.queries))
        with psycopg.connect(args.dsn, autocommit=True) as connection:
            rows = run_benchmark(connection, queries, repeat=args.repeat)
    except (OSError, ValueError, psycopg.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    write_csv(rows, Path(args.out))
    for line in summarise(rows):
        print(f"{line['query']:<28} {line['phase']:<7} median {line['median_ms']} ms")
    print(f"wrote {len(rows)} row(s) to {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="planlens", description=__doc__)
    parser.add_argument("--version", action="version", version=f"planlens {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", help="analyse an EXPLAIN (FORMAT JSON) file")
    a.add_argument("plan", help="path to the JSON plan, or - for stdin")
    a.add_argument("--format", choices=sorted(RENDERERS), default="md")
    a.add_argument("--out", help="write the report here instead of stdout")
    a.add_argument("--existing", action="append", default=[], metavar="TABLE:COL,COL",
                   help="an index that already exists (repeatable)")  # fmt: skip
    a.add_argument("--min-rows", type=int, default=Thresholds.min_rows_scanned)
    a.add_argument("--mismatch-factor", type=float, default=Thresholds.mismatch_factor)
    a.set_defaults(func=_cmd_analyze)

    g = sub.add_parser("gen", help="generate seeded demo data as CSV")
    g.add_argument("--out", default="data")
    g.add_argument("--scale", type=float, default=1.0)
    g.add_argument("--seed", type=int, default=42)
    g.set_defaults(func=_cmd_gen)

    b = sub.add_parser("bench", help="time queries before and after their index")
    b.add_argument("--dsn", required=True, help="PostgreSQL connection string (disposable DB)")
    b.add_argument("--queries", default="benchmark/queries")
    b.add_argument("--out", default="results.csv")
    b.add_argument("--repeat", type=int, default=5)
    b.add_argument("--yes", action="store_true", help="confirm the database is disposable")
    b.set_defaults(func=_cmd_bench)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
