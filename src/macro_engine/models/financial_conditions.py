"""Module 12 — the financial conditions index (FCI).

Section 22.7 / Finding #7 governs this function, and it is explicit that the
**earlier version was wrong**:

> Every component is Z-SCORE STANDARDIZED ((x - mean) / std) BEFORE weighting —
> percent, bp, and index-point units are not comparable as raw deviations,
> **which the prior version incorrectly did**.

Section 22.13 makes the consequence mandatory: *"the raw-deviation
`compute_fci` … must be deleted from the codebase if already written, not left
alongside the corrected versions."* Nothing had been written, so there is
nothing to delete — but the placeholder form must never appear, and the
**no-raw-deviation** property is asserted in the test suite.

Positive = tighter-than-average financial conditions; negative = looser.

Four things had to be settled before the function could be written. See
**D-038**.

**1. The config's stored averages were materially wrong, and are gone.** The
`fci.averages` block held trailing means for three of five components, no
standard deviations, and no window. Measured against the live series:

| component | stored | measured | sigma | error |
|---|---|---|---|---|
| `credit_spread_hy` | **4.0** | **3.12** | 0.42 | **2.1 sigma** |
| `term_premium` | 0.3 | 0.132 | 0.35 | 0.48 sigma |
| `policy_rate` | 2.5 | 2.286 | 1.88 | 0.11 sigma |

The credit-spread average would have scored today's spread at **z = -2.95**
instead of **-0.85** — reporting conditions as far looser than they are.
Freezing a denominator is what let it drift, so the block is **removed** and the
statistics are computed by the caller over a documented window. Section 22.7
takes mean and std as parameters, so this is the specified design, not a
deviation.

**2. The 10-year window Section 22.7 suggests is not achievable.** The binding
constraint is `BAMLH0A0HYM2`, which returns **786 observations (~3.1 years)** on
this build, and that is a **provider limit rather than a fetch window**:
requesting `start_date=1990-01-01` returns the identical 786 rows. Section 22.7
requires *"a consistent, documented trailing window for every component"*, so
the window is the **common** history — not each series' own maximum, which would
make the z-scores incomparable, the very defect Finding #7 corrects.

**3. The weights are config's, not the specification's.** Section 22.7's
illustrative defaults (0.25/0.30/0.15/0.15/0.15) differ from the `fci.weights`
block that already existed (0.25/0.25/0.20/0.20/0.10). The block governs — it
names the components explicitly and postdates the defaults — and the divergence
is recorded rather than silently reconciled. `FCISettings` refuses to load a set
that does not sum to 1.0.

**4. The NFCI cross-check is part of the contract, not a script detail.**
Section 21.1 calls it *"mandatory"*. The model accepts an optional
`nfci_value`, publishes the divergence, and warns when it exceeds the configured
bar — and warns separately when the cross-check is **absent**, so a caller who
skips it cannot mistake silence for corroboration.
"""

from __future__ import annotations

from math import isfinite
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from macro_engine.models.contracts import (
    ConfidenceInputs,
    FiniteInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)

if TYPE_CHECKING:
    from macro_engine.config import FCISettings

__all__ = [
    "FCIComponent",
    "FCIComponentName",
    "FCIInputs",
    "compute_fci",
]

#: The five components, as a closed vocabulary.
FCIComponentName = Literal[
    "policy_rate",
    "credit_spread_hy",
    "term_premium",
    "equity_index",
    "usd_index",
]

#: Components whose standardised contribution is SUBTRACTED rather than added.
#:
#: Section 22.7 writes the composite as
#: ``... + w_dollar*z_dollar - w_equity*z_equity``. The sign is what makes
#: "positive = tighter" work: a RISING equity market is looser financial
#: conditions, so its contribution must push the index DOWN. Named here rather
#: than inlined so the orientation is auditable and a mutation can target it —
#: an inverted sign here flips the index's entire interpretation while leaving
#: every number plausible, which is the D-034 failure mode.
_NEGATED_COMPONENTS: frozenset[FCIComponentName] = frozenset({"equity_index"})


class FCIComponent(BaseModel):
    """One component's current value and the statistics it is standardised against.

    The mean and standard deviation are **supplied**, not stored in config, and
    must be computed over the same trailing window for every component
    (Section 22.7). ``std`` is constrained positive because it is a divisor: a
    zero would be a `ZeroDivisionError` at best and, if it slipped through as a
    tiny number, would produce a z-score of thousands that looks like a
    once-in-history reading.
    """

    model_config = ConfigDict(extra="forbid")

    value: float = Field(
        allow_inf_nan=False,
        description=(
            "The component's current reading, in its own units. MUST be finite: "
            "the composite is `sum(contribution)`, and `sum` propagates NaN, so "
            "one non-finite component silently destroys the whole index — and "
            "because `nan > 0` is False, `tighter_than_average` would silently "
            "read as 'looser than average'. Missing data is represented by the "
            "component being ABSENT, never by a non-finite sentinel."
        ),
    )
    mean: float = Field(
        allow_inf_nan=False,
        description="Mean over the standardization window, in the same units as `value`.",
    )
    std: float = Field(
        gt=0.0,
        allow_inf_nan=False,
        description=(
            "Standard deviation over the same window and in the same units. Must "
            "be positive and FINITE: it is the z-score divisor. `gt=0.0` alone "
            "does not reject `inf` (an infinite divisor yields a z-score of 0.0, "
            "inventing a neutral reading), and it does not reject `nan` for the "
            "right reason either — a NaN comparison is False, so the constraint "
            "passes by accident rather than by design."
        ),
    )

    @property
    def z_score(self) -> float:
        """(value - mean) / std — the standardization Finding #7 requires."""
        return (self.value - self.mean) / self.std


class FCIInputs(FiniteInputs):
    """Five standardised-able components, plus the window they were standardised over.

    Every component is a level (for the rates and spreads) or a change (for the
    dollar and equity indices), and each carries its own mean and standard
    deviation. Section 22.7 z-scores **all five**, including the two changes —
    a raw percent change in the S&P is not comparable to a basis-point spread
    move, which is the whole point of Finding #7.
    """

    model_config = ConfigDict(extra="forbid")

    policy_rate: FCIComponent
    credit_spread_hy: FCIComponent
    term_premium: FCIComponent
    equity_index: FCIComponent
    usd_index: FCIComponent

    standardization_window_years: int = Field(
        gt=0,
        description=(
            "The trailing window, in years, that the mean and standard deviation "
            "of EVERY component above were computed over. Declared by the caller "
            "because the caller computed them; the model checks it against the "
            "configured expectation and warns on a mismatch, since components "
            "standardised over different windows are not comparable."
        ),
    )
    nfci_value: float | None = Field(
        default=None,
        description=(
            "The Chicago Fed's National Financial Conditions Index (FRED `NFCI`) "
            "on the same date, if available. Section 21.1 calls the cross-check "
            "mandatory; supplying it here publishes the divergence and lets the "
            "model warn when the two disagree materially."
        ),
    )


def compute_fci(inputs: FCIInputs) -> ModelResult:
    """Compute the z-scored financial conditions index (Module 12, Section 22.7).

    Positive means tighter-than-average financial conditions, negative means
    looser. Confidence is computed from the stated factors (Section 22.8),
    never asserted.
    """
    settings = _fci_settings()
    weights = settings.component_weights

    # A mapping rather than dynamic attribute access, so the checker sees every
    # component and a name that drifts out of the input model fails here.
    components: dict[FCIComponentName, FCIComponent] = {
        "policy_rate": inputs.policy_rate,
        "credit_spread_hy": inputs.credit_spread_hy,
        "term_premium": inputs.term_premium,
        "equity_index": inputs.equity_index,
        "usd_index": inputs.usd_index,
    }

    # The configured set and the modelled set must be the same set. A component
    # added to config but not here would be silently dropped from the composite
    # while still carrying weight; one added here but not to config would be
    # silently unweighted. Both are invisible in the output, so both are refused.
    configured = set(settings.component_names)
    modelled = set(components)
    if configured != modelled:
        raise ValueError(
            f"fci.weights.components is {sorted(configured)} but the model carries "
            f"{sorted(modelled)}. The two must be the same set — a component on one "
            f"side only is silently dropped from, or added to, the composite."
        )

    z_scores: dict[FCIComponentName, float] = {}
    contributions: dict[FCIComponentName, float] = {}
    for name, component in components.items():
        z = component.z_score
        # `FCIComponent` refuses a non-finite value/std, but this is the point
        # of USE and the component may have arrived via `model_construct`, a
        # pickle, or a cache read. `sum` propagates NaN and a NaN comparison is
        # False, so a poisoned component would not raise — it would report a
        # fabricated "looser than average" verdict. Check the derived quantity,
        # not the input, because `z` is what the composite actually consumes.
        if not isfinite(z):
            raise ValueError(
                f"FCI component {name!r} produced a non-finite z-score ({z!r}) from "
                f"value={component.value!r}, mean={component.mean!r}, "
                f"std={component.std!r}. The composite is a sum, so one non-finite "
                "term would silently make the whole index nan and its "
                "'tighter_than_average' verdict False — a conclusion drawn from "
                "no data (Section 21.0 rule 2)."
            )
        sign = -1.0 if name in _NEGATED_COMPONENTS else 1.0
        z_scores[name] = z
        contributions[name] = sign * weights[name] * z

    fci = sum(contributions.values())
    tighter_than_average = fci > 0.0

    warnings = [
        # The specification's own caveat, kept because it is the reason the
        # number must not be trusted at size.
        "Weights are illustrative defaults, not calibrated against the Chicago "
        "Fed's NFCI methodology. Cross-check before this feeds any thesis at "
        "meaningful confidence.",
        f"The z-scores are computed over a {inputs.standardization_window_years}-year "
        f"window, which is bounded by data availability rather than chosen: the "
        f"high-yield spread series returns only ~3 years on this build. A component "
        f"standardised over a different window is not comparable, so every "
        f"component must use the same one.",
    ]

    if inputs.standardization_window_years != settings.standardization_window_years:
        warnings.append(
            f"The declared standardization window is "
            f"{inputs.standardization_window_years} years but config expects "
            f"{settings.standardization_window_years}. The model cannot verify which "
            f"window was actually used; it reports the declared one and flags the "
            f"disagreement."
        )

    nfci_divergence: float | None = None
    if inputs.nfci_value is None:
        # Silence must not read as corroboration.
        warnings.append(
            "NFCI cross-check NOT PERFORMED: no `nfci_value` was supplied. "
            "Section 21.1 calls this cross-check mandatory, so the composite is "
            "uncorroborated and must not be used at size."
        )
    else:
        nfci_divergence = fci - inputs.nfci_value
        if abs(nfci_divergence) > settings.nfci_divergence_threshold:
            warnings.append(
                f"This composite ({fci:+.3f}) diverges from NFCI "
                f"({inputs.nfci_value:+.3f}) by {nfci_divergence:+.3f}, beyond the "
                f"{settings.nfci_divergence_threshold:.1f} bar. The two are different "
                f"constructions, so some gap is expected — a gap this large is a "
                f"disagreement to investigate, not to average away."
            )

    confidence = compute_confidence(
        ConfidenceInputs(
            # The weights are uncalibrated_illustrative in settings.yaml, so this
            # reads True today and would read False if a phase calibrates them.
            is_heuristic_not_calibrated=not _weights_calibrated(),
            # Five series, one provider. One family, not five corroborating ones.
            source_independence_count=0,
        )
    )

    return ModelResult(
        model_name="compute_fci",
        country="us",
        as_of=utc_now(),
        value={
            "fci": round(fci, 4),
            "tighter_than_average": tighter_than_average,
            # The components, published so the composite is RECOMPUTABLE from
            # the output rather than trusted (the D-009 cross-field identity).
            "z_scores": {name: round(z, 4) for name, z in z_scores.items()},
            "contributions": {name: round(c, 4) for name, c in contributions.items()},
            "weights": dict(weights),
            "negated_components": sorted(_NEGATED_COMPONENTS),
            "standardization_window_years": inputs.standardization_window_years,
            "nfci_value": inputs.nfci_value,
            "nfci_divergence": None if nfci_divergence is None else round(nfci_divergence, 4),
            "nfci_cross_checked": inputs.nfci_value is not None,
        },
        confidence=confidence,
        interpretation=(
            f"FCI (z-score composite): {fci:+.3f} "
            f"({'tighter' if tighter_than_average else 'looser'} than average "
            f"financial conditions)"
        ),
        context=(
            "All components z-standardized before combination — comparable units, "
            "not raw mixed-unit deviations (Section 22.7 / Finding #7). Positive "
            "= tighter than average. MUST cross-check vs Chicago Fed NFCI "
            "(FRED: NFCI)."
        ),
        inputs_used=[
            "policy_rate",
            "credit_spread_hy",
            "term_premium",
            "equity_index",
            "usd_index",
        ],
        warnings=warnings,
    )


def _weights_calibrated() -> bool:
    """Whether the composite's weights are calibrated or illustrative placeholders."""
    from macro_engine.config import get_settings

    return get_settings().is_calibrated("fci.weights")


def _fci_settings() -> FCISettings:
    """Read Module 12's weights, window and cross-check bar. Lazy to avoid a config cycle."""
    from macro_engine.config import get_settings

    return get_settings().fci
