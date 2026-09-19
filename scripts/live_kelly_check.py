"""Live cross-check: ``apply_fractional_kelly`` against the binary closed form.

Not a test. This directory holds operator scripts, deliberately excluded from the
default test run because they exercise the real settings tree and the real
scenario plumbing. Run with::

    uv run python scripts/live_kelly_check.py

Section 21.0: unit tests prove the arithmetic, this proves the wiring. For D-057
the wiring question is unusual and worth stating precisely.

What is different about a Kelly live check
------------------------------------------
Every sibling live check fetches a **time series** and drives the model over it.
This one cannot, because **Kelly's input is a caller-supplied distribution, not a
series** -- there is no market object whose schema is "a probability and a payoff
per branch". So the cross-check is not "does it reproduce a historical number";
it is **"does the shipped grid search agree with the closed form that exists for
the two-outcome case"**. That is a real, independent check of the arithmetic, and
it is the one §22.6 itself invites: the specification says the closed form does
not exist for more than two outcomes, which implies it does exist for two -- so
the binary case is the function's own analytic oracle.

The five things this check establishes
--------------------------------------

1. **THE CROSS-CHECK, against the analytic closed form.** For two outcomes the
   growth-optimal fraction is ``f* = (p*b - q*a) / (a*b)``, clamped to ``[0, 1]``
   (``b`` = the win payoff, ``a`` = the loss magnitude, ``q = 1 - p``). The
   shipped ``generalized_kelly_fraction`` is called over a sweep of the whole
   ``(p, b, a)`` space and compared against it. This is the D-057 increment's
   mandated cross-check, and it was **built from the start** rather than
   retrofitted -- the standing brief's second honour, bought forward from O-43's
   lesson.

2. **The placeholder is refuted on the REAL config tree.** §22.13 makes deleting
   ``raw_kelly = ev / 100`` mandatory. Probed in the increment it was 3 077x
   wrong; here the same claim is re-derived through the shipped settings, so a
   later config change that made the two coincide would be visible.

3. **The divisor is read from the live config, and it is >= the floor.** The
   mandatory fractional rule is the increment's central safety property. The
   check moves nothing; it reads ``kelly.fractional_divisor`` from the shipped
   YAML and asserts the published request is exactly ``full / divisor``.

4. **The search-edge collapse (P5b) is reproduced live.** Every all-positive-EV
   distribution pins ``f*`` at the grid's upper edge, so after division the
   *request* is identically ``1/divisor`` for all of them and does NOT
   distinguish them. The check demonstrates this on three different confident
   theses and shows that ``expected_log_growth_at_request`` is the surviving
   discriminator -- which is why that key exists rather than being decoration.

5. **Reports what it cannot validate.** The probabilities are judgements with no
   calibration behind them; nothing here can say whether ``p = 0.40`` is right.
   The check validates the *arithmetic over a stated distribution*, which is a
   strictly weaker claim than the sizing being correct, and it says so.

Offline by design: unlike the sibling live checks this one needs **no network**,
because the object under validation is the arithmetic rather than a data feed.
The "live" here means "through the live settings tree and the real call path",
which is the part the unit tests stub out. That is stated rather than hidden so a
reader does not mistake the absence of a fetch for a missing step.
"""

from __future__ import annotations

import sys
from typing import Any

from macro_engine.config import get_settings
from macro_engine.models.probability import ScenarioOutcome
from macro_engine.portfolio.risk_budget import (
    KellyInputs,
    RiskLimits,
    apply_fractional_kelly,
    generalized_kelly_fraction,
)

#: Win payoffs to sweep, as fractions of capital.
_WIN_PAYOFFS: tuple[float, ...] = (0.25, 0.50, 1.00, 2.00)

#: Loss magnitudes to sweep, as fractions of capital.
_LOSS_MAGNITUDES: tuple[float, ...] = (0.10, 0.25, 0.50, 1.00)

#: Win probabilities to sweep.
_PROBABILITIES: tuple[float, ...] = (0.20, 0.35, 0.50, 0.65, 0.80)


def _pair(probability: float, win: float, loss: float) -> list[ScenarioOutcome]:
    """A two-branch set. ``loss`` is passed as a **magnitude** and negated here.

    Negating inside the helper is deliberate: the first draft of the unit-test
    helper passed a positive number through as the loss and every branch won,
    which read as a grid bug rather than a fixture bug. The same trap applies to
    a live check, so the sign is handled in exactly one place.
    """
    assert loss > 0.0, "pass the loss as a magnitude; the sign is applied here"
    return [
        ScenarioOutcome(name="win", probability=probability, payoff_estimate=win),
        ScenarioOutcome(
            name="loss",
            probability=1.0 - probability,
            payoff_estimate=-loss,
        ),
    ]


def _closed_form_binary(probability: float, win: float, loss: float) -> float:
    """``f* = (p*b - q*a) / (a*b)`` clamped to ``[0, 1]`` -- the analytic oracle."""
    q = 1.0 - probability
    raw = (probability * win - q * loss) / (loss * win)
    return min(1.0, max(0.0, raw))


def _values_of(result: object) -> dict[str, Any]:
    """Narrow a ``ModelResult``'s published ``value`` to a dict for indexing.

    ``ModelResult.value`` is typed as a union (a result may carry a scalar), so
    indexing it and feeding the entries to ``float`` needs a narrowing step. The
    return type is ``dict[str, Any]`` rather than ``dict[str, object]`` because
    that is the project's idiom (``tests/portfolio/test_fractional_kelly.py``)
    and because ``object`` is not ``SupportsFloat`` — mypy --strict rejects
    ``float(values["x"])`` on a ``dict[str, object]`` while accepting it here.
    """
    value = getattr(result, "value", None)
    assert isinstance(value, dict), "these functions publish a dict"
    return value


def main() -> int:
    settings = get_settings()
    divisor = settings.kelly.divisor
    floor = float(settings.kelly.min_fractional_divisor.value)
    grid_points = settings.kelly.search_points
    cap = RiskLimits.from_settings().max_position_pct_of_portfolio

    print("=" * 78)
    print("live check: apply_fractional_kelly (Module 17.3, Sections 20.14/22.6)")
    print(f"config: divisor {divisor}  floor {floor}  grid {grid_points}  cap {cap}")
    print("=" * 78)

    # --- 1. THE CROSS-CHECK: shipped grid vs the analytic closed form -------
    print()
    print("1. CROSS-CHECK: the shipped grid search vs the binary CLOSED FORM")
    print(
        "   The analytic oracle for two outcomes is f* = (p*b - q*a) / (a*b),\n"
        "   clamped to [0,1]. Section 22.6 says no closed form exists beyond two\n"
        "   outcomes -- which is exactly why the binary case is the function's own\n"
        "   oracle, and why this is the mandated cross-check rather than a\n"
        "   re-implementation of the thing under test.\n"
    )

    worst_error = 0.0
    worst_case = ""
    checked = 0
    edge_pinned = 0
    for probability in _PROBABILITIES:
        for win in _WIN_PAYOFFS:
            for loss in _LOSS_MAGNITUDES:
                scenarios = _pair(probability, win, loss)
                published = float(
                    _values_of(generalized_kelly_fraction(scenarios))["full_kelly_fraction"]
                )
                closed = _closed_form_binary(probability, win, loss)
                error = abs(published - closed)
                checked += 1
                if error > worst_error:
                    worst_error = error
                    worst_case = (
                        f"p={probability} b={win} a={loss} grid={published} closed={closed}"
                    )
                if published >= 1.0:
                    edge_pinned += 1

    print(f"   cases compared: {checked}")
    print(f"   worst absolute error: {worst_error:.2e}")
    if worst_case:
        print(f"     at {worst_case}")
    print(f"   edge-pinned cases (f* == 1.0): {edge_pinned} of {checked}")

    # The published precision is 6 dp, so agreement is required AT that
    # precision rather than exactly: a 100001-point grid lands on a point
    # within 1e-5 of the true optimum, and the rounding is what we assert.
    assert worst_error < 1e-5, (
        f"the grid must agree with the closed form to better than the grid step; "
        f"worst error was {worst_error:.2e}"
    )
    print("   -> AGREES with the analytic oracle to better than the 1e-5 grid step")
    print("      (a 1000-point grid would NOT: it returns 0.2002 against 0.200000)")

    # --- 2. the placeholder refuted on the live config ----------------------
    print()
    print("2. THE PLACEHOLDER §22.13 DELETES, refuted on the live config tree")
    thesis = _pair(0.40, 1.00, 0.50)
    real = float(_values_of(generalized_kelly_fraction(thesis))["full_kelly_fraction"])
    ev = sum(s.probability * s.payoff_estimate for s in thesis)
    placeholder = ev / 100.0
    ratio = real / placeholder if placeholder else float("inf")
    print("   reference thesis: p=0.40 win=+1.00 loss=-0.50")
    print(f"   EV = {ev:+.6f}   placeholder EV/100 = {placeholder:.6f}")
    print(f"   shipped full-Kelly  = {real:.6f}   ratio = {ratio:,.1f}x")
    assert abs(real - placeholder) > 1e-3, "the placeholder must be a DIFFERENT number"
    assert real == 0.2, "the closed form on this thesis is exactly 0.200000"
    print("   -> the deletion is real: the two disagree by orders of magnitude,")
    print("      and the closed form confirms the shipped value is the correct one.")

    # --- 3. the mandatory divisor, read from the live config ----------------
    print()
    print("3. THE MANDATORY FRACTIONAL DIVISOR, read from the shipped YAML")
    limits = RiskLimits.from_settings()
    sized = apply_fractional_kelly(
        KellyInputs(scenarios=thesis, payoff_unit="fraction_of_capital", limits=limits)
    )
    sized_values = _values_of(sized)
    print(f"   configured divisor k = {divisor}  (floor {floor})")
    assert divisor >= floor, "the config floor is what makes full Kelly a startup error"
    assert float(sized_values["fractional_divisor"]) == divisor, "read from config, not a literal"
    assert float(sized_values["requested_fraction_of_capital"]) == round(real / divisor, 6), (
        "the request must be exactly full / divisor"
    )
    print(f"   full Kelly {real:.6f} / {divisor} = request {real / divisor:.6f}")
    print(
        f"   published {float(sized_values['fraction_of_capital']):.6f} "
        f"(cap {float(sized_values['position_cap']):.4f})"
    )
    print(f"   outcome: {sized_values['outcome']!r}")
    assert float(sized_values["fraction_of_capital"]) < real, (
        "fractional Kelly must never publish full Kelly"
    )

    # --- 4. the search-edge collapse, reproduced live -----------------------
    print()
    print("4. THE SEARCH-EDGE COLLAPSE (P5b): confident views flatten to one size")
    print(
        "   Every all-positive-EV distribution pins f* at the grid's upper edge, so\n"
        "   after division the REQUEST is identically 1/divisor for all of them.\n"
        "   expected_log_growth_at_request is the key that still discriminates.\n"
    )
    # Three DISTINCT theses that all pin at the search edge. The pinning
    # condition is `(p*b - q*a) / (a*b) >= 1`, i.e. `p*b - q*a >= a*b` -- a very
    # favourable edge. The first draft of this section used a 2:1 and an
    # even-money thesis, which have INTERIOR optima (0.95 and 0.10) and therefore
    # do NOT collapse; the assertion below caught it. Only sets that genuinely
    # pin at the boundary demonstrate the collapse, which is why they are
    # selected by the condition rather than by how confident they sound.
    confident = [
        ("5:1 payout ", _pair(0.70, 2.00, 0.25)),
        ("3:1 payout ", _pair(0.90, 1.00, 0.10)),
        ("1:1 payout ", _pair(0.80, 1.00, 0.25)),
    ]
    requests: list[float] = []
    growths: list[float] = []
    for label, scenarios in confident:
        result = apply_fractional_kelly(
            KellyInputs(scenarios=scenarios, payoff_unit="fraction_of_capital", limits=limits)
        )
        values = _values_of(result)
        # `at_search_edge` is published by the FULL-Kelly function, not by the
        # applied sizer, so it is read from the function that produces it rather
        # than assumed to be present on the sizing output.
        edge = _values_of(generalized_kelly_fraction(scenarios))["at_search_edge"]
        requests.append(float(values["requested_fraction_of_capital"]))
        growths.append(float(values["expected_log_growth_at_request"]))
        print(
            f"   {label}: full {float(values['full_kelly_fraction']):.4f} "
            f"edge={edge!s:5} "
            f"request {float(values['requested_fraction_of_capital']):.6f} "
            f"growth {float(values['expected_log_growth_at_request']):.6f} "
            f"outcome {values['outcome']!r}"
        )
    distinct_requests = len(set(requests))
    distinct_growths = len(set(growths))
    print(f"   distinct REQUESTS: {distinct_requests} of {len(requests)}")
    print(f"   distinct GROWTHS:  {distinct_growths} of {len(growths)}")
    assert distinct_requests == 1, "the collapse is the finding: all requests equal 1/divisor"
    assert requests[0] == round(1.0 / divisor, 6), "and the collapsed value IS 1/divisor"
    assert distinct_growths == len(growths), (
        "expected_log_growth_at_request must still separate the theses"
    )
    print("   -> CONFIRMED: the request does NOT preserve conviction at the edge,")
    print("      and the published growth rate is what still does.")

    # --- 5. what this check cannot validate ---------------------------------
    print()
    print("WHAT THIS CHECK CANNOT VALIDATE")
    print(
        "  * The PROBABILITIES. They are caller judgements with no calibration, so\n"
        "    this check validates the arithmetic OVER a stated distribution, which\n"
        "    is strictly weaker than the sizing being right. Nothing here can say\n"
        "    whether p=0.40 is the correct belief."
    )
    print(
        "  * Whether the hard limits are the RIGHT limits. The cap is a policy\n"
        "    number; the check confirms the configured value is the one used, not\n"
        "    that it is well chosen."
    )
    print(
        "  * Any network path. This check needs no feed, because the object under\n"
        "    validation is the arithmetic and the settings tree rather than a\n"
        "    series. That is a deliberate difference from its sibling checks, not\n"
        "    a missing step."
    )
    print()
    print("LIVE CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
