"""Citation check for ``thesis_layer/warnings.py``'s docstring.

Finding guarded here:
  * F-WARN-001 (INFO) — the module's defect-6 passage said "The flag currently
    only *lowers confidence* (D-033 / §22.8)". §22.8 ("Confidence Is Computed,
    Never Hardcoded") is defensible; **D-033 is not** — it is titled "A registry
    entry has exactly two resolution paths, and a daily series may outrun the
    UTC clock", spans 180 lines, and never mentions "confidence" or
    "data_quality" once. The same mis-citation was duplicated in
    ``docs/DECISIONS.md`` (D-067's defect table). "only lowers confidence" was
    also imprecise: it lowers confidence in ``gdp_nowcast`` alone.

This file is deliberately narrow — the module's full review is still pending;
it exists so the corrected claim is pinned rather than merely edited.
"""

from __future__ import annotations

from pathlib import Path

import macro_engine.thesis_layer.warnings as warnings_mod

ROOT = Path(__file__).resolve().parents[2]


def test_warnings_docstring_does_not_mis_cite_d033() -> None:
    doc = warnings_mod.__doc__ or ""
    assert "D-033" not in doc
    assert "gdp_nowcast" in doc


def test_d033_really_is_unrelated_to_the_flag_penalty() -> None:
    """The reason the citation was wrong, pinned so it cannot be re-added."""
    text = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    assert "D-033 — A registry entry has exactly two resolution paths" in text

    start = text.index("## D-033 —")
    end = text.index("\n## D-", start + 1)
    body = text[start:end]
    assert "confidence" not in body.lower()
    assert "data_quality" not in body


def test_decisions_copy_of_the_claim_is_corrected_too() -> None:
    text = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    assert "The flag only *lowers confidence* (D-033 / §22.8)" not in text
    assert "The flag lowers confidence only in `gdp_nowcast` (§22.8)" in text
