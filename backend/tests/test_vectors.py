"""Golden vectors: the Python engine must reproduce contracts/vectors/*.json exactly.

* ``analysis-*.json``  : ``{input, expected}`` pairs for ``analyze`` (single case, a list of
  cases, or an object with a ``cases`` list; ``expected`` may also be called ``output``).
* ``normalization.json``: cases for the primitives in ``recruit_radar.engine.normalize``,
  either grouped by function name or as a flat list of ``{fn, input, expected}`` objects.

When no vector file exists the tests skip with a clear message, unless ``RR_REQUIRE_VECTORS=1``
is set, in which case the absence itself is a failure (use that in CI and in release gates).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from recruit_radar.engine import EngineInputError, analyze
from recruit_radar.engine import normalize as norm

REPO_ROOT = Path(__file__).resolve().parents[2]
VECTORS_DIR = Path(os.environ.get("RR_VECTORS_DIR") or REPO_ROOT / "contracts" / "vectors")
REQUIRE_VECTORS = os.environ.get("RR_REQUIRE_VECTORS") == "1"

EXPECTED_KEYS = ("expected", "output", "expect", "analysis", "result")
NORMALIZATION_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "norm_text": norm.norm_text,
    "company_key": norm.company_key,
    "title_key": norm.title_key,
    "location_key": norm.location_key,
    "token_sequence_match": norm.token_sequence_match,
    "sha12": norm.sha12,
    "levenshtein": norm.levenshtein,
}
TWO_ARGUMENT_FUNCTIONS = {"token_sequence_match", "levenshtein"}


@dataclass(frozen=True)
class Case:
    case_id: str
    kind: str  # "analysis" | "normalization" | "error"
    payload: Any
    expected: Any = None
    function: str = ""


# ---------------------------------------------------------------------------------------------
# Exact comparison
# ---------------------------------------------------------------------------------------------
def first_difference(actual: Any, expected: Any, path: str = "$") -> str | None:
    """Path and values of the first strict difference, or ``None`` when identical.

    Strict means JSON-exact: ``True`` is not ``1`` and ``1`` is not ``1.0``; objects compare by
    key set (order irrelevant), arrays by element order.
    """
    if type(actual) is not type(expected):
        return f"{path}: type {type(actual).__name__} != {type(expected).__name__} ({actual!r} vs {expected!r})"
    if isinstance(actual, dict):
        for key in sorted(set(actual) | set(expected)):
            if key not in actual:
                return f"{path}.{key}: missing from actual (expected {expected[key]!r})"
            if key not in expected:
                return f"{path}.{key}: unexpected key in actual ({actual[key]!r})"
            found = first_difference(actual[key], expected[key], f"{path}.{key}")
            if found is not None:
                return found
        return None
    if isinstance(actual, list):
        if len(actual) != len(expected):
            return f"{path}: length {len(actual)} != {len(expected)}"
        for index, (a, e) in enumerate(zip(actual, expected, strict=True)):
            found = first_difference(a, e, f"{path}[{index}]")
            if found is not None:
                return found
        return None
    return None if actual == expected else f"{path}: {actual!r} != {expected!r}"


# ---------------------------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------------------------
def _expected_of(case: dict[str, Any]) -> tuple[bool, Any]:
    for key in EXPECTED_KEYS:
        if key in case:
            return True, case[key]
    return False, None


def load_analysis_cases(path: Path) -> list[Case]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and isinstance(raw.get("cases"), list):
        items = raw["cases"]
    elif isinstance(raw, list):
        items = raw
    else:
        items = [raw]
    cases: list[Case] = []
    for index, item in enumerate(items):
        default_name = path.stem if len(items) == 1 else f"{path.stem}[{index}]"
        name = (
            f"{path.name}::{item.get('name') or default_name}"
            if isinstance(item, dict)
            else default_name
        )
        if not isinstance(item, dict) or "input" not in item:
            cases.append(Case(name, "error", f"{path.name}: case {index} has no 'input' object"))
            continue
        has_expected, expected = _expected_of(item)
        if not has_expected:
            cases.append(Case(name, "error", f"{path.name}: case {index} has no expected output"))
            continue
        cases.append(Case(name, "analysis", item["input"], expected))
    return cases


def _normalization_case(case_id: str, function: str, item: Any) -> Case:
    if function not in NORMALIZATION_FUNCTIONS:
        return Case(case_id, "error", f"unknown normalization function {function!r}")
    if isinstance(item, list) and len(item) == 2:
        raw_input, expected = item
    elif isinstance(item, dict):
        has_expected, expected = _expected_of(item)
        if not has_expected and "out" in item:
            has_expected, expected = True, item["out"]
        if "input" in item:
            raw_input = item["input"]
        elif "args" in item:
            raw_input = item["args"]
        elif "in" in item:
            raw_input = item["in"]
        else:
            return Case(case_id, "error", f"{case_id}: no input/args in {item!r}")
        if not has_expected:
            return Case(case_id, "error", f"{case_id}: no expected value in {item!r}")
    else:
        return Case(case_id, "error", f"{case_id}: unrecognized case layout {item!r}")
    return Case(case_id, "normalization", raw_input, expected, function)


def load_normalization_cases(path: Path) -> list[Case]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases: list[Case] = []
    if isinstance(raw, dict) and isinstance(raw.get("cases"), list):
        raw = raw["cases"]
    if isinstance(raw, dict):
        for function, items in raw.items():
            if not isinstance(items, list):
                continue  # metadata such as "description" or "version"
            for index, item in enumerate(items):
                cases.append(
                    _normalization_case(f"{path.name}::{function}[{index}]", function, item)
                )
    elif isinstance(raw, list):
        for index, item in enumerate(raw):
            function = ""
            if isinstance(item, dict):
                function = str(
                    item.get("fn")
                    or item.get("function")
                    or item.get("name")
                    or item.get("op")
                    or ""
                )
            cases.append(_normalization_case(f"{path.name}::{function}[{index}]", function, item))
    else:
        cases.append(
            Case(path.name, "error", f"{path.name}: unrecognized layout ({type(raw).__name__})")
        )
    if not cases:
        cases.append(Case(path.name, "error", f"{path.name}: contains no cases"))
    return cases


def discover(directory: Path = VECTORS_DIR) -> list[Case]:
    cases: list[Case] = []
    for path in sorted(directory.glob("analysis-*.json")):
        try:
            cases.extend(load_analysis_cases(path))
        except (OSError, ValueError) as exc:
            cases.append(Case(path.name, "error", f"{path.name}: cannot load ({exc})"))
    normalization = directory / "normalization.json"
    if normalization.is_file():
        try:
            cases.extend(load_normalization_cases(normalization))
        except (OSError, ValueError) as exc:
            cases.append(
                Case(normalization.name, "error", f"{normalization.name}: cannot load ({exc})")
            )
    return cases


# ---------------------------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------------------------
def call_normalization(function: str, raw_input: Any) -> Any:
    target = NORMALIZATION_FUNCTIONS[function]
    if isinstance(raw_input, dict):
        arguments = list(raw_input.values())
    elif isinstance(raw_input, list) and function in TWO_ARGUMENT_FUNCTIONS:
        arguments = raw_input
    else:
        arguments = [raw_input]
    return target(*arguments)


def run_case(case: Case) -> None:
    if case.kind == "error":
        pytest.fail(str(case.payload))
    if case.kind == "analysis":
        actual = analyze(case.payload)
    else:
        actual = call_normalization(case.function, case.payload)
    difference = first_difference(actual, case.expected)
    assert difference is None, f"{case.case_id}: first difference at {difference}"


CASES = discover()
NO_VECTORS = Case("no-vectors-present", "none", None)


def _absence_message() -> str:
    return (
        f"no golden vectors found in {VECTORS_DIR} "
        "(expected analysis-*.json and/or normalization.json)"
    )


@pytest.mark.parametrize(
    "case", CASES or [NO_VECTORS], ids=[c.case_id for c in CASES or [NO_VECTORS]]
)
def test_vector(case: Case) -> None:
    if case.kind == "none":
        if REQUIRE_VECTORS:
            pytest.fail(_absence_message() + "; RR_REQUIRE_VECTORS=1 makes this a failure")
        pytest.skip(_absence_message() + "; set RR_REQUIRE_VECTORS=1 to make this a failure")
    run_case(case)


# ---------------------------------------------------------------------------------------------
# The loader itself (exercised on throwaway files, never on the real vectors)
# ---------------------------------------------------------------------------------------------
class TestLoader:
    def test_strict_comparison(self) -> None:
        assert first_difference({"a": [1, 2]}, {"a": [1, 2]}) is None
        assert first_difference({"a": 1}, {"a": True}) is not None
        assert first_difference({"a": 1}, {"a": 1.0}) is not None
        assert first_difference({"a": [1]}, {"a": [1, 2]}) == "$.a: length 1 != 2"
        assert first_difference({"a": 1}, {"b": 1}) is not None
        assert first_difference({"k": None}, {"k": None}) is None
        assert first_difference({"x": {"y": "s"}}, {"x": {"y": "t"}}) == "$.x.y: 's' != 't'"

    def test_analysis_file_layouts(self, tmp_path: Path) -> None:
        empty = {"as_of": "2026-10-13T12:00:00Z"}
        (tmp_path / "analysis-a.json").write_text(
            json.dumps({"name": "single", "input": empty, "expected": {"x": 1}}), encoding="utf-8"
        )
        (tmp_path / "analysis-b.json").write_text(
            json.dumps({"cases": [{"input": empty, "output": 1}, {"input": empty, "expected": 2}]}),
            encoding="utf-8",
        )
        (tmp_path / "analysis-c.json").write_text(json.dumps([{"input": empty}]), encoding="utf-8")
        found = discover(tmp_path)
        assert [(c.case_id, c.kind) for c in found] == [
            ("analysis-a.json::single", "analysis"),
            ("analysis-b.json::analysis-b[0]", "analysis"),
            ("analysis-b.json::analysis-b[1]", "analysis"),
            ("analysis-c.json::analysis-c", "error"),
        ]

    def test_normalization_layouts(self, tmp_path: Path) -> None:
        (tmp_path / "normalization.json").write_text(
            json.dumps(
                {
                    "description": "x",
                    "norm_text": [{"input": "A, B", "expected": "a b"}, ["Z", "z"]],
                    "token_sequence_match": [{"input": ["a b c", "b c"], "expected": True}],
                    "bogus_fn": [["x", "y"]],
                }
            ),
            encoding="utf-8",
        )
        found = discover(tmp_path)
        assert [c.kind for c in found] == [
            "normalization",
            "normalization",
            "normalization",
            "error",
        ]
        for case in found[:3]:
            run_case(case)

    def test_flat_normalization_list(self, tmp_path: Path) -> None:
        (tmp_path / "normalization.json").write_text(
            json.dumps(
                [
                    {"fn": "company_key", "input": "The Acme Corp.", "expected": "acme"},
                    {"function": "levenshtein", "args": ["kitten", "sitting"], "expected": 3},
                    {"fn": "sha12", "input": "abc", "expected": "ba7816bf8f01"},
                ]
            ),
            encoding="utf-8",
        )
        for case in discover(tmp_path):
            run_case(case)

    def test_a_mismatch_is_reported_with_a_path(self) -> None:
        case = Case("c", "normalization", "Hello", "nope", "norm_text")
        with pytest.raises(AssertionError, match=r"\$: 'hello' != 'nope'"):
            run_case(case)

    def test_analyze_error_type_is_importable_for_error_vectors(self) -> None:
        with pytest.raises(EngineInputError):
            analyze({"snapshots": []})
