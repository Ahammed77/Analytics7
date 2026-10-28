"""Compare an endpoint answer with a case's expected result (used by tests and the approved-question runner)."""
from __future__ import annotations

from typing import Any

TOLERANCE = 0.005


def _same(expected: Any, actual: Any) -> bool:
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(expected - actual) <= TOLERANCE
    return str(expected) == str(actual)


def _matches(expected_row: dict, actual_row: dict) -> bool:
    return all(key in actual_row and _same(value, actual_row[key]) for key, value in expected_row.items())


def rows_as_dicts(answer: dict[str, Any]) -> list[dict[str, Any]]:
    keys = [c["key"] for c in answer["columns"]]
    return [dict(zip(keys, row)) for row in answer["rows"]]


def compare(expect: dict[str, Any], answer: dict[str, Any]) -> list[str]:
    """Return the ways the answer differs from the expectation; empty means it passes."""
    kind = expect.get("kind", "answer")
    if answer.get("kind") != kind:
        return [f"expected {kind}, got {answer.get('kind')}: {answer.get('text', '')}".strip()]
    if kind != "answer":
        return []
    keys = [c["key"] for c in answer["columns"]]
    actual = rows_as_dicts(answer)
    wanted = expect.get("rows", [])
    if len(actual) != len(wanted):
        return [f"expected {len(wanted)} rows, got {len(actual)}"]
    missing_columns = sorted({k for row in wanted for k in row} - set(keys))
    if missing_columns:
        return [f"missing columns {missing_columns}"]
    if expect.get("ordered"):
        return [f"row {i + 1}: expected {w}, got {a}" for i, (w, a) in enumerate(zip(wanted, actual)) if not _matches(w, a)]
    remaining = list(actual)
    problems = []
    for row in wanted:
        hit = next((a for a in remaining if _matches(row, a)), None)
        if hit is None:
            problems.append(f"no row matches {row}")
        else:
            remaining.remove(hit)
    return problems
