"""The live-test time bound must stay configured (O-110).

**The defect this file exists to pin.** O-110 recorded two halves:

* **(fixed at D-087.6)** the default run reached the `live` tests, so a plain
  ``uv run pytest`` fanned out ~21 sequential network calls with 3 retries x 15 s
  timeout each; a single test was measured at **over 40 minutes**. Fixed by
  ``-m 'not live and not slow'`` in ``addopts``.
* **(the durable half, this increment)** *"there is still no per-test timeout, so
  a single live test can hang indefinitely **when it is asked for**."* Excluding
  a marker bounds what a **default** run touches; it does nothing about a test
  that is deliberately asked for, or one that opens a socket without being
  marked. ``pytest-timeout`` is now installed and ``--timeout`` is set.

**Why a test and not just the setting.** The project's rule is explicit —
**enforce it, or it is only documented** (standing rule 2). A timeout in
``addopts`` is a config line, and a config line is exactly the kind of thing a
future contributor removes while chasing an unrelated slow test. The same shape
happened to this project's ``sweep_health.py`` in CI: the tool existed and
nothing ran it, so it *was* documented and *did* nothing. The guard below is what
makes the bound a property of the suite rather than a preference.

**The number is checked, not just its presence.** A bare ``--timeout`` assertion
would pass on ``--timeout=1``, which would kill every legitimate test — a guard
that admits the opposite defect. So the value is parsed and asserted to clear the
**measured** worst offline case with headroom, and the reasoning is recorded in
``pyproject.toml`` where a reviewer will see it.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _PROJECT_ROOT / "pyproject.toml"

#: The slowest legitimate OFFLINE test, measured (D-087.27):
#: ``test_the_two_copies_agree_on_the_real_catalogue`` at **162 s** — it loads all
#: sweeps. Recorded here as a number because the timeout must clear it; if a
#: future test legitimately exceeds the timeout, THIS is the constant to re-derive
#: (and then the timeout, together).
#:
#: NOTE (D-092): the sweep census is now **43**, one more than when this was
#: measured, and this constant has **not** been re-taken. The staleness is in the
#: safe direction — the derived floor is 162 x 1.5 = 243 s against a 300 s bound,
#: so one additional sweep cannot move the verdict. Re-measure before relying on
#: the *headroom*; the gate itself is unaffected.
_MEASURED_WORST_OFFLINE_SECONDS = 162.0

#: The headroom the timeout must keep over the measured worst case. 1.5x is the
#: floor: a bound that only just clears the current slowest test is a bound that
#: fails the first time CI is slow, and a gate that goes red for a reason nobody
#: can fix is a gate people learn to skip (the project's own words).
_MIN_HEADROOM = 1.5


def _pytest_config() -> dict[str, object]:
    """The ``[tool.pytest.ini_options]`` table, parsed with stdlib ``tomllib``."""
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    config = data.get("tool", {}).get("pytest", {}).get("ini_options", {})
    assert isinstance(config, dict), "pyproject has no [tool.pytest.ini_options] table"
    return config


def _addopts() -> str:
    addopts = _pytest_config().get("addopts", "")
    assert isinstance(addopts, str), "addopts is not a string"
    return addopts


def test_a_per_test_timeout_is_configured() -> None:
    """The load-bearing assertion: O-110's durable half is actually wired.

    Without this the marker filter is the only bound, and it is not a bound on a
    test that was asked for — which is precisely the state O-110 recorded.
    """
    addopts = _addopts()
    assert "--timeout=" in addopts, (
        "no --timeout in pytest addopts. O-110's remaining half is *'a single "
        "live test can hang indefinitely when it is asked for'*; excluding the "
        "`live` marker bounds a DEFAULT run but not a deliberate one. Install "
        "pytest-timeout (it is already a dev dependency) and set --timeout."
    )


def test_the_timeout_clears_the_measured_worst_case() -> None:
    """A timeout below the real worst case is WORSE than no timeout.

    It kills a correct test, and on ``win32`` the kill leaves no ``finally`` — so
    the file-based sweep sidecars, not a handler, are what survives. The value
    must clear the measured worst offline test with headroom.
    """
    match = re.search(r"--timeout=(\d+)", _addopts())
    assert match is not None, "could not parse the --timeout value from addopts"
    timeout = int(match.group(1))

    floor = _MEASURED_WORST_OFFLINE_SECONDS * _MIN_HEADROOM
    assert timeout >= floor, (
        f"--timeout={timeout} does not clear the measured worst offline test "
        f"({_MEASURED_WORST_OFFLINE_SECONDS:.0f} s) by the required "
        f"{_MIN_HEADROOM}x headroom (floor {floor:.0f} s). A timeout below the "
        "real worst case kills correct tests -- re-derive BOTH numbers together "
        "if a test legitimately got slower."
    )
    # And it must still be a bound: a huge value is the defect returning in
    # disguise (it would not fire before the >40 min hang it exists to catch).
    assert timeout <= 1800, (
        f"--timeout={timeout} is so large it would not fire before the "
        ">40-minute hang O-110 recorded. This is a bound, not a formality."
    )


def test_the_timeout_method_is_not_pinned_to_signal() -> None:
    """Pinning ``--timeout-method=signal`` would DISABLE the timeout on win32.

    ``signal`` uses ``SIGALRM``; this platform has no ``SIGALRM``, and the
    plugin's value is that it defaults to ``thread`` where ``signal`` is
    unavailable. Pinning it would silently restore the O-110 defect — a timeout
    that is configured and never fires, which is indistinguishable from no
    timeout until something hangs.
    """
    addopts = _addopts()
    assert "--timeout-method=signal" not in addopts, (
        "`--timeout-method=signal` is pinned. On win32 SIGALRM does not exist, "
        "so this would disable the timeout while leaving it looking configured. "
        "Leave the method unset so the plugin picks `thread` here."
    )


def test_the_live_marker_is_still_excluded_by_default() -> None:
    """O-110's FIRST half must not regress while fixing the second.

    The per-test timeout and the marker filter are complements, not alternatives:
    the filter keeps a default run off the network, the timeout bounds a run that
    deliberately goes there. A change that added the timeout while dropping the
    filter would leave the default run as expensive as it was at D-087.6.
    """
    addopts = _addopts()
    assert "not live" in addopts, (
        "the default run no longer excludes `live` tests. The per-test timeout "
        "does NOT substitute for this: a timeout still lets the default run make "
        "the calls, it just stops one of them running forever."
    )
    assert "not slow" in addopts, "the default run no longer excludes `slow` tests"


def test_pytest_timeout_is_a_declared_dependency() -> None:
    """A configured plugin that is not a dependency fails on a clean install.

    CI runs ``uv sync --extra dev --frozen``; a plugin imported by ``addopts``
    but absent from the extra would make every CI run fail with an unknown
    option. The dependency is asserted in BOTH declarations the project uses —
    ``[project.optional-dependencies]`` (what CI's ``--extra dev`` installs) and
    ``[dependency-groups]`` (what local ``uv run`` installs).
    """
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))

    extras = data.get("project", {}).get("optional-dependencies", {}).get("dev", [])
    assert any(str(dep).startswith("pytest-timeout") for dep in extras), (
        "pytest-timeout is missing from [project.optional-dependencies].dev -- "
        "CI's `uv sync --extra dev` would then not install it, and every run "
        "would fail on the unknown --timeout option."
    )

    groups = data.get("dependency-groups", {}).get("dev", [])
    assert any(str(dep).startswith("pytest-timeout") for dep in groups), (
        "pytest-timeout is missing from [dependency-groups].dev -- a local "
        "`uv run pytest` would then not have the plugin."
    )


@pytest.mark.parametrize("marker", ["live", "slow", "offline", "golden", "warning_path"])
def test_the_documented_markers_are_still_registered(marker: str) -> None:
    """``--strict-markers`` makes an unregistered marker a hard error.

    A cheap guard, but it is the one that turns a typo'd marker into a loud
    failure rather than a silently-unapplied one — which matters more now that
    the ``live``/``slow`` markers are load-bearing for cost.
    """
    markers = _pytest_config().get("markers", [])
    assert isinstance(markers, list)
    assert any(str(m).startswith(marker) for m in markers), (
        f"the `{marker}` marker is no longer registered in pyproject's markers "
        "list; with --strict-markers this makes it unusable."
    )
