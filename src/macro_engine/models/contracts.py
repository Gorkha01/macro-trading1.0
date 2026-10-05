"""The universal typed-output contract and confidence rule for every model.

This module exists to make two of the external-review resolutions structural
rather than conventional:

* **AGENTS.md Section 22.9 / Finding #9** — ``ModelResult.value`` is a broad
  union that matches the heterogeneous returns models actually produce. The
  broad union is the *outer* contract; every subclass must still document its
  own narrower value type.
* **AGENTS.md Section 22.8 / Finding #8** — confidence is **computed from
  stated factors, never asserted**. ``compute_confidence()`` replaces every
  hardcoded ``confidence=0.X`` literal in the specification.

The governing rule, verbatim from Section 22.8:

    "No model may hardcode confidence going forward."

Placement note: this lives in ``models/`` rather than ``data_layer/`` because
it is the models-layer contract. ``thesis_layer/`` imports it; the data layer
does not need it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from macro_engine.models.evidence_family import EvidenceSourceFamily

__all__ = [
    "NON_FINITE_INPUT_REMEDY",
    "ConfidenceInputs",
    "EvidenceSourceFamily",
    "FiniteInputs",
    "ModelResult",
    "ModelValue",
    "compute_confidence",
    "require_finite_scalars",
    "utc_now",
]


def utc_now() -> datetime:
    """Timezone-aware current UTC time.

    The specification's sample code repeatedly writes ``datetime.utcnow()``,
    which returns a **naive** datetime and is deprecated as of Python 3.12.
    A naive datetime is a real defect here, not a style preference: it makes
    ``retrieved_at``-vs-``observation_date`` comparisons in
    ``data_layer/validation.py`` ambiguous about which timezone they are in.
    Every call site in this codebase uses this helper instead.
    """
    return datetime.now(tz=UTC)


# Corrected per AGENTS.md Section 22.9 / Finding #9. The legacy narrower
# `float | dict` declaration that appears earlier in the document is
# superseded and must not be reintroduced.
ModelValue = float | int | str | bool | dict[str, Any] | list[Any] | None


#: The shared reason a non-finite input is refused, quoted wherever the guard
#: fires so the reader gets the same explanation from every model. A non-finite
#: value is not "missing" and not "neutral": it fails EVERY comparison, so it
#: does not merely escape a rule's bounds — it silently takes the branch the
#: bounds were written to exclude. Measured before the guard existed (D-078):
#: `taylor_rule(pi_current=nan)` returned `value=nan`, and every consumer that
#: asks "is the prescription above the actual rate?" gets `False` from
#: `nan > actual` — the rule reports a verdict on a number it never computed.
#: Missing data is represented by refusing to compute (Section 21.0 rule 3).
NON_FINITE_INPUT_REMEDY = (
    "A non-finite value is neither missing nor neutral — it is a value that "
    "fails EVERY comparison, so it does not merely escape the input's bounds, it "
    "silently takes the branch those bounds were written to exclude. Missing "
    "data is represented by refusing to compute (Section 21.0 rule 3)."
)


class FiniteInputs(BaseModel):
    """Base for model INPUT groups: every float — scalar or list element — must be FINITE.

    Promoted here (D-139) from ``policy_rules._FiniteInputs``, which proved the
    pattern on the policy-rule inputs after D-078. It belongs in the shared
    contract module because the failure is a property of the INPUT, not of any
    one model: a ``nan`` that reaches a model body has already lost the
    information that it was never a number, and the arithmetic downstream has no
    way to recover it. Guarding at construction names the offending field in the
    error and stops the value before it can be mixed with real ones.

    Two shapes are covered:

    * a scalar ``float`` field that is ``nan``/``inf``;
    * a ``list[float]`` field carrying a non-finite ELEMENT — which per-field
      ``allow_inf_nan=False`` does NOT catch on its own, and which is the shape
      ``claims_trend_signal`` consumes (a weekly claims series where one bad
      print would otherwise propagate silently through both windows).

    **Nested containers are covered too (D-139b).** A ``list[list[float]]`` —
    a covariance or correlation MATRIX, the shape ``risk.PortfolioVaRInputs``
    and ``risk.MonteCarloVaRInputs`` carry — is walked recursively, because an
    element of a matrix is a ``list``, not a ``float``, so a one-level scan
    would pass a ``nan`` on the diagonal straight through and the model would
    publish a ``nan`` volatility/VaR. The walk is bounded by the data (a finite
    nesting depth), never by a fixed index count.

    **Dict VALUES are covered too (D-139c).** A ``dict[str, float]`` — the shape
    ``yield_curve.CurveSlopeInputs.tenors`` carries, a tenor→rate map — holds its
    numbers in the VALUES, and ``isinstance(value, (list, tuple))`` never sees
    them. A ``nan`` rate at one tenor would pass a one-shape scan and then
    contaminate every slope/curvature number derived from the curve. Dict keys
    are strings and are not inspected; only values are walked. A
    ``dict[str, list[float]]`` (``gdp_nowcast.SimpleGDPNowcastInputs``' quarter
    maps) is walked through both levels.

    **Nested MODEL fields are covered too (D-139c).** A field whose type is
    itself a pydantic model (``financial_conditions.FCIInputs``' five
    ``FCIComponent`` slots) is still an input: the walk recurses through the
    nested model's fields, so a ``nan`` in a sub-component is refused rather than
    slipping past because it is not a bare ``float``.

    Only *float* checks run: ``bool`` is a subclass of ``int`` in Python but is
    not a ``float``, and ``int`` is always finite, so neither can false-positive
    here. Non-numeric fields are ignored.
    """

    model_config = ConfigDict(extra="forbid")

    @staticmethod
    def _non_finite_offenders(name: str, value: object, path: str = "") -> list[str]:
        """Recursively collect non-finite floats reachable from ``value``.

        A scalar float is reported as ``name``; a list/tuple element as
        ``name[index]``; a nested container as ``name[i][j]``; a dict value as
        ``name['key']``. The error therefore names the EXACT cell, not merely the
        field, which is what makes a matrix or a curve map debuggable.
        """
        location = f"{name}{path}"
        if isinstance(value, bool):
            # bool is an int subclass and never non-finite; excluded explicitly
            # so the isinstance(float) test below cannot be reached with it.
            return []
        if isinstance(value, float):
            return [] if isfinite(value) else [f"{location}={value!r}"]
        if isinstance(value, (list, tuple)):
            offenders: list[str] = []
            for index, element in enumerate(value):
                offenders.extend(
                    FiniteInputs._non_finite_offenders(name, element, f"{path}[{index}]")
                )
            return offenders
        if isinstance(value, dict):
            offenders = []
            for key, element in value.items():
                offenders.extend(
                    FiniteInputs._non_finite_offenders(name, element, f"{path}[{key!r}]")
                )
            return offenders
        if isinstance(value, BaseModel):
            # A nested model field (e.g. FCIInputs' five FCIComponent slots) is
            # still an input: its floats must be finite too. Recurse through its
            # fields so the guard covers a group of sub-components, not only the
            # scalars at the top level.
            offenders = []
            for sub_name in type(value).model_fields:
                offenders.extend(
                    FiniteInputs._non_finite_offenders(
                        name, getattr(value, sub_name), f"{path}.{sub_name}"
                    )
                )
            return offenders
        return []

    @model_validator(mode="after")
    def _reject_non_finite(self) -> FiniteInputs:
        offenders: list[str] = []
        for name in type(self).model_fields:
            offenders.extend(self._non_finite_offenders(name, getattr(self, name)))
        if offenders:
            raise ValueError(
                f"non-finite input(s): {', '.join(offenders)}. {NON_FINITE_INPUT_REMEDY}"
            )
        return self


def require_finite_scalars(**named: object) -> None:
    """The ``FiniteInputs`` guard for functions that take POSITIONAL floats.

    ``FiniteInputs`` closes the non-finite class at construction, which covers
    the ~70 model functions that accept an ``Inputs`` model. It cannot cover the
    handful of reference-arithmetic functions whose signatures are bare floats
    by design — ``bond_math.modified_duration`` and
    ``price_change_with_convexity``, ``national_accounts.gdp_deflator`` and
    ``production_function.growth_accounting_decomposition``. Those keep their
    signatures (``growth_accounting_decomposition``'s docstring gives the
    reason: both terms are growth rates, the whole input surface, with no config
    parameter to shadow), so the guard has to be called explicitly.

    It was not, and the class was therefore OPEN for exactly those four.
    MEASURED 2026-10-05 before this helper existed::

        modified_duration(nan, 100.0)                    -> value = nan
        price_change_with_convexity(nan, 1.0, 1.0)       -> value = nan
        gdp_deflator(nan, 100.0)                         -> value = nan
        growth_accounting_decomposition(nan, 1.0)        -> {'potential_growth': nan,
                                                            'productivity_share': nan, ...}

    The last one is the worst shape: three of its four published fields go
    ``nan`` while the fourth stays a real number, so a consumer that sums or
    compares them gets ``nan`` with no signal about which term was bad.

    Reuses ``FiniteInputs._non_finite_offenders`` so the error message is
    byte-identical to the one a model input would raise, naming the offending
    argument: ``non-finite input(s): mac_dur=nan. <remedy>``.
    """
    offenders: list[str] = []
    for name, value in named.items():
        offenders.extend(FiniteInputs._non_finite_offenders(name, value))
    if offenders:
        raise ValueError(f"non-finite input(s): {', '.join(offenders)}. {NON_FINITE_INPUT_REMEDY}")


class ConfidenceInputs(BaseModel):
    """The stated factors that determine a model's confidence.

    AGENTS.md Section 22.8. Every field is a *fact about the computation*,
    not a feeling about it — which is the entire point of Finding #8.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # The three penalty factors below default to the NO-PENALTY state, so a
    # caller that omits one gets the highest confidence the formula can return
    # for that factor. That is the wrong direction for a default (§22.8 exists
    # to keep confidence from being overstated), and it is deliberate: making
    # them required would force ~70 call sites to assert `False` — a claim about
    # the computation — where today they are silent. Silence is the lesser evil
    # only because `extra="forbid"` now makes a MISS-SPELLED factor
    # (``is_heuristic_not_calibrated_=True``) an error instead of a silently
    # ignored argument that leaves the penalty unapplied. The absent factor and
    # the misspelled one are different failure modes; the first is a deliberate
    # default, the second is prevented here rather than left to a later reader.
    data_quality_flags_present: bool = Field(
        default=False,
        description="True if any input carried a data_quality_flag (Section 5.4).",
    )
    is_heuristic_not_calibrated: bool = Field(
        default=False,
        description=(
            "True for the illustrative Section 15.19/20 thresholds and any "
            "coefficient that has not been calibrated against realized data."
        ),
    )
    source_independence_count: int = Field(
        default=0,
        ge=0,
        description=(
            "From count_independent_families() — genuine source independence, not signal count."
        ),
    )
    depends_on_unobservable: bool = Field(
        default=False,
        description=(
            "True when the model depends on r*, u*, potential GDP or TFP. "
            "These are unobservable by nature (Section 21.4 item 13)."
        ),
    )


def _confidence_parameters() -> dict[str, float]:
    """Read the confidence constants from config.

    Imported lazily so that a caller which only needs ``ModelResult`` (for
    example an offline test fixture) does not require the config directory to
    be present and parseable. The import is cheap after the first call because
    ``get_settings`` is ``lru_cache``-backed.
    """
    from macro_engine.config import get_settings

    return get_settings().confidence.values


def compute_confidence(inputs: ConfidenceInputs) -> float:
    """THE single confidence-computation rule (AGENTS.md Section 22.8).

    Confidence is derived from stated facts about the computation:

    * start from a configurable base,
    * subtract for each risk factor present (data-quality flags, reliance on
      uncalibrated heuristics, dependence on unobservables),
    * credit genuine independent corroboration,
    * clamp into ``[floor, ceiling]``.

    The ceiling is **deliberate and load-bearing**: this system never claims
    near-certainty about a macro forecast. The floor keeps a returning
    confidence distinguishable from a missing value.

    Every constant is read from ``config/settings.yaml`` under ``confidence:``
    rather than hardcoded, because Section 22.8 states the formula is itself
    illustrative and explicitly scheduled for Phase 5+ calibration. What is
    mandatory from Phase 2 onward is the **structure** — confidence must be
    computed from stated factors rather than asserted.
    """
    p = _confidence_parameters()

    conf = p["base"]
    if inputs.data_quality_flags_present:
        conf -= p["data_quality_flag_penalty"]
    if inputs.is_heuristic_not_calibrated:
        conf -= p["heuristic_penalty"]
    if inputs.depends_on_unobservable:
        conf -= p["unobservable_penalty"]
    conf += min(
        inputs.source_independence_count * p["source_independence_bonus"],
        p["source_independence_bonus_cap"],
    )
    return round(max(p["floor"], min(p["ceiling"], conf)), 3)


class ModelResult(BaseModel):
    """No model ever returns a bare number (AGENTS.md Section 6).

    Implements the specification's "reason object" requirement: a model's
    output always carries its own interpretation, its comparison context, the
    inputs it consumed, and — critically — its warnings.

    ``value`` type contract (corrected, Section 22.9 / Finding #9):
        ``float | int | str | bool | dict | list | None``

    Subclasses (``PolicyRuleResult``, ``RegressionResult``, ...) MUST document
    their own narrower value type in their own docstring. This broad union is
    the outer contract, not license for any individual model to be vague
    about what it actually returns.
    """

    model_config = ConfigDict(extra="forbid")

    model_name: str = Field(description="Stable identifier, used as the MLflow metric key.")
    country: str = Field(description='ISO-3166 alpha-2 lowercase. "us" only through Phase 4.')
    as_of: datetime = Field(description="Timezone-aware UTC timestamp of the computation.")
    value: ModelValue = Field(
        description="Primary output. See the corrected union type in Section 22.9."
    )
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] = Field(
        description=(
            "0-1. **This is a RELIABILITY measure, not a probability that the "
            "model is correct** (economic-integrity directive Section 5). It says "
            "how much the inputs and method can be trusted — data quality, "
            "calibration status, observability — and nothing about whether the "
            "world will behave as modelled. A confidence of 0.7 does NOT mean "
            "'70% chance this call is right'; it means the estimate rests on "
            "reasonably reliable inputs. Reading it as a hit-rate is the exact "
            "misreading this note exists to prevent. MUST come from "
            "compute_confidence(), never a literal (Section 22.8)."
        )
    )
    interpretation: str = Field(description="Plain-language meaning of the value.")
    context: str = Field(description="Comparison point: vs target, vs prior, vs history.")
    inputs_used: list[str] = Field(
        description="Which snapshot fields / upstream functions fed this model."
    )
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "Never dropped. Propagated up into MacroThesis.warnings by "
            "collect_all_warnings(). An untested warning path is an untested "
            "safety mechanism (Section 21.2 Step 5)."
        ),
    )
    source_family: EvidenceSourceFamily | None = Field(
        default=None,
        description=(
            "Module 13 provenance. Set by tag_evidence_source(); consumed by "
            "count_independent_families() as the unit of independence. A typed "
            "field rather than a warning string, because a warning is a "
            "reporting surface that callers may rewrite and a tag is a fact "
            "(Section 15.19-D, corrected — see DECISIONS)."
        ),
    )
    data_quality_flags_present: bool = Field(
        default=False,
        description=(
            "Whether any input to this model carried a Section 5.4 data-quality "
            "flag. Recorded so a convergence caller can price it; it does NOT "
            "retroactively change this result's confidence, which was computed "
            "when the result was built (Section 22.8 forbids a second producer)."
        ),
    )

    # ------------------------------------------------------------------
    # Reasoning-object fields (economic-integrity directive Sections 3-4)
    #
    # Section 3 states a model must return a REASONING OBJECT, not a number
    # with prose around it. `interpretation`/`context`/`warnings` above were
    # already the core of that; these fields close the remaining gaps the
    # directive names.
    #
    # EVERY ONE DEFAULTS TO AN HONEST "NOT SUPPLIED", never to a plausible
    # fill. A model that does not state its unit says `unit=None` — which a
    # consumer reads as "unknown", not as "dimensionless". The whole point of
    # Section 3 is that the absence of a justification must be *visible*, and
    # a zero-effort default that looked complete would destroy that.
    # ------------------------------------------------------------------

    unit: str | None = Field(
        default=None,
        description=(
            "Units of `value`, spelled out (e.g. 'percent', 'bp', 'index', "
            "'fraction_of_capital', 'usd_billions'). None = the model did not "
            "declare one, which a consumer MUST treat as unknown rather than as "
            "dimensionless (Section 3)."
        ),
    )
    direction: str | None = Field(
        default=None,
        description=(
            "Which way the value moves the underlying economic quantity, where "
            "that is meaningful (e.g. 'expansionary', 'restrictive', 'neutral'). "
            "Distinct from the SIGN of `value`: a negative output gap is "
            "loosening, a positive Taylor residual is restrictive. None when the "
            "model's value has no direction (Section 3)."
        ),
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description=(
            "Modelling assumptions this result depends on, stated as claims "
            "(e.g. 'the projected path is the CBO baseline, not a forecast of "
            "policy'). Empty means the model declares none, which a consumer "
            "should read as under-documented rather than assumption-free."
        ),
    )
    data_provenance: list[str] = Field(
        default_factory=list,
        description=(
            "Where each input actually came from, at the granularity a reader "
            "needs to audit it (e.g. 'CPIAUCSL @ 2026-08-01 via openbb:"
            "http://127.0.0.1:6900'). Complements `inputs_used`, which names "
            "the FIELDS; this names the SOURCES (Section 4)."
        ),
    )
    observation_dates: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Snapshot field name -> ISO date of the observation actually used. "
            "Makes the vintage of each input explicit, so a reader can see that "
            "the CPI reading is August while the unemployment reading is "
            "September (Section 4)."
        ),
    )
    release_dates: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Snapshot field name -> ISO datetime the value became public. "
            "Expected EMPTY on this installation: no reachable route returns "
            "release dates (Section 6, measured 2026-09-19). An empty dict here "
            "is a true statement that the information is unavailable, not an "
            "omission by the model."
        ),
    )
    vintage_dates: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Snapshot field name -> ISO datetime identifying which revision of "
            "the value was used. Empty for the same measured reason as "
            "`release_dates` (Section 4/6)."
        ),
    )
    retrieved_at: datetime | None = Field(
        default=None,
        description=(
            "When the underlying data was read. Distinct from `as_of`, which is "
            "when the COMPUTATION ran: a model can run off a snapshot cached "
            "hours earlier, and conflating the two hides that staleness. None "
            "when the caller did not thread it through (Section 4)."
        ),
    )
    source_families: list[EvidenceSourceFamily] = Field(
        default_factory=list,
        description=(
            "Every source family the inputs span — the plural of the singular "
            "`source_family` above, which records only this result's OWN tag. "
            "Needed because Section 5.17's independence count is about the SET "
            "of families a conclusion rests on, not the one tag it carries."
        ),
    )
    limitations: list[str] = Field(
        default_factory=list,
        description=(
            "What this result CANNOT tell you — the standing caveats that hold "
            "even when the computation succeeded, as distinct from `warnings`, "
            "which report a condition of THIS run. E.g. 'rule-based, so it "
            "partitions but does not estimate' is a limitation; 'CPI is stale "
            "by one month' is a warning (Section 3)."
        ),
    )
    decision_relevance: str | None = Field(
        default=None,
        description=(
            "What this output is FOR in the thesis pipeline — which downstream "
            "gate, view, or sizing input consumes it. None = the model does not "
            "know its own downstream use, which is a real gap a reader should "
            "see (Section 3)."
        ),
    )
    decision_prohibition: list[str] = Field(
        default_factory=list,
        description=(
            "What a consumer is FORBIDDEN to do with this output. This is the "
            "load-bearing field of Section 3: it is where a proxy declares it "
            "must not be traded, an uncalibrated distribution declares it must "
            "not be sized, and a rule-based label declares it must not be read "
            "as a probability. Empty means the model claims no restriction, "
            "which is itself an assertion a reviewer can challenge."
        ),
    )

    def value_dict(self) -> dict[str, Any]:
        """Return ``value`` narrowed to a ``dict``, or raise if it is not one.

        ``value`` is a broad union by contract (Section 22.9): a model may
        publish a scalar, a list, a string or ``None``. A consumer that KNOWS
        this result published a mapping — which is every model that returns a
        report dict — otherwise has to narrow the union at every read, and that
        is exactly where an unchecked ``isinstance`` typo would go unnoticed.
        This is the ONE narrowing point: it returns the mapping, or raises with
        the model's name so a mis-use is loud rather than a silent ``KeyError``
        on a list index.

        It is a method on the contract rather than a helper in the test suite
        because the need is not test-specific — any consumer reading a dict
        value has it — and a second copy in ``tests/`` would be a second source
        of truth for the same narrowing.
        """
        value = self.value
        if not isinstance(value, dict):
            raise TypeError(
                f"{self.model_name}: value is {type(value).__name__}, not a dict; "
                f"read `.value` directly for a non-dict result."
            )
        return value

    def value_float(self) -> float:
        """Return ``value`` narrowed to a ``float``, or raise if it is not numeric.

        The scalar counterpart of :meth:`value_dict`: it is the ONE place a
        consumer that knows this result published a number narrows the union,
        rather than a bare ``float(self.value)`` — which mypy rejects anyway,
        because the union contains ``dict``/``list``/``str``. A ``bool`` is
        refused even though it is an ``int`` subclass, so ``True`` cannot
        silently become ``1.0`` in an arithmetic comparison.
        """
        value = self.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(
                f"{self.model_name}: value is {type(value).__name__}, not a number; "
                f"read `.value` directly for a non-numeric result."
            )
        return float(value)
