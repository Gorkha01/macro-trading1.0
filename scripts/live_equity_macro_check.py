"""Live wiring check: real FRED data -> the shipped regime classifier ->
Section 21.3 Tier-5's ``sector_rotation_prior`` (Module 11, Section 6.9).

Not a test. This directory holds operator scripts, deliberately excluded from the
default test run because they hit the network. Run with::

    uv run python scripts/live_equity_macro_check.py

Section 21.0: unit tests prove the arithmetic, this proves the WIRING. For a
LOOKUP whose only input is a regime label, the question is not "does the lookup
work" (a unit test settles that) — it is **"is the label this function is keyed
on the label the shipped classifier actually produces?"** So this check runs the
REAL pipeline end to end: it fetches the classifier's own inputs from FRED, runs
``classify_regime_rule_based``, and feeds the state it returns — not a hand-typed
string — into ``sector_rotation_prior``.

⚠️ **THE HONESTY TIER IS END-TO-END, NOT CONSTRUCTED-SUBSTITUTE.** Section 1
proves it: the regime that reaches the prior is the classifier's own output on
live data, not a literal chosen to make the demo work. Two independent things
are established that no unit test can:

1. **the classifier emits a state the map covers.** The whole reason this
   function exists is that Section 6.9's reference map is keyed on SIX regime
   strings while the classifier declares NINE. Running the real classifier
   therefore tests the CONTRACT between the two modules, and the check reports
   which state came out and whether the map had a row for it.

2. **the coverage assertion holds against the real vocabulary.** ``REGIME_STATES``
   is re-read from the classifier module and diffed against the map's keys, so a
   future classifier change that added a state would be visible here as well as
   in the unit suite.

What this check establishes
---------------------------

1. **End-to-end: the real regime reaches the prior.** FRED -> ``RegimeInputs`` ->
   ``classify_regime_rule_based`` -> ``sector_rotation_prior``, with the state
   printed beside its sector prior.

2. **Every declared regime resolves to a real prior.** All nine states are driven
   through the function and each must return sectors, not the fallback — the
   coverage hole restated on the shipped build.

3. **The vocabulary is the classifier's, imported not re-typed.** The map's keys
   are diffed against ``REGIME_STATES`` read from ``models/regime.py``.

4. **The confidence is the PRODUCT of the computed half and the cap**, and BOTH
   are re-derived here from the same run (the D-119 lesson: a two-half check must
   read both halves from the SAME run).

5. **The prior-not-rule caveat is present on every path**, because a caller who
   reads a bare sector list as a recommendation has misread the model.

Run it before trusting a ``sector_rotation_prior`` claim, and re-run it if FRED
changes a route or the classifier's vocabulary changes. A green unit suite says
the code does what the tests say; only this says the *classifier* produces the
labels this function is keyed on.
"""

from __future__ import annotations

import sys
from datetime import date
from typing import TYPE_CHECKING, cast

from macro_engine.config import get_settings
from macro_engine.data_layer.openbb_client import OpenBBClient
from macro_engine.models.contracts import ConfidenceInputs as _ConfidenceInputs
from macro_engine.models.contracts import ModelResult, compute_confidence
from macro_engine.models.equity_macro import (
    SECTOR_PRIOR_EXTENSION_REGIMES,
    SECTOR_ROTATION_PRIOR,
    SPECIFICATION_REGIMES,
    SectorRotationInputs,
    sector_rotation_prior,
)
from macro_engine.models.regime import (
    REGIME_STATES,
    RegimeInputs,
    RegimeState,
    classify_regime_rule_based,
)

if TYPE_CHECKING:
    import pandas as pd


def _fetch(client: OpenBBClient, symbol: str, label: str) -> pd.DataFrame:
    """Mirror how the snapshot builder fetches a registry series."""
    return client.fetch_series(
        provider="fred",
        endpoint="economy.fred_series",
        params={"symbol": symbol},
        series_label=label,
    )


def _values(frame: pd.DataFrame) -> list[float]:
    """The non-null values of a series, in order."""
    clean = frame.loc[frame["value"].notna(), "value"]
    return [float(value) for value in clean]


def _sectors(result: ModelResult) -> list[str]:
    value = result.value
    assert isinstance(value, list), f"value is {type(value).__name__}"
    return [str(item) for item in value]


def main() -> int:
    failures: list[str] = []
    settings = get_settings()
    equity_macro = settings.equity_macro

    print("=" * 78)
    print("SECTION 6.9 — SECTOR ROTATION PRIOR: LIVE WIRING CHECK (END-TO-END)")
    print("=" * 78)
    print(f"  reliability cap:          {equity_macro.reliability_value:.4f}")
    print(f"  no-prior label:           {equity_macro.no_prior_label!r}")
    print(f"  specification rows:       {len(SPECIFICATION_REGIMES)}")
    print(f"  extension rows:           {len(SECTOR_PRIOR_EXTENSION_REGIMES)}")
    print(f"  map size vs vocabulary:   {len(SECTOR_ROTATION_PRIOR)} / {len(REGIME_STATES)}")
    print(f"  as_of:                    {date.today().isoformat()}")
    print()

    # ----------------------------------------------------------------------
    # 1: END-TO-END — the real classifier's state feeds the prior.
    # ----------------------------------------------------------------------
    print("1. END-TO-END — FRED -> classify_regime_rule_based -> sector_rotation_prior")
    live_state: str | None = None
    try:
        client = OpenBBClient()
        try:
            gdp = _values(_fetch(client, "GDPC1", "gdp_real"))
            pot = _values(_fetch(client, "GDPPOT", "gdp_potential"))
            cpi = _values(_fetch(client, "CPIAUCSL", "cpi_headline"))
            unrate = _values(_fetch(client, "UNRATE", "unemployment_rate"))
        finally:
            client.close()

        if len(gdp) < 2 or len(pot) < 2 or len(cpi) < 13 or not unrate:
            failures.append(
                "a classifier input series returned too few observations to form "
                "its axis (GDPC1/GDPPOT/CPIAUCSL/UNRATE) — the live path cannot "
                "be established"
            )
        else:
            output_gap = (gdp[-1] - pot[-1]) / pot[-1] * 100.0
            inflation_yoy = (cpi[-1] - cpi[-13]) / cpi[-13] * 100.0
            inflation_trend_3m = (cpi[-1] - cpi[-4]) / cpi[-4] * 100.0
            unemployment_gap = unrate[-1] - settings.phillips.nairu_value

            regime_inputs = RegimeInputs(
                output_gap=output_gap,
                inflation_yoy=inflation_yoy,
                inflation_trend_3m=inflation_trend_3m,
                unemployment_gap=unemployment_gap,
            )
            regime_result = classify_regime_rule_based(regime_inputs)
            regime_value = regime_result.value
            assert isinstance(regime_value, dict)
            live_state = str(regime_value["state"])

            print(f"  GDPC1  latest            = {gdp[-1]:,.3f}")
            print(f"  GDPPOT latest            = {pot[-1]:,.3f}")
            print(f"  output_gap               = {output_gap:+.3f} %")
            print(f"  inflation_yoy            = {inflation_yoy:+.3f} %")
            print(f"  inflation_trend_3m       = {inflation_trend_3m:+.3f} %")
            print(f"  unemployment_gap         = {unemployment_gap:+.3f} pp")
            print(f"  classify_regime_rule_based -> {live_state!r}")

            if live_state not in SECTOR_ROTATION_PRIOR:
                failures.append(
                    f"the classifier emitted {live_state!r}, which the sector map "
                    f"does NOT cover — the coverage assertion is broken"
                )
            else:
                prior_result = sector_rotation_prior(
                    SectorRotationInputs(regime_state=cast(RegimeState, live_state))
                )
                print(
                    f"  sector_rotation_prior    -> {_sectors(prior_result)} "
                    f"(confidence {prior_result.confidence:.4f})"
                )
                print(f"  interpretation: {prior_result.interpretation}")
    except Exception as exc:  # the check reports, it does not raise
        failures.append(f"the end-to-end path failed: {exc}")
    print()

    # ----------------------------------------------------------------------
    # 2: every declared regime resolves to a REAL prior (no fallback).
    # ----------------------------------------------------------------------
    print("2. COVERAGE — every declared regime returns sectors, not the fallback")
    fallback = [equity_macro.no_prior_label]
    for state in REGIME_STATES:
        result = sector_rotation_prior(SectorRotationInputs(regime_state=cast(RegimeState, state)))
        sectors = _sectors(result)
        origin = "spec" if state in SPECIFICATION_REGIMES else "extension"
        flag = "  <-- FALLBACK" if sectors == fallback else ""
        print(f"  {state:18s} [{origin:9s}] {sectors}{flag}")
        if sectors == fallback:
            failures.append(
                f"regime {state!r} returned the generic fallback — the map is not "
                f"exhaustive over the classifier's vocabulary"
            )
    print()

    # ----------------------------------------------------------------------
    # 3: the vocabulary is the classifier's, imported not re-typed.
    # ----------------------------------------------------------------------
    print("3. VOCABULARY — the map's keys against the classifier's declared states")
    missing = set(REGIME_STATES) - set(SECTOR_ROTATION_PRIOR)
    extra = set(SECTOR_ROTATION_PRIOR) - set(REGIME_STATES)
    print(f"  REGIME_STATES:            {sorted(REGIME_STATES)}")
    print(f"  map keys not in vocab:    {sorted(extra) or 'none'}")
    print(f"  vocab states without row: {sorted(missing) or 'none'}")
    if missing:
        failures.append(f"regimes with no map row: {sorted(missing)}")
    if extra:
        failures.append(f"map keys outside the vocabulary (dead rows): {sorted(extra)}")

    partition_spec = set(SPECIFICATION_REGIMES)
    partition_ext = set(SECTOR_PRIOR_EXTENSION_REGIMES)
    if partition_spec & partition_ext:
        both = partition_spec & partition_ext
        failures.append(f"a regime is both specification and extension: {both}")
    if partition_spec | partition_ext != set(REGIME_STATES):
        failures.append("the specification/extension constants do not cover the vocabulary")
    print()

    # ----------------------------------------------------------------------
    # 4: the confidence — a PRODUCT, both halves from the SAME run.
    # ----------------------------------------------------------------------
    print("4. CONFIDENCE — the product of the computed half and the cap")
    if live_state is not None and live_state in SECTOR_ROTATION_PRIOR:
        live_result = sector_rotation_prior(
            SectorRotationInputs(regime_state=cast(RegimeState, live_state))
        )
        computed = compute_confidence(
            _ConfidenceInputs(
                data_quality_flags_present=False,
                is_heuristic_not_calibrated=not equity_macro.reliability_cap_is_calibrated,
                source_independence_count=1,
                depends_on_unobservable=False,
            )
        )
        expected = computed * equity_macro.reliability_value
        print(f"  computed half (same run)  = {computed:.6f}")
        print(f"  cap                       = {equity_macro.reliability_value:.6f}")
        print(f"  expected product          = {expected:.6f}")
        print(f"  published confidence      = {live_result.confidence:.6f}")
        if abs(live_result.confidence - expected) > 1e-12:
            failures.append(
                f"published confidence {live_result.confidence} != product "
                f"{expected} — the two halves must multiply, and both must come "
                f"from the same run"
            )
    else:
        print("  (skipped — no live state available)")
    print()

    # ----------------------------------------------------------------------
    # 5: the prior-not-rule caveat is present on every path.
    # ----------------------------------------------------------------------
    print("5. THE CAVEAT — the base-rate qualification is published on every path")
    for state in REGIME_STATES:
        result = sector_rotation_prior(SectorRotationInputs(regime_state=cast(RegimeState, state)))
        if "BASE-RATE PRIOR" not in result.context or not any(
            "BASE-RATE PRIOR" in w for w in result.warnings
        ):
            failures.append(f"regime {state!r} published no prior-not-rule caveat")
    print("  caveat present in context AND warnings for all nine regimes")
    print()

    # ----------------------------------------------------------------------
    # Verdict.
    # ----------------------------------------------------------------------
    print("=" * 78)
    if failures:
        print(f"FAILED — {len(failures)} problem(s):")
        for problem in failures:
            print(f"  !! {problem}")
        print("=" * 78)
        return 1
    print("OK — the real classifier's state resolves to a real prior; the map is")
    print("exhaustive; the confidence is the product of both halves from one run;")
    print("the prior-not-rule caveat is published on every path.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
