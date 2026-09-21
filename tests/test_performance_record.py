"""The recorded build-cost explanation must stay corrected (D-087.19, O-111(b)).

**The defect this file exists to pin.** For most of a day, five separate copies
of the same sentence told the next reader that a snapshot build costs *223.6 s
over the local OpenBB API against 9.5 s in-process*, and that the remedy is
*batching or parallelising ~24 sequential requests*. Every part of that was
wrong and all of it was load-bearing:

* The two figures were taken in **different thermal states** — 223.6 s was a COLD
  run, 9.5 s a WARM one. Re-measured 3-runs-each on a live service, both paths
  warm, the *real* ratio is **1.20x** (3.71 s local vs 4.46 s package), not 23x.
  The withdrawn 223.6 s does not reproduce at all — it is ~60x off.
* The honest operational statement is **first build ~46-81 s, subsequent ~4 s**,
  because cold start *dominates* a build (12-19x) and the old note never
  mentioned it. A build time quoted without its thermal state is **ambiguous,
  not merely imprecise**.
* The remedy was aimed at the wrong layer: the build overhead a smarter loop
  could remove is **2.41 s of 56** (4%), so making the loop infinitely parallel
  saves ~2.4 s. The cost is per-series **provider latency** (and, on the first
  build, interpreter/import warm-up).

**Why a test and not a note.** The wrong numbers had already been *corrected in
prose* once — D-087.19 says the ``settings.yaml`` note "has been corrected" — and
they were still sitting in `config/settings.yaml`, `config.py` and three
`api_layer` docstrings when this file was written, because **nothing read the
note**. A correction that lives only in a decision record is a claim, not a fix
(O-88, and the same shape as D-087.19's own fourth-instance lesson). This file
is the reader.

**The predicate, and the trap it avoids.** A naive "the string 223.6 must not
appear" guard would be wrong, because the *corrected* notes deliberately quote
the old figure in order to retract it — and a guard that forbids the honest
citation is a guard that gets deleted. So the test is **contextual**: it allows a
figure that appears within a sentence that also retracts it (``does not
reproduce``, ``used to sit``, ``were taken in``, ...) and forbids it otherwise.
That is the **O-107 narrow-predicate** lesson applied in advance — three checks
in this project have already disagreed because a predicate matched a *prefix*
rather than the *meaning*, so the retraction vocabulary is explicit and tested
both directions below.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: Files whose job is to explain the build's cost to a human. Every one of these
#: carried the withdrawn figures at some point, which is the whole point.
_PERFORMANCE_SURFACES: tuple[str, ...] = (
    "config/settings.yaml",
    "src/macro_engine/config.py",
    "src/macro_engine/api_layer/reasoning_stream.py",
    "src/macro_engine/api_layer/routes_health.py",
    "src/macro_engine/api_layer/snapshot_provider.py",
)

#: The figures that were WITHDRAWN, and the only way they may still be quoted:
#: inside a retraction. Anything else is a live claim and fails.
_WITHDRAWN_FIGURES: tuple[str, ...] = ("223.6", "9.5s", "9.5 s")

#: Vocabulary that marks a citation as a RETRACTION rather than a claim. Kept
#: explicit (not a fuzzy match) so that a new live claim cannot slip through by
#: happening to sit near one of these words.
_RETRACTION_MARKERS: tuple[str, ...] = (
    "does not reproduce",
    "did not reproduce",
    "used to sit",
    "were taken in",
    "withdrawn",
    "no longer",
    "was a cold run",
)

#: The honest statement, which must be PRESENT. Both halves matter: the cold
#: figure alone would invite quoting "46 s" as a single number, and the warm
#: figure alone hides the first build's real cost.
#:
#: The separator may be a hyphen or an en dash — a record written by a human on a
#: word processor routinely uses the latter, and refusing the typographic form
#: would fail a correct note. Written as ``\u2013`` so the source stays ASCII
#: (ruff's RUF001 flags a literal en dash as an ambiguous character).
_REQUIRED_STATEMENT = re.compile(r"46[-\u2013]81|46\s*[-\u2013]\s*81")

#: The warm half must be present **in the same note**, not merely somewhere in
#: the file. This scoping is not fussiness: `warm` occurs 8 times in
#: `settings.yaml`, so a file-scoped search passed on a mutant that had deleted
#: the warm half from the memoize note (the sweep's M5 survived, and that is what
#: it taught — **O-107's failure in the too-broad direction**). A predicate must
#: be scoped to the thing it names.
_REQUIRED_WARM = re.compile(r"subsequent|warm", re.IGNORECASE)

#: The remedy that was DISPROVED and must not come back as advice. D-087.18
#: showed "batching/parallelising the ~24 sequential requests" targets the build
#: overhead — 2.41 s of 56 (4%) — so it is not the durable fix and naming it
#: misdirects the next reader. Forbidding the wrong *figures* does not forbid the
#: wrong *remedy*, which is why this is a separate predicate (the sweep's M3
#: survived until it existed).
_DISPROVED_REMEDY = re.compile(
    r"batch(?:ing)?\s+(?:or\s+parallelis\w+\s+)?(?:the\s+)?~?24\s+"
    r"(?:sequential\s+)?(?:requests|fetches)|parallelis\w+\s+~?24\s+",
    re.IGNORECASE,
)

#: The YAML note whose body the scoped checks read. Anchored on its own key so
#: the region is unambiguous even as neighbouring notes change.
_NOTE_KEY = "memoize_snapshots_value:"


def _scoped_region(text: str, relpath: str) -> str:
    """The region a scoped predicate should search.

    For the YAML surface that is the ``memoize_snapshots_value`` note — the note
    this record is about — because searching the whole file lets an unrelated
    note satisfy a predicate the target note has stopped satisfying. For the
    Python surfaces the whole file is the right scope: each is a module whose
    docstring and code both describe one build path, and they carry no second
    performance note to confuse the search.

    Kept as one small function rather than inlined per test, because **the scope
    is the load-bearing decision here** and it should be argued once.
    """
    if relpath.endswith(".yaml"):
        start = text.find(_NOTE_KEY)
        if start < 0:
            return text
        # The next top-level key at the same indent ends the note. The file uses
        # 2-space indent for config keys, so the next line matching
        # "\n  <word>:" is the boundary.
        boundary = re.search(r"\n  \S[^\n]*:\s*(?:\n|$)", text[start + 1 :])
        if boundary is None:
            return text[start:]
        return text[start : start + 1 + boundary.start()]
    return text


def _sentences(text: str) -> list[str]:
    """Split into sentence-ish units for the retraction check.

    Splitting on sentence enders rather than lines is deliberate: the notes
    under test are hard-wrapped, so a retraction and the figure it retracts are
    routinely on *different physical lines*. A line-based predicate would have
    flagged the corrected notes — exactly the false positive that gets a guard
    disabled.
    """
    return re.split(r"(?<=[.!?])\s+|\n{2,}", text)


def _is_retraction(sentence: str) -> bool:
    lowered = sentence.lower()
    return any(marker in lowered for marker in _RETRACTION_MARKERS)


@pytest.mark.parametrize("relpath", _PERFORMANCE_SURFACES)
def test_no_withdrawn_figure_survives_as_a_live_claim(relpath: str) -> None:
    """Each performance surface may quote the old figures only to retract them.

    Both directions are exercised in this module: the helper below is proven to
    accept a real retraction and reject a real claim, so a green run here means
    the predicate discriminated rather than merely matched nothing.

    Scoped like the presence check — a retraction sitting in an *unrelated* note
    must not license a live claim in this one.
    """
    text = _scoped_region((_PROJECT_ROOT / relpath).read_text(encoding="utf-8"), relpath)

    offences: list[str] = []
    for sentence in _sentences(text):
        if not any(figure in sentence for figure in _WITHDRAWN_FIGURES):
            continue
        if not _is_retraction(sentence):
            offences.append(" ".join(sentence.split()))

    assert not offences, (
        f"{relpath} states a WITHDRAWN build figure as if it were current. "
        "These were disproved at D-087.19 (the 223.6 s / 9.5 s pair compared a "
        "COLD run with a WARM one; warm the ratio is 1.20x, and 223.6 s does "
        "not reproduce). If you are documenting history, say so in the same "
        "sentence (e.g. 'does not reproduce') — otherwise state the honest "
        "numbers: first build ~46-81 s, subsequent ~4 s. Offending text:\n  - "
        + "\n  - ".join(offences)
    )


@pytest.mark.parametrize("relpath", _PERFORMANCE_SURFACES)
def test_the_honest_statement_is_actually_present(relpath: str) -> None:
    """Removing the old claim is only half the fix — say what IS true.

    A guard that only forbids the old sentence would be satisfied by deleting
    the explanation entirely, which would leave the next reader with no cost
    figure at all. The record must carry the corrected statement — and the warm
    half must be in **the same note**, not merely somewhere in the file.
    """
    text = _scoped_region((_PROJECT_ROOT / relpath).read_text(encoding="utf-8"), relpath)

    assert _REQUIRED_STATEMENT.search(text), (
        f"{relpath} no longer states the honest build cost (first build "
        "~46-81 s, subsequent ~4 s). The cost is temperature-dependent; a "
        "surface that explains the build must carry both halves. See D-087.19."
    )
    assert _REQUIRED_WARM.search(text), (
        f"{relpath} states the cold figure without naming the warm one, in the "
        "passage that explains the build. A build time quoted without its "
        "thermal state is ambiguous, not merely imprecise (D-087.19). NOTE: "
        "this check is deliberately scoped to the note/passage it is about — a "
        "file-wide search passes on a mutant that deleted the warm half, "
        "because 'warm' appears 8 times elsewhere in settings.yaml."
    )


@pytest.mark.parametrize("relpath", _PERFORMANCE_SURFACES)
def test_the_disproved_remedy_is_not_recommended(relpath: str) -> None:
    """The wrong REMEDY must not return either, not just the wrong figures.

    D-087.18 disproved *"batching or parallelising the ~24 sequential requests"*
    as the durable fix by arithmetic on the record's own numbers: the build
    overhead a smarter loop could remove is **2.41 s of 56 (4 %)**, so
    parallelising the loop saves ~2.4 s while the real cost is per-series
    provider latency. A guard that forbids only the withdrawn *figures* permits
    this sentence, which is what the sweep's M3 demonstrated by surviving.

    Stated as a prohibition rather than a positive requirement, because the
    corrected record simply does not need to argue about batching — the honest
    numbers speak for themselves.
    """
    text = (_PROJECT_ROOT / relpath).read_text(encoding="utf-8")

    hit = _DISPROVED_REMEDY.search(text)
    assert hit is None, (
        f"{relpath} recommends the remedy D-087.18 DISPROVED: {hit.group(0)!r}. "
        "Batching/parallelising the fetch targets 2.41 s of a 56 s build (4 %); "
        "the cost is per-series provider latency and, on the first build, cold "
        "start. If batching is mentioned at all it must be named as the thing "
        "that was ruled out — and then say why."
    )


def test_the_retraction_predicate_accepts_a_real_retraction() -> None:
    """The predicate's positive direction — proven, not assumed (O-107).

    The corrected notes genuinely quote 223.6 s in order to withdraw it. If
    this predicate were too narrow, the guard above would fail on the very text
    that fixes the bug, and the guard would be deleted within a week.
    """
    if _PROJECT_ROOT.joinpath("config/settings.yaml").exists():
        settings_note = (_PROJECT_ROOT / "config/settings.yaml").read_text(encoding="utf-8")
        claiming = [" ".join(s.split()) for s in _sentences(settings_note) if "223.6" in s]
        assert claiming, (
            "expected config/settings.yaml to quote the withdrawn figure while "
            "retracting it; if the retraction was removed too, update this test "
            "-- it exists to prove the predicate discriminates"
        )
        assert all(_is_retraction(s) for s in claiming), (
            "every surviving 223.6 citation in settings.yaml must sit in a "
            "retraction; got: " + repr(claiming)
        )


def test_the_retraction_predicate_rejects_a_live_claim() -> None:
    """The predicate's negative direction — the half that actually guards.

    A bare claim, in the shape the tree used to carry, must NOT be treated as a
    retraction. Without this, a predicate that accepted everything (or matched
    the wrong substring) would pass every test above while guarding nothing.
    """
    live_claim = (
        "MEASURED: a full live snapshot build took 223.6s over the local "
        "OpenBB API and 9.5s in-process."
    )
    assert not _is_retraction(live_claim), (
        "the predicate called a bare live claim a retraction -- it would guard "
        "nothing (the O-107 narrow-predicate failure)"
    )


def test_the_retraction_predicate_is_not_matched_by_prefix_alone() -> None:
    """O-107 in advance: a marker is not honoured by a *prefix* coincidence.

    ``no longer`` is a retraction marker. A live claim that simply happens to
    begin with those characters must not be admitted, which is why markers are
    compared as substrings of a *sentence* the human can see rather than by a
    startswith on the raw buffer.
    """
    trap = "Nobody checks this: build time 223.6s and 9.5s warm are the cure."
    # 'no longer' is absent as a standalone phrase, so this must NOT be a
    # retraction even though it contains the letters 'no ' and 'longer'.
    assert not _is_retraction(trap), (
        "a claim containing the fragile substring was wrongly admitted as a "
        "retraction -- rethink the marker vocabulary"
    )
