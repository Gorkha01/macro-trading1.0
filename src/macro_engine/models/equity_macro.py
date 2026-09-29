"""Module 11 — Equity Macro: the regime-conditional equity posture.

Section 6.9 gives Module 11 two functions and Section 20.20's part E adds a
third. All three live here, because the mapping table (``AGENTS.md:1783``) and
the source tree (``AGENTS.md:229``) both name ``models/equity_macro.py`` as
Module 11's home, and Section 20.20-E's own header reads
``# src/macro_engine/models/equity_macro.py (addition)``. Module 11 is the
equity-macro layer — it maps a macro **regime label** (Module 3/4's classifier)
onto an equity posture, in three complementary forms:

* :func:`sector_rotation_prior` — which *sectors* a historical base rate favours
  in the regime;
* :func:`duration_sensitivity` — how much a *rate move* moves a growth or value
  equity, through the discount-rate channel (a mechanical duration proxy);
* :func:`factor_tilt_prior` — which *style factors* the regime has historically
  rewarded.

The first and third are **lookups whose domain is the classifier's own declared
vocabulary** and read no prices. The second reads no prices either, but it *is*
an arithmetic sensitivity: it turns a rate move into a percentage price move —
and, per its own specification, an *illustrative* one that is explicitly not a
calibrated regression.

Supersession for the other two functions (Section 21.3, D-096) — answered first
-------------------------------------------------------------------------------
``duration_sensitivity`` and ``factor_tilt_prior`` supersede **nothing named**,
and nothing supersedes them: the same *new capability* answer the module's first
function gave. Module 11 had **no function at all** in ``src/`` before D-123;
these complete the module the specification always placed here. Neither shares
an input with a shipped model: both read a regime label (and, for
``duration_sensitivity``, a stated rate move), never a price, rate, spread or
flow.

A PRIOR, not a rule — and the model says so on every path
---------------------------------------------------------
Section 6.9's own ``context`` and the Module 11 discussion (``AGENTS.md:2195``)
are emphatic: sector rotation here is a **historical base-rate prior**, not a
mechanical rule, and "every cycle has idiosyncratic features (starting
valuations, policy mix)". Two design consequences follow, and both are load
bearing rather than decoration:

* the published ``context`` states the prior-not-rule qualification, and a
  ``warnings`` entry names the cycle-specific adjustments a reader must make
  before acting — because a caller who reads a bare list of sectors as a
  recommendation has misread the model, and the output must make that hard;
* the ``confidence`` is a **cap**, not a computed hit-rate, precisely because the
  method has no factor measuring the current cycle's idiosyncrasies.

The defect in the reference map, and how this closes it
-------------------------------------------------------
Section 6.9's reference body (``AGENTS.md:1092``) inlines a ``ROTATION_MAP`` keyed
on **six** regime strings — ``early_expansion`` / ``mid_expansion`` /
``late_expansion`` / ``recession`` / ``stagflation`` / ``disinflation`` — and
resolves it with ``ROTATION_MAP.get(regime_state, ["diversified — no strong
prior"])``. But the classifier in ``models/regime.py`` declares **nine** states
in ``REGIME_STATES``, and — after **D-037** made the declared vocabulary
*reachable*, by fixing exactly the three states Section 6.2 left unreachable —
it can return all nine, including ``slowdown``, ``recovery`` and ``reflation``.
Under the reference body, a lookup on any of those three **silently returns the
generic fallback**: the model would answer *"no prior"* for three regimes the
classifier actually produces.

This is the same ``declared-consumed-unreachable`` shape D-037 fixed in the
classifier's own branch chain, reappearing one module downstream — the reference
map is not **exhaustive over the vocabulary it is keyed on**. ``sector_rotation_prior``
closes it: :data:`SECTOR_ROTATION_PRIOR` is keyed on **every** member of
``REGIME_STATES`` (asserted by a test, so the two cannot drift), and the
fallback is reserved for a regime value that is genuinely outside the declared
vocabulary. The three added rows (``slowdown`` / ``recovery`` / ``reflation``)
are drawn from Module 11's own factor-tilt sibling (``AGENTS.md:3092``'s
``FACTOR_REGIME_MAP``, which *is* exhaustive over the nine) and from the
adjacent-regime sector logic the reference already uses — ``slowdown`` and
``recovery`` are the "growth contracting but not yet a recession" and "turning up
from the trough" states, so ``slowdown`` takes the defensive/quality tilt and
``recovery`` takes the early-recovery cyclical tilt. **The added rows are this
build's declaration, recorded as such; they are NOT in Section 6.9's six-key
map.** A caller can therefore distinguish a specification row from an extension
row by reading :data:`SPECIFICATION_REGIMES` below.

The vocabulary is REFUSED, not defaulted, when it is not a classifier value
----------------------------------------------------------------------------
Section 6.9's signature is ``sector_rotation_prior(regime_state: str)`` and its
body branches on a mapping. A bare ``str`` lets a typo, a spelling, or an
empty string reach the ``.get`` and receive the generic fallback — a caller who
passes ``"recesion"`` is told *"no strong prior"* rather than *"that is not a
regime"*. That is the silent-fallthrough class this project refuses (the
``intervention_capacity`` direction-``else`` defect, D-118). The field is
therefore typed as :data:`~macro_engine.models.regime.RegimeState` — the
classifier's own ``Literal``, imported rather than re-typed (D-046: ask the
upper layer's rule) — so an unrecognised value is refused at construction and
can never reach the lookup.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    EvidenceSourceFamily,
    FiniteInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)
from macro_engine.models.regime import REGIME_STATES, RegimeState

__all__ = [
    "FACTOR_NAMES",
    "FACTOR_REGIME_MAP",
    "SECTOR_PRIOR_EXTENSION_REGIMES",
    "SECTOR_ROTATION_PRIOR",
    "SPECIFICATION_REGIMES",
    "DurationSensitivityInputs",
    "EquityStyle",
    "FactorTiltInputs",
    "SectorRotationInputs",
    "duration_sensitivity",
    "factor_tilt_prior",
    "sector_rotation_prior",
]

#: The two equity styles ``duration_sensitivity`` distinguishes.
#:
#: Section 6.9's signature takes a bare ``is_growth: bool``; the field is a named
#: ``Literal`` instead, because a two-valued boolean's meaning depends on which
#: way a bare ``True`` is read and the two styles are the model's entire
#: distinction (D-029/D-046). The classifier's ``RegimeState`` is imported because
#: its vocabulary lives in ``regime.py``; this vocabulary lives here, because it
#: is Equity Macro's own.
EquityStyle = Literal["growth", "value"]

#: The regime states Section 6.9's reference ``ROTATION_MAP`` is keyed on.
#:
#: Preserved as a declared constant so the extension rows below (and the test
#: that pins them) can name exactly which rows are the specification's and which
#: are this build's. It is a subset of
#: :data:`~macro_engine.models.regime.REGIME_STATES`.
SPECIFICATION_REGIMES: tuple[str, ...] = (
    "early_expansion",
    "mid_expansion",
    "late_expansion",
    "recession",
    "stagflation",
    "disinflation",
)

#: The three classifier states Section 6.9's six-key map does NOT cover.
#:
#: ``regime.py`` can emit all three (D-037 made them reachable), so without
#: these rows the reference body would answer *"no strong prior"* for a regime
#: the classifier actually produces — the coverage hole this module closes.
SECTOR_PRIOR_EXTENSION_REGIMES: tuple[str, ...] = (
    "slowdown",
    "recovery",
    "reflation",
)

#: The regime-conditional sector prior, keyed on the classifier's vocabulary.
#:
#: **Every** member of ``REGIME_STATES`` (the nine-string tuple in
#: ``models/regime.py``) has an entry — asserted by
#: ``tests/models/test_equity_macro.py``, so a future change to the classifier's
#: vocabulary cannot leave a state unmapped without failing a test.
#:
#: The six :data:`SPECIFICATION_REGIMES` rows are Section 6.9's own. The three
#: :data:`SECTOR_PRIOR_EXTENSION_REGIMES` rows are this build's declaration (see
#: the module docstring): ``slowdown`` takes the durable/quality tilt its
#: ``FACTOR_REGIME_MAP`` sibling gives it, ``recovery`` takes the early-recovery
#: cyclical tilt, and ``reflation`` — the "growth re-accelerating with inflation
#: firming" state — takes the late-cycle real-asset/cyclical tilt that ``energy``
#: and ``materials`` express. Section 6.9 has no row for any of the three.
#:
#: The lists are ORDERED, and the order is the specification's: it runs most
#: advantaged first. It is preserved rather than sorted because a consumer that
#: renders "top sector" reads position zero, and the specification's ordering is
#: the claim about which sector leads.
SECTOR_ROTATION_PRIOR: dict[str, tuple[str, ...]] = {
    # --- Section 6.9's six specification rows -------------------------------
    "early_expansion": ("financials", "consumer_discretionary", "industrials"),
    "mid_expansion": ("technology",),
    "late_expansion": ("energy", "materials"),
    "recession": ("utilities", "staples", "healthcare"),
    "stagflation": ("staples", "energy"),
    "disinflation": ("technology", "financials"),
    # --- this build's three extension rows (Section 6.9 lacks them) ---------
    # `slowdown` is "growth contracting but not yet a recession": the
    # `FACTOR_REGIME_MAP` sibling tilts it to quality + low-vol, whose sector
    # expression is the defensive/quality complex.
    "slowdown": ("staples", "healthcare", "utilities"),
    # `recovery` is "turning up from the trough" — early-cycle cyclicals lead
    # before the expansion is confirmed.
    "recovery": ("financials", "consumer_discretionary", "industrials"),
    # `reflation` is "growth re-accelerating with inflation firming": the
    # late-cycle real-asset tilt, expressed through energy and materials.
    "reflation": ("energy", "materials", "industrials"),
}


class SectorRotationInputs(BaseModel):
    """The single input: a regime label from the classifier.

    Section 6.9's signature takes ``regime_state: str``. It is a ``Literal`` here
    — the classifier's own :data:`~macro_engine.models.regime.RegimeState`,
    **imported rather than re-typed** — so a value outside the declared
    vocabulary is refused at construction rather than falling through a mapping's
    ``.get`` into the generic fallback. This is the ``intervention_capacity``
    direction-field correction (D-118) applied to Module 11: an unrecognised
    value must produce an error, never a confident answer about the wrong regime.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    regime_state: RegimeState = Field(
        description=(
            "The macro regime label, as produced by "
            "`classify_regime_rule_based()` / `classify_regime_markov_switching()` "
            "in `models/regime.py`. Typed as the classifier's `RegimeState` "
            "Literal so a typo or an out-of-vocabulary value is refused, not "
            "defaulted."
        )
    )


def sector_rotation_prior(inputs: SectorRotationInputs) -> ModelResult:
    """The base-rate sector posture for a macro regime.

    A pure lookup over :data:`SECTOR_ROTATION_PRIOR`, plus the confidence and the
    mandatory prior-not-rule caveat. It reads no price and estimates nothing.

    The published ``value`` is a ``list[str]`` of sectors on **every** path —
    the mapped sectors when the regime is known, and the single-element generic
    label from ``equity_macro.no_prior_label`` when it is a declared state with
    no defined rotation. It is a list rather than a possibly-empty one so a
    consumer never has to branch on the container's shape.

    **A regime value outside the classifier's vocabulary cannot reach this
    function** — :class:`SectorRotationInputs` types the field as the
    classifier's ``Literal`` and Pydantic refuses anything else. So the fallback
    here is reachable only for a *declared* regime state that has no row, which
    — since the map is exhaustive over ``REGIME_STATES`` — today means: never,
    unless the classifier's vocabulary grows and the map is not extended. The
    test that pins the exhaustiveness is what makes that "never" true, and the
    fallback is kept as the honest response if it ever stops being true.
    """
    settings = get_settings()
    equity_macro = settings.equity_macro

    regime = inputs.regime_state
    sectors = SECTOR_ROTATION_PRIOR.get(regime)
    has_prior = sectors is not None
    published: list[str] = list(sectors) if sectors is not None else [equity_macro.no_prior_label]

    # --- confidence: two producers, both load-bearing ------------------------
    # The input-quality half is computed from facts about THIS run: whether the
    # regime is one the map actually covers (a covered regime is a real input;
    # an uncovered one means the input is a state the model has no prior for),
    # and the leaf's own calibration status. The method's weakness — a base-rate
    # prior with no current-cycle factor — is what the CAP states.
    #
    # ⚠️ THE TWO COMBINE MULTIPLICATIVELY, NOT BY `min()`. `min()` was the first
    # draft's temptation and it is WRONG here for the same reason it was wrong in
    # InterventionSettings: the cap (0.4) and every computed value sit in the same
    # range, so `min()` would publish the smaller on every path and the other
    # factor would never change an output — a computation that is scaffolding,
    # not a model. Multiplying keeps BOTH load-bearing: the cap says how much a
    # base-rate prior is worth, and the computed value says how much THIS run's
    # input is worth relative to a covered one. Both remain visible in the
    # result's confidence and neither can silently become dead code (D-118…
    # D-122).
    computed = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=not has_prior,
            is_heuristic_not_calibrated=not equity_macro.reliability_cap_is_calibrated,
            source_independence_count=1,
            depends_on_unobservable=False,
        )
    )
    confidence = computed * equity_macro.reliability_value

    warnings: list[str] = [
        "This is a historical BASE-RATE PRIOR, not a mechanical rule — every "
        "cycle has idiosyncratic features (starting valuations, policy mix). "
        "Adjust for the current cycle before acting (Module 11.1)."
    ]
    if not has_prior:
        warnings.append(
            f"Regime {regime!r} is a declared classifier state with no defined "
            f"sector prior, so no rotation is applied. The map is exhaustive over "
            f"the classifier's vocabulary; seeing this warning means the "
            f"vocabulary grew without the map being extended."
        )

    assumptions = [
        "The regime label is taken as given; this model does not classify and "
        "does not read the classifier's inputs.",
        "Sector lists are ORDERED most-advantaged-first, following Section 6.9's "
        "own ordering; the order is part of the published value.",
        "The prior is unconditional on starting valuations, which Section 6.9 "
        "and the Module 11 discussion both name as the principal reason a "
        "same-phase cycle can still reward a different sector.",
    ]
    if regime in SECTOR_PRIOR_EXTENSION_REGIMES:
        assumptions.append(
            f"The row for {regime!r} is this build's declaration, NOT Section "
            f"6.9's: the specification's map covers only six of the classifier's "
            f"nine states, and D-037 made {regime!r} reachable."
        )

    return ModelResult(
        model_name="sector_rotation_prior",
        country="us",
        as_of=utc_now(),
        value=published,
        confidence=confidence,
        unit="sector_names",
        direction=None,
        source_family=EvidenceSourceFamily.MANUAL_ASSESSMENT,
        interpretation=(
            f"Base-rate sector prior for '{regime}': {', '.join(published)}"
            if has_prior
            else f"No sector prior defined for regime '{regime}': {published[0]}"
        ),
        context=(
            "This is a historical BASE-RATE PRIOR, not a mechanical rule — every "
            "cycle has idiosyncratic features (Module 11.1)."
        ),
        inputs_used=["regime_state"],
        warnings=warnings,
        assumptions=assumptions,
        data_provenance=[
            "CONSTRUCTED — the sector lists are the specification's declared "
            "priors (Section 6.9) plus three extension rows for classifier states "
            "the specification's map omits; no market data is fetched or read."
        ],
    )


# ===========================================================================
# duration_sensitivity — Section 6.9's second Module 11 function
# ===========================================================================
#
# The equity *duration* channel, stated as an arithmetic sensitivity. A growth
# equity's cash flows sit further out in time than a value equity's, so a move in
# the discount rate hits it harder — the equity analog of a long-duration bond.
# Section 6.9 expresses this as a crude proxy: a growth equity is treated as a
# ~15-year-duration instrument and a value equity as ~5-year, and the price move
# is ``-duration * (rate_change_bp / 10000)``.
#
# ⚠️ THE SPECIFICATION CALLS ITS OWN PROXY ILLUSTRATIVE, AND SO DOES THIS BUILD.
# Section 6.9's inline comment is literally "illustrative, calibrate against real
# data later", and its ``context`` carries "illustrative duration proxy" while its
# ``warnings`` says "Proxy duration is illustrative, not calibrated — refine with
# real sector-level regression, Phase 5+". This is the ONE Module 11 function
# whose output is a NUMBER rather than a label, so the disclosure is not
# decoration: a reader who takes 12.0 (%) as a calibrated forecast has misread the
# model. The two duration leaves are therefore ``uncalibrated_illustrative`` in
# config, and the published result carries the qualification on EVERY path.


class DurationSensitivityInputs(FiniteInputs):
    """A rate move and the equity style it is applied to.

    Section 6.9's signature is ``duration_sensitivity(is_growth: bool,
    rate_change_bp: float)``. Two things are corrected here rather than copied:

    * the ``is_growth`` **boolean** becomes a typed ``Literal``, because a bool
      is a two-valued field whose meaning depends entirely on which way a bare
      ``True`` is read — and Section 6.9 reads it as "growth" while an adjacent
      reader could as easily read ``True`` as "value". Naming the style removes
      the ambiguity (D-029/D-046: an enumerated field is a ``Literal``, and the
      label is what a caller keys on);
    * the **rate move** is validated to a plausible band. A number in basis
      points arrives from a caller (or a scenario), and a typo — ``2500`` for
      ``25``, or a rate level where a change was meant — would be silently
      amplified by the duration multiplier into a headline percentage. The band
      refuses the implausible rather than publishing it (the ``intervention_capacity``
      input-validation class, D-118).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    style: EquityStyle = Field(
        description=(
            "The equity style the rate move is applied to. `growth` is treated as "
            "the long-duration leg, `value` as the short-duration leg (Section "
            "6.9). A named style rather than Section 6.9's bare `is_growth` "
            "boolean: `True` has no meaning without knowing which way the flag "
            "points."
        )
    )
    rate_change_bp: float = Field(
        description=(
            "The discount-rate change in BASIS POINTS. Positive is a rate RISE "
            "(a headwind for a long-duration equity), negative a fall. Kept as "
            "basis points rather than percent so the unit is stated in the field "
            "name, as the specification's own signature does."
        )
    )

    @field_validator("rate_change_bp")
    @classmethod
    def _rate_change_within_the_plausible_band(cls, value: float) -> float:
        """Refuse a rate move outside ``[lo, hi]`` basis points (D-118 class).

        The bounds are config leaves, not literals, because they are a modelling
        judgement (how large a rate move this proxy is meaningful for) rather
        than a fact. A value past the band is almost certainly a unit error — a
        percentage typed where basis points were meant, or a rate level where a
        change was meant — and the duration multiplier would turn it into a
        headline number with no second chance to notice.
        """
        band = get_settings().equity_macro
        low = band.duration_rate_change_min_bp
        high = band.duration_rate_change_max_bp
        if not low <= value <= high:
            raise ValueError(
                f"rate_change_bp is {value}. It must lie in [{low}, {high}] "
                f"basis points. A move outside that band is almost certainly a "
                f"unit error (percent where bp were meant, or a level where a "
                f"change was meant), and the duration multiplier would publish it "
                f"as a headline percentage move."
            )
        return value


def duration_sensitivity(inputs: DurationSensitivityInputs) -> ModelResult:
    """The illustrative price impact of a rate move on a growth or value equity.

    ``est_pct_move = -proxy_duration * (rate_change_bp / 10000)`` — Section 6.9's
    formula, with the two durations read from config rather than inlined.

    The sign is the model: a rate RISE (positive ``rate_change_bp``) is a
    **negative** price impact, because a higher discount rate lowers the present
    value of the equity's cash flows, and the longer the duration the larger the
    fall. A growth equity (``proxy_duration`` 15) therefore falls roughly three
    times as far as a value equity (``proxy_duration`` 5) for the same move —
    which is the whole content of the growth-vs-value duration trade
    (``AGENTS.md:2198``).

    The published ``value`` is the estimated percentage price move, rounded to
    two decimals. It is **illustrative, not a calibrated regression** — the
    specification says so, the config leaves are marked
    ``uncalibrated_illustrative``, and the result carries the qualification in
    ``context`` and ``warnings`` on every path.
    """
    settings = get_settings()
    equity_macro = settings.equity_macro

    style = inputs.style
    is_growth = style == "growth"
    proxy_duration = (
        equity_macro.duration_growth_proxy_years
        if is_growth
        else equity_macro.duration_value_proxy_years
    )

    est_pct_move = -proxy_duration * (inputs.rate_change_bp / 10000.0)
    published = round(est_pct_move * 100.0, 2)

    # --- confidence: two producers, both load-bearing ------------------------
    # The computed half prices THIS run's input quality: the proxy durations are
    # an uncalibrated illustrative pair (so the heuristic penalty applies while
    # the leaves say so), and the estimate rests on a single declared method with
    # no independent corroboration (source_independence_count=1). It does NOT
    # depend on an unobservable: a rate move and a duration proxy are both stated
    # numbers.
    #
    # ⚠️ THE TWO COMBINE MULTIPLICATIVELY, NOT BY `min()` — the D-118 defect,
    # restated for the third time in this module. The cap and every computed
    # value sit in the same [0, 1] range, so `min()` would publish the smaller on
    # every path and one factor would never change an output. The cap states how
    # much a crude duration proxy is worth as a class; the computed half states
    # how much THIS estimate's inputs are worth. Both stay visible, neither
    # becomes dead code.
    computed = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=not equity_macro.duration_proxy_is_calibrated,
            source_independence_count=1,
            depends_on_unobservable=False,
        )
    )
    confidence = computed * equity_macro.duration_reliability_value

    return ModelResult(
        model_name="duration_sensitivity",
        country="us",
        as_of=utc_now(),
        value=published,
        confidence=confidence,
        unit="percent_price_change",
        direction=(
            "down" if inputs.rate_change_bp > 0 else "up" if inputs.rate_change_bp < 0 else None
        ),
        source_family=EvidenceSourceFamily.MANUAL_ASSESSMENT,
        interpretation=(
            f"Illustrative price impact of a {inputs.rate_change_bp:+.0f}bp rate "
            f"move on a {style} equity: {est_pct_move * 100:+.2f}%"
        ),
        context=(
            f"Illustrative duration proxy ({style} = {proxy_duration}yr): a growth "
            f"equity is treated as a long-duration instrument, a value equity as a "
            f"short-duration one. This is the discount-rate channel only — a crude "
            f"proxy, NOT a calibrated sector-level regression (Module 11.1)."
        ),
        inputs_used=["style", "rate_change_bp"],
        warnings=[
            "Proxy duration is ILLUSTRATIVE, not calibrated — refine with a real "
            "sector-level regression, Phase 5+. Do NOT read this as a forecast.",
            "This models the DISCOUNT-RATE channel only; earnings, composition and "
            "a style's own rate sensitivity change the realised move, and the proxy "
            "says nothing about them.",
        ],
        assumptions=[
            "A growth equity is approximated as a 15-year-duration instrument and a "
            "value equity as a 5-year-duration one; both leaves are "
            "`uncalibrated_illustrative` and the values are Section 6.9's own.",
            "The rate move is applied as a parallel shift of the discount rate; the "
            "curve's shape and its change are not modelled.",
            "The proxy is linear in the rate move — no convexity term — which is "
            "adequate only for the modest moves the input band admits.",
        ],
        data_provenance=[
            "CONSTRUCTED — the price move is computed from a stated rate move and "
            "the specification's illustrative duration proxies (Section 6.9); no "
            "market data is fetched or read."
        ],
    )


# ===========================================================================
# factor_tilt_prior — Section 20.20's part E (the module's third function)
# ===========================================================================
#
# The style-factor analog of the sector prior: five factors (value, momentum,
# quality, low-vol, size), each tilted in [-1, +1] per regime, from a base rate.
# Section 20.20-E's header literally reads
# ``# src/macro_engine/models/equity_macro.py (addition)`` and its table is
# exhaustive over the nine regimes — so, unlike Section 6.9's six-key sector map,
# THIS reference map has no coverage hole to close. What it does have is a bare
# ``confidence=0.35`` (Section 22.8) and a ``regime_state: str`` signature whose
# ``.get`` silently absorbs a typo, both corrected here the same way the first
# function's were.
#
# ⚠️ THE SPECIFICATION'S OWN TABLE IS KEPT VERBATIM. Every value in the map below
# is Section 20.20-E's, in its own order; the map is the specification's declared
# prior, not this build's invention. The header comment records that so a future
# edit cannot mistake an invented row for a specified one.

#: The five style factors Section 20.20-E's table tilts, in its own order.
#:
#: ``low_vol`` is the specification's own key (not ``low_volatility``) — kept
#: verbatim so the published dict matches the table a reader can check it against.
FACTOR_NAMES: tuple[str, ...] = ("value", "momentum", "quality", "low_vol", "size")

#: The regime-conditional factor tilts (-1 underweight .. +1 overweight).
#:
#: Verbatim from Section 20.20-E (``AGENTS.md:3094``). Every value is the
#: specification's; **every** member of ``REGIME_STATES`` has a row (asserted by a
#: test), so — unlike Section 6.9's six-key sector map — the reference table has
#: no coverage hole and no extension rows are added. The tilts are BASE-RATE
#: PRIORS from historical regime behaviour, NOT mechanical rules (Module 11.2).
FACTOR_REGIME_MAP: dict[str, dict[str, float]] = {
    "early_expansion": {
        "value": 1.0,
        "momentum": 0.5,
        "quality": -0.5,
        "low_vol": -1.0,
        "size": 0.5,
    },
    "mid_expansion": {"value": 0.0, "momentum": 1.0, "quality": 0.0, "low_vol": -0.5, "size": 0.0},
    "late_expansion": {
        "value": 0.5,
        "momentum": 0.5,
        "quality": 0.5,
        "low_vol": 0.5,
        "size": -0.5,
    },
    "slowdown": {"value": -0.5, "momentum": -0.5, "quality": 1.0, "low_vol": 1.0, "size": -1.0},
    "recession": {"value": -0.5, "momentum": -1.0, "quality": 1.0, "low_vol": 1.0, "size": -1.0},
    "recovery": {"value": 1.0, "momentum": 0.0, "quality": -0.5, "low_vol": -1.0, "size": 1.0},
    "disinflation": {
        "value": 0.0,
        "momentum": 0.5,
        "quality": 0.5,
        "low_vol": 0.0,
        "size": 0.0,
    },
    "reflation": {"value": 1.0, "momentum": 0.5, "quality": -0.5, "low_vol": -0.5, "size": 0.5},
    "stagflation": {"value": 0.5, "momentum": -0.5, "quality": 1.0, "low_vol": 0.5, "size": -1.0},
}


class FactorTiltInputs(BaseModel):
    """The single input: a regime label from the classifier.

    Section 20.20-E's signature is ``factor_tilt_prior(regime_state: str)``. As
    with :class:`SectorRotationInputs`, the field is the classifier's own
    :data:`~macro_engine.models.regime.RegimeState` ``Literal`` — **imported, not
    re-typed** (D-046) — so a value outside the declared vocabulary is refused at
    construction rather than falling through the map's ``.get`` into the
    "unknown regime" branch. A caller who passes ``"recesion"`` for
    ``factor_tilt_prior`` and ``sector_rotation_prior`` alike must get an error,
    never a confident answer about the wrong regime (D-118's class).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    regime_state: RegimeState = Field(
        description=(
            "The macro regime label, as produced by "
            "`classify_regime_rule_based()` / `classify_regime_markov_switching()` "
            "in `models/regime.py`. Typed as the classifier's `RegimeState` "
            "Literal so a typo or an out-of-vocabulary value is refused, not "
            "defaulted."
        )
    )


def factor_tilt_prior(inputs: FactorTiltInputs) -> ModelResult:
    """The base-rate style-factor tilts for a macro regime.

    A pure lookup over :data:`FACTOR_REGIME_MAP` — five factors, each in
    ``[-1, +1]`` (``+1`` overweight, ``-1`` underweight) — plus the confidence
    and the mandatory prior-not-rule caveat, with the specification's extra
    warning about momentum.

    The published ``value`` is a ``dict[str, float]`` on **every** path: the five
    tilts when the regime is known, and an empty dict when it is a declared state
    the map does not cover. The two maps are keyed on the same vocabulary, so the
    fallback is reachable today only if the classifier's vocabulary grows — the
    test that pins exhaustiveness is what keeps that true.

    **The caveat is the specification's own, and it is the sharpest of the three
    functions.** Section 20.20-E's ``warnings`` says momentum tilts are *"least
    reliable precisely at regime turns (momentum crashes) — the moment this prior
    matters most is when it's weakest"*. A caller who reads a ``-1.0`` momentum
    tilt as an instruction has misread the model in the one place the
    specification explicitly warns against; the output carries that warning on
    every path.
    """
    settings = get_settings()
    equity_macro = settings.equity_macro

    regime = inputs.regime_state
    tilts = FACTOR_REGIME_MAP.get(regime)
    has_prior = tilts is not None
    published: dict[str, float] = dict(tilts) if tilts is not None else {}

    # --- confidence: two producers, both load-bearing ------------------------
    # The computed half prices THIS run's input quality: whether the regime is one
    # the map covers (an uncovered regime is an input the model has no prior for),
    # and the leaf's own calibration status. The method's weakness — a base-rate
    # prior with no current-cycle factor — is what the CAP states.
    #
    # ⚠️ THE TWO COMBINE MULTIPLICATIVELY, NOT BY `min()` — the D-118 defect,
    # restated. Both factors sit in [0, 1], so `min()` would publish the smaller
    # on every path and the other would never change an output: scaffolding, not a
    # model. Multiplying keeps both load-bearing and neither dead.
    computed = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=not has_prior,
            is_heuristic_not_calibrated=not equity_macro.factor_tilt_reliability_cap_is_calibrated,
            source_independence_count=1,
            depends_on_unobservable=False,
        )
    )
    confidence = computed * equity_macro.factor_tilt_reliability_value

    warnings: list[str] = [
        "Base-rate priors from historical regime behaviour — NOT mechanical rules (Module 11.2).",
        "Momentum tilts are LEAST reliable precisely at regime turns (momentum "
        "crashes) — the moment this prior matters most is when it is weakest "
        "(Section 20.20-E).",
    ]
    if not has_prior:
        warnings.append(
            f"Regime {regime!r} is a declared classifier state with no defined "
            f"factor prior, so no tilt is applied. The map is exhaustive over the "
            f"classifier's vocabulary; seeing this warning means the vocabulary "
            f"grew without the map being extended."
        )

    assumptions = [
        "The regime label is taken as given; this model does not classify and does "
        "not read the classifier's inputs.",
        "The published tilts are Section 20.20-E's table verbatim; the five factors "
        "are the specification's own set and the key `low_vol` is its own spelling.",
        "The tilts are unconditional on starting valuations and on crowding, which "
        "is the principal reason a prior can fail in a same-phase cycle.",
    ]

    return ModelResult(
        model_name="factor_tilt_prior",
        country="us",
        as_of=utc_now(),
        value=published,
        confidence=confidence,
        unit="tilt_minus1_to_plus1",
        direction=None,
        source_family=EvidenceSourceFamily.MANUAL_ASSESSMENT,
        interpretation=(
            f"Factor tilts for '{regime}': "
            + ", ".join(f"{name} {published[name]:+.1f}" for name in FACTOR_NAMES)
            if has_prior
            else f"No factor prior defined for regime '{regime}'"
        ),
        context=(
            "Base-rate priors from historical regime behaviour — NOT mechanical "
            "rules (Module 11.2). +1 overweight, -1 underweight."
        ),
        inputs_used=["regime_state"],
        warnings=warnings,
        assumptions=assumptions,
        data_provenance=[
            "CONSTRUCTED — the tilts are the specification's declared table "
            "(Section 20.20-E); no market data is fetched or read."
        ],
    )


# A module-level assertion that the imported vocabulary is what this module
# believes it is. `REGIME_STATES` is the iterable form of the `RegimeState`
# Literal (Pydantic's Literal is not iterable through `typing` at runtime), so
# the two are the same set by construction in `regime.py`; this checks the
# IMPORT rather than re-deriving it, so a future re-export change fails loudly
# here instead of silently shrinking the maps' asserted domain.
assert set(get_args(RegimeState)) == set(REGIME_STATES), (
    "The sector-rotation and factor-tilt maps key on the classifier's "
    "vocabulary; RegimeState and REGIME_STATES must be the same set (see "
    "models/regime.py)."
)

# Both regime-keyed maps must be exhaustive over the classifier's vocabulary.
# `sector_rotation_prior` closes a hole Section 6.9's six-key map leaves;
# `factor_tilt_prior` completes a table Section 20.20-E already made exhaustive.
# Asserting it here means a classifier vocabulary change fails at IMPORT, before
# any caller can receive a silent fallback — the same D-037 shape, guarded at the
# module boundary as well as by the tests.
assert set(FACTOR_REGIME_MAP) == set(REGIME_STATES), (
    "factor_tilt_prior keys on the classifier's vocabulary; FACTOR_REGIME_MAP "
    "must be exhaustive over REGIME_STATES (see models/regime.py)."
)
assert all(set(row) == set(FACTOR_NAMES) for row in FACTOR_REGIME_MAP.values()), (
    "every FACTOR_REGIME_MAP row must tilt exactly the five FACTOR_NAMES."
)
