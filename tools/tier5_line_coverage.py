"""Naming-agnostic line coverage for the nine Tier-5 functions.

Why this exists
---------------
A grep for a function's NAME in the test files measures how the tests happened
to be named, not what code the tests actually execute.  ``run_regression`` has
many dedicated behavioural tests (``test_mechanism_is_recorded_on_the_result``,
``test_the_regression_type_used_is_named_in_the_context``, ...) yet ZERO of
their names contain the string ``run_regression``, so a name-grep reports 0.

This tool measures the real thing: it runs the dedicated test files under a
``sys.settrace`` line tracer and records which SOURCE LINE of each of the nine
target functions actually executes.  It needs no third-party dependency.

Run::

    uv run python tools/tier5_line_coverage.py              # the table
    uv run python tools/tier5_line_coverage.py --uncovered  # + missing lines

It is READ-ONLY: it imports the library, runs pytest, and prints a table.
"""

from __future__ import annotations

import importlib
import inspect
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import FrameType
from typing import Any

TARGETS: dict[str, str] = {
    "run_regression": "macro_engine.models.econometrics",
    "test_stationarity": "macro_engine.models.econometrics",
    "test_cointegration": "macro_engine.models.econometrics",
    "compute_pca": "macro_engine.models.econometrics",
    "kalman_latent_state": "macro_engine.models.econometrics",
    "monte_carlo_var": "macro_engine.models.risk",
    "compute_risk_parity_weights": "macro_engine.portfolio.risk_budget",
    "classify_regime_markov_switching": "macro_engine.models.regime",
    "yield_curve_pca": "macro_engine.models.yield_curve",
}

TEST_FILES = [
    "tests/models/test_econometrics.py",
    "tests/models/test_monte_carlo_var.py",
    "tests/portfolio/test_risk_budget.py",
    "tests/portfolio/test_risk_parity.py",
    "tests/models/test_regime.py",
    "tests/models/test_yield_curve.py",
]


def _executable_lines(fn: Any) -> set[int]:
    """Return the line numbers in ``fn`` that carry executable code.

    Uses the function's code object (``co_lines``) so blank lines and pure
    comment lines are excluded from the denominator -- otherwise a function
    with a long docstring would look under-covered by construction.
    """
    code = fn.__code__
    return {lineno for _, _, lineno in code.co_lines() if lineno is not None}


def _source_path(fn: Any) -> str:
    """Absolute path of ``fn``'s source file."""
    src = inspect.getsourcefile(fn)
    if src is None:
        raise RuntimeError(f"cannot locate source for {fn!r}")
    return str(Path(src).resolve())


def main() -> int:
    lines_of: dict[str, set[int]] = {}
    path_of: dict[str, str] = {}
    for name, mod_name in TARGETS.items():
        mod = importlib.import_module(mod_name)
        fn = getattr(mod, name)
        path_of[name] = _source_path(fn)
        lines_of[name] = _executable_lines(fn)

    # Map: absolute source file -> every line the tracer should watch.
    wanted_per_file: dict[str, set[int]] = {}
    for name in TARGETS:
        wanted_per_file.setdefault(path_of[name], set()).update(lines_of[name])

    executed: dict[str, set[int]] = {}

    def tracer(frame: FrameType, event: str, arg: object) -> Any:
        fname = frame.f_code.co_filename
        if fname in wanted_per_file:
            if event == "line":
                executed.setdefault(fname, set()).add(frame.f_lineno)
            return tracer
        return None

    import pytest

    argv = [*TEST_FILES, "-q", "--no-header", "-p", "no:cacheprovider"]
    sys.settrace(tracer)
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            rc = pytest.main(argv)
    finally:
        sys.settrace(None)

    print("=" * 74)
    print("Naming-agnostic line coverage of the nine Tier-5 functions")
    print("=" * 74)
    print(f"{'function':<34}{'exec':>7}{'total':>7}{'%':>8}")
    print("-" * 74)
    big_total = 0
    big_exec = 0
    for name in TARGETS:
        path = path_of[name]
        total = lines_of[name]
        hit = total & executed.get(path, set())
        total_n = len(total)
        hit_n = len(hit)
        big_total += total_n
        big_exec += hit_n
        pct = (100.0 * hit_n / total_n) if total_n else 0.0
        print(f"{name:<34}{hit_n:>7}{total_n:>7}{pct:>7.1f}%")
    print("-" * 74)
    pct = (100.0 * big_exec / big_total) if big_total else 0.0
    print(f"{'TOTAL':<34}{big_exec:>7}{big_total:>7}{pct:>7.1f}%")
    print("=" * 74)

    # Dump the uncovered lines so the gap can be judged (real hole vs. a
    # defensive branch that only fires on a library change).
    if "--uncovered" in sys.argv:
        print()
        print("Uncovered source lines:")
        for name in TARGETS:
            path = path_of[name]
            missing = sorted(lines_of[name] - executed.get(path, set()))
            if not missing:
                continue
            print(f"\n  {name}  ({path}):")
            src = Path(path).read_text(encoding="utf-8").splitlines()
            for ln in missing:
                text = src[ln - 1].strip() if 0 < ln <= len(src) else "<out of range>"
                print(f"    L{ln}: {text}")
    return int(rc)


if __name__ == "__main__":
    raise SystemExit(main())
