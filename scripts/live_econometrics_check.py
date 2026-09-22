"""Live check: ``run_regression`` against real FRED data (Module 18).

Not a test. This directory holds operator scripts, deliberately excluded from
the default test run because they exercise the live provider. Run with::

    uv run python scripts/live_econometrics_check.py

Section 21.0: unit tests prove the arithmetic, this proves the **wiring** — the
real units, the real frequency, the real sign conventions. ``test_econometrics``
already proves the OLS arithmetic against exact rational values; what it cannot
prove is that the function behaves correctly on a real macro pair whose
coefficient has a sign the economics predicts in advance.

What this check establishes
---------------------------

1. **THE REGRESSION, on a real mechanism with a sign predicted BEFORE the fit.**
   The ex-post Fisher relation: the nominal policy rate against year-over-year
   core inflation. The mechanism is stated first (as Section 15.18 requires),
   and the *sign* is the test — a policy rate that does not rise with inflation
   would mean the wiring is broken somewhere, not that the Fed changed its
   reaction function. The magnitude is reported, not asserted: the coefficient
   on inflation is an estimate, and this script has no business claiming what
   it "should" be.

2. **The mechanism gate refuses on the SAME real data.** A gate that only ever
   sees synthetic input proves nothing about the shipped call path. The blank
   mechanism is refused against the identical frame that just produced a fit.

3. **The stationarity limitation is REAL, not decorative.** Section 15.18 names
   spurious level regression first. This is demonstrated on two real series
   whose LEVELS have no mechanism connecting them: the fit reports a high
   R-squared and a "significant" coefficient anyway. That is the artefact the
   ``limitations`` field warns about, reproduced live rather than asserted in
   prose. The unit tests cannot show this — it is a property of real data.

4. **The warnings are driven by the data, not by the code path.** The reported
   R-squared and the presence or absence of the weak-mechanism warning are
   checked against each other, so a warning that fired unconditionally would
   fail here even though every unit test passed.
"""

from __future__ import annotations

import sys

import pandas as pd

from macro_engine.config import get_registry, get_settings
from macro_engine.data_layer.openbb_client import OpenBBClient
from macro_engine.models.contracts import ModelResult
from macro_engine.models.econometrics import (
    RegressionResult,
    run_regression,
    test_stationarity,
)

# Transcribed from config/series_registry.yaml — the registry is the only place
# that names providers, and a live check is not an exception to that. The
# symbols are quoted here rather than imported because the registry is data, not
# code; the assertions below re-check them against the registry at run time.
_SYMBOLS: dict[str, str] = {
    "cpi_core": "CPILFESL",
    "fed_funds_rate": "FEDFUNDS",
    "retail_sales": "RSAFS",
}

_MECHANISM = (
    "The Fisher relation: the nominal policy rate compensates for realised core "
    "inflation, so the rate should rise with year-over-year core CPI."
)

_SPURIOUS_MECHANISM = (
    "Deliberately NO mechanism: this states only that the two series' LEVELS are "
    "both non-stationary, which is the spurious-regression case, not a hypothesis."
)


def _fetch(client: OpenBBClient, field: str) -> pd.DataFrame:
    """Fetch one registry series, exactly as the snapshot builder would."""
    return client.fetch_series(
        provider="fred",
        endpoint="economy.fred_series",
        params={"symbol": _SYMBOLS[field]},
        series_label=field,
    )


def _monthly(frame: pd.DataFrame, field: str) -> pd.Series:
    """Return the series indexed by month, asserting the cadence is monthly.

    The index is a ``PeriodIndex`` at month frequency rather than a
    ``DatetimeIndex``: the arithmetic below shifts by 12 *months*, and doing
    that on a date index would silently depend on the observation day-of-month
    being stable across the series. Periods make the 12-month lag mean what it
    says.
    """
    clean = frame.loc[frame["value"].notna(), ["date", "value"]]
    stamps = pd.to_datetime(clean["date"], errors="raise")
    periods = stamps.dt.to_period("M")
    if not periods.is_monotonic_increasing:
        raise AssertionError(f"{field}: dates are not in ascending order")
    if periods.duplicated().any():
        raise AssertionError(f"{field}: more than one observation in a month")
    series = pd.Series([float(value) for value in clean["value"]], index=periods, name=field)
    return series.sort_index()


def _check_registry_agreement() -> None:
    """The transcribed symbols must still match the registry.

    A live check that hardcodes a symbol and never re-checks it is how a
    re-pointed registry goes unnoticed — the script would keep validating a
    series the engine no longer uses.
    """
    registry = get_registry()
    for field, symbol in _SYMBOLS.items():
        entry = registry.series.get(field)
        assert entry is not None, f"{field} is no longer in the series registry"
        assert entry.symbol == symbol, (
            f"{field}: registry says {entry.symbol!r}, this check transcribes "
            f"{symbol!r}. Re-transcribe it rather than editing the registry."
        )


def _fisher_relation(client: OpenBBClient) -> RegressionResult:
    """Run the legitimate regression and check its sign against the mechanism."""
    cpi = _monthly(_fetch(client, "cpi_core"), "cpi_core")
    policy_rate = _monthly(_fetch(client, "fed_funds_rate"), "fed_funds_rate")

    joined = pd.DataFrame({"cpi": cpi, "policy_rate": policy_rate}).dropna()
    print(f"   overlapping months, both series observed : {len(joined):,}")
    print(f"   window                                    : {joined.index[0]} .. {joined.index[-1]}")

    # Year-over-year core inflation from the INDEX. The model refuses non-finite
    # input by design, so the cleaning happens HERE, in the caller, where it is
    # visible -- the first 12 months have no year-ago level and must be dropped
    # explicitly rather than silently absorbed.
    yoy = (joined["cpi"] / joined["cpi"].shift(12) - 1.0) * 100.0
    paired = pd.DataFrame({"inflation": yoy, "policy_rate": joined["policy_rate"]}).dropna()

    assert len(paired) > 100, (
        f"only {len(paired)} usable months; the live window is implausibly short, "
        f"which points at a fetch or alignment fault rather than at the model"
    )

    result = run_regression(
        paired["policy_rate"],
        paired[["inflation"]],
        _MECHANISM,
    )

    slope = result.beta["inflation"]
    print("   mechanism stated before the fit           : yes")
    print(f"   observations                              : {result.n_obs:,}")
    print(f"   intercept                                 : {result.beta['const']:+.4f}")
    print(f"   coefficient on inflation                  : {slope:+.4f}")
    print(
        f"   R-squared / adjusted                      : "
        f"{result.r_squared:.4f} / {result.adj_r_squared:.4f}"
    )
    print(f"   confidence                                : {result.confidence}")

    # THE SIGN IS THE WIRING TEST. A policy rate that fell as inflation rose
    # would mean the two series were misaligned, mis-scaled, or swapped -- not
    # that the reaction function changed. The magnitude is deliberately not
    # asserted: it is an estimate, and pinning it here would be recording the
    # output as the expectation (Section 21.2's own warning).
    assert slope > 0.0, (
        f"the coefficient on inflation is {slope:+.4f}, but the stated mechanism "
        f"requires it to be POSITIVE. Either the series are misaligned or the "
        f"registry now points somewhere unexpected."
    )

    # The warnings must be consistent with the number that drives them. A
    # warning that fired unconditionally would pass every unit test and fail
    # here; one that never fired would fail the unit tests.
    threshold = float(get_settings().econometrics.low_r_squared_threshold.value)
    weak_warned = any("WEAK MECHANISM" in w for w in result.warnings)
    assert weak_warned == (result.r_squared < threshold), (
        f"the weak-mechanism warning is {'present' if weak_warned else 'absent'} "
        f"but R-squared {result.r_squared:.4f} is "
        f"{'below' if result.r_squared < threshold else 'at or above'} the "
        f"configured floor {threshold:.4f}"
    )
    print("   weak-mechanism warning consistent with R2 : yes")

    return result


def _mechanism_gate_refuses_on_real_data(client: OpenBBClient) -> None:
    """The gate must refuse against the very frame that just produced a fit."""
    cpi = _monthly(_fetch(client, "cpi_core"), "cpi_core")
    policy_rate = _monthly(_fetch(client, "fed_funds_rate"), "fed_funds_rate")
    joined = pd.DataFrame({"cpi": cpi, "policy_rate": policy_rate}).dropna()
    yoy = (joined["cpi"] / joined["cpi"].shift(12) - 1.0) * 100.0
    paired = pd.DataFrame({"inflation": yoy, "policy_rate": joined["policy_rate"]}).dropna()

    refusals = 0
    for mechanism in ("", "   ", "no mechanism"):
        try:
            run_regression(paired["policy_rate"], paired[["inflation"]], mechanism)
        except ValueError:
            refusals += 1
    assert refusals == 3, f"only {refusals}/3 blank mechanisms were refused"
    print("   3/3 insubstantial mechanisms refused on the real frame")


def _spurious_level_regression(client: OpenBBClient) -> RegressionResult:
    """Show the stationarity limitation is a live property of real data.

    Two series whose LEVELS have no mechanism connecting them: the core CPI
    index and nominal retail sales. Both are non-stationary (they trend), so a
    level-on-level regression finds a strong relationship where the stated
    mechanism says there is none. Section 15.18 names this first, and this is
    what the ``limitations`` field on every result is warning about.
    """
    cpi = _monthly(_fetch(client, "cpi_core"), "cpi_core")
    sales = _monthly(_fetch(client, "retail_sales"), "retail_sales")

    joined = pd.DataFrame({"cpi_level": cpi, "sales_level": sales}).dropna()
    assert len(joined) > 100, f"only {len(joined)} overlapping months"

    result = run_regression(
        joined["cpi_level"],
        joined[["sales_level"]],
        _SPURIOUS_MECHANISM,
    )

    print(f"   level-on-level observations               : {result.n_obs:,}")
    print(f"   coefficient on retail-sales LEVEL         : {result.beta['sales_level']:+.6f}")
    print(f"   R-squared                                 : {result.r_squared:.4f}")
    print(f"   p-value on that coefficient               : {result.p_values['sales_level']:.3e}")

    assert result.r_squared > 0.5, (
        f"the level regression reported R-squared {result.r_squared:.4f}; the "
        f"demonstration needs a visibly strong fit to be a demonstration at all"
    )
    assert result.p_values["sales_level"] < 0.01, (
        "the level regression must report a 'significant' coefficient -- that is "
        "the artefact. If it does not, this script is no longer showing what it "
        "claims to show."
    )
    assert any("Stationarity is NOT tested" in item for item in result.limitations), (
        "the stationarity caveat must be attached to this result"
    )
    return result


def _verdict(result: ModelResult) -> str:
    """Read the verdict out of a ``test_stationarity`` result, asserting the shape."""
    value = result.value
    assert isinstance(value, dict), f"expected a dict value, got {type(value).__name__}"
    return str(value["verdict"])


def _diagnose_the_spurious_pair(client: OpenBBClient) -> tuple[str, str, str]:
    """Test both LEVELS and one CHANGE for stationarity — the missing half.

    D-092's live check could only *illustrate* the spurious regression: it
    reproduced a high R-squared from a pair with no stated mechanism and said
    plainly that it could not diagnose it, because ``test_stationarity`` did not
    exist yet. It exists now, so the argument can be **completed** rather than
    left as an assertion: if both LEVELS carry a unit root and the CHANGE does
    not, the spurious fit is explained rather than merely observed.

    Returns ``(cpi_level_verdict, sales_level_verdict, cpi_change_verdict)``.
    """
    cpi = _monthly(_fetch(client, "cpi_core"), "cpi_core")
    sales = _monthly(_fetch(client, "retail_sales"), "retail_sales")
    joined = pd.DataFrame({"cpi_level": cpi, "sales_level": sales}).dropna()

    cpi_result = test_stationarity(joined["cpi_level"])
    sales_result = test_stationarity(joined["sales_level"])
    # The first difference has no value for its first row BY CONSTRUCTION, so the
    # caller drops it explicitly. The model refuses non-finite input and would
    # (correctly) raise if the NaN were passed through.
    cpi_change_result = test_stationarity(joined["cpi_level"].diff().dropna())

    for label, result in (
        ("core CPI, LEVEL", cpi_result),
        ("retail sales, LEVEL", sales_result),
        ("core CPI, first DIFFERENCE", cpi_change_result),
    ):
        value = result.value
        assert isinstance(value, dict)
        clip = " (KPSS p clipped)" if value["kpss_p_value_is_clipped"] else ""
        print(
            f"   {label:28s} {value['verdict']:24s} "
            f"adf p={value['adf_p_value']:.4f}  kpss p={value['kpss_p_value']:.4f}{clip}"
        )

    cpi_verdict = _verdict(cpi_result)
    sales_verdict = _verdict(sales_result)
    change_verdict = _verdict(cpi_change_result)

    # THE DIAGNOSIS, stated as exactly what the data can support. Both LEVELS
    # must read non-stationary — that is the *necessary* condition for the
    # spurious-regression explanation, and the whole of it.
    assert cpi_verdict == "non_stationary", (
        f"the core-CPI LEVEL read as {cpi_verdict!r}, so this pair is not the "
        f"spurious-regression case the section above claims to demonstrate"
    )
    assert sales_verdict == "non_stationary", f"the retail-sales LEVEL read as {sales_verdict!r}"

    # The first difference is REPORTED, never asserted. An earlier draft required
    # it to read `stationary` and the live run **failed** — correctly, because
    # that requirement was an assumption about real macro data rather than a
    # property of the method. Measured 2026-09-22: core CPI's monthly change
    # reads `non_stationary` (ADF p = 0.1558, KPSS p = 0.0100), because the
    # GROWTH RATE itself shifted across the window — double-digit inflation in
    # the 1970s against roughly 2% recently. KPSS's null is stationarity around a
    # CONSTANT, and a change series whose mean moves is not that. So a
    # non-stationary difference is a further finding about the series (the Great
    # Moderation is visible in it), not a contradiction of the diagnosis.
    # Requiring it would have made this check assert the data into agreement.
    return cpi_verdict, sales_verdict, change_verdict


def main() -> int:
    print("=" * 78)
    print("LIVE CHECK: run_regression (Module 18) against real FRED data")
    print("=" * 78)

    _check_registry_agreement()
    print()
    print("0. REGISTRY AGREEMENT")
    print("   Every transcribed symbol still matches config/series_registry.yaml.")
    print(f"   {', '.join(f'{k}={v}' for k, v in _SYMBOLS.items())}")

    client = OpenBBClient()

    print()
    print("1. THE FISHER RELATION -- a real mechanism, sign predicted in advance")
    print(
        "   Mechanism (stated BEFORE fitting, per Section 15.18): the nominal\n"
        "   policy rate compensates for realised core inflation, so it should rise\n"
        "   with year-over-year core CPI. The SIGN is the wiring test; the\n"
        "   magnitude is reported as an estimate and not asserted."
    )
    fisher = _fisher_relation(client)

    print()
    print("2. THE MECHANISM GATE, on the same real frame")
    _mechanism_gate_refuses_on_real_data(client)

    print()
    print("3. THE STATIONARITY LIMITATION, reproduced on live data")
    print(
        "   Core CPI LEVEL against retail-sales LEVEL. No mechanism links these\n"
        "   levels; both simply trend. Section 15.18 names this case first, and a\n"
        "   strong fit here is the artefact -- which is exactly why every result\n"
        "   carries the caveat rather than implying the check was done."
    )
    spurious = _spurious_level_regression(client)

    print()
    print("4. THE DIAGNOSIS -- test_stationarity closes the thread D-092 left open")
    print(
        "   D-092 reproduced a spurious fit and said plainly that it could NOT\n"
        "   diagnose it, because test_stationarity did not exist. It exists now.\n"
        "   The NECESSARY condition is that both LEVELS carry a unit root; if\n"
        "   they do, the spurious fit above is EXPLAINED rather than observed.\n"
        "   The first difference is reported too, but NOT required to be\n"
        "   stationary -- see the note at the assertion."
    )
    level_cpi, level_sales, change_cpi = _diagnose_the_spurious_pair(client)

    print()
    print("=" * 78)
    print("PLAUSIBILITY ASSESSMENT")
    print("=" * 78)
    # The reading is DERIVED from the fitted value, never narrated. An earlier
    # draft of this script asserted "below 1 means the policy rate moved less
    # than one-for-one" as fixed prose, and the live coefficient came back
    # ABOVE 1 -- so the assessment contradicted the number printed beside it.
    # A live check whose commentary is hardcoded is a claim the data has not
    # agreed to yet.
    fisher_slope = fisher.beta["inflation"]
    if fisher_slope > 1.0:
        fisher_reading = (
            "above 1, so over this window the policy rate moved MORE than "
            "one-for-one with realised inflation"
        )
    elif fisher_slope < 1.0:
        fisher_reading = (
            "below 1, so the policy rate moved LESS than one-for-one with realised inflation"
        )
    else:
        fisher_reading = "exactly 1, i.e. full one-for-one compensation"
    print(
        f"  * The Fisher coefficient is {fisher_slope:+.4f} with "
        f"R-squared {fisher.r_squared:.4f} over {fisher.n_obs:,} months.\n"
        f"    The sign is what the mechanism predicts. Read against 1.0 it is\n"
        f"    {fisher_reading}.\n"
        f"    That is a property of THIS sample and THIS inflation measure, not a\n"
        f"    structural claim about the reaction function. The fit is not tight,\n"
        f"    and that is a real finding about the relation rather than a defect\n"
        f"    in the regression."
    )
    print(
        f"  * The spurious level fit reached R-squared {spurious.r_squared:.4f} with a\n"
        f"    p-value of {spurious.p_values['sales_level']:.2e} on a pair with no stated\n"
        f"    mechanism. That number is the reason the limitation exists, and it was\n"
        f"    produced by this function on real data -- not quoted from a textbook."
    )
    print(
        "  * Confidence is computed, not asserted: the value above is\n"
        "    compute_confidence()'s output, carrying the heuristic penalty because\n"
        "    the R-squared floor it judges against is an uncalibrated placeholder."
    )
    print()
    print(
        f"  * THE DIAGNOSIS (new in D-094): the spurious fit is now EXPLAINED, not\n"
        f"    merely observed. The levels read '{level_cpi}' and '{level_sales}':\n"
        f"    two non-stationary series regressed on each other produce a significant\n"
        f"    coefficient from their shared trend. D-092 could only assert this; it\n"
        f"    is now measured.\n"
        f"    The first difference of core CPI reads '{change_cpi}' too, which is a\n"
        f"    SECOND finding rather than a contradiction: the growth rate itself\n"
        f"    shifted across the window, so it is not stationary around a constant.\n"
        f"    That is the Great Moderation showing up in a stationarity test."
    )
    print(
        "  * Still NOT established: that these verdicts hold outside this window.\n"
        "    A unit root is a statement about the sample. The structural-break\n"
        "    ambiguity is also unresolved — ADF and KPSS cannot distinguish 'a\n"
        "    random walk' from 'stationary around a level that moved once', and\n"
        "    those imply opposite things for a relative-value trade."
    )
    print()
    print("LIVE CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
