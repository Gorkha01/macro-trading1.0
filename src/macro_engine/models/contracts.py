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
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from macro_engine.models.evidence_family import EvidenceSourceFamily

__all__ = [
    "ConfidenceInputs",
    "EvidenceSourceFamily",
    "ModelResult",
    "ModelValue",
    "compute_confidence",
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


class ConfidenceInputs(BaseModel):
    """The stated factors that determine a model's confidence.

    AGENTS.md Section 22.8. Every field is a *fact about the computation*,
    not a feeling about it — which is the entire point of Finding #8.
    """

    model_config = ConfigDict(frozen=True)

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
        description="0-1. MUST come from compute_confidence(), never a literal (Section 22.8)."
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
