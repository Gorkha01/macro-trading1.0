"""``/thesis/{country}`` — the thesis, or an honest failure (Section 8.2, D-070).

What Section 8.2's sample gets wrong, and what replaces it
---------------------------------------------------------
The sample is three lines and every one of them diverges from the shipped code:

========================================  ==========================================
sample                                    measured
========================================  ==========================================
``fetch_full_snapshot(client, country)``  does not exist; the entry point is
                                          ``build_snapshot`` returning
                                          ``(snapshot, report)``
``build_us_macro_thesis(snapshot)``       raises ``TypeError: missing 6 required
                                          arguments`` (``.probe/d070_sig.py``)
``except OpenBBFetchError``               catches the wrong failure; the
                                          orchestration's refusals are a different
                                          exception class entirely
========================================  ==========================================

The first two are the orchestration module's job. This file's job is the third:
mapping failures onto the right status codes, and — the part that is easy to get
wrong — **never mapping one onto a ``WATCH`` thesis.**

The status codes, and why each is what it is
--------------------------------------------
================  ==================================================================
**501**           the country is not implemented. ``NotImplementedError`` from
                  Section 22.3. Not a 404: the route exists, the *capability*
                  does not, and 404 would suggest a typo in the URL.
**502**           a dependency failed — the provider did not answer
                  (``SnapshotUnavailableError``) or the data was unusable
                  (``OrchestrationError``). The remedy is upstream of this code.
**500**           reserved. If it appears, this code is wrong, and the two 502
                  cases above are deliberately distinct so that a 500 means what
                  it says.
================  ==================================================================

**A ``WATCH`` thesis is never a failure response.** This is the single most
important line in the file. ``build_us_macro_thesis`` returns ``WATCH`` when Q6,
Q7 or Q8 stands the sentence down — a real analytical finding with real evidence
attached. Section 16.3 is explicit that a stand-down is not a fallback for
missing data. So a 200 with ``status="WATCH"`` means "we read the world and the
models agree there is no edge", and a 502 means "we could not read the world".
Collapsing them would let a broken feed publish "no trade today".

Direction and instrument are reported as the selector published them
-------------------------------------------------------------------
Measured during D-069 (O-87): ``select_instrument`` publishes two different
shapes — a dict under a live thesis and a bare sentinel string under a
stand-down. This router does not assume a dict; it passes the published value
through and lets the schema's own types carry it, so a future change in the
selector's shape is a schema error rather than a ``TypeError`` in a handler.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from macro_engine.api_layer.orchestration import (
    OrchestrationError,
    snapshot_to_thesis_inputs,
)
from macro_engine.api_layer.snapshot_provider import (
    SnapshotProvenance,
    SnapshotUnavailableError,
    get_snapshot,
)
from macro_engine.models.instrument_selection import ThesisType
from macro_engine.thesis_layer.builder import build_us_macro_thesis
from macro_engine.thesis_layer.schemas import MacroThesis

router = APIRouter(tags=["thesis"])


class ThesisResponse(BaseModel):
    """A ``MacroThesis`` plus how it was produced.

    The thesis alone is not the whole answer. Two facts a caller needs and the
    ``MacroThesis`` schema does not carry:

    * **how old the snapshot is** — the thesis has an ``as_of``, but not the age,
      and an age is what a reader needs to decide whether to act on it;
    * **which derivations were assumed** — the orchestration's notes, including
      the ``thesis_type`` it took as the API default when the caller named none.

    Returned as a wrapper rather than by adding fields to ``MacroThesis``,
    because the thesis schema is the *analytical* object and this is the
    *serving* one. Mixing them would mean the provenance became part of every
    persisted thesis, and an assumption made by this API would be indistinguishable
    from a fact about the world.
    """

    model_config = ConfigDict(extra="forbid")

    thesis: MacroThesis
    provenance: SnapshotProvenance
    derivation_notes: list[dict[str, str | None]] = Field(
        default_factory=list,
        description=(
            "Every derived input, with its source. This is the part of the pipeline "
            "a reader cannot check by looking at the thesis, so it travels with it."
        ),
    )
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "The provenance's disclosure lines plus the orchestration's, deduplicated. "
            "Carried here as well as on the thesis because a caller reading only this "
            "wrapper should not have to know which list a given warning landed in."
        ),
    )
    thesis_type_source: str = Field(
        description=(
            '"supplied by the caller" or "assumed from api.default_thesis_type". '
            "Stated as its own field because it is the one analytical choice this "
            "endpoint makes on the caller's behalf."
        )
    )


def _http_status_for(exc: Exception, *, country: str) -> HTTPException:
    """Map an exception onto the status code that describes it.

    One function rather than a ``try/except`` chain in each handler, so the
    mapping is stated once and a test can exercise it without an HTTP client.
    """
    if isinstance(exc, NotImplementedError):
        return HTTPException(
            status_code=501,
            detail=(
                f"country '{country}' is not implemented. Section 22.3: the system is "
                f"US-only through Phase 4, and this is not a label to re-point — a "
                f"different country needs its own series set, its own central-bank "
                f"reaction function and its own instrument universe. "
                f"Original: {exc}"
            ),
        )
    if isinstance(exc, SnapshotUnavailableError):
        return HTTPException(
            status_code=502,
            detail=(
                f"the data source did not produce a usable snapshot, so no thesis can "
                f"be built: {exc}. This is NOT a no-trade verdict — Section 16.3 "
                f"forbids reporting missing data as a stand-down."
            ),
        )
    if isinstance(exc, OrchestrationError):
        return HTTPException(
            status_code=502,
            detail=(
                f"the snapshot could not be turned into thesis inputs "
                f"(unusable field(s): {list(exc.fields)}): {exc}. This is NOT a "
                f"no-trade verdict — the models never ran."
            ),
        )
    raise exc


@router.get("/{country}", response_model=ThesisResponse)
async def get_thesis(
    country: str,
    thesis_type: str | None = Query(
        default=None,
        description=(
            "Which analytical family to express (Section 22.3.1's seven). Omit to use "
            "api.default_thesis_type, which the response reports in thesis_type_source. "
            "Not inferred from the data: the same policy-path gap can be an outright, "
            "a curve trade or an FX carry, and choosing is part of the analysis."
        ),
    ),
    fresh: bool = Query(
        default=False,
        description="Rebuild the snapshot rather than serving the cached one (~10s-220s).",
    ),
) -> ThesisResponse:
    """Build the US macro thesis, or explain why it could not be built."""
    resolved_type: ThesisType | None = None
    if thesis_type is not None:
        try:
            resolved_type = ThesisType(thesis_type)
        except ValueError as exc:
            valid = sorted(member.value for member in ThesisType)
            raise HTTPException(
                status_code=422,
                detail=(f"unknown thesis_type {thesis_type!r}. Section 22.3.1 defines: {valid}"),
            ) from exc

    try:
        snapshot, provenance = get_snapshot(country, force_refresh=fresh)
    except Exception as exc:
        raise _http_status_for(exc, country=country) from exc

    try:
        inputs = snapshot_to_thesis_inputs(snapshot, thesis_type=resolved_type)
    except Exception as exc:
        raise _http_status_for(exc, country=country) from exc

    try:
        thesis = build_us_macro_thesis(
            inputs.reads,
            inputs.taylor_inputs,
            inputs.first_difference_inputs,
            thesis_type=inputs.thesis_type,
            universe=inputs.universe,
            short_yield=inputs.short_yield,
        )
    except Exception as exc:
        # The builder's own failures are a bug here, not a data condition, so
        # they are NOT mapped onto a 502. Letting them propagate as a 500 is the
        # honest signal: the two 502 classes above exist precisely so that a 500
        # means what it says.
        raise HTTPException(
            status_code=500,
            detail=(
                f"the thesis builder raised {type(exc).__name__}: {exc}. The "
                f"orchestration produced inputs the builder rejected, which is a "
                f"defect in this service rather than a data condition."
            ),
        ) from exc

    type_note = next(
        (n for n in inputs.notes if n.name == "thesis_type"),
        None,
    )

    # Provenance first, then the orchestration's warnings, deduplicated in order.
    # The two lists overlap by design (the snapshot's flags reach the thesis AND
    # the provenance), and a caller that saw the same line twice would reasonably
    # wonder what else was double-counted.
    combined: list[str] = []
    for warning in [*provenance.warnings(), *inputs.warnings]:
        if warning not in combined:
            combined.append(warning)

    return ThesisResponse(
        thesis=thesis,
        provenance=provenance,
        derivation_notes=[
            {"name": n.name, "value": n.value, "source": n.source, "window": n.window}
            for n in inputs.notes
        ],
        warnings=combined,
        thesis_type_source=(type_note.source if type_note else "supplied by the caller"),
    )
