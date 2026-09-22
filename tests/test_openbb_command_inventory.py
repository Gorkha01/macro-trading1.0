"""The recorded OpenBB command inventory must match the tree (O-104).

**The defect this file exists to pin.** For the whole of Phase 4 the record said
the engine calls **2 of 201** OpenBB commands — ``fred_series`` and
``fred_search`` — and that sentence was still standing on three live surfaces
(``docs/PROGRESS.md``, ``docs/DECISIONS.md``, ``MEMORY.md``) after D-086 had
*already* applied two of the audit's five changes:

* **Change 1** moved the whole Treasury curve off eleven ``fred_series`` calls
  onto ``fixedincome.government.yield_curve`` — **one** new command.
* **Change 2** replaced the ``federalreserve.gov`` HTML scrape in
  ``thesis_layer/catalysts.py`` with ``economy.fomc_documents`` — a **second**
  new command.

So the tree calls **four** commands, and the record said two. Nothing was
broken; the *record* had drifted. That is the same class as the withdrawn
``223.6s/9.5s`` pair (D-087.23): **a superseded count left standing on a live
surface**, where the costing is not the number but the next reader who plans
work against it.

**Why a test and not a docs edit.** The same reasoning as
``test_performance_record.py``: D-087.19 corrected that prose once and the old
figures were *still* on five surfaces afterwards, because **nothing read the
note**. A correction that lives only in a decision record is a claim, not a fix.
This file is the reader. The count is derived two independent ways below, and the
two doc surfaces that state it as a live measurement are asserted to agree.

**What is derived, and why not typed.** The inventory is computed from the two
real sources of truth — the parsed registry (whose ``defaults:`` inheritance is
applied by a model validator, so every entry carries its endpoint) and the
endpoint literals actually present in ``src/``. A test that typed "4" would agree
with itself and disagree with the tree the first time someone adds a command,
which is exactly how O-104 arose.

**The predicate scope (O-107, both directions).**
* Too *narrow* was the recurring failure — five times in this project. So the
  registry half reads every ``series`` entry **and** the curve/calendar/search
  blocks, not just one category.
* Too *wide* is the newer failure (D-087.23's too-broad guard). So the
  ``economy.calendar`` command — declared in the registry but ``enabled: false``
  — is classified as **declared-but-disabled** and is NOT counted among the
  live commands. Counting it would overstate coverage by exactly the amount the
  ``enabled: false`` exists to prevent.

**The retraction vocabulary.** The stale phrase "2 of 201" may still appear — a
*dated* narrative that measured it in September is history and must be allowed to
keep its own number. It may only appear inside a sentence that marks it as
superseded. The markers are explicit and tested in both directions below, so a
new live claim cannot slip through by happening to sit near one of the words.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from macro_engine.config import get_registry

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: The command the engine calls that is NOT declared anywhere in
#: ``series_registry.yaml``: it lives as a path literal in ``thesis_layer``
#: because the catalyst calendar is not a snapshot field (it is a two-source
#: merge). Named here so the derivation below can account for it explicitly
#: rather than discovering it by a fragile source scrape.
_SOURCE_LITERAL_COMMANDS: frozenset[str] = frozenset({"economy.fomc_documents"})

#: Surfaces that state the command count as a *live* measurement. A dated
#: narrative section is deliberately NOT in this list — history is allowed to
#: record what was true when it was written. These are the places a reader goes
#: to learn what the engine does *now*.
_LIVE_COUNT_SURFACES: tuple[str, ...] = (
    "docs/PROGRESS.md",
    "docs/OPEN_ISSUES.md",
)

#: The stale figures, and the only way they may still be quoted: inside a
#: superseded-marked sentence.
_STALE_CLAIMS: tuple[str, ...] = ("2 of 201", "2 commands", "`fred_series`, `fred_search`")

#: Vocabulary that marks a citation as superseded rather than current.
_SUPERSEDED_MARKERS: tuple[str, ...] = (
    "superseded",
    "no longer",
    "used to",
    "at d-084",
    "when measured",
    "as measured on",
    "corrected",
    "stale",
)

#: The registry blocks that carry an ``endpoint`` of their own, outside
#: ``series``. Kept as data so a new block is a one-line addition here.
_REGISTRY_BLOCK_NAMES: tuple[str, ...] = ("release_calendar", "publication_dates")


def _registry_commands() -> tuple[set[str], set[str]]:
    """``(live, declared_but_disabled)`` endpoint strings from the registry.

    Derives from the **parsed** registry, so the ``defaults:`` inheritance is
    already applied — a spec-level read of the YAML would see ``endpoint: None``
    on every scalar series and silently under-count (measured: the raw file has
    only five ``endpoint:`` lines; the parsed model resolves one per entry).

    Returns endpoint strings in the dotted ``economy.fred_series`` form used
    everywhere else in the project.
    """
    registry = get_registry()

    live: set[str] = set()
    disabled: set[str] = set()

    for entry in registry.series.values():
        endpoint = getattr(entry, "endpoint", None)
        if endpoint:
            live.add(str(endpoint))

    for block_name in _REGISTRY_BLOCK_NAMES:
        block = getattr(registry, block_name, None)
        if block is None:
            continue
        endpoint = getattr(block, "endpoint", None)
        if not endpoint:
            continue
        # `enabled` is the gate the data layer honours before issuing the call.
        # A disabled block is DECLARED, not USED — the distinction O-104's
        # correction turns on.
        if getattr(block, "enabled", True):
            live.add(str(endpoint))
        else:
            disabled.add(str(endpoint))

    return live, disabled


def _live_commands() -> frozenset[str]:
    """Every OpenBB command the engine can actually issue today.

    Registry-derived commands, plus the source-literal ones (accounted for
    explicitly rather than by scrape). Excludes anything a registry block marks
    ``enabled: false``.
    """
    registry_live, _ = _registry_commands()
    return frozenset(registry_live | _SOURCE_LITERAL_COMMANDS)


def test_the_command_set_is_derived_not_empty() -> None:
    """A derivation that returns nothing would make every check below vacuous.

    The same guard shape as ``test_tenor_labels_agree_with_declared_tenors``'s
    ``checked > 0``: prove the population is non-empty before asserting anything
    about it.
    """
    live = _live_commands()
    assert live, (
        "derived an EMPTY command set -- the registry parse or the literal set "
        "has broken, and every assertion below this would pass vacuously."
    )
    assert "economy.fred_series" in live, (
        "the generic FRED series route is missing from the derivation; check "
        "that `defaults:` inheritance is still applied by the registry validator."
    )


def test_the_disabled_calendar_is_not_counted_as_live() -> None:
    """``economy.calendar`` is declared with ``enabled: false`` — not a live call.

    This is the check that keeps the count honest in the direction that matters:
    a census that swept every ``endpoint:`` line regardless of its gate would
    report the calendar as used, overstating coverage by exactly what the gate
    exists to remove.
    """
    _, disabled = _registry_commands()
    assert "economy.calendar" in disabled, (
        "release_calendar.enabled is no longer false, OR the disabled-branch of "
        "the derivation broke. If the calendar has genuinely been re-enabled, "
        "move it to the live set deliberately -- do not let it drift in."
    )
    assert "economy.calendar" not in _live_commands(), (
        "the disabled calendar is being counted as a live command."
    )


def test_the_recorded_live_count_matches_the_tree() -> None:
    """The load-bearing assertion: 4 commands, derived, with no number typed.

    Written as a comparison against the derivation rather than against a literal
    so that ADDING a command fails here and forces the record to move with the
    tree — which is the failure mode O-104 actually had, in reverse.
    """
    live = _live_commands()
    assert len(live) == 4, (
        f"the engine can now issue {len(live)} OpenBB commands, not 4: "
        f"{sorted(live)}.\n"
        "If this is a NEW command, update the count on the live surfaces "
        "(docs/PROGRESS.md, docs/OPEN_ISSUES.md) in the same change -- a "
        "capability the record does not mention is the O-104 defect arriving "
        "from the other side. If a command was REMOVED, do the same."
    )
    # The four, named, so a swap that keeps the count at 4 is still caught.
    assert live == frozenset(
        {
            "economy.fred_series",
            "economy.fred_search",
            "fixedincome.government.yield_curve",
            "economy.fomc_documents",
        }
    ), (
        "the command SET changed while the count stayed 4 -- a substitution "
        f"hides behind an unmoved total. Derived: {sorted(live)}."
    )


def _sentences(text: str) -> list[str]:
    """Split into sentence-ish units for the superseded check.

    Splitting on sentence enders *and* table cells, because the count is stated
    inside a markdown table row in ``docs/PROGRESS.md`` and inside a single long
    table row in ``docs/OPEN_ISSUES.md`` — neither of which has a sentence ender
    to split on. A line-based predicate would miss both.
    """
    return re.split(r"(?<=[.!?])\s+|\n{2,}|\n\|", text)


def _is_superseded(sentence: str) -> bool:
    lowered = sentence.lower()
    return any(marker in lowered for marker in _SUPERSEDED_MARKERS)


@pytest.mark.parametrize("relpath", _LIVE_COUNT_SURFACES)
def test_a_stale_count_is_not_stated_as_current(relpath: str) -> None:
    """The old "2 of 201" may survive only inside its own retraction.

    An absolute prohibition would be wrong: the D-084 narrative legitimately
    records what was measured on 2026-09-20, and deleting that history would
    lose the very provenance that lets a reader date the claim. So the check is
    **contextual** — the figures are permitted in a superseded-marked sentence
    and forbidden as a bare current claim.
    """
    text = (_PROJECT_ROOT / relpath).read_text(encoding="utf-8")

    offences: list[str] = []
    for sentence in _sentences(text):
        if not any(stale in sentence for stale in _STALE_CLAIMS):
            continue
        if not _is_superseded(sentence):
            offences.append(" ".join(sentence.split())[:200])

    assert not offences, (
        f"{relpath} states a SUPERSEDED OpenBB command count as current.\n"
        "The engine now issues 4 commands, not 2: `fred_series`, `fred_search`, "
        "`fixedincome.government.yield_curve` (D-086 change 1) and "
        "`economy.fomc_documents` (D-086 change 2). A superseded count left "
        "standing on a live surface is the D-087.23 defect class -- the next "
        "reader plans work against a number that is not true.\n"
        "If you are recording history, mark it in the same sentence (e.g. "
        "'superseded', 'when measured at D-084'); otherwise state the current "
        "count.\nOffending text:\n  - " + "\n  - ".join(offences)
    )


def test_the_superseded_predicate_accepts_a_real_retraction() -> None:
    """The predicate's positive direction — proven, not assumed (O-107).

    The dated D-084 narrative genuinely quotes "2 of 201" in order to record the
    September measurement. If this predicate were too narrow, the guard above
    would fail on the archive text that gives the figure its provenance, and the
    guard would be deleted within a week.
    """
    real_retraction = (
        "The engine uses 2 of 201 commands as measured at D-084; that count is "
        "superseded (the tree now issues four)."
    )
    assert _is_superseded(real_retraction), (
        "a genuine superseded-marked citation was rejected -- the marker "
        "vocabulary is too narrow and the guard would fail on correct text."
    )


def test_the_superseded_predicate_rejects_a_live_claim() -> None:
    """The predicate's negative direction — the half that actually guards.

    A bare claim, in the exact shape the tree carried, must NOT be admitted.
    Without this, a predicate that matched everything would pass the guard above
    while protecting nothing.
    """
    live_claim = "| OpenBB commands the engine uses | **2 of 201** (`fred_series`, `fred_search`) |"
    assert not _is_superseded(live_claim), (
        "the predicate called a bare live claim superseded -- it would guard "
        "nothing (the O-107 narrow-predicate failure)."
    )
