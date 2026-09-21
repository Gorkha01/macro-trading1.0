"""Tests for the OpenBB reachability probe (O-111(a), D-087.15).

**The defect this file exists to pin.** For a day, `settings.yaml` pointed at
`:6901` — a port that is **bound but answers 502 Bad Gateway** on every data
route. Every gate passed, every unit test passed, and **three coverage tests
skipped** with *"local OpenBB service not reachable"*, so a dead endpoint
**deleted coverage without failing anything**. The cost surfaced only as
unexplained slowness: a snapshot build retried 42 series x 3 attempts against
the 502 and exceeded 400 s, where the same build against `:6900` takes 83 s.

The reason nothing caught it is the distinction these tests pin:

    ``:6900``  reachable=True  status=200  paths=278  -> SERVES
    ``:6901``  reachable=True  status=502  paths=0    -> does NOT serve

**Both are reachable.** "Can I connect?" was never a sufficient question, and
the project had no command that asked a better one. These tests make the
better question executable, and they are all **offline**: the transport is
monkeypatched, so the suite stays deterministic and needs no live service.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PROBE = _ROOT / "tools" / "openbb_reachability.py"


def _load(path: Path, name: str) -> Any:
    """Import a module from a path, the way the other tool tests do.

    ``tools/`` is not a package, so there is no importable name to use.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def probe_mod() -> Any:
    return _load(_PROBE, "_openbb_reachability_probe")


def _fake_get(
    *,
    status: int = 200,
    body: Any = None,
    raises: Exception | None = None,
) -> Any:
    """A ``httpx.get`` replacement returning one canned response."""

    def _get(url: str, *, timeout: float) -> Any:
        if raises is not None:
            raise raises
        return httpx.Response(
            status_code=status,
            json=body,
            request=httpx.Request("GET", url),
        )

    return _get


# ---------------------------------------------------------------------------
# The distinction the defect turned on
# ---------------------------------------------------------------------------


def test_a_502_on_a_bound_port_does_not_serve(
    probe_mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE pin: reachable is not serving, and ``:6901`` is exactly this case.

    This is the single assertion that would have caught O-111 on day one. A
    bound port answering 502 must be reported as NOT serving, even though the
    connection succeeds — collapsing those two is what made a dead service look
    healthy to every reachability-style check the project had.
    """
    monkeypatch.setattr(
        httpx,
        "get",
        _fake_get(status=502, body={"detail": "Bad Gateway"}),
    )
    result = probe_mod.probe("http://127.0.0.1:6901")

    assert result.reachable is True, (
        "the fixture simulates a BOUND port — reachable must be True, or this "
        "test is not testing the case that broke"
    )
    assert result.status_code == 502
    assert result.serves is False, (
        "a bound port answering 502 was reported as serving; this is the exact "
        "condition O-111 recorded"
    )
    assert "O-111" in result.detail, (
        "the failure must name the recorded incident so the operator can find "
        f"the context: {result.detail!r}"
    )


def test_a_serving_service_is_reported_as_serving(
    probe_mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The negative control: a healthy service must pass, or the gate is noise.

    Both directions are asserted because a probe that always fails is the same
    cry-wolf failure as one that never does (O-88).
    """
    monkeypatch.setattr(
        httpx,
        "get",
        _fake_get(status=200, body={"paths": {"/api/v1/a": {}, "/api/v1/b": {}}}),
    )
    result = probe_mod.probe("http://127.0.0.1:6900")

    assert result.serves is True
    assert result.path_count == 2
    assert result.status_code == 200


def test_a_transport_failure_is_unreachable_not_merely_not_serving(
    probe_mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Connection refused is a DIFFERENT state from 502, and is reported so.

    The distinction matters operationally: nothing answered means the service is
    not running (fix: start it), while 502 means something is bound and
     malfunctioning (fix: re-measure which port is real). Conflating them sends
    the operator to the wrong remedy.
    """
    monkeypatch.setattr(
        httpx,
        "get",
        _fake_get(raises=httpx.ConnectError("connection refused")),
    )
    result = probe_mod.probe("http://127.0.0.1:6900")

    assert result.reachable is False
    assert result.status_code is None
    assert result.serves is False


def test_a_200_with_no_paths_is_reachable_but_not_serving(
    probe_mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reachable-but-empty conflation, which ``_openapi_paths()`` names.

    An empty path set is not the same as "could not ask", and it is not the same
    as serving either. A service returning 200 with no routes is not usable, and
    treating it as healthy would hide a half-started instance.
    """
    monkeypatch.setattr(httpx, "get", _fake_get(status=200, body={"paths": {}}))
    result = probe_mod.probe("http://127.0.0.1:6900")

    assert result.reachable is True
    assert result.status_code == 200
    assert result.path_count == 0
    assert result.serves is False, "an empty service is not a serving service"


def test_a_non_json_200_body_does_not_serve(
    probe_mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 200 whose body is not the document is not a usable service.

    Plausible in practice: an HTML error page or a proxy interstitial served
    with a 200 status. Parsing must be required, not assumed.
    """

    def _get(url: str, *, timeout: float) -> Any:
        return httpx.Response(
            status_code=200,
            content=b"<html>not json</html>",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", _get)
    result = probe_mod.probe("http://127.0.0.1:6900")

    assert result.reachable is True
    assert result.serves is False
    assert "not JSON" in result.detail


# ---------------------------------------------------------------------------
# The probe must follow config — O-113's lesson applied to the probe itself
# ---------------------------------------------------------------------------


def test_the_probe_reads_the_configured_base_url(
    probe_mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A health check with its own hard-coded host goes on passing after config moves.

    This is O-113 (*derive the host from config*) applied to the probe. The
    probe would be self-defeating if it checked a literal: it would report OK
    while the project called a different, dead URL — a false all-clear, which is
    worse than no check.
    """
    import macro_engine.config as cfg

    settings = cfg.get_settings()
    expected_base = settings.openbb.base_url.rstrip("/")

    seen: list[str] = []

    def _get(url: str, *, timeout: float) -> Any:
        seen.append(url)
        return httpx.Response(
            status_code=200,
            json={"paths": {"/api/v1/x": {}}},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", _get)
    probe_mod.probe()

    assert seen, "the probe made no request"
    assert seen[0].startswith(expected_base), (
        f"the probe called {seen[0]!r}, which does not start with the configured "
        f"base {expected_base!r} — a hard-coded host has crept into the probe"
    )


def test_an_explicit_base_url_overrides_config(
    probe_mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Passing a base must actually be honoured — that is how two ports are compared.

    The D-087.10 investigation settled which port was live by probing both; that
    is only possible if the explicit argument wins over config. A probe that
    ignored its argument would make the comparison impossible while appearing to
    support it.
    """
    seen: list[str] = []

    def _get(url: str, *, timeout: float) -> Any:
        seen.append(url)
        return httpx.Response(
            status_code=200,
            json={"paths": {"/api/v1/x": {}}},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", _get)
    probe_mod.probe("http://example.invalid:9999/")

    assert seen[0] == "http://example.invalid:9999/openapi.json"


# ---------------------------------------------------------------------------
# Exit codes are the contract (O-88: a row is a claim, so it must be readable)
# ---------------------------------------------------------------------------


def test_main_exits_zero_when_serving(probe_mod: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx,
        "get",
        _fake_get(status=200, body={"paths": {"/api/v1/x": {}}}),
    )
    assert probe_mod.main() == 0


def test_main_exits_one_when_the_port_is_bound_but_dead(
    probe_mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The O-111 state must be a FAILING exit code, not a printed warning.

    A probe whose finding is not consumed by an exit code is O-62's shape — a
    check that cannot fail is indistinguishable from one nobody ran.
    """
    monkeypatch.setattr(httpx, "get", _fake_get(status=502, body={}))
    assert probe_mod.main() == 1


def test_main_exits_one_when_nothing_answers(
    probe_mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        httpx,
        "get",
        _fake_get(raises=httpx.ConnectError("refused")),
    )
    assert probe_mod.main() == 1


# ---------------------------------------------------------------------------
# Structure: the probe must not acquire its own hard-coded host
# ---------------------------------------------------------------------------


def test_the_probe_module_contains_no_hard_coded_port() -> None:
    """A regression guard on the probe's own source (O-113 applied to itself).

    The probe is the tool that exists to catch hard-coded hosts, so it carrying
    one would be self-defeating. Docstrings may *mention* ports (they explain
    the incident); no executable line may contain one.
    """
    import ast

    source = _PROBE.read_text(encoding="utf-8")
    tree = ast.parse(source)

    # String constants in CODE only — docstrings are documentation of the
    # incident and are allowed to name the ports.
    docstrings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                value = body[0].value.value
                if isinstance(value, str):
                    docstrings.add(value)

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in docstrings:
                continue
            assert "6900" not in node.value and "6901" not in node.value, (
                f"the probe contains a hard-coded port in executable code: "
                f"{node.value!r} — derive it from config instead (O-113)"
            )


# ---------------------------------------------------------------------------
# The probe is ENFORCED in CI, and the enforcement is itself guarded.
# ---------------------------------------------------------------------------


def _workflow_step_text(job: str) -> list[str]:
    """Every field of every step — ``name``, ``run`` and ``uses``, CONCATENATED.

    Concatenating rather than choosing one field is deliberate and was itself a
    found defect: an earlier version returned ``name or run or uses``, so a step
    named *"OpenBB reachability (…)"* whose ``run`` contained
    ``tools/openbb_reachability.py`` was matched by its NAME only — and the test
    reported the probe missing when it was right there. **A predicate that picks
    the field it expects to be interesting is the same narrow-predicate failure
    this project keeps hitting (O-107).** Reading all the text removes the guess.
    """
    import yaml

    path = _ROOT / ".github" / "workflows" / "quality-gates.yml"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    steps = workflow["jobs"][job]["steps"]
    return [
        " ".join(str(v) for k, v in step.items() if k in {"name", "run", "uses"}) for step in steps
    ]


def test_the_probe_gates_the_live_data_job() -> None:
    """A tool nothing runs does not close O-111(a) — O-62 in a new costume.

    The probe was built and documented as Step 0, but documentation is not
    enforcement: the live job went straight into ``pytest -m live``, which
    **skips** the coverage checks when the service is down and therefore passes
    GREEN on a dead endpoint. This asserts the probe actually runs there and
    runs BEFORE the tests it is meant to protect.
    """
    steps = _workflow_step_text("live-data")

    probe_steps = [s for s in steps if "openbb_reachability" in s]
    assert len(probe_steps) == 1, (
        f"expected exactly one step running `tools/openbb_reachability.py` in the "
        f"live-data job, found {len(probe_steps)}: {steps}. The probe exists but "
        "nothing enforces it (O-62, one level up from O-111)."
    )

    test_steps = [s for s in steps if "pytest -m live" in s]
    assert len(test_steps) == 1, f"expected one `pytest -m live` step, found: {steps}"

    probe_at = steps.index(probe_steps[0])
    tests_at = steps.index(test_steps[0])
    assert probe_at < tests_at, (
        "the reachability probe must run BEFORE `pytest -m live`; running it after "
        "means the tests have already skipped and the job has already gone green "
        "(the probe would report a failure nobody needed)"
    )


def test_the_probe_step_can_actually_fail_the_job() -> None:
    """The probe must not be neutered into a warning.

    ``|| true``, ``continue-on-error``, an explicit ``exit 0`` — any of these
    converts the gate back into the false all-clear it was built to remove. The
    probe's exit codes are the contract (O-88): only an unguarded invocation
    lets a non-zero exit fail the step.
    """
    import yaml

    path = _ROOT / ".github" / "workflows" / "quality-gates.yml"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    probe_steps = [
        s
        for s in workflow["jobs"]["live-data"]["steps"]
        if "openbb_reachability" in str(s.get("run") or s.get("name") or "")
    ]
    assert probe_steps, "no probe step found (see the ordering test)"

    step = probe_steps[0]
    run = str(step.get("run", ""))
    assert "|| true" not in run, f"the probe step swallows failure: {run!r}"
    assert "continue-on-error" not in step or not step["continue-on-error"], (
        "the probe step is marked continue-on-error, so a dead service cannot fail "
        f"the job: {step!r}"
    )
    assert "|| exit 0" not in run and "|| true" not in run, f"forced success: {run!r}"
