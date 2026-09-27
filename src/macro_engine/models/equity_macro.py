"""Module 11 — Equity Macro: the regime-conditional sector-rotation PRIOR.

Section 6.9 gives Module 11 two functions, and this module begins it with the
first: :func:`sector_rotation_prior`. Module 11 is the equity-macro layer — it
maps a macro **regime label** (Module 3/4's classifier) onto an equity-*sector*
posture. It reads no prices and estimates nothing; it is a **lookup whose domain
is the classifier's own declared vocabulary**.

Supersession (Section 21.3, D-096) — the question this increment answers first
---------------------------------------------------------------------------
**This function supersedes nothing named, and nothing supersedes it.** Phase 5+
is an upgrade pass: most Tier-5 names are REPLACEMENTS for a simpler Phase 0-4
function, and the honest answer here is the ``cip_check`` / ``intervention_capacity``
answer — *a new capability*. Module 11 has **no function at all** in ``src/``
today; ``docs/MODULE_MAPPING.md`` carries no Module 11 row; and the tier table
(``AGENTS.md:1783``) maps Module 11 to ``models/equity_macro.py``, a file that
did not exist before this increment. It shares **no input** with any shipped
model: those read prices, rates, spreads and flows; this reads a single
**regime label**, and its whole content is which sectors a historical base rate
favours in that regime.

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

from typing import get_args

from pydantic import BaseModel, ConfigDict, Field

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    EvidenceSourceFamily,
    ModelResult,
    compute_confidence,
    utc_now,
)
from macro_engine.models.regime import REGIME_STATES, RegimeState

__all__ = [
    "SECTOR_PRIOR_EXTENSION_REGIMES",
    "SECTOR_ROTATION_PRIOR",
    "SPECIFICATION_REGIMES",
    "SectorRotationInputs",
    "sector_rotation_prior",
]

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

    model_config = ConfigDict(extra="forbid")

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


# A module-level assertion that the imported vocabulary is what this module
# believes it is. `REGIME_STATES` is the iterable form of the `RegimeState`
# Literal (Pydantic's Literal is not iterable through `typing` at runtime), so
# the two are the same set by construction in `regime.py`; this checks the
# IMPORT rather than re-deriving it, so a future re-export change fails loudly
# here instead of silently shrinking the map's asserted domain.
assert set(get_args(RegimeState)) == set(REGIME_STATES), (
    "Sector rotation keys on the classifier's vocabulary; RegimeState and "
    "REGIME_STATES must be the same set (see models/regime.py)."
)
