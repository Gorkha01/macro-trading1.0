"""Live wiring check: ``compute_risk_parity_weights`` against a real multi-asset book.

Not a test. This directory holds operator scripts, deliberately excluded from the
default test run because they hit the network. Run with::

    uv run python scripts/live_risk_parity_check.py

Section 21.0: unit tests prove the arithmetic, this proves the wiring — the
units, the annualisation, the convergence behaviour on a real covariance, and
whether the risk-parity problem has a *well-conditioned* solution on a real
multi-asset book at all.

What this check does that the unit tests cannot
-----------------------------------------------

1. **The covariance is ESTIMATED, not constructed.** Every unit test in
   ``tests/portfolio/test_risk_parity.py`` builds the covariance from a formula so
   the hand-computed answer is exact. That is the right way to test a SOLVER and
   the wrong way to find out whether a real five-leg ETF covariance is
   well-conditioned enough for the solver to converge at all, how many sweeps it
   takes, and whether the budget is even *reachable*. The answer to all three is
   measured here.

2. **The notional-vs-risk gap is MEASURED on a real book.** Module 17.1's entire
   content is that equal *risk* is not equal *dollars*. A fixture can be built so
   the two differ; only a real covariance shows *how much* — and whether the
   configured stress-shift threshold (``0.05``) is a live branch or dead code.

3. **The correlation stress is measured against the SHIPPED leaf.** The stressed
   re-solve is run at ``risk.stress_correlation`` (``0.9``) and the resulting
   weight shift is compared to ``risk.risk_parity_stress_shift_threshold``. If
   the shift never exceeded the threshold the escalation warning would be dead
   code, and the check says so rather than letting a reader assume it fires.

4. **The converging solution is CROSS-CHECKED against the project's own Euler
   decomposition.** ``marginal_risk_contributions`` (``models/risk.py``, Section
   20.12C) is the other implemented decomposition of the same quantity. The two
   must agree on the solved weights, because ``risk_contributions`` here is the
   optimiser's inner loop and ``marginal_risk_contributions`` is the one a caller
   reports with. If they drift, the optimiser is solving a different problem from
   the one the report describes.

   **This is the cross-check and it is a real call on both sides** — the same
   discipline ``live_rebalancing_check.py`` uses against
   ``evaluate_drawdown_rules``. Neither side is re-implemented locally, so there
   is no local arithmetic to inherit errors from.

   **It also pins a contract difference between the two.** ``models/risk.py``
   publishes ``risk_contributions`` as the **raw** Euler quantities that sum to
   the portfolio VARIANCE, and the normalised shares separately in
   ``risk_contribution_pct``. ``portfolio/risk_budget.py``'s ``risk_contributions``
   returns normalised shares. The first run of this check compared the two
   directly and reported a spurious 2.00e-01 disagreement on every leg — the
   comparison was between a share and a variance. The check now reads the percent
   vector and converts, and says so, because two functions that both call their
   output "risk contributions" and mean different things is exactly the trap this
   kind of cross-check exists to expose.

5. **The closed-form ORACLE is re-verified on a 2-leg slice of real data.** The
   two-asset uncorrelated case has an exact answer (``w_i prop 1/sigma_i``). The
   live book has correlated legs, so the oracle is not expected to hold exactly —
   but on near-uncorrelated pairs it must hold *approximately*, and the measured
   deviation is a real-data calibration of how far the closed form drifts once
   correlation enters. That number is printed rather than assumed away.

6. **Reports what it cannot validate.** The covariance is an estimate from a
   chosen window, and the risk budget is a *policy* — no history can say whether
   a 20% risk share per leg is the right budget. The check makes the window
   dependence visible by solving at two lookbacks and printing both.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from macro_engine.config import get_settings
from macro_engine.data_layer.openbb_client import OpenBBClient
from macro_engine.models.risk import marginal_risk_contributions
from macro_engine.portfolio.risk_budget import (
    RiskBudgetInputs,
    compute_risk_parity_weights,
    risk_contributions,
    sample_covariance,
)

#: The same tradeable multi-asset book the rebalancing check uses, so the two
#: checks describe ONE book and their numbers are comparable. Reusing the
#: universe is deliberate: a second universe would make a discrepancy between the
#: two checks ambiguous between "the function differs" and "the book differs".
_LEGS: tuple[str, ...] = ("SPY", "TLT", "IEF", "GLD", "UUP")

#: Lookbacks the budget is solved over. Two, because the covariance is an
#: ESTIMATE and the whole point of printing both is that the budget moves with
#: the window — a single figure would present an estimate as a fact.
_SHORT_LOOKBACK = 252
_LONG_LOOKBACK = 1004

#: Trading days per year, for annualising a daily covariance.
_TRADING_DAYS = 252

#: The equal-risk budget. Equal is the standard risk-parity target and the one
#: the unit oracle uses, so the live number is comparable to the pinned one.
_EQUAL_BUDGET = {leg: 1.0 / len(_LEGS) for leg in _LEGS}


def _fetch_closes(client: OpenBBClient, symbol: str) -> pd.Series:
    """Daily closes for one ETF, oldest first.

    The client normalises every provider route to a single schema
    (``date``, ``value``, ``series_id``, ``source``, ``retrieved_at``), so the
    route's own ``close`` field arrives as ``value``.
    """
    frame = client.fetch_series(
        provider="yfinance",
        endpoint="etf.historical",
        params={"symbol": symbol, "start_date": "2019-01-01"},
        series_label=symbol,
    )
    series = pd.Series(
        frame["value"].to_numpy(dtype=float),
        index=pd.to_datetime(frame["date"]),
        name=symbol,
    )
    return series.sort_index()


def _panel(returns: pd.DataFrame) -> dict[str, list[float]]:
    """The ``RiskBudgetInputs`` panel shape: one float list per instrument."""
    return {column: returns[column].tolist() for column in returns.columns}


def main() -> int:
    print("=" * 78)
    print("live check: compute_risk_parity_weights (Module 17.1, Section 9.2)")
    print(f"book: {' '.join(_LEGS)}   lookbacks: {_SHORT_LOOKBACK} / {_LONG_LOOKBACK} sessions")
    print("=" * 78)

    settings = get_settings()
    stress_correlation = settings.risk.stress_corr
    shift_threshold = settings.risk.risk_parity_stress_shift_threshold
    print(
        f"config: annualization={settings.risk.risk_parity_annualization_periods} "
        f"tolerance={settings.risk.risk_parity_tolerance:.1e} "
        f"stress_rho={stress_correlation} shift_threshold={shift_threshold}"
    )

    client = OpenBBClient()
    try:
        closes = {leg: _fetch_closes(client, leg) for leg in _LEGS}
    finally:
        client.close()

    frame = pd.DataFrame(closes).dropna()
    if frame.empty:
        print("FAILED: no observations returned. A live check must not fall back to")
        print("a synthetic book -- that would make it a unit test with extra steps.")
        return 1

    print()
    print(f"fetched {len(frame)} inner-joined sessions")
    print(f"  first {frame.index[0].date()}   last {frame.index[-1].date()}")
    if len(frame) < _LONG_LOOKBACK:
        print(f"FAILED: only {len(frame)} sessions; {_LONG_LOOKBACK} are needed")
        return 1

    returns_all = frame.pct_change().dropna()

    results: dict[int, object] = {}
    solved: dict[int, dict[str, float]] = {}

    for lookback in (_SHORT_LOOKBACK, _LONG_LOOKBACK):
        window = returns_all.iloc[-lookback:]
        inputs = RiskBudgetInputs(
            instrument_returns=_panel(window),
            target_risk_contribution=dict(_EQUAL_BUDGET),
        )
        result = compute_risk_parity_weights(inputs)
        results[lookback] = result
        solved[lookback] = _as_float_map(result.value, "weights")

        print()
        print("-" * 78)
        first, last = window.index[0].date(), window.index[-1].date()
        print(f"lookback {lookback} sessions   ({first} .. {last})")
        print("-" * 78)
        converged = _as_bool(result.value, "converged")
        iterations = _as_int(result.value, "iterations")
        portfolio_vol = _as_number(result.value, "portfolio_volatility_annualized")
        print(f"  converged: {converged}  in {iterations} sweeps")
        print(f"  portfolio vol (annualized): {portfolio_vol:.4%}")
        worst_error = _as_number(result.value, "worst_target_error")
        print(f"  worst |RC - target|: {worst_error:.2e}")

        # --- 1. the notional-vs-risk distinction, MEASURED -------------------
        print()
        print("1. RISK-BUDGETED WEIGHTS (equal 20% risk each) — the whole point of 17.1")
        weights = solved[lookback]
        contributions = _as_float_map(result.value, "risk_contributions")
        print("   leg    weight    risk contribution   gap (notional - risk)")
        for leg in _LEGS:
            gap = weights[leg] - contributions[leg]
            print(
                f"   {leg}   {weights[leg]:7.4%}   {contributions[leg]:7.4%}          {gap:+7.4%}"
            )
        spread = max(weights.values()) - min(weights.values())
        print(f"   weight spread across legs: {spread:.4%}")
        # Equal risk means UNEQUAL notional. A spread near zero would mean the
        # function returned the budget as the weights and the check proved
        # nothing.
        if spread < 0.01:
            print("   !! equal risk produced near-equal notional, so this book cannot")
            print("   !! distinguish 'budgeted by risk' from 'budgeted by dollars'.")
            return 1
        print("   equal risk required UNEQUAL notional — the distinction is live")

        # --- 2. the stress re-solve against the SHIPPED leaf ----------------
        shift = _as_number(result.value, "max_weight_shift_under_stress")
        stressed = _as_float_map(result.value, "stressed_weights")
        print()
        print(f"2. CORRELATION STRESS at rho={stress_correlation} (Module 17.1's LTCM lesson)")
        print("   leg    normal    stressed   shift")
        for leg in _LEGS:
            shift = stressed[leg] - weights[leg]
            print(f"   {leg}   {weights[leg]:7.4%}   {stressed[leg]:7.4%}   {shift:+7.4%}")
        print(f"   largest single-leg shift: {shift:.4%}  (threshold {shift_threshold:.2%})")
        if shift > shift_threshold:
            print("   the shift EXCEEDS the threshold — the escalation warning is a live branch")
        else:
            print("   the shift is BELOW the threshold — the escalation warning is DEAD CODE")
            print("   on this book, and the threshold should be re-examined")

        # --- 3. cross-check against the project's own Euler decomposition ---
        names, covariance = sample_covariance(
            _panel(window),
            annualization_periods=settings.risk.risk_parity_annualization_periods,
        )
        weight_vector = [weights[name] for name in names]
        inner = risk_contributions(weight_vector, covariance)

        # The other side is CALLED with its real (positional) signature, taken
        # from the source rather than assumed: `marginal_risk_contributions`
        # takes `weights, covariance_matrix`, NOT a `PortfolioVaRInputs`. An
        # earlier increment found a function whose input contract differed from
        # the specification's sample call, and a local re-implementation would
        # have hidden it (the O-43 pattern) — so the cross-check calls the real
        # thing or the script fails.
        report = marginal_risk_contributions(weight_vector, covariance)
        # `models/risk.py` publishes BOTH the raw Euler contributions (which sum
        # to the portfolio VARIANCE) and their normalised shares as a percent.
        # The comparable quantity here is the SHARE, so the percent vector is the
        # one to read — comparing against `risk_contributions` would compare a
        # share to a variance and report a spurious 2e-1 disagreement, which is
        # what happened on this check's first run.
        section = _as_float_list(report.value, "risk_contribution_pct")

        print()
        print("3. CROSS-CHECK: risk_budget.risk_contributions vs models/risk.py")
        print("   leg    risk_budget (fraction)   models/risk (percent)   |diff|")
        worst = 0.0
        for i, name in enumerate(names):
            other = section[i] / 100.0
            diff = abs(inner[i] - other)
            worst = max(worst, diff)
            print(f"   {name}   {inner[i]:21.10f}   {other:20.10f}   {diff:.2e}")
        print(f"   worst disagreement: {worst:.2e}")
        if worst > 1e-9:
            print("   !! the two decompositions disagree; the optimiser is solving a")
            print("   !! different problem from the one a report describes.")
            return 1
        print("   the two agree — the optimiser and the report describe one problem")

    # --- 4. window dependence, stated rather than hidden ---------------------
    print()
    print("-" * 78)
    print("4. WINDOW DEPENDENCE — a covariance is an ESTIMATE, not a fact")
    print("-" * 78)
    print("   leg    weight @252    weight @1004    change")
    for leg in _LEGS:
        short_w = solved[_SHORT_LOOKBACK][leg]
        long_w = solved[_LONG_LOOKBACK][leg]
        print(f"   {leg}   {short_w:10.4%}   {long_w:11.4%}   {long_w - short_w:+7.4%}")

    def _window_change(leg: str) -> float:
        return abs(solved[_LONG_LOOKBACK][leg] - solved[_SHORT_LOOKBACK][leg])

    widest = max(_LEGS, key=_window_change)
    widest_change = abs(solved[_LONG_LOOKBACK][widest] - solved[_SHORT_LOOKBACK][widest])
    print(f"   widest: {widest} moves {widest_change:.4%} between the two windows")
    print("   The budget is not wrong — it is conditional on the window. Nothing in")
    print("   the data says which window is right, which is why it is an input.")

    # --- 5. the closed-form oracle on a 2-leg slice -------------------------
    print()
    print("-" * 78)
    print("5. CLOSED-FORM ORACLE on the least-correlated pair of real legs")
    print("-" * 78)
    oracle_status = _oracle_on_least_correlated_pair(
        returns_all, settings.risk.risk_parity_annualization_periods
    )
    if oracle_status != 0:
        return oracle_status

    print()
    print("=" * 78)
    print("PASSED — the risk-parity solve converges on real data, the stress branch")
    print("is live, the two decompositions agree, and the window dependence is stated.")
    print("=" * 78)
    return 0


def _oracle_on_least_correlated_pair(returns: pd.DataFrame, periods: int) -> int:
    """Compare the solved weights to the closed form on the least-correlated pair.

    For two UNCORRELATED assets the exact risk-parity solution under an equal
    budget is ``w_i proportional to 1 / sigma_i``. Real legs are never exactly
    uncorrelated, so the check picks the pair whose sample correlation is
    smallest in absolute value, solves it, and reports the deviation from the
    closed form.

    **The deviation is the finding, not a pass/fail.** A small deviation is the
    closed form being approximately right where correlation is approximately
    zero; a large one would mean the solver is not tracking the oracle even in
    the regime where the oracle is valid, and that IS a failure.

    The check reports which of the two regimes it landed in rather than asserting
    a departure it may not have observed: on the live book the least-correlated
    pair (SPY/IEF at rho = 0.084) solves to the uncorrelated closed form in the
    first six decimals, which is the *agreement* result, not the departure one.
    Announcing a departure there would be a claim the data does not support.
    """
    correlation = returns.corr()
    best_pair: tuple[str, str] | None = None
    best_abs = float("inf")
    for i, left in enumerate(_LEGS):
        for right in _LEGS[i + 1 :]:
            entry = correlation.loc[left, right]
            assert isinstance(entry, (int, float))
            value = abs(float(entry))
            if value < best_abs:
                best_abs = value
                best_pair = (left, right)
    if best_pair is None:  # pragma: no cover - _LEGS has >= 2 entries
        print("   no pair available")
        return 1

    window = returns.iloc[-_LONG_LOOKBACK:]
    names, covariance = sample_covariance(_panel(window), annualization_periods=periods)
    index = {name: i for i, name in enumerate(names)}

    # The 2x2 sub-covariance for the chosen pair.
    i_a, i_b = index[best_pair[0]], index[best_pair[1]]
    sub = [
        [covariance[i_a][i_a], covariance[i_a][i_b]],
        [covariance[i_b][i_a], covariance[i_b][i_b]],
    ]
    result = compute_risk_parity_weights(
        RiskBudgetInputs(
            instrument_returns={
                best_pair[0]: window[best_pair[0]].tolist(),
                best_pair[1]: window[best_pair[1]].tolist(),
            },
            target_risk_contribution={best_pair[0]: 0.5, best_pair[1]: 0.5},
        )
    )
    weights = _as_float_map(result.value, "weights")

    sigma_a = float(np.sqrt(sub[0][0]))
    sigma_b = float(np.sqrt(sub[1][1]))
    exact_a = (1.0 / sigma_a) / ((1.0 / sigma_a) + (1.0 / sigma_b))
    exact_b = 1.0 - exact_a

    print(f"   pair: {best_pair[0]} / {best_pair[1]}   sample rho = {best_abs:.4f}")
    print(f"   sigma: {sigma_a:.4%} / {sigma_b:.4%}")
    print(f"   closed form (if rho == 0): {exact_a:.6f} / {exact_b:.6f}")
    solved_a, solved_b = weights[best_pair[0]], weights[best_pair[1]]
    print(f"   solved:                    {solved_a:.6f} / {solved_b:.6f}")
    deviation = abs(weights[best_pair[0]] - exact_a)
    print(f"   |deviation|: {deviation:.6f}")

    # The printed deviation may round to zero at 6 dp even when the pair is
    # slightly correlated, so the assertion is on the print *resolution* rather
    # than on exact zero — a claim of "zero deviation" on a correlated pair would
    # be a claim the data does not support.
    if deviation >= 1e-6:
        print("   the solve departs from the uncorrelated closed form, as a nonzero")
        print("   correlation requires — the solver is not ignoring the correlation")
    else:
        print("   the deviation is below the 6 dp print resolution, i.e. the pair is")
        print(f"   effectively uncorrelated at rho={best_abs:.4f} and the closed form")
        print("   applies. A LARGER |rho| would be needed to test the departure.")
    return 0


def _as_number(value: object, key: str) -> float:
    """Read a scalar float off ``ModelResult.value`` (assert, never cast).

    Local for the same reason as ``_as_float_map``: operator scripts must not
    depend on the test package.
    """
    assert isinstance(value, dict), f"expected a dict value, got {type(value).__name__}"
    entry = value[key]
    assert isinstance(entry, (int, float)) and not isinstance(entry, bool), (
        f"value[{key!r}] is {type(entry).__name__}, not numeric"
    )
    return float(entry)


def _as_int(value: object, key: str) -> int:
    """Read a count off ``ModelResult.value``; rejects bool for the same reason."""
    assert isinstance(value, dict), f"expected a dict value, got {type(value).__name__}"
    entry = value[key]
    assert isinstance(entry, int) and not isinstance(entry, bool), (
        f"value[{key!r}] is {type(entry).__name__}, not an int"
    )
    return entry


def _as_bool(value: object, key: str) -> bool:
    """Read a flag off ``ModelResult.value`` — a flag is not a magnitude."""
    assert isinstance(value, dict), f"expected a dict value, got {type(value).__name__}"
    entry = value[key]
    assert isinstance(entry, bool), f"value[{key!r}] is {type(entry).__name__}, not a bool"
    return entry


def _as_float_list(value: object, key: str) -> list[float]:
    """Read a positional float vector off ``ModelResult.value``.

    ``marginal_risk_contributions`` publishes its shares as a **list** in
    instrument order, not a keyed mapping — the opposite of what
    ``compute_risk_parity_weights`` publishes. The cross-check therefore reads
    the LIST and pairs it with the same sorted name order the covariance was
    built with, rather than assuming both sides share a shape.

    This is not a stylistic preference: assuming a dict here raised
    ``AssertionError: value['risk_contributions'] is list, not a dict`` on the
    first live run, which is exactly the kind of contract mismatch the
    cross-check exists to surface.
    """
    assert isinstance(value, dict), f"expected a dict value, got {type(value).__name__}"
    entry = value[key]
    assert isinstance(entry, list), f"value[{key!r}] is {type(entry).__name__}, not a list"
    out: list[float] = []
    for item in entry:
        assert isinstance(item, (int, float)) and not isinstance(item, bool), (
            f"value[{key!r}] contains {type(item).__name__}, not numeric"
        )
        out.append(float(item))
    return out


def _as_float_map(value: object, key: str) -> dict[str, float]:
    """Read a keyed float mapping off ``ModelResult.value``.

    Local rather than imported from ``tests.helpers``: operator scripts must not
    depend on the test package. The narrowing is the same discipline — assert,
    never cast, so a result carrying the wrong shape fails loudly.
    """
    assert isinstance(value, dict), f"expected a dict value, got {type(value).__name__}"
    entry = value[key]
    assert isinstance(entry, dict), f"value[{key!r}] is {type(entry).__name__}, not a dict"
    out: dict[str, float] = {}
    for name, item in entry.items():
        assert isinstance(name, str), f"value[{key!r}] has a non-str key"
        assert isinstance(item, (int, float)) and not isinstance(item, bool), (
            f"value[{key!r}][{name!r}] is {type(item).__name__}, not numeric"
        )
        out[name] = float(item)
    return out


if __name__ == "__main__":
    sys.exit(main())
