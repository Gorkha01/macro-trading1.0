"""Live wiring check: real correlated returns -> Section 17.1's ``monte_carlo_var``.

Not a test. This directory holds operator scripts, deliberately excluded from
the default test run because they hit the network. Run with::

    uv run python scripts/live_monte_carlo_check.py

Section 21.0: unit tests prove the arithmetic, this proves the WIRING — the
units, the nulls, the frequency, the sign conventions, and whether the numbers
that come out are the numbers the specification says should come out.

Three factors, fetched as REAL series (FRED, via the project's OpenBB client)
--------------------------------------------------------------------------

* ``SP500``        -> daily fractional returns  (an INDEX LEVEL: return it)
* ``BAMLH0A0HYM2`` -> daily changes / 100       (an OAS in percent: difference, decimalise)
* ``DGS10``        -> daily changes / 100       (a yield in percent: difference, decimalise)

The 3x3 correlation matrix and the three factor volatilities are estimated from
those return/change histories, so the joint structure the function consumes is a
MEASURED one rather than a fixture.

**The basis and the unit are two separate corrections, and getting either wrong
is a many-orders-of-magnitude error.** The BASIS differs per series on purpose —
a level is returned, a rate/spread is differenced; mixing them deflates every
cross-factor correlation toward zero through scale alone (the D-049/D-054 "same
basis" failure ``live_cross_market_rv.py`` also exists to prevent). The UNIT is
uniform: everything is expressed as an **annualised fraction**, because
``MonteCarloVaRInputs.factor_volatilities`` are ANNUALISED decimals (``0.15`` =
15%/yr) — the model scales them DOWN to ``horizon_days`` by
``sqrt(horizon_days / periods_per_year)``.

**What this check found.** Its first draft passed ANNUALISED PERCENT figures
(15.06 for equity), and the reported VaR came out at 49.6% of the book. The
second draft correctly decimalised but passed the DAILY decimal, on the strength
of the class docstring's claim that ``factor_volatilities`` are "per-period,
NOT annualised" — and the VaR then came out ~15.9x too small (0.0312% against an
analytic 0.4946%). The docstring was WRONG: ``horizon_scale`` divides by
``sqrt(252)``, so the input is annualised. The unit tests never caught it because
they supply annualised numbers and cross-check with an annualising analytic — two
consistently-wrong-but-mutually-agreeing routes. The defect was fixed in
``models/risk.py`` in the same increment; this check is the only thing that
could have seen it, which is Section 21.0's whole argument.

What this check establishes beyond running the function
-------------------------------------------------------

1. **The sign and unit conventions hold on live values.** Each estimated
   annualised volatility is asserted to land inside a plausible band, so a
   units or basis error (volatility read off a price LEVEL rather than a return,
   or annualised where a per-period decimal is required) fails here rather than
   producing a large number nobody reads.

2. **The production stress transform is exercised — a REAL object, not a
   stand-in.** ``stress_correlations`` is imported from
   ``portfolio/risk_budget.py``, the same callable the thesis risk axis supplies,
   and the caller-supplied target is the configured ``risk.stress_corr`` leaf
   read live. The Protocol is therefore validated against its real implementation.

3. **The LTCM inequality holds on live data.** The stressed VaR must exceed the
   normal VaR, and the stressed diversification ratio must be at least the
   normal one (Section 18.2): a crisis cannot make a book MORE diversified. If
   either were reversed the stress was not a stress on this book, and the
   function's central comparison would be backwards.

4. **The analytic cross-check agrees on live data.** The simulated normal VaR
   must match ``parametric_var`` evaluated on the SAME measured portfolio
   volatility. This is the live counterpart of the unit test that pins the two
   ROUTES to one quantity together — if the Cholesky induction or the sqrt-time
   scale were wrong, the two would diverge on real data even though a synthetic
   fixture might not notice.

5. **Reproducibility on the published seed.** Replaying the seed the result
   published must reproduce the result exactly, which is the property that makes
   a published VaR auditable.

What this check CANNOT validate
-------------------------------
The measured covariance is ONE sample over ONE window, so nothing here
establishes that the sampling window is the right one, nor that the normal-regime
correlations will persist. The function's own tail census and diversification
warnings are the disclosures for that, and they are printed. Whether the
configured stress magnitude is the right one is a *claim about the world*, not a
wiring question, and it is recorded as such in ``settings.yaml`` rather than
established here.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from macro_engine.config import get_settings  # noqa: E402
from macro_engine.data_layer.openbb_client import OpenBBClient  # noqa: E402
from macro_engine.models.contracts import ModelResult  # noqa: E402
from macro_engine.models.risk import (  # noqa: E402
    MonteCarloVaRInputs,
    ParametricVaRInputs,
    monte_carlo_var,
    parametric_var,
)
from macro_engine.portfolio.risk_budget import stress_correlations  # noqa: E402

SETTINGS = get_settings()

#: The three risk factors, as (label, FRED symbol, is_level). ``is_level`` picks
#: the BASIS: a level is returned, a rate/spread is differenced. Both are then
#: decimalised, so every factor is a FRACTION.
_FACTORS: tuple[tuple[str, str, bool], ...] = (
    ("equity", "SP500", True),
    ("credit", "BAMLH0A0HYM2", False),
    ("rates", "DGS10", False),
)

#: A plausible ANNUALISED-FRACTION volatility band per factor — the unit the
#: model's ``factor_volatilities`` uses (equity 0.15 = 15%/yr). Wide on purpose:
#: the point is to fail on an order-of-magnitude mistake, not to pin a regime.
#:
#: The levels matter and were MEASURED (2026-09-24, 745 overlapping obs): an
#: equity index runs ~15%/yr; a HY OAS LEVEL of ~3.1 PERCENT changes by
#: ~0.069 percentage points a day = ~1.1 percentage points a year = ~0.011 as a
#: FRACTION, its own correct unit for comparability with a return; the 10y
#: yield level of ~4% changes ~0.054 pp a day = ~0.86 pp/yr = ~0.0086 as a
#: fraction. The first draft's bands were written for PERCENT-POINT figures,
#: which flagged the (correct) fractional credit vol as out of band — a check
#: that fires on the right answer is a broken check, not a finding.
_VOL_BANDS: dict[str, tuple[float, float]] = {
    "equity": (0.03, 1.20),
    "credit": (0.002, 0.20),
    "rates": (0.001, 0.20),
}

_PERIODS_PER_YEAR = 252
_PORTFOLIO_VALUE = 1_000_000.0
_CONFIDENCE = 0.95


def _fetch(symbols: set[str]) -> dict[str, pd.Series]:
    """Pull each FRED series through the project's OpenBB client."""
    client = OpenBBClient()
    out: dict[str, pd.Series] = {}
    for symbol in sorted(symbols):
        frame = client.fetch_series(
            provider="fred",
            endpoint="economy.fred_series",
            params={"symbol": symbol},
            series_label=symbol,
        )
        out[symbol] = frame.set_index("date")["value"].astype(float).sort_index()
    return out


def _basis(series: pd.Series, *, is_level: bool) -> pd.Series:
    """The DAILY FRACTIONAL change of a series.

    A level is percent-returned (already a fraction). A rate or spread is in
    PERCENTAGE POINTS, so its difference is divided by 100 to reach a fraction —
    the unit correction that makes all three factors comparable for a
    correlation. The result is a DAILY fraction; it is annualised, by
    ``sqrt(252)``, only when it is turned into a ``factor_volatility``.
    """
    if is_level:
        return series.pct_change()
    return series.diff() / 100.0


def _values(result: ModelResult) -> dict[str, object]:
    value = result.value
    assert isinstance(value, dict)
    return value


def _number(result: ModelResult, key: str) -> float:
    item = _values(result)[key]
    assert isinstance(item, (int, float)), f"{key} is {type(item).__name__}"
    return float(item)


def main() -> int:
    failures: list[str] = []

    print("=" * 78)
    print("SECTION 17.1 MONTE CARLO VaR — LIVE WIRING CHECK")
    print("=" * 78)

    print("  fetching real series via OpenBB:")
    raw = _fetch({s for _, s, _ in _FACTORS})

    # --- build the per-factor return/change frame --------------------------
    frame = pd.DataFrame(
        {label: _basis(raw[sym], is_level=level) for label, sym, level in _FACTORS}
    )
    frame = frame.dropna()
    if len(frame) < 60:
        print(f"FAIL — only {len(frame)} overlapping observations; too few to measure")
        return 1
    print(f"  overlapping observations: {len(frame)}")

    # --- measured volatilities, with a band assert -------------------------
    # The model's ``factor_volatilities`` are ANNUALISED decimals (the unit the
    # docstring names and the unit ``horizon_scale`` implies), so the frame's
    # daily fractional series is annualised here. Checking the DAILY number would
    # pass while the model was fed the wrong period.
    print()
    print("  measured volatility (daily decimal | annualised, the model's unit):")
    volatilities: list[float] = []
    for label, _, _ in _FACTORS:
        daily = float(frame[label].std())
        annual = daily * math.sqrt(_PERIODS_PER_YEAR)
        volatilities.append(annual)
        low, high = _VOL_BANDS[label]
        status = "OK" if low <= annual <= high else "OUT-OF-BAND"
        print(f"    vol[{label:<7}] = {daily:.6f} | {annual:7.4f}  [{status}]")
        if not (low <= annual <= high):
            failures.append(
                f"{label} annualised vol {annual:.4f} is outside the plausible "
                f"band [{low}, {high}] — a units or basis error (level vs "
                "return, or a per-period where an annualised figure is required)"
            )

    # --- measured correlation matrix ---------------------------------------
    labels = [label for label, _, _ in _FACTORS]
    correlations = frame.corr().to_numpy().tolist()
    print()
    print("  measured correlation matrix (daily return/change basis):")
    for i, row_label in enumerate(labels):
        cells = "  ".join(f"{float(v):+.3f}" for v in correlations[i])
        print(f"    {row_label:<7} {cells}")

    # --- run through the PRODUCTION transform ------------------------------
    weights = [1.0 / len(labels)] * len(labels)
    inputs = MonteCarloVaRInputs(
        weights=weights,
        factor_volatilities=volatilities,
        normal_correlations=correlations,
        portfolio_value=_PORTFOLIO_VALUE,
        confidence=_CONFIDENCE,
    )
    result = monte_carlo_var(
        inputs,
        stress_correlations=stress_correlations,
        stressed_correlation=SETTINGS.risk.stress_corr,
    )
    var_normal = _number(result, "var_normal_pct")
    var_stressed = _number(result, "var_stressed_pct")
    div_normal = _number(result, "diversification_ratio_normal")
    div_stressed = _number(result, "diversification_ratio_stressed")

    print()
    print(
        "  result (through the production stress transform, target "
        f"risk.stress_corr={SETTINGS.risk.stress_corr}):"
    )
    print(
        f"    normal   {var_normal:.4f}%  "
        f"({_number(result, 'var_normal_amount'):,.2f})   "
        f"diversification {div_normal:.4f}"
    )
    print(
        f"    stressed {var_stressed:.4f}%  "
        f"({_number(result, 'var_stressed_amount'):,.2f})   "
        f"diversification {div_stressed:.4f}"
    )
    ratio = _values(result)["stressed_to_normal_ratio"]
    if ratio is None:
        ratio_text = "absent"
    else:
        assert isinstance(ratio, (int, float))
        ratio_text = f"{float(ratio):.4f}x"
    print(f"    stressed/normal ratio: {ratio_text}")
    print(
        f"    n_sims={_values(result)['n_sims']}  seed={_values(result)['seed']}  "
        f"confidence={result.confidence}"
    )
    for note in result.warnings:
        print(f"    warning: {note}")

    # --- (3) the LTCM inequality on live data ------------------------------
    if not var_stressed > var_normal:
        failures.append(
            f"stressed VaR {var_stressed} did not exceed normal {var_normal} — "
            "the stress did not stress this book"
        )
    if not div_stressed >= div_normal:
        failures.append(
            f"stressed diversification ratio {div_stressed} fell below normal "
            f"{div_normal} — a crisis cannot make a book MORE diversified"
        )

    # --- (4) the analytic cross-check on live data -------------------------
    # ``parametric_var`` takes an ANNUALISED vol and applies its own sqrt-time
    # scale, which is exactly what the model does — so both routes now consume
    # ``volatilities`` (already annualised) on the same basis. When they agree,
    # BOTH the Cholesky induction and the horizon convention are right on real
    # data; when they disagree by a factor of ~16, the model was fed a daily
    # number where an annualised one was expected (the defect this check
    # surfaced: the first draft's docstring named the wrong unit).
    variance = sum(
        weights[i] * weights[j] * float(correlations[i][j]) * volatilities[i] * volatilities[j]
        for i in range(len(labels))
        for j in range(len(labels))
    )
    portfolio_vol = math.sqrt(max(variance, 0.0))
    parametric = parametric_var(
        ParametricVaRInputs(
            portfolio_value=_PORTFOLIO_VALUE,
            vol_annualized=portfolio_vol,
            confidence=_CONFIDENCE,
            horizon_days=1,
        )
    )
    para_pct = _number(parametric, "var_pct")
    delta = abs(var_normal - para_pct)
    print()
    print(
        f"  analytic cross-check: simulated {var_normal:.4f}% vs parametric "
        f"{para_pct:.4f}%  (delta {delta:.4f}pp)"
    )
    # The bound is a SAMPLING tolerance, not an identity: the 5% quantile of one
    # simulated sample carries its own standard error. A wiring error (wrong
    # horizon scale, wrong unit, wrong correlation induction) produces a delta of
    # order percentage points — an order of magnitude above this bound.
    if delta > 0.05:
        failures.append(
            f"simulated normal VaR {var_normal} differs from the analytic "
            f"{para_pct} by {delta}pp — the correlation induction, the horizon "
            "scale, or the volatility unit is wrong on real data"
        )

    # --- (5) reproducibility on the published seed -------------------------
    published_seed = _values(result)["seed"]
    assert isinstance(published_seed, int)
    replay = monte_carlo_var(
        inputs.model_copy(update={"seed": published_seed}),
        stress_correlations=stress_correlations,
        stressed_correlation=SETTINGS.risk.stress_corr,
    )
    if _values(replay) != _values(result):
        failures.append("replaying the published seed did not reproduce the result")
    else:
        print(f"  reproducibility: replaying seed {published_seed} reproduced the result")

    print()
    print("=" * 78)
    if failures:
        print(f"FAIL — {len(failures)} problem(s):")
        for problem in failures:
            print(f"  * {problem}")
        return 1
    print("PASS — the estimator is wired to real data end to end.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
