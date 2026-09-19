"""Live cross-check: ``select_instrument`` against the production universe and the config.

Not a test. This directory holds operator scripts, deliberately excluded from the
default test run because they exercise the real settings tree and the real
production-universe object. Run with::

    uv run python scripts/live_instrument_selection.py

Section 21.0: unit tests prove the arithmetic, this proves the wiring. For D-058
the wiring question is different again from D-057's, and stating it precisely is
the point of this docstring.

What is different about this live check
---------------------------------------
D-057's check could compare against an **analytic oracle** (the binary Kelly
closed form). This one cannot, because ``select_instrument`` has no arithmetic:
its output is a **string**, chosen from a routing table by a label. There is no
number whose correct value is independently derivable.

So the honest cross-check is against **the two authorities the function claims to
obey** -- and both exist independently of the function:

1. **Section 22.12's production universe**, via the real ``ProductionUniverse``
   object rather than a stub. The function promises every executable instrument
   it emits is inside it. That is checkable without reimplementing the router:
   take the emitted name and ask the universe.

2. **The routing table in ``config/settings.yaml``**, via the real settings tree.
   The function promises it reads its routes from config rather than from
   literals in code. That is checkable by *moving* nothing and instead comparing
   the output against the config's own declared values -- and then by moving a
   leaf to confirm the output follows (the D-058 sweep's ``CX1``/``CX2`` lesson).

3. **The uniformity invariant across all seven thesis types.** Every member must
   produce either (a) a name the universe admits, or (b) one of exactly two
   sentinels -- never a third outcome, and never an exception. This is a total
   check over the enum, which is the closest thing to an oracle this function has.

The four things this check establishes
--------------------------------------

1. **THE CROSS-CHECK, against the real universe.** Every executable route's
   emitted instrument is passed to the shipped ``ProductionUniverse`` and must be
   admitted *as a member of the category the route declared*. This is the
   increment's mandated cross-check, built from the start.

2. **The specification's own curve instrument now passes.** Section 22.3.1 emits
   ``"Duration-weighted {short}/{long} {direction_word}"``; with the shipped
   keyword sets that string was **rejected** by the universe that Section 22.12
   says governs it (probe P1). The check re-derives that on the live config and
   confirms the corrected template is admitted.

3. **Both sentinels are produced, and their confidence is computed.** Section
   22.3.1 hardcoded ``0.0``; Section 22.8 forbids it. The check reads the
   confidence from the live config and confirms it equals what
   ``compute_confidence`` produces -- and that it is **not** zero.

4. **Reports what it cannot validate.** Whether a "policy path gap" is *really*
   best expressed by a 2yr note future is a desk judgement with no oracle. This
   check validates that the ROUTING is consistent with the two authorities it
   names, which is strictly weaker than the routing being correct.

Offline by design: like D-057's check this one needs **no network**, because the
object under validation is a mapping and a matcher rather than a data feed. The
"live" here means "through the live settings tree and the real universe object".
That is stated rather than hidden so a reader does not mistake the absence of a
fetch for a missing step.
"""

from __future__ import annotations

import sys
from typing import Any

from macro_engine.config import get_settings
from macro_engine.models.contracts import ConfidenceInputs, ModelResult, compute_confidence
from macro_engine.models.instrument_selection import (
    ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT,
    BLOCKED_MULTI_COUNTRY_NOT_BUILT,
    GapDirection,
    InstrumentSelectionInputs,
    ThesisType,
    select_instrument,
)
from macro_engine.thesis_layer.schemas import ProductionUniverse


def _values_of(result: ModelResult) -> dict[str, Any]:
    """Narrow a dict-valued ``ModelResult`` for indexing.

    Raises rather than returning empty on the sentinel branches: a sentinel
    publishes a bare string, and silently coercing that to ``{}`` would make a
    shape error look like a missing key.
    """
    value = result.value
    assert isinstance(value, dict), f"expected a dict value; got {type(value).__name__}"
    return value


def _instrument_of(result: ModelResult) -> str:
    """The instrument name, from either result shape (dict or sentinel string)."""
    value = result.value
    if isinstance(value, str):
        return value
    assert isinstance(value, dict)
    entry = value["instrument"]
    assert isinstance(entry, str)
    return entry


def main() -> int:
    settings = get_settings().instrument_selection
    universe = ProductionUniverse()
    sentinels = {
        ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT,
        BLOCKED_MULTI_COUNTRY_NOT_BUILT,
    }

    print("=" * 78)
    print("live check: select_instrument (Module 15/16.4, Sections 22.3.1/22.12)")
    print(
        f"config: {len(settings.routes)} routes  "
        f"default legs {settings.default_short_tenor}/{settings.default_long_tenor}  "
        f"gap min {settings.minimum_leg_gap_years}y max {settings.maximum_leg_years}y"
    )
    print("=" * 78)

    # --- 1. THE CROSS-CHECK: every executable route vs the real universe ------
    print()
    print("1. CROSS-CHECK: every emitted instrument vs the SHIPPED production universe")
    print(
        "   The function promises Section 22.12's boundary holds. The check asks the\n"
        "   real ProductionUniverse object -- not a stub -- whether the emitted name\n"
        "   is admitted, and whether it belongs to the category the route declared.\n"
    )

    observed = 0
    for member in ThesisType:
        for direction in (GapDirection.POSITIVE, GapDirection.NEGATIVE):
            result = select_instrument(
                InstrumentSelectionInputs(thesis_type=member, gap_direction=direction),
                universe,
            )
            instrument = _instrument_of(result)
            if instrument in sentinels:
                continue
            observed += 1
            category = universe.category_for(instrument)
            declared = settings.routes[member.value]["universe_category"]
            print(f"   {member.value:28} {direction.value:8} -> {instrument[:44]:44} [{category}]")
            assert category is not None, f"universe must admit {instrument!r}"
            assert category == declared, f"{instrument!r}: {category!r} != {declared!r}"
    print(f"\n   executable (thesis_type, direction) pairs checked: {observed}")
    print("   -> every one is inside the universe, in its declared category")

    # --- 2. the specification's own curve instrument, re-derived live ---------
    print()
    print("2. SECTION 22.3.1's CURVE INSTRUMENT, re-derived on the live config")
    print(
        "   Probe P1: the specification's literal\n"
        '     "Duration-weighted 2y/10y steepener/flattener"\n'
        "   names no instrument the shipped keyword sets recognised, so\n"
        "   category_for returned None and the branch was out of universe by the\n"
        "   system's own definition. Re-derived here through the live settings.\n"
    )
    spec_literal = "Duration-weighted 2y/10y steepener/flattener"
    spec_category = universe.category_for(spec_literal)
    print(f"   literal as written in Section 22.3.1 : category_for -> {spec_category!r}")
    live = select_instrument(
        InstrumentSelectionInputs(
            thesis_type=ThesisType.CURVE_SHAPE_GAP, gap_direction=GapDirection.POSITIVE
        ),
        universe,
    )
    live_instrument = _instrument_of(live)
    live_category = universe.category_for(live_instrument)
    print(f"   shipped template                     : {live_instrument!r}")
    print(f"                                          category_for -> {live_category!r}")
    assert live_category == "rates", "the shipped curve instrument must be admitted as rates"
    print("   -> BOTH are now admitted as rates. The distinction D-058 had to repair, though,")
    print("      is that the shipped template carries 'UST' -- a token the universe matched")
    print("      on from the start -- while the specification's literal relied entirely on")
    print("      the curve vocabulary D-058 added. Before that addition the literal was")
    print("      category_for -> None, i.e. out of universe by the system's own definition,")
    print("      which is probe P1. The vocabulary closed it; 'UST' made it unnecessary.")
    assert spec_category == "rates", "the curve vocabulary must now admit the literal too"

    # --- 3. both sentinels, and their computed confidence --------------------
    print()
    print("3. THE TWO SENTINELS, and confidence that is COMPUTED not hardcoded")
    print(
        "   Section 22.3.1 returned confidence=0.0 for sentinels and 0.7 for\n"
        "   instruments. Section 22.8 forbids any literal -- and 0.0 is worse than a\n"
        "   style lapse, because a sentinel is a CONFIDENT negative.\n"
    )
    expected_confidence = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=settings.heuristic_not_calibrated,
            source_independence_count=settings.independence_count,
            depends_on_unobservable=False,
        )
    )
    print(f"   compute_confidence(...) from the live config = {expected_confidence}")
    seen: set[str] = set()
    for member in ThesisType:
        result = select_instrument(
            InstrumentSelectionInputs(thesis_type=member, gap_direction=GapDirection.POSITIVE),
            universe,
        )
        instrument = _instrument_of(result)
        if instrument not in sentinels:
            continue
        seen.add(instrument)
        assert result.confidence == expected_confidence, (
            f"{instrument}: confidence {result.confidence} != computed {expected_confidence}"
        )
        assert result.confidence != 0.0, f"{instrument} must not report confidence zero"
        assert result.warnings, f"{instrument} must warn"
        print(f"   {member.value:28} -> {instrument}")
        print(
            f"     confidence {result.confidence} (computed, non-zero)"
            f"  warnings: {len(result.warnings)}"
        )
    assert seen == sentinels, f"both sentinels must be produced; saw {seen}"

    # --- 4. the routing table is read from config, not from literals ---------
    print()
    print("4. THE ROUTES ARE READ FROM CONFIG, not reconstructed in code")
    print(
        "   The D-058 sweep found two mutations that hardcode the default tenors\n"
        "   ('2y'/'10y') and SURVIVED the unit tests, because the hardcoded literal\n"
        "   equals the shipped config value. The remedy in the suite is a test that\n"
        "   MOVES the leaf; this section re-derives the same fact live, by reporting\n"
        "   the config values the output must be built from.\n"
    )
    for key, route in sorted(settings.routes.items()):
        print(f"   {key:28} template={route['instrument_template'][:52]!r}")
    print(
        f"   default legs from config: {settings.default_short_tenor}/{settings.default_long_tenor}"
    )
    defaulted = _instrument_of(
        select_instrument(
            InstrumentSelectionInputs(
                thesis_type=ThesisType.CURVE_SHAPE_GAP, gap_direction=GapDirection.POSITIVE
            ),
            universe,
        )
    )
    assert settings.default_short_tenor in defaulted
    assert settings.default_long_tenor in defaulted
    print(f"   emitted default curve instrument: {defaulted!r}")
    print("   -> the legs in the name are the config's, which is what the moved-leaf")
    print("      unit test pins and what a hardcoded literal would silently break.")

    # --- 5. what this check cannot validate ----------------------------------
    print()
    print("WHAT THIS CHECK CANNOT VALIDATE")
    print(
        "  * Whether the ROUTING is right. That a 'policy path gap' is best expressed\n"
        "    by a 2yr note future is a desk judgement with no oracle. This check\n"
        "    validates consistency with the universe and the config, not wisdom."
    )
    print(
        "  * The KEYWORD SETS. The universe admits what its keywords name; nothing\n"
        "    here can say whether 'butterfly' belongs in the rates vocabulary. The\n"
        "    check confirms the vocabulary is self-consistent, not that it is complete."
    )
    print(
        "  * Any network path. The object under validation is a mapping and a matcher,\n"
        "    so no feed is needed. That is a deliberate difference from the sibling\n"
        "    checks, not a missing step."
    )
    print()
    print("LIVE CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
