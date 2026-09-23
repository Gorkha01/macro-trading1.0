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

5. **The DAILY-CHANGES requirement is demonstrated, not merely obeyed (D-099).**
   Section 15.20-F runs PCA on daily changes and never on raw levels, because
   levels are trend-dominated and produce a misleading PC1. The model cannot
   refuse levels — it receives a DataFrame of numbers either way — so the
   protection is that the levels shape is *detected and disclosed*. The check
   passes the real Treasury **levels** and requires the length-aware warning to
   fire, then passes the **changes** and requires a coherent spectrum with no
   negative ratio and the sign rule applied. A prohibition (no auto-labelling of
   level/slope/curvature) is asserted as an absence in the published payload.

6. **A rank-deficient panel is refused on real data.** A duplicated real tenor is
   rank-deficient by construction, and the eigendecomposition of such a matrix
   returns a NEGATIVE eigenvalue — silent failure #1. Requiring the refusal here
   means a rejection is reachable through the same fetch-and-align path the
   legitimate call uses, rather than only on a synthetic ``b = 2a`` fixture.
"""

from __future__ import annotations

import sys

import pandas as pd

from macro_engine.config import get_registry, get_settings
from macro_engine.data_layer.openbb_client import OpenBBClient
from macro_engine.models.contracts import ModelResult
from macro_engine.models.econometrics import (
    RegressionResult,
    compute_pca,
    run_regression,
    test_cointegration,
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

# The cointegration pairs, added at D-097. These are NOT registry fields: the
# registry carries the series the ENGINE consumes, and a live check that needs a
# second tenor must not invent a registry entry to get one. They are FRED symbols
# fetched through the same `economy.fred_series` route the registry uses, and the
# route is asserted below rather than assumed.
_COINT_SYMBOLS: dict[str, str] = {
    "fed_funds_daily": "DFF",  # the DAILY effective fed funds rate
    "tips_5yr": "DFII5",  # 5-year TIPS real yield
    "tips_10yr": "DFII10",  # 10-year TIPS real yield
    "tips_30yr": "DFII30",  # 30-year TIPS real yield
    "nominal_10yr": "DGS10",  # 10-year nominal constant-maturity yield
}

# The `compute_pca` panel, added with D-099. Five NOMINAL constant-maturity
# tenors, fetched daily through `economy.fred_series`.
#
# WHY NOT THE REGISTRY'S `treasury_curve` ENTRY, which already names these very
# symbols: that entry is served by the single-call `fixedincome.government.yield_curve`
# route, and the registry records `window_filter_supported: false` for it because
# it was MEASURED to be a LATEST-ONLY snapshot endpoint (with `start_date=2026-09-15`
# and with no `start_date` at all the response was identical: 11 rows, all dated
# 2026-09-17). PCA needs a HISTORY — one row per tenor cannot produce a covariance
# matrix — so the registry's own `symbol:` values for each tenor are fetched
# individually through `economy.fred_series`, which does return history. The
# symbols are transcribed from the registry's `tenors:` block and re-checked
# against it at run time (see `_pca_check_registry_agreement`), so this is a
# second ROUTE to the same series rather than a second source of truth.
#
# DGS6MO is deliberately absent: a five-tenor panel keeps rows-per-series above
# the thin-panel boundary and matches the k = 5 noise-floor table the model
# publishes. Adding a sixth tenor would move the panel off that table.
_PCA_SYMBOLS: dict[str, str] = {
    "3mo": "DGS3MO",
    "1yr": "DGS1",
    "2yr": "DGS2",
    "10yr": "DGS10",
    "30yr": "DGS30",
}

#: How much daily history to request. The model refuses fewer than
#: `pca_min_observations` rows, and a daily series needs roughly 260 business days
#: per year, so this is about two years of trading days.
_PCA_START = "2024-01-01"

_COINT_MECHANISM = (
    "The expectations hypothesis of the term structure: yields at two maturities "
    "of the SAME curve share a common stochastic trend — both move with the "
    "expected path of the policy rate — so their difference should be stationary "
    "even though neither level is."
)

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


def _monthly_symbol(client: OpenBBClient, symbol: str) -> pd.Series:
    """Fetch one FRED symbol and return it as a month-indexed Series.

    The same ``economy.fred_series`` route the registry's ``tips_yields`` entry
    uses, asserted rather than assumed: a cointegration check that fetched
    through some other route would be exercising wiring the engine does not have.

    Duplicate months are dropped keeping the FIRST observation. TIPS yields are
    daily, so a month has many observations and the choice matters — but the
    point of this check is the model on a real monthly series, not a particular
    within-month aggregation rule, and the drop is stated rather than hidden.
    """
    frame = client.fetch_series(
        provider="fred",
        endpoint="economy.fred_series",
        params={"symbol": symbol},
        series_label=symbol,
    )
    clean = frame.loc[frame["value"].notna(), ["date", "value"]]
    periods = pd.to_datetime(clean["date"], errors="raise").dt.to_period("M")
    if not periods.is_monotonic_increasing:
        raise AssertionError(f"{symbol}: dates are not in ascending order")
    series = pd.Series([float(value) for value in clean["value"]], index=periods, name=symbol)
    return series.sort_index()[~series.sort_index().index.duplicated(keep="first")]


def _resolve(symbol_name: str) -> str:
    """Resolve a transcribed name to a FRED symbol from EITHER table.

    The two tables exist for a reason — `_SYMBOLS` mirrors the registry and
    `_COINT_SYMBOLS` holds extra maturities the registry does not carry — but a
    pair may legitimately draw one leg from each (the positive control pairs the
    registry's ``fed_funds_rate`` with the extra ``DFF``). Resolving in one place
    keeps the lookup honest: a name in neither table is a transcription error and
    raises rather than silently fetching something else.
    """
    if symbol_name in _COINT_SYMBOLS:
        return _COINT_SYMBOLS[symbol_name]
    if symbol_name in _SYMBOLS:
        return _SYMBOLS[symbol_name]
    raise AssertionError(
        f"{symbol_name!r} is in neither _SYMBOLS nor _COINT_SYMBOLS — a "
        f"transcription error, not a fetch failure"
    )


def _live_pair(
    client: OpenBBClient,
    left: str,
    right: str,
    *,
    method: str = "engle_granger",
) -> tuple[ModelResult, int]:
    """Run ``test_cointegration`` on a real pair and print every mandated field."""
    a = _monthly_symbol(client, _resolve(left))
    b = _monthly_symbol(client, _resolve(right))
    joined = pd.DataFrame({"a": a, "b": b}).dropna()

    result = test_cointegration(joined["a"], joined["b"], method=method)
    value = result.value
    assert isinstance(value, dict), f"expected a dict value, got {type(value).__name__}"

    half_life = value["half_life_periods"]
    print(
        f"   {left} ~ {right:20s} n={value['n_obs']:4d}  "
        f"stat={value['statistic']:+9.4f}  p={value['p_value']:.4f}  "
        f"cointegrated={value['is_cointegrated']!s:5s}"
    )
    print(
        f"     hedge ratio {value['hedge_ratio']}  "
        f"half-life {half_life if half_life is not None else 'UNESTIMABLE'}  "
        f"regime {value['regime_stability']}  "
        f"window {joined.index[0]}..{joined.index[-1]}"
    )
    return result, len(joined)


def _cointegration_positive_control(client: OpenBBClient) -> ModelResult:
    """A real pair the test SHOULD reject, so a rejection is reachable live.

    ``FEDFUNDS`` (the monthly effective federal funds rate) against ``DFF`` (the
    DAILY effective rate) measures the same policy rate at two frequencies, so a
    failure to find cointegration would be a wiring fault rather than a finding.
    Measured 2026-09-23 over 1954-07 .. 2026-08 (n = 866): p = 0.0000,
    ``is_cointegrated = True``, hedge ratio 0.949, half-life 0.73 periods, regime
    stability ``stable``.

    This is the **necessary** condition only. It is NOT asserted that a
    MACRO-economic pair must cointegrate — the runs below show real term-structure
    pairs that do NOT — but a test that could never reject on live data would make
    every non-rejection meaningless, so one reachable rejection is required.
    """
    result, _ = _live_pair(client, "fed_funds_rate", "fed_funds_daily")
    value = result.value
    assert isinstance(value, dict)

    assert value["is_cointegrated"] is True, (
        f"the same policy rate at two frequencies did not cointegrate "
        f"(p = {value['p_value']}); that points at a wiring fault, not at the "
        f"economy"
    )
    assert value["regime_stability"] == "stable", (
        f"the regime-stability check returned {value['regime_stability']!r} on the "
        f"strongest pair available; both halves should support a relationship this "
        f"mechanical"
    )
    # The hedge ratio must be near 1: these are the SAME quantity in the SAME
    # units, so any other coefficient is a sign of misalignment. This is the one
    # place a magnitude is legitimate to assert, because the mechanism pins it.
    hedge = value["hedge_ratio"]
    assert isinstance(hedge, float)
    assert abs(hedge - 1.0) < 0.2, (
        f"hedge ratio {hedge} is far from 1.0 for two measurements of the same "
        f"rate — the series are probably not the ones intended"
    )
    return result


def _cointegration_term_structure(client: OpenBBClient) -> list[tuple[str, bool, str]]:
    """The real term-structure pairs, REPORTED rather than asserted.

    This is the honest half, and it is the reason the check is worth running.
    Three pairs on the SAME curve, all with the expectations-hypothesis mechanism
    stated in advance, and their outcomes measured 2026-09-23:

    * ``DFII5 ~ DFII10`` — p = 0.1402, NOT cointegrated, ``absent_in_both_halves``;
    * ``DFII10 ~ DFII30`` — p = 0.5822, NOT cointegrated, ``absent_in_both_halves``;
    * ``DFII10 ~ DGS10`` — p = 0.0741, NOT cointegrated, **``unstable``**.

    **The narrative loses here, and the record says so.** The tempting story is
    that yields on one curve cointegrate because they share a policy-rate trend.
    Over these windows they do NOT: the spreads are wide and persistent (the
    2013 taper episode and the 2022-23 inversion are visible in them), and a
    two-half split finds the relationship either absent or actively contradictory.
    Asserting cointegration here would have been a live check that asserted the
    data into agreement — D-094's exact failure, three increments later.

    The ``unstable`` pair is the most instructive: it is a term spread whose
    halves disagree, which is the LTCM shape the first mandatory warning
    describes, found in real data rather than quoted from a history book.

    Every outcome is returned for the assessment below to read. Unlike the
    spurious-regression section, NOTHING here is asserted about the verdicts —
    only that the published fields are mutually consistent, which is a property of
    the function and not of the economy.
    """
    outcomes: list[tuple[str, bool, str]] = []
    for left, right in (
        ("tips_5yr", "tips_10yr"),
        ("tips_10yr", "tips_30yr"),
        ("tips_10yr", "nominal_10yr"),
    ):
        result, _ = _live_pair(client, left, right)
        value = result.value
        assert isinstance(value, dict)
        verdict = str(value["regime_stability"])
        rejected = bool(value["is_cointegrated"])

        # CONSISTENCY, not agreement with a prior. These are the properties the
        # function promises, and they must hold on real data as well as synthetic:
        assert verdict in {"stable", "unstable", "absent_in_both_halves", "not_tested"}
        # A full-sample rejection neither half reproduces is a contradiction the
        # function must warn about rather than publish quietly. Collapsed to one
        # condition rather than an `if` around an `if`: the outer test is implied
        # by the message the inner one asserts on.
        if verdict == "absent_in_both_halves" and rejected:
            assert any("NOT REPRODUCED BY EITHER HALF" in w for w in result.warnings)
        if not rejected:
            assert any("NO COINTEGRATION DETECTED" in w for w in result.warnings)
        # The two mandatory warnings, on every live call.
        assert "BACKWARD-LOOKING" in result.warnings[0]
        assert "MULTIPLE" in result.warnings[1].upper()

        outcomes.append((f"{left} ~ {right}", rejected, verdict))
    return outcomes


def _cointegration_multiple_testing_is_counted() -> tuple[int, float, float]:
    """The counting obligation, checked against the arithmetic on live settings.

    Section 15.18-F makes this a COUNT rather than a sentence, so a live check
    that only confirmed the warning's presence would miss a hardcoded family size
    or an arithmetic slip. The published counts are recomputed here from the
    configured size and family and compared exactly.
    """
    settings = get_settings().econometrics
    alpha = float(settings.significance_level.value)
    family = int(settings.assumed_test_family_size.value)

    result = test_cointegration(*_synthetic_pair())
    value = result.value
    assert isinstance(value, dict)

    expected_family_wise = 1.0 - (1.0 - alpha) ** family
    expected_corrected = 1.0 - (1.0 - alpha) ** (1.0 / family)
    assert value["family_size_assumed"] == family
    assert abs(float(value["family_wise_error_rate"]) - expected_family_wise) < 1e-8
    assert abs(float(value["corrected_per_test_size"]) - expected_corrected) < 1e-8
    print(
        f"   at alpha = {alpha} and an assumed family of {family}: family-wise "
        f"error rate {expected_family_wise:.4f}, corrected per-test size "
        f"{expected_corrected:.8f}"
    )
    return family, expected_family_wise, expected_corrected


def _synthetic_pair() -> tuple[pd.Series, pd.Series]:
    """A small deterministic cointegrated pair, for the settings-arithmetic check.

    Used only where the check is about the CONFIGURED numbers rather than about
    the data — fetching a real series to verify ``1 - (1 - alpha)^m`` would add a
    network call and a source of variation to an arithmetic assertion.
    """
    index = pd.RangeIndex(200)
    steps = [((i * 37) % 11) - 5.0 for i in range(200)]
    x = pd.Series(pd.Series(steps).cumsum().to_numpy(), index=index, name="x")
    noise = [0.5 * (((i * 13) % 7) - 3.0) for i in range(200)]
    y = pd.Series(x.to_numpy() + noise, index=index, name="y")
    return y, x


# ---------------------------------------------------------------------------
# compute_pca (Section 15.20-F). Added at D-099.
# ---------------------------------------------------------------------------


def _pca_check_registry_agreement() -> None:
    """The transcribed tenor symbols must still match the registry's curve entry.

    The registry's ``treasury_curve`` block carries a ``tenors:`` mapping from
    this check's names to exactly these FRED symbols, and that mapping is
    documentation of what each tenor *is* even though the single-call route does
    not send it. Re-checking it here means a re-pointed registry is caught rather
    than silently invalidating the panel's labels: if ``3mo`` stopped meaning
    ``DGS3MO``, the loadings would still be published under the label ``3mo``
    while describing a different series.
    """
    entry = get_registry().series.get("treasury_curve")
    assert entry is not None, "treasury_curve is no longer in the series registry"
    declared = entry.tenors or {}
    for tenor, symbol in _PCA_SYMBOLS.items():
        assert tenor in declared, (
            f"tenor {tenor!r} is no longer declared on the registry's treasury_curve "
            f"entry; this check transcribes it from there"
        )
        assert declared[tenor] == symbol, (
            f"treasury_curve.{tenor}: registry says {declared[tenor]!r}, this check "
            f"transcribes {symbol!r}. Re-transcribe it rather than editing the registry."
        )


def _pca_panel(client: OpenBBClient) -> pd.DataFrame:
    """Fetch each tenor's daily history and join on the common observation dates.

    Two things are done HERE rather than inside the model, and both are stated
    because the model refuses them by design:

    * **The join is an inner join on date.** A tenor that did not trade on a day
      the others did would leave a NaN, and the model refuses a non-finite panel
      rather than dropping rows silently — so the alignment happens in the caller
      where it is visible.
    * **The first difference is taken HERE.** Section 15.20-F is explicit that PCA
      runs on DAILY CHANGES, never on raw levels, because levels are
      trend-dominated and produce a misleading PC1. The ``.diff()`` is therefore
      the caller's obligation, and the check below asserts the model would have
      WARNED had the levels been passed instead — so the requirement is
      demonstrated rather than merely obeyed.
    """
    frames: dict[str, pd.Series] = {}
    for tenor, symbol in _PCA_SYMBOLS.items():
        raw = client.fetch_series(
            provider="fred",
            endpoint="economy.fred_series",
            params={"symbol": symbol, "start_date": _PCA_START},
            series_label=f"treasury.{tenor}",
        )
        clean = raw.loc[raw["value"].notna(), ["date", "value"]]
        stamps = pd.to_datetime(clean["date"], errors="raise")
        series = pd.Series(
            [float(value) for value in clean["value"]],
            index=stamps,
            name=tenor,
        ).sort_index()
        frames[tenor] = series[~series.index.duplicated(keep="last")]

    joined = pd.DataFrame(frames).dropna()
    print(f"   tenors fetched                            : {', '.join(_PCA_SYMBOLS)}")
    print(f"   common daily observations (inner join)     : {len(joined):,}")
    first, last = joined.index[0].date(), joined.index[-1].date()
    print(f"   window                                    : {first} .. {last}")
    return joined


def _pca_levels_warning_is_reachable(levels: pd.DataFrame) -> str:
    """Pass the RAW LEVELS and confirm the model flags them — the 15.20-F trap.

    This is the check that earns its network call. The model cannot stop a caller
    from passing levels (it receives a DataFrame of numbers either way), so the
    only protection against the trend-dominated PC1 is that the levels shape is
    *detected and disclosed*. Demonstrating that on real Treasury levels — which
    are the canonical case the warning was written for — is what makes the
    disclosure a property of real data rather than of a synthetic fixture.

    Returns the warning string, so the assessment below can quote it.
    """
    result = compute_pca(levels, 3)
    matched = next((w for w in result.warnings if "lag-1 autocorrelation" in w), None)
    assert matched is not None, (
        f"compute_pca did NOT warn on real Treasury LEVELS. Level series are the "
        f"case Section 15.20-F names first, so a silent pass here means the "
        f"length-aware boundary is no longer catching them. Warnings were: "
        f"{result.warnings}"
    )
    print(f"   levels warning fired                      : {matched[:96]}...")
    return matched


def _pca_on_real_changes(client: OpenBBClient) -> ModelResult:
    """The legitimate call: PCA on real Treasury daily changes.

    Three properties are asserted, and each is a property of the FUNCTION rather
    than of the economy — the distinction this script's other sections are
    careful about:

    1. **The ratios are a valid probability distribution over components** and
       every one is non-negative. A negative ratio is silent failure #1
       (the rank-deficient eigendecomposition), and it is checked on real data
       here as well as synthetically.
    2. **The sign rule holds.** The largest-|loading| element of every published
       component is positive. `eigh` returns arbitrary signs, so this is the one
       convention that makes two runs comparable.
    3. **Nothing is auto-labelled.** The published payload must NOT contain a
       level/slope/curvature label — Section 15.20-F forbids it, because the
       assignment is an interpretation and not an output of the decomposition.
       Asserted as an absence, which is the testable form of a prohibition.
    """
    levels = _pca_panel(client)
    _pca_levels_warning_is_reachable(levels)
    changes = levels.diff().dropna()

    result = compute_pca(changes, 3)
    value = result.value
    assert isinstance(value, dict), f"expected a dict value, got {type(value).__name__}"

    ratios = value["explained_variance_ratios"]
    assert isinstance(ratios, list)
    assert all(float(r) >= 0.0 for r in ratios), (
        f"a NEGATIVE variance ratio was published on real data: {ratios}. That is "
        f"silent failure #1 -- a rank-deficient panel whose eigendecomposition went "
        f"through the rank guard"
    )
    total = sum(float(r) for r in ratios)
    assert abs(total - 1.0) < 1e-9, f"the ratios sum to {total}, not 1.0"

    loadings = value["loadings"]
    assert isinstance(loadings, dict)
    for component, mapping in loadings.items():
        assert isinstance(mapping, dict)
        largest = max(mapping.items(), key=lambda kv: abs(float(kv[1])))
        assert float(largest[1]) > 0.0, (
            f"{component}'s largest-|loading| element ({largest[0]}) is "
            f"{largest[1]}, so the sign rule was not applied"
        )

    # The prohibition, asserted as an ABSENCE. A payload that grew a
    # `pc1_label: "level"` field would violate 15.20-F while looking helpful.
    flat = " ".join(str(item) for item in value).lower()
    for forbidden in ("level", "slope", "curvature"):
        assert forbidden not in flat, (
            f"the published payload contains {forbidden!r}, but Section 15.20-F "
            f"forbids auto-labelling components -- the label is an interpretation, "
            f"not a decomposition output"
        )

    print(
        f"   PC1 / PC2 / PC3 variance ratios           : "
        f"{', '.join(f'{float(r):.4f}' for r in ratios[:3])}"
    )
    print(
        f"   3-component cumulative                     : "
        f"{float(value['n_components_explained_variance']):.4f}"
    )
    print(f"   standardisation route published            : {value['standardisation']}")
    print(f"   sign rule published                        : {value['sign_rule']}")
    print(f"   confidence                                 : {result.confidence}")
    return result


def _pca_positive_control(client: OpenBBClient) -> str:
    """A panel that MUST be refused, so a refusal is reachable on real data.

    Two tenors of the same curve are driven by the same policy-rate factor, so at
    daily frequency their changes can be strongly co-moving — and if one tenor is
    an exact multiple of another the panel is rank-deficient and the
    eigendecomposition would return a negative variance. That is silent failure
    #1 on REAL data rather than on a synthetic `b = 2a` fixture.

    The control is built by duplicating a real tenor under a second label, which
    is rank-deficiency BY CONSTRUCTION and therefore guaranteed to be refused. The
    value of doing it with real numbers is that it exercises the guard through the
    same fetch-and-align path the legitimate call uses.
    """
    levels = _pca_panel(client)
    changes = levels.diff().dropna()
    changes["duplicate_10yr"] = changes["10yr"]
    try:
        compute_pca(changes, 3)
    except ValueError as exc:
        message = str(exc)
        assert "rank-deficient" in message, (
            f"a panel containing a DUPLICATED real tenor was refused, but for the "
            f"wrong reason: {message[:160]}"
        )
        print(f"   duplicated real tenor refused             : {message[:88]}...")
        return message
    raise AssertionError(
        "a panel with a duplicated real 10yr tenor was ACCEPTED. That is silent "
        "failure #1: the eigendecomposition of a rank-deficient matrix returns a "
        "negative eigenvalue, so a negative variance would be publishable."
    )


def main() -> int:
    print("=" * 78)
    print("LIVE CHECK: Module 18 econometrics against real FRED data")
    print("             (run_regression, test_stationarity, test_cointegration, compute_pca)")
    print("=" * 78)

    _check_registry_agreement()
    print()
    print("0. REGISTRY AGREEMENT")
    print("   Every transcribed symbol still matches config/series_registry.yaml.")
    print(f"   {', '.join(f'{k}={v}' for k, v in _SYMBOLS.items())}")
    print(
        "   The cointegration symbols are NOT registry fields — they are extra\n"
        "   maturities fetched through the same `economy.fred_series` route the\n"
        "   registry uses, and the routes are asserted when they are fetched:"
    )
    print(f"   {', '.join(f'{k}={v}' for k, v in _COINT_SYMBOLS.items())}")

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
    print("5. COINTEGRATION -- the counting obligation, on the configured numbers")
    print(
        "   Section 15.18-F makes the multiple-testing correction a COUNT rather\n"
        "   than a sentence, so the published figures are recomputed here from the\n"
        "   configured size and family and compared exactly."
    )
    family, family_wise, corrected = _cointegration_multiple_testing_is_counted()

    print()
    print("6. COINTEGRATION -- a POSITIVE CONTROL the test should reject")
    print(
        "   Mechanism (stated BEFORE fitting): the expectations hypothesis of the\n"
        "   term structure. FEDFUNDS and DFF measure the SAME policy rate at two\n"
        "   frequencies, so a non-rejection here would be a wiring fault rather\n"
        "   than a finding."
    )
    positive = _cointegration_positive_control(client)

    print()
    print("7. COINTEGRATION -- the REAL term-structure pairs, reported not asserted")
    print(
        "   Three pairs on the same curve, all with the expectations-hypothesis\n"
        "   mechanism stated in advance. The tempting story is that yields sharing\n"
        "   a policy-rate trend must cointegrate. The outcomes below are reported\n"
        "   as measured; NONE is asserted, because asserting one would be a live\n"
        "   check that asserts the data into agreement."
    )
    term_outcomes = _cointegration_term_structure(client)

    print()
    print("8. PCA -- the DAILY-CHANGES requirement, on real Treasury history")
    print(
        "   Section 15.20-F is explicit: PCA runs on DAILY CHANGES, never raw\n"
        "   levels, because levels are trend-dominated and produce a misleading\n"
        "   PC1. The model cannot refuse levels (it receives numbers either way),\n"
        "   so the protection is that the levels shape is DETECTED and DISCLOSED.\n"
        "   Both halves are exercised below: the warning must fire on the real\n"
        "   levels, and the legitimate call must produce a coherent spectrum."
    )
    _pca_check_registry_agreement()
    pca = _pca_on_real_changes(client)

    print()
    print("9. PCA -- a POSITIVE CONTROL that must be refused")
    print(
        "   A duplicated real tenor makes the panel rank-deficient by\n"
        "   construction, and the eigendecomposition of such a matrix returns a\n"
        "   NEGATIVE eigenvalue. A negative variance is incoherent, so the guard\n"
        "   must refuse -- and doing it on real numbers exercises the same\n"
        "   fetch-and-align path the legitimate call uses."
    )
    _pca_positive_control(client)

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
    print(
        "  * COINTEGRATION (new in D-097). The three mandated extras — the spread,\n"
        "    the half-life, the regime-stability check — are all produced on real\n"
        "    data, and the two mandatory warnings are attached to every live call."
    )
    positive_value = positive.value
    assert isinstance(positive_value, dict)
    print(
        f"    The positive control (FEDFUNDS ~ DFF) rejects at p = "
        f"{positive_value['p_value']:.4f} with hedge ratio "
        f"{positive_value['hedge_ratio']} and regime "
        f"'{positive_value['regime_stability']}' — so a rejection IS reachable on\n"
        f"    live data, and every non-rejection below is therefore informative."
    )
    print(
        "    THE TERM-STRUCTURE PAIRS DID NOT COINTEGRATE, and that is the finding\n"
        "    rather than a failure of the check:"
    )
    for label, rejected, verdict in term_outcomes:
        print(f"      {label:26s} cointegrated={rejected!s:5s} regime={verdict}")
    print(
        "    The expectations hypothesis is a statement about EX-ANTE yields; the\n"
        "    realised spreads here are wide and persistent (the 2013 taper episode\n"
        "    and the 2022-23 inversion both sit inside the window), which is exactly\n"
        "    what makes them fail a stationarity test. The 'unstable' pair is the\n"
        "    LTCM shape -- two sub-periods that disagree -- found in real data.\n"
        "    Asserting cointegration would have been the D-094 failure repeated:\n"
        "    a live check that asserted the data into agreement."
    )
    print()
    print(
        f"  * The multiple-testing obligation is COUNTED, not narrated: at "
        f"alpha = {get_settings().econometrics.significance_level.value} and an\n"
        f"    assumed family of {family} tests, the family-wise error rate is "
        f"{family_wise:.4f}\n"
        f"    and the corrected per-test size is {corrected:.8f}. The family size is\n"
        f"    an ASSUMPTION this function cannot verify — it tests one pair and\n"
        f"    cannot see the others — so it is published beside the counts."
    )
    print()
    print(
        "  * NOT established by the cointegration section: that any of these\n"
        "    verdicts will hold going forward. The statistic describes the sample,\n"
        "    which is the first mandatory warning; the LTCM shape appears here as\n"
        "    the 'unstable' pair, not as a citation."
    )
    print()
    pca_value = pca.value
    assert isinstance(pca_value, dict)
    pca_ratios = pca_value["explained_variance_ratios"]
    assert isinstance(pca_ratios, list)
    print(
        f"  * PCA (new in D-099). On real Treasury daily changes "
        f"({pca_value['n_obs']} common\n"
        f"    observations, {pca_value['n_variables']} tenors), the first "
        f"three components explain\n"
        f"    {float(pca_value['n_components_explained_variance']):.4f} of the "
        f"variance and no\n"
        f"    component returned a negative ratio -- so the rank guard held on "
        f"real data\n"
        f"    as well as on the synthetic cases."
    )
    print(
        "    THE COMPONENTS ARE NOT NAMED, DELIBERATELY. Section 15.20-F forbids\n"
        "    auto-labelling them level/slope/curvature: the assignment is an\n"
        "    INTERPRETATION of the loadings, not an output of the decomposition, and\n"
        "    this check asserts the published payload contains no such label. A\n"
        "    reader who wants the names must read the loadings and decide."
    )
    print(
        "    The levels case is the reason the function exists in the shape it\n"
        "    does: passing the raw Treasury LEVELS fires the length-aware warning,\n"
        "    which is what tells a caller their PC1 is the trend rather than a\n"
        "    factor. That warning was verified reachable on real data above.\n"
        "    NOT established: that the standardisation route chosen in config is\n"
        "    the right one for a particular question. Measured 2026-09-23, the\n"
        "    covariance and correlation routes disagree by 0.28 on PC1's loadings\n"
        "    and invert their ordering, so the route is published on every result\n"
        "    and a consumer who ignores it is reading a different decomposition."
    )
    print()
    print("LIVE CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
