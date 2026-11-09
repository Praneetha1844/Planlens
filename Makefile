.PHONY: install lint format typecheck test check

install:
	python -m pip install -e ".[dev,db]"

lint:
	ruff check .

format:
	ruff format .

typecheck:
	mypy

test:
	pytest

check: lint typecheck test
