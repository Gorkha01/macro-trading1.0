"""Module 3.5 / 7.2 — potential output, the Cobb-Douglas production function.

``Y = A * K^alpha * L^(1-alpha)``

Four symbols, and three of them cannot be observed
--------------------------------------------------
Section 21.4 item 13 lists r*, u*, potential GDP and TFP together as
**unobservable by nature** — "config estimates only". That sentence covers
almost this entire equation:

* ``A`` — total factor productivity. Not published by anyone. The residual of
  a growth-accounting exercise, which means it absorbs every measurement error
  in ``K`` and ``L`` as well as every genuine efficiency change.
* ``K`` — the capital stock. Published (FRED ``RKNANPUSA666NRUG``,
  BEA fixed-asset tables), but *estimated* rather than counted: it is built by
  perpetual-inventory from investment flows and assumed depreciation, so it
  inherits decades of accumulated assumption.
* ``alpha`` — the capital share. **This one is measurable**, and it is why
  ``config/settings.yaml`` marks it ``conventional`` rather than
  ``uncalibrated_illustrative``: labor's share of income is directly observed
  in the national accounts, so ``alpha`` is arithmetic rather than judgment.
* ``Y`` — potential output. The thing being estimated, and unobservable by
  definition. Nobody has seen it.

So this function multiplies three estimated quantities to produce a fourth, and
the specification's own golden test — ``A=1, K=100, L=100, alpha=0.3`` returns
exactly ``100.0`` — is a test of the *arithmetic*, not of the estimate. That
distinction is the whole module. The test proves the exponent handling is
right; it says nothing about whether any of the inputs resemble the US economy.
A function that presented its output as a measurement would be overstating what
three unobservables multiplied together can support.

Why the specification's ``alpha: float = 0.3`` default is not carried through
-----------------------------------------------------------------------------
The sample declares ``alpha: float = 0.3`` with the comment "capital share",
and ``config/settings.yaml`` already carries ``production_function.alpha`` at
the same value. That is the same defect the Phillips module records: a signature
default is a *second source of truth* with priority over the configured one
whenever a caller omits the argument. A recalibration in config would then move
nothing for those callers, silently.

``alpha`` is therefore read from config and is **not** a field on
``PotentialGDPInputs``. This is the one input in the equation that is genuinely
observable, so it is the one where currency matters most — and a stale copy in a
call site is exactly how it goes stale unnoticed.

Why ``confidence`` is the lowest in the suite
---------------------------------------------
Four penalties apply at once, and there is no independence credit to offset
them: all three inputs descend from the same national-accounts framework, so
they are one source, not three. A model that treats ``A``, ``K`` and ``L`` as
independent confirmations of each other has mistaken one accounting identity for
three observations.

What this module is for, given ``GDPPOT`` exists
------------------------------------------------
Section 21.1 lists FRED ``GDPPOT`` (the CBO estimate) as the **preferred source
for potential GDP**, live and verified. This function is not a competitor to it
and does not supersede it. It exists for two reasons the specification gives
explicitly:

1. **Cross-check.** Section 21.1's own logic — dispersion across independent
   estimates *is* the uncertainty band — applies here. CBO's method is not
   Cobb-Douglas with these inputs; a large divergence between the two is a
   finding about how much the answer depends on method rather than data, which
   is precisely what Section 21.4 item 13 says the band should be built from.
2. **Decomposition.** The term-wise breakdown is not available from a
   published potential-GDP series. This returns the contribution of each factor
   so that ``output_gap``'s single number can be attributed.

Section 21.0 discipline: this function is *estimated*, and every branch that
reports it says so.
"""

from __future__ import annotations

import math

from pydantic import ConfigDict, Field

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    FiniteInputs,
    ModelResult,
    compute_confidence,
    require_finite_scalars,
    utc_now,
)

__all__ = [
    "PotentialGDPInputs",
    "growth_accounting_decomposition",
    "potential_gdp_cobb_douglas",
]


class PotentialGDPInputs(FiniteInputs):
    """The three estimated terms of ``Y = A * K^alpha * L^(1-alpha)``.

    ``alpha`` is deliberately absent — see the module docstring. Every field
    that remains is constrained positive: the equation is a product of powers,
    so a zero or negative factor makes the result either zero or undefined
    rather than merely wrong, and a negative base with a fractional exponent
    raises inside ``math.pow`` with a traceback that names neither the field nor
    the caller.
    """

    model_config = ConfigDict(extra="forbid")

    total_factor_productivity: float = Field(
        gt=0.0,
        description=(
            "A — total factor productivity. UNOBSERVABLE by nature (Section "
            "21.4 item 13). Not published by any statistical agency; it is the "
            "Solow residual, so it absorbs measurement error in capital and "
            "labor alongside genuine efficiency change. Supply as an index or "
            "in whatever level units make the product come out in real GDP "
            "units; the function does not normalise, because a normalised "
            "output would hide a units mismatch rather than surface it."
        ),
    )
    capital_stock: float = Field(
        gt=0.0,
        description=(
            "K — the capital stock, in the same real units as the intended "
            "output. Published but ESTIMATED: perpetual-inventory construction "
            "from investment flows and assumed depreciation, not a census."
        ),
    )
    labor_input: float = Field(
        gt=0.0,
        description=(
            "L — labor input. The specification names this ``labor_input`` "
            "rather than ``labor_force`` because the production function wants "
            "effective labor, and the choice between bodies (employment), hours "
            "(total hours worked), and quality-adjusted hours is a real one that "
            "changes the result. The caller chooses and records it; the "
            "function cannot tell which was passed."
        ),
    )


def potential_gdp_cobb_douglas(inputs: PotentialGDPInputs) -> ModelResult:
    """``Y = A * K^alpha * L^(1-alpha)``. ``value``: ``float``.

    Hand calculation at the Section 20.3 golden case (``A = 1``,
    ``K = 100``, ``L = 100``, ``alpha = 0.3`` from config)::

        K^0.3      = 100^0.3   = 3.9810717...
        L^0.7      = 100^0.7   = 25.1188643...
        Y = 1 * 3.9810717 * 25.1188643 = 100.0000

    The golden case is exact by construction: ``100^0.3 * 100^0.7 = 100^1``.
    That makes it a genuine test of the exponent arithmetic rather than of the
    inputs — and it is why the specification specifies it. It returns ``100.0``
    under the correct exponents and ``1000.0`` if ``alpha`` is accidentally
    applied to ``L`` as well (``100^0.3 * 100^0.3``), a difference no
    plausibility range would catch.

    A second hand-verified case with the terms *not* chosen to cancel::

        A = 20, K = 40,000, L = 160,000, alpha = 0.3
            K^0.3 = 40000^0.3  = 24.02248868...
            L^0.7 = 160000^0.7 = 4394.2421732...
            Y = 20 * 24.02248868 * 4394.2421732 = 2,111,212.66

    (The first draft of this docstring carried a wrong ``L^0.7`` and therefore a
    wrong product — 3,252,491.2 instead of 2,111,212.7 — because it was written
    from recollection rather than computed. The test caught it. That is the
    argument for hand-verifying rather than hand-asserting: a miscomputed
    exponent propagates through the whole product while every intermediate step
    still *looks* like arithmetic.)

    Reported to 2 decimal places like every other level in this system, with the
    unrounded factor contributions reported alongside so a reader can
    reconstruct the product from the reported parts.

    ``confidence`` comes from ``compute_confidence()`` with the full set of
    applicable penalties. Section 20.3 writes ``confidence=0.3`` as a literal;
    Section 22.8 replaces it. The computed value lands at or below that, which
    is the correct direction — the specification's literal was already reaching
    for "this is the least trustworthy number in the suite".

    Parameters
    ----------
    inputs:
        ``PotentialGDPInputs``. No snapshot parameter: nothing is fetched here,
        and keeping the arithmetic pure is what lets the golden test target the
        formula rather than the plumbing.
    """
    settings = get_settings()
    alpha = settings.production_function.alpha_value
    one_minus_alpha = 1.0 - alpha

    capital_term = math.pow(inputs.capital_stock, alpha)
    labor_term = math.pow(inputs.labor_input, one_minus_alpha)
    potential = inputs.total_factor_productivity * capital_term * labor_term

    # Always present, both of them, because both are properties of the EQUATION
    # rather than of this particular set of numbers. Making either conditional
    # would imply the model escapes it on some inputs, which it never does.
    #
    # The ORDER is deliberate and follows the same reasoning as D-026 in the
    # Phillips module: A is both the least predictable term AND, unlike alpha,
    # entirely unobserved. Section 20.3 names it first and that ranking holds —
    # here the specification has it right, and a test pins the order so a later
    # edit cannot quietly invert it.
    warnings = [
        "A (total factor productivity) is the LEAST predictable and MOST "
        "IMPACTFUL term — Module 3.5. It is unobservable by nature (Section "
        "21.4 item 13): the Solow residual absorbs measurement error in capital "
        "and labor as well as genuine efficiency change, so it is the term most "
        "likely to move and least likely to move predictably. A 1% error in A is "
        "a 1% error in potential GDP, one-for-one.",
        "Track CBO/Fed/IMF estimates alongside this; dispersion across them IS "
        "the uncertainty band — Module 3.5. A single point estimate from any one "
        "methodology understates the uncertainty by construction. FRED GDPPOT "
        "(CBO) is the preferred published series (Section 21.1); this "
        "Cobb-Douglas figure is a cross-check against it, not a replacement.",
        "Potential GDP is a PRODUCTION-FUNCTION ESTIMATE, not observed — Module "
        "7.2. Every consumer of this value (notably output_gap) inherits that "
        "status. It must not be presented as a measurement, and a thesis that "
        "rests on the level of the output gap should state which estimate it "
        "used.",
    ]

    # A factor contributing nothing is worth naming rather than leaving for the
    # reader to notice: at alpha -> 0 or 1 the model degenerates to a
    # single-factor function and stops being a production function at all.
    if alpha <= 0.0 or alpha >= 1.0:
        warnings.append(
            f"alpha={alpha} is outside the interior (0, 1). The capital term "
            f"contributes {capital_term:.6g} and the labor term "
            f"{labor_term:.6g}; at the boundary the function degenerates to a "
            f"single-factor model and is no longer a production function. Check "
            f"config/settings.yaml production_function.alpha."
        )

    # Constant returns to scale is the assumption this functional form encodes,
    # and it is an ASSUMPTION rather than an identity: alpha + (1 - alpha) = 1
    # by construction, so the function can never report a scale elasticity other
    # than one. Named here so no reader mistakes the built-in CRS for a finding.
    if not math.isclose(alpha + one_minus_alpha, 1.0, rel_tol=0.0, abs_tol=1e-12):
        warnings.append(
            "alpha + (1 - alpha) does not equal 1 exactly in floating point. "
            "The output carries a rounding-level scale artifact."
        )

    return ModelResult(
        model_name="potential_gdp_cobb_douglas",
        country="us",
        as_of=utc_now(),
        value=round(potential, 2),
        confidence=compute_confidence(
            ConfidenceInputs(
                # Section 21.4 item 13: potential GDP and TFP are unobservable
                # by nature. The whole equation is built from them.
                depends_on_unobservable=True,
                # alpha is conventional but the LEVEL inputs are the estimated
                # ones, and no calibration of this equation against realised
                # potential output exists in this system.
                is_heuristic_not_calibrated=True,
                # A, K and L all descend from the same national-accounts
                # framework. One source, not three.
                source_independence_count=0,
            )
        ),
        interpretation=(
            f"Estimated potential GDP: {potential:,.2f} "
            f"(Cobb-Douglas: A={inputs.total_factor_productivity:g}, "
            f"K={inputs.capital_stock:,.0f}, L={inputs.labor_input:,.0f}, "
            f"alpha={alpha:g})"
        ),
        context=(
            f"Y = A * K^alpha * L^(1-alpha) with alpha={alpha:g}. "
            f"Factor decomposition: A contributes a factor of "
            f"{inputs.total_factor_productivity:g}, K^{alpha:g} = "
            f"{capital_term:,.4f}, L^{one_minus_alpha:g} = {labor_term:,.4f}. "
            f"Constant returns to scale is ASSUMED by this functional form, not "
            f"estimated — the exponents sum to 1 by construction, so this "
            f"function can never report a scale elasticity other than 1. "
            f"Cross-check against FRED GDPPOT (CBO); divergence is a finding "
            f"about method, not a defect in either figure."
        ),
        inputs_used=[
            "total_factor_productivity",
            "capital_stock",
            "labor_input",
        ],
        warnings=warnings,
    )


def growth_accounting_decomposition(
    labor_force_growth_pct: float,
    productivity_growth_pct: float,
) -> ModelResult:
    """Potential growth ≈ labor force growth + productivity growth. ``value``:
    ``dict``.

    Module 3.5. The specification's signature takes two bare floats rather than
    an input model, and unlike the Phillips ``beta`` case that is **not** a
    defect worth correcting: both terms are growth *rates* in percent, they are
    the entire input surface, and there is no config parameter they could
    shadow. The signature is kept as written.

    The interesting content is the asymmetry the specification names::

        Demographics are HIGH-confidence; productivity is LOW-confidence.
        Confidence in the total scales inversely with productivity's share.

    That is a statement about how a *sum* of two terms with very different
    reliabilities should be read, and it is measurable rather than rhetorical.
    The productivity share is reported, and the confidence penalty for the
    heuristic is applied when productivity carries more than half the total —
    which is the specification's own threshold, read from config.

    ``productivity_share`` is ``None``, never ``0.0``, when the two terms sum to
    zero. A zero total is not a finding that labor explains everything; it is an
    undefined ratio, and reporting ``0.0`` would assert the one thing the
    arithmetic cannot support. Same rule as ``ahe_composition_flag``.

    The sign case that matters: a **shrinking** labor force can produce positive
    potential growth only if productivity growth exceeds the decline. The
    interpretation names that explicitly, because "potential growth +0.5%" reads
    as healthy until you see it is ``-0.3%`` labor and ``+0.8%`` productivity —
    at which point the entire estimate rests on the low-confidence term alone.
    """
    settings = get_settings()
    productivity_dominance = settings.production_function.productivity_dominance

    # Bare-float signature by design (see the docstring above), so the
    # FiniteInputs guard never sees these and the check is explicit. Measured
    # before it was: growth_accounting_decomposition(nan, 1.0) published a dict
    # with THREE nan fields and one real one, so a consumer summing the
    # contributions got nan with no signal about which term was bad.
    require_finite_scalars(
        labor_force_growth_pct=labor_force_growth_pct,
        productivity_growth_pct=productivity_growth_pct,
    )

    total = labor_force_growth_pct + productivity_growth_pct

    # None, not 0.0. A zero denominator makes the ratio undefined; reporting 0.0
    # would claim labor explains the whole of a total that is itself zero.
    productivity_share: float | None = (
        round(productivity_growth_pct / total, 3) if total != 0.0 else None
    )

    warnings: list[str] = []

    if productivity_share is not None and productivity_share > productivity_dominance:
        warnings.append(
            f"Productivity drives {productivity_share:.0%} of this estimate — the "
            f"less-predictable term dominates (Module 3.5). Demographics are "
            f"high-confidence; productivity is low-confidence, so a potential-"
            f"growth figure resting mainly on productivity inherits its "
            f"unreliability rather than averaging it away."
        )

    if (
        labor_force_growth_pct < 0.0
        and productivity_growth_pct > 0.0
        and total > 0.0
    ):
        # All three conditions are required. The docstring's stated case is "a
        # shrinking labor force can produce POSITIVE potential growth only if
        # productivity growth EXCEEDS the decline" -- i.e. total > 0. A bare
        # `labor < 0 and prod > 0` fires even when total <= 0 (e.g. labor=-0.5,
        # prod=+0.5 -> total=0; or labor=-0.8, prod=+0.3 -> total<0), emitting a
        # "Positive potential growth here rests entirely on productivity" claim
        # that is then false. The `total > 0` guard makes the warning match the
        # arithmetic it describes. The both-negative branch below handles the
        # prod<0 case, which needs no offset description.
        warnings.append(
            f"Labor force growth is NEGATIVE ({labor_force_growth_pct:+.2f}%). "
            f"Positive potential growth here rests entirely on productivity "
            f"({productivity_growth_pct:+.2f}%). This is the US demographic "
            f"position: the arithmetic works only while productivity growth "
            f"outruns the labor-force decline, and productivity is the term "
            f"nobody can predict."
        )

    if productivity_share is None:
        warnings.append(
            "The two growth terms sum to exactly zero, so the productivity "
            "SHARE is undefined and reported as None rather than 0.0. The total "
            "is known to be zero; the split between its two components is not."
        )
    elif productivity_growth_pct < 0.0 and labor_force_growth_pct > 0.0:
        warnings.append(
            f"Productivity growth is NEGATIVE ({productivity_growth_pct:+.2f}%) "
            f"while labor force growth is positive ({labor_force_growth_pct:+.2f}%). "
            f"Potential growth is being carried by headcount alone, which is the "
            f"pattern that precedes a downward revision to potential output."
        )
    elif productivity_growth_pct < 0.0 and labor_force_growth_pct < 0.0:
        # BOTH terms negative is a different situation from either offsetting
        # pattern, and it must not be described by one of them. A guard written
        # as a bare ``labor_force_growth_pct < 0`` would fire here and report
        # that positive growth "rests entirely on productivity" — in a case where
        # productivity is negative too, so there is no positive growth and
        # nothing for it to rest on. Found by
        # `test_both_terms_negative_is_not_flagged_as_offsetting` during the
        # Step 5 warning-path pass.
        warnings.append(
            f"BOTH terms are negative (labor {labor_force_growth_pct:+.2f}%, "
            f"productivity {productivity_growth_pct:+.2f}%), so potential growth "
            f"is negative at {total:+.2f}%. This is a contracting capacity "
            f"estimate, not a slowing one — the output gap computed against it "
            f"will widen mechanically even if actual GDP is flat."
        )

    return ModelResult(
        model_name="growth_accounting_decomposition",
        country="us",
        as_of=utc_now(),
        value={
            "potential_growth": round(total, 2),
            "productivity_share": productivity_share,
            "labor_contribution_pp": round(labor_force_growth_pct, 2),
            "productivity_contribution_pp": round(productivity_growth_pct, 2),
        },
        confidence=compute_confidence(
            ConfidenceInputs(
                # Section 21.4 item 13: productivity growth is the TFP term.
                depends_on_unobservable=True,
                # The dominance threshold is config-supplied and illustrative.
                is_heuristic_not_calibrated=(
                    productivity_share is not None and productivity_share > productivity_dominance
                ),
            )
        ),
        interpretation=(
            f"Potential growth {total:+.2f}% "
            f"({labor_force_growth_pct:+.2f}pp labor, "
            f"{productivity_growth_pct:+.2f}pp productivity)"
            + (
                f", {productivity_share:.0%} of it from productivity"
                if productivity_share is not None
                else "; productivity share undefined (terms sum to zero)"
            )
        ),
        context=(
            f"Potential growth ≈ labor force growth + productivity growth "
            f"(Module 3.5). Labor {labor_force_growth_pct:+.2f}% + productivity "
            f"{productivity_growth_pct:+.2f}% = {total:+.2f}%. Demographics are "
            f"HIGH-confidence; productivity is LOW-confidence. Confidence in the "
            f"total scales inversely with productivity's share of it."
        ),
        inputs_used=[
            "labor_force_growth_pct",
            "productivity_growth_pct",
        ],
        warnings=warnings,
    )
