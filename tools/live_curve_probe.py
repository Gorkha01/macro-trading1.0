"""Live probe: do the curve reads reach real data, and does the tenor map work?

DEF-004 (``docs/DEFECTS_2026-09-19.md``) found the snapshot carrying a real
11-tenor UST curve and a 5-tenor TIPS curve while ``curve_slope``,
``breakeven_inflation`` and ``decompose_yield`` sat in the unreferenced set. The
data existed and the consumers did not run.

Wiring them exposed a **latent vocabulary defect** this probe documents rather
than hides: the config writes ``2y``/``10y`` (correct for instrument names), the
curve data is keyed ``2yr``/``10yr`` (from FRED's ``DGS2``), and nothing
translated between them. Fed the config labels raw, ``curve_slope`` raises
``KeyError``. The probe shows both the failure and the reconciliation.

It also checks the arithmetic independently: every spread and every breakeven is
recomputed from the snapshot's own tenors and compared to the model's output.

Usage::

    uv run python tools/live_curve_probe.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from macro_engine.api_layer.orchestration import (
    _config_tenor_for,
    snapshot_to_thesis_inputs,
)
from macro_engine.api_layer.snapshot_provider import get_snapshot
from macro_engine.config import get_settings
from macro_engine.models.instrument_selection import ThesisType


def main() -> int:
    snapshot, _ = get_snapshot("us", force_refresh=True)
    curve = snapshot.yield_curve
    tips = snapshot.tips_yields
    if curve is None or tips is None:
        print("no curve in the snapshot")
        return 1

    print(f"nominal curve as_of {curve.as_of}: {len(curve.tenors)} tenors")
    print(f"  {curve.tenors}")
    print(f"TIPS curve as_of {tips.as_of}: {len(tips.tenors)} tenors")
    print(f"  {tips.tenors}")

    st = get_settings()
    short_cfg = st.instrument_selection.default_short_tenor
    long_cfg = st.instrument_selection.default_long_tenor
    print(f"\nconfig labels: short={short_cfg!r} long={long_cfg!r}")
    print(f"  (correct for instrument names: 'Duration-weighted {short_cfg}/{long_cfg} UST ...')")
    print(f"  curve keys are {sorted(curve.tenors)[:3]}... -- a DIFFERENT vocabulary")

    print("\n-- the defect, then the reconciliation ---------------------------")
    print(f"  raw config label in curve? {short_cfg in curve.tenors}  <- this is why KeyError")
    mapped_short = _config_tenor_for(short_cfg, curve.tenors)
    mapped_long = _config_tenor_for(long_cfg, curve.tenors)
    print(f"  _config_tenor_for({short_cfg!r}) -> {mapped_short!r}")
    print(f"  _config_tenor_for({long_cfg!r}) -> {mapped_long!r}")

    inputs = snapshot_to_thesis_inputs(snapshot, thesis_type=ThesisType.CURVE_SHAPE_GAP)

    print(f"\n-- ThesisInputs.curve: {len(inputs.curve)} result(s) ---------------")
    if not inputs.curve:
        note = next(n for n in inputs.notes if n.name == "curve_slope")
        print(f"NOT_COMPUTED: {note.source}")
        return 1

    slope = next((r for r in inputs.curve if r.model_name == "curve_slope"), None)
    if slope is not None:
        # Independent recomputation from the snapshot's own numbers.
        expected_bp = round((curve.tenors["10yr"] - curve.tenors["2yr"]) * 100, 1)
        print(f"  curve_slope value : {slope.value}")
        print(f"  recomputed        : {expected_bp}")
        assert slope.value == expected_bp, "slope disagrees with recomputation"
        print(f"  interpretation    : {slope.interpretation}")
        print(f"  confidence        : {slope.confidence}")
        print("  -> matches an independent recomputation")

    breakevens = [r for r in inputs.curve if r.model_name == "breakeven_inflation"]
    print(f"\n-- breakevens: {len(breakevens)} tenor(s) ------------------------")
    for r in breakevens:
        # The tenor is echoed in the interpretation; recover it for the check.
        tenor = next(t for t in tips.tenors if t in r.interpretation)
        expected = round(curve.tenors[tenor] - tips.tenors[tenor], 2)
        flag = "OK" if r.value == expected else "MISMATCH"
        print(
            f"  {tenor:>4}: nominal {curve.tenors[tenor]:.2f}% - "
            f"TIPS {tips.tenors[tenor]:.2f}% = {r.value:+.2f}%   "
            f"(recomputed {expected:+.2f}%)  [{flag}]"
        )
        assert r.value == expected, f"{tenor} breakeven disagrees with recomputation"

    print("\n-- derivation notes ---------------------------------------------")
    for note in inputs.notes:
        if note.name in ("curve_slope", "breakeven_inflation"):
            print(f"  {note.name}: {note.value}  ({note.window})")

    print(f"\nwarnings carried: {len(inputs.warnings)}")
    print("\nVERDICT: the curve reads are wired to real data, and the tenor map works")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
