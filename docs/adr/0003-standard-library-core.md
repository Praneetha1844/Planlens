# ADR 0003: A standard-library core with an optional database extra

Status: accepted

## Context

Planlens parses text and reasons about trees. Only the benchmark harness and the hypopg adapter need a database driver.

## Decision

- The core (`plan`, `expr`, `findings`, `advisor`, `report`, `datagen`, `cli analyze|gen`) uses only the Python standard library and declares **no runtime dependencies**.
- `psycopg` lives in an optional extra, `planlens[db]`. `planlens bench` imports it lazily and prints how to install it if it is missing.
- `bench` and `whatif` depend on small `Cursor` and `Connection` protocols, not on psycopg types.

## Consequences

- The analyser installs and runs anywhere Python 3.12 does, which suits CI jobs and one-off use on a server.
- Tests for the harness and the adapter use scripted stand-in cursors, so the suite needs no database.
- The scripted cursors only prove the harness issues the right statements in the right order. They do not prove the SQL runs on a real server.
- Dataclasses and `argparse` are less convenient than pydantic and typer, and the code does more manual validation. That is accepted for a library with no dependencies.
