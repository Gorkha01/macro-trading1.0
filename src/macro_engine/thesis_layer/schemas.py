"""MacroThesis schema (AGENTS.md Section 7.1, corrected per Section 22).

The ``MacroThesis`` is the codified form of the institutional
trade-construction discipline: hypothesis → thesis → evidence → probability →
risk → catalyst → instrument → sizing, expressed as data rather than prose.

Corrections integrated here, each replacing an earlier definition that must
**not** be reintroduced (Section 22.13):

* ``thesis_id`` is generated, not hand-written.
* ``convergence_classification`` includes ``NO_SIGNAL`` — Section 22.10 /
  Finding #10 makes it a first-class value, because "no signal at all" is not
  the same as "low conviction signal" and must not be collapsed into LOW.
* ``ScenarioOutcome`` carries the full discrete distribution the generalized
  Kelly formula consumes, and its probabilities are validated to sum to 1.
* ``TradeIdea`` distinguishes an analytical expression from a production one.
  Finding #12 / Section 22.12: the production execution universe is
  **exclusively** FX spot/forwards, sovereign rates instruments, and broad
  equity indices. Anything else returns ``ANALYTICAL_ONLY_NO_PRODUCTION_
  INSTRUMENT`` rather than an instrument name that cannot actually be traded.
* ``EvidenceSourceFamily`` (Module 13) exists so that five sub-measures of one
  release count as one vote, not five.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from macro_engine.config import get_settings
from macro_engine.models.contracts import utc_now

# Module 13's vocabulary lives in the models layer (the lower layer) because
# model-layer convergence classifiers must consume it. Re-exported here so
# thesis-layer code and existing imports are unaffected.
from macro_engine.models.evidence_family import EvidenceSourceFamily

# ``MarketPricingGap``, ``ScenarioOutcome`` and ``PayoffUnit``: one pattern,
# one reason. Each had TWO structurally different declarations carrying one
# name, and in each case a producer in the models layer could not feed a
# consumer in this one. The
# producer (``build_scenario_distribution``, Section 16.4) and the consumer
# (``apply_fractional_kelly``, Section 22.6) must agree on ONE class, and
# until D-064 they did not — two structurally different classes carried this
# one name, which ``mypy --strict``, ``ruff`` and any single-import test all
# accepted. D-057 recorded it as **O-51**; D-064 closed it.
from macro_engine.models.policy_rules import MarketPricingGap as MarketPricingGap
from macro_engine.models.probability import PayoffUnit as PayoffUnit
from macro_engine.models.probability import ScenarioOutcome as ScenarioOutcome

__all__ = [
    "NO_PRODUCTION_INSTRUMENT",
    "ConfirmationSignal",
    "ConvergenceClassification",
    "EvidenceSourceFamily",
    "InstrumentExpression",
    "MacroThesis",
    "MarketPricingGap",
    "PayoffUnit",
    "ProductionUniverse",
    "ScenarioOutcome",
    "SignalDirection",
    "ThesisStatus",
    "TradeIdea",
]


# The canonical no-instrument sentinel. Section 22.12: a thesis with no
# production expression must say so explicitly rather than naming an
# instrument the desk cannot actually put on.
NO_PRODUCTION_INSTRUMENT = "NONE"

#: G10 currency codes, used only to recognise a concatenated spot pair.
#:
#: A bare "starts with a 3-letter code" test is **too weak**: `"europe"` is six
#: alphabetic characters beginning with `"eur"`, so it would have permitted
#: `"europe equity"` as FX (D-058 probe). Requiring **both** halves to be a
#: known currency code is the discriminator: `"eurusd"` splits into `eur` +
#: `usd`, while `"europe"` splits into `eur` + `ope`, and `"ope"` is not a
#: currency.
_G10_CURRENCY_CODES: frozenset[str] = frozenset(
    {"usd", "eur", "jpy", "gbp", "chf", "aud", "cad", "nzd", "nok", "sek"}
)


class ThesisStatus(str, Enum):
    """Lifecycle of a thesis.

    Phase 1 always produces ``DRAFT``: a human reviews and promotes. There is
    no auto-promotion to ACTIVE until the Phase 5+ risk gating exists.
    """

    DRAFT = "DRAFT"
    WATCH = "WATCH"
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    INVALIDATED = "INVALIDATED"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class ConvergenceClassification(str, Enum):
    """How well the independent signals agree (Section 22.10 / Finding #10).

    ``NO_SIGNAL`` is first-class. It means every pillar read neutral — which is
    genuinely different from ``LOW``, where signals exist but conflict
    weakly. Collapsing the two would report "we see something, weakly" when
    the truth is "we see nothing".
    """

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    CONFLICTED = "CONFLICTED"
    NO_SIGNAL = "NO_SIGNAL"


class SignalDirection(int, Enum):
    """Directional read of one signal.

    ``-1`` easing-implying, ``0`` neutral, ``+1`` tightening-implying.

    An ``IntEnum`` because these values are summed and compared numerically in
    ``four_pillar_scorecard()``, and a bare int would lose the vocabulary that
    makes ``+1`` mean "tightening" rather than "positive".
    """

    EASING = -1
    NEUTRAL = 0
    TIGHTENING = 1


# ``MarketPricingGap`` was declared HERE until D-064, as a structurally
# different class from ``models/policy_rules.py``'s — same fields except that the
# noise-floor field was named ``rule_dispersion`` here and ``dispersion`` there.
# It now lives in the models layer and is re-exported at the top of this module,
# for the same reason ``ScenarioOutcome`` does: the canonical producer
# (``canonical_policy_gap``, Section 22.4) returns the models-layer class and
# ``build_scenario_distribution`` consumes it, so two classes meant the producer
# could not feed the consumer. See **O-51** and **O-71**.


class ConfirmationSignal(BaseModel):
    """One model's corroboration (or contradiction) of the thesis.

    Section 22.10 / Finding #10: ``direction`` is an explicit enum, not a free
    string. Free strings made it impossible for ``classify_convergence()`` to
    reliably ignore neutral signals, which caused the earlier implementation to
    flag CONFLICTED on non-opposed directional inputs.
    """

    model_config = ConfigDict(extra="forbid")

    source_model: str
    direction: str = Field(description='"confirms" | "contradicts" | "neutral"')
    detail: str
    source_family: EvidenceSourceFamily | None = Field(
        default=None,
        description="Module 13 family. Used by count_independent_families() — None if unmapped.",
    )

    @model_validator(mode="after")
    def _validate_direction(self) -> ConfirmationSignal:
        permitted = {"confirms", "contradicts", "neutral"}
        if self.direction not in permitted:
            raise ValueError(
                f"ConfirmationSignal.direction must be one of {sorted(permitted)}; "
                f"got {self.direction!r}"
            )
        return self


# ``ScenarioOutcome`` was declared HERE until D-064, as a structurally different
# class from ``models/probability.py``'s. It now lives in the models layer and is
# re-exported at the top of this module — see the note beside that import, and
# **O-51**.


class ProductionUniverse(BaseModel):
    """The production execution universe (Section 22.12 / Finding #12).

    Exhaustive by construction. An instrument that is not in one of these
    categories is analytically useful but not executable, and the thesis must
    say so rather than naming it as a trade.

    Matching is by **keyword**, not by substring containment of whole
    instrument strings. Naive containment fails in both directions: it rejects
    legitimate instruments ("UST 2yr note futures" contains none of the listed
    full strings) and accepts illegitimate ones (any description mentioning
    "cash"). Keywords are checked per category so that a rejection can say
    *which* category was consulted.
    """

    model_config = ConfigDict(extra="forbid")

    rates: list[str] = Field(
        default_factory=lambda: [
            "UST cash (2yr, 5yr, 10yr, 30yr)",
            "UST futures (TU, FV, TY, US)",
            "SOFR futures",
            "Fed funds futures",
            "TIPS cash and breakevens",
        ]
    )
    fx: list[str] = Field(
        default_factory=lambda: [
            "G10 FX spot",
            "G10 FX forwards",
        ]
    )
    equity: list[str] = Field(
        default_factory=lambda: [
            "Broad equity indices (ES, NQ, RTY)",
        ]
    )

    # Keyword sets per category. A candidate instrument must match at least one
    # keyword from exactly one category to be permitted.
    #
    # NOTE the absence of bare short tickers such as "us" (the long-bond
    # futures root) and "es": as standalone tokens they collide with ordinary
    # prose ("US HY credit index", "ESG index") and would silently admit
    # out-of-universe instruments. Multi-character roots are kept only where
    # they are unambiguous ("sofr", "tips").
    _RATES_KEYWORDS: tuple[str, ...] = (
        "ust",
        "treasury",
        "sofr",
        "fed funds",
        "fedfunds",
        "tips",
        "breakeven",
        "note futures",
        "bond futures",
        "swap",
        "ois",
        "tnote",
        # Curve-shape vocabulary (D-058 probe P2). Section 22.3.1's
        # CURVE_SHAPE_GAP branch emits a duration-weighted steepener/flattener,
        # and NONE of these words appeared in any keyword set — so the
        # specification's own curve instrument failed the matcher that is
        # supposed to admit it. These are the vocabulary a rates desk actually
        # uses for a slope trade, and they are unambiguous: none of them occurs
        # in ordinary credit/commodity prose.
        "steepener",
        "flattener",
        "steepening",
        "flattening",
        "duration-weighted",
        "butterfly",
        "curve",
    )
    _FX_KEYWORDS: tuple[str, ...] = (
        "fx",
        "currency",
        "spot fx",
        "forward",
        "eur",
        "usd",
        "jpy",
        "gbp",
        "chf",
        "aud",
        "cad",
        "nzd",
        "nok",
        "sek",
    )
    _EQUITY_KEYWORDS: tuple[str, ...] = (
        "equity index",
        "equity indices",
        "index futures",
        "s&p",
        "spx",
        "nasdaq",
        "russell",
        "dax",
        "euro stoxx",
        "nikkei",
    )
    # Bare exchange tickers, matched only as a standalone token or as the token
    # immediately preceding "futures"/"options". These are unambiguous enough
    # to admit, but too short to match as loose substrings ("es" appears inside
    # "futures"; "ty" inside "volatility"). The "ticker + futures" form is how
    # a desk actually names these contracts.
    _BARE_TICKERS: dict[str, str] = {
        "tu": "rates",
        "fv": "rates",
        "ty": "rates",
        "us": "rates",
        "tnote": "rates",
        "es": "equity",
        "nq": "equity",
        "rty": "equity",
        "ym": "equity",
    }
    # G10 currency codes, used ONLY to recognise a concatenated spot pair
    # ("EURUSD", "USDJPY"). The set itself lives at module scope so that
    # `_keyword_match` can consult it; see the note there for why a bare
    # three-letter prefix test is not enough.
    _G10_CURRENCIES: frozenset[str] = _G10_CURRENCY_CODES
    # Categories that are explicitly NOT in the production universe. Listed so
    # the rejection can name why, rather than reporting a generic miss.
    _EXCLUDED_KEYWORDS: tuple[str, ...] = (
        "credit",
        "cdx",
        "cds",
        "hy ",
        "high yield",
        "em sovereign",
        "em bond",
        "gold",
        "copper",
        "wti",
        "crude",
        "commodity",
        "oil",
        "iron ore",
        "aluminum",
        "silver",
        "invoice",
    )

    @property
    def all_instruments(self) -> list[str]:
        return [*self.rates, *self.fx, *self.equity]

    def permits(self, instrument: str) -> bool:
        """Whether an instrument string names something in the universe.

        Returns ``True`` for the ``NONE`` sentinel, since "no instrument" is
        always a permitted outcome — it is the correct answer more often than
        any specific trade is.

        The sentinel is matched **case-insensitively**, like every other
        comparison in this class. It previously compared exactly, so ``"NONE"``
        was permitted and ``"none"`` was not — a one-character difference
        deciding whether the system reported "no trade" or "out of universe"
        (D-058 probe P17).
        """
        if instrument.strip().upper() == NO_PRODUCTION_INSTRUMENT:
            return True
        needle = instrument.lower().strip()
        if not needle:
            return False
        return bool(self.category_for(instrument))

    def category_for(self, instrument: str) -> str | None:
        """Which universe category an instrument belongs to, if any.

        Returning the category (rather than a bare bool) is what lets the
        thesis explain *why* something is out of universe — "credit indices are
        not in the production universe" is actionable; "not permitted" is not.

        Excluded categories are checked **first**. That ordering matters: "US
        HY credit index" contains "index", which would otherwise match the
        equity category, and a false permit here means proposing a trade the
        desk cannot execute.
        """
        if instrument.strip().upper() == NO_PRODUCTION_INSTRUMENT:
            return "none"
        needle = instrument.lower().strip()
        if any(_keyword_match(keyword, needle) for keyword in self._EXCLUDED_KEYWORDS):
            return None
        # A literal entry from one of the universe lists is permitted by
        # construction — this is what makes the lists themselves authoritative
        # rather than decorative.
        for category, members in (("rates", self.rates), ("fx", self.fx), ("equity", self.equity)):
            if any(needle == member.lower() for member in members):
                return category
        ticker_category = self._bare_ticker_category(needle)
        if ticker_category:
            return ticker_category
        for category, keywords in (
            ("rates", self._RATES_KEYWORDS),
            ("fx", self._FX_KEYWORDS),
            ("equity", self._EQUITY_KEYWORDS),
        ):
            if any(_keyword_match(keyword, needle) for keyword in keywords):
                return category
        return None

    def _bare_ticker_category(self, needle: str) -> str | None:
        """Match a bare futures ticker as a standalone token.

        Only two shapes count: the ticker alone ("TU"), or the ticker directly
        followed by a contract noun ("TU futures", "ES options"). Anything
        looser would let "US HY credit index" through on the strength of the
        word "US".
        """
        tokens = [t.strip(",;:()[]") for t in needle.split()]
        if not tokens:
            return None
        contract_nouns = {"futures", "future", "options", "option", "contract", "contracts"}
        if len(tokens) == 1 and tokens[0] in self._BARE_TICKERS:
            return self._BARE_TICKERS[tokens[0]]
        if len(tokens) == 2 and tokens[1] in contract_nouns and tokens[0] in self._BARE_TICKERS:
            return self._BARE_TICKERS[tokens[0]]
        return None


def _keyword_match(keyword: str, haystack: str) -> bool:
    """Whole-token keyword match, with currency-pair and phrase support.

    Whole-token rather than substring, so that short tickers like ``"es"`` or
    ``"ty"`` do not match inside unrelated words ("futures", "treasury",
    "volatility"). A substring match here would silently admit instruments the
    universe is meant to exclude.

    Two exceptions, both **measured** rather than assumed (D-058 probe P15/P16):

    * **A currency pair is ONE token, or one token with a slash through it.**
      ``"EURUSD spot"`` tokenises to ``{"eurusd", "spot"}``, so the keyword
      ``"eur"`` does not match it and ``"spot fx"`` does not either (the phrase
      is not a substring). The result was that a real G10 FX instrument — one
      of the *three* production categories — was **rejected by the universe
      that defines FX**. A currency code is therefore also matched when the
      token is **two known G10 codes concatenated** (``eurusd`` → ``eur`` +
      ``usd``), which is the shape of a spot pair and nothing else. The
      slash-separated form (``EUR/USD``) is normalised to the concatenated form
      first, because that is how a desk writes the same instrument.
    * A multi-word keyword is still matched as a substring, since a phrase like
      ``"spot fx"`` has no token boundary of its own.
    """
    if " " in keyword:
        return keyword in haystack
    tokens = {token.strip(",;:()[]") for token in haystack.split()}
    if keyword in tokens:
        return True
    if len(keyword) == 3 and keyword in _G10_CURRENCY_CODES:
        # Normalise "eur/usd" -> "eurusd" so both desk spellings behave alike.
        normalised = {
            token.replace("/", "") if token.count("/") == 1 else token for token in tokens
        }
        return any(
            len(token) == 6
            and token[:3] in _G10_CURRENCY_CODES
            and token[3:] in _G10_CURRENCY_CODES
            for token in normalised
        )
    return False


class InstrumentExpression(BaseModel):
    """How (or whether) a view can actually be expressed (Section 22.12).

    Distinguishing "analytically interesting" from "executable" is the whole
    point: credit, EM bond and commodity views are valuable inputs to the
    macro read but return ``ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT`` here,
    because the desk cannot put them on.
    """

    model_config = ConfigDict(extra="forbid")

    instrument: str = Field(
        description=f'A production instrument, or the sentinel "{NO_PRODUCTION_INSTRUMENT}".'
    )
    direction: str = "n/a"
    executable: bool = False
    reason: str = ""


class TradeIdea(BaseModel):
    """The constructive expression of the thesis (or its explicit absence).

    A thesis with no trade is a **first-class outcome**, not an exception and
    not a null: Section 16.3 requires a full ``MacroThesis`` with
    ``status=WATCH`` and ``instrument="NONE"``. Reporting "here is the trade"
    when the honest answer is "there isn't one" is how a reasoning layer
    becomes a signal generator.
    """

    model_config = ConfigDict(extra="forbid")

    instrument: str = Field(
        description=(
            f'Production instrument name, or "{NO_PRODUCTION_INSTRUMENT}" when no '
            f"clean expression exists."
        )
    )
    direction: str = Field(default="n/a", description='"long" | "short" | "n/a"')
    timeframe: str = "n/a"
    sizing_logic: str = ""
    stop_or_invalidation: str = Field(
        default="",
        description=(
            "The LTCM-lesson hard gate. Every thesis that is not an explicit "
            "no-trade must carry a non-empty invalidation condition — a position "
            "you cannot state a falsifier for is a position you cannot exit."
        ),
    )
    catalysts: list[str] = Field(default_factory=list)
    expression: InstrumentExpression | None = None

    @model_validator(mode="after")
    def _no_trade_requires_consistency(self) -> TradeIdea:
        """Keep the no-trade shape internally consistent, and gate live trades.

        Two rules, both structural:

        1. A no-trade idea must not carry a direction or a timeframe — those
           fields would render as "short, 6-12 months" in a UI even though
           there is no position, which is exactly the kind of half-true output
           this schema exists to make impossible.
        2. A **live** trade must carry a non-empty invalidation condition. This
           is the LTCM-lesson hard gate from Section 15 Module 1: a position
           without a stated falsifier is a position that cannot be exited. It
           is enforced here rather than only on ``MacroThesis`` because a
           ``TradeIdea`` can be constructed standalone, and the gate must not
           be bypassable by skipping the parent object.
        """
        if self.instrument == NO_PRODUCTION_INSTRUMENT:
            if self.direction not in {"n/a", "none", ""}:
                raise ValueError(
                    f'A no-trade idea (instrument="{NO_PRODUCTION_INSTRUMENT}") must not '
                    f"specify a direction; got {self.direction!r}."
                )
            return self

        if self.direction not in {"long", "short"}:
            raise ValueError(
                "A live trade idea must specify direction 'long' or 'short'; "
                f"got {self.direction!r}."
            )
        if not self.stop_or_invalidation.strip():
            raise ValueError(
                "A live trade idea must carry a non-empty stop_or_invalidation. "
                "Section 15 Module 1 (LTCM lesson): a position without a stated falsifier "
                "is a position that cannot be exited."
            )
        return self

    @property
    def is_trade(self) -> bool:
        return self.instrument != NO_PRODUCTION_INSTRUMENT


class MacroThesis(BaseModel):
    """The complete thesis object (Section 7.1).

    Field-by-field, this is the Section 16.2 "15 core questions" rendered as
    typed data. ``build_us_macro_thesis()`` populates it; nothing else may.
    """

    model_config = ConfigDict(extra="forbid")

    thesis_id: str
    country: str = Field(
        default="us",
        description="US-only through Phase 4 (Section 22.3 / Finding #3).",
    )
    created_at: datetime = Field(default_factory=utc_now)
    as_of: datetime = Field(
        default_factory=utc_now,
        description="The snapshot timestamp the thesis was computed from.",
    )

    # --- Views (each a small dict rather than a nested model, per Section 7.1,
    # --- because each carries a different shape of supporting detail) --------
    regime: dict[str, object]
    growth_view: dict[str, object]
    inflation_view: dict[str, object]
    policy_view: dict[str, object]

    market_pricing_gap: MarketPricingGap
    confirmation_signals: list[ConfirmationSignal] = Field(default_factory=list)
    convergence_classification: ConvergenceClassification

    # --- Probabilities. None until the Bayesian layer lands (Phase 5+); the
    # --- fields exist now so populating them is not a schema change. ---------
    prior_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    posterior_probability: float | None = Field(default=None, ge=0.0, le=1.0)

    trade_idea: TradeIdea
    scenario_distribution: list[ScenarioOutcome] = Field(default_factory=list)

    status: ThesisStatus = ThesisStatus.DRAFT
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "The union of every underlying ModelResult.warnings plus any "
            "convergence-specific caveats. Never dropped (Section 7.2 step 9)."
        ),
    )

    # --- Provenance -------------------------------------------------------
    independent_source_families: int = Field(default=0, ge=0)
    snapshot_quality_flags: list[str] = Field(
        default_factory=list,
        description="Copied from MacroDataSnapshot.data_quality_flags for audit.",
    )
    catalyst_calendar: list[dict[str, str]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _enforce_invalidation_gate(self) -> MacroThesis:
        """The LTCM-lesson hard gate (Section 15, Module 1).

        Every thesis that proposes an actual trade must state how it would be
        known to be wrong. This is enforced at the schema level rather than in
        the builder because a schema violation cannot be skipped by a future
        caller, whereas a builder check can be bypassed by constructing the
        object directly.
        """
        if self.trade_idea.is_trade and not self.trade_idea.stop_or_invalidation.strip():
            raise ValueError(
                "A thesis with a live trade idea must carry a non-empty "
                "stop_or_invalidation. Section 15 Module 1: a position without a "
                "stated falsifier is a position that cannot be exited."
            )
        return self

    @model_validator(mode="after")
    def _enforce_conflicted_blocks_trade(self) -> MacroThesis:
        """CONFLICTED must block trade construction (Section 22.10 / Finding #10).

        Not advisory — a hard error. A CONFLICTED convergence classification
        means the growth and inflation pillars point opposite ways, and
        constructing a position on that is precisely the false-confidence
        failure Module 12.2 exists to prevent.
        """
        if (
            self.convergence_classification is ConvergenceClassification.CONFLICTED
            and self.trade_idea.is_trade
        ):
            raise ValueError(
                "convergence_classification=CONFLICTED must block trade construction. "
                "Use no_trade_thesis() instead. See AGENTS.md Section 22.10 / Finding #10."
            )
        return self

    @model_validator(mode="after")
    def _enforce_scenario_probabilities(self) -> MacroThesis:
        """Scenario probabilities must sum to 1.0 when a distribution exists.

        Checked here rather than only in ``expected_value()`` because a
        malformed distribution that never reaches that function would otherwise
        sit in the object looking authoritative.
        """
        if not self.scenario_distribution:
            return self
        total = sum(s.probability for s in self.scenario_distribution)
        tolerance = get_settings().validation.prob_tolerance
        if abs(total - 1.0) > tolerance:
            raise ValueError(
                f"scenario_distribution probabilities sum to {total:.4f}, must sum to 1.0 "
                f"(tolerance {tolerance}). A distribution that does not integrate to 1 is not "
                f"a distribution, and Kelly sizing over it is meaningless."
            )
        return self
