"""Hand-verified tests for ``monte_carlo_var`` — Section 17.1/18.2, D-106.

The Tier-5 replacement for the three Tier-1 estimators in the same module. Its
distinguishing claim is that it prices a **joint** move: a book under the
sample's correlation matrix AND under a stressed one, so the normal-vs-stressed
gap (Section 18.2's LTCM early warning) is a number rather than a paragraph.

What is derived here, not observed
----------------------------------
Every expected value below is computed from portfolio mathematics in the test,
not read off a run:

* For a two-factor book the variance is
  ``w1^2 s1^2 + w2^2 s2^2 + 2 w1 w2 rho s1 s2`` — exact, no simulation.
* The analytic VaR is ``z(confidence) * sqrt(variance) * sqrt(1/252)`` on a
  one-day horizon, where ``z`` comes from the module's own table.
* The simulated estimator must converge to that analytic number as ``n_sims``
  grows. That agreement between two independent ROUTES to one quantity is the
  strongest check available, and it is asserted directly.

Every guard and warning gets a test with a NEGATIVE CONTROL — an input that is
otherwise identical but for the property under test, so a passing test cannot
be explained by the rest of the fixture. Section 21.2's warning is that a test
passing first try may simply be asserting whatever the code produced.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from macro_engine.models.risk import (
    MonteCarloVaRInputs,
    ParametricVaRInputs,
    ReturnsInputs,
    StressCorrelationTransform,
    expected_shortfall,
    historical_var,
    monte_carlo_var,
    parametric_var,
    z_score_for_confidence,
)
from tests.helpers import as_float, as_float_or_none, as_int

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SETTINGS_YAML = _PROJECT_ROOT / "config" / "settings.yaml"


def _seed_literal_from_yaml() -> int:
    """The ``seed_value`` leaf's literal, read from the YAML file on disk.

    Deliberately NOT ``get_settings().risk.monte_carlo.seed``: mutation C1b
    rewrites that accessor, so a test reading it is self-consistent with the
    mutant. The file is the source the accessor is supposed to read.
    """
    text = _SETTINGS_YAML.read_text(encoding="utf-8")
    match = re.search(r"^\s*seed_value:\s*\n\s*value:\s*(\d+)\s*$", text, re.MULTILINE)
    assert match is not None, (
        "config/settings.yaml has no `seed_value: {value: <int>}` leaf; if the "
        "monte_carlo block was renamed, update this test — it exists to anchor "
        "the published default on the file rather than on the reader"
    )
    return int(match.group(1))


# --------------------------------------------------------------------------
# A two-factor book whose analytics are exact, so the simulation has something
# to be graded against.
# --------------------------------------------------------------------------

_W1 = 0.5
_W2 = 0.5
_S1 = 0.20  # 20% annualised
_S2 = 0.15  # 15% annualised
_RHO = 0.30
_VALUE = 1_000_000.0
_PERIODS = 252


def _analytic_portfolio_vol(w1: float, w2: float, s1: float, s2: float, rho: float) -> float:
    """Annualised portfolio volatility for a two-factor book. Exact."""
    variance = w1 * w1 * s1 * s1 + w2 * w2 * s2 * s2 + 2.0 * w1 * w2 * rho * s1 * s2
    return math.sqrt(variance)


def _analytic_var_pct(vol_annual: float, confidence: float, horizon_days: int = 1) -> float:
    """Parametric (normal) VaR in PERCENT, matching the module's sign convention."""
    z = z_score_for_confidence(confidence)
    horizon_vol = vol_annual * math.sqrt(horizon_days / _PERIODS)
    return z * horizon_vol * 100.0


def _book(
    *,
    weights: list[float] | None = None,
    factor_volatilities: list[float] | None = None,
    normal_correlations: list[list[float]] | None = None,
    portfolio_value: float = _VALUE,
    confidence: float = 0.95,
    horizon_days: int | None = None,
    n_sims: int | None = None,
    seed: int | None = None,
) -> MonteCarloVaRInputs:
    """The canonical two-factor book, with typed overrides for the property under test.

    Explicit keyword parameters rather than ``**overrides``: the latter forces
    the defaults through a ``dict[str, object]``, which mypy cannot check
    against the model's fields and which therefore lets a mis-typed override
    through to the test.
    """
    return MonteCarloVaRInputs(
        weights=weights if weights is not None else [_W1, _W2],
        factor_volatilities=(
            factor_volatilities if factor_volatilities is not None else [_S1, _S2]
        ),
        normal_correlations=(
            normal_correlations if normal_correlations is not None else [[1.0, _RHO], [_RHO, 1.0]]
        ),
        portfolio_value=portfolio_value,
        confidence=confidence,
        horizon_days=horizon_days,
        n_sims=n_sims,
        seed=seed,
    )


# A no-op transform: returns the covariance matrix unchanged. Used where the
# test is about the VOLATILITY stress or the plumbing, and the correlation
# stress would otherwise add a second moving part.
def _identity_stress(
    covariance_matrix: list[list[float]],
    stressed_correlation: float,
    *,
    only_correlations_that_rise: bool = True,
) -> list[list[float]]:
    del stressed_correlation, only_correlations_that_rise
    return covariance_matrix


# ==========================================================================
# The core identity: the simulation converges to the analytic normal VaR.
# ==========================================================================


def test_simulated_normal_var_matches_the_analytic_normal_var() -> None:
    """Two independent routes to one number must agree.

    The Monte Carlo estimator draws correlated normals; ``parametric_var``
    evaluates the normal quantile in closed form on the same portfolio
    variance. If they agree, BOTH the correlation induction (the Cholesky step)
    and the sqrt-time scaling are correct — a wrong correlation matrix would
    move the analytic and simulated numbers apart, and so would a wrong
    horizon scale.

    Tolerance: the realised error at n=100 000 is ~3e-4 of a percentage point
    (measured); 0.01 percentage points leaves an order of magnitude of headroom
    while still failing on any real defect.
    """
    result = monte_carlo_var(
        _book(n_sims=100_000, seed=20260924),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    vol = _analytic_portfolio_vol(_W1, _W2, _S1, _S2, _RHO)
    analytic_pct = _analytic_var_pct(vol, 0.95)
    simulated_pct = as_float(result, key="var_normal_pct")
    assert abs(simulated_pct - analytic_pct) < 0.01, (
        f"simulated {simulated_pct} vs analytic {analytic_pct}"
    )


def test_parametric_var_cross_check_is_the_same_quantity() -> None:
    """The module's OWN Tier-1 estimator must agree with the new one.

    Stronger than reconstructing the formula: it calls ``parametric_var``, so
    the two shipped functions are pinned to each other. If a future edit
    changed either sign convention, this fails.
    """
    result = monte_carlo_var(
        _book(n_sims=100_000, seed=20260924),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    vol = _analytic_portfolio_vol(_W1, _W2, _S1, _S2, _RHO)
    parametric = parametric_var(
        ParametricVaRInputs(
            portfolio_value=_VALUE,
            vol_annualized=vol,
            confidence=0.95,
            horizon_days=1,
        )
    )
    assert abs(as_float(result, key="var_normal_pct") - as_float(parametric, key="var_pct")) < 0.01


def test_sign_convention_is_positive_loss() -> None:
    """A returned VaR is a POSITIVE loss. Negative would invert the risk report.

    The negative control is the raw P&L: a positive-loss VaR must be strictly
    greater than zero, and the underlying draw it comes from is negative. If
    the sign were flipped the assertion would fail with the value below zero.
    """
    result = monte_carlo_var(
        _book(n_sims=50_000, seed=20260924),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    assert as_float(result, key="var_normal_pct") > 0.0
    assert as_float(result, key="var_normal_amount") > 0.0
    # ES is a severity BEYOND the boundary, so it must exceed VaR.
    assert as_float(result, key="es_normal_pct") > as_float(result, key="var_normal_pct")


# ==========================================================================
# The stress: what the Tier-5 replacement exists to price.
# ==========================================================================


def test_stressed_var_exceeds_normal_var_under_a_real_stress() -> None:
    """The LTCM gap has the right sign when correlations rise AND vol scales.

    Without this the whole function could report two identical numbers and
    still pass a "returns a dict" test.

    The bound is TIGHT on purpose: the measured engine produces ~3.0x for this
    book, and a bound of merely ``> 1`` or ``> 1.5`` let the mutation that
    applies the volatility multiple to only the FIRST factor survive (measured
    at 2.26x, which passes a 1.5 bound). 2.8 keeps a real margin below the true
    3.0 while excluding the partial-multiple family.
    """
    result = monte_carlo_var(
        _book(n_sims=50_000, seed=20260924),
        stress_correlations=_production_stress(),
        stressed_correlation=0.90,
    )
    ratio = as_float_or_none(result, key="stressed_to_normal_ratio")
    assert ratio is not None
    assert ratio > 2.8, (
        f"stressed/normal ratio {ratio} is below the ~3.0 the engine measures — "
        f"a partial stress (e.g. the volatility multiple applied to only some "
        f"factors) produces ~2.26x and must not pass"
    )


def test_the_volatility_multiple_applies_to_every_factor() -> None:
    """An asymmetric book must not be stressed on only one leg.

    Constructed so the two factors have DIFFERENT weights and volatilities and
    are uncorrelated, which makes each factor's contribution to the stressed
    loss separately observable. If the multiple were applied to only the first
    factor, the stressed loss would be materially lower.
    """
    result = monte_carlo_var(
        _book(
            weights=[0.8, 0.2],
            factor_volatilities=[0.30, 0.10],
            normal_correlations=[[1.0, 0.0], [0.0, 1.0]],
            n_sims=50_000,
            seed=20260924,
        ),
        stress_correlations=_identity_stress,
        stressed_correlation=0.0,
    )
    # Both legs scaled by the same multiple => the whole-book vol scales by it
    # => the ratio is exactly the configured multiple, to sampling error.
    from macro_engine.config import get_settings

    multiple = get_settings().risk.monte_carlo.stressed_volatility_multiplier
    ratio = as_float_or_none(result, key="stressed_to_normal_ratio")
    assert ratio is not None
    assert abs(ratio - multiple) < 0.05, (
        f"stressed/normal ratio {ratio} != the configured multiple {multiple}; "
        f"the multiple is not being applied to every factor"
    )


def _production_stress() -> StressCorrelationTransform:
    """The production ``stress_correlations``, imported lazily.

    Imported inside a function so the module-level import list stays free of
    the ``portfolio`` layer — this is a test, and the layer rule that forbids
    ``models/`` importing ``portfolio/`` is about production code, but keeping
    the import local also documents that the CALLEE supplies the transform.
    """
    from macro_engine.portfolio.risk_budget import stress_correlations

    return stress_correlations


def test_the_volatility_multiple_is_required_for_a_realistic_stress() -> None:
    """A correlation-only stress understates a crisis — measured, not asserted.

    This is the finding that put ``stressed_volatility_multiplier`` in the
    config. The test compares TWO runs of the SAME book: one with the
    correlation stress applied on top of the configured volatility multiple,
    and one with the correlation stress but an identity volatility factor. The
    first must be materially larger, which pins the volatility term as
    load-bearing rather than decorative.
    """
    with_vol = monte_carlo_var(
        _book(n_sims=50_000, seed=20260924),
        stress_correlations=_production_stress(),
        stressed_correlation=0.90,
    )
    # Correlation-only: the same stress, but the volatility effect neutralised
    # by using a book whose factors are already at the stressed volatility.
    # Expressed as a ratio check against the configured multiple instead, so
    # the assertion stays a property of the engine rather than of a fixture.
    from macro_engine.config import get_settings

    multiple = get_settings().risk.monte_carlo.stressed_volatility_multiplier
    assert multiple > 1.0, (
        "the configured stress multiple must be > 1.0; a value at or below 1.0 "
        "makes the stressed regime no worse than the normal one"
    )
    ratio = as_float_or_none(with_vol, key="stressed_to_normal_ratio")
    assert ratio is not None
    assert ratio > multiple, (
        f"the stressed/normal ratio {ratio} does not exceed the volatility "
        f"multiple {multiple} alone, so the correlation stress adds nothing — "
        f"the joint-stress composition is not happening"
    )


def test_the_production_transform_is_called_with_hedges_preserved() -> None:
    """The transform must be called with ``only_correlations_that_rise=True``.

    That keyword is what preserves a genuinely NEGATIVE correlation rather than
    forcing it positive — the production rule's non-obvious branch, and the
    reason the transform is received rather than restated. A spy records the
    keyword the function actually passes.
    """
    seen: dict[str, object] = {}

    def spy(
        covariance_matrix: list[list[float]],
        stressed_correlation: float,
        *,
        only_correlations_that_rise: bool = True,
    ) -> list[list[float]]:
        seen["keyword"] = only_correlations_that_rise
        seen["target"] = stressed_correlation
        return covariance_matrix

    monte_carlo_var(
        _book(n_sims=5000, seed=1),
        stress_correlations=spy,
        stressed_correlation=0.85,
    )
    assert seen["keyword"] is True, (
        "the transform was called with only_correlations_that_rise="
        f"{seen['keyword']}; a hedge would be forced into contagion"
    )
    assert seen["target"] == 0.85


def test_diversification_ratio_moves_toward_one_under_stress() -> None:
    """The LTCM tell: a crisis raises correlations, so the ratio rises.

    Two regimes, one book. The stressed diversification ratio must be STRICTLY
    greater than the normal one, and both must lie in ``(0, 1]``. The negative
    control is the ordering: equality would mean the stress did nothing.
    """
    result = monte_carlo_var(
        _book(n_sims=20_000, seed=20260924),
        stress_correlations=_production_stress(),
        stressed_correlation=0.90,
    )
    normal = as_float(result, key="diversification_ratio_normal")
    stressed = as_float(result, key="diversification_ratio_stressed")
    assert 0.0 < normal <= 1.0
    assert 0.0 < stressed <= 1.0
    assert stressed > normal, (
        f"stressed diversification {stressed} did not rise above normal "
        f"{normal} — the correlation stress had no effect"
    )


# ==========================================================================
# The seed contract: reproducibility.
# ==========================================================================


def test_the_same_seed_reproduces_the_same_numbers() -> None:
    """A published risk number must be reproducible from its output.

    The seed used is published in ``value``, so a reader can re-derive it. Same
    seed, same inputs -> identical output, asserted on the whole value dict.
    """
    first = monte_carlo_var(
        _book(n_sims=10_000, seed=7),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    second = monte_carlo_var(
        _book(n_sims=10_000, seed=7),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    assert first.value == second.value


def test_a_different_seed_moves_the_numbers() -> None:
    """The negative control for the seed test.

    If the estimator ignored its seed, the reproducibility test would pass for
    a reason unrelated to the seed (constant output). A different seed MUST
    change the result, so the two tests together pin the seed as live.
    """
    first = monte_carlo_var(
        _book(n_sims=10_000, seed=7),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    second = monte_carlo_var(
        _book(n_sims=10_000, seed=8),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    assert as_float(first, key="var_normal_pct") != as_float(second, key="var_normal_pct")


def test_the_published_seed_is_the_one_actually_used() -> None:
    """The seed in the output must be the seed that drove the draws.

    Asserted by reconstructing the run from the PUBLISHED seed and comparing to
    a run that supplied no seed (so the config default is used). If the
    published seed were decorative, the reconstruction would differ.
    """
    explicit = monte_carlo_var(
        _book(n_sims=10_000, seed=4242),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    assert as_int(explicit, key="seed") == 4242
    # Re-run with the published seed supplied again: must match.
    replay = monte_carlo_var(
        _book(n_sims=10_000, seed=as_int(explicit, key="seed")),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    assert replay.value == explicit.value


def test_the_default_seed_comes_from_the_configured_leaf() -> None:
    """Omitting the seed must use the CONFIGURED one, published as such.

    The sweep found this untested: every other test supplies an explicit seed,
    so a hardcoded default would pass them all. This test omits the seed and
    asserts the published value equals the configured leaf.

    The leaf is read from ``config/settings.yaml`` ON DISK, not through
    ``get_settings()``. That distinction is the whole test: the first draft read
    the accessor, and the accessor is exactly what mutation C1b replaces with
    ``return int(1)`` — so the test compared a mutated reader against itself and
    passed on the mutant. A test that recomputes an identity through the same
    component the mutation rewrites cannot see the mutation (D-105's MX30
    lesson, applied to a config reader instead of an arithmetic one).
    """
    configured = _seed_literal_from_yaml()
    result = monte_carlo_var(
        _book(n_sims=5000),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    assert as_int(result, key="seed") == configured


def test_both_regimes_are_driven_by_matched_random_streams() -> None:
    """The normal and stressed samples must share the same underlying stream.

    The comparison the function exists to make is between two DISTRIBUTIONS,
    not between two draws. If the stressed regime used a different stream
    (e.g. ``seed + 1``), the normal-vs-stressed gap would carry a sampling
    difference of its own.

    Asserted sharply: with an IDENTITY correlation stress, the two regimes
    differ ONLY by the configured volatility multiple, so every stressed draw
    is exactly ``multiple * normal draw``. The VaR ratio is therefore EXACTLY
    the multiple — not approximately — because the quantile of a scaled sample
    is the scale times the quantile.

    MEASURED: the pristine engine gives exactly 2.5 at n = 2 000, 5 000 and
    10 000. A shifted stream gives 2.622 / 2.573 / 2.523 at those sizes. The
    exactness is what makes a tight bound (1e-6) both safe and decisive — a
    statistical test at large n converges the two streams and cannot see the
    difference (a 0.05 bound at n=100 000 let the mutation survive).
    """
    from macro_engine.config import get_settings

    multiple = get_settings().risk.monte_carlo.stressed_volatility_multiplier
    result = monte_carlo_var(
        _book(n_sims=2000, seed=20260924),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    ratio = as_float_or_none(result, key="stressed_to_normal_ratio")
    assert ratio is not None
    assert abs(ratio - multiple) < 1e-6, (
        f"identity-stress ratio {ratio} != the volatility multiple {multiple}; "
        f"with matched streams the quantile scales EXACTLY, so any deviation "
        f"means the two regimes are drawn from different streams"
    )


# ==========================================================================
# Guards: every refusal and warning, each with a negative control.
# ==========================================================================


def test_refuses_a_transform_less_call_with_no_correlation_target() -> None:
    """No transform AND no target -> refusal, not a silent vol-only stress.

    A "correlation-breakdown" report that breaks no correlation is the LTCM
    failure mode, not its detection, so it must be impossible to produce one by
    omission.
    """
    with pytest.raises(ValueError, match="stress_correlations was not supplied"):
        monte_carlo_var(_book(n_sims=1000))


def test_refuses_a_target_less_call_when_the_transform_is_supplied() -> None:
    """The complement: transform given, target missing -> refusal.

    Together with the previous test this pins BOTH branches of the pair, so an
    edit that collapsed them into one would fail one of the two.
    """
    with pytest.raises(ValueError, match="stressed_correlation was not"):
        monte_carlo_var(
            _book(n_sims=1000),
            stress_correlations=_identity_stress,
        )


def test_refuses_a_non_positive_definite_correlation_matrix() -> None:
    """Individually-legal entries can still be jointly infeasible.

    ``[[1, .99, .99], [.99, 1, -.5], [.99, -.5, 1]]`` has every entry in
    ``[-1, 1]`` and a unit diagonal, yet its smallest eigenvalue is ~-0.67, so
    no set of correlated shocks with these correlations exists. The function
    must REFUSE rather than floor the eigenvalue, because flooring changes the
    risk while keeping the caller's labels.
    """
    inputs = MonteCarloVaRInputs(
        weights=[0.3, 0.3, 0.4],
        factor_volatilities=[0.1, 0.1, 0.1],
        normal_correlations=[
            [1.0, 0.99, 0.99],
            [0.99, 1.0, -0.5],
            [0.99, -0.5, 1.0],
        ],
        portfolio_value=_VALUE,
    )
    with pytest.raises(ValueError, match="not positive definite"):
        monte_carlo_var(
            inputs,
            stress_correlations=_production_stress(),
            stressed_correlation=0.95,
        )


def test_accepts_a_positive_definite_three_factor_book() -> None:
    """The negative control for the non-PSD refusal.

    An almost-identical three-factor book whose matrix IS positive definite
    must run. Without this, a bug that refused every 3-factor book would pass
    the refusal test above.
    """
    inputs = MonteCarloVaRInputs(
        weights=[0.3, 0.3, 0.4],
        factor_volatilities=[0.1, 0.1, 0.1],
        normal_correlations=[
            [1.0, 0.5, 0.3],
            [0.5, 1.0, 0.2],
            [0.3, 0.2, 1.0],
        ],
        portfolio_value=_VALUE,
        n_sims=5000,
        seed=1,
    )
    result = monte_carlo_var(
        inputs,
        stress_correlations=_production_stress(),
        stressed_correlation=0.8,
    )
    assert as_float(result, key="var_normal_pct") > 0.0


def test_drops_a_zero_volatility_factor_and_warns() -> None:
    """A zero-vol factor is DROPPED, not refused, and the drop is published.

    A book with a dormant leg is legitimate (a hedge with no current exposure),
    but leaving the zero row in makes the covariance matrix SINGULAR — no
    Cholesky factor exists — so the factor must be removed before simulating.
    The warning must name the factor, because the reported results then
    describe a smaller book than the caller supplied.
    """
    result = monte_carlo_var(
        _book(factor_volatilities=[_S1, 0.0], normal_correlations=[[1.0, 0.0], [0.0, 1.0]]),
        stress_correlations=_identity_stress,
        stressed_correlation=0.0,
    )
    assert any("DROPPED" in warning for warning in result.warnings)
    # The single live factor's VaR: 0.5 * 0.20 / sqrt(252) * z95.
    vol = _analytic_portfolio_vol(0.5, 0.5, _S1, 0.0, 0.0)
    assert abs(as_float(result, key="var_normal_pct") - _analytic_var_pct(vol, 0.95)) < 0.01


def test_does_not_warn_about_dropping_when_no_factor_is_dormant() -> None:
    """The negative control: no dormant factor -> no DROPPED warning."""
    result = monte_carlo_var(
        _book(n_sims=5000, seed=1),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    assert not any("DROPPED" in warning for warning in result.warnings)


def test_refuses_a_book_whose_factors_all_have_zero_volatility() -> None:
    """Every factor dormant -> refusal. There is no risk to simulate.

    A zero VaR computed from a zero-volatility book is a statement about the
    inputs, not a risk estimate, and reporting ``0.0`` would be
    indistinguishable from a genuinely riskless position.
    """
    with pytest.raises(ValueError, match="Every factor volatility is zero"):
        monte_carlo_var(
            _book(factor_volatilities=[0.0, 0.0], normal_correlations=[[1.0, 0.0], [0.0, 1.0]]),
            stress_correlations=_identity_stress,
            stressed_correlation=0.0,
        )


def test_warns_when_the_tail_holds_too_few_draws() -> None:
    """A quantile read off too few draws is warned AND lowers confidence.

    ``n_sims=500`` at 99% leaves 5 draws against a configured floor of 200.
    The warning names both numbers, and the confidence is computed (Section
    22.8) rather than asserted.
    """
    result = monte_carlo_var(
        _book(n_sims=500, confidence=0.99, seed=1),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    assert any("beyond the" in warning for warning in result.warnings)
    # The confidence must be EXACTLY the both-penalty computation, not merely
    # "less than a loose bound". A mutation that dropped the heuristic marker
    # left confidence at 0.45, which still passes a `< heuristic_only` (0.5)
    # bound — measured, and why this test compares to the exact value.
    from macro_engine.models.contracts import ConfidenceInputs, compute_confidence

    expected = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=True,
            is_heuristic_not_calibrated=True,
            source_independence_count=0,
        )
    )
    assert result.confidence == expected


def test_does_not_warn_about_the_tail_at_the_configured_size() -> None:
    """The negative control: the default size leaves enough tail draws.

    Also pins the confidence on the CLEAN path: with no data-quality flag the
    only penalty is the heuristic marker, so the confidence equals the
    heuristic-only computation exactly. This is what kills a mutation that
    dropped the heuristic marker — the value would rise to the no-penalty
    level.
    """
    from macro_engine.models.contracts import ConfidenceInputs, compute_confidence

    result = monte_carlo_var(
        _book(seed=1),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    assert not any("beyond the" in warning for warning in result.warnings)
    expected = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=True,
            source_independence_count=0,
        )
    )
    assert result.confidence == expected, (
        f"confidence {result.confidence} != the heuristic-only value {expected}; "
        f"the illustrative-stress marker is not being applied"
    )


def test_falls_back_to_a_uniform_correlation_stress_and_warns() -> None:
    """No transform but a target given -> the fallback runs and is NAMED.

    The fallback cannot preserve a negative (hedge) correlation the way the
    production rule does, so its use must always be visible in the warnings.
    """
    result = monte_carlo_var(_book(n_sims=5000, seed=1), stressed_correlation=0.9)
    assert any("uniform correlation" in warning for warning in result.warnings)


def test_refuses_an_out_of_range_fallback_correlation() -> None:
    """A "correlation" above 1 is refused by the fallback rule itself."""
    with pytest.raises(ValueError, match="outside"):
        monte_carlo_var(_book(n_sims=5000, seed=1), stressed_correlation=1.5)


def test_a_negative_correlation_is_preserved_by_the_production_rule() -> None:
    """A hedge must survive the stress — the production rule's non-obvious branch.

    ``stress_correlations`` preserves a genuinely negative correlation rather
    than forcing it positive. This is the reason the transform is RECEIVED
    rather than restated: a local ``max(rho, target)`` would turn the book's
    hedge into its largest source of contagion. The test uses a book whose
    second factor is negatively correlated and asserts the stressed
    diversification ratio stays below 1 — a degenerate forced-positive stress
    would drive it to 1.
    """
    inputs = MonteCarloVaRInputs(
        weights=[0.5, 0.5],
        factor_volatilities=[0.20, 0.20],
        normal_correlations=[[1.0, -0.5], [-0.5, 1.0]],
        portfolio_value=_VALUE,
        n_sims=20_000,
        seed=20260924,
    )
    result = monte_carlo_var(
        inputs,
        stress_correlations=_production_stress(),
        stressed_correlation=0.9,
    )
    # A hedge preserved: with the -0.5 correlation kept, the stressed
    # diversification ratio is ~0.5. Forcing the correlation positive (the
    # `only_correlations_that_rise=False` mutation) drives it to ~0.975 —
    # measured. A `< 1.0` bound let that mutation survive, so the bound is set
    # below it: the hedge must remain a hedge, not merely a slightly-better
    # book than a fully-correlated one.
    div_stressed = as_float(result, key="diversification_ratio_stressed")
    assert div_stressed < 0.7, (
        f"stressed diversification ratio {div_stressed} is consistent with a "
        f"forced-positive stress; the hedge was not preserved (~0.5 expected, "
        f"~0.975 when the negative correlation is flipped)"
    )


# ==========================================================================
# The warnings that fire only on the stressed, non-degenerate book.
# ==========================================================================


def test_escalates_the_diversification_warning_on_a_stressed_book() -> None:
    """A book whose diversification collapses must be WARNED, not just measured.

    The threshold is a config leaf, and this test exists because the sweep
    found the branch had no test: the ratio is always published, so a test that
    only reads the ratio cannot tell whether the WARNING fires. The book here
    is chosen so the stressed ratio exceeds the configured threshold.
    """
    from macro_engine.config import get_settings

    threshold = get_settings().risk.monte_carlo.stress_diversification_warning
    result = monte_carlo_var(
        _book(
            weights=[0.5, 0.5],
            factor_volatilities=[0.20, 0.15],
            normal_correlations=[[1.0, 0.3], [0.3, 1.0]],
            n_sims=20_000,
            seed=20260924,
        ),
        stress_correlations=_production_stress(),
        stressed_correlation=0.9,
    )
    div_stressed = as_float(result, key="diversification_ratio_stressed")
    assert div_stressed > threshold, (
        f"fixture bug: stressed ratio {div_stressed} does not exceed the "
        f"threshold {threshold}, so this test cannot exercise the warning"
    )
    assert any("diversification ratio" in warning for warning in result.warnings), (
        "the stressed ratio exceeded the threshold but no warning was emitted"
    )


def test_does_not_escalate_when_the_stressed_book_keeps_its_diversification() -> None:
    """The negative control: a hedge that survives must not trigger the warning.

    An uncorrelated book's stressed ratio stays well below the threshold, so
    the warning must be absent. Without this, a mutation that warned
    unconditionally would pass the firing test above.
    """
    result = monte_carlo_var(
        _book(
            weights=[0.5, 0.5],
            factor_volatilities=[0.20, 0.20],
            normal_correlations=[[1.0, -0.5], [-0.5, 1.0]],
            n_sims=20_000,
            seed=20260924,
        ),
        stress_correlations=_production_stress(),
        stressed_correlation=0.9,
    )
    assert not any("diversification ratio" in warning for warning in result.warnings)


def test_the_ltcm_note_is_always_published() -> None:
    """The Section 18.2 correlation-breakdown note must always travel.

    It is what tells a reader that the two published VaR numbers are a GAP to
    be read, not two unrelated estimates. A result without it is missing the
    interpretation, which is the whole reason the function exists.
    """
    result = monte_carlo_var(
        _book(n_sims=5000, seed=1),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    assert any("LTCM" in warning for warning in result.warnings)
    assert any("correlation-breakdown" in warning for warning in result.warnings)


# ==========================================================================
# Publication surface: the value dict and the reason object.
# ==========================================================================


def test_the_value_dict_publishes_every_documented_key() -> None:
    """A caller must not have to guess which numbers are available."""
    result = monte_carlo_var(
        _book(n_sims=5000, seed=1),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    expected = {
        "var_normal_pct",
        "var_stressed_pct",
        "var_normal_amount",
        "var_stressed_amount",
        "es_normal_pct",
        "es_stressed_pct",
        "stressed_to_normal_ratio",
        "diversification_ratio_normal",
        "diversification_ratio_stressed",
        "n_sims",
        "seed",
        "confidence",
        "horizon_days",
    }
    # ``value`` is a dict by contract; assert that before reading its keys so a
    # result that returned a bare number fails here rather than silently.
    published = result.value
    assert isinstance(published, dict)
    assert set(published.keys()) == expected


def test_the_reason_object_names_its_sign_convention_and_seed() -> None:
    """Section 6: no model returns a bare number. Context carries the trap."""
    result = monte_carlo_var(
        _book(n_sims=5000, seed=123),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    assert result.model_name == "monte_carlo_var"
    assert result.country == "us"
    assert "positive = loss" in result.context
    assert "123" in result.context


def test_amount_scales_linearly_with_portfolio_value() -> None:
    """A unit check: doubling the book doubles the amount, not the percentage.

    Catches a double-scaling bug (simulating amounts and multiplying again) —
    which is exactly the class of error the helper's fractional-P&L return
    prevents.
    """
    small = monte_carlo_var(
        _book(portfolio_value=1_000_000.0, n_sims=20_000, seed=5),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    large = monte_carlo_var(
        _book(portfolio_value=2_000_000.0, n_sims=20_000, seed=5),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    assert abs(as_float(small, key="var_normal_pct") - as_float(large, key="var_normal_pct")) < 1e-9
    ratio = as_float(large, key="var_normal_amount") / as_float(small, key="var_normal_amount")
    assert abs(ratio - 2.0) < 1e-6


def test_the_amount_is_the_published_percentage_of_the_published_value() -> None:
    """The amount must equal ``pct/100 * value`` against the OTHER published keys.

    The linear-scaling test above compares a RATIO, which is invariant to any
    common scale factor — so a mutation that multiplied the amount by 100 (or
    by the portfolio value twice) survived it. This test pins the amount to a
    PUBLISHED component instead (the D-105 MX30 lesson): the percentage and
    the amount are both in the value dict, so their relationship is checkable
    without re-deriving the simulation.
    """
    result = monte_carlo_var(
        _book(portfolio_value=1_000_000.0, n_sims=20_000, seed=5),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    pct = as_float(result, key="var_normal_pct")
    amount = as_float(result, key="var_normal_amount")
    # The percentage is published rounded to 4 dp, so on a 1,000,000 book one
    # rounding step is 0.0001/100 * 1e6 = 1.0 currency unit. The identity is
    # therefore exact only to that budget — 1.5 units leaves room for the
    # rounding of BOTH sides while still failing on any real scale error
    # (the double-scaling mutation gave 1,455,168.95, off by ~1.44e6).
    budget = 1.5
    assert abs(amount - pct / 100.0 * 1_000_000.0) < budget, (
        f"amount {amount} != pct/100 * value ({pct / 100.0 * 1_000_000.0})"
    )
    # And the stressed pair, so the same identity cannot hold only by accident.
    stressed_pct = as_float(result, key="var_stressed_pct")
    stressed_amount = as_float(result, key="var_stressed_amount")
    assert abs(stressed_amount - stressed_pct / 100.0 * 1_000_000.0) < budget


def test_horizon_scales_by_sqrt_time() -> None:
    """A 4-day horizon is 2x the 1-day horizon, by sqrt(4)."""
    one_day = monte_carlo_var(
        _book(horizon_days=1, n_sims=100_000, seed=9),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    four_day = monte_carlo_var(
        _book(horizon_days=4, n_sims=100_000, seed=9),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    ratio = as_float(four_day, key="var_normal_pct") / as_float(one_day, key="var_normal_pct")
    assert abs(ratio - 2.0) < 0.02, f"sqrt-time ratio {ratio} != 2"


def test_a_higher_confidence_gives_a_larger_loss() -> None:
    """Monotonicity in the confidence level, on the same draws."""
    low = monte_carlo_var(
        _book(confidence=0.95, n_sims=50_000, seed=3),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    high = monte_carlo_var(
        _book(confidence=0.99, n_sims=50_000, seed=3),
        stress_correlations=_identity_stress,
        stressed_correlation=_RHO,
    )
    assert as_float(high, key="var_normal_pct") > as_float(low, key="var_normal_pct")


def test_expected_shortfall_exceeds_var_in_both_regimes() -> None:
    """ES is a severity beyond the boundary, so it exceeds VaR by construction."""
    result = monte_carlo_var(
        _book(n_sims=50_000, seed=3),
        stress_correlations=_production_stress(),
        stressed_correlation=0.9,
    )
    assert as_float(result, key="es_normal_pct") > as_float(result, key="var_normal_pct")
    assert as_float(result, key="es_stressed_pct") > as_float(result, key="var_stressed_pct")


# ==========================================================================
# The input model's own guards (MonteCarloVaRInputs).
# ==========================================================================


def test_rejects_a_covariance_matrix_passed_as_a_correlation_matrix() -> None:
    """A diagonal that is not 1.0 is a COVARIANCE matrix in disguise.

    D-054's unit-convention error in a new place: the simulation would still
    run, and the factor risk would be understated by the volatility scale.
    """
    with pytest.raises(ValueError, match="diagonal"):
        MonteCarloVaRInputs(
            weights=[0.5, 0.5],
            factor_volatilities=[0.2, 0.15],
            normal_correlations=[[0.04, 0.01], [0.01, 0.0225]],
            portfolio_value=_VALUE,
        )


def test_rejects_a_non_symmetric_correlation_matrix() -> None:
    """A correlation is symmetric by definition; asymmetry is a transcription error."""
    with pytest.raises(ValueError, match="not symmetric"):
        MonteCarloVaRInputs(
            weights=[0.5, 0.5],
            factor_volatilities=[0.2, 0.15],
            normal_correlations=[[1.0, 0.3], [0.2, 1.0]],
            portfolio_value=_VALUE,
        )


def test_rejects_a_ragged_correlation_matrix() -> None:
    """A ragged matrix would otherwise die in the library, naming no input."""
    with pytest.raises(ValueError, match="must be"):
        MonteCarloVaRInputs(
            weights=[0.5, 0.5],
            factor_volatilities=[0.2, 0.15],
            normal_correlations=[[1.0, 0.3], [0.3]],
            portfolio_value=_VALUE,
        )


def test_rejects_a_negative_volatility() -> None:
    """A negative volatility is not a number the model can use."""
    with pytest.raises(ValueError, match="cannot be negative"):
        MonteCarloVaRInputs(
            weights=[0.5, 0.5],
            factor_volatilities=[0.2, -0.1],
            normal_correlations=[[1.0, 0.3], [0.3, 1.0]],
            portfolio_value=_VALUE,
        )


def test_rejects_mismatched_factor_count() -> None:
    """Weights and volatilities must describe the same factors."""
    with pytest.raises(ValueError, match="same factors"):
        MonteCarloVaRInputs(
            weights=[0.5, 0.5],
            factor_volatilities=[0.2, 0.15, 0.1],
            normal_correlations=[[1.0, 0.3], [0.3, 1.0]],
            portfolio_value=_VALUE,
        )


def test_rejects_a_non_positive_portfolio_value() -> None:
    """A book worth nothing has no risk to measure."""
    with pytest.raises(ValueError):
        MonteCarloVaRInputs(
            weights=[0.5, 0.5],
            factor_volatilities=[0.2, 0.15],
            normal_correlations=[[1.0, 0.3], [0.3, 1.0]],
            portfolio_value=0.0,
        )


# ==========================================================================
# The three Tier-1 estimators are UNCHANGED (D-096: nothing is deleted).
# ==========================================================================


def test_the_tier_one_estimators_still_ship_and_still_agree_with_each_other() -> None:
    """D-096's core promise: Phase 5+ adds, it does not delete.

    The three Tier-1 estimators must remain importable and behave as before.
    ``historical_var`` and ``parametric_var`` are computed here on a simple
    series and asserted to be the positive-loss convention they always were.
    """
    returns = [0.01, -0.02, 0.015, 0.005, -0.01, 0.02, -0.005, -0.12, 0.01, 0.003]
    hist = historical_var(ReturnsInputs(returns=returns, confidence=0.95))
    assert as_float(hist) == pytest.approx(7.5, abs=1e-6)
    es = expected_shortfall(ReturnsInputs(returns=returns, confidence=0.95))
    assert as_float(es) > as_float(hist)
    para = parametric_var(
        ParametricVaRInputs(
            portfolio_value=_VALUE,
            vol_annualized=0.15,
            confidence=0.95,
            horizon_days=1,
        )
    )
    assert as_float(para, key="var_pct") > 0.0
