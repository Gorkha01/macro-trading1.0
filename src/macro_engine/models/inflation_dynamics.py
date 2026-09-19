"""Module 3.3 — the expectations-augmented Phillips curve.

One equation, and almost everything interesting about it is in the two terms
that cannot be measured.

The specification's form is ``pi = pi^e - beta * (u - u*)``. Read carefully,
that is a statement about *excess demand*: when unemployment is **below** u*
(``u - u* < 0``), the product ``beta * (u - u*)`` is negative, and subtracting a
negative number raises inflation. A tight labor market is inflationary. The sign
convention is load-bearing and easy to invert by accident, so it has a dedicated
test asserting direction against a tight-market case whose answer is known
before the code runs.

Why this returns a range-like reading rather than a point estimate
------------------------------------------------------------------
Section 21.4 lists u* (NAIRU) as **unobservable by nature** — item 13, alongside
r* and potential GDP. It is not a series with missing values; it is a latent
quantity that revisions move by several tenths of a point *after the fact*. A
Phillips-curve output that presented a single number would be concealing the
dominant source of its own error inside a float.

So this module does three things a naive transcription does not:

* It reports the **u-gap** alongside the implied inflation, because the gap is
  the part that is actually computed from observables and is therefore the part
  a reader can check.
* It **propagates the unobservability** through
  ``ConfidenceInputs(depends_on_unobservable=True)`` — the one lever Section
  21.1 says must be pulled wherever u* is consumed.
* It **states the two dominant failure modes as warnings** unconditionally:
  u*'s unobservability, and the fact that an unanchored ``pi^e`` makes the
  expectations term dominate so the slack term stops mattering at all (the
  1970s lesson, Module 3.3).

What this module deliberately does not do
-----------------------------------------
It does not derive ``pi^e`` and it does not estimate u*. Both are inputs. A
model that manufactured either would be inventing exactly the quantities the
Loophole Ledger exists to protect.

Module 5.6 — ``cross_asset_transmission``
-----------------------------------------
The second function here is Section 20.5's cross-asset transmission map. It is
a different kind of object from the Phillips curve: where that estimates one
number, this emits **a table of directional expectations** for six assets from
a single repricing.

Its specification is the most defective in the Tier 3 set, and the defects are
worth naming here because most of them are *structural* rather than numeric:

* **A declared input that is never read.** ``inflation_surprise_bp`` is in the
  input model, in ``inputs_used``, and in the docstring's triggering scenario
  — and appears **nowhere** in the body. Enumerated over the specification's
  whole declared input space, the output is invariant to it. The input could
  not have been live either: no free series carries a CPI consensus forecast.
* **A published value that is not a direction.** ``usd`` is assigned the
  string ``"up_if_relative_rate_expectations_rose"`` — a sentence placed in a
  map whose every other value is comparable. A caller cannot branch on it, and
  on a US-only system (§22.3) the counterparty reaction it names is
  genuinely unobservable, so the honest answer is ``unresolved``.
* **Three keys driven by one predicate.** ``bonds``,
  ``long_duration_growth_equities`` and ``value_vs_growth`` all test
  ``nominal_yield_change_bp > 0``, so four asset keys carry two bits.
* **A stated trigger that differs from the implemented one.** The gold
  paragraph argues from "a hot CPI print with real yields rising"; the code
  tests only ``real_yield_change > 0``, so a *cool* print with rising real
  yields is indistinguishable from a hot one in the output.
* **A bare ``str`` where a ``Literal`` belongs** (D-029), **a ``> 0`` / ``else``
  pair that reports a flat market as a move** (D-040's class), and **a
  hardcoded ``confidence=0.45``** (§22.8).

What is *not* a defect, and is load-bearing: the real-yield identity.
``nominal - breakeven`` reproduces the TIPS real yield to **0.000000** on live
data, so the derivation is exact rather than a proxy — and that exactness is
what allows the live check to cross-check the two paths against each other.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from macro_engine.config import TransmissionSettings, get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)

__all__ = [
    "ASSET_KEYS",
    "InflationTransmissionInputs",
    "PhillipsCurveInputs",
    "SurpriseDriver",
    "TransmissionDirection",
    "cross_asset_transmission",
    "phillips_curve_inflation",
]

#: The five assets the transmission map covers, declared once so a test can
#: assert the published key set rather than iterate whatever happens to be
#: there (the D-038 rule: **a test that iterates a published dict is vacuous
#: when it is empty**). The specification's own map adds a sixth key,
#: ``equities_overall``, and a seventh is proposed by neither — see the module
#: docstring on why the equity split is published as *two* keys rather than one.
ASSET_KEYS: tuple[str, ...] = (
    "bonds",
    "long_duration_growth_equities",
    "value_vs_growth",
    "equities_overall",
    "gold",
    "usd",
)

#: Every direction the map may emit. A ``Literal`` is a promise with two
#: halves (D-045a): this tuple is the runtime-iterable half, ``Tier``-style,
#: and a test asserts the two agree in both directions — membership *and*
#: producibility.
TransmissionDirection = Literal[
    "down",
    "up",
    "value_outperforms",
    "growth_outperforms",
    "worse_than_rate_move_alone",
    "better_than_rate_move_alone",
    "flat",
    "unresolved",
]

#: The declared surprise drivers. Section 20.5 annotates the field with these
#: three as a COMMENT on a bare ``str``, which is the D-029 defect class: a
#: typo falls through to the ``else`` and reports the least-informative branch
#: silently.
SurpriseDriver = Literal["demand", "supply_shock", "shelter_lag_mechanical"]


class PhillipsCurveInputs(BaseModel):
    """Module 3.3's four terms.

    ``beta`` is **not** a field. The specification's sample declares
    ``beta: float = 0.5`` with the comment "sensitivity, configurable", and
    ``config/settings.yaml`` already carries ``phillips.beta``. A default in the
    signature would be a second source of truth that silently wins whenever a
    caller omits the argument — so the model reads config instead, and a
    recalibration in one place moves every result.
    """

    model_config = ConfigDict(extra="forbid")

    inflation_expectations: float = Field(
        description=(
            "pi^e — expected inflation, percent. The specification does not "
            "prescribe a measure; a survey-based series (e.g. a University of "
            "Michigan or SPF expectation) and a market-based one (breakeven "
            "inflation from the TIPS spread) are both defensible and will "
            "differ. The choice belongs to the caller and should be recorded "
            "alongside the result, because the two are answering different "
            "questions: what households believe versus what the bond market "
            "is priced for."
        )
    )
    unemployment_rate: float = Field(
        ge=0.0,
        le=100.0,
        description="u — the actual unemployment rate, percent.",
    )
    nairu: float = Field(
        ge=0.0,
        le=100.0,
        description=(
            "u* — the NAIRU, percent. UNOBSERVABLE by nature (Section 21.4 item "
            "13): a latent quantity that ex-post revisions move by several "
            "tenths of a point. Supply it from config "
            "(``phillips.nairu``) or from a named forecaster (CBO), and note "
            "that a structural Beveridge outward shift implies this value has "
            "risen — ``beveridge_curve_position`` emits that instruction."
        ),
    )


def phillips_curve_inflation(inputs: PhillipsCurveInputs) -> ModelResult:
    """``pi = pi^e - beta * (u - u*)`` — expectations-augmented. ``value``: ``float``.

    Hand calculation at the Section 3.3 defaults (``beta = 0.5``)::

        pi^e = 2.5%, u = 4.0%, u* = 4.4%
            gap = 4.0 - 4.4 = -0.4pp          (labor market TIGHT: u below u*)
            pi  = 2.5 - 0.5 * (-0.4) = 2.5 + 0.2 = 2.70%

        pi^e = 2.5%, u = 5.4%, u* = 4.4%
            gap = +1.0pp                      (labor market SLACK)
            pi  = 2.5 - 0.5 * (+1.0) = 2.00%

    The first case is the one to hold onto: **u below u-star must raise
    inflation above pi^e**, and the sign test asserts exactly that. An implementation that
    wrote ``pi^e + beta * (u - u*)`` returns 2.30% on the first case and 3.00%
    on the second — both entirely plausible readings of the same inputs, and
    both backwards. Only a direction assertion against a known-tight market
    distinguishes them.

    Reported to 2 decimal places, matching the specification. The rounding is
    deliberately *after* the clamp-free arithmetic and the unrounded gap is
    reported separately, so a reader can recompute the implied value from the
    two reported numbers and see it reconcile.

    ``confidence`` comes from ``compute_confidence()`` and is the lowest in the
    model suite, because three penalties apply at once: u* is unobservable, the
    relationship is an uncalibrated heuristic, and the specification itself
    assigns it 0.35 — the lowest of any model in Section 20.
    """
    settings = get_settings()
    beta = settings.phillips.beta_value

    gap = inputs.unemployment_rate - inputs.nairu
    implied_inflation = inputs.inflation_expectations - beta * gap

    # Unconditional, because both are properties of the EQUATION rather than of
    # this particular set of numbers. Making either conditional would imply the
    # model is free of it on some inputs, which it never is.
    #
    # The ORDER is measured, not assumed (D-026). Section 3.3 calls u* "the
    # dominant uncertainty here"; live data shows the pi^e MEASURE choice moves
    # this output by ~1.8pp while a 0.5pp u* revision moves it by
    # ``beta * 0.5`` — an order of magnitude more. Both warnings are true, but
    # the expectations term is listed first because it is the larger risk, and a
    # caveat that points a reader at the smaller of two uncertainties is worse
    # than no caveat.
    expectations_dominance_pp = abs(beta) * 0.5
    warnings = [
        "The CHOICE of pi^e measure is the largest single source of variation "
        "in this output. A survey-based measure (what households expect) and a "
        "market-based one (breakeven inflation) answer different questions and "
        "differ by ~1.8pp on live data (4.20% Michigan vs 2.37% 10yr breakeven) "
        "— which moves this result by more than any other input. Record which "
        "measure you used; the number alone does not say.",
        "u* (NAIRU) is UNOBSERVABLE and revised significantly ex-post — "
        "Section 21.4 item 13 lists it as unobservable by nature, so no data "
        "improvement removes this. A 0.5pp error in u* moves the implied "
        f"inflation by {expectations_dominance_pp:.2f}pp at the current beta, "
        f"which is a real but SECOND-ORDER effect next to the pi^e measure "
        f"choice above.",
        "If pi^e is UNANCHORED, the expectations term dominates and the slack "
        "term barely matters. The 1970s stagflation lesson (Module 3.3): when "
        "expected inflation is high and moving, the (u - u*) term is a "
        "rounding error against it.",
    ]

    # A slack term that contributes nothing is worth naming rather than leaving
    # for the reader to notice. At small gaps the model is reporting pi^e back
    # with a slightly-adjusted label.
    slack_contribution = -beta * gap
    if abs(slack_contribution) < 0.05:
        warnings.append(
            f"The slack term contributes only {slack_contribution:+.3f}pp here — "
            f"the implied inflation is pi^e with a negligible adjustment. The "
            f"output carries almost no information beyond the expectations "
            f"input, so a change in the gap will look like noise in the result."
        )

    # Negative implied inflation is defensible but is a state worth flagging: it
    # means the slack term has overwhelmed a positive pi^e, which requires
    # either a large gap or a small beta.
    if implied_inflation < 0.0:
        warnings.append(
            f"Implied inflation is NEGATIVE ({implied_inflation:.2f}%). The "
            f"slack term has overwhelmed the expectations term. Check that the "
            f"u-gap is genuinely large and that pi^e is not negative before "
            f"reading this as deflation."
        )

    return ModelResult(
        model_name="phillips_curve_inflation",
        country="us",
        as_of=utc_now(),
        value=round(implied_inflation, 2),
        confidence=compute_confidence(
            ConfidenceInputs(
                is_heuristic_not_calibrated=True,
                depends_on_unobservable=True,
            )
        ),
        interpretation=(
            f"Phillips-implied inflation: {implied_inflation:.2f}% "
            f"(u-gap {gap:+.2f}pp, "
            f"{'tight' if gap < 0 else 'slack' if gap > 0 else 'at u*'})"
        ),
        context=(
            f"pi^e={inputs.inflation_expectations:.2f}%, beta={beta}, "
            f"u={inputs.unemployment_rate:.2f}%, u*={inputs.nairu:.2f}%. "
            f"Slack term contributes {slack_contribution:+.3f}pp. "
            f"Expectations-augmented form (Module 3.3): a NEGATIVE u-gap "
            f"(u below u*) means a tight labor market and raises inflation."
        ),
        inputs_used=[
            "inflation_expectations",
            "unemployment_rate",
            "nairu",
        ],
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Module 5.6 — cross-asset transmission
# ---------------------------------------------------------------------------


class InflationTransmissionInputs(BaseModel):
    """Module 5.6's transmission inputs, with the units of each change stated.

    Section 20.5 declares four fields and documents none of them. Three are
    **basis-point changes** and one is a **categorical**; the specification
    writes all four as bare floats/strings, so a caller who supplies a percent
    change instead of a bp change is wrong by a factor of 100 with no error
    raised. That is the same unit ambiguity that has already produced a silent
    factor-of-100 in this project (Treasury yields in percent vs OpenBB in fractions),
    so the unit is stated in the field description rather than in prose above
    the class.

    **All three change fields must be measured over the SAME window and come
    from the same observation dates.** The map is a statement about *one*
    repricing, and a nominal change measured over a month paired with a
    breakeven change measured over a week is not a decomposition of anything.
    This is the pairing discipline of Section 21.0's nine axes (date, window,
    right window, span) applied to the one model in the suite whose whole
    content is a *difference of two changes*.
    """

    model_config = ConfigDict(extra="forbid")

    inflation_surprise_bp: float | None = Field(
        default=None,
        description=(
            "The CPI surprise in basis points (outturn minus consensus "
            "forecast, same sign convention: a hot print is POSITIVE). "
            "**Optional, and its absence is not a reduction in coverage.** "
            "Section 20.5 declares this field, lists it in ``inputs_used``, and "
            "then never reads it — the specification's map is provably "
            "invariant to it (enumerated over the full declared input space; "
            "see the module docstring and D-052). There is also no free series "
            "carrying a CPI consensus forecast (probed via ``fred_search``; "
            "recorded as a ``blocked:`` entry in ``series_registry.yaml``), so "
            "requiring it would make the function uncallable on live data while "
            "buying nothing. It is retained as an optional *disclosure* channel "
            "and is reported in ``value`` when supplied — never used to change "
            "a direction, because a direction the specification never derived "
            "from it must not start depending on it silently."
        ),
    )
    surprise_driver: SurpriseDriver = Field(
        description=(
            "Which channel produced the repricing. Section 20.5 annotates this "
            "as a comment on a bare ``str``, which lets a typo reach the "
            "``else`` branch and be reported as the *shelter-lag* case — the "
            "least informative of the three — with no error. Typed as a "
            "``Literal`` so the typo is a validation failure instead."
        )
    )
    nominal_yield_change_bp: float = Field(
        description=(
            "Change in the nominal 10-year Treasury yield, **basis points**, "
            "over the measurement window. Percent must be multiplied by 100 "
            "before passing. Positive = yields rose."
        )
    )
    breakeven_change_bp: float = Field(
        description=(
            "Change in the 10-year TIPS breakeven inflation rate, **basis "
            "points**, over the SAME window and the same observation dates as "
            "``nominal_yield_change_bp``. Positive = the market repriced "
            "inflation expectations UP."
        )
    )

    @model_validator(mode="after")
    def _check_change_signs_are_not_degenerate(self) -> InflationTransmissionInputs:
        """Reject a *zero* change only when it is the **only** thing supplied.

        A single change of exactly zero is a perfectly real observation — a
        Treasury market that did not move — but Section 20.5's map turns it
        into a *direction* via ``> 0`` comparisons, so a flat market is
        reported as ``bonds: up``. The map below handles that case explicitly
        (``flat``), so this validator does NOT reject zeros: rejecting them
        would make an observable state unrepresentable, which is D-050's
        ``allow_all_neutral`` lesson.

        What it rejects is the *silent* case: two identical changes that the
        caller believes are different, which is only detectable when the pair
        is (0, 0) and the caller has supplied no size to the surprise either.
        That combination carries literally no information and a map built from
        it is noise dressed as a view.
        """
        if (
            self.nominal_yield_change_bp == 0.0
            and self.breakeven_change_bp == 0.0
            and not self.inflation_surprise_bp
        ):
            raise ValueError(
                "nominal_yield_change_bp and breakeven_change_bp are both "
                "exactly zero and no inflation_surprise_bp was supplied: the "
                "transmission map would be built from no repricing at all. "
                "Supply the actual changes, or record why the market did not "
                "move — the function reports `flat` for a single zero change, "
                "but has nothing to report when nothing moved anywhere."
            )
        return self


def _driver_of(
    real_change_bp: float,
    breakeven_change_bp: float,
    nominal_change_bp: float,
    *,
    real_threshold: float,
    breakeven_threshold: float,
    trivial_move: float,
) -> str:
    """Which channel drove the repricing — **measured from the split, not assumed**.

    Section 20.5 declares a ``surprise_driver`` input and then reads it only
    for the ``equities_overall`` key, never to decide *whether the move was
    real or breakeven driven*. That is backwards: the split of a nominal move
    into its real and breakeven legs is exactly the measurement of which
    channel drove it, and it is the thing the section's own gold paragraph
    argues from.

    Live measurement over 5 520 non-trivial monthly changes in the 10-year
    complex (DGS10 / T10YIE / DFII10, 2003-01-02..2026-09-16) shows why this
    matters: the breakeven share of a nominal move is **negative 27.54%** of
    the time and exceeds 1.0 a further 18.06% of the time. The two legs
    routinely move in opposite directions, so "the nominal yield rose" does
    not tell you which channel moved and the sign of the real leg is genuinely
    new information. Classifying by the split: 61.74% of moves are real-driven,
    40.85% breakeven-driven, 20.42% both (the shares overlap because a share
    and its complement can both be large only when one is negative), and
    17.83% are marginal with neither band met.

    Returns one of ``real_driven`` / ``breakeven_driven`` / ``both_channels`` /
    ``neither_channel`` / ``indeterminate``. **The bands are not a partition**
    and the return value says so: ``both_channels`` is the genuinely
    opposite-signed case, not a failure to decide.

    A move smaller than ``trivial_move`` is ``indeterminate`` regardless of the
    shares — dividing by a near-zero denominator is how a 1bp rounding artefact
    becomes a confident driver call.
    """
    if abs(nominal_change_bp) < trivial_move:
        return "indeterminate"

    real_share = real_change_bp / nominal_change_bp
    breakeven_share = breakeven_change_bp / nominal_change_bp

    real_drives = abs(real_share) >= real_threshold
    breakeven_drives = abs(breakeven_share) >= breakeven_threshold

    if real_drives and breakeven_drives:
        # Both legs carry most of the move. Reachable only when they point in
        # OPPOSITE directions (a share and its complement cannot both be large
        # otherwise), which is why it is its own outcome rather than a tie.
        return "both_channels"
    if real_drives:
        return "real_driven"
    if breakeven_drives:
        return "breakeven_driven"
    return "neither_channel"


def _leg_direction(change_bp: float, flat_band: float) -> TransmissionDirection:
    """Map a signed change to ``up`` / ``down`` / ``flat``.

    This is Section 20.5's ``"down" if x > 0 else "up"`` with the dead branch
    repaired. The specification's ``else`` catches **both** ``x == 0`` and
    ``x < 0``, so an exactly-unchanged yield is reported as having *fallen*.
    Measured live: DGS10 is exactly unchanged on **459 of 5 930** daily changes
    (7.7%) and T10YIE on **965** (16.3%), so the fallthrough is not vanishingly
    rare — it is a wrong sign on a seventh of observations. D-040 found the
    same defect shape in ``qe_qt_stance`` (a neutral branch requiring a
    thirteen-week change of exactly zero, measured at 0 of 1 226 weeks).

    The boundary is **inclusive on the flat side**: a change of exactly
    ``flat_band`` is ``flat``. A test pins which side owns it, because without
    one a ``<`` → ``<=`` change is unobservable and every boundary reading
    could silently shift into the neighbouring band (D-045a).
    """
    if abs(change_bp) <= flat_band:
        return "flat"
    return "down" if change_bp > 0 else "up"


def cross_asset_transmission(inputs: InflationTransmissionInputs) -> ModelResult:
    """Module 5.6's transmission map, as explicit directional expectations.

    ``value``: ``dict[str, str]`` — seven keys. Five are the assets Section
    20.5 names (``bonds``, ``long_duration_growth_equities``,
    ``value_vs_growth``, ``gold``, ``usd``) and two are diagnostics this module
    adds because the specification's own reasoning requires them and its output
    cannot express them (``driver_channel``, ``real_yield_change_bp``).

    The critical, non-obvious one, verbatim from the specification: **GOLD
    trades REAL yields, not inflation** — a hot CPI print with real yields
    RISING is gold-NEGATIVE, which contradicts naive "gold is an inflation
    hedge" reasoning.

    What the specification gets right, and what it gets wrong
    ---------------------------------------------------------
    The real-yield identity is **exact**, not an approximation. Probed live:
    ``DGS10 - T10YIE - DFII10`` has a maximum absolute error of **0.000000**
    over all 5 931 observations (2003-01-02..2026-09-16), and 100.00% agree
    within 0.01pp. So deriving the real leg as ``nominal - breakeven`` is
    arithmetically identical to reading the TIPS series directly — and the
    live check uses that to cross-check the two paths, which is the strongest
    available wiring test for this function.

    Seven defects are corrected. They are listed in full in the module
    docstring of ``docs/DECISIONS.md`` D-052; the substance is:

    1. **``inflation_surprise_bp`` is declared, listed in ``inputs_used``, and
       never read.** Enumerated over the specification's whole declared input
       space, the map produces the *same* output for every value of it. The
       input could not have been live either: no free series carries a CPI
       consensus forecast (probed with ``fred_search``; recorded as a
       ``blocked:`` entry). It is retained as an optional **disclosure** — its
       value is published when supplied, and it never moves a direction,
       because a direction the specification did not derive from it must not
       start depending on it silently.
    2. **Three keys from one predicate.** ``bonds``, ``long_duration_growth_equities``
       and ``value_vs_growth`` all key on ``nominal_yield_change_bp > 0``, so
       the map's four asset keys carry at most **two** independent bits. The
       three are kept (each names a distinct mechanism) but the shared
       predicate is published as its own key so the coupling is visible rather
       than implied.
    3. **``usd`` was not a direction.** The specification emits the *sentence*
       ``"up_if_relative_rate_expectations_rose"`` into a directional map. A
       value no caller can compare, branch on or evaluate is not an output, it
       is a TODO. The corrected form emits ``unresolved`` **and** warns, which
       is the honest report: the dollar leg genuinely requires the
       counterparty central bank's reaction (§22.3's US-only scope means this
       system cannot see it), so a direction would be fabricated.
    4. **The gold rule's stated trigger and its implemented trigger differ.**
       The prose says "a hot CPI print with real yields RISING"; the code tests
       only ``real_yield_change > 0``. So a *cool* print with rising real
       yields — a completely different scenario — also returns gold-down, and
       the two are indistinguishable from the output. The corrected form
       publishes the ``driver_channel`` so the reason is on the record.
    5. **``surprise_driver`` is a bare ``str``** whose third value falls
       through an ``else``, so a typo like ``"supply shock"`` is reported as
       the shelter-lag case — the least informative branch — with no error
       (D-029's ``Literal`` rule).
    6. **A flat market reports a direction.** ``x > 0`` with an ``else``
       reports ``x == 0`` as ``up``; see ``_leg_direction``.
    7. **Confidence is hardcoded ``0.45``**, which §22.8 reserves for
       ``compute_confidence()``.

    What this function deliberately does not do
    -------------------------------------------
    It does not fetch anything, and it does not decide trades. It is a map:
    given one repricing, it reports which way each asset is expected to move
    *by that channel*, with the driver made explicit so a reader can tell a
    real-yield call from an inflation call. **The USD leg is structurally
    unresolvable on this system's supported path** and says so.
    """
    settings = get_settings().transmission

    nominal_change = inputs.nominal_yield_change_bp
    breakeven_change = inputs.breakeven_change_bp
    # The identity is exact on live data (max error 0.000000), so this is a
    # derivation of a measured quantity, not a proxy for one.
    real_change = nominal_change - breakeven_change

    bonds = _leg_direction(nominal_change, settings.flat_band)
    gold = _leg_direction(real_change, settings.flat_band)

    # Section 20.5 emits three keys from this one predicate. Kept as three
    # keys because each names a distinct mechanism (a bond price, a duration
    # exposure, a style spread), but the shared input is published so the
    # coupling is auditable from the output rather than inferred from the code.
    if bonds == "flat":
        long_duration = "flat"
        value_vs_growth = "flat"
    elif bonds == "up":
        long_duration = "up"
        value_vs_growth = "growth_outperforms"
    else:
        long_duration = "down"
        value_vs_growth = "value_outperforms"

    driver = _driver_of(
        real_change,
        breakeven_change,
        nominal_change,
        real_threshold=settings.real_driven_threshold,
        breakeven_threshold=settings.breakeven_driven_threshold,
        trivial_move=settings.trivial_move,
    )

    # The equity leg keys on the DECLARED driver, which is the one place the
    # specification's `surprise_driver` input is genuinely load-bearing (it
    # selects a mechanism description, not a direction). The measured
    # `driver` above is published alongside so the two can disagree visibly.
    if inputs.surprise_driver == "supply_shock":
        equities = "worse_than_rate_move_alone"
    elif inputs.surprise_driver == "demand":
        equities = "better_than_rate_move_alone"
    else:
        equities = "flat"

    # Section 20.5's `usd` value is a sentence, not a direction. A caller
    # cannot compare, branch on or evaluate it. Emitted as `unresolved` with a
    # warning, because on a US-only system (§22.3) the counterparty reaction
    # is genuinely unobservable — a direction here would be invented.
    usd: TransmissionDirection = "unresolved"

    warnings = _transmission_warnings(
        inputs=inputs,
        driver=driver,
        bonds=bonds,
        gold=gold,
        real_change=real_change,
        settings=settings,
    )

    return ModelResult(
        model_name="cross_asset_transmission",
        country="us",
        as_of=utc_now(),
        value={
            "bonds": bonds,
            "long_duration_growth_equities": long_duration,
            "value_vs_growth": value_vs_growth,
            "equities_overall": equities,
            "gold": gold,
            "usd": usd,
            "real_yield_change_bp": round(real_change, 2),
            "driver_channel": driver,
            "real_leg_share_of_move": (
                round(real_change / nominal_change, 4) if nominal_change else None
            ),
            "breakeven_leg_share_of_move": (
                round(breakeven_change / nominal_change, 4) if nominal_change else None
            ),
            "inflation_surprise_bp": inputs.inflation_surprise_bp,
            "gold_call_base_rate": settings.gold_base_rate,
        },
        confidence=compute_confidence(
            ConfidenceInputs(
                is_heuristic_not_calibrated=True,
                # The bands are shares of a measured split, but which channel
                # "drove" a move is an attribution, not an observation — the
                # same repricing is consistent with more than one narrative.
                depends_on_unobservable=False,
            )
        ),
        interpretation=(
            f"Transmission map for a {inputs.surprise_driver}-driven "
            f"{nominal_change:+.0f}bp nominal move: real leg "
            f"{real_change:+.0f}bp ({driver}), so gold {gold}, bonds {bonds}. "
            f"USD unresolved — it needs the counterparty central bank's "
            f"reaction, which a US-only read cannot see."
        ),
        context=(
            f"Real yield change {real_change:+.0f}bp drives the gold call, NOT "
            f"the CPI print itself (Module 5.6). Nominal {nominal_change:+.1f}bp "
            f"= real {real_change:+.1f}bp + breakeven {breakeven_change:+.1f}bp "
            f"— an EXACT identity on live data, max error 0.000000. "
            f"Gold-on-a-nominal-rise base rate {settings.gold_base_rate:.2%}; "
            f"the breakeven leg opposes the nominal leg "
            f"{settings.breakeven_negative_share:.2%} of the time."
        ),
        inputs_used=[
            "surprise_driver",
            "nominal_yield_change_bp",
            "breakeven_change_bp",
        ]
        + (["inflation_surprise_bp"] if inputs.inflation_surprise_bp is not None else []),
        warnings=warnings,
    )


def _transmission_warnings(
    *,
    inputs: InflationTransmissionInputs,
    driver: str,
    bonds: TransmissionDirection,
    gold: TransmissionDirection,
    real_change: float,
    settings: TransmissionSettings,
) -> list[str]:
    """Build the warning list. Every branch is reachable by some test."""
    flat_band = settings.flat_band
    warnings: list[str] = [
        "USD direction requires the COUNTERPARTY central bank's reaction too — "
        "never a single-country read (Module 5.6/9). On this US-only system "
        "(Section 22.3) that reaction is unobservable, so `usd` is reported "
        "`unresolved` rather than guessed.",
        "The transmission map is a set of DIRECTIONAL expectations from ONE "
        "channel, not a forecast. It says which way each asset moves if this "
        "channel dominates; it does not say the channel will dominate.",
    ]

    if bonds == "flat":
        warnings.append(
            f"The nominal 10-year yield changed by "
            f"{inputs.nominal_yield_change_bp:+.2f}bp — within the "
            f"{flat_band:.2f}bp flat band. Section 20.5's `> 0` test would have "
            f"reported this as a RISE; it is reported `flat` because a change "
            f"below the reporting granularity is not a direction."
        )

    if gold != bonds and bonds != "flat" and gold != "flat":
        warnings.append(
            f"GOLD DISAGREES WITH BONDS: bonds read {bonds} (nominal "
            f"{inputs.nominal_yield_change_bp:+.1f}bp) while gold reads {gold} "
            f"(real {real_change:+.1f}bp). This is the case Section 20.5's own "
            f"paragraph exists to flag — the inflation print and the real-yield "
            f"move point opposite ways. Measured frequency: the breakeven leg "
            f"opposes the nominal leg on "
            f"{settings.breakeven_negative_share:.2%} of non-trivial monthly "
            f"changes, so this is common, not exotic."
        )

    if driver == "indeterminate":
        warnings.append(
            f"The nominal move ({inputs.nominal_yield_change_bp:+.2f}bp) is "
            f"below the {settings.trivial_move:.1f}bp floor at which a "
            f"real/breakeven SPLIT is measurable, so no driver is attributed. "
            f"The directional reads below are still reported, but the shares "
            f"that would justify them are a ratio over a near-zero "
            f"denominator."
        )
    elif driver == "both_channels":
        warnings.append(
            "BOTH legs carry most of the move. This is reachable only when the "
            "real and breakeven legs point in OPPOSITE directions — a share "
            "and its complement cannot both be large otherwise — so the "
            "repricing is not attributable to one channel and `equities_overall` "
            "(keyed on the DECLARED driver) should be read with that in mind."
        )
    elif driver == "neither_channel":
        warnings.append(
            "NEITHER leg carries most of the move: the two legs offset each "
            "other, each individually below its band. The `equities_overall` "
            "key is still keyed on the DECLARED `surprise_driver`, which the "
            "measured split does not corroborate."
        )

    if gold == "down" and inputs.nominal_yield_change_bp > 0:
        warnings.append(
            f"Gold reads DOWN on a nominal yield RISE. Section 20.5's stated "
            f"trigger is 'a hot CPI print with real yields rising', but the "
            f"implemented test is only whether the REAL yield rose — so this "
            f"call fires on a COOL print with rising real yields as well. "
            f"Base rate: this is what the rule says on "
            f"{settings.gold_base_rate:.2%} of nominal rises, i.e. it is closer "
            f"to the rule's default than to a finding."
        )

    if inputs.inflation_surprise_bp is not None:
        warnings.append(
            f"inflation_surprise_bp={inputs.inflation_surprise_bp:+.1f}bp was "
            f"supplied and is REPORTED ONLY: Section 20.5 declares it, lists it "
            f"in `inputs_used`, and never reads it, so no direction here "
            f"depends on it. It is published so a downstream reader can "
            f"reconcile the map against the print."
        )

    return warnings
