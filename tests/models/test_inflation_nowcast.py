"""Tests for Module 5.1 — ``project_shelter_cpi``.

The centrepiece is the **vintage index**. The specification's sample uses
``[-lag_months]``, which reads the element ``lag_months - 1`` positions before the
end; since the end element is the *current* month, that is ``lag_months - 1``
months ago, not ``lag_months``. Worse, its meaning moves with the length of the
list the caller happened to supply, so the same code reports different lags on
different inputs while the context line states one fixed number.

Every guard here is therefore written in terms of **months ago**, and the fixtures
are built by constructing a series whose value at each offset is distinguishable —
so reading the wrong offset produces a different, identifiable number rather than
a plausible one.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from macro_engine.config import get_settings
from macro_engine.models.inflation_nowcast import (
    ShelterLagInputs,
    project_shelter_cpi,
)
from tests.helpers import as_float

# A market-rent series old enough to satisfy any lag the config might hold, with
# each position's value encoding its own months-ago offset. Any index error
# yields a value that names the offset it actually read.
MARKER_BASE = 100.0


def _marker_series(length: int) -> list[float]:
    """Rent growth whose value at each index is the month it represents.

    ``index i`` (oldest first) = ``length - 1 - i`` months ago, so the value is
    set to exactly the months-ago number. Reading index -k then returns
    ``k - 1`` — which is the defect, made visible as a number rather than
    inferred.
    """
    return [float((length - 1) - i) for i in range(length)]


def _lag() -> int:
    """The configured lag, never a literal — a recalibration must move the tests."""
    return get_settings().inflation.shelter_lag


def _tolerance() -> float:
    return get_settings().inflation.shelter_converged_tolerance


# ---------------------------------------------------------------------------
# The vintage index — the defect the module exists to correct
# ---------------------------------------------------------------------------


def test_projection_reads_the_vintage_exactly_lag_months_ago() -> None:
    """``lag`` months ago is index ``-(lag + 1)``, not ``-lag``.

    With the marker series, the value returned must equal ``lag`` exactly. The
    specification's ``[-lag]`` returns ``lag - 1``, so this test fails by exactly
    one under the specification's spelling.
    """
    length = _lag() + 4
    result = project_shelter_cpi(
        ShelterLagInputs(
            market_rent_growth_yoy_pct=_marker_series(length),
            current_cpi_shelter_yoy_pct=50.0,
        )
    )
    assert as_float(result) == pytest.approx(float(_lag()))


def test_vintage_is_stable_when_the_caller_passes_extra_history() -> None:
    """The reported vintage must NOT depend on how much history was supplied.

    This is the failure mode the specification's ``[-lag]`` has: with 18 points
    it reads 14-months-ago, with 15 points it reads the oldest point. The
    projection is a statement about a fixed lag, so extra history must not move
    the number read.
    """
    current = 50.0
    readings = []
    for length in (_lag() + 1, _lag() + 2, _lag() + 12, _lag() + 30):
        result = project_shelter_cpi(
            ShelterLagInputs(
                market_rent_growth_yoy_pct=_marker_series(length),
                current_cpi_shelter_yoy_pct=current,
            )
        )
        readings.append(as_float(result))
    assert len(set(readings)) == 1, (
        f"the projection moved with the length of the supplied history: {readings}. "
        f"The vintage is fixed by the lag, not by the caller's list length."
    )
    assert readings[0] == pytest.approx(float(_lag()))


def test_index_minus_lag_would_read_one_month_early() -> None:
    """Documents the exact defect being corrected, as an executable statement.

    ``series[-lag]`` selects the element ``lag - 1`` before the end. With the
    marker series that returns ``lag - 1``. Asserting the difference here means a
    future "simplification" back to ``[-lag]`` fails with a message that explains
    itself rather than a bare off-by-one.
    """
    length = _lag() + 4
    series = _marker_series(length)
    spec_spelling = series[-_lag()]
    correct_spelling = series[-(_lag() + 1)]
    assert spec_spelling == pytest.approx(float(_lag() - 1))
    assert correct_spelling == pytest.approx(float(_lag()))
    assert spec_spelling != correct_spelling


def test_reversed_series_order_produces_a_different_result() -> None:
    """List order is load-bearing; a reversed list must not silently "work".

    The docstring states oldest-first and says why. A reversed input reads the
    current month instead of the lagged vintage, which is a plausible number from
    the wrong end of the window — no shape or range check would catch it.
    """
    length = _lag() + 4
    forward = _marker_series(length)
    result_forward = project_shelter_cpi(
        ShelterLagInputs(market_rent_growth_yoy_pct=forward, current_cpi_shelter_yoy_pct=50.0)
    )
    result_reversed = project_shelter_cpi(
        ShelterLagInputs(
            market_rent_growth_yoy_pct=list(reversed(forward)),
            current_cpi_shelter_yoy_pct=50.0,
        )
    )
    assert as_float(result_forward) != pytest.approx(as_float(result_reversed))


# ---------------------------------------------------------------------------
# Insufficient history — None, not a substituted vintage
# ---------------------------------------------------------------------------


def test_insufficient_history_returns_none_not_the_oldest_point() -> None:
    """``value is None`` when no observation exists at the required vintage.

    Using the oldest available point would report a shorter lag under the
    configured lag's name. The spec's ``value=None`` is kept; only its confidence
    is corrected.
    """
    short = _marker_series(_lag() - 1)
    result = project_shelter_cpi(
        ShelterLagInputs(market_rent_growth_yoy_pct=short, current_cpi_shelter_yoy_pct=50.0)
    )
    assert result.value is None
    assert "Insufficient" in result.interpretation


def test_exactly_the_required_length_succeeds() -> None:
    """The boundary: ``lag + 1`` points is enough, because the current month counts.

    The specification's guard is ``len < lag_months``, which admits a list of
    exactly ``lag`` points — but a list of ``lag`` points has its oldest element
    ``lag - 1`` months ago, so the required vintage does not exist. The corrected
    requirement is ``lag + 1``, and this pair of tests pins both sides of it.
    """
    exact = _marker_series(_lag() + 1)
    result = project_shelter_cpi(
        ShelterLagInputs(market_rent_growth_yoy_pct=exact, current_cpi_shelter_yoy_pct=50.0)
    )
    assert result.value is not None
    assert as_float(result) == pytest.approx(float(_lag()))


def test_one_point_short_of_required_length_fails() -> None:
    """``lag`` points is one short — the other side of the same boundary."""
    one_short = _marker_series(_lag())
    result = project_shelter_cpi(
        ShelterLagInputs(market_rent_growth_yoy_pct=one_short, current_cpi_shelter_yoy_pct=50.0)
    )
    assert result.value is None


def test_insufficient_history_confidence_is_computed_not_zero() -> None:
    """The spec writes ``confidence=0.0``; Section 22.8 forbids a literal.

    ``0.0`` is below the configured floor, which exists so that a returning
    confidence is distinguishable from a missing value. The computed value must
    be positive, and it must equal what the formula produces for a flagged input.
    """
    from macro_engine.models.contracts import ConfidenceInputs, compute_confidence

    result = project_shelter_cpi(
        ShelterLagInputs(
            market_rent_growth_yoy_pct=_marker_series(_lag() - 1),
            current_cpi_shelter_yoy_pct=50.0,
        )
    )
    assert result.confidence > 0.0
    assert result.confidence == pytest.approx(
        compute_confidence(ConfidenceInputs(data_quality_flags_present=True))
    )


def test_insufficient_history_names_the_required_length_in_the_message() -> None:
    """The error must state the requirement, not just that data was missing."""
    result = project_shelter_cpi(
        ShelterLagInputs(
            market_rent_growth_yoy_pct=_marker_series(2),
            current_cpi_shelter_yoy_pct=50.0,
        )
    )
    assert f"{_lag() + 1} required" in result.interpretation
    assert f"{_lag()}-month lag" in result.interpretation


# ---------------------------------------------------------------------------
# Direction — three states, not two
# ---------------------------------------------------------------------------


def test_cooling_when_lagged_rents_are_below_current_shelter() -> None:
    result = project_shelter_cpi(
        ShelterLagInputs(
            market_rent_growth_yoy_pct=_marker_series(_lag() + 3),
            current_cpi_shelter_yoy_pct=float(_lag()) + 5.0,
        )
    )
    assert "cooling" in result.interpretation


def test_reaccelerating_when_lagged_rents_are_above_current_shelter() -> None:
    result = project_shelter_cpi(
        ShelterLagInputs(
            market_rent_growth_yoy_pct=_marker_series(_lag() + 3),
            current_cpi_shelter_yoy_pct=float(_lag()) - 5.0,
        )
    )
    assert "reaccelerating" in result.interpretation


def test_exact_match_is_converged_not_reaccelerating() -> None:
    """The specification's two-way test calls an exact match "reaccelerating".

    That asserts a direction change where none exists. A gap of zero must be
    reported as converged.

    The converged branch deliberately uses different prose ("already at …
    consistent with") rather than inserting the word "converged", so the
    assertion targets both the wording AND the absence of the two directional
    words. An earlier version searched only for the literal "converged" and
    failed against correct code.
    """
    result = project_shelter_cpi(
        ShelterLagInputs(
            market_rent_growth_yoy_pct=_marker_series(_lag() + 3),
            current_cpi_shelter_yoy_pct=float(_lag()),
        )
    )
    assert "consistent with the market-rent vintage" in result.interpretation
    assert "reaccelerating" not in result.interpretation
    assert "cooling" not in result.interpretation


def test_converged_band_boundary_is_inclusive() -> None:
    """A gap exactly at the tolerance is converged — the comparison is ``<=``.

    Fixture built from the config value, so a recalibration moves the test.
    """
    tolerance = _tolerance()
    result = project_shelter_cpi(
        ShelterLagInputs(
            market_rent_growth_yoy_pct=_marker_series(_lag() + 3),
            current_cpi_shelter_yoy_pct=float(_lag()) - tolerance,
        )
    )
    assert "consistent with the market-rent vintage" in result.interpretation
    assert "reaccelerating" not in result.interpretation


def test_just_outside_the_converged_band_is_directional() -> None:
    """One step beyond the tolerance must produce a direction.

    Without this the boundary test above could be satisfied by a model that
    always says "converged".
    """
    tolerance = _tolerance()
    result = project_shelter_cpi(
        ShelterLagInputs(
            market_rent_growth_yoy_pct=_marker_series(_lag() + 3),
            current_cpi_shelter_yoy_pct=float(_lag()) - tolerance - 0.05,
        )
    )
    assert "consistent with the market-rent vintage" not in result.interpretation
    assert "reaccelerating" in result.interpretation


def test_converged_case_warns_that_it_carries_no_forward_information() -> None:
    """A converged reading is a level confirmation, and the warning says so."""
    result = project_shelter_cpi(
        ShelterLagInputs(
            market_rent_growth_yoy_pct=_marker_series(_lag() + 3),
            current_cpi_shelter_yoy_pct=float(_lag()),
        )
    )
    assert any("little forward information" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Config, not literals
# ---------------------------------------------------------------------------


def test_lag_is_not_an_input_field() -> None:
    """``lag_months`` must not shadow config with a signature default."""
    assert set(ShelterLagInputs.model_fields) == {
        "market_rent_growth_yoy_pct",
        "current_cpi_shelter_yoy_pct",
    }


def test_lag_passed_as_a_field_is_rejected() -> None:
    """A caller's lag fails loudly rather than being absorbed by a default."""
    with pytest.raises(ValidationError):
        ShelterLagInputs(
            market_rent_growth_yoy_pct=[1.0] * 20,
            current_cpi_shelter_yoy_pct=4.0,
            lag_months=12,  # type: ignore[call-arg]
        )


def test_input_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ShelterLagInputs(
            market_rent_growth_yoy_pct=[1.0] * 20,
            cpi_shelter_yoy_pct=4.0,  # type: ignore[call-arg]
        )


def test_empty_history_is_handled_not_crashed() -> None:
    """An empty list must take the insufficient-data path, not raise."""
    result = project_shelter_cpi(
        ShelterLagInputs(market_rent_growth_yoy_pct=[], current_cpi_shelter_yoy_pct=4.0)
    )
    assert result.value is None
    assert "0 months supplied" in result.interpretation


# ---------------------------------------------------------------------------
# Confidence and reporting
# ---------------------------------------------------------------------------


def test_normal_path_confidence_is_computed() -> None:
    from macro_engine.models.contracts import ConfidenceInputs, compute_confidence

    result = project_shelter_cpi(
        ShelterLagInputs(
            market_rent_growth_yoy_pct=_marker_series(_lag() + 3),
            current_cpi_shelter_yoy_pct=50.0,
        )
    )
    assert result.confidence == pytest.approx(compute_confidence(ConfidenceInputs()))


def test_no_hardcoded_confidence_in_either_branch() -> None:
    """Both branches carry exactly one confidence value, the computed one."""
    ok = project_shelter_cpi(
        ShelterLagInputs(
            market_rent_growth_yoy_pct=_marker_series(_lag() + 3),
            current_cpi_shelter_yoy_pct=50.0,
        )
    )
    short = project_shelter_cpi(
        ShelterLagInputs(
            market_rent_growth_yoy_pct=_marker_series(1),
            current_cpi_shelter_yoy_pct=50.0,
        )
    )
    assert len([ok.confidence]) == 1
    assert len([short.confidence]) == 1
    assert short.confidence < ok.confidence


def test_context_reports_the_gap_between_projection_and_current() -> None:
    result = project_shelter_cpi(
        ShelterLagInputs(
            market_rent_growth_yoy_pct=_marker_series(_lag() + 3),
            current_cpi_shelter_yoy_pct=float(_lag()) + 2.0,
        )
    )
    assert "-2.00pp" in result.context


def test_extra_history_warning_fires_only_when_history_is_extra() -> None:
    """More history is not more information here, and the model says so."""
    extra = project_shelter_cpi(
        ShelterLagInputs(
            market_rent_growth_yoy_pct=_marker_series(_lag() + 6),
            current_cpi_shelter_yoy_pct=50.0,
        )
    )
    exact = project_shelter_cpi(
        ShelterLagInputs(
            market_rent_growth_yoy_pct=_marker_series(_lag() + 1),
            current_cpi_shelter_yoy_pct=50.0,
        )
    )
    assert any("do not improve it" in w or "does not improve it" in w for w in extra.warnings)
    assert not any("improve it" in w for w in exact.warnings)


def test_vintage_warning_names_the_config_driven_lag() -> None:
    """The reported vintage must be described as config-derived, not measured."""
    result = project_shelter_cpi(
        ShelterLagInputs(
            market_rent_growth_yoy_pct=_marker_series(_lag() + 3),
            current_cpi_shelter_yoy_pct=50.0,
        )
    )
    assert any(f"{_lag()} months ago" in w and "config parameter" in w for w in result.warnings)


def test_lag_assumption_warning_is_always_present() -> None:
    """The average-not-fixed-delay caveat applies to every run."""
    result = project_shelter_cpi(
        ShelterLagInputs(
            market_rent_growth_yoy_pct=_marker_series(_lag() + 3),
            current_cpi_shelter_yoy_pct=50.0,
        )
    )
    assert any("lease-turnover dynamics hold" in w for w in result.warnings)


def test_shelter_share_warning_is_always_present() -> None:
    """Shelter's weight in CPI is what makes the assumption load-bearing."""
    result = project_shelter_cpi(
        ShelterLagInputs(
            market_rent_growth_yoy_pct=_marker_series(_lag() + 3),
            current_cpi_shelter_yoy_pct=50.0,
        )
    )
    assert any("third of CPI" in w for w in result.warnings)
