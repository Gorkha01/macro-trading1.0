"""``/query`` — keyword routing that admits it is keyword routing (Section 8.2, D-070).

The spec is unusually direct about what this is, and the directness is the
design: *"Phase 1: simple keyword routing to relevant model outputs ... NOT an
LLM-backed free-text answer in Phase 1 — that's an explicit Phase 5+ item once
reasoning_step streaming (8.3) exists to support it properly rather than
returning an unexplainable black box."*

So this endpoint does exactly two things and claims nothing more:

1. matches the question against a declared keyword table,
2. returns the **actual thesis fields** the matched topics correspond to.

The honesty requirement is not decoration. A caller who types "will the Fed cut"
and receives a fluent paragraph will treat the paragraph as an answer, whether or
not a language model produced it. So:

* ``answer`` is a **routing description**, phrased as one ("matched topics: policy
  rules, regime — see the fields listed"), never a verdict;
* ``matched_topics`` and ``unmatched_terms`` are returned, so a caller can see
  what did *not* match and know the retrieval was partial;
* ``is_keyword_routing`` is a field, not a footnote — a machine-readable
  statement that no inference happened;
* a question matching **nothing** is a 200 with an empty result and an explicit
  note, not a fabricated answer. Returning "I could not map that" is the correct
  outcome and must not be dressed as a finding.

Why an unmatched question is not a 404
--------------------------------------
The route exists and the request was well-formed. "No topic matched" is a
*result* about the keyword table, and a 4xx would tell a client its request was
malformed when it was not.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from macro_engine.api_layer.orchestration import snapshot_to_thesis_inputs
from macro_engine.api_layer.routes_thesis import _http_status_for
from macro_engine.api_layer.snapshot_provider import get_snapshot
from macro_engine.models.instrument_selection import ThesisType
from macro_engine.thesis_layer.builder import build_us_macro_thesis
from macro_engine.thesis_layer.schemas import MacroThesis

router = APIRouter(tags=["query"])


class QueryRequest(BaseModel):
    """A question, and the thesis family to answer it from."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    country: str = "us"
    thesis_type: str | None = Field(
        default=None,
        description="Omit to use api.default_thesis_type.",
    )


class QueryResponse(BaseModel):
    """A routing result. Not an answer, and labelled so a caller cannot mistake it."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(
        description=(
            "A DESCRIPTION of the routing and what was retrieved — never a verdict "
            "about the market. Phase 1 has no language model in this path."
        )
    )
    is_keyword_routing: bool = Field(
        default=True,
        description=(
            "Machine-readable statement that no inference happened. Present as a "
            "field so a client cannot miss it in prose."
        ),
    )
    supporting_thesis_id: str | None = None
    matched_topics: list[str] = Field(default_factory=list)
    unmatched_terms: list[str] = Field(
        default_factory=list,
        description=(
            "Question tokens that matched no topic. Reported so a caller can see the "
            "retrieval was partial rather than inferring full coverage from silence."
        ),
    )
    relevant_model_outputs: list[dict[str, object]] = Field(default_factory=list)
    thesis_type_source: str | None = None
    warnings: list[str] = Field(default_factory=list)


#: The keyword table. Each entry maps a topic to the thesis fields it explains and
#: the words that select it. Kept as a module constant because it is the *whole*
#: behaviour of this endpoint — a reader should be able to see the entire routing
#: rule without following a call.
#:
#: Words are matched as whole tokens after lowercasing and stripping punctuation,
#: never as substrings: "recession" contains "session", and a substring match
#: would route an unrelated question about a trading session to the regime model.
_TOPIC_KEYWORDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "policy_rules": (
        ("fed", "fomc", "rate", "rates", "cut", "hike", "policy", "taylor", "funds"),
        ("policy_view", "market_pricing_gap"),
    ),
    "regime": (
        ("regime", "recession", "expansion", "cycle", "slowdown", "growth"),
        ("regime", "growth_view"),
    ),
    "inflation": (
        ("inflation", "cpi", "pce", "prices", "disinflation", "price"),
        ("inflation_view",),
    ),
    "labor": (
        ("labor", "labour", "jobs", "unemployment", "claims", "payrolls", "nfp", "jolts"),
        ("confirmation_signals",),
    ),
    "curve": (
        ("curve", "yield", "yields", "slope", "steepener", "flattener", "term"),
        ("trade_idea",),
    ),
    "risk": (
        ("risk", "vol", "volatility", "drawdown", "var", "stop", "invalidation"),
        ("scenario_distribution", "trade_idea"),
    ),
}


def _tokenise(question: str) -> list[str]:
    """Lowercased word tokens, punctuation stripped.

    ``str.isalnum()`` rather than a regex character class: it is Unicode-aware, so
    a question containing an accented word or a non-Latin script degrades to
    "no match" rather than producing mangled tokens that match something
    accidentally.
    """
    cleaned = "".join(c if c.isalnum() else " " for c in question.lower())
    return list(cleaned.split())


def _match_topics(tokens: list[str]) -> tuple[list[str], list[str]]:
    """``(matched_topics, unmatched_tokens)``, in declaration order.

    A token counts as matched when it equals any keyword. Whole-token equality,
    deliberately: see the note on ``_TOPIC_KEYWORDS``.
    """
    matched: list[str] = []
    consumed: set[str] = set()
    for topic, (keywords, _fields) in _TOPIC_KEYWORDS.items():
        hits = {token for token in tokens if token in keywords}
        if hits:
            matched.append(topic)
            consumed |= hits
    unmatched = sorted({token for token in tokens if token not in consumed})
    return matched, unmatched


def _project(thesis: MacroThesis, fields: tuple[str, ...]) -> list[dict[str, object]]:
    """The named thesis fields, with their values.

    ``model_dump(mode="json")`` per field so the response is JSON-safe without a
    custom encoder. A field the thesis does not carry is skipped rather than
    emitted as ``null``: an absent key means "this thesis has no such field",
    whereas ``null`` reads as "the field exists and is empty".
    """
    dumped = thesis.model_dump(mode="json")
    return [{"field": name, "value": dumped[name]} for name in fields if name in dumped]


@router.post("/query", response_model=QueryResponse)
async def query(
    req: QueryRequest,
    fresh: bool = Query(default=False),
) -> QueryResponse:
    """Route a question to thesis fields by keyword. No inference happens."""
    tokens = _tokenise(req.question)
    matched, unmatched = _match_topics(tokens)

    if not matched:
        # A real outcome, returned as one. No thesis is built: retrieving fields
        # from a thesis nobody asked for would attach an unrelated object to the
        # response and make the empty match look like a partial success.
        return QueryResponse(
            answer=(
                f"No topic matched {req.question!r}. Phase 1 routes by keyword only "
                f"— this is not a language-model answer, and an unmatched question "
                f"has no answer here rather than an invented one. Known topics: "
                f"{sorted(_TOPIC_KEYWORDS)}."
            ),
            is_keyword_routing=True,
            matched_topics=[],
            unmatched_terms=unmatched,
            relevant_model_outputs=[],
        )

    resolved_type: ThesisType | None = None
    if req.thesis_type is not None:
        try:
            resolved_type = ThesisType(req.thesis_type)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"unknown thesis_type {req.thesis_type!r}. Valid: "
                    f"{sorted(member.value for member in ThesisType)}"
                ),
            ) from exc

    # Three stages, three handlers, three messages.
    #
    # These used to share one ``try`` and one 502. That collapsed two facts that
    # are deliberately distinct — "the data source did not answer" versus "the
    # data arrived and could not be used" — into one message, and it did not
    # catch a *builder* failure at all: ``build_us_macro_thesis`` raises on
    # inputs it rejects, which is a defect in this service rather than a data
    # condition, and an uncaught raise here escaped as a stack trace with no
    # ``detail``. ``/thesis`` already reported all three correctly; one builder
    # with two failure shapes across two endpoints is one too many.
    #
    # The mapping now lives in ``routes_thesis._http_status_for`` and is imported
    # rather than restated, so the two endpoints cannot drift apart again. (It is
    # underscore-private by this package's convention and already the single
    # shared mapping — ``tests/api_layer/test_strictness.py`` exercises it
    # directly — so re-exporting it as a second public name would create two
    # entry points to one function.) Each stage re-raises through it.
    try:
        snapshot, provenance = get_snapshot(req.country, force_refresh=fresh)
    except Exception as exc:
        raise _http_status_for(exc, country=req.country) from exc

    try:
        inputs = snapshot_to_thesis_inputs(snapshot, thesis_type=resolved_type)
    except Exception as exc:
        raise _http_status_for(exc, country=req.country) from exc

    try:
        thesis = build_us_macro_thesis(
            inputs.reads,
            inputs.taylor_inputs,
            inputs.first_difference_inputs,
            thesis_type=inputs.thesis_type,
            universe=inputs.universe,
            short_yield=inputs.short_yield,
            regime=inputs.regime,
        )
    except Exception as exc:
        # Same 500-with-detail shape ``/thesis`` uses, for the same reason: the
        # builder rejecting its own orchestration's output is a bug here, and a
        # 502 would blame the data for it.
        raise HTTPException(
            status_code=500,
            detail=(
                f"the thesis builder raised {type(exc).__name__}: {exc}. The "
                f"orchestration produced inputs the builder rejected, which is a "
                f"defect in this service rather than a data condition."
            ),
        ) from exc

    fields = tuple(field for topic in matched for field in _TOPIC_KEYWORDS[topic][1])
    # Deduplicate while preserving order: two topics can name the same field
    # (`trade_idea` is reachable from both `curve` and `risk`), and a client that
    # rendered the duplicates would show the same value twice.
    seen: set[str] = set()
    unique_fields: list[str] = []
    for field in fields:
        if field not in seen:
            seen.add(field)
            unique_fields.append(field)

    answers = ", ".join(matched)
    note = (
        f" Matched topics: {answers}. The fields below are the thesis values those "
        f"topics correspond to; this endpoint retrieves, it does not interpret."
    )
    if unmatched:
        note += (
            f" {len(unmatched)} token(s) matched no topic ({unmatched}) — the retrieval is partial."
        )

    # The same union ``/thesis`` publishes: the provenance warnings AND the
    # orchestration's own disclosures. Publishing only ``provenance.warnings()``
    # silently dropped everything the orchestration learned while deriving the
    # inputs — the curve legs it had to ignore, the unit traps it asserted, the
    # fields it could not read. Those are exactly the disclosures a caller needs
    # to judge how much of the thesis to trust, and ``/query`` was the one
    # endpoint that withheld them. Deduplicated in order, as ``/thesis`` does,
    # because the two lists overlap by design.
    warnings: list[str] = []
    for warning in [*provenance.warnings(), *inputs.warnings]:
        if warning not in warnings:
            warnings.append(warning)

    # The STALE disclosure travels as the structured warning above and nowhere
    # else. It used to be appended to ``note`` as prose too, behind a substring
    # check on the warning text — two representations of one fact, which can
    # disagree the moment the wording changes. A client parses the list.
    return QueryResponse(
        answer=f"Keyword routing for {req.question!r}." + note,
        is_keyword_routing=True,
        supporting_thesis_id=thesis.thesis_id,
        matched_topics=matched,
        unmatched_terms=unmatched,
        relevant_model_outputs=_project(thesis, tuple(unique_fields)),
        thesis_type_source=next(
            (n.source for n in inputs.notes if n.name == "thesis_type"),
            None,
        ),
        warnings=warnings,
    )
