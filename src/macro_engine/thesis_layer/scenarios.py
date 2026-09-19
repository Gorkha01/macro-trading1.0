"""Module 12 — the explicit scenario set (Section 16.4 Q10, D-064).

``build_scenario_distribution`` turns a ``MarketPricingGap`` and a convergence
verdict into the four-branch outcome distribution that
``MacroThesis.scenario_distribution`` carries and ``apply_fractional_kelly``
sizes over.

Four defects in Section 16.4's sample, all measured before any code was written
------------------------------------------------------------------------------

**1. Two branches for a five-member vocabulary.** The sample's probability
mapping is

    base_prob = 0.55 if convergence == "HIGH" else 0.45 if convergence == "MEDIUM" else 0.30

so ``LOW``, ``CONFLICTED`` and ``NO_SIGNAL`` **all** fall into the ``else`` and
each receives a full, tradeable four-scenario distribution. But
``MacroThesis`` **hard-blocks** a live trade on ``CONFLICTED`` (Section 22.10 /
Finding #10: *"must block trade construction"*, not advisory), and ``NO_SIGNAL``
means every pillar read neutral — there is no thesis to distribute over. The
producer was emitting a distribution for two states its own consumer refuses.

**2. `convergence: str` is a bare string.** ``"high"`` and ``"High"`` both fall
into the ``else`` and silently become ``0.30``, which is D-029's enumerated-field
rule: a closed vocabulary typed as ``str`` lets a typo through a branch nobody
tests. The parameter is typed ``ConvergenceClassification`` here.

**3. `ScenarioOutcome` was declared twice, and the two were incompatible.** The
sample builds ``thesis_layer.schemas.ScenarioOutcome`` (fields ``scenario_name``,
``unit``, ``description``); ``apply_fractional_kelly`` consumes
``models.probability.ScenarioOutcome`` (field ``name``). Passing one to the other
raises ``Input should be a valid dictionary or instance of ScenarioOutcome`` — a
message naming a class **both objects claim to be**. D-057 recorded it as
**O-51**; this increment closes it, because a producer that cannot hand its
output to its own consumer is not a producer. See
``models/probability.py`` for the single definition and
``thesis_layer/schemas.py`` for the re-export.

**4. `gap.unit` is never read.** The sample computes ``abs(gap.raw_gap) * 100``
unconditionally. ``MarketPricingGap.unit`` is a bare ``str`` defaulting to
``"%"``, so a caller who supplies an already-basis-point gap is scaled by 100
**silently** — the same percent/basis-point class as D-054's 100x ladder error.
The unit is read and an unconvertible one is **refused**.

What this function will not do
------------------------------
**It will not produce a distribution for a thesis that cannot exist.** Three
states are distinguished, and the distinction is the contract:

======================  ==========================================
state                   behaviour
======================  ==========================================
``CONFLICTED``          ``[]`` — a legitimate no-trade; ``MacroThesis``
``NO_SIGNAL``           refuses a live trade on both, and an empty
                        distribution is schema-valid
``not gap.is_meaningful``  **raises** — Section 16.2's Q6 routes this to
                        ``no_trade_thesis`` *before* Q10, so reaching
                        here means the caller skipped it
``gap.unit`` unknown    **raises** — a unit this function cannot
                        convert is a unit it must not guess
======================  ==========================================

**The probabilities are illustrative, not estimated.** Section 16.4 says so and
every leaf is ``uncalibrated_illustrative`` in config. The function's output
carries that in its ``unit`` and its branch names, and the distributions are
**not Kelly-sizable**: ``apply_fractional_kelly`` accepts only
``fraction_of_capital`` and raises on ``bp_pnl_proxy``, which is D-057's
deliberate design (O-50) rather than a gap here.

**The distribution is DIRECTION-BLIND, and that is a measured boundary rather
than an oversight (D-064).** The magnitude is ``abs(gap.raw_gap)`` and
``gap.direction`` is never read, so a **+1%** gap and a **-1%** gap produce
byte-identical payoffs *and* identical probabilities — the whole distribution is
a function of ``|raw_gap|`` and the verdict. A branch named
``thesis_invalidated_reversal`` paying -60bp reads as a loss for a **long**
position, but it is the loss for a **short** only once the sign of the trade is
known, and the trade is not an input.

This was found by D-064's **live check**, which is the point worth keeping: every
fixture in the test file uses a **positive** gap, and the live canonical gap
happened to be **negative** (the model below the market, a tightening bias). A
suite written entirely on one sign cannot see a sign-independence defect — the
same shape as D-063's direction-blind model and D-062's golden case that was
exact by construction. The sign remains reachable on ``gap.direction``; a
consumer that needs it must read the gap, and the omission is pinned by
``test_the_distribution_is_direction_blind`` rather than left to be rediscovered.
"""

from __future__ import annotations

from macro_engine.config import get_settings
from macro_engine.models.probability import ScenarioOutcome
from macro_engine.thesis_layer.schemas import (
    ConvergenceClassification,
    MarketPricingGap,
)

__all__ = [
    "build_scenario_distribution",
]

#: The four branches, in the order they are published. Order is load-bearing for
#: a reader — base case first, adverse tail last — and the names are the keys the
#: config's ``payoff_multiples`` and ``remaining_shares`` use, so a rename in one
#: place fails loudly in the other.
_BASE = "base_case_gap_closes_as_modeled"
_PARTIAL = "gap_partially_closes"
_REVERSAL = "thesis_invalidated_reversal"
_TAIL = "tail_adverse_surprise"

#: The convergence verdicts that produce a distribution at all. A **partition** of
#: the five-member vocabulary, not a fall-through: the other two are named
#: explicitly in the module docstring and return an empty list.
_DISTRIBUTABLE: frozenset[ConvergenceClassification] = frozenset(
    {
        ConvergenceClassification.HIGH,
        ConvergenceClassification.MEDIUM,
        ConvergenceClassification.LOW,
    }
)

#: The gap units this function can convert to a basis-point payoff. One member,
#: because one conversion factor is configured: a second unit would need its own,
#: and refusing is cheaper than guessing (D-057's ``payoff_unit`` pattern).
_CONVERTIBLE_GAP_UNITS: frozenset[str] = frozenset({"%"})


def build_scenario_distribution(
    gap: MarketPricingGap, convergence: ConvergenceClassification
) -> list[ScenarioOutcome]:
    """The four-branch outcome distribution for a thesis (Section 16.4 Q10).

    The probabilities and payoff multiples come from
    ``scenario_distribution`` in config; the gap supplies the scale. Returns an
    **empty list** for a convergence verdict that cannot carry a thesis, so the
    caller's ``MacroThesis`` is schema-valid with no scenarios rather than
    carrying a distribution for a trade that must not exist.
    """
    settings = get_settings().scenario_distribution

    # Parse at the boundary. The parameter is typed ``ConvergenceClassification``
    # so ``mypy --strict`` catches a typo at the call site, but the annotation is
    # not a runtime guard — and the runtime behaviour without this line is worse
    # than an error: ``ConvergenceClassification`` inherits from ``str``, so a
    # bare ``"HIGH"`` has the same hash as the member, passes the membership test
    # below, and then dies on ``.value`` with
    # ``AttributeError: 'str' object has no attribute 'value'``. Parsing turns
    # both cases into one: a valid spelling works, a typo raises.
    verdict = ConvergenceClassification(convergence)

    if verdict not in _DISTRIBUTABLE:
        return []

    if gap.unit not in _CONVERTIBLE_GAP_UNITS:
        raise ValueError(
            f"gap.unit is {gap.unit!r}, which this function cannot convert to a "
            f"basis-point payoff. The configured factor is "
            f"{settings.bp_per_percent:g} bp per percent, so only "
            f"{sorted(_CONVERTIBLE_GAP_UNITS)} is accepted. A gap in unknown "
            f"units must be refused rather than scaled: the percent/basis-point "
            f"confusion is a silent 100x error (Section 16.4's sample multiplies "
            f"by 100 unconditionally)."
        )

    if not gap.is_meaningful:
        raise ValueError(
            f"gap.is_meaningful is False (raw_gap={gap.raw_gap!r}, "
            f"dispersion={gap.dispersion!r}). Section 16.2's Q6 routes a "
            f"gap inside the policy rules' own dispersion to no_trade_thesis() "
            f"BEFORE Q10, because a distribution over a sub-noise-floor gap is the "
            f"false-confidence failure Module 12.2 exists to prevent. Reaching this "
            f"function with such a gap means the caller skipped Q6."
        )

    magnitude_bp = abs(gap.raw_gap) * settings.bp_per_percent
    if magnitude_bp == 0.0:
        raise ValueError(
            "raw_gap is exactly zero, so every branch would pay zero and the "
            "distribution would be degenerate — four outcomes that differ only in "
            "their probabilities. is_meaningful is a caller-set field rather than a "
            "derived one, so this is reachable and is refused explicitly."
        )

    base = settings.base_probabilities[verdict.value]
    remaining = 1.0 - base
    shares = settings.remaining_shares
    multiples = settings.payoff_multiples

    return [
        ScenarioOutcome(
            name=_BASE,
            probability=base,
            payoff_estimate=magnitude_bp * multiples[_BASE],
            unit="bp_pnl_proxy",
            description="The mispricing closes as the model expects.",
        ),
        ScenarioOutcome(
            name=_PARTIAL,
            probability=remaining * shares[_PARTIAL],
            payoff_estimate=magnitude_bp * multiples[_PARTIAL],
            unit="bp_pnl_proxy",
            description="Part of the mispricing closes; the thesis is partly right.",
        ),
        ScenarioOutcome(
            name=_REVERSAL,
            probability=remaining * shares[_REVERSAL],
            payoff_estimate=magnitude_bp * multiples[_REVERSAL],
            unit="bp_pnl_proxy",
            description="The thesis is invalidated and the gap moves against it.",
        ),
        ScenarioOutcome(
            name=_TAIL,
            probability=remaining * shares[_TAIL],
            payoff_estimate=magnitude_bp * multiples[_TAIL],
            unit="bp_pnl_proxy",
            description=(
                "Adverse tail: the gap moves against the position by MORE than the "
                "whole mispricing. Positive expected value says nothing about "
                "surviving this branch (Module 12.4, LTCM 1998)."
            ),
        ),
    ]
