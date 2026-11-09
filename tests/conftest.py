"""Shared fixtures for the test suite."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from planlens.plan import Plan, parse_explain

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_text() -> Callable[[str], str]:
    """Return the text of a hand-written plan fixture, by name without `.json`."""

    def read(name: str) -> str:
        return (FIXTURES / f"{name}.json").read_text(encoding="utf-8")

    return read


@pytest.fixture
def plan_of(fixture_text: Callable[[str], str]) -> Callable[[str], Plan]:
    """Parse a fixture by name."""

    def parse(name: str) -> Plan:
        return parse_explain(fixture_text(name))

    return parse
