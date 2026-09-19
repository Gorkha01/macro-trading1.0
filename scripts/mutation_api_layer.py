"""Mutation sweep for the API layer (D-070).

**Run this in the FOREGROUND ONLY.** The sweep rewrites files under
``src/macro_engine/api_layer/`` in place, so any concurrent test run, live check
or probe reads a mutated module. The blast radius is the repository.

What this increment is really testing
-------------------------------------
Section 8's sample is a *shape*, not code: ``fetch_full_snapshot`` does not
exist, ``build_us_macro_thesis(snapshot)`` raises ``TypeError: missing 6 required
arguments``, and §8.3's reasoning trace is four hardcoded strings. So the defects
in an increment built from it are **not arithmetic defects** — they are:

1. **A fabricated number presented as measured.** ``"gap = -140bp"`` is exactly
   as fluent as the real thing, and no type checker or schema can tell them
   apart, because a string is a valid string. This is the defect class the
   ``compute_gap`` mutants attack.
2. **A failure dressed as a finding.** Section 16.3's line: a stand-down says
   "the models agree there is no edge", not "we could not read the inputs".
   Mutating the status mapping produces a 200/``WATCH`` on a broken feed, which
   is the single most dangerous outcome this file can have.
3. **A default where a refusal is required.** ``M1.2``/``M1.3`` make the
   orchestration substitute a value for a missing series. The substitution is
   *legal* — it produces a schema-valid thesis — which is why only a sweep can
   find it.
4. **A disclosure that is computed but not published.** The provenance is the
   whole reason ``get_snapshot`` returns a pair rather than a snapshot; mutating
   it produces a service that is right and silent.

What IS killable, and by which test
-----------------------------------
Every mutant below names the test that should kill it. In summary:

=================================================================  =======================
mutant                                                             killed by
=================================================================  =======================
``M1.*`` the orchestration refuses rather than defaults             ``test_orchestration``
``M2.*`` the YoY anniversary tolerance is enforced                  ``test_orchestration``
``M3.*`` the three unit conversions are the ones measured           ``test_orchestration``
``M4.*`` the stand-down gates / derived-not-inferred boundary       ``test_orchestration``
``M5.*`` the status-code contract (501/502/422/200)                 ``test_routes``
``M6.*`` the dashboard publishes measurements, not claims           ``test_routes``
``M7.*`` the query endpoint is keyword routing and says so          ``test_routes``
``M8.*`` the stream emits what the models measured                  ``test_routes``
``M9.*`` the provenance discloses age and partiality                ``test_routes``
``M10.*`` the honesty control and the static guards                 ``test_strictness``
=================================================================  =======================

What this sweep structurally CANNOT find
----------------------------------------
1. **Whether the derivation is economically RIGHT.** ``M3.4`` proves the claims
   sign convention is not inverted *here*; whether the score's own multiplier
   inverts it correctly is ``mutation_labor_check``'s / the labor model's
   problem. A sweep of this file can only prove that the number handed to the
   model is the number the snapshot implies.
2. **Whether a live provider returns what the persisted snapshot returns.** The
   tests seed the cache from ``data/raw``; the provider path is exercised by
   ``scripts/live_api_check.py`` (Section 21.0's split: unit tests prove the
   function, the live check proves the wiring).
3. **Whether a wrong thesis is a *good* thesis.** Every gate here is about
   honesty — did we refuse, did we disclose, did we publish a measurement rather
   than a claim. None of them can say whether ``WATCH`` was the right verdict
   for the economy on the day.
4. **The §8.4 CORS/loopback pair, end to end.** ``M9.5`` mutates the config
   validator; whether a *deployment* actually binds loopback is
   ``uvicorn``'s process, not this repository's.
5. **Whether the REST handlers agree with the stream.** They share
   ``snapshot_to_thesis_inputs`` and the builder but compute their responses
   independently; a divergence between ``/thesis`` and ``/thesis/.../stream``
   would need a cross-endpoint test, which is what
   ``test_the_stream_agrees_with_the_rest_endpoint`` asserts — and no single
   mutant kills it.

The honesty control
-------------------
``M10.1`` is semantically identical to the shipped code and **must survive**. If
the sweep reports it killed, the sweep is reporting kills it cannot justify and
no other number it prints means anything.

Anchors
-------
Every anchor is verified against the SHIPPED source by ``check_targets`` before a
single mutation is applied — present **exactly once** — and by
``check_anchor_landings``, which proves it lands in a symbol this increment owns.

``refuse_on_noop`` is set for every mutation (D-064's lesson 93): a mutation
whose ``old`` text is absent is reported NOT APPLIED and refuses to certify,
because in the D-064 sweep two unapplied mutations silently left the denominator
and the run certified ``25/27``.
"""

from __future__ import annotations

import argparse
import ast
import re
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

ORCH = REPO / "src/macro_engine/api_layer/orchestration.py"
PROVIDER = REPO / "src/macro_engine/api_layer/snapshot_provider.py"
THESIS = REPO / "src/macro_engine/api_layer/routes_thesis.py"
DASH = REPO / "src/macro_engine/api_layer/routes_dashboard.py"
QUERY = REPO / "src/macro_engine/api_layer/routes_query.py"
STREAM = REPO / "src/macro_engine/api_layer/reasoning_stream.py"
HEALTH = REPO / "src/macro_engine/api_layer/routes_health.py"
CONFIG = REPO / "src/macro_engine/config.py"

#: The test selection a surviving mutation must be *capable* of killing.
#: ``test_orchestration.py`` carries the derivation assertions;
#: ``test_routes.py`` the endpoint contract and the stream's real values;
#: ``test_strictness.py`` the **static** guards (lesson 5bf) that no behavioural
#: assertion can make — the config-driven boundary and the absence of literals.
#: All three are named because a kill that could have come from any of them must
#: be attributable to one of them (lesson 5be).
PYTEST_TARGETS = [
    "tests/api_layer/test_orchestration.py",
    "tests/api_layer/test_routes.py",
    "tests/api_layer/test_snapshot_provider.py",
    "tests/api_layer/test_strictness.py",
]


@dataclass(frozen=True)
class Mutation:
    """One single-substring rewrite of one file."""

    group: str
    name: str
    path: Path
    old: str
    new: str
    intent: str
    expect_killed: bool | None = None
    inert_proof: str = ""


@dataclass
class Result:
    """The outcome of applying and testing one mutation."""

    mutation: Mutation
    applied: bool
    exit_code: int
    output: str = field(default="")

    @property
    def killed(self) -> bool:
        """True only for a genuine test failure.

        Exit 4 is pytest's usage error (a missing path, a plugin crash, no tests
        collected). Counting it as a kill is how D-051's first draft reported
        56/56 against a control that could not fail.
        """
        return self.exit_code not in (0, 4)


# ---------------------------------------------------------------------------
# Anchors — read out of the shipped source, never transcribed from memory
# ---------------------------------------------------------------------------


def enclosing_symbol(text: str, index: int) -> str:
    """The top-level symbol a character offset falls inside, or ``"<module>"``.

    **Deliberately duplicated from ``tools/sweep_health.py``, not imported** —
    ``mypy --strict`` refuses the import (``tools/`` has no ``__init__.py`` and
    the gate names both ``src tests scripts tools``, so one file becomes two
    modules). The owner is resolved by **parsing**, not by a backwards line walk,
    because a line-walk matches ``def ...`` inside a comment (D-064).
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return "<module>"
    offset_line = text[:index].count("\n") + 1
    enclosing: list[tuple[int, str]] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if node.lineno > offset_line:
            continue
        if node.end_lineno is not None and node.end_lineno < offset_line:
            continue
        enclosing.append((node.lineno, node.name))
    if not enclosing:
        return "<module>"
    return max(enclosing)[1]


#: The top-level symbols this increment owns in each file. An anchor landing
#: outside these means a neighbour is about to be rewritten (O-67).
_ALLOWED_ANCHOR_OWNERS: dict[str, frozenset[str]] = {
    "orchestration.py": frozenset(
        {
            "_require",
            "_realised",
            "_value_on_or_before",
            "_mom_percent",
            "_yoy_percent",
            "_yoy_tolerance_days",
            "_trailing_percentile",
            "_claims_4wk_change",
            "_policy_rate",
            "_short_yield_from_curve",
            "_labor_leg",
            "_output_gap_change",
            "_percentile_window_months",
            "_r_star_from_config",
            "snapshot_to_thesis_inputs",
            "OrchestrationError",
            "DerivationNote",
            "ThesisInputs",
            "<module>",
        }
    ),
    "snapshot_provider.py": frozenset(
        {
            "SnapshotProvenance",
            "SnapshotUnavailableError",
            "_provenance_from_report",
            "_age_hours",
            "get_snapshot",
            "reset_cache",
            "cached_snapshot_provenance",
            "_build",
            "_CacheEntry",
            "<module>",
        }
    ),
    "routes_thesis.py": frozenset({"ThesisResponse", "_http_status_for", "get_thesis", "<module>"}),
    "routes_dashboard.py": frozenset(
        {"SeriesPanel", "CurvePanel", "DashboardData", "_panel", "dashboard_data", "<module>"}
    ),
    "routes_query.py": frozenset(
        {
            "QueryRequest",
            "QueryResponse",
            "_tokenise",
            "_match_topics",
            "_project",
            "query",
            "<module>",
        }
    ),
    "reasoning_stream.py": frozenset(
        {"_event", "_fired", "reasoning_step_generator", "stream_thesis_reasoning", "<module>"}
    ),
    "routes_health.py": frozenset({"HealthResponse", "health", "<module>"}),
    "config.py": frozenset({"ApiSettings", "<module>"}),
}


# === M1: the orchestration REFUSES rather than defaults =======================
#: ``_require`` is the single gate in front of every series read. Deleting the
#: raise turns an empty series into an ``IndexError`` three frames down (loud) or
#: — worse, in the hands of a caller that catches broadly — a thesis.
_REQUIRE_RAISE = """    if not points:
        raise OrchestrationError("""

#: ``_policy_rate``'s final refusal. Mutating the fallback in means ``i_prev``
#: is an invented number in the first-difference rule's inertia term.
_POLICY_FALLBACK = """            )
    raise OrchestrationError(
        "none of iorb, fed_funds_rate or sofr carries a realised observation, so \""""

#: ``_short_yield_from_curve``'s magnitude check — the only thing standing
#: between a basis-point value and a market-implied policy path of 430%.
_YIELD_RANGE = "    if not 0.0 < value < 25.0:"

#: ``_claims_4wk_change``'s minimum. Eight is not a style choice: four recent
#: plus four prior, with no overlap.
_CLAIMS_MINIMUM = "    if len(points) < 8:"

#: ``_output_gap_change``'s "no earlier pair" branch. Removing it lets a
#: ``None`` reach the subtraction, which is a ``TypeError`` at best and — with
#: the ``or 0.0`` idiom this project has used elsewhere — a fabricated zero
#: momentum at worst.
_GAP_CHANGE_BRANCH = """    if len(common_dates) < 2:
        return 0.0, ("""


# === M2: the YoY anniversary tolerance =======================================
#: The guard itself. Without it a ratio against an off-anniversary point is
#: published under the words "year-over-year".
_YOY_TOLERANCE_GUARD = """    tolerance = _yoy_tolerance_days()
    offset = abs((target - prior.observation_date).days)
    if offset > tolerance:
        raise OrchestrationError("""

#: The tolerance is read from CONFIG, not typed as a literal. A hardcoded 5 here
#: would make ``api.yoy_match_tolerance_days`` an inert input (D-037's class) —
#: a knob that reads as connected and is not.
_TOLERANCE_READ = "    return get_settings().api.yoy_match_tolerance_days"


# === M3: the three measured unit conversions =================================
#: JTSJOL is in THOUSANDS; the model wants a YoY percent. The YoY ratio is the
#: conversion — ``_yoy_percent`` itself. Mutating its divisor to the LATEST
#: observation inverts the ratio, which is the sign-and-scale error this
#: increment measured first.
#: The anchor carries the ``described`` string as well as the arithmetic: the
#: same expression appears in ``_mom_percent``, so the bare line is AMBIGUOUS and
#: ``str.replace`` would rewrite whichever came first (D-048). The two functions
#: differ precisely in the description they attach, which is why the anchor spans
#: both — and the mutant then also proves the *label* is part of the arithmetic's
#: contract, not decoration.
_YOY_DIVISOR = (
    "    change = (latest.value / prior.value - 1.0) * 100.0\n"
    "    described = (\n"
    '        f"{change:+.4f}% ({latest.observation_date.isoformat()} "\n'
    '        f"{latest.value:g} vs {prior.observation_date.isoformat()} {prior.value:g}; "\n'
    '        f"{offset} day(s) off the anniversary)"\n'
    "    )"
)

#: ``_mom_percent``'s divisor. Backwards here changes the sign of an
#: *accelerating* series — the only case the breadth score's sign test cares
#: about — while leaving a decelerating one looking identical.
#: Same ambiguity, resolved the other way: this anchor carries ``_mom_percent``'s
#: description, which names no anniversary — so the two mutants cannot collide.
_MOM_DIVISOR = (
    "    change = (latest.value / prior.value - 1.0) * 100.0\n"
    "    described = (\n"
    '        f"{change:+.4f}% ({latest.observation_date.isoformat()} "\n'
    '        f"{latest.value:g} vs {prior.observation_date.isoformat()} {prior.value:g})"\n'
    "    )"
)

#: The claims sign convention. ``LaborInputs`` documents POSITIVE = loosening and
#: §6.4's multiplier performs the inversion; a leading minus here cancels it and
#: reports a tightening labor market on a claims surge.
_CLAIMS_SIGN = "    change = (recent_avg / prior_avg - 1.0) * 100.0"

#: ``_trailing_percentile``'s window. A 30-day-month approximation drifts a week
#: over three years — enough to move a boundary observation, which is the entire
#: content of a percentile.
_PERCENTILE_MONTHS = "    return int(get_settings().labor.quits_percentile_window_months.value)"

#: The percentile definition. ``<`` instead of ``<=`` under-counts the latest
#: value's own position and makes a series at its historical high read 98.3
#: rather than 100.
_PERCENTILE_COMPARISON = "    at_or_below = sum(1 for p in window if p.value <= latest.value)"


# === M4: the derived-not-inferred boundary ===================================
#: ``thesis_type`` is an ANALYTICAL choice. Inferring it from the data is the
#: "manufacturing a claim" failure the builder's divergence 1 warns about, one
#: layer up.
_TYPE_INFERENCE = "    resolved_type = thesis_type or ThesisType(settings.api.default_thesis_type)"

#: The curve legs are forwarded, not defaulted in. A curve tenor pair on an
#: outright thesis is a parameter nothing reads (D-037's inert-input class).
_CURVE_LEG_WARNING = """    elif curve_short_tenor is not None or curve_long_tenor is not None:"""

#: ``country`` is a label, not a capability (Section 22.3). Removing this check
#: lets a ``de`` snapshot be read by a US reaction function.
_COUNTRY_CHECK = '    if snapshot.country != "us":'

#: ``pi_target=None`` hands the model its own config target. Passing a literal
#: here would be a second, silent definition of the inflation target.
_PI_TARGET = "        pi_target=None,  # the model's own config target, not a second literal"


# === M5: the status-code contract ============================================
#: 501 for an unimplemented country. Mapping it onto 502 would tell a caller the
#: data source failed when the capability is what is missing.
_STATUS_501 = """    if isinstance(exc, NotImplementedError):
        return HTTPException(
            status_code=501,"""

#: 502 for an unusable snapshot field. Changing this to 422 blames the request.
_STATUS_502 = """    if isinstance(exc, OrchestrationError):
        return HTTPException(
            status_code=502,"""

#: The builder's own failures are a 500, deliberately. Mapping them onto 502
#: would hide a defect in this service behind "the provider failed".
_BUILDER_STATUS = "            status_code=500,"

#: The 422 for an unknown ``thesis_type``. A silent fallback to the default would
#: build the wrong family and answer a question nobody asked.
_THESIS_TYPE_422 = "                status_code=422,"

#: The stream validates the country BEFORE opening. Removing the pre-check
#: returns a 200 whose body carries one error frame — by then a client is
#: already parsing events and the status code was the last chance to say so.
_STREAM_PRECHECK = '    if country != "us":'


# === M6: the dashboard publishes measurements, not claims ====================
#: Most-recent, not oldest. A truncated chart showing the oldest twelve points
#: is a chart of four years ago.
_DASHBOARD_KEEP = "    kept = points[-limit:] if available > limit else list(points)"

#: The withheld count is what makes truncation visible.
_DASHBOARD_WITHHELD = "        points_withheld=available - len(kept),"

#: An empty family is omitted rather than returned as ``{"growth": []}``.
_DASHBOARD_EMPTY = "        if any(panel.points_available for panel in panels):"

#: The curve is published in PERCENT and labelled so.
_CURVE_UNITS = '    units: str = "percent"'


# === M7: the query endpoint is keyword routing and says so ===================
#: The machine-readable admission. A field rather than a footnote, so a client
#: cannot miss it in prose.
_KEYWORD_FLAG = "    is_keyword_routing: bool = Field(\n        default=True,"

#: Whole-token matching. Substring matching routes "recession" (which contains
#: "session") to the regime model.
_TOKENISE = '    cleaned = "".join(c if c.isalnum() else " " for c in question.lower())'

#: An unmatched question returns NO thesis rather than attaching one. The guard
#: is the whole protection: without it the empty match falls through into the
#: projection code and returns a populated payload beside `matched_topics=[]`.
_NO_MATCH_GUARD = "    if not matched:"

#: Deduplication. Two topics can name ``trade_idea`` and a client that rendered
#: the duplicates would show the same value twice.
_QUERY_DEDUPE = """    seen: set[str] = set()
    unique_fields: list[str] = []"""


# === M8: the stream emits what the models measured ==========================
#: The gap frame. Replacing the computed value with the spec's literal is the
#: defect this module exists to prevent — and it is the one mutation in this
#: sweep whose behaviour is *identical on every run*, which is why the test
#: cross-checks against a separately built thesis rather than a fixed string.
_STREAM_GAP = """    yield _event(
        "compute_gap",
        "done",
        f"Model-implied {market_path.value!r} vs market-implied policy path: "
        f"gap = {gap.raw_gap:+.4f}pp ({gap.raw_gap * 100:+.1f}bp), "
        f"dispersion {gap.dispersion:.4f}pp, meaningful={gap.is_meaningful}",
    )"""

#: The rule values. §8.3 says "9 models completed" — a count that cannot be
#: wrong because it is not measured.
_STREAM_RULES = """        f"{len(rules)} policy rule(s) evaluated: "
        + ", ".join(f"{name}={value}" for name, value in rule_values.items()),"""

#: The convergence label, read off the published thesis.
#: The frame appears TWICE (once on the stand-down path, once on the live
#: path) with the identical detail string, so the anchor carries the enclosing
#: ``_event`` call AND the step name to stay unique — and the mutant then
#: rewrites BOTH branches, which is the right blast radius: a fixed convergence
#: label is wrong whichever branch emits it.
#: The convergence label, read off the published thesis. The frame appears TWICE
#: with an identical detail string, so the anchor carries the enclosing branch —
#: the stand-down path, distinguished by the ``build_thesis`` frame that follows
#: it. Both would be wrong to hardcode, but the STAND-DOWN one is the case §8.3's
#: sample gets most wrong: it asserts "HIGH convergence" on the day the analysis
#: found the signals conflicted.
_STREAM_CONVERGENCE = """        yield _event(
            "classify_convergence",
            "done",
            f"convergence={thesis.convergence_classification.value}",
        )
        yield _event(
            "build_thesis",
            "done",
            f"Thesis stood down by {', '.join(fired)}: status={thesis.status.value}, \""""

#: Every path ends with the terminator.
_STREAM_DONE = '    yield "data: [DONE]\\n\\n"\n\n\n@router.get("/{country}/stream")'

#: A stand-down is a COMPLETED analysis. Emitting an error frame for it would
#: make a real failure indistinguishable from a no-trade verdict (Section 16.3).
_STAND_DOWN_STATUS = """        yield _event(
            "build_thesis",
            "done",
            f"Thesis stood down by {', '.join(fired)}: status={thesis.status.value}, \""""


# === M9: the provenance discloses age and partiality ========================
#: Stale-served-as-fresh. Without the re-stamp a cached entry reports the age it
#: had when it was written, for ever.
_PROVENANCE_RESTAMP = """                    "age_hours": _age_hours(cached.snapshot.as_of, now),"""

#: A negative age passes every ``age > max_age`` check. The floor is what stops a
#: clock skew from disabling the staleness disclosure.
_AGE_FLOOR = "    return max(0.0, seconds / 3600.0)"

#: A build that fetched nothing is unavailable, not empty.
_EMPTY_BUILD_GUARD = "    if requested and not succeeded:"

#: The CORS/loopback pair. Section 8.4's permissive policy is safe *because* the
#: bind is loopback; unpaired, it is an open relay to a service with no auth.
_CORS_VALIDATOR = '        if self.host not in {"127.0.0.1", "localhost", "::1"}:'

#: ``loopback_only`` is published rather than inferred from the host string.
_LOOPBACK_PROPERTY = '        return self.host in {"127.0.0.1", "localhost", "::1"}'


# === M10: the honesty control and the static guards =========================
#: ``str(...)`` around an already-``str`` value: the identity, spelled
#: differently. Semantically identical, so it must survive.
_CONTROL_INTENT = "CONTROL — the country check is re-spelled as a comparison against a set."

#: ``routes_health``'s cheap path must not build. Mutating it to build would make
#: the supervisor's poll cost 223.6s against the provider it is diagnosing.
_HEALTH_CHEAP = "    if not deep:"

#: ``SERVICE_VERSION`` is read by both ``/health`` and the app factory. A version
#: that disagrees between them is a version nobody trusts.
_VERSION_CONSTANT = 'SERVICE_VERSION = "1.0.0"'


def build_mutations() -> list[Mutation]:
    """The catalogue. Order is group-major so a partial run is interpretable."""
    return [
        # =====================================================================
        # M1 — the orchestration REFUSES rather than defaults
        # =====================================================================
        Mutation(
            group="M1",
            name="M1.1 _require stops refusing an empty series",
            path=ORCH,
            old=_REQUIRE_RAISE,
            new="""    if not points:
        return  # MUTANT: an empty series is silently tolerated""",
            intent=(
                "Restores the default-instead-of-refuse behaviour: an empty series "
                "flows on and the failure surfaces as an IndexError three frames "
                "down, or — for a caller catching broadly — as a thesis computed "
                "from whatever the next line produced. Killed by the refusal "
                "matrix in test_orchestration.py, which parametrises every series "
                "and asserts OrchestrationError NAMING the field."
            ),
        ),
        Mutation(
            group="M1",
            name="M1.2 _policy_rate invents a rate when all three are empty",
            path=ORCH,
            old=_POLICY_FALLBACK,
            new="""            )
    return 4.0, "MUTANT: assumed 4.0\"""",
            intent=(
                "Puts an invented number into i_prev and hence into the "
                "first-difference rule's inertia term. The thesis is schema-valid "
                "and the number is plausible, which is why only a refusal test "
                "catches it. Killed by "
                "test_policy_rate_refuses_when_every_rate_is_empty."
            ),
        ),
        Mutation(
            group="M1",
            name="M1.3 the short yield accepts a basis-point value",
            path=ORCH,
            old=_YIELD_RANGE,
            new="    if False:  # MUTANT: the units check is removed",
            intent=(
                "A 430-bp curve entry read as a percent inflates the "
                "market-implied path by 100x and produces a gap of thousands of "
                "bp — loud in the response, but only after it has been computed "
                "and published. Killed by test_a_basis_point_curve_is_refused."
            ),
        ),
        Mutation(
            group="M1",
            name="M1.4 the claims window shrinks below two non-overlapping averages",
            path=ORCH,
            old=_CLAIMS_MINIMUM,
            new="    if len(points) < 4:  # MUTANT: overlapping windows",
            intent=(
                "Four points makes recent and prior windows share observations, "
                "which compresses the change toward zero and reports a claims "
                "surge as a mild rise. Killed by "
                "test_the_claims_conversion_needs_eight_weeks."
            ),
        ),
        Mutation(
            group="M1",
            name="M1.5 the output-gap change loses its no-earlier-pair branch",
            path=ORCH,
            old=_GAP_CHANGE_BRANCH,
            new="""    if False:  # MUTANT: no earlier pair is not handled
        return 0.0, (""",
            intent=(
                "An empty earlier set reaches max() on an empty sequence, so a "
                "short snapshot crashes instead of reporting 0.0 with the "
                "'masquerading' note."
            ),
            expect_killed=False,
            inert_proof=(
                "MEASURED, not assumed. Applying this and running the suite leaves "
                "125 passed with no red. The reason is a second, overlapping guard "
                "eight lines below: after the removed branch the code computes "
                "``earlier_dates = [d for d in common_dates if d <= earlier_target]`` "
                "and returns the SAME 0.0 from ``if not earlier_dates:`` with a note "
                "that differs only in naming the earlier_target date. On the "
                "fixture's short history ``earlier_dates`` is empty, so that guard "
                "fires and the required behaviour — 0.0 plus an honest "
                "'masquerading' note, never a level passed off as a change — is "
                "produced either way. Verified by driving the function directly on "
                "a two-point snapshot: the note returned names the date, proving "
                "the second guard ran. The property (never crash on short history, "
                "never publish a level as a change) is therefore doubly enforced, "
                "and no test can distinguish the two because both are correct."
            ),
        ),
        # =====================================================================
        # M2 — the YoY anniversary tolerance (the defect this increment found)
        # =====================================================================
        Mutation(
            group="M2",
            name="M2.1 the YoY anniversary tolerance is not enforced",
            path=ORCH,
            old=_YOY_TOLERANCE_GUARD,
            new="""    offset = abs((target - prior.observation_date).days)
    if False:  # MUTANT: any point at or before the anniversary is 'year-over-year'""",
            intent=(
                "The defect the D-070 probe found in the first draft: a ratio "
                "against a point 30 days off the anniversary is published under "
                "the words 'year-over-year', and the note prints both dates "
                "beside the label so the number and its description disagree "
                "while nothing says so. Killed by "
                "test_the_yoy_lookup_refuses_a_point_far_off_the_anniversary."
            ),
        ),
        Mutation(
            group="M2",
            name="M2.2 the tolerance is a hardcoded literal, not config",
            path=ORCH,
            old=_TOLERANCE_READ,
            new="    return 5  # MUTANT: the config leaf is inert",
            intent=(
                "Makes api.yoy_match_tolerance_days an inert input (D-037's "
                "class): a knob that reads as connected and is not, so an operator "
                "who widens it to admit a quarterly series sees no change and no "
                "explanation. Killed by the strictness guard plus the "
                "tolerance-both-ways test, which moves the config value."
            ),
        ),
        # =====================================================================
        # M3 — the three measured unit conversions
        # =====================================================================
        Mutation(
            group="M3",
            name="M3.1 the YoY ratio is inverted",
            path=ORCH,
            old=_YOY_DIVISOR,
            new="    change = (prior.value / latest.value - 1.0) * 100.0  # MUTANT: inverted",
            intent=(
                "Inverts every YoY conversion, so a 7% rise in openings reads as a "
                "6.5% FALL and the labor score's JOLTS term takes the opposite "
                "sign. Mathematically legal, plausible in magnitude. Killed by "
                "test_the_openings_conversion_is_a_yoy_ratio."
            ),
        ),
        Mutation(
            group="M3",
            name="M3.2 the m/m divisor is the latest rather than the prior",
            path=ORCH,
            old=_MOM_DIVISOR,
            new="    change = (prior.value / latest.value - 1.0) * 100.0  # MUTANT: inverted",
            intent=(
                "Changes the sign of an ACCELERATING series and leaves a "
                "decelerating one looking identical, which is exactly the case the "
                "breadth score's sign test is about. Killed by "
                "test_the_inflation_leg_uses_mom_changes."
            ),
        ),
        Mutation(
            group="M3",
            name="M3.3 the claims sign is inverted here as well as in the score",
            path=ORCH,
            old=_CLAIMS_SIGN,
            new="    change = -(recent_avg / prior_avg - 1.0) * 100.0  # MUTANT: double inversion",
            intent=(
                "LaborInputs documents POSITIVE = loosening and the score's own "
                "configurable multiplier performs the inversion. Inverting here "
                "cancels it and reports a TIGHTENING labor market on a claims "
                "surge — the module docstring's third trap. Killed by "
                "test_the_claims_change_is_not_pre_inverted."
            ),
        ),
        Mutation(
            group="M3",
            name="M3.4 the percentile window is a hardcoded 36",
            path=ORCH,
            old=_PERCENTILE_MONTHS,
            new="    return 36  # MUTANT: labor.quits_percentile_window_months is inert",
            intent=(
                "Same inert-input class as M2.2, on the window the derivation "
                "explicitly REPORTS ('n monthly observations'). If the reported "
                "window disagrees with the window used, the disclosure is worse "
                "than absent. Killed by the strictness guard."
            ),
        ),
        Mutation(
            group="M3",
            name="M3.5 the percentile excludes the latest value from its own rank",
            path=ORCH,
            old=_PERCENTILE_COMPARISON,
            new="    at_or_below = sum(1 for p in window if p.value < latest.value)  # MUTANT",
            intent=(
                "A series at its historical high reads 98.3 rather than 100, so an "
                "extreme reading looks ordinary — and the bias grows as the window "
                "shortens, which is the case the snapshot actually produces. "
                "Killed by test_the_quits_percentile_at_a_high_is_one_hundred."
            ),
        ),
        # =====================================================================
        # M4 — the derived-not-inferred boundary
        # =====================================================================
        Mutation(
            group="M4",
            name="M4.1 thesis_type is inferred from the data",
            path=ORCH,
            old=_TYPE_INFERENCE,
            new=(
                "    resolved_type = thesis_type or (\n"
                "        ThesisType.CURVE_SHAPE_GAP\n"
                "        if 0.0 < snapshot.yield_curve.tenors.get('10yr', 0.0) < 4.0\n"
                "        else ThesisType(settings.api.default_thesis_type)\n"
                "    )  # MUTANT: an analytical choice inferred from a market level"
            ),
            intent=(
                "The builder's divergence 1, one layer up: thesis_type is 'an "
                "analytical choice among seven families, and a gap says nothing "
                "about which one the thesis is'. A builder that guessed it from a "
                "yield level would be manufacturing a claim. Killed by "
                "test_the_thesis_type_is_not_inferred_from_the_data."
            ),
        ),
        Mutation(
            group="M4",
            name="M4.2 ignored curve legs are dropped silently",
            path=ORCH,
            old=_CURVE_LEG_WARNING,
            new="    elif False:  # MUTANT: the inert-input warning is removed",
            intent=(
                "A caller who supplies curve legs on an outright thesis gets no "
                "warning, so a parameter they set expecting it to matter is "
                "silently inert (D-037). Killed by "
                "test_ignored_curve_legs_are_reported."
            ),
        ),
        Mutation(
            group="M4",
            name="M4.3 a foreign snapshot is accepted",
            path=ORCH,
            old=_COUNTRY_CHECK,
            new='    if snapshot.country != "us" and False:  # MUTANT: label implies capability',
            intent=(
                "Section 22.3 / Finding #3: country is a LABEL, not a "
                "generalisation. Reading a 'de' snapshot with the Fed's reaction "
                "function produces a fluent, wrong thesis — and the ECB's "
                "20-country compromise is not the Taylor rule with a different "
                "label."
            ),
            expect_killed=False,
            inert_proof=(
                "MEASURED, not assumed. Applying this and running the suite leaves "
                "125 passed with no red, because a second independent guard one "
                "layer down raises first. Traced by driving the function on a real "
                "US snapshot relabelled 'de': the NotImplementedError comes from "
                "``gdp_nowcast.py:442`` inside ``output_gap_from_snapshot`` — "
                'reached at ``orchestration.py:867`` — with the message "output_gap '
                "is implemented for country 'us' only; got 'de'\". So the "
                "orchestration's guard is the EARLY copy of a check the growth "
                "model already enforces for its own series set; removing it still "
                "refuses, one call later, in the same class. The two are genuinely "
                "independent (different modules, different series sets, different "
                "messages) and either suffices — which is why no assertion on the "
                "behaviour can separate them. Kept rather than deleted because the "
                "orchestration's copy is the one that fails BEFORE a snapshot's "
                "other field conversions run, and its message names the "
                "API-layer contract rather than one model's."
            ),
        ),
        Mutation(
            group="M4",
            name="M4.4 pi_target is a second literal rather than the model's config",
            path=ORCH,
            old=_PI_TARGET,
            new="        pi_target=2.0,  # MUTANT: a second definition of the target",
            intent=(
                "The model resolves pi_target from config and reports its "
                "inputs_used. A literal here creates a second definition of the "
                "inflation target that the model's own disclosure would not show. "
                "Killed by test_pi_target_is_left_to_the_model."
            ),
        ),
        # =====================================================================
        # M5 — the status-code contract
        # =====================================================================
        Mutation(
            group="M5",
            name="M5.1 an unimplemented country becomes a 502",
            path=THESIS,
            old=_STATUS_501,
            new="""    if isinstance(exc, NotImplementedError):
        return HTTPException(
            status_code=502,""",
            intent=(
                "Tells a caller the DATA SOURCE failed when the capability is what "
                "is missing, so the remedy they reach for is a provider retry. "
                "Killed by test_an_unimplemented_country_is_a_501."
            ),
        ),
        Mutation(
            group="M5",
            name="M5.2 an unusable field maps to 422 instead of 502",
            path=THESIS,
            old=_STATUS_502,
            new="""    if isinstance(exc, OrchestrationError):
        return HTTPException(
            status_code=422,""",
            intent=(
                "Blames the caller's request for a data condition, so a client "
                "fixes its query and gets the same failure. Killed by "
                "test_a_failed_orchestration_is_a_502_and_never_a_thesis."
            ),
        ),
        Mutation(
            group="M5",
            name="M5.3 a builder failure is dressed as a provider failure",
            path=THESIS,
            old=_BUILDER_STATUS,
            new="            status_code=502,  # MUTANT: a bug hidden behind a dependency",
            intent=(
                "The two 502 classes exist precisely so a 500 means what it says. "
                "Mapping the builder's own exception onto 502 makes every defect "
                "in this service look like the provider's fault, and the "
                "'reserved for real bugs' contract stops carrying information. "
                "Killed by the strictness guard on the status table."
            ),
        ),
        Mutation(
            group="M5",
            name="M5.4 an unknown thesis_type falls back to the default",
            path=THESIS,
            old=_THESIS_TYPE_422,
            new="                status_code=200,  # MUTANT: silently answers a different question",
            intent=(
                "A caller who typed 'policy_gap' instead of 'policy_path_gap' gets "
                "a fluent thesis for a family they did not choose, with "
                "thesis_type_source saying 'assumed from api.default_thesis_type' — "
                "true, and not what they asked. Killed by "
                "test_an_unknown_thesis_type_is_a_422."
            ),
        ),
        Mutation(
            group="M5",
            name="M5.5 the stream opens before validating the country",
            path=STREAM,
            old=_STREAM_PRECHECK,
            new='    if country != "us" and False:  # MUTANT: validated after the stream opens',
            intent=(
                "Returns a 200 whose body carries one error frame. A client that "
                "has opened a stream is already parsing events and cannot be told "
                "'you asked for the wrong thing' — the status code was the last "
                "chance to say so. Killed by "
                "test_stream_refuses_an_unimplemented_country_before_opening."
            ),
        ),
        # =====================================================================
        # M6 — the dashboard publishes measurements, not claims
        # =====================================================================
        Mutation(
            group="M6",
            name="M6.1 the dashboard keeps the OLDEST points",
            path=DASH,
            old=_DASHBOARD_KEEP,
            new="    kept = points[:limit] if available > limit else list(points)  # MUTANT",
            intent=(
                "A truncated chart that shows the oldest twelve points is a chart "
                "of four years ago, rendered beside a 'latest_value' field showing "
                "today — so the chart and the headline disagree and the chart is "
                "the part a human reads. Killed by "
                "test_dashboard_keeps_the_most_recent_points."
            ),
        ),
        Mutation(
            group="M6",
            name="M6.2 the withheld count is not reported",
            path=DASH,
            old=_DASHBOARD_WITHHELD,
            new="        points_withheld=0,  # MUTANT: truncation is invisible",
            intent=(
                "Silently truncates every long series. A reader who does not know "
                "the history was cut reads the visible window as the whole series, "
                "and a 12-point window of a weekly series looks like a quarter "
                "rather than five years. Killed by "
                "test_dashboard_caps_each_series_and_reports_what_it_withheld."
            ),
        ),
        Mutation(
            group="M6",
            name="M6.3 an empty family is returned as empty panels",
            path=DASH,
            old=_DASHBOARD_EMPTY,
            new="        if True:  # MUTANT: empty families are emitted as []",
            intent=(
                "A widget that receives {'growth': []} must special-case the empty "
                "list; an absent key is simply 'no panel here'. Emitting the empty "
                "family also makes a provider failure look like a rendering "
                "problem. Killed by "
                "test_dashboard_omits_an_empty_family_rather_than_returning_empty_panels."
            ),
        ),
        Mutation(
            group="M6",
            name="M6.4 the curve panel is unlabelled as to units",
            path=DASH,
            old=_CURVE_UNITS,
            new='    units: str = "bp"  # MUTANT: the curve is labelled in basis points',
            intent=(
                "The published values ARE percent (4.35 means 4.35%); labelling "
                "them bp makes every consumer that trusts the label draw a yield "
                "chart 100x too tall, and a reader comparing it against a "
                "published curve sees a factor-of-100 error with no cause. Killed "
                "by test_dashboard_reports_the_curve_in_percent."
            ),
        ),
        # =====================================================================
        # M7 — the query endpoint is keyword routing and says so
        # =====================================================================
        Mutation(
            group="M7",
            name="M7.1 the keyword-routing flag defaults to False",
            path=QUERY,
            old=_KEYWORD_FLAG,
            new="    is_keyword_routing: bool = Field(\n        default=False,",
            intent=(
                "The machine-readable admission that no inference happened "
                "becomes a lie, and a client that gates on it would render a "
                "routing description as an answer. No behavioural test can see "
                "it — both construction sites pass the flag explicitly, so the "
                "default is unreachable at runtime; the property is only "
                "observable structurally. Killed by "
                "test_every_query_response_construction_passes_the_routing_flag_"
                "explicitly, which reads the field's default off "
                "QueryResponse.model_fields and asserts it is True (plus that "
                "every site states it)."
            ),
        ),
        Mutation(
            group="M7",
            name="M7.2 the tokeniser matches substrings",
            path=QUERY,
            old=_TOKENISE,
            new=(
                '    cleaned = " ".join(question.lower().split())  # MUTANT: '
                "punctuation kept as part of the token"
            ),
            intent=(
                "Keeps punctuation attached, so 'recession?' does not equal "
                "'recession' and a question with a question mark matches nothing — "
                "the silent no-match. The substring variant is worse still "
                "('recession' contains 'session'), and the whole-token rule is "
                "what the comment beside the table claims. Killed by "
                "test_query_matches_whole_tokens_not_substrings."
            ),
        ),
        Mutation(
            group="M7",
            name="M7.3 an unmatched question falls through to the thesis path",
            path=QUERY,
            old=_NO_MATCH_GUARD,
            new="    if False:  # MUTANT: an unmatched question attaches a thesis",
            intent=(
                "Every no-match path must return NO thesis. Removing the guard "
                "sends an unmatched question into the projection code, where "
                "``matched`` is empty: the response then carries "
                "``matched_topics=[]`` alongside a populated "
                "``relevant_model_outputs`` — an empty match dressed as a partial "
                "success, and a client cannot tell the two apart. Killed by "
                "test_query_with_no_match_returns_no_thesis."
            ),
        ),
        Mutation(
            group="M7",
            name="M7.4 the query stops deduplicating fields",
            path=QUERY,
            old=_QUERY_DEDUPE,
            new="""    seen: set[str] = set()
    unique_fields: list[str] = list(fields)  # MUTANT: no dedupe""",
            intent=(
                "Two topics name trade_idea (curve and risk), so a question "
                "mentioning both renders the same value twice and a client that "
                "keyed on field name would resolve one of them arbitrarily. Killed "
                "by test_query_deduplicates_fields_named_by_two_topics."
            ),
        ),
        # =====================================================================
        # M8 — the stream emits what the models measured
        # =====================================================================
        Mutation(
            group="M8",
            name="M8.1 the compute_gap frame is the spec's hardcoded -140bp",
            path=STREAM,
            old=_STREAM_GAP,
            new="""    yield _event(
        "compute_gap",
        "done",
        "Market-implied policy path gap = -140bp",  # MUTANT: Section 8.3 verbatim
    )""",
            intent=(
                "THE defect this increment exists to remove, restored verbatim. "
                "The stream emits identical text on every run, so a live "
                "'thinking' trace says -140bp on a day the gap is +26bp. No type "
                "checker or schema can catch it, because a string is a valid "
                "string. Killed by test_stream_emits_the_real_gap_not_the_spec_literal, "
                "which cross-checks the frame against a separately built thesis."
            ),
        ),
        Mutation(
            group="M8",
            name="M8.2 the run_models frame reports a count, not the values",
            path=STREAM,
            old=_STREAM_RULES,
            new='        f"{len(rules)} models completed",  # MUTANT: Section 8.3 verbatim',
            intent=(
                "A count that cannot be wrong because it is not measured. The "
                "trace then says '3 models completed' while saying nothing about "
                "what they produced — the whole value of the trace. Killed by "
                "test_stream_emits_the_real_rule_values."
            ),
        ),
        Mutation(
            group="M8",
            name="M8.3 the convergence label is a fixed string",
            path=STREAM,
            old=_STREAM_CONVERGENCE,
            new="""        yield _event(
            "classify_convergence",
            "done",
            "convergence=HIGH",  # MUTANT: Section 8.3 verbatim
        )
        yield _event(
            "build_thesis",
            "done",
            f"Thesis stood down by {', '.join(fired)}: status={thesis.status.value}, \"""",
            intent=(
                "§8.3's 'HIGH convergence' is emitted on a day the builder stood "
                "the sentence down — so the trace asserts convergence in exactly "
                "the case the analysis found none. Killed by "
                "test_stream_emits_the_real_convergence_and_gate, which reads the "
                "label off a separately built thesis."
            ),
        ),
        Mutation(
            group="M8",
            name="M8.4 a stand-down emits an error frame",
            path=STREAM,
            old=_STAND_DOWN_STATUS,
            new="""        yield _event(
            "build_thesis",
            "error",
            f"Thesis stood down by {', '.join(fired)}: status={thesis.status.value}, \"""",
            intent=(
                "Section 16.3: a stand-down is a COMPLETED analysis. Marking it an "
                "error makes a successful 'the models agree there is no edge' "
                "indistinguishable from a real failure — and a real failure "
                "indistinguishable from a no-trade verdict. Killed by "
                "test_stream_never_emits_an_error_status_on_a_stand_down."
            ),
        ),
        Mutation(
            group="M8",
            name="M8.5 the terminal [DONE] is dropped from the normal path",
            path=STREAM,
            old=_STREAM_DONE,
            new='\n\n@router.get("/{country}/stream")',
            intent=(
                "An SSE client needs a terminator to distinguish 'the stream "
                "ended' from 'the connection dropped'. Without it every completed "
                "thesis looks truncated. Killed by test_stream_terminates_with_done."
            ),
        ),
        Mutation(
            group="M8",
            name="M8.6 the fired gate is recomputed rather than read off the thesis",
            path=STREAM,
            old="""    return [
        trigger
        for trigger in _TRIGGERS
        if any(NO_TRADE_TRIGGER_LABELS[trigger] in w for w in thesis_warnings)
    ]""",
            new="""    return list(_TRIGGERS)  # MUTANT: every gate reported as fired""",
            intent=(
                "A second definition of the same fact — the D-067 attribution "
                "defect in the trace position. The trace then names three gates "
                "when one fired, and a reader cannot tell which. Killed by "
                "test_stream_emits_the_real_convergence_and_gate."
            ),
        ),
        # =====================================================================
        # M9 — the provenance discloses age and partiality
        # =====================================================================
        Mutation(
            group="M9",
            name="M9.1 a cached snapshot is served with no age attached",
            path=PROVIDER,
            old=_PROVENANCE_RESTAMP,
            new='                    "age_hours": cached.provenance.age_hours,  # MUTANT',
            intent=(
                "The D-069 lesson in the cache position: a cached answer with no "
                "age attached is a claim about the present made from the past. The "
                "entry reports the age it had when it was WRITTEN, for ever, so a "
                "day-old snapshot reports zero hours — and the payload is "
                "byte-identical either way, so nothing else can catch it. Killed "
                "by test_the_age_is_re_stamped_on_every_serve."
            ),
        ),
        Mutation(
            group="M9",
            name="M9.2 the age floor is removed",
            path=PROVIDER,
            old=_AGE_FLOOR,
            new="    return seconds / 3600.0  # MUTANT: a negative age is possible",
            intent=(
                "A clock skew that puts as_of slightly ahead of now yields a "
                "negative age, and a negative age silently passes any "
                "age > max_age check — the exact comparison the staleness "
                "disclosure is built on. Killed by "
                "test_the_age_is_floored_at_zero."
            ),
        ),
        Mutation(
            group="M9",
            name="M9.3 a build that fetched nothing does not raise",
            path=PROVIDER,
            old=_EMPTY_BUILD_GUARD,
            new="    if False:  # MUTANT: an empty build is served as a snapshot",
            intent=(
                "An empty snapshot flows downstream where every series read "
                "refuses — so the failure is precise but arrives as an "
                "OrchestrationError naming a field, blaming the data when the "
                "PROVIDER returned nothing at all. Killed by "
                "test_a_wholly_failed_build_is_unavailable."
            ),
        ),
        Mutation(
            group="M9",
            name="M9.4 the CORS/loopback pairing is not enforced",
            path=CONFIG,
            old=_CORS_VALIDATOR,
            new="        if False:  # MUTANT: permissive CORS on any bind",
            intent=(
                "§8.4 pairs a permissive CORS policy with a loopback-only bind and "
                "they are only safe together: allow_origins=['*'] on a wildcard "
                "socket is an open relay to /thesis, which runs a full snapshot "
                "build, in a service with NO authentication. The failure is "
                "invisible — the service works perfectly while it happens. Killed "
                "by the strictness guard, because no route test can construct this "
                "config."
            ),
        ),
        Mutation(
            group="M9",
            name="M9.5 loopback_only is not published",
            path=CONFIG,
            old=_LOOPBACK_PROPERTY,
            new="        return True  # MUTANT: always claims loopback",
            intent=(
                "A caller reading a response can no longer tell whether the "
                "service it is talking to is reachable off this machine. Hardcoding "
                "True is the worst form: it reports the safety property as present "
                "regardless of the bind. Killed by "
                "test_loopback_only_is_computed_from_the_bind_not_hardcoded, which "
                "builds a LEGAL non-loopback bind and requires False. Asserting "
                "True under the shipped config cannot kill it — the shipped host "
                "is loopback, so the constant and the computation agree and the "
                "check is a tautology (lesson 80)."
            ),
        ),
        # =====================================================================
        # M10 — the honesty control and the remaining guards
        # =====================================================================
        Mutation(
            group="M10",
            name="M10.1 the cheap health path still does not build (CONTROL)",
            path=HEALTH,
            old=_HEALTH_CHEAP,
            new="    if not deep and True:",
            intent=(
                "CONTROL — `not deep and True` is `not deep`. Semantically "
                "identical to the shipped code: same branch, same body, same "
                "return. It must survive."
            ),
            expect_killed=False,
            inert_proof=(
                "CONTROL — `X and True` is the identity on a boolean, so the "
                "control flow, the values returned and the exception surface are "
                "all unchanged. Nothing observable differs, so a kill would mean "
                "the selection is detecting the SHAPE of the code rather than its "
                "behaviour, and no other number here could be trusted."
            ),
        ),
        Mutation(
            group="M10",
            name="M10.2 the service version disagrees between /health and the app",
            path=HEALTH,
            old=_VERSION_CONSTANT,
            new='SERVICE_VERSION = "1.0.1"  # MUTANT: the app factory reads a different string',
            intent=(
                "The constant exists so /health and /openapi.json cannot disagree. "
                "Killed by test_the_health_version_is_the_app_version, which pins "
                "SERVICE_VERSION against the version declared in pyproject.toml — "
                "an INDEPENDENT source. Asserting only "
                "``app.version == SERVICE_VERSION`` cannot kill this, because both "
                "sides read the same constant and move together (lesson 80)."
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------


def check_targets(mutations: list[Mutation], *, verbose: bool = True) -> list[str]:
    """Refuse to run unless every ``old`` string is present EXACTLY ONCE.

    From D-048. ``str.replace(old, new, 1)`` takes the FIRST occurrence, so an
    ``old`` appearing twice silently rewrites the wrong site and the sweep then
    reports a surviving test — a conclusion about code nobody mutated.
    """
    problems: list[str] = []
    by_file: dict[Path, str] = {}
    for path in {mt.path for mt in mutations}:
        by_file[path] = path.read_text(encoding="utf-8")

    for mt in mutations:
        text = by_file[mt.path]
        if mt.old == mt.new:
            problems.append(f"{mt.name}: INERT BY CONSTRUCTION (old == new)")
            continue
        count = text.count(mt.old)
        if count == 0:
            problems.append(f"{mt.name}: target ABSENT in {mt.path.name} (0 occurrences)")
        elif count > 1:
            problems.append(
                f"{mt.name}: target AMBIGUOUS in {mt.path.name} "
                f"({count} occurrences) -- str.replace would rewrite the first"
            )
    if verbose:
        print(f"check_targets: {len(mutations)} mutations, {len(problems)} problem(s)")
        for p in problems:
            print(f"  !! {p}")
    return problems


def check_anchor_landings(mutations: list[Mutation], *, verbose: bool = True) -> list[str]:
    """Refuse to run unless every anchor lands in a symbol THIS increment owns.

    ``check_targets`` proves an anchor is unique; it cannot prove it is in the
    **right place** (O-67). The API layer has several ``if``-shaped statements a
    careless anchor could match in a neighbour — ``_require``'s guard appears in
    four different functions in spirit if not in text, and ``M8.5``'s ``[DONE]``
    literal occurs four times in ``reasoning_stream.py``.
    """
    problems: list[str] = []
    for mt in mutations:
        allowed = _ALLOWED_ANCHOR_OWNERS.get(mt.path.name)
        if allowed is None:
            problems.append(f"{mt.name}: no anchor-owner rule for {mt.path.name}")
            continue
        text = mt.path.read_text(encoding="utf-8")
        index = text.find(mt.old)
        if index < 0:
            continue  # check_targets already reports ABSENT
        owner = enclosing_symbol(text, index)
        if owner not in allowed:
            problems.append(
                f"{mt.name}: anchor lands in {owner!r}, which this increment does "
                f"not own (allowed: {sorted(allowed)})"
            )
    if verbose:
        print(f"check_anchor_landings: {len(mutations)} mutations, {len(problems)} problem(s)")
        for p in problems:
            print(f"  !! {p}")
    return problems


def check_no_mutant_left_on_disk() -> list[str]:
    """O-83's remedy: scan the WHOLE tree for mutant shapes, not per-catalogue.

    ``tools/sweep_health.py``'s leftover scan is **scoped**: it looks for
    mutations the sweep being checked declares, so a mutation left in a SHARED
    file by a different sweep is invisible — and it is invisible *precisely
    because that sweep succeeded*, because a succeeded mutation is one whose
    ``new`` text is now on disk. Measured live in D-067: D-064's ``M6.3`` mutant
    (``if False:`` in ``config.py``'s ``_remaining_shares_must_sum_to_one``) was
    still on disk and the health check reported 0 leftovers.

    The remedy is the one line O-83 names: scan ``src/`` for the mutant shapes
    independently of any catalogue. This runs BEFORE the sweep applies anything
    and AFTER it restores, so a mutant this sweep writes can never be mistaken
    for a pre-existing one.
    """
    problems: list[str] = []
    for path in sorted((REPO / "src").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith(("if False:", "if True:")):
                problems.append(f"{path.relative_to(REPO).as_posix()}:{lineno}: '{stripped[:60]}'")
            elif "# MUTANT" in line:
                problems.append(
                    f"{path.relative_to(REPO).as_posix()}:{lineno}: MUTANT marker left on disk"
                )
    return problems


def check_tests_collect() -> list[str]:
    """Prove the test selection actually collects tests BEFORE the sweep runs.

    A bad target path makes pytest exit **4**, and exit 4 is not a kill. Without
    this gate a typo'd path produces a false 100%-killed report (D-051).

    The selection is passed from ``PYTEST_TARGETS`` — the same constant
    ``run_pytest`` consumes. Both functions previously repeated the list by hand
    and the repetition drifted: four files were declared, three were run. This
    gate then validated the declaration the run did not use, and three provider
    mutants were reported SURVIVED that were measurably killed. **The fix is to
    make the list exist once.** (Lesson 5be.)
    """
    problems: list[str] = []
    for target in PYTEST_TARGETS:
        if not (REPO / target).exists():
            problems.append(f"test target ABSENT: {target}")
    if problems:
        return problems

    # this file, not untrusted input. The rule fires on any non-literal argv,
    # which is why the original code inlined the paths and drifted from the
    # declaration; suppressing it here is the price of one shared list.
    proc = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            *PYTEST_TARGETS,
            "-m",
            "not live",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        problems.append(
            f"test selection does not collect (pytest exit {proc.returncode}): "
            f"{proc.stdout.strip().splitlines()[-3:]}"
        )
        return problems
    match = re.search(r"(\d+)\s+tests? collected", proc.stdout)
    if not match or int(match.group(1)) == 0:
        problems.append("test selection collects ZERO tests")
    return problems


def check_the_run_and_the_declaration_agree() -> list[str]:
    """The kill run must select exactly the declared targets — structurally.

    D-070 shipped `PYTEST_TARGETS` with four entries while `run_pytest` and
    `check_tests_collect` each ran a hand-repeated three. The sweep therefore
    reported M9.1/M9.2/M9.3 as SURVIVED when each is measurably KILLED — the
    tests that kill them live in the file nobody selected. A green
    `check_tests_collect` certified a list the run never used.

    Reading the source to confirm both functions pass `*PYTEST_TARGETS` is the
    point: a future edit that re-inlines a path makes this red immediately,
    instead of waiting for a survivor to be misdiagnosed as an inert mutant.
    """
    problems: list[str] = []
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    for func_name in ("run_pytest", "check_tests_collect"):
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                argv_lists = [
                    elt
                    for call in ast.walk(node)
                    if isinstance(call, ast.Call)
                    for arg in call.args
                    if isinstance(arg, ast.List)
                    for elt in arg.elts
                ]
                # A literal test filename in the argv list is the drift.
                literals = [
                    elt.value
                    for elt in argv_lists
                    if isinstance(elt, ast.Constant)
                    and isinstance(elt.value, str)
                    and elt.value.startswith("tests/")
                ]
                if literals:
                    problems.append(
                        f"{func_name} passes literal test paths {literals} instead of "
                        f"*PYTEST_TARGETS; the declaration and the run can drift "
                        f"(lesson 5be, D-070)"
                    )
                uses_star = any(
                    isinstance(elt, ast.Starred)
                    and isinstance(elt.value, ast.Name)
                    and elt.value.id == "PYTEST_TARGETS"
                    for elt in argv_lists
                )
                if not uses_star:
                    problems.append(f"{func_name} does not splat PYTEST_TARGETS into its argv")
    return problems


def run_pytest() -> tuple[int, str]:
    """Run the targeted tests. Non-zero means the mutation was killed.

    Exit code **4** is pytest's "usage error / no tests collected", which is not
    a kill. ``-x`` is passed and is not optional (lesson 61): the kill signal
    must be cheap, because the cheap path is the one that gets used.

    The targets come from ``PYTEST_TARGETS`` rather than being repeated here.
    Repeating them is how this sweep first shipped: the module-level list named
    four files, this function ran three, and ``check_tests_collect`` validated
    the list the function did not use. Three provider mutants (M9.1/M9.2/M9.3)
    were measured KILLED when applied by hand and reported SURVIVED by the sweep,
    because the file containing their tests was never selected. **Lesson 5be
    again: the target list is a claim, and the claim is only true where it is
    consumed.** Deriving one from the other makes the drift unrepresentable.
    """

    # ``PYTEST_TARGETS``, a module-level literal defined at the top of this
    # file. The interpreter path is ``sys.executable``. Nothing here is
    # untrusted input, and sharing the list with ``check_tests_collect`` is what
    # stops the two from drifting (the D-070 defect).
    proc = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pytest",
            "-x",
            "-q",
            *PYTEST_TARGETS,
            "-m",
            "not live",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


#: The mutation currently written to disk, so a signal handler can undo it.
_IN_FLIGHT: list[tuple[Path, str] | None] = [None]


def _restore_in_flight(_signum: int, _frame: object) -> None:
    """Undo an in-flight mutation, then exit. Installed for SIGTERM/SIGINT.

    Without this a killed sweep leaves mutated source on disk — D-057's first run
    was stopped by a ``SIGTERM`` that bypassed the ``finally``, and D-062 caught a
    leftover (`MX3d`) with ``tools/sweep_health.py``'s scan. **O-83 adds: that
    scan is per-sweep, so a leftover in a SHARED file is invisible.** This handler
    plus ``check_no_mutant_left_on_disk`` is the defence.
    """
    pending = _IN_FLIGHT[0]
    if pending is not None:
        path, original = pending
        path.write_text(original, encoding="utf-8", newline="")
        print(f"\n!! interrupted -- restored {path.name} from the in-flight mutation")
    raise SystemExit(130)


def apply_and_test(mutation: Mutation) -> Result:
    """Apply one mutation, run the selection, restore the file."""
    original = mutation.path.read_text(encoding="utf-8")
    mutated = original.replace(mutation.old, mutation.new, 1)
    if mutated == original:
        return Result(mutation=mutation, applied=False, exit_code=-1)

    _IN_FLIGHT[0] = (mutation.path, original)
    try:
        mutation.path.write_text(mutated, encoding="utf-8", newline="")
        code, out = run_pytest()
    finally:
        mutation.path.write_text(original, encoding="utf-8", newline="")
        _IN_FLIGHT[0] = None
    return Result(mutation=mutation, applied=True, exit_code=code, output=out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", help="run only this mutation group, e.g. M1")
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the mutation catalogue and the check_targets verdict, then exit",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _restore_in_flight)
    signal.signal(signal.SIGINT, _restore_in_flight)

    print("=" * 78)
    print("mutation sweep: api_layer (D-070)")
    print("FOREGROUND ONLY -- this rewrites files under src/ while it runs.")
    print("=" * 78)

    # O-83's remedy, run FIRST: a mutant already on disk from an earlier sweep
    # would be indistinguishable from one of ours, and the sweep would then
    # report a survivor about code it did not write.
    pre_existing = check_no_mutant_left_on_disk()
    if pre_existing:
        print("\nREFUSING TO RUN: mutant shapes are already on disk (O-83). This")
        print("sweep's own restore cannot be distinguished from a foreign leftover:")
        for p in pre_existing:
            print(f"  !! {p}")
        return 2
    print("check_no_mutant_left_on_disk: clean (O-83 remedy)")

    mutations = build_mutations()
    problems = check_targets(mutations)
    if problems:
        print(
            "\nREFUSING TO RUN: check_targets found absent or ambiguous targets. "
            "A sweep that mutates the wrong site reports survivors that mean "
            "nothing (D-048)."
        )
        return 2

    landing_problems = check_anchor_landings(mutations)
    if landing_problems:
        print(
            "\nREFUSING TO RUN: an anchor lands in a function this increment does "
            "not own. The mutant would rewrite a neighbour, the tests that catch it "
            "are not in this selection, and the sweep would report a survivor about "
            "code nobody mutated (O-67)."
        )
        return 2

    test_problems = check_tests_collect()
    if test_problems:
        print("\nREFUSING TO RUN: the test selection is broken, so exit codes")
        print("would not distinguish a kill from a harness error:")
        for p in test_problems:
            print(f"  !! {p}")
        return 2
    print(f"test selection collects cleanly: {', '.join(PYTEST_TARGETS)}")

    drift_problems = check_the_run_and_the_declaration_agree()
    if drift_problems:
        print("\nREFUSING TO RUN: the kill run and the declared targets disagree.")
        print("A survivor would be misdiagnosed as inert when its test was never")
        print("selected (lesson 5be, D-070):")
        for p in drift_problems:
            print(f"  !! {p}")
        return 2
    print("the kill run and the declared selection agree (lesson 5be)")

    if args.list:
        for mt in mutations:
            print(f"  {mt.group:4} {mt.path.name:24} {mt.name}")
        return 0

    if args.group:
        mutations = [mt for mt in mutations if mt.group == args.group]
        if not mutations:
            print(f"no mutations in group {args.group}")
            return 2
        print(f"restricted to group {args.group}: {len(mutations)} mutation(s)")

    results: list[Result] = []
    for mt in mutations:
        print(f"\n--- {mt.group} {mt.name}")
        res = apply_and_test(mt)
        results.append(res)
        if not res.applied:
            print("    NOT APPLIED (no-op)")
        elif res.killed:
            first_fail = next(
                (ln for ln in res.output.splitlines() if ln.startswith("FAILED")),
                "(see output)",
            )
            print(f"    KILLED  {first_fail}")
        else:
            print("    SURVIVED")

    killed = sum(1 for r in results if r.applied and r.killed)
    survived = [r for r in results if r.applied and not r.killed]
    noop = [r for r in results if not r.applied]

    print("\n" + "=" * 78)
    print(f"applied {len(results) - len(noop)} / {len(results)}")
    print(f"killed  {killed}")
    print(f"survived {len(survived)}")

    # D-064's lesson 93: a mutation that was never APPLIED silently leaves the
    # denominator, and a sweep that does not say so can certify a run it did not
    # perform. The D-064 sweep printed "applied 25 / 27" and still certified.
    if noop:
        print("\nREFUSING TO CERTIFY: the following mutations were NOT APPLIED.")
        print("Their target text produced no change, so they tested nothing and")
        print("their absence from the survivor list is not evidence (lesson 93).")
        for r in noop:
            print(f"  !! {r.mutation.name}")
        return 2

    defects: list[str] = []
    if survived:
        print("\nsurvivors, classified:")
        for r in survived:
            name = r.mutation.name
            proof = r.mutation.inert_proof
            if not proof:
                defects.append(name)
                print(f"  [NO PROOF] {name}")
                continue
            tag = "control" if "CONTROL" in name else "inert"
            print(f"  [{tag}] {name}")
            for line in proof.splitlines():
                print(f"           {line}")

    print()
    if defects:
        print(
            "REFUSING TO CERTIFY: the following survivors carry no proof. An "
            "exemption must be an argument, not a label (O-42)."
        )
        for d in defects:
            print(f"  !! {d}")
        return 2

    control_name = "M10.1 the cheap health path still does not build (CONTROL)"
    control = next((r for r in results if r.mutation.name == control_name), None)
    if control is not None and control.killed:
        print(
            "REFUSING TO CERTIFY: the honesty control was killed. The sweep is "
            "reporting kills it cannot justify, so no other number means anything."
        )
        return 2

    # The final O-83 check: the restore ran for every mutation, so the tree must
    # be exactly as clean as it was before the sweep.
    post_sweep = check_no_mutant_left_on_disk()
    if post_sweep:
        print("\nREFUSING TO CERTIFY: the sweep left mutant shapes on disk.")
        for p in post_sweep:
            print(f"  !! {p}")
        return 2

    print("RESULT: every survivor is either expected or proven inert,")
    print("        and no mutant shape remains on disk (O-83).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
