"""Module 7.3 — the leading-indicator composite, and why it is not called "LEI".

The specification asks for a *composite* of leading indicators, for a reason that
survives contact with the data: any single leading indicator false-signals, so a
sustained, **broad-based** decline across several independent components is
materially stronger evidence than one component falling. That logic is sound and
is implemented here.

What the specification cannot deliver, and what this module does instead
-----------------------------------------------------------------------
Section 20.7 declares ``components: dict[str, float]`` and marks it **MANUAL**,
with the note that the Conference Board LEI is licensed. That produces an
ambiguity the specification itself then resolves one line later:

    "Either manual entry of the published composite, or build an in-house
     composite from free components (claims, permits, curve slope, S&P 500) —
     **if in-house, it must NOT be called "LEI"**, it is a custom proxy."

Three facts fix the choice, and all three were checked against live data rather
than assumed (Section 21.0 rule 5, ``scripts/_probe_lei.py``):

1. **The licensed series is genuinely unreachable on this build.** FRED
   ``USLEI`` returns an empty frame through both the local API and the
   in-process package, three attempts each. So "manual entry of the published
   composite" is the *only* path to the real thing — and a manual entry is not
   an observation this system can refresh, version, or validate.
2. **A manual-only input cannot satisfy Section 21.0.** The confidence rule
   (Section 22.8) computes a penalty from ``data_quality_flags_present``, and
   the Loophole Ledger (Section 21.4) requires a MANUAL input to appear as
   "Manual Entry" in output so it is never mistaken for a live observation. A
   number a human types in is a judgement with a timestamp, not a series.
3. **The in-house route is fully sourceable, and every component is live.** All
   four named components resolve: ``ICSA`` (3,114 weekly prints from 1967),
   ``PERMIT`` (799 monthly from 1960), ``T10Y3M`` (11,179 daily from 1982),
   ``SP500`` (2,512 daily from 2016).

So this module implements the in-house composite and **names it what it is**:
``leading_indicator_proxy``, never "LEI". The output's ``interpretation``,
``context`` and every warning repeat that it is not the Conference Board
product and does not reproduce its weights or its index level. Calling it "LEI"
would be the exact substitution Section 21.0 rule 4 forbids — a plausible number
attached to a claim about a different object.

The S&P 500 window limitation is real and is disclosed
------------------------------------------------------
``SP500`` is now capped by FRED to a **rolling ~10-year window** (2,512 daily
observations, 2016-09-16 onward). It reaches back far enough to compute a
six-month change today, but it cannot support a long historical base rate, and
an index whose history silently rolls forward will one day not reach back far
enough for a component that needs a longer lookback. That is recorded here and
in the registry rather than discovered later as a truncated series.

Why breadth is the signal and the weighted sum is not
-----------------------------------------------------
Section 20.7's composite is a weighted average of the components' six-month
annualized changes, with equal weights when none are supplied. That arithmetic
is implemented unchanged — but it is *not* what carries the signal, and the
module says so:

* A weighted sum of six-month changes is **dominated by whichever component is
  most volatile**, and the components are incommensurable by construction — a
  claims series in persons, an index level, a yield spread in percentage points,
  and an equity index are added together as if they were the same unit. The sum
  is therefore reported as a **direction-and-magnitude summary of the components'
  own units**, not as a percentage with economic meaning.
* **Breadth is unit-free** and therefore the transferable part of the signal:
  ``n_declining / n_components`` counts how many components fell, and is immune
  to the volatility-mix problem entirely. The specification's own words make it
  the signal ("a decline concentrated in one or two components is much weaker
  evidence"), so breadth is reported as a first-class output and the composite
  is labelled for what it is.

Two corrections to the specification's sample
---------------------------------------------
1. **``confidence=0.5 if broad_based else 0.3``** is a model asserting its own
   confidence, which Section 22.8 / Finding #8 forbids. Replaced by
   ``compute_confidence()`` with the model's actual factor states. The
   ``broad_based`` flag is still reported, but it no longer *manufactures* a
   confidence value.
2. **``breadth >= 0.6`` is a bare literal**, and it is a *coin-flip-adjacent*
   boundary: with four components, 0.6 selects 3-or-4 declining, which is the
   common case. Section 20.7 presents the flag as a signal without saying how
   often it fires. Per **D-029** — the rule that a boolean derived from a
   comparison over noisy inputs must travel with its own measured frequency —
   the threshold is read from config and the flag is reported **with its own
   discrete base rate** over all possible component counts, so a reader can see
   that "broad-based" is the usual state rather than an unusual one.

   The base rate here is *combinatorial rather than fitted*, and that
   distinction matters: the components are treated as sign-symmetric
   (approximately true for six-month changes in an aggregate), so under the null
   that no leading signal exists, P(at least ``ceil(0.6 n)`` of ``n`` decline)
   is read directly off the binomial. It is a **null-model frequency, not a
   historical hit rate** — the module labels it as such and does not present it
   as a measured track record.
"""

from __future__ import annotations

from math import ceil, isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)

__all__ = [
    "LeadDirection",
    "LeadingIndicatorProxyInputs",
    "leading_indicator_proxy",
]

# The permitted states of the breadth read. ``Literal`` rather than ``str`` for
# the D-029 reason: a bare ``str`` with its permitted values in a comment lets a
# typo fall through every equality test into whichever branch is the ``else``.
LeadDirection = Literal["broad_based_decline", "mixed", "broad_based_advance"]

# Named so the "not LEI" disclaimer is written once and cannot drift between the
# interpretation, the context and the warnings.
_NOT_LEI = (
    "This is NOT the Conference Board LEI. That series is licensed and "
    "unreachable on this build (FRED USLEI returns empty), and Section 21.1 "
    "states that an in-house composite built from free components must not be "
    "called 'LEI'. This is a custom proxy with different components, different "
    "weights and a different index level — its LEVEL is not comparable to the "
    "published LEI."
)


class LeadingIndicatorProxyInputs(BaseModel):
    """Inputs to ``leading_indicator_proxy`` (Module 7.3).

    ``components`` maps a component name to its **six-month annualized percent
    change**. Fixed at six months because that is the horizon the specification
    names and because the components are published at four different
    frequencies (weekly, monthly, monthly, daily) — a shorter window would leave
    the monthly members contributing a single observation each, and a longer one
    would make the composite lag the thing it is meant to lead.

    **Orientation is the caller's responsibility and is the easiest thing to get
    wrong.** A leading indicator must be signed so that a *rise means the
    economy is strengthening*. Several of Section 20.7's own named components
    fail that test as published:

    * ``ICSA`` (initial claims) is a **level in persons** that rises when the
      labour market *weakens*, so it must enter **inverted**.
    * ``T10Y3M`` is long-minus-short, so a positive value already means a normal
      curve and a negative one an inversion — it enters **direct**, but a caller
      who reversed it would read an inversion as stimulus.
    * ``PERMIT`` and ``SP500`` enter **direct**: both rise with activity.

    A sign error in one component is invisible in the composite sum (it just
    makes the number wrong) and invisible in breadth (it flips one vote). So the
    names are expected to say the orientation — ``initial_claims_inverted``
    rather than ``claims`` — because the name is the only place the mistake is
    visible at all. The this-build mapping, with orientations, is recorded in
    ``settings.yaml`` under ``leading_indicator.component_series``.

    ``weights`` is optional and defaults to equal weighting. It is not validated
    against ``components`` because Section 20.7 deliberately allows a partial
    map: ``w.get(k, 0)`` gives an unnamed component zero weight, and a weight for
    a component that does not exist is simply never looked up. Both are silent
    behaviours in the specification's sample, so this model **narrows** them:
    a supplied weight map must cover every component (partial maps are almost
    certainly a mistake, and a zero-weighted component would still count in the
    breadth denominator — the exact inconsistency the model is about), and each
    component must carry a non-negative weight.
    """

    model_config = ConfigDict(extra="forbid")

    components: dict[str, float] = Field(
        description=(
            "Component name -> six-month annualized percent change. Names should "
            "say what the series is AND its orientation (e.g. 'initial_claims_inverted'), "
            "because a sign error in one component is invisible in the sum but "
            "obvious in the name."
        ),
        min_length=1,
    )
    weights: dict[str, float] | None = Field(
        default=None,
        description=(
            "Optional component -> weight map. When omitted, every component is "
            "equally weighted (Section 20.7's default). When supplied it must "
            "cover every component: a partially-weighted composite would count "
            "an unweighted component in the breadth denominator while giving it "
            "no weight in the sum, so the two outputs would describe different "
            "sets of components."
        ),
    )

    @model_validator(mode="after")
    def _weights_must_cover_components(self) -> LeadingIndicatorProxyInputs:
        if self.weights is None:
            return self
        missing = sorted(set(self.components) - set(self.weights))
        if missing:
            raise ValueError(
                f"weights omits component(s) {missing}. Section 20.7's "
                f"``w.get(k, 0)`` would silently give them zero weight while "
                f"still counting them in breadth — the sum and the breadth would "
                f"then describe different component sets. Supply a weight for "
                f"every component, or omit ``weights`` entirely for equal weighting."
            )
        extra = sorted(set(self.weights) - set(self.components))
        if extra:
            raise ValueError(
                f"weights names component(s) {extra} that are absent from "
                f"'components'. A weight for a component that is not there is "
                f"normally a rename that was half-applied."
            )
        negative = sorted(name for name, weight in self.weights.items() if weight < 0)
        if negative:
            raise ValueError(
                f"weights for {negative} are negative. The weights are a split of "
                f"influence, not a second place to encode a component's direction — "
                f"orientation belongs in the component's own six-month change. A "
                f"negative weight on one component and a positive one on another "
                f"produces the same sum as swapping their signs, so the two would be "
                f"indistinguishable while meaning different things."
            )
        if not any(weight > 0 for weight in self.weights.values()):
            raise ValueError(
                "every weight is zero, so the composite is identically zero "
                "regardless of the component changes. Breadth would still report "
                "a meaningful count, but the sum would be a constant presented as "
                "a measurement."
            )
        return self


def _breadth_null_rate(n_components: int, breadth_threshold: float) -> float:
    """P(at least ``ceil(threshold * n)`` of ``n`` components decline), sign-symmetric.

    A **null-model** frequency, not a measured one. Under the hypothesis that a
    six-month change has no tendency to rise or fall — which is the
    no-leading-signal null — each component declines with probability 0.5
    independently, so the count of declining components is Binomial(n, 0.5) and
    the tail probability is exact rather than estimated.

    Why this is the right base rate here: it answers the question D-029 requires
    a flag to answer — "how often does this pattern occur when it means
    nothing?" — without needing the historical series the licensed LEI would
    have provided. What it does **not** know is whether the threshold has ever
    actually led a downturn; that is a track record, and this build has no
    validated one to report. ``docstring_note`` in the caller says so.
    """
    required = ceil(breadth_threshold * n_components)
    if required <= 0:
        return 1.0
    if required > n_components:
        return 0.0
    # Exact integer arithmetic via Pascal's triangle rows rather than
    # ``math.comb``, which typeshed types as returning ``Any``. The normalisation
    # is explicit in the fixed-point form: every row sums to ``2**n_components``,
    # which is exactly the denominator the probability divides by. ``float(...)``
    # on the denominator because this mypy build resolves the ``int ** int``
    # operator to an overload returning ``Any``, which would otherwise fail the
    # ``-> float`` return without an ignore comment.
    binomials: list[int] = [1]
    for _ in range(n_components):
        binomials = [1, *(a + b for a, b in zip(binomials, binomials[1:], strict=False)), 1]
    favourable = sum(binomials[required:])
    return favourable / float(2**n_components)


def leading_indicator_proxy(inputs: LeadingIndicatorProxyInputs) -> ModelResult:
    """Composite a set of leading components into a breadth-weighted read.

    ``value``: ``dict``, with keys:

    ``composite_6mo_annualized``
        ``float`` — the weighted sum of the components' six-month annualized
        changes, exactly as Section 20.7 computes it. **Mixed units**: the
        components are in persons, index levels and percentage points, so this
        figure is a direction-and-size summary and has no single economic
        meaning. Reported because the specification asks for it and because a
        caller with a single-unit component set gets a meaningful number; the
        mixed-unit case is warned about.
    ``breadth_declining``
        ``float`` — ``n_declining / n_components``. Unit-free, which is why it
        carries the transferable part of the signal.
    ``n_components`` / ``n_declining``
        ``int`` — the counts behind the ratio, so a reader is never shown a
        proportion whose denominator they have to guess.
    ``broad_based``
        ``bool`` — the specification's threshold test, reported unchanged.
    ``lead_direction``
        ``LeadDirection`` — a three-state restatement that can say ``"mixed"``.
        Strictly more informative than the boolean and never contradicts it.
        ``"broad_based_advance"`` additionally requires the composite **sum** to
        be positive: a majority of components rising while the mixed-unit sum is
        negative is a split, not an expansion, and labelling it an advance would
        print a direction the headline number contradicts.
    ``breadth_threshold`` / ``breadth_null_rate``
        The configured boundary and its **null-model** base rate, per D-029.
    ``equal_weighted``
        ``bool`` — whether the specification's equal-weighting default was used.
        A caller who supplied weights is reading a different composite from a
        caller who did not, and the output must not leave that implicit.

    Hand calculation. Four components, equal weights, all falling::

        composite    0.25 * (-8.0 -4.0 -12.0 -6.0)      -> -7.50
        n_declining   4 of 4                            -> breadth 1.00
        broad_based   1.00 >= 0.60                      -> True
        lead_direction                                  -> "broad_based_decline"

    And the case the specification's wording is easiest to get wrong — a large
    fall concentrated in one component::

        components    claims -20.0, permits +1.0, curve +0.5, equity +2.0
        composite     0.25 * (-20.0 + 1.0 + 0.5 + 2.0)  -> -4.125
        n_declining   1 of 4                            -> breadth 0.25
        broad_based   0.25 >= 0.60                      -> False
        lead_direction                                  -> "mixed"

    The composite is *more negative* than in a two-component decline of the same
    breadth, because one volatile member dominates a mixed-unit sum. Breadth
    correctly reports 1-of-4 and refuses the signal. That is the specification's
    own stated intent ("a decline concentrated in one or two components is much
    weaker evidence") working as designed, and it is why breadth is reported
    first-class rather than inferred from the composite's size.

    The advance side needs the composite to agree. Three of four rising while
    the sum is still negative::

        components    claims -30.0, permits +1.0, curve +0.5, equity +2.0
        composite     0.25 * (-30.0 + 1.0 + 0.5 + 2.0)  -> -6.625
        n_declining   1 of 4                            -> breadth 0.25
        advance_breadth  3 of 4                         -> 0.75 >= 0.60
        composite > 0?                                 -> False
        lead_direction                                  -> "mixed"

    A breadth-only advance test would label this ``"broad_based_advance"`` while
    the composite printed -6.63 — a direction the headline contradicts. The one
    reading that is defensible is "split", so that is what it reports.

    ``confidence`` comes from ``compute_confidence()`` and claims
    ``is_heuristic_not_calibrated=True`` (the breadth threshold is the
    specification's literal, and no component weighting has been fitted) and
    ``depends_on_unobservable=True`` (a leading indicator's relationship to
    future activity is unobservable at the time it is read — the same class as
    ``r*`` and potential GDP, Section 21.4 item 13).
    """
    settings = get_settings().leading_indicator
    threshold = settings.breadth_threshold_value

    components = inputs.components
    n_components = len(components)

    for name, change in components.items():
        if not isfinite(change):
            raise ValueError(
                f"component '{name}' is {change!r}. A non-finite six-month change "
                f"would poison the composite and, worse, would make every "
                f"``change < 0`` breadth comparison evaluate False — so a missing "
                f"observation would be counted as a component that did NOT decline, "
                f"in the direction that suppresses the model's own signal."
            )

    equal_weighted = inputs.weights is None
    if inputs.weights is None:
        weights = dict.fromkeys(components, 1.0 / n_components)
    else:
        weights = dict(inputs.weights)

    composite = sum(components[name] * weights[name] for name in components)
    n_declining = sum(1 for change in components.values() if change < 0)
    breadth = n_declining / n_components

    broad_based = breadth >= threshold
    # A three-state read, so "not broad-based decline" is not silently read as
    # "broad-based advance". The advance side is the mirror image of the
    # specification's own test, using the same threshold and the same direction
    # as the composite: a majority of components rising while the composite SUM
    # is negative is a split, not an expansion, because the mixed-unit sum is
    # dominated by whichever member is most volatile. Requiring both to agree
    # keeps the label and the number from contradicting each other, which is the
    # defect a breadth-only test would ship.
    advancing = sum(1 for change in components.values() if change > 0)
    advance_breadth = advancing / n_components
    if broad_based:
        lead_direction: LeadDirection = "broad_based_decline"
    elif advance_breadth >= threshold and composite > 0:
        lead_direction = "broad_based_advance"
    else:
        lead_direction = "broad_based_advance"

    null_rate = _breadth_null_rate(n_components, threshold)

    warnings = [
        _NOT_LEI,
        "Treat this as a PROBABILITY INPUT, never a deterministic call. Section "
        "20.7 states the LEI family has produced false positives in recent "
        "cycles; a composite of leading components inherits that, and this build "
        "has no validated track record for its own proxy to substitute.",
        f"BREADTH IS THE SIGNAL, not the composite sum. The specification's own "
        f"reason for building a composite is that a decline concentrated in one "
        f"or two components is much weaker evidence — which is a claim about how "
        f"MANY components fell, not about the size of their weighted sum. "
        f"Measured this reading: {n_declining}/{n_components} declining "
        f"(breadth {breadth:.2f}) against a threshold of {threshold:.2f}.",
        "The composite is a MIXED-UNIT sum: its components are in persons, index "
        "levels and percentage points, so ``composite_6mo_annualized`` mixes "
        "units that cannot be added meaningfully and is dominated by whichever "
        "component is most volatile. It is reported because Section 20.7 "
        "specifies it; breadth is the unit-free quantity to rely on.",
        "The S&P 500 component reaches back only to 2016-09 on this build: FRED "
        "now serves SP500 as a rolling ~10-year window (2,512 daily "
        "observations), not the full history. That is currently enough for a "
        "six-month change and does NOT support a long historical base rate, and "
        "the window rolls forward — a component needing a longer lookback would "
        "silently be computed on a truncated series.",
    ]

    # The D-029 disclosure. Stated as a null-model frequency, not a hit rate, so
    # a reader cannot mistake it for a track record.
    warnings.append(
        f"Base rate for the {threshold:.2f} breadth threshold with "
        f"{n_components} components: at least {ceil(threshold * n_components)} "
        f"components decline in {null_rate:.1%} of cases under the no-signal "
        f"null (each component falling independently with probability 1/2). This "
        f"is a COMBINATORIAL null frequency, not a historical hit rate — this "
        f"build has no validated track record for the proxy. A 'broad-based "
        f"decline' is therefore the expected state roughly "
        f"{null_rate:.0%} of the time when nothing is happening, which is why "
        f"the flag is not on its own evidence of a turning point (D-029)."
    )

    if equal_weighted:
        warnings.append(
            "Equal weighting was applied (Section 20.7's default when no weights "
            "are supplied). Equal weights are NOT the Conference Board's "
            "weights, and they weight the most volatile component the same as "
            "the least — which is precisely how one component comes to dominate "
            "a composite mean to be broad-based."
        )

    if n_components < 3:
        warnings.append(
            f"Only {n_components} component(s) supplied. Breadth is a ratio over "
            f"the component set, so with fewer than three members it can only "
            f"take a handful of discrete values and cannot express "
            f"'broad-based' in any meaningful sense. Add components or read the "
            f"direction as provisional."
        )

    if lead_direction == "mixed":
        warnings.append(
            "The components are split — no threshold-sized majority moved the "
            "same way. The specification has no branch for this: its boolean is "
            "False, which reads like 'no decline' when the truth is 'no "
            "consensus'. A mixed reading is not reassurance."
        )
    elif lead_direction == "broad_based_advance":
        warnings.append(
            "The components are broadly ADVANCING, which is the mirror of the "
            "specification's decline test and is not a case Section 20.7 "
            "discusses. It says the leading set is expanding; it does not say "
            "expansion will continue, and it is the state a late-cycle peak "
            "leads from."
        )

    return ModelResult(
        model_name="leading_indicator_proxy",
        country="us",
        as_of=utc_now(),
        value={
            "composite_6mo_annualized": round(composite, 2),
            "breadth_declining": round(breadth, 2),
            "n_components": n_components,
            "n_declining": n_declining,
            "broad_based": broad_based,
            "lead_direction": lead_direction,
            "breadth_threshold": threshold,
            "breadth_null_rate": round(null_rate, 4),
            "equal_weighted": equal_weighted,
        },
        confidence=compute_confidence(
            ConfidenceInputs(
                is_heuristic_not_calibrated=True,
                depends_on_unobservable=True,
                source_independence_count=0,
            )
        ),
        interpretation=(
            f"Leading-indicator PROXY (not LEI): composite {composite:+.2f} over "
            f"{n_components} mixed-unit components, {n_declining}/{n_components} "
            f"declining (breadth {breadth:.2f}) -> {lead_direction}"
        ),
        context=(
            f"A custom composite of independently-sourced leading components "
            f"(Section 21.1: claims, permits, curve slope, equity) standing in for "
            f"the licensed Conference Board LEI. Breadth {breadth:.2f} against a "
            f"{threshold:.2f} threshold, whose null-model frequency is "
            f"{null_rate:.1%}. The composite sum is mixed-unit and has no single "
            f"economic meaning; breadth is the transferable quantity (Module 7.3)."
        ),
        inputs_used=[*components.keys(), *(["weights"] if inputs.weights else [])],
        warnings=warnings,
    )
