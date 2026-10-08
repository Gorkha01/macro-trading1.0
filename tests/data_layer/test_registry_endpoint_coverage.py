"""D-086 §8 Change 5: every registry endpoint must exist on the live service.

The audit's own closing recommendation, and the guard that would have surfaced
its §4.1 findings automatically: **before** D-086 the registry pointed at
`economy.fred_series` for 44 of 44 entries and nobody had checked which *other*
commands existed. A wrong endpoint is normally caught the first time the series
is fetched — but a series fetched once and cached, or one whose endpoint is
merely *suboptimal* rather than broken, never announces itself.

What this asserts, in two halves
--------------------------------
**Offline (always runs):** the registry's own declarations are internally
consistent — every `tenor_labels` key is a declared tenor, every declared tenor
has a label, and no entry names an endpoint that is not a dotted
``namespace.command`` path. These are cheap, deterministic, and catch the
config-authoring mistakes.

**Live (skipped when the service is unreachable):** every distinct endpoint the
registry names appears in the live ``/openapi.json``. This is the half that
needs the service, so it **skips** rather than fails when the local OpenBB
instance is down — an external dependency being unavailable is not a regression
in this repository, and a test that fails for it would be turned off within a
week (the O-88 lesson: a gate that cries wolf stops being read).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from macro_engine.config import get_registry, get_settings

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _openapi_paths() -> set[str] | None:
    """The live service's path set, or ``None`` when it is not reachable.

    ``None`` means "could not ask", which is deliberately distinct from an empty
    set ("asked and there are no paths"). Collapsing the two would make an
    unreachable service look like a service with no endpoints — the
    reachable-but-empty vs never-attempted conflation.
    """
    base = get_settings().openbb.base_url.rstrip("/")
    try:
        resp = httpx.get(f"{base}/openapi.json", timeout=5.0)
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    try:
        payload: Any = resp.json()
    except ValueError:
        return None
    paths = payload.get("paths") if isinstance(payload, dict) else None
    if not isinstance(paths, dict):
        return None
    return {str(p) for p in paths}


def _require_service(context: str) -> set[str]:
    """The live path set, or a **loud** skip naming why the service was unusable.

    The skip is retained — an external dependency being down is not a regression
    in this repository, and a test that fails for it gets turned off within a
    week (O-88). But O-111 showed the *reason* matters enormously: `:6901` was
    **bound and answering 502**, and the flat message *"service not reachable"*
    was read as an environment quirk rather than as a dead endpoint that had
    already **deleted three tests' worth of coverage**.

    So the message now separates the two states that `_openapi_paths()`
    deliberately distinguishes, because they have different remedies:

    * **unreachable** — nothing answered; the service is probably not running.
    * **reachable-but-not-serving** — something is bound and returning a bad
      status. This is the dangerous one, and it is the O-111 incident.

    The reason is also surfaced in the probe's own words by calling
    ``tools/openbb_reachability`` when it is importable, so an operator sees
    *"reachable but answered HTTP 502"* rather than a generic phrase.
    """
    paths = _openapi_paths()
    if paths is None:
        pytest.skip(
            f"OpenBB service not serving ({context}); coverage not checked. "
            "NOTE: this skip deletes assertions without failing anything (O-62) "
            "— run `uv run python tools/openbb_reachability.py` to see whether "
            "the configured URL is unreachable or bound-but-not-serving (O-111)."
        )
    return paths


def _endpoint_as_path(endpoint: str) -> str:
    """``fixedincome.government.yield_curve`` -> ``/api/v1/fixedincome/...``.

    The registry names endpoints in the dotted form the Python package uses; the
    REST surface spells the same route with slashes. Deriving one from the other
    here keeps the registry readable while still checking the live surface.
    """
    return "/api/v1/" + endpoint.replace(".", "/")


def test_registry_endpoints_are_well_formed() -> None:
    """Every declared endpoint is a dotted namespace path (offline)."""
    registry = get_registry()
    declared = {entry.endpoint for entry in registry.series.values() if entry.endpoint is not None}
    assert declared, "the registry declares no endpoints at all"
    for endpoint in sorted(declared):
        assert "." in endpoint, f"endpoint {endpoint!r} is not a dotted path"
        assert not endpoint.startswith("."), f"endpoint {endpoint!r} starts with '.'"
        assert not endpoint.endswith("."), f"endpoint {endpoint!r} ends with '.'"


def test_tenor_labels_agree_with_declared_tenors() -> None:
    """`tenor_labels` and `tenors` must describe the SAME set of tenors.

    Two failure modes, both silent before this test:

    * a tenor with no label cannot be read from a single-call response, and the
      fetcher would later blame the provider for the registry's own omission;
    * a label for an undeclared tenor is a typo that no code path ever reads.

    Only entries that declare `tenor_labels` are checked, since the per-symbol
    shape has no labels by design.
    """
    registry = get_registry()
    checked = 0
    for name, entry in registry.series.items():
        if not entry.tenor_labels:
            continue
        checked += 1
        assert entry.tenors, f"{name} declares tenor_labels but no tenors"
        assert set(entry.tenor_labels) == set(entry.tenors), (
            f"{name}: tenor_labels {sorted(entry.tenor_labels)} and tenors "
            f"{sorted(entry.tenors)} are not the same set"
        )
    assert checked > 0, (
        "no registry entry declares tenor_labels; the single-call curve guard "
        "in this file is therefore vacuous"
    )


def test_single_call_entries_declare_their_source_units() -> None:
    """A single-call curve entry is where the scale trap actually bites.

    Measured 2026-09-21: the one route D-086 moved returns its rate as a
    DECIMAL where the FRED route returned percent. An entry that opts into a
    dedicated command without declaring `source_units` is exactly the case that
    would publish a 100x error, so the declaration is required for any entry
    using the single-call shape.
    """
    registry = get_registry()
    for name, entry in registry.series.items():
        if not entry.tenor_labels:
            continue
        assert entry.source_units is not None, (
            f"{name} uses the single-call curve shape but declares no "
            "source_units. The dedicated curve command returns decimals; without "
            "the declaration its values are published 100x too small."
        )


def test_live_service_exposes_every_registry_endpoint() -> None:
    """Every registry endpoint exists on the live service (skips if unreachable)."""
    paths = _require_service("registry endpoint coverage")

    registry = get_registry()
    declared = {entry.endpoint for entry in registry.series.values() if entry.endpoint is not None}
    missing = sorted(e for e in declared if _endpoint_as_path(e) not in paths)
    assert not missing, (
        f"registry names endpoint(s) the live service does not expose: {missing}. "
        f"The service has {len(paths)} paths. Either the endpoint was renamed "
        "upstream or the registry entry is a typo."
    )


def test_live_service_serves_the_curve_command_as_one_call() -> None:
    """The curve command returns all eleven tenors in ONE response (live).

    This is the D-086 claim in its testable form: if the command ever degrades
    to one tenor per call, the 11-calls-to-1 saving is gone and the registry's
    `tenor_labels` join would silently read only whichever label it found.
    """
    paths = _require_service("curve shape")
    assert paths  # narrowing for the type checker; _require_service never returns empty

    base = get_settings().openbb.base_url.rstrip("/")
    try:
        resp = httpx.get(
            f"{base}/api/v1/fixedincome/government/yield_curve",
            params={"provider": "federal_reserve"},
            timeout=15.0,
        )
    except httpx.HTTPError:
        pytest.skip("curve command unreachable; shape not checked")
    if resp.status_code != 200:
        pytest.skip(f"curve command returned {resp.status_code}; shape not checked")

    payload: Any = resp.json()
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or not results:
        pytest.skip("curve command returned no rows; shape not checked")

    labels = {str(r.get("maturity")) for r in results if isinstance(r, dict)}
    entry = get_registry().series["treasury_curve"]
    # The provider's labels, not the registry's tenor keys: `tenor_labels` maps
    # the registry's `1mo`/`10yr` ONTO the provider's `month_1`/`year_10`, so the
    # join is checked in the provider's vocabulary.
    expected = set((entry.tenor_labels or {}).values())
    missing = sorted(expected - labels)
    assert not missing, (
        f"the live curve response is missing label(s) {missing} that the registry "
        f"maps to; got {sorted(labels)}. The join would drop those tenors."
    )
    # The scale claim, re-measured: a decimal-scaled response puts every rate
    # below 1.0. A response that had switched to percent would be caught here
    # rather than by a model receiving a plausible-but-100x-wrong curve.
    rates = [float(r["rate"]) for r in results if isinstance(r, dict) and r.get("rate") is not None]
    assert rates, "the curve response carries no `rate` field"
    assert max(rates) < 1.0, (
        f"the curve command now returns rates up to {max(rates)} — it appears to "
        "have switched from decimal to percent, so `source_units: decimal` is now "
        "WRONG and every value would be published 100x too large."
    )


def test_openapi_is_parseable_when_reachable() -> None:
    """The service's own spec is valid JSON we can actually read (live).

    Cheap, and it distinguishes 'the service is down' from 'the service is up but
    its spec changed shape' — two conditions with the same downstream symptom and
    different remedies.
    """
    paths = _require_service("openapi spec")
    assert len(paths) > 100, (
        f"the live OpenAPI spec exposes only {len(paths)} paths, which is far "
        "below the ~278 the audit measured; the spec may have been truncated."
    )
