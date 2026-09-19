"""Module 15 / Section 16.4 — ``select_instrument`` (Tier 4, D-058).

The last-mile function that turns a macro thesis *type* into the instrument a
desk would actually put on — or into an explicit statement that no such
instrument exists. Section 22.3.1's corrected version replaces Section 16.2's
single-fallback placeholder; Section 22.12 supplies the boundary it enforces.

What this module is responsible for, and what it is not
--------------------------------------------------------

It **routes**: it maps a ``ThesisType`` and a gap direction onto one instrument
name plus the production-universe category that name belongs to. It does **not**
size, price, or decide whether the thesis is worth expressing — those are
``apply_fractional_kelly`` and ``build_us_macro_thesis`` respectively.

Three defect classes were found by the D-058 probe and are repaired here rather
than inherited. Each is recorded because each would have shipped looking
correct:

1. **The specification's own curve instrument failed its own universe check.**
   ``"Duration-weighted 2y/10y steepener/flattener"`` names *no instrument the
   production universe recognises*: ``steepener``, ``flattener``, ``duration``,
   ``weighted`` and ``curve`` appeared in **no** keyword set of
   ``ProductionUniverse``, so ``category_for`` returned ``None`` and the
   instrument was out of universe by the system's own definition (probe P1/P2).
   The shipped template now carries ``UST`` — which is what a desk calls the
   thing anyway — and the vocabulary gained the curve-shape words.

2. **``gap_direction`` was a declared, validated-nowhere, consumed-nowhere
   input.** Section 22.3.1 types it ``str`` with a comment and then never reads
   it: the branch is chosen by ``thesis_type`` alone and ``gap_direction``
   appears only in ``inputs_used``, which is a provenance string rather than a
   consumer. The "steepener/flattener" literal was both-or-neither, so the name
   did not encode direction either. It is now a ``Literal`` **and** it is
   consumed — the curve template's ``{direction_word}`` is derived from it, so
   ``positive`` → "steepener" and ``negative`` → "flattener". A parameter the
   function cannot observe the effect of is the D-037 class, and the repair is
   to make it load-bearing rather than to document its uselessness.

3. **Both confidence values were hardcoded.** Section 22.3.1 returns
   ``confidence=0.7`` for the executable branches and ``confidence=0.0`` for the
   sentinels. Section 22.8 forbids any literal, and the ``0.0`` is worse than a
   style lapse: a sentinel is a **confident** "no instrument", so presenting it
   at confidence zero reports a *known* answer as an *unknown* one. Both now go
   through ``compute_confidence()``.

Failure direction
-----------------

This function's failure direction is **toward a trade that cannot be put on** —
that is, toward *false executability*. If the universe check is wrong in the
permissive direction, the caller receives a plausible instrument name for
something the desk cannot trade, and the name reaches ``TradeIdea.instrument``
where §22.12 says it must never appear. The guard is therefore **two-sided and
asserted**: every executable branch re-checks its own emitted string against the
real ``ProductionUniverse``, so a template edited to name something out of
universe fails at the call rather than at the desk.

Provenance and layering
-----------------------

``models/`` is the lower layer and does not import ``thesis_layer/``. The
universe vocabulary therefore lives where it already lived — in
``thesis_layer.schemas`` — and this module receives it as a **required
argument** rather than importing it. That inverts the dependency instead of
duplicating the vocabulary, which is the D-046 repair (a 31-member enum that
existed twice). The type is a module-level ``Protocol`` so ``models/`` can
annotate it without a circular import.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)

__all__ = [
    "ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT",
    "BLOCKED_MULTI_COUNTRY_NOT_BUILT",
    "GapDirection",
    "InstrumentSelectionInputs",
    "InstrumentUniverse",
    "ThesisType",
    "select_instrument",
]


class ThesisType(str, Enum):
    """The analytical thesis families Section 22.3.1 enumerates.

    ``str``-valued so a member serialises to its documented string and can key
    the config routing table without a translation layer.
    """

    POLICY_PATH_GAP = "policy_path_gap"
    CURVE_SHAPE_GAP = "curve_shape_gap"
    CROSS_COUNTRY_DIVERGENCE = "cross_country_divergence"  # BLOCKED (US-only, Section 22.3)
    INFLATION_EXPECTATIONS_GAP = "inflation_expectations_gap"
    CREDIT_QUALITY_GAP = "credit_quality_gap"  # analytical only, Section 22.12
    EM_VULNERABILITY = "em_vulnerability"  # BLOCKED (US-only, Section 22.3)
    EQUITY_MACRO = "equity_macro"


#: Section 22.12's sentinel for a thesis whose analytical expression lies outside
#: the production execution universe. Named as a module constant so the value is
#: importable without constructing anything, and so a test can assert the
#: function *returns* this rather than a re-typed string.
ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT = "ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT"

#: Section 22.3's sentinel for a thesis family that needs a second country.
BLOCKED_MULTI_COUNTRY_NOT_BUILT = "BLOCKED_MULTI_COUNTRY_NOT_BUILT"


class InstrumentUniverse(Protocol):
    """Structural view of ``thesis_layer.schemas.ProductionUniverse``.

    Declared as a ``Protocol`` rather than imported so the dependency runs
    ``thesis_layer → models`` (the permitted direction) and not the reverse. A
    caller passes the real object; this module only needs these two methods.

    Both are **required** on the caller's object. The protocol is deliberately
    narrow: it is the smallest surface ``select_instrument`` actually uses, so a
    future universe implementation is not forced to reproduce an unrelated API.
    """

    def permits(self, instrument: str) -> bool:
        """Whether ``instrument`` names something inside the production universe."""
        ...

    def category_for(self, instrument: str) -> str | None:
        """The universe category ``instrument`` belongs to, or ``None``."""
        ...


class GapDirection(str, Enum):
    """Which way the mispricing runs.

    A ``Literal``-equivalent that is iterable at runtime (the tuple-plus-enum
    idiom): the vocabulary must be enumerable for the config template's
    ``{direction_word}`` substitution to be validated against it, and a bare
    ``str`` let Section 22.3.1's own comment ("positive" | "negative") go
    unenforced — a typo would have fallen through to a default branch and
    reported the optimistic answer silently.

    Semantics are stated because the sign convention is otherwise ambiguous and
    a flip here is invisible: **positive** means the thesis expects the traded
    variable to move *up* relative to what the market prices (a steeper curve, a
    higher policy path); **negative** means *down*.
    """

    POSITIVE = "positive"
    NEGATIVE = "negative"


#: direction -> the word a rates desk uses for that slope trade. This is the
#: consumption site for ``GapDirection``; before D-058 the direction reached only
#: ``inputs_used`` and no output depended on it.
_DIRECTION_WORD: dict[GapDirection, str] = {
    GapDirection.POSITIVE: "steepener",
    GapDirection.NEGATIVE: "flattener",
}


class InstrumentSelectionInputs(BaseModel):
    """What ``select_instrument`` needs, and nothing more.

    Parameters
    ----------
    thesis_type:
        Which family of macro thesis is being expressed. Selects the route.
    gap_direction:
        Which way the mispricing runs; see :class:`GapDirection`. **Consumed**,
        not merely carried: it selects the ``steepener``/``flattener`` word in
        the curve shape.
    curve_short_tenor / curve_long_tenor:
        The two legs of a curve trade, as desk strings (``"2y"``, ``"10y"``).
        Ignored by every non-curve route. ``None`` means "use the configured
        default". Supplying **both** is the only way to get a curve trade with
        non-default legs; supplying one and not the other is accepted, with the
        omitted leg defaulted, because that is what a caller editing one leg
        expects.
    """

    model_config = ConfigDict(extra="forbid")

    thesis_type: ThesisType
    gap_direction: GapDirection
    curve_short_tenor: str | None = Field(
        default=None,
        description='Near leg, desk spelling (e.g. "2y"). None -> configured default.',
    )
    curve_long_tenor: str | None = Field(
        default=None,
        description='Far leg, desk spelling (e.g. "10y"). None -> configured default.',
    )

    @model_validator(mode="after")
    def _tenors_only_belong_to_curve_trades(self) -> InstrumentSelectionInputs:
        """Refuse a curve leg supplied for a thesis type that cannot use one.

        Silent acceptance is how a caller concludes their tenors were honoured
        when they were dropped. A non-curve route ignores both legs, so passing
        one is a category error worth surfacing rather than discarding — the
        same reasoning as ``extra="forbid"``, one level down.
        """
        if self.thesis_type is not ThesisType.CURVE_SHAPE_GAP:
            supplied = [
                name
                for name, value in (
                    ("curve_short_tenor", self.curve_short_tenor),
                    ("curve_long_tenor", self.curve_long_tenor),
                )
                if value is not None
            ]
            if supplied:
                raise ValueError(
                    f"{', '.join(supplied)} supplied for thesis_type="
                    f"{self.thesis_type.value!r}, which has no curve legs. Tenors are "
                    f"read only by CURVE_SHAPE_GAP; supplying them to another route "
                    f"would be silently ignored."
                )
        return self


def _parse_tenor_years(tenor: str) -> float:
    """Convert a desk tenor string to years, or raise with the accepted forms.

    Accepts the spellings a rates desk actually uses: ``"2y"``, ``"10yr"``,
    ``"6m"``, ``"3mo"``, ``"1w"``. Raising rather than returning ``None`` keeps
    the failure at the input boundary: a tenor the parser cannot read would
    otherwise flow into a string comparison that silently passes.

    This exists solely to make the leg-separation check possible — nothing in
    the emitted instrument name is derived from the number.
    """
    text = tenor.strip().lower()
    units: tuple[tuple[str, float], ...] = (
        ("yr", 1.0),
        ("y", 1.0),
        ("mo", 1.0 / 12.0),
        ("m", 1.0 / 12.0),
        ("w", 1.0 / 52.0),
    )
    for suffix, years in units:
        if text.endswith(suffix):
            number = text[: -len(suffix)].strip()
            try:
                return float(number) * years
            except ValueError:
                continue
    raise ValueError(
        f"Unrecognised tenor {tenor!r}. Expected a number followed by one of "
        f"'y'/'yr', 'm'/'mo', 'w' (e.g. '2y', '10yr', '6mo', '1w')."
    )


def _build_curve_instrument(
    short_tenor: str,
    long_tenor: str,
    direction: GapDirection,
    template: str,
) -> str:
    """Format the curve template and refuse a degenerate or unreadable pair.

    Three rejections, each for a case Section 22.3.1's bare f-string accepted:

    * **An unparseable tenor** — ``"long"`` is not a leg.
    * **Equal legs** — ``"2y/2y"`` is not a slope trade; it is a small
      duration position wearing a curve trade's name.
    * **Inverted legs** — a "2y/10y" trade and a "10y/2y" trade are the same
      instrument written two ways, and the sign of the slope they express lives
      in ``gap_direction`` rather than in the leg order. Accepting both orderings
      would make the direction word and the leg order two ways to say one thing,
      which is one way to say it twice and get it wrong. The short leg must be
      the shorter one.
    """
    short_years = _parse_tenor_years(short_tenor)
    long_years = _parse_tenor_years(long_tenor)
    if short_years >= long_years:
        raise ValueError(
            f"Curve legs must be ordered short-to-long: got "
            f"{short_tenor!r} ({short_years:.4f}y) and {long_tenor!r} "
            f"({long_years:.4f}y). The direction of the trade is carried by "
            f"gap_direction, not by the leg order, so a reversed pair would "
            f"express the same view twice."
        )
    settings = get_settings().instrument_selection
    gap = long_years - short_years
    if gap < settings.minimum_leg_gap_years:
        raise ValueError(
            f"Curve legs {short_tenor!r}/{long_tenor!r} are {gap:.4f}y apart, below "
            f"the configured minimum of {settings.minimum_leg_gap_years}y. Legs this "
            f"close are the same point on the curve, not a slope."
        )
    if long_years > settings.maximum_leg_years:
        raise ValueError(
            f"Curve long leg {long_tenor!r} ({long_years:.4f}y) exceeds the configured "
            f"maximum of {settings.maximum_leg_years}y — beyond the tenors this book "
            f"trades."
        )
    return template.format(
        short=short_tenor,
        long=long_tenor,
        direction_word=_DIRECTION_WORD[direction],
    )


def _sentinel_result(
    *,
    thesis_type: ThesisType,
    value: str,
    interpretation: str,
    context: str,
    warnings: list[str],
    as_of: datetime,
) -> ModelResult:
    """Build a sentinel (no-production-instrument) result.

    Confidence is **computed**, like every other branch. A sentinel is a
    *confident* negative — "this thesis has no production expression" is a
    structural fact, not a failure to determine one — so reporting it at
    confidence ``0.0`` (as Section 22.3.1 does) states the opposite of the
    truth. ``depends_on_unobservable`` is left ``False``: nothing here rests on
    r*, u* or potential GDP.

    The source-independence credit is deliberately **zero for the blocked
    multi-country case and zero for the analytical case alike**, because a
    routing decision carries no corroboration. That is a true zero, and it is
    the same zero the executable branches receive — the confidence difference
    between a sentinel and an instrument is a difference of *no* factors, not a
    hand-set penalty.
    """
    settings = get_settings().instrument_selection
    confidence = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=settings.heuristic_not_calibrated,
            source_independence_count=settings.independence_count,
            depends_on_unobservable=False,
        )
    )
    return ModelResult(
        model_name="select_instrument",
        country="us",
        as_of=as_of,
        value=value,
        confidence=confidence,
        interpretation=interpretation,
        context=context,
        inputs_used=["thesis_type"],
        warnings=warnings,
        # --- Section 3/4: the reasoning object, populated -------------------
        unit=(
            "categorical (a sentinel value naming WHY there is no production "
            "instrument — not an instrument name)"
        ),
        direction=(
            "NO DIRECTION: a sentinel names the absence of an expression, so "
            "there is no trade side to state. `direction_word` is deliberately "
            "absent from this branch (see decision_prohibition)."
        ),
        assumptions=[
            "THERE IS NO PRODUCTION INSTRUMENT FOR THIS THESIS. The branch is "
            "reached only by a routing decision — a blocked multi-country thesis "
            "or an analytical (non-tradable) case — so the absence of an "
            "instrument is a STRUCTURAL FACT about the thesis, not a failure of "
            "this function to find one.",
            "The reason for the absence is correctly attributed. `value` names "
            "WHY (the sentinel), so a consumer can distinguish 'not tradable as "
            "constructed' from 'tradable in principle but outside this book'. "
            "The two call for different follow-ups.",
            "The routing decision that produced this sentinel is itself sound: "
            "this function trusts the caller's thesis_type rather than "
            "re-deriving it, so a mis-typed thesis yields a confidently-reported "
            "wrong sentinel rather than an error here.",
        ],
        data_provenance=[
            "thesis_type — resolved by the orchestrator from the caller or "
            "settings.api.default_thesis_type; it is the ONLY input, which is "
            "why `inputs_used` records just this one field",
            "`value`/`interpretation`/`context`/`warnings` — supplied by the "
            "call site that decided no production instrument exists, so this "
            "function does not itself inspect the universe on this branch",
            "Confidence is COMPUTED like every other branch, not hand-set. "
            "`independence_count` is a config leaf whose value on this branch is "
            "a TRUE ZERO (a routing decision carries no corroboration), and "
            "`depends_on_unobservable` is False because nothing here rests on "
            "r*, u* or potential GDP.",
        ],
        limitations=[
            "CONFIDENCE ON A SENTINEL IS A CONFIDENT NEGATIVE, NOT A DEGREE OF "
            "BELIEF. Reporting it at 0.0 would state the opposite of the truth: "
            "the claim 'this thesis has no production expression' is known, not "
            "unknown. So a high confidence here means the ABSENCE is "
            "well-established — it does NOT mean an instrument was found, and "
            "it does NOT mean the thesis is tradable.",
            "THE INDEPENDENCE CREDIT IS A TRUE ZERO FOR BOTH SENTINEL CASES, and "
            "that zero is the SAME zero the executable branches receive. The "
            "confidence difference between a sentinel and an instrument is "
            "therefore a difference of NO factors — not a hand-set penalty "
            "applied to sentinels. A reader who treats the two confidence values "
            "as different kinds of quantity will misread one of them.",
            "NO ALTERNATIVE EXPRESSION IS CONSIDERED. The function reports that "
            "the thesis has no instrument in THIS universe under SECTION 15's "
            "table; it does not search for a substitute, and it does not say "
            "whether a differently-constructed thesis on the same view would be "
            "expressible.",
            "THE SENTINEL VALUE IS NOT AN INSTRUMENT NAME despite sharing a "
            "field with one. Any consumer that reads `value` as a ticker without "
            "checking `is_production`/the sentinel set will route a "
            "non-existent instrument downstream.",
            "Points-in-time: a routing decision is deterministic in its inputs "
            "and carries no vintage risk of its own; the confidence inherits the "
            "config leaves' vintage, not a data vintage (Section 6).",
        ],
        decision_relevance=(
            "Section 16.2's Q9 — the instrument — where the answer is NONE. Its "
            "`value` becomes the thesis's `trade_idea.instrument`, and a "
            "sentinel is what makes a thesis honestly expressible as NO TRADE "
            "rather than as a fabricated expression. This is the branch that "
            "lets the system decline to trade."
        ),
        decision_prohibition=[
            "MUST NOT be read as a recommendation, a weak recommendation, or a "
            "trade at confidence 0. It is a statement that there is no trade to "
            "express, and the confidence describes how well-established that "
            "absence is.",
            "MUST NOT have its `value` consumed as an instrument name. The field "
            "is SHARED with the executable branch by schema, not by meaning; a "
            "consumer must branch on whether the result is a sentinel before "
            "treating `value` as a ticker.",
            "MUST NOT be reported with `direction_word`, which exists only on "
            "the executable branch. A position side attached to a sentinel would "
            "imply an expression that this result explicitly denies.",
            "MUST NOT be read as evidence about the thesis's correctness. The "
            "same sentinel would be returned for this thesis_type regardless of "
            "whether the underlying view is right — and, symmetrically, MUST NOT "
            "be taken to mean the view was judged WRONG. It was judged "
            "inexpressible in this book, which is a different claim.",
        ],
    )


def select_instrument(
    inputs: InstrumentSelectionInputs,
    universe: InstrumentUniverse,
) -> ModelResult:
    """Pick the production instrument that expresses ``inputs``, or say why not.

    An explicit branch per Module 15's instrument-selection table — never a
    single fallback. Every executable branch is checked against ``universe``
    before its instrument is returned, so a template edited to name something
    outside FX/rates/equity indices fails **here** rather than at the desk
    (Section 22.12).

    Parameters
    ----------
    inputs:
        See :class:`InstrumentSelectionInputs`.
    universe:
        The production-execution boundary. Passed in rather than imported
        because the canonical object lives in the layer **above** this one; see
        the module docstring.

    Returns
    -------
    ModelResult
        ``value`` is a ``dict`` with keys:

        * ``instrument`` — the name, or one of the two sentinels.
        * ``universe_category`` — ``"rates"`` / ``"fx"`` / ``"equity"``, or
          ``None`` for a sentinel. This is the **shipped** category vocabulary,
          not Section 22.3.1's ``"equity_index"``, which is not a category this
          system has (probe P3).
        * ``executable`` — whether a desk could put the instrument on.
        * ``rationale`` — why this instrument expresses this thesis type.
        * ``direction_word`` — the slope word the curve branch used, or ``None``.
          Published so the consumption of ``gap_direction`` is visible in the
          output rather than only in the code.

    Raises
    ------
    ValueError
        On an unhandled thesis type (a routing-table gap), or on a curve pair
        that is degenerate, inverted, out of range, or unparseable.
    """
    as_of = utc_now()
    settings = get_settings().instrument_selection
    routes = settings.routes

    if inputs.thesis_type in (ThesisType.CROSS_COUNTRY_DIVERGENCE,):
        return _sentinel_result(
            thesis_type=inputs.thesis_type,
            value=BLOCKED_MULTI_COUNTRY_NOT_BUILT,
            interpretation=(
                "Cross-country RV instrument selection requires a second country's "
                "rates system — not implemented in Phases 0-4."
            ),
            context=(
                "This system is genuinely US-only through Phase 4 (Section 22.3). "
                "country='us' is a label, not a generalisation."
            ),
            warnings=[
                "Do not fabricate a cross-market RV trade against an unbuilt country system."
            ],
            as_of=as_of,
        )

    if inputs.thesis_type in (ThesisType.CREDIT_QUALITY_GAP, ThesisType.EM_VULNERABILITY):
        return _sentinel_result(
            thesis_type=inputs.thesis_type,
            value=ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT,
            interpretation=(
                f"{inputs.thesis_type.value} is outside the production execution "
                f"universe (FX/rates/equity indices only)."
            ),
            context=(
                "Section 22.12: the analytical asset universe is not the production "
                "execution universe. CDS, HY/IG spreads and EM bonds are modelled for "
                "macro understanding only and must never reach TradeIdea.instrument."
            ),
            warnings=[
                "This thesis type cannot produce a TradeIdea.instrument in this system by design."
            ],
            as_of=as_of,
        )

    route = routes.get(inputs.thesis_type.value)
    if route is None:
        raise ValueError(
            f"Unhandled thesis_type: {inputs.thesis_type.value!r}. The routing table in "
            f"config/settings.yaml under instrument_selection.thesis_type_routes has no "
            f"entry for it, so no instrument can be selected. Known routes: "
            f"{sorted(routes)}."
        )

    template = route["instrument_template"]
    category = route["universe_category"]
    rationale = route["rationale"]

    direction_word: str | None = None
    if inputs.thesis_type is ThesisType.CURVE_SHAPE_GAP:
        short_tenor = inputs.curve_short_tenor or settings.default_short_tenor
        long_tenor = inputs.curve_long_tenor or settings.default_long_tenor
        instrument = _build_curve_instrument(
            short_tenor, long_tenor, inputs.gap_direction, template
        )
        direction_word = _DIRECTION_WORD[inputs.gap_direction]
    else:
        instrument = template

    # Section 22.12's hard boundary, enforced on the string we are about to
    # publish. Section 22.3.1's own `assert universe in PRODUCTION_UNIVERSE`
    # could never fire: it compared a literal to a set the literal was written
    # from (probe P4). This compares the EMITTED NAME to the real matcher, so a
    # template edited to name an out-of-universe instrument is caught here.
    observed_category = universe.category_for(instrument)
    if observed_category is None:
        raise ValueError(
            f"The route for {inputs.thesis_type.value!r} produced {instrument!r}, which "
            f"is OUTSIDE the production execution universe (Section 22.12). This is a "
            f"config error: instrument_selection.thesis_type_routes."
            f"{inputs.thesis_type.value}.instrument_template names something the desk "
            f"cannot trade. Refusing to publish it rather than substituting a "
            f"different instrument for a different risk."
        )
    if observed_category != category:
        raise ValueError(
            f"The route for {inputs.thesis_type.value!r} declares universe_category="
            f"{category!r} but {instrument!r} is classified {observed_category!r} by the "
            f"production universe. Fix the routing table — a category that disagrees "
            f"with the matcher makes the config note a claim rather than a fact."
        )

    confidence = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=settings.heuristic_not_calibrated,
            source_independence_count=settings.independence_count,
            depends_on_unobservable=False,
        )
    )
    return ModelResult(
        model_name="select_instrument",
        country="us",
        as_of=as_of,
        value={
            "instrument": instrument,
            "universe_category": observed_category,
            "executable": True,
            "rationale": rationale,
            "direction_word": direction_word,
        },
        confidence=confidence,
        interpretation=f"Selected: {instrument}",
        context=rationale,
        inputs_used=["thesis_type", "gap_direction"],
        # --- Section 3/4: the reasoning object, populated -------------------
        unit="categorical (an instrument name from the production universe)",
        direction=(f"{direction_word}: the thesis's gap direction, expressed through {instrument}"),
        assumptions=[
            "The instrument named by Section 15's selection table for this "
            "(thesis_type, gap_direction) pair is the correct expression of the "
            "view. The table is a curated mapping, not an optimisation: it "
            "encodes which instrument a desk would use, not which has the best "
            "expected payoff.",
            "The chosen instrument is a member of the supplied `universe`. This "
            "was CHECKED before returning rather than assumed — a template edited "
            "to name something outside FX/rates/equity indices fails at this "
            "function rather than at the desk (Section 22.12).",
            "`gap_direction` was read from the gap's own sign, not inferred here. "
            "The selection consumes a direction someone else established.",
        ],
        data_provenance=[
            "thesis_type — resolved by the orchestrator from the caller or "
            "settings.api.default_thesis_type",
            "gap_direction — from _gap_direction(gap), i.e. the sign of the "
            "canonical model-vs-market gap (Section 22.4)",
            "universe — a ProductionUniverse, validated for membership; the "
            "observed category is echoed as `universe_category`",
            "Selection templates are config-sourced "
            "(settings.instrument_selection), including the "
            "heuristic_not_calibrated and independence_count leaves that feed "
            "the confidence",
        ],
        limitations=[
            "IT SELECTS AN EXPRESSION, NOT EDGE. That a clean instrument exists "
            "for this view says nothing about whether the view is right, and "
            "nothing about whether it is worth trading — the significance test "
            "(Q6) already ran and is separate.",
            "THE MAPPING IS CURATED, NOT OPTIMISED: the table is a desk "
            "convention. A different desk might express the same view with a "
            "different instrument, and nothing here establishes that this is the "
            "best available expression.",
            "NO SIZING, NO COST, NO LIQUIDITY. The function names an instrument "
            "and stops; it does not consider transaction costs, market impact, "
            "or whether the instrument is actually tradable at the size the "
            "thesis would imply.",
            "The confidence is heuristic by construction "
            "(heuristic_not_calibrated is a config leaf), so it states the "
            "quality of a lookup rather than of a measurement.",
            "Points-in-time: the selection is deterministic in its inputs, so it "
            "carries no vintage risk of its own — but the gap_direction it "
            "consumes inherits the gap's revision exposure (Section 6, measured "
            "2026-09-19).",
        ],
        decision_relevance=(
            "Section 16.2's Q9 — the instrument. Its `instrument` value becomes "
            "the thesis's `trade_idea.instrument`, so this result is what makes a "
            "thesis expressible as a trade at all."
        ),
        decision_prohibition=[
            "MUST NOT be read as a recommendation to trade. Instrument selection "
            "is one gate among many, and the significance test that decides "
            "whether any trade is warranted has already run separately.",
            "MUST NOT be used to justify a trade whose gap was not significant. "
            "A clean, executable instrument for a sub-noise gap is still a "
            "sub-noise gap (Section 16.3).",
            "MUST NOT be treated as evidence about the thesis's correctness: the "
            "same instrument would be selected for the same view regardless of "
            "whether the view is right.",
            "MUST NOT be consumed without `direction_word`: the instrument alone "
            "does not say which way the position is taken.",
        ],
    )


def _selection_value(result: ModelResult) -> dict[str, Any]:
    """Narrow ``result.value`` to its documented dict shape.

    A helper rather than an inline ``isinstance`` so the narrowing is stated
    once. ``ModelResult.value`` is the deliberately broad union of Section 22.9;
    a consumer that knows this function returns a dict should assert that rather
    than cast.
    """
    value = result.value
    if not isinstance(value, dict):
        raise TypeError(
            f"select_instrument always returns a dict value; got {type(value).__name__}."
        )
    return value
