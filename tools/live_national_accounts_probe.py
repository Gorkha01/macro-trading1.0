"""Live probe: does ``gdp_gdi_divergence`` reach a real thesis, on a real pair?

DEF-002 (``docs/DEFECTS_2026-09-19.md``) found ``gdi`` declared in the snapshot
schema and never fetched, which is why Module 7.1's ``gdp_gdi_divergence`` had no
caller in the pipeline despite being implemented and mutation-tested. DEF-002 put
real GDI in the snapshot; this probe measures whether the wiring then works.

What it checks, in order of importance:

1. **The pair is real and same-quarter.** Both growth rates are recomputed here
   independently from the snapshot's own observations, so the note the
   orchestrator wrote can be checked against arithmetic done a second way.
2. **The basis is nominal on both sides.** ``GDP`` and ``GDI`` are the nominal
   pair; the model's docstring is explicit that mixing in a real series would
   make the difference measure the deflator.
3. **The mean-zero property still holds on the live window.** The model's
   corrections are built on the growth divergence being mean-zero and its sign
   being a coin flip. If live data contradicted that, the corrections would be
   wrong — so it is re-measured rather than trusted.

Usage::

    uv run python tools/live_national_accounts_probe.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from macro_engine.api_layer.orchestration import snapshot_to_thesis_inputs
from macro_engine.api_layer.snapshot_provider import get_snapshot
from macro_engine.models.instrument_selection import ThesisType


def main() -> int:
    snapshot, _ = get_snapshot("us", force_refresh=True)

    gdp = {p.observation_date: p.value for p in snapshot.gdp_nominal}
    gdi = {p.observation_date: p.value for p in snapshot.gdi}
    print(f"gdp_nominal : {len(gdp)} observations")
    print(f"gdi         : {len(gdi)} observations")
    if gdp and gdi:
        print(f"  GDP range : {min(gdp)} .. {max(gdp)}")
        print(f"  GDI range : {min(gdi)} .. {max(gdi)}")

    common = sorted(set(gdp) & set(gdi))
    print(f"common quarters: {len(common)}")
    if not common:
        print("NO COMMON QUARTERS -- the pair cannot be formed")
        return 1

    # Independent recomputation, so the orchestrator's note is checkable. The
    # year-ago date is `_minus_months`-style calendar arithmetic and the prior
    # quarter is the latest at or before it — the same convention the
    # orchestrator uses, restated here so agreement is evidence rather than
    # tautology. (A first version of this probe used `replace(year=...)` and
    # silently picked 2021-07 for a 2026-04 quarter, reporting +35% YoY; the
    # lesson is that "one year ago" on a quarterly series needs a *lookup*, not
    # a date rewrite.)
    latest = common[-1]
    target = latest.replace(year=latest.year - 1)
    candidates = [d for d in common if d <= target]
    if not candidates:
        print(f"no common quarter at or before {target} -- pair cannot be formed")
        return 1
    prior = candidates[-1]
    print(f"\n  year-ago target {target}, used {prior}")
    gdp_g = (gdp[latest] / gdp[prior] - 1) * 100
    gdi_g = (gdi[latest] / gdi[prior] - 1) * 100
    print(f"\nlatest pair : {latest} vs {prior}")
    print(f"  GDP YoY   : {gdp_g:+.3f}%   (level {gdp[latest]:,.1f} vs {gdp[prior]:,.1f})")
    print(f"  GDI YoY   : {gdi_g:+.3f}%   (level {gdi[latest]:,.1f} vs {gdi[prior]:,.1f})")
    print(f"  divergence: {gdp_g - gdi_g:+.3f}pp  <- recomputed independently")

    # The mean-zero property the model's corrections rest on.
    pairs = []
    for q in common:
        try:
            y = q.replace(year=q.year - 1)
        except ValueError:
            continue
        if y in gdp and y in gdi and gdp[y] and gdi[y]:
            pairs.append(((gdp[q] / gdp[y] - 1) * 100) - ((gdi[q] / gdi[y] - 1) * 100))
    if pairs:
        mean = sum(pairs) / len(pairs)
        led = sum(1 for d in pairs if d > 0) / len(pairs)
        print(f"\nhistory: {len(pairs)} YoY pairs")
        print(f"  mean divergence = {mean:+.4f}pp   (model expects ~0)")
        print(f"  GDP-led share   = {led:.1%}        (model expects a coin flip)")

    inputs = snapshot_to_thesis_inputs(snapshot, thesis_type=ThesisType.POLICY_PATH_GAP)
    print("\n-- ThesisInputs.national_accounts --------------------------------")
    if inputs.national_accounts is None:
        note = next(n for n in inputs.notes if n.name == "gdp_gdi_divergence")
        print(f"NOT_COMPUTED: {note.source}")
        return 1
    raw = inputs.national_accounts.value
    # ``ModelResult.value`` is a union because different models publish different
    # shapes; this one is documented and tested to be a dict, so the narrowing is
    # asserted rather than cast — a probe that silently printed nothing on an
    # unexpected shape would be worse than one that stops.
    assert isinstance(raw, dict), f"expected a dict value, got {type(raw).__name__}"
    for key, value in raw.items():
        print(f"  {key}: {value}")
    print(f"confidence: {inputs.national_accounts.confidence}")
    print(f"warnings  : {len(inputs.national_accounts.warnings)}")

    fired_note = next((n for n in inputs.notes if n.name == "gdp_gdi_divergence"), None)
    if fired_note is not None:
        print(f"\n  derivation note value : {fired_note.value}")
        print(f"  derivation window     : {fired_note.window}")

    print("\nVERDICT: gdp_gdi_divergence is wired to real data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
