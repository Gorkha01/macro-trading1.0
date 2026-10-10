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
from macro_engine.models.probability import ScenarioDistributionStatus as ScenarioDistributionStatus
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
    "ScenarioDistributionStatus",
    "ScenarioOutcome",
    "SignalDirection",
    "ThesisStatus",
    "TradeIdea",
    "is_no_production_instrument",
]


# The canonical no-instrument sentinel. Section 22.12: a thesis with no
# production expression must say so explicitly rather than naming an
# instrument the desk cannot actually put on.
NO_PRODUCTION_INSTRUMENT = "NONE"


def is_no_production_instrument(instrument: str) -> bool:
    """Whether ``instrument`` names the no-production sentinel, case-insensitively.

    **One definition, consulted by every site that asks the question.** The
    sentinel was compared case-SENSITIVELY by ``TradeIdea`` while
    ``ProductionUniverse`` compared it case-insensitively, so the same string
    meant "no trade" in one class and "a live trade that must state a direction
    and a falsifier" in the other — the one-character split D-058 probe P17 fixed
    inside ``permits``, re-created one class away. ``portfolio/risk_budget`` reads
    it too, so a re-typed literal there cannot disagree either.
    """
    return instrument.strip().upper() == NO_PRODUCTION_INSTRUMENT


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
        description=(
            "Module 13 family, carried through from the source ModelResult by "
            "`signals.py`; None if the result was unmapped. NOTE this is NOT what "
            "`count_independent_families()` reads — that function takes a "
            "`list[ModelResult]` and reads each result's OWN `source_family`, so "
            "it never sees a ConfirmationSignal (measured 2026-10-06: nothing in "
            "`src/` reads this field; it is published on the thesis so a reader "
            "can group confirmations by provenance, while the family COUNT comes "
            "from the builder's reads)."
        ),
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

    **Country (§22.3, added 2026-10-10).** Section 22.3 requires each
    multi-country increment to have *its own instrument set*, and names the
    failure it rejects: a country's set must not be the US set with a different
    label. ``country`` therefore selects a **separate plan** — its own
    instrument lists AND its own keyword sets — rather than filtering the US
    lists. The two plans genuinely differ:

    * **US** — USTs (cash + TU/FV/TY/US futures), SOFR futures, Fed funds
      futures, TIPS/breakevens; equity expressed through ES/NQ/RTY.
    * **GB** — gilts (conventional cash + futures), index-linked gilts (the UK
      analogue of TIPS), **short-sterling futures** (the LSEG/ICE contract
      whose underlying is the SONIA-compounded 3-month rate — the UK's own
      short-rate instrument, distinct from SOFR), SONIA OIS, and the FTSE 100.
      The keyword vocabulary is the UK's: ``gilt``, ``gilt-edged``, ``sonia``,
      ``short sterling``, ``short-sterling``, ``ftse``, ``boe`` — none of which
      appears in the US plan.

    ``fx`` is **shared** between the plans and deliberately so: G10 FX is one
    market, and a GBP/USD instrument is the same tradeable object whichever
    country's thesis names it. Only ``rates`` and ``equity`` are country
    plans, because only those are genuinely different instruments in the two
    markets. This is the asymmetry Section 22.3 turns on — the point is not
    that *every* category differ, it is that a category which DOES differ must
    not be faked by relabelling.
    """

    model_config = ConfigDict(extra="forbid")

    country: str = Field(
        default="us",
        description=(
            "ISO-3166 alpha-2 lowercase. Selects the instrument plan (Section "
            "22.3). 'us' through Phase 4; 'gb' and 'eu' added by the multi-country "
            "increment. An unknown code is rejected at construction rather than "
            "silently falling back to the US plan — a fallback would serve US "
            "instruments to another country's thesis, the exact relabel Section "
            "22.3 rejects."
        ),
    )

    # The three lists are filled from the country plan by the model validator
    # below. They are declared with an explicit empty default (rather than as
    # ``default_factory`` lambdas reading ``self.country`` — which a field
    # default cannot do, since defaults are evaluated before the model exists)
    # and populated in one place, so the plan is the single source of truth for
    # both the lists AND the keyword sets that must agree with them.
    rates: list[str] = Field(
        default_factory=list,
        description=(
            "Country-plan rates instruments (Section 22.3). Populated from the "
            "plan selected by ``country``; do not pass a US list to a gb universe."
        ),
    )
    fx: list[str] = Field(
        default_factory=list,
        description="G10 FX spot/forwards. Shared across country plans by design.",
    )
    equity: list[str] = Field(
        default_factory=list,
        description="Country-plan equity instruments (Section 22.3).",
    )

    # PLANS ------------------------------------------------------------------
    # One entry per implemented country. ``rates``/``equity`` differ per plan
    # (the instruments are genuinely different); ``fx`` is shared because G10 FX
    # is one market. Order of the tuples is the order instruments are published
    # in, which the tests read.
    _US_PLAN: dict[str, tuple[str, ...]] = {
        "rates": (
            "UST cash (2yr, 5yr, 10yr, 30yr)",
            "UST futures (TU, FV, TY, US)",
            "SOFR futures",
            "Fed funds futures",
            "TIPS cash and breakevens",
        ),
        "fx": ("G10 FX spot", "G10 FX forwards"),
        "equity": ("Broad equity indices (ES, NQ, RTY)",),
    }
    #: The UK plan. Every rates/equity entry names an instrument that trades in
    #: London and has no US equivalent: gilts are not USTs, short sterling is
    #: not SOFR, and the FTSE 100 is not the S&P. Section 22.3's test is exactly
    #: whether this list would read as wrong if the label said "us" — it does.
    _GB_PLAN: dict[str, tuple[str, ...]] = {
        "rates": (
            "Conventional gilts (2yr, 5yr, 10yr, 30yr)",
            "Gilt futures (short sterling, long gilt)",
            "Index-linked gilts",
            "Short-sterling futures",
            "SONIA OIS swaps",
        ),
        "fx": ("G10 FX spot", "G10 FX forwards"),
        "equity": ("FTSE 100 index futures",),
    }
    #: The euro-area plan. Every rates/equity entry names an instrument that
    #: trades in the euro area and has no US or UK equivalent: **Bunds** are the
    #: euro area's benchmark (not USTs, not gilts), the **Bund future** and
    #: **BTP/SPGB/OAT/Bonos** futures are the contract complex, **ESTR** (the
    #: ECB's euro short-term rate) is the risk-free reference — the euro-area
    #: analogue of SOFR and SONIA and distinct from both — and the **Euro
    #: Stoxx 50 / DAX** are the euro-area equity benchmarks. Section 22.3's test
    #: is whether this list would read as wrong if the label said "us" or "gb";
    #: it would.
    #:
    #: NON-NEGOTIABLE, and the reason the list is not the UK plan relabelled:
    #: the euro area has ONE monetary policy but TWENTY sovereign issuers, so
    #: its rates market is not a single-country gilt/UST market — it is a
    #: benchmark (Bund) plus an intra-area spread complex (BTP-Bund, OAT-Bund,
    #: etc.). The keyword set below therefore includes the spread vocabulary
    #: ("bund", "btp", "oat", "bonos", "spgb", "spread") that neither the US nor
    #: the UK set carries, and the instrument list names both the benchmark and
    #: the spread instruments.
    _EU_PLAN: dict[str, tuple[str, ...]] = {
        "rates": (
            "Euro-area government bonds (Bunds, OATs, BTPs, Bonos, SPGBs)",
            "Bund futures (Euro-Bund, Euro-Bobl, Euro-Schatz)",
            "Euro-area spread instruments (BTP-Bund, OAT-Bund)",
            "ESTR futures and swaps",
            "Euro-area OIS swaps",
        ),
        "fx": ("G10 FX spot", "G10 FX forwards"),
        "equity": ("Euro Stoxx 50 index futures", "DAX index futures"),
    }
    #: Country code -> plan. A code absent here is rejected by the validator.
    _PLANS: dict[str, dict[str, tuple[str, ...]]] = {}

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
    #: The UK rates vocabulary. Kept SEPARATE from the US set and selected by
    #: country, so that a gb thesis cannot be admitted on the strength of a US
    #: keyword (and vice versa). Note what is deliberately ABSENT: ``ust``,
    #: ``sofr``, ``tips``, ``tnote``. A gb universe that accepted "UST futures"
    #: would be the relabel Section 22.3 rejects.
    _GB_RATES_KEYWORDS: tuple[str, ...] = (
        "gilt",
        "gilts",
        "gilt-edged",
        "sonia",
        "short sterling",
        "short-sterling",
        "short stg",
        "index-linked",
        "index linked",
        "linker",
        "long gilt",
        "boe",
        "bank of england",
        # Curve-shape vocabulary is market-neutral and shared, so a
        # duration-weighted steepener is recognised in both plans.
        "steepener",
        "flattener",
        "steepening",
        "flattening",
        "duration-weighted",
        "butterfly",
        "curve",
        "swap",
        "ois",
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
    #: The UK equity vocabulary. The US-only words (``s&p``, ``spx``,
    #: ``nasdaq``, ``russell``) are deliberately ABSENT, so a gb thesis naming
    #: the S&P 500 is rejected rather than silently permitted as "equity". The
    #: generic "equity index"/"index futures" phrases are shared, because a
    #: broad-index expression is the same *kind* of instrument in both markets
    #: and the country plan supplies the actual index.
    _GB_EQUITY_KEYWORDS: tuple[str, ...] = (
        "equity index",
        "equity indices",
        "index futures",
        "ftse",
        "ftse 100",
        "ftse 250",
        "uk equity",
        "london equity",
    )
    #: The euro-area rates vocabulary. Kept SEPARATE from the US and UK sets and
    #: selected by country, so a eu thesis cannot be admitted on the strength of
    #: a US or UK keyword. Note what is deliberately ABSENT: ``ust``,
    #: ``treasury``, ``sofr``, ``tips``, ``tnote`` (US) and ``gilt``, ``sonia``,
    #: ``short sterling``, ``linker`` (UK). A eu universe that accepted "UST
    #: futures" or "gilts" would be the relabel Section 22.3 rejects. What is
    #: PRESENT and euro-area-specific is the sovereign-spread vocabulary
    #: (``bund``, ``btp``, ``oat``, ``bonos``, ``spgb``, ``euro-bund``, ``bobl``,
    #: ``schatz``, ``estr``) — the euro area's defining rates structure, which
    #: neither single-sovereign market has.
    _EU_RATES_KEYWORDS: tuple[str, ...] = (
        "bund",
        "bunds",
        "euro-bund",
        "euro bobl",
        "bobl",
        "schatz",
        "btp",
        "btps",
        "oat",
        "oats",
        "bonos",
        "spgb",
        "spgbs",
        "euro-area government",
        "euro area government",
        "eurozone",
        "euro-area bond",
        "euro area bond",
        "estr",
        "euro short-term rate",
        "euribor",
        # Sovereign-spread vocabulary: the euro area's defining rates feature,
        # absent from both the US and UK sets because neither has an intra-area
        # credit structure.
        "btp-bund",
        "oat-bund",
        "bonos-bund",
        "spread",
        "periphery",
        # Curve-shape vocabulary is market-neutral and shared, so a
        # duration-weighted steepener is recognised in every plan.
        "steepener",
        "flattener",
        "steepening",
        "flattening",
        "duration-weighted",
        "butterfly",
        "curve",
        "swap",
        "ois",
    )
    #: The euro-area equity vocabulary. The US-only (``s&p``, ``spx``,
    #: ``nasdaq``, ``russell``) and UK-only (``ftse``) words are deliberately
    #: ABSENT, so a eu thesis naming the S&P 500 or the FTSE 100 is rejected.
    _EU_EQUITY_KEYWORDS: tuple[str, ...] = (
        "equity index",
        "equity indices",
        "index futures",
        "euro stoxx",
        "eurostoxx",
        "stoxx",
        "dax",
        "cac",
        "ibex",
        "ftse mib",
        "euro-area equity",
        "euro area equity",
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

    @model_validator(mode="after")
    def _populate_from_country_plan(self) -> ProductionUniverse:
        """Fill the instrument lists from the plan ``country`` selects.

        A single place where ``country`` becomes lists, so the plan is the only
        source of truth and a new country cannot be half-added (lists without
        keywords, or a keyword set that admits the wrong market's instruments).

        **An unknown country is rejected, not defaulted.** Falling back to the
        US plan would serve USTs and SOFR to, say, a ``de`` thesis — the exact
        relabel Section 22.3 rejects — and the failure would be invisible,
        because the resulting universe is internally consistent. Raising here
        makes "this country has no instrument set" a loud, testable fact, which
        is also what ``CountrySettings._no_false_genericity_claim`` enforces one
        layer up.
        """
        plans = {"us": self._US_PLAN, "gb": self._GB_PLAN, "eu": self._EU_PLAN}
        if self.country not in plans:
            raise ValueError(
                f"ProductionUniverse.country={self.country!r} has no instrument "
                f"plan (Section 22.3). Implemented: {sorted(plans)}. A country "
                f"without its own instrument set must not borrow another's — "
                f"that is the relabelled-universe failure 22.3 rejects."
            )
        plan = plans[self.country]
        # Only fill a list the caller left empty, so an explicit override (a
        # narrower universe for a specific run) is preserved rather than
        # clobbered. An explicit US list on a gb universe is the caller's
        # stated choice, not this validator's to silently correct.
        if not self.rates:
            self.rates = list(plan["rates"])
        if not self.fx:
            self.fx = list(plan["fx"])
        if not self.equity:
            self.equity = list(plan["equity"])
        return self

    @property
    def _rates_keywords(self) -> tuple[str, ...]:
        """The rates vocabulary for THIS country's plan.

        The US, UK and euro-area sets are disjoint in their market-specific
        terms (no ``ust``/``sofr`` in the UK or EU sets; no ``gilt``/``sonia``
        in the US or EU sets; no ``bund``/``btp``/``estr`` in the US or UK
        sets), so a country's thesis cannot be admitted by another country's
        instrument vocabulary. The shared curve-shape words are the deliberate
        exception — a steepener is a steepener in every market.
        """
        if self.country == "gb":
            return self._GB_RATES_KEYWORDS
        if self.country == "eu":
            return self._EU_RATES_KEYWORDS
        return self._RATES_KEYWORDS

    @property
    def _equity_keywords(self) -> tuple[str, ...]:
        """The equity vocabulary for THIS country's plan (see above)."""
        if self.country == "gb":
            return self._GB_EQUITY_KEYWORDS
        if self.country == "eu":
            return self._EU_EQUITY_KEYWORDS
        return self._EQUITY_KEYWORDS

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
        if is_no_production_instrument(instrument):
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

        Excluded categories are checked **first**. That ordering matters, and the
        reason is measured rather than assumed: a string can carry an excluded
        word *and* a genuine keyword at once. Measured,
        ``category_for("US HY credit index futures")`` is ``None`` while
        ``category_for("index futures")`` is ``"equity"`` — the first carries the
        equity keyword ``"index futures"`` **and** the excluded ``"credit"``, so
        without the exclusion it would be admitted as equity, and a false permit
        here means proposing a trade the desk cannot execute. (The earlier note
        gave ``"US HY credit index"`` as the example, but that string carries no
        keyword at all — bare ``"index"`` is not one; measured
        ``category_for("some index") is None`` — so it was never the case being
        guarded.)
        """
        if is_no_production_instrument(instrument):
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
        # Country-aware keyword sets (Section 22.3): a gb universe reads the UK
        # rates/equity vocabulary, so a US-only instrument ("SOFR futures") is
        # not admitted into a UK thesis and vice versa.
        for category, keywords in (
            ("rates", self._rates_keywords),
            ("fx", self._FX_KEYWORDS),
            ("equity", self._equity_keywords),
        ):
            if any(_keyword_match(keyword, needle) for keyword in keywords):
                return category
        return None

    #: The UK bare-ticker vocabulary. ``G``/``long gilt`` for the 10y+ gilt
    #: future; ``short sterling`` is a phrase handled in the keyword set, not
    #: here. Deliberately does NOT include ``us`` (a US long-bond root and also
    #: the country code), ``es``/``nq``/``rty``/``ym`` (US equity roots), or any
    #: of ``tu``/``fv``/``ty`` — so a gb universe cannot be entered by a US
    #: ticker.
    _GB_BARE_TICKERS: dict[str, str] = {
        "g": "rates",
        "gl": "rates",
        "ftse": "equity",
        "z": "equity",
    }

    #: The euro-area bare-ticker vocabulary. Eurex contract roots: ``FGBL``
    #: (Euro-Bund), ``FGBM`` (Euro-Bobl), ``FGBS`` (Euro-Schatz), ``FBTP``
    #: (Euro-BTP), ``FOAT`` (Euro-OAT) for rates; ``FESX`` (Euro Stoxx 50) and
    #: ``FDAX`` (DAX) for equity. These are FOUR-character Eurex roots, not the
    #: US two-letter roots — so there is no ``es``/``tu``/``ty`` collision to
    #: guard against, and the table is kept deliberately disjoint from the US
    #: one. Absent by construction: every US root, so a eu universe cannot be
    #: entered by ``ES futures`` or ``TU futures`` (the relabel §22.3 rejects).
    _EU_BARE_TICKERS: dict[str, str] = {
        "fgbl": "rates",
        "fgbm": "rates",
        "fgbs": "rates",
        "fbtp": "rates",
        "foat": "rates",
        "fesx": "equity",
        "fdax": "equity",
    }

    def _bare_ticker_category(self, needle: str) -> str | None:
        """Match a bare futures ticker as a standalone token.

        Only two shapes count: the ticker alone ("TU"), or the ticker directly
        followed by a contract noun ("TU futures", "ES options"). Anything
        looser would let "US HY credit index" through on the strength of the
        word "US".

        **Country-aware (§22.3).** The ticker table is selected by ``country``,
        because the roots are market-specific: ``us`` is both the US long-bond
        root and the country code, so a gb or eu universe must not read the US
        table (it would admit "US futures" into a UK or euro thesis). The euro
        table is disjoint from the US one by construction — Eurex four-letter
        roots against US two-letter roots — so neither can enter the other.
        Bare single letters are kept only where they are the actual exchange
        root AND are not a substring risk — the two-token form ("gl futures") is
        the shape a desk uses, so the single-letter form is admitted only
        alongside a contract noun.
        """
        tokens = [t.strip(",;:()[]") for t in needle.split()]
        if not tokens:
            return None
        if self.country == "gb":
            table = self._GB_BARE_TICKERS
        elif self.country == "eu":
            table = self._EU_BARE_TICKERS
        else:
            table = self._BARE_TICKERS
        contract_nouns = {"futures", "future", "options", "option", "contract", "contracts"}
        if len(tokens) == 1 and tokens[0] in table:
            return table[tokens[0]]
        if len(tokens) == 2 and tokens[1] in contract_nouns and tokens[0] in table:
            return table[tokens[0]]
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
    point: credit, EM bond and commodity views are valuable inputs to the macro
    read but cannot be put on, so the thesis must say so rather than naming them
    as trades.

    **The sentinel this class carries is** ``NO_PRODUCTION_INSTRUMENT``
    (``"NONE"``), the same one ``TradeIdea.instrument`` uses — see the field
    description below. It is **not**
    ``ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT``: that is a *models*-layer value
    (``models/instrument_selection.py``) which reaches a thesis through
    ``TradeIdea.instrument`` by the pass-through path **O-53** records, never
    through this class. The earlier note said those views "return
    ``ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT`` here", naming a sentinel this
    field's own description contradicts and a value nothing puts here.

    Measured 2026-10-06: nothing in ``src/`` or ``tests/`` constructs this class,
    so ``TradeIdea.expression`` is always ``None`` and this is a forward-declared
    record rather than a live producer. ``direction``/``executable`` therefore
    carry no validation: a guard on a class nothing builds could never fire (the
    D-045/D-046 class). Recorded rather than repaired.
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
        if is_no_production_instrument(self.instrument):
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
        """Whether this idea names a live position rather than the no-trade sentinel.

        The sentinel test is case-insensitive via
        :func:`is_no_production_instrument`, so ``"none"`` and ``"NONE"`` agree.
        It was an exact comparison, which made this property answer ``True`` for
        ``"none"`` while ``ProductionUniverse.permits("none")`` answered ``True``
        for "no trade" — the same one-character split, in the two directions
        (F-TSC-002).
        """
        return not is_no_production_instrument(self.instrument)


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
    scenario_distribution_status: ScenarioDistributionStatus = Field(
        default="empty_no_trade",
        description=(
            "Whether ``scenario_distribution`` is fit to size a position with "
            "(Section 25 of the economic-integrity directive). ``calibrated`` "
            "means every probability rests on a calibrated value; "
            "``SCENARIO_DISTRIBUTION_UNAVAILABLE`` means a distribution is "
            "published for a human to read but its probabilities are "
            "``uncalibrated_illustrative`` placeholders and it MUST NOT drive "
            "Kelly sizing; ``empty_no_trade`` means there is no distribution "
            "because the verdict cannot carry a thesis. Default is the safest "
            "value, so a thesis built without stating its provenance is treated "
            "as unsizable rather than silently sized."
        ),
    )

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
        # The SAME leaf the consumer reads. `expected_value`
        # (models/probability.py) and `risk_budget` both gate on
        # `probability.probability_sum_tolerance`; this validator used
        # `validation.prob_tolerance`, a SECOND leaf with the same meaning but a
        # different `calibration_status` ('conventional' vs
        # 'uncalibrated_illustrative'). Both read 0.01 today, so nothing is
        # broken — but recalibrating either one alone would split the gate from
        # the function it gates, letting a distribution pass here and be refused
        # there (or the reverse). One leaf, one boundary (F-TSC-004).
        tolerance = get_settings().probability.probability_sum_tolerance
        if abs(total - 1.0) > tolerance:
            raise ValueError(
                f"scenario_distribution probabilities sum to {total:.4f}, must sum to 1.0 "
                f"(tolerance {tolerance}). A distribution that does not integrate to 1 is not "
                f"a distribution, and Kelly sizing over it is meaningless."
            )
        return self

    @model_validator(mode="after")
    def _enforce_scenario_status_matches_distribution(self) -> MacroThesis:
        """The status field must be consistent with what is actually present.

        Section 25 makes the status load-bearing — a downstream sizer reads it to
        decide whether sizing is permitted — so a status that disagrees with the
        distribution would be worse than no status at all. Two directions, both
        checked because both are reachable:

        * a non-empty distribution declared ``empty_no_trade`` would hide a real
          (if unsizable) distribution from a reader;
        * an empty distribution declared ``calibrated`` or
          ``SCENARIO_DISTRIBUTION_UNAVAILABLE`` would claim a distribution that
          is not there.

        Note this validator does **not** try to re-derive whether the
        probabilities are calibrated: that fact lives in the config
        (``scenario_probabilities_are_calibrated()``) and is stamped by the
        builder, which is the only place that knows it. The validator's job is
        internal consistency, not provenance.
        """
        if self.scenario_distribution and self.scenario_distribution_status == "empty_no_trade":
            raise ValueError(
                "scenario_distribution has "
                f"{len(self.scenario_distribution)} branches but "
                "scenario_distribution_status='empty_no_trade'. A non-empty "
                "distribution must be classified as 'calibrated' or "
                "'SCENARIO_DISTRIBUTION_UNAVAILABLE' so a reader can tell which."
            )
        if not self.scenario_distribution and self.scenario_distribution_status != "empty_no_trade":
            raise ValueError(
                f"scenario_distribution is empty but "
                f"scenario_distribution_status={self.scenario_distribution_status!r}. An empty "
                f"distribution has no probabilities to be calibrated or unavailable."
            )
        return self

    @property
    def scenario_sizing_permitted(self) -> bool:
        """Whether Section 25 permits Kelly sizing from this thesis's scenarios.

        ``True`` only for a **calibrated, non-empty** distribution. This is the
        single question a sizer must ask before calling
        ``apply_fractional_kelly`` on ``self.scenario_distribution``, and it is a
        property rather than a documented convention so the answer cannot be
        inferred wrong. Measured on every live thesis today: ``False`` — the
        probabilities are the specification's illustrative literals.
        """
        return self.scenario_distribution_status == "calibrated"
