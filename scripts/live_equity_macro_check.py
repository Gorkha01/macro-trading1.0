"""Live wiring check: real FRED data -> the shipped regime classifier ->
Section 21.3 Tier-5's Module 11 functions (Section 6.9, Section 20.20-E).

Not a test. This directory holds operator scripts, deliberately excluded from the
default test run because they hit the network. Run with::

    uv run python scripts/live_equity_macro_check.py

Section 21.0: unit tests prove the arithmetic, this proves the WIRING. For the
two LOOKUPS whose only input is a regime label, the question is not "does the
lookup work" (a unit test settles that) — it is **"is the label these functions
are keyed on the label the shipped classifier actually produces?"** So this check
runs the REAL pipeline end to end: it fetches the classifier's own inputs from
FRED, runs ``classify_regime_rule_based``, and feeds the state it returns — not a
hand-typed string — into ``sector_rotation_prior`` and ``factor_tilt_prior``.

``duration_sensitivity`` takes no regime, so it is checked against a REAL rate
move: the change in the effective fed funds rate over the fetched window is
computed from FRED and applied to both styles, so the wiring it proves is that a
real rate move produces a sane, correctly-signed price impact.

⚠️ **THE HONESTY TIER IS END-TO-END, NOT CONSTRUCTED-SUBSTITUTE.** Section 1
proves it: the regime that reaches the priors is the classifier's own output on
live data, not a literal chosen to make the demo work. Two independent things
are established that no unit test can:

1. **the classifier emits a state the maps cover.** The whole reason these
   functions exist is that Section 6.9's reference map is keyed on SIX regime
   strings while the classifier declares NINE. Running the real classifier
   therefore tests the CONTRACT between the modules, and the check reports which
   state came out and whether the maps had a row for it.

2. **the coverage assertion holds against the real vocabulary.** ``REGIME_STATES``
   is re-read from the classifier module and diffed against both maps' keys, so a
   future classifier change that added a state would be visible here as well as
   in the unit suite.

What this check establishes
---------------------------

1. **End-to-end: the real regime reaches both priors.** FRED -> ``RegimeInputs``
   -> ``classify_regime_rule_based`` -> ``sector_rotation_prior`` and
   ``factor_tilt_prior``, with the state printed beside each result.

2. **Every declared regime resolves to a real prior.** All nine states are driven
   through both functions and each must return a non-fallback result — the
   coverage hole restated on the shipped build.

3. **The vocabulary is the classifier's, imported not re-typed.** Both maps' keys
   are diffed against ``REGIME_STATES`` read from ``models/regime.py``.

4. **The confidences are PRODUCTS of a computed half and a cap**, and BOTH are
   re-derived here from the same run (the D-119 lesson: a two-half check must
   read both halves from the SAME run).

5. **``duration_sensitivity`` answers a REAL rate move with the right sign.** The
   live fed-funds change is applied to growth and value; a rise must be negative,
   the growth leg three times the value leg, and the pair's ratio must be the
   config duration ratio.

6. **The caveats are present on every path**, because a caller who reads a bare
   sector list or a ``-1.0`` momentum tilt as an instruction has misread the
   models.

Run it before trusting a Module 11 claim, and re-run it if FRED changes a route
or the classifier's vocabulary changes. A green unit suite says the code does what
the tests say; only this says the *classifier* produces the labels these functions
are keyed on.
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
    FACTOR_NAMES,
    FACTOR_REGIME_MAP,
    SECTOR_PRIOR_EXTENSION_REGIMES,
    SECTOR_ROTATION_PRIOR,
    SPECIFICATION_REGIMES,
    DurationSensitivityInputs,
    EquityStyle,
    FactorTiltInputs,
    SectorRotationInputs,
    duration_sensitivity,
    factor_tilt_prior,
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
    print("MODULE 11 — EQUITY MACRO: LIVE WIRING CHECK (END-TO-END)")
    print("=" * 78)
    print(f"  sector reliability cap:   {equity_macro.reliability_value:.4f}")
    print(f"  duration cap:             {equity_macro.duration_reliability_value:.4f}")
    print(f"  factor-tilt cap:          {equity_macro.factor_tilt_reliability_value:.4f}")
    print(f"  no-prior label:           {equity_macro.no_prior_label!r}")
    print(
        f"  duration proxies (g/v):   {equity_macro.duration_growth_proxy_years} / "
        f"{equity_macro.duration_value_proxy_years}"
    )
    print(f"  specification rows:       {len(SPECIFICATION_REGIMES)}")
    print(f"  extension rows:           {len(SECTOR_PRIOR_EXTENSION_REGIMES)}")
    print(f"  sector map vs vocabulary: {len(SECTOR_ROTATION_PRIOR)} / {len(REGIME_STATES)}")
    print(f"  factor map vs vocabulary: {len(FACTOR_REGIME_MAP)} / {len(REGIME_STATES)}")
    print(f"  as_of:                    {date.today().isoformat()}")
    print()

    # ----------------------------------------------------------------------
    # 1: END-TO-END — the real classifier's state feeds both priors.
    # ----------------------------------------------------------------------
    print("1. END-TO-END — FRED -> classify_regime_rule_based -> Module 11 priors")
    live_state: str | None = None
    rate_change_bp: float | None = None
    try:
        client = OpenBBClient()
        try:
            gdp = _values(_fetch(client, "GDPC1", "gdp_real"))
            pot = _values(_fetch(client, "GDPPOT", "gdp_potential"))
            cpi = _values(_fetch(client, "CPIAUCSL", "cpi_headline"))
            unrate = _values(_fetch(client, "UNRATE", "unemployment_rate"))
            # The live rate move for duration_sensitivity: the change in the
            # effective fed funds rate over the last two observations.
            ffr = _values(_fetch(client, "DFF", "fed_funds_effective"))
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
            elif live_state not in FACTOR_REGIME_MAP:
                failures.append(
                    f"the classifier emitted {live_state!r}, which the FACTOR map "
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

                factor_result = factor_tilt_prior(
                    FactorTiltInputs(regime_state=cast(RegimeState, live_state))
                )
                fvalue = factor_result.value
                assert isinstance(fvalue, dict)
                print(
                    "  factor_tilt_prior        -> "
                    + ", ".join(f"{n} {fvalue[n]:+.1f}" for n in FACTOR_NAMES)
                    + f" (confidence {factor_result.confidence:.4f})"
                )

        # The live rate move for duration_sensitivity: the change in the real
        # effective fed funds rate over a ~3-month window (63 business days),
        # not one daily step — a single daily step is very often 0.0, which would
        # make the sign check vacuous. The window is measured, not assumed: if
        # it is still zero the check reports that honestly rather than passing on
        # a degenerate input.
        if len(ffr) >= 64:
            rate_change_bp = (ffr[-1] - ffr[-64]) * 100.0  # percent -> bp
            print(
                f"  DFF 3m window            = {ffr[-64]:.3f} -> {ffr[-1]:.3f} "
                f"({rate_change_bp:+.1f} bp over {len(ffr)} obs)"
            )
        elif len(ffr) >= 2:
            rate_change_bp = (ffr[-1] - ffr[-2]) * 100.0
            print(
                f"  DFF last two             = {ffr[-2]:.3f} -> {ffr[-1]:.3f} "
                f"({rate_change_bp:+.1f} bp; short series, 2-obs window)"
            )
        else:
            failures.append(
                "DFF returned fewer than two observations — the live rate move "
                "for duration_sensitivity cannot be formed"
            )
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
    print("   factor tilts, per regime (value/momentum/quality/low_vol/size):")
    for state in REGIME_STATES:
        fresult = factor_tilt_prior(FactorTiltInputs(regime_state=cast(RegimeState, state)))
        fvalue = fresult.value
        assert isinstance(fvalue, dict)
        if not fvalue:
            failures.append(
                f"regime {state!r} returned an empty factor prior — the map is not "
                f"exhaustive over the classifier's vocabulary"
            )
            continue
        tilts = " ".join(f"{n}={fvalue[n]:+.1f}" for n in FACTOR_NAMES)
        print(f"  {state:18s} {tilts}")
    print()

    # ----------------------------------------------------------------------
    # 3: the vocabulary is the classifier's, imported not re-typed.
    # ----------------------------------------------------------------------
    print("3. VOCABULARY — both maps' keys against the classifier's declared states")
    sector_missing = set(REGIME_STATES) - set(SECTOR_ROTATION_PRIOR)
    sector_extra = set(SECTOR_ROTATION_PRIOR) - set(REGIME_STATES)
    factor_missing = set(REGIME_STATES) - set(FACTOR_REGIME_MAP)
    factor_extra = set(FACTOR_REGIME_MAP) - set(REGIME_STATES)
    print(f"  REGIME_STATES:            {sorted(REGIME_STATES)}")
    print(f"  sector map keys not in v: {sorted(sector_extra) or 'none'}")
    print(f"  sector vocab w/o row:     {sorted(sector_missing) or 'none'}")
    print(f"  factor map keys not in v: {sorted(factor_extra) or 'none'}")
    print(f"  factor vocab w/o row:     {sorted(factor_missing) or 'none'}")
    if sector_missing:
        failures.append(f"sector regimes with no map row: {sorted(sector_missing)}")
    if sector_extra:
        failures.append(f"sector map keys outside the vocabulary: {sorted(sector_extra)}")
    if factor_missing:
        failures.append(f"factor regimes with no map row: {sorted(factor_missing)}")
    if factor_extra:
        failures.append(f"factor map keys outside the vocabulary: {sorted(factor_extra)}")

    # Every factor row must tilt exactly the five declared factors.
    for state, row in FACTOR_REGIME_MAP.items():
        if set(row) != set(FACTOR_NAMES):
            failures.append(f"factor row {state!r} does not tilt exactly {list(FACTOR_NAMES)}")

    partition_spec = set(SPECIFICATION_REGIMES)
    partition_ext = set(SECTOR_PRIOR_EXTENSION_REGIMES)
    if partition_spec & partition_ext:
        both = partition_spec & partition_ext
        failures.append(f"a regime is both specification and extension: {both}")
    if partition_spec | partition_ext != set(REGIME_STATES):
        failures.append("the specification/extension constants do not cover the vocabulary")
    print()

    # ----------------------------------------------------------------------
    # 4: the confidences — PRODUCTS, both halves from the SAME run.
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
        print(f"  sector: computed half     = {computed:.6f}")
        print(f"  sector: cap               = {equity_macro.reliability_value:.6f}")
        print(f"  sector: expected product  = {expected:.6f}")
        print(f"  sector: published conf    = {live_result.confidence:.6f}")
        if abs(live_result.confidence - expected) > 1e-12:
            failures.append(
                f"sector published confidence {live_result.confidence} != product "
                f"{expected} — the two halves must multiply, both from one run"
            )

        f_computed = compute_confidence(
            _ConfidenceInputs(
                data_quality_flags_present=False,
                is_heuristic_not_calibrated=(
                    not equity_macro.factor_tilt_reliability_cap_is_calibrated
                ),
                source_independence_count=1,
                depends_on_unobservable=False,
            )
        )
        f_expected = f_computed * equity_macro.factor_tilt_reliability_value
        factor_result = factor_tilt_prior(
            FactorTiltInputs(regime_state=cast(RegimeState, live_state))
        )
        print(f"  factor: computed half     = {f_computed:.6f}")
        print(f"  factor: cap               = {equity_macro.factor_tilt_reliability_value:.6f}")
        print(f"  factor: expected product  = {f_expected:.6f}")
        print(f"  factor: published conf    = {factor_result.confidence:.6f}")
        if abs(factor_result.confidence - f_expected) > 1e-12:
            failures.append(
                f"factor published confidence {factor_result.confidence} != product "
                f"{f_expected} — the two halves must multiply, both from one run"
            )
    else:
        print("  (skipped — no live state available)")
    print()

    # ----------------------------------------------------------------------
    # 5: duration_sensitivity on a REAL rate move, with the right sign.
    # ----------------------------------------------------------------------
    print("5. DURATION — a real rate move through the growth/value proxy")
    if rate_change_bp is not None:
        growth = duration_sensitivity(
            DurationSensitivityInputs(style="growth", rate_change_bp=rate_change_bp)
        )
        value = duration_sensitivity(
            DurationSensitivityInputs(style="value", rate_change_bp=rate_change_bp)
        )
        g_val = growth.value
        v_val = value.value
        assert isinstance(g_val, float) and isinstance(v_val, float)
        print(f"  live rate move            = {rate_change_bp:+.1f} bp")
        print(f"  growth impact             = {g_val:+.2f} % (confidence {growth.confidence:.4f})")
        print(f"  value impact              = {v_val:+.2f} % (confidence {value.confidence:.4f})")
        ratio = equity_macro.duration_growth_proxy_years / equity_macro.duration_value_proxy_years

        if rate_change_bp == 0.0:
            # A zero live move is DEGENERATE for a sign/ratio check: every impact
            # is 0.0 and the ratio is undefined. Reported honestly and checked
            # with a NON-DEGENERATE declared move instead, so this section still
            # proves the wiring without pretending a 0bp window is evidence.
            print("  live move is ZERO — the ratio and sign checks would be vacuous;")
            print("  re-running them on a declared +25bp move instead:")
            probe = duration_sensitivity(
                DurationSensitivityInputs(style="growth", rate_change_bp=25.0)
            )
            probe_v = duration_sensitivity(
                DurationSensitivityInputs(style="value", rate_change_bp=25.0)
            )
            pg, pv = probe.value, probe_v.value
            assert isinstance(pg, float) and isinstance(pv, float)
            print(f"    +25bp growth            = {pg:+.2f} %")
            print(f"    +25bp value             = {pv:+.2f} %")
            print(f"    growth/value ratio      = {pg / pv:.3f} (expected {ratio:.3f})")
            if not (pg < 0 and pv < 0):
                failures.append("a +25bp probe move produced a non-negative impact")
            if abs(pg / pv - ratio) > 1e-9:
                failures.append(f"the probe growth/value ratio {pg / pv} != config ratio {ratio}")
        else:
            print(f"  growth/value ratio        = {g_val / v_val:.3f} (expected {ratio:.3f})")
            if rate_change_bp > 0 and (g_val >= 0 or v_val >= 0):
                failures.append(
                    f"a RATE RISE ({rate_change_bp:+.1f}bp) produced a non-negative "
                    f"price impact — the discount-rate sign is wrong"
                )
            if rate_change_bp < 0 and (g_val <= 0 or v_val <= 0):
                failures.append(
                    f"a RATE FALL ({rate_change_bp:+.1f}bp) produced a non-positive "
                    f"price impact — the discount-rate sign is wrong"
                )
            if v_val != 0 and abs(g_val / v_val - ratio) > 1e-9:
                failures.append(
                    f"the growth/value ratio {g_val / v_val} != the config proxy ratio "
                    f"{ratio} — the two legs are not using the configured durations"
                )
    else:
        print("  (skipped — no live rate move available)")
    print()

    # ----------------------------------------------------------------------
    # 6: the caveats are present on every path.
    # ----------------------------------------------------------------------
    print("6. THE CAVEATS — qualifications published on every path")
    for state in REGIME_STATES:
        result = sector_rotation_prior(SectorRotationInputs(regime_state=cast(RegimeState, state)))
        if "BASE-RATE PRIOR" not in result.context or not any(
            "BASE-RATE PRIOR" in w for w in result.warnings
        ):
            failures.append(f"regime {state!r} published no prior-not-rule caveat")
        fresult = factor_tilt_prior(FactorTiltInputs(regime_state=cast(RegimeState, state)))
        if not any("momentum" in w.lower() and "crash" in w.lower() for w in fresult.warnings):
            failures.append(f"regime {state!r} published no momentum-crash warning")
    styles: tuple[EquityStyle, ...] = ("growth", "value")
    for style in styles:
        dresult = duration_sensitivity(DurationSensitivityInputs(style=style, rate_change_bp=25.0))
        if not any("ILLUSTRATIVE" in w.upper() for w in dresult.warnings):
            failures.append(f"style {style!r} published no illustrative-proxy warning")
    print("  sector: prior-not-rule caveat — all nine regimes")
    print("  factor: prior-not-rule caveat + momentum-crash warning — all nine regimes")
    print("  duration: illustrative-proxy warning — both styles")
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
    print("OK — the real classifier's state resolves to real sector and factor priors;")
    print("both maps are exhaustive; a real rate move produces a correctly-signed")
    print("duration impact with the configured growth/value ratio; every confidence is")
    print("the product of both halves from one run; all caveats are published.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
