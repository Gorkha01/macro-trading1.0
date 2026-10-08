"""Live probe: is ``regime.state`` still ``None`` on a real thesis?

DEF-003 (``docs/DEFECTS_2026-09-19.md``) recorded that ``_regime_view`` published
``state: None`` on **every** thesis ever produced, because the builder was never
given ``RegimeInputs``. The remediation wired ``_regime_leg`` in
``orchestration.py`` and threaded ``regime=`` through the builder and the three
production call sites.

This probe exists so the claim is **measured rather than asserted**: it fetches a
real snapshot, runs the real orchestration, builds the real thesis, and prints
the regime field plus the derivation note and the classifier's own result. It is
deliberately not a test (it needs network + a FRED key); it is the evidence step
the audit standard requires — run against live data, output pasted.

Usage::

    uv run python tools/live_regime_probe.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from macro_engine.api_layer.orchestration import snapshot_to_thesis_inputs
from macro_engine.api_layer.snapshot_provider import get_snapshot
from macro_engine.models.instrument_selection import ThesisType
from macro_engine.thesis_layer.builder import build_us_macro_thesis


def main() -> int:
    snapshot, provenance = get_snapshot("us", force_refresh=True)
    print(f"snapshot as_of      : {snapshot.as_of}")
    print(f"snapshot provenance : {provenance.warnings()[:2]}")

    inputs = snapshot_to_thesis_inputs(snapshot, thesis_type=ThesisType.POLICY_PATH_GAP)

    print("\n-- ThesisInputs.regime ------------------------------------------")
    if inputs.regime is None:
        print("regime is None  <-- DEF-003 NOT FIXED")
        return 1
    print(f"model_name   : {inputs.regime.model_name}")
    print(f"value        : {json.dumps(inputs.regime.value, indent=2, default=str)}")
    print(f"confidence   : {inputs.regime.confidence}")
    print(f"interpretation: {inputs.regime.interpretation}")
    print(f"inputs_used  : {inputs.regime.inputs_used}")
    print(f"warnings     : {inputs.regime.warnings}")

    print("\n-- orchestration derivation notes --------------------------------")
    for note in inputs.notes:
        if "regime" in note.name or "nairu" in note.name.lower():
            print(f"  {note.name}: {note.value}  <- {note.source}")

    thesis = build_us_macro_thesis(
        inputs.reads,
        inputs.taylor_inputs,
        inputs.first_difference_inputs,
        thesis_type=inputs.thesis_type,
        universe=inputs.universe,
        short_yield=inputs.short_yield,
        regime=inputs.regime,
    )

    print("\n-- thesis.regime (the consumer) ----------------------------------")
    print(json.dumps(thesis.regime, indent=2, default=str))
    print(f"\nstatus       : {thesis.status.value}")
    print(f"warnings     : {len(thesis.warnings)}")

    state = thesis.regime.get("state")
    print(f"\nVERDICT: regime.state = {state!r}")
    if state is None:
        print("  -> DEF-003 STILL PRESENT")
        return 1
    print("  -> DEF-003 FIXED: the classifier's label reached the thesis")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
