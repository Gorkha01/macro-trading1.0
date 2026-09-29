"""D-070 — ``api_layer.orchestration``: the derivation, and its refusals.

This module is the API layer's only place where a **wrong number can look like a
right one**. Everything else in ``api_layer/`` is transport. So this file has two
jobs, and the second is the one that matters:

1. **Prove each derivation is the one documented** — the m/m convention, the
   claims 4-week pairing, the two unit conversions JOLTS needs, the YoY
   anniversary tolerance.
2. **Prove every refusal is a refusal**, not a default. The alternative to
   refusing is the failure ``live_builder_check.py`` shipped: four literals
   (``0.2 / 0.3 / 0.1 / -0.4``) that produce a syntactically perfect thesis
   about a world that does not exist. A test that only asserted the happy path
   would pass on a module that defaulted every missing series to zero.

**Why the expected values are hand-computed.** Section 21.2 Step 4: if a test
passes on the first attempt without the expected value having been computed
independently, it asserted whatever the code produced. Every arithmetic
expectation below carries the calculation that produced it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from macro_engine.api_layer.orchestration import (
    DerivationNote,
    OrchestrationError,
    ThesisInputs,
    _config_tenor_for,
    snapshot_to_thesis_inputs,
)
from macro_engine.config import get_settings
from macro_engine.data_layer.schemas import (
    MacroDataSnapshot,
    ObservationPoint,
    YieldCurveSnapshot,
)
from macro_engine.models.contracts import ModelResult
from macro_engine.models.instrument_selection import ThesisType
from macro_engine.thesis_layer.schemas import ProductionUniverse

# ---------------------------------------------------------------------------
# A hand-built, fully-consistent snapshot
# ---------------------------------------------------------------------------
#
# Built with EXPLICIT dates rather than ``make_points``' relative origin,
# because several assertions below are about the calendar (the one-year
# anniversary, the 4-week boundary) and a relative origin makes those assertions
# depend on the day the suite is run.

_AS_OF = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def _monthly(values: list[float], *, series_id: str, last_month: int = 8) -> list[ObservationPoint]:
    """Monthly points ending in ``last_month`` of 2026, oldest first."""
    points: list[ObservationPoint] = []
    month = last_month - (len(values) - 1)
    year = 2026
    while month <= 0:
        month += 12
        year -= 1
    for value in values:
        points.append(
            ObservationPoint(
                observation_date=date(year, month, 1),
                value=value,
                series_id=series_id,
            )
        )
        month += 1
        if month > 12:
            month = 1
            year += 1
    return points


def _weekly(values: list[float], *, series_id: str) -> list[ObservationPoint]:
    """Weekly points ending on 2026-09-12, oldest first."""
    end = date(2026, 9, 12)
    start = end - timedelta(weeks=len(values) - 1)
    return [
        ObservationPoint(
            observation_date=start + timedelta(weeks=index),
            value=value,
            series_id=series_id,
        )
        for index, value in enumerate(values)
    ]


def _quarterly(values: list[float], *, series_id: str) -> list[ObservationPoint]:
    """Quarterly points ending 2026-04-01, oldest first."""
    end = date(2026, 4, 1)
    points: list[ObservationPoint] = []
    month, year = end.month, end.year
    for offset in range(len(values)):
        m = month - 3 * offset
        y = year
        while m <= 0:
            m += 12
            y -= 1
        points.append(
            ObservationPoint(
                observation_date=date(y, m, 1),
                value=values[-1 - offset],
                series_id=series_id,
            )
        )
    points.reverse()
    return points


def _two_years_monthly(
    *, series_id: str, recent: list[float], prior: list[float]
) -> list[ObservationPoint]:
    """13 months of history: ``prior`` then ``recent``, monthly, ending 2026-08.

    Thirteen rather than twelve so the first point of the recent block has an
    exact one-year anniversary inside the series — which is what the YoY
    tolerance guard requires and what makes these fixtures exercise the guard's
    *permissive* branch rather than its refusal.
    """
    values = [*prior, *recent]
    return _monthly(values, series_id=series_id)


@pytest.fixture
def consistent_snapshot() -> MacroDataSnapshot:
    """A snapshot every derivation can read, with round numbers.

    The numbers are chosen so each expectation is checkable by hand:

    * ``cpi_headline`` 330.0 -> 331.0 is ``+0.303030...%``
    * ``cpi_core`` 335.0 -> 336.0 is ``+0.298507...%``
    * ``pce_core`` 129.0 -> 130.0 is ``+0.775193...%``, and its year-ago
      (125.0) makes the YoY ``+4.0%`` exactly
    * ``initial_claims`` recent 4wk avg 200,000 vs prior 4wk avg 210,000 is
      ``-4.761904...%``
    * ``jolts_openings`` 2025-08 7,000 -> 2026-08 8,000 is ``+14.285714...%``
    * ``gdp_real`` / ``gdp_potential`` produce a same-quarter gap of
      ``(23000 - 22500) / 22500 * 100 = +2.2222...%``
    """
    return MacroDataSnapshot(
        country="us",
        as_of=_AS_OF,
        gdp_real=_quarterly([22000.0, 22500.0, 23000.0], series_id="gdp_real"),
        gdp_potential=_quarterly([22100.0, 22300.0, 22500.0], series_id="gdp_potential"),
        # 13 monthly points: 12 prior + 1 latest, so the anniversary is exact.
        cpi_headline=_monthly(
            [*[300.0] * 11, 330.0, 331.0],
            series_id="cpi_headline",
        ),
        cpi_core=_monthly(
            [*[320.0] * 11, 335.0, 336.0],
            series_id="cpi_core",
        ),
        pce_core=_monthly(
            [*[125.0] * 11, 129.0, 130.0],
            series_id="pce_core",
        ),
        initial_claims=_weekly(
            [
                210_000.0,
                210_000.0,
                210_000.0,
                210_000.0,
                200_000.0,
                200_000.0,
                200_000.0,
                200_000.0,
            ],
            series_id="initial_claims",
        ),
        jolts_openings=_monthly(
            [
                7000.0,
                7000.0,
                7000.0,
                7000.0,
                7000.0,
                7000.0,
                7000.0,
                7000.0,
                7000.0,
                7000.0,
                7000.0,
                7000.0,
                7000.0,
                8000.0,
            ],
            series_id="jolts_openings",
        ),
        jolts_quits=_monthly(
            [2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 3.0, 3.0],
            series_id="jolts_quits",
        ),
        iorb=_monthly([4.0] * 13, series_id="iorb"),
        # --- Module 4.1 balance sheet (D-085). 14 weekly points so the 13-week
        #     change has both endpoints. WALCL/WRESBAL in MILLIONS, RRPONTSYD in
        #     BILLIONS — the 1000x trap the leg asserts against.
        #
        #     assets:    6,700,000 -> 6,750,000 over 13 weeks = +50,000mn
        #     change_pct = 50,000 / 6,750,000 * 100 = +0.740740...%  -> QE (>0.5)
        #     reserves:  3,050,000 -> 3,000,000 = -50,000mn (draining)
        #     RRP:       5.0bn, far below the drained threshold -> drained
        #     => QE_EXPANDING, reserves falling, RRP gone: the scarcity shape.
        fed_total_assets=_weekly(
            [6_700_000.0, *[6_720_000.0] * 12, 6_750_000.0],
            series_id="fed_total_assets",
        ),
        reserve_balances=_weekly(
            [3_050_000.0, *[3_040_000.0] * 12, 3_000_000.0],
            series_id="reserve_balances",
        ),
        on_rrp_volume_bn=_weekly([5.0] * 14, series_id="on_rrp_volume_bn"),
        yield_curve=YieldCurveSnapshot(
            as_of=date(2026, 9, 15),
            tenors={"3mo": 4.6, "1yr": 4.5, "2yr": 4.25, "10yr": 4.1, "30yr": 4.5},
        ),
    )


def _note_float(note: DerivationNote) -> float:
    """Read a derivation note's numeric value.

    Notes stringify with ``:+.4f`` because they are *display* strings — the
    precision a reviewer reads, not the precision the arithmetic carries. A test
    that compared the string against a full-precision expectation would be
    asserting the formatter, so this parses the value back to a float and every
    expectation below uses ``rel=1e-3``, which is the precision the note
    genuinely reports.
    """
    return float(note.value)


def _model_float(value: object) -> float:
    """Read a ``ModelResult.value`` as a float, refusing anything non-numeric.

    ``ModelResult.value`` is typed as a union (a model may publish a dict, a
    string or a number), so ``float(result.value)`` is an ``arg-type`` error
    under ``mypy --strict`` — and it *should* be: the union is telling the truth
    about what a model may return. This narrows it explicitly, so a model that
    started publishing a string would fail here with a clear message rather than
    a confusing ``TypeError`` inside ``pytest.approx``.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise AssertionError(
            f"expected a numeric ModelResult.value, got {type(value).__name__}: {value!r}"
        )
    return float(value)


# ---------------------------------------------------------------------------
# 1. The happy path — every argument derived, none defaulted
# ---------------------------------------------------------------------------


def test_the_six_arguments_are_all_produced(consistent_snapshot: MacroDataSnapshot) -> None:
    """The builder takes six required arguments; the orchestration must supply six.

    Measured against the builder's real signature (``.probe/d070_sig.py``):
    ``reads``, ``taylor_inputs``, ``first_difference_inputs`` required
    positionally; ``thesis_type``, ``universe``, ``short_yield`` required
    keyword-only. Section 8.2's sample passes one — this proves the gap is
    closed rather than relocated.
    """
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)

    assert isinstance(inputs, ThesisInputs)
    assert inputs.reads.growth.model_name
    assert inputs.reads.inflation.model_name
    assert inputs.reads.labor.model_name
    assert inputs.taylor_inputs is not None
    assert inputs.first_difference_inputs is not None
    assert inputs.short_yield > 0.0
    assert isinstance(inputs.thesis_type, ThesisType)
    assert isinstance(inputs.universe, ProductionUniverse)


def test_short_yield_comes_from_the_curve_in_percent(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """``short_yield`` is the configured tenor of the curve, in PERCENT.

    4.25 is the fixture's 2yr. The assertion is not merely "it is positive" —
    a basis-point read would be 425.0, and a test that only checked the sign
    would pass on the units fault this function's range check exists to catch.
    """
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)

    assert inputs.short_yield == pytest.approx(4.25)


def test_the_configured_tenor_is_the_one_read(consistent_snapshot: MacroDataSnapshot) -> None:
    """The tenor is config, so moving it must move the derivation."""
    inputs = snapshot_to_thesis_inputs(consistent_snapshot, short_yield_tenor="10yr")

    assert inputs.short_yield == pytest.approx(4.1)


def test_thesis_type_defaults_from_config_and_is_disclosed(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """Assuming a family is allowed; assuming it silently is not.

    The builder's divergence 1 is explicit that ``thesis_type`` is an analytical
    choice and that guessing it from the gap "would be manufacturing a claim".
    The API therefore *has* a default — it must pass something — and this test
    pins that the assumption is recorded in ``notes``, where a caller can see it.
    """
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)
    configured = ThesisType(get_settings().api.default_thesis_type)

    assert inputs.thesis_type is configured
    note = next(n for n in inputs.notes if n.name == "thesis_type")
    assert "assumed from api.default_thesis_type" in note.source


def test_an_explicit_thesis_type_is_honoured_and_labelled(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    inputs = snapshot_to_thesis_inputs(consistent_snapshot, thesis_type=ThesisType.CURVE_SHAPE_GAP)

    assert inputs.thesis_type is ThesisType.CURVE_SHAPE_GAP
    note = next(n for n in inputs.notes if n.name == "thesis_type")
    assert note.source == "supplied by the caller"


def test_curve_legs_are_forwarded_for_a_curve_thesis(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    inputs = snapshot_to_thesis_inputs(
        consistent_snapshot,
        thesis_type=ThesisType.CURVE_SHAPE_GAP,
        curve_short_tenor="2yr",
        curve_long_tenor="10yr",
    )

    note = next(n for n in inputs.notes if n.name == "curve legs")
    assert "2yr" in note.value
    assert "10yr" in note.value


def test_curve_legs_on_an_outright_thesis_are_flagged_not_dropped(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """An inert input must be reported, not silently ignored (D-037's class).

    Nothing reads the curve legs on a ``POLICY_PATH_GAP`` thesis. The failure
    mode is a caller who set them expecting them to matter and got no signal,
    so the orchestration says so.
    """
    inputs = snapshot_to_thesis_inputs(
        consistent_snapshot,
        thesis_type=ThesisType.POLICY_PATH_GAP,
        curve_short_tenor="2yr",
        curve_long_tenor="10yr",
    )

    assert not any(n.name == "curve legs" for n in inputs.notes)
    assert any("CURVE LEGS IGNORED" in w for w in inputs.warnings)


# ---------------------------------------------------------------------------
# 2. The inflation leg — the m/m convention and the sign test
# ---------------------------------------------------------------------------


def test_inflation_legs_are_month_over_month_percent(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """Each measure is a m/m percent change of the latest two observations.

    Hand calculation:
        cpi_headline  331/330 - 1 = +0.303030...%
        cpi_core      336/335 - 1 = +0.298507...%
        pce_core      130/129 - 1 = +0.775193...%

    The divisor is the PRIOR observation. Getting that backwards would divide
    by the latest, which inverts which of the two is "large" and is invisible
    in the sign test the model actually performs.
    """
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)
    by_name = {n.name: n for n in inputs.notes}

    assert _note_float(by_name["cpi_headline_mom"]) == pytest.approx(0.3030, abs=5e-5)
    assert _note_float(by_name["cpi_core_mom"]) == pytest.approx(0.2985, abs=5e-5)
    assert _note_float(by_name["pce_core_mom"]) == pytest.approx(0.7752, abs=5e-5)


def test_all_three_rising_reads_as_convergent(consistent_snapshot: MacroDataSnapshot) -> None:
    """Three positive m/m changes are a convergent breadth read.

    The model's own docstring: ``same direction (all positive) -> convergent``,
    ``average = (0.2 + 0.3 + 0.1) / 3``. Here the average is
    ``(0.3030 + 0.2985 + 0.7752) / 3 = +0.4589...``.
    """
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)
    expected = (0.3030303 + 0.2985075 + 0.7751938) / 3

    assert _model_float(inputs.reads.inflation.value) == pytest.approx(expected, abs=5e-3)


def test_a_missing_price_series_refuses_rather_than_substituting(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """The breadth score is a sign test across three measures; two is not a test.

    ``InflationSubMeasures`` has no defaults and cannot have them: substituting
    a value for a missing measure changes the verdict rather than degrading it.
    """
    broken = consistent_snapshot.model_copy(update={"pce_core": []})

    with pytest.raises(OrchestrationError) as caught:
        snapshot_to_thesis_inputs(broken)

    assert caught.value.fields == ("pce_core",)
    assert "is empty" in str(caught.value)


def test_a_zero_prior_observation_refuses(consistent_snapshot: MacroDataSnapshot) -> None:
    """A zero denominator is undefined, not infinite.

    Hand-checked: the fixture's cpi_headline prior point is set to zero, so the
    m/m change would divide by zero. Returning ``inf`` would propagate into an
    ``InflationSubMeasures`` field and then into an average, and the failure
    would surface as a nonsensical score rather than as a refusal.
    """
    points = list(consistent_snapshot.cpi_headline)
    points[-2] = points[-2].model_copy(update={"value": 0.0})
    broken = consistent_snapshot.model_copy(update={"cpi_headline": points})

    with pytest.raises(OrchestrationError) as caught:
        snapshot_to_thesis_inputs(broken)

    assert caught.value.fields == ("cpi_headline",)
    assert "zero prior observation" in str(caught.value)


# ---------------------------------------------------------------------------
# 3. The labor leg — three unit conversions, each of which is silent if wrong
# ---------------------------------------------------------------------------


def test_claims_change_is_the_four_week_ratio_not_a_single_week(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """8 weekly points -> recent 4wk avg vs prior 4wk avg, NON-overlapping.

    Hand calculation: recent avg = 200,000; prior avg = 210,000;
    ``(200000/210000 - 1) * 100 = -4.761904...%``.

    The overlap trap: ``avg(last4) / avg(-3:-7)`` shares three of four
    observations with the numerator and would compress this toward zero. The
    fixture's eight points make the two averages exactly derivable, so a
    three-observation overlap is visible as a different number rather than as
    a rounding difference.
    """
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)
    note = next(n for n in inputs.notes if n.name == "initial_claims_4wk_avg_change_pct")

    assert _note_float(note) == pytest.approx(-4.7619, abs=5e-5)


def test_claims_sign_is_not_inverted_by_the_conversion(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """POSITIVE means claims RISING, i.e. labor loosening — the model's contract.

    ``LaborInputs`` states the inversion is performed by the score's own
    configurable multiplier, not by a leading minus sign at the call site. So
    the conversion must return the natural signed change. Inverting here *as
    well as* there cancels and reports a tightening labor market on a claims
    surge — a two-negatives defect that each half looks correct in isolation.
    """
    points = list(consistent_snapshot.initial_claims)
    # Reverse the two 4-week blocks: claims now RISING.
    rising = points[-4:] + points[:4]
    rising = [
        p.model_copy(update={"observation_date": points[index].observation_date})
        for index, p in enumerate(rising)
    ]
    snapshot = consistent_snapshot.model_copy(update={"initial_claims": rising})

    inputs = snapshot_to_thesis_inputs(snapshot)
    note = next(n for n in inputs.notes if n.name == "initial_claims_4wk_avg_change_pct")

    assert float(note.value) > 0.0, "rising claims must read as a POSITIVE change"


def test_claims_needs_eight_weeks_not_seven(consistent_snapshot: MacroDataSnapshot) -> None:
    """Seven points cannot form two non-overlapping 4-week windows."""
    broken = consistent_snapshot.model_copy(
        update={"initial_claims": consistent_snapshot.initial_claims[:7]}
    )

    with pytest.raises(OrchestrationError) as caught:
        snapshot_to_thesis_inputs(broken)

    assert caught.value.fields == ("initial_claims",)
    assert "needs 8" in str(caught.value)


def test_jolts_openings_is_converted_from_thousands_to_a_percent(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """JTSJOL is published in THOUSANDS; the model wants a YoY PERCENT.

    Hand calculation: 8,000 / 7,000 - 1 = ``+14.285714...%``.

    This is the trap the registry records (``units: thousands``, measured level
    7271.0). Passing the level would put seven thousand into a term whose sane
    range is single digits and produce a tightness score in the thousands —
    loud in this fixture, but the *real* trap is that a level of 3.0 in some
    other series would pass silently.
    """
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)
    note = next(n for n in inputs.notes if n.name == "jolts_openings_yoy_pct")

    assert _note_float(note) == pytest.approx(14.2857, abs=5e-5)
    assert "THOUSANDS" in note.source


def test_jolts_quits_is_a_percentile_of_its_window_not_the_rate(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """JTSQUR is a rate in PERCENT; the model wants a percentile of its range.

    The fixture's quits series is 2.0 for two years and 3.0 for the last point,
    so the latest value is at or above every observation -> 100.0.

    Why this matters more than it looks: 1.9 (the live rate) satisfies the
    model's ``ge=0, le=100`` validator, so passing the RATE instead of the
    PERCENTILE is accepted silently and reports near-zero quits pressure. The
    validator cannot catch it — the two quantities share a range. Only the
    transformation can, which is why the transformation is tested.
    """
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)
    note = next(n for n in inputs.notes if n.name == "jolts_quits_level_percentile")

    assert float(note.value) == pytest.approx(100.0)
    assert note.window is not None and "monthly observations" in note.window


def test_jolts_quits_percentile_reports_the_window_it_used(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """A percentile over a narrowed window makes an ordinary reading look extreme.

    ``LaborInputs`` documents "trailing 3-year range"; the 13-point fixture
    cannot supply three years, so the window is 13. The number must be
    *reported* rather than described as three years.
    """
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)
    note = next(n for n in inputs.notes if n.name == "jolts_quits_level_percentile")

    assert note.window == "13 monthly observations"


def test_the_missing_nfp_block_is_disclosed(consistent_snapshot: MacroDataSnapshot) -> None:
    """No payrolls field exists, so the score is a 2-block reading.

    The alternative — ``nfp_3m_avg=0.0`` — is a *legal* value meaning "no
    payroll growth", so the score would return a plausible number computed from
    an asserted fact about a series nobody read. This test pins that the
    degradation is stated rather than absorbed.
    """
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)

    match = [w for w in inputs.warnings if "NFP MISSING" in w]
    assert match, "the NFP gap must be disclosed"
    assert "2-block reading" in match[0]


def test_labor_computation_uses_the_configured_score(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """The labor leg is the real model, not a re-implementation.

    Hand calculation with the fixture's derived inputs, at Section 6.4's
    defaults (claims weight 0.4, JOLTS 0.4, NFP 0.2 and the claims multiplier
    2.0):

        claims_component = -(-4.7619048) * 2.0              = +9.5238096
        jolts_component  = 0.5(14.2857143) + 0.5(100 - 50)  = 7.1428572 + 25.0
                                                            = +32.1428572
        nfp_component    = (0 - 150) / 10                    = -15.0
        score = 0.4(9.5238096) + 0.4(32.1428572) + 0.2(-15.0)
              = 3.8095238 + 12.8571429 - 3.0 = +13.6666667

    Computed here independently rather than read off the result, so a change to
    the model's weights makes this test fail rather than silently agree.
    """
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)

    expected = (
        0.4 * (4.7619048 * 2.0)
        + 0.4 * (0.5 * 14.2857143 + 0.5 * (100.0 - 50.0))
        + 0.2 * ((0.0 - 150.0) / 10.0)
    )
    assert _model_float(inputs.reads.labor.value) == pytest.approx(expected, abs=5e-2)


# ---------------------------------------------------------------------------
# 4. The policy chain — levels versus changes
# ---------------------------------------------------------------------------


def test_pi_current_is_a_year_over_year_level(consistent_snapshot: MacroDataSnapshot) -> None:
    """The Taylor rule reads a LEVEL where the inflation leg reads a CHANGE.

    Hand calculation: 130.0 / 125.0 - 1 = ``+4.0%`` exactly.

    Deriving ``pi_current`` from the m/m alone would put a one-month rate into a
    rule calibrated on a twelve-month one — the kind of substitution that
    produces a plausible policy rate from the wrong quantity.
    """
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)
    note = next(n for n in inputs.notes if n.name == "pi_current")

    assert _note_float(note) == pytest.approx(4.0)
    assert inputs.taylor_inputs.pi_current == pytest.approx(4.0)


def test_the_taylor_rule_is_fed_the_derived_gap_and_the_config_target(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """``r_star`` from config, ``output_gap`` from the growth leg, target defaulted.

    Hand calculation of the fixture's gap: ``(23000 - 22500) / 22500 * 100 =
    +2.2222...%``.

    ``pi_target=None`` is deliberate: the model resolves it from its own config,
    and passing 2.0 from here would be a second literal for one target.
    """
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)
    settings = get_settings()

    assert inputs.taylor_inputs.r_star == pytest.approx(float(settings.policy.r_star.value))
    assert inputs.taylor_inputs.output_gap == pytest.approx(2.22, abs=5e-3), (
        "output_gap rounds to 2dp (measured), so the fixture's +2.2222...% read back as 2.22"
    )
    assert inputs.taylor_inputs.pi_target is None


def test_the_first_difference_rule_gets_the_effective_policy_rate(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """``i_prev`` is the administered rate; the fixture's IORB is 4.0.

    The preference order is ``iorb > fed_funds_rate > sofr``, and the source
    note names which one answered — a reader who disagrees with the preference
    can see what was used rather than having to infer it.
    """
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)
    note = next(n for n in inputs.notes if n.name == "i_prev")

    assert inputs.first_difference_inputs.i_prev == pytest.approx(4.0)
    assert "iorb" in note.source


def test_the_policy_rate_falls_back_in_the_documented_order(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """IORB absent -> fed_funds_rate. The fallback is real, not decorative."""
    fallback = consistent_snapshot.model_copy(
        update={
            "iorb": [],
            "fed_funds_rate": consistent_snapshot.iorb,
        }
    )

    inputs = snapshot_to_thesis_inputs(fallback)
    note = next(n for n in inputs.notes if n.name == "i_prev")

    assert "fed_funds_rate" in note.source


def test_output_gap_change_is_a_difference_of_two_gaps(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """The momentum term is a change of gaps, not a gap.

    Hand calculation from the quarterly fixtures:
        at 2026-04-01: (23000 - 22500) / 22500 * 100 = +2.2222...%
        at 2026-01-01: (22500 - 22300) / 22300 * 100 = +0.89686...%
        change        = 2.2222... - 0.89686... = +1.32534...pp

    Subtracting a level from a change would make the rule report a policy path
    that does not exist, and the number would still be plausible.
    """
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)
    note = next(n for n in inputs.notes if n.name == "output_gap_change")

    expected = (23000.0 - 22500.0) / 22500.0 * 100.0 - (22500.0 - 22300.0) / 22300.0 * 100.0
    assert _note_float(note) == pytest.approx(expected, abs=1e-3)


def test_a_single_quarter_of_history_reports_no_momentum_rather_than_a_level(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """One same-quarter pair cannot yield a *change*; 0.0 is stated as "no momentum".

    This is the one derivation that degrades rather than refusing, and the
    distinction is deliberate: a missing earlier pair degrades one term whose
    weight is separate, whereas an empty series invalidates the whole read. The
    warning text must not let 0.0 read as a measured zero.
    """
    single = consistent_snapshot.model_copy(
        update={
            "gdp_real": consistent_snapshot.gdp_real[-1:],
            "gdp_potential": consistent_snapshot.gdp_potential[-1:],
        }
    )

    inputs = snapshot_to_thesis_inputs(single)
    note = next(n for n in inputs.notes if n.name == "output_gap_change")

    assert _note_float(note) == 0.0
    assert note.window is not None, "the note must carry the reason it reports 0.0"
    assert "0.0" in note.window
    assert "masquerading" in note.window


# ---------------------------------------------------------------------------
# 5. The refusals — every one of these is the module's actual purpose
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    ["cpi_headline", "cpi_core", "pce_core", "initial_claims", "jolts_openings", "jolts_quits"],
)
def test_an_empty_required_series_refuses(
    consistent_snapshot: MacroDataSnapshot, field: str
) -> None:
    """An absent series is not a zero (Section 21.4).

    Parametrised over all six so that a future refactor cannot make one of them
    default without this failing — which is exactly what a single ``cpi_core``
    test would allow.
    """
    broken = consistent_snapshot.model_copy(update={field: []})

    with pytest.raises(OrchestrationError) as caught:
        snapshot_to_thesis_inputs(broken)

    assert caught.value.fields == (field,)


def test_a_missing_yield_curve_refuses(consistent_snapshot: MacroDataSnapshot) -> None:
    broken = consistent_snapshot.model_copy(update={"yield_curve": None})

    with pytest.raises(OrchestrationError) as caught:
        snapshot_to_thesis_inputs(broken)

    assert caught.value.fields == ("yield_curve",)
    assert "no yield curve" in str(caught.value)


def test_all_three_policy_rates_absent_refuses(consistent_snapshot: MacroDataSnapshot) -> None:
    """Falling back to a literal rate would put an invented number in ``i_prev``."""
    broken = consistent_snapshot.model_copy(update={"iorb": [], "fed_funds_rate": [], "sofr": []})

    with pytest.raises(OrchestrationError) as caught:
        snapshot_to_thesis_inputs(broken)

    assert set(caught.value.fields) == {"iorb", "fed_funds_rate", "sofr"}


def test_a_curve_in_basis_points_refuses(consistent_snapshot: MacroDataSnapshot) -> None:
    """The units fault that produces a market-implied path of 430%.

    ``YieldCurveSnapshot`` documents percent. A bp value passes every type check
    and every validator, so the only thing that catches it is a plausibility
    range — and the range must be checked, not assumed.
    """
    curve = consistent_snapshot.yield_curve
    assert curve is not None
    broken_curve = YieldCurveSnapshot(
        as_of=curve.as_of,
        tenors={**curve.tenors, "2yr": 425.0},
    )
    broken = consistent_snapshot.model_copy(update={"yield_curve": broken_curve})

    with pytest.raises(OrchestrationError) as caught:
        snapshot_to_thesis_inputs(broken)

    assert "plausible bond range" in str(caught.value)


def test_the_yield_ceiling_is_taken_from_config_not_a_literal(
    consistent_snapshot: MacroDataSnapshot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-132 / D-031 — the ceiling must be READ, not re-typed.

    ``_short_yield_from_curve`` used to admit ``if not 0.0 < value < 25.0``: a
    bare literal that ALSO hardcoded "is 25.0" in its own message, a second
    definition of the very number ``data_layer/validation.py`` reads via
    ``validation.max_yield`` (leaf ``validation.max_plausible_yield_pct``).
    Two definitions of one bound drift silently.

    A *pinner* cannot tell a leaf-read from a re-typed literal: the fixture's
    2yr = 4.25 passes ``< 25.0`` under BOTH forms, and even 425.0 fails under
    both. The measurement that separates them is a **mover**: set the leaf to a
    value the shipped literal does NOT equal — 4.0 — and a 4.25 yield, which the
    shipped leaf admits, must now REFUSE. If the code still held ``25.0`` it
    would keep admitting and this test fails.
    """
    import macro_engine.api_layer.orchestration as module

    settings = get_settings()
    assert settings.validation.max_yield == pytest.approx(25.0), (
        "the shipped leaf moved; this mover's 4.0/4.25 split assumes 25.0"
    )
    # Baseline: the shipped leaf admits the fixture's 2yr = 4.25.
    snapshot_to_thesis_inputs(consistent_snapshot)

    def _patched(ceiling: float) -> object:
        moved_validation = settings.validation.model_copy(
            update={
                "max_plausible_yield_pct": (
                    settings.validation.max_plausible_yield_pct.model_copy(
                        update={"value": ceiling}
                    )
                )
            }
        )
        return settings.model_copy(update={"validation": moved_validation})

    # Move the leaf BELOW the fixture's 2yr: the same snapshot must now refuse.
    monkeypatch.setattr(module, "get_settings", lambda: _patched(4.0))
    with pytest.raises(OrchestrationError) as caught:
        snapshot_to_thesis_inputs(consistent_snapshot)

    assert caught.value.fields == ("yield_curve",)
    assert "plausible bond range" in str(caught.value), "the ceiling is not read from the leaf"


def test_a_curve_without_the_configured_tenor_refuses(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    broken_curve = YieldCurveSnapshot(as_of=date(2026, 9, 15), tenors={"10yr": 4.1})
    broken = consistent_snapshot.model_copy(update={"yield_curve": broken_curve})

    with pytest.raises(OrchestrationError) as caught:
        snapshot_to_thesis_inputs(broken)

    assert "no '2yr' tenor" in str(caught.value)


def test_a_fully_forward_dated_series_refuses(consistent_snapshot: MacroDataSnapshot) -> None:
    """O-7's discipline, applied to the API layer's own reads.

    A series whose every point is dated after the snapshot's ``as_of`` carries a
    projection block, not history. ``gdp_potential`` is the known instance; this
    proves the check is not special-cased to it.
    """
    future = date(2027, 6, 1)
    forward = [
        ObservationPoint(observation_date=future, value=100.0, series_id="cpi_core"),
    ]
    broken = consistent_snapshot.model_copy(update={"cpi_core": forward})

    with pytest.raises(OrchestrationError) as caught:
        snapshot_to_thesis_inputs(broken)

    assert "none dated on or before" in str(caught.value)


def test_a_foreign_country_raises_rather_than_relabelling(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """Section 22.3: ``country`` is a label, not a generalization.

    A US-shaped thesis with a ``de`` label is exactly the false-genericity claim
    the section forbids, so this is a ``NotImplementedError`` — the same class
    every other US-only function raises — rather than an ``OrchestrationError``,
    which would suggest a retry might succeed.
    """
    broken = consistent_snapshot.model_copy(update={"country": "de"})

    with pytest.raises(NotImplementedError):
        snapshot_to_thesis_inputs(broken)


def test_the_refusal_error_names_its_fields(consistent_snapshot: MacroDataSnapshot) -> None:
    """The API's error body must say WHICH input failed.

    "thesis unavailable" is not actionable; "pce_core is empty" is.
    """
    broken = consistent_snapshot.model_copy(update={"jolts_openings": []})

    with pytest.raises(OrchestrationError) as caught:
        snapshot_to_thesis_inputs(broken)

    assert caught.value.fields == ("jolts_openings",)
    assert "jolts_openings" in str(caught.value)


def test_orchestration_error_defaults_to_no_fields() -> None:
    """A raised-without-fields error still carries an empty tuple, not None.

    ``fields`` is read by the API's handler and formatted; ``None`` there would
    be a second failure on the error path.
    """
    error = OrchestrationError("something went wrong")

    assert error.fields == ()


# ---------------------------------------------------------------------------
# 6. The YoY anniversary tolerance — the defect this increment found
# ---------------------------------------------------------------------------


def test_a_yoy_prior_must_be_within_tolerance_of_the_anniversary(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """A ratio mislabelled as "year-over-year" is the defect, and it was measured.

    Removing the exact anniversary point leaves a candidate one month earlier.
    Before the tolerance guard existed, the orchestration **accepted this** and
    printed the two dates beside the words "year-over-year" — the number and its
    label disagreed and nothing said so. Measured on a real JTSJOL series during
    this increment's probe (``.probe/d070_refuse.py``, case 2), where a 20-point
    series was accepted with the ratio computed against an off-anniversary point.

    Hand calculation of the refusal: the anniversary is 2025-08-01; the closest
    observation at or before it, once the exact point is removed, is 2025-07-01,
    which is 31 days away — beyond the 5-day tolerance.
    """
    points = [
        p for p in consistent_snapshot.jolts_openings if p.observation_date != date(2025, 8, 1)
    ]
    broken = consistent_snapshot.model_copy(update={"jolts_openings": points})

    with pytest.raises(OrchestrationError) as caught:
        snapshot_to_thesis_inputs(broken)

    assert caught.value.fields == ("jolts_openings",)
    assert "beyond the" in str(caught.value)
    assert "tolerance" in str(caught.value)


def test_the_tolerance_admits_an_exact_anniversary(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """The permissive branch must stay permissive.

    A guard that refused everything would also pass the test above, so the
    acceptance case is asserted separately rather than assumed.
    """
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)
    note = next(n for n in inputs.notes if n.name == "jolts_openings_yoy_pct")

    assert note.window is not None
    assert "0 day(s) off the anniversary" in note.window


def test_the_tolerance_is_config_driven() -> None:
    """It is config, so it is reviewable and movable — not a literal in a compare."""
    settings = get_settings()

    assert settings.api.yoy_match_tolerance_days >= 1
    assert settings.api.yoy_match_tolerance_days < 28, (
        "a tolerance of 28+ days would admit a monthly series' neighbouring "
        "month, which is the mislabelled-YoY defect the guard exists to catch"
    )


# ---------------------------------------------------------------------------
# 7. Provenance — the notes are the part a reader cannot check from the thesis
# ---------------------------------------------------------------------------


def test_every_note_has_a_source(consistent_snapshot: MacroDataSnapshot) -> None:
    """A derivation note without its source is an assertion, not evidence."""
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)

    assert inputs.notes, "the orchestration must publish its derivations"
    for note in inputs.notes:
        assert isinstance(note, DerivationNote)
        assert note.source.strip(), f"{note.name} carries no source"


def test_the_notes_name_every_derived_argument(consistent_snapshot: MacroDataSnapshot) -> None:
    """Every argument the builder receives has a note explaining it.

    Not a completeness-for-its-own-sake check: the whole reason the notes exist
    is that a reviewer cannot reproduce the derivation from the thesis, so a
    derived argument that is absent here is one nobody can challenge.

    The list covers the six *required* arguments and the two optional reads. The
    optional pair is included deliberately: a degraded read writes a
    ``NOT_COMPUTED`` note, so the name must be present either way — a check that
    only listed the required arguments would stop noticing if an optional leg
    dropped its disclosure.
    """
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)
    names = {n.name for n in inputs.notes}

    for required in (
        "growth (output_gap)",
        "cpi_headline_mom",
        "cpi_core_mom",
        "pce_core_mom",
        "initial_claims_4wk_avg_change_pct",
        "jolts_openings_yoy_pct",
        "jolts_quits_level_percentile",
        "short_yield",
        "pi_current",
        "output_gap_change",
        "i_prev",
        "r_star",
        "thesis_type",
        # The optional reads. On this fixture both abstain, and each still
        # writes its note — which is the property worth pinning.
        "regime",
        "gdp_gdi_divergence",
        # The curve reads produce one note per model regardless of outcome.
        "curve_slope",
        "breakeven_inflation",
    ):
        assert required in names, f"no derivation note for {required!r}"


def test_the_growth_note_reports_the_withheld_projection_points(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """The O-7 disclosure travels from the adapter into the note."""
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)
    note = next(n for n in inputs.notes if n.name == "growth (output_gap)")

    assert note.window is not None
    assert "withheld" in note.window


def test_r_star_is_labelled_unobservable(consistent_snapshot: MacroDataSnapshot) -> None:
    """``r*``'s provenance matters more than its value (Section 22.8).

    ``r*`` is unobservable, which is why the confidence rule has a penalty for
    depending on it. A note reading only "0.5" invites it to be treated as a
    measurement.
    """
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)
    note = next(n for n in inputs.notes if n.name == "r_star")

    assert "UNOBSERVABLE" in note.source


# ---------------------------------------------------------------------------
# 8. Strictness — the guards that keep the module honest
# ---------------------------------------------------------------------------


def test_no_hardcoded_economic_literal_reaches_the_derivation() -> None:
    """The module must contain no economic constant as a bare literal.

    The failure this guards is ``live_builder_check.py``'s: four numbers typed
    into a call site because no snapshot-fed helper produced them. Every
    threshold here is config-derived, so the check is that the module *reads*
    config in the places it must.

    Implemented with ``ast`` rather than a text search — lesson 5bf: a text
    assertion pins spelling, and a formatter or a rename would break it while
    the defect returned intact.
    """
    import ast
    import pathlib

    source = pathlib.Path("src/macro_engine/api_layer/orchestration.py").read_text("utf-8")
    tree = ast.parse(source)

    config_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "get_settings"
    ]
    assert len(config_calls) >= 3, (
        f"expected the derivation to read config in at least 3 places "
        f"(quits window, r*, YoY tolerance); found {len(config_calls)}"
    )


def test_the_module_refuses_rather_than_defaulting_on_a_required_series() -> None:
    """Structural: every series conversion raises before it computes.

    A behavioural test can only cover the series a fixture happens to empty.
    This asserts the *shape* — that the conversion helpers exist and each raises
    ``OrchestrationError`` — so a new helper added without a refusal is visible.

    ``ast`` rather than a text match, for the reason above.
    """
    import ast
    import pathlib

    source = pathlib.Path("src/macro_engine/api_layer/orchestration.py").read_text("utf-8")
    tree = ast.parse(source)

    helpers = {
        "_require",
        "_realised",
        "_mom_percent",
        "_yoy_percent",
        "_trailing_percentile",
        "_claims_4wk_change",
        "_policy_rate",
        "_short_yield_from_curve",
    }
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in helpers
    }
    assert defined == helpers, f"missing refusal helpers: {sorted(helpers - defined)}"

    for name in sorted(helpers):
        func = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == name
        )
        raises = [
            node
            for node in ast.walk(func)
            if isinstance(node, ast.Raise)
            and isinstance(node.exc, ast.Call)
            and getattr(node.exc.func, "id", None) == "OrchestrationError"
        ]
        assert raises, f"{name} does not raise OrchestrationError anywhere"


def test_no_bare_numeric_literal_is_used_as_a_threshold() -> None:
    """The economic thresholds are config, so the literals that remain are structural.

    ``0.0``/``1.0``/``2.0``/``100.0`` are unit conversions (a percent change, a
    ratio, a percentile scale), not judgments. Anything else would be a threshold
    a reviewer cannot find — so this pins the permitted set explicitly rather
    than allowing "some literals".
    """
    import ast
    import pathlib

    source = pathlib.Path("src/macro_engine/api_layer/orchestration.py").read_text("utf-8")
    tree = ast.parse(source)

    permitted = {0.0, 1.0, 2.0, 3.0, 4.0, 100.0, 25.0, 0.1, 10.0, 8.0}
    offenders: list[tuple[int, float]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, float)
            and node.value not in permitted
        ):
            offenders.append((node.lineno, node.value))

    assert not offenders, (
        f"unexpected float literals: {offenders}. A threshold that is not in "
        f"config is one a reviewer cannot find; add it to settings.yaml and read "
        f"it through get_settings() instead."
    )


# ---------------------------------------------------------------------------
# The regime read degrades rather than blocking the thesis
# ---------------------------------------------------------------------------


def _value_dict(result: ModelResult) -> dict[str, object]:
    """A ``ModelResult.value`` narrowed to the dict these tests expect.

    ``ModelResult.value`` is a union because different models publish different
    shapes. The national-accounts model is documented and tested to publish a
    dict, so the narrowing is asserted here once rather than cast or ignored at
    every use — a bare ``.value["key"]`` would be a runtime ``TypeError`` if the
    shape ever changed, which is what this makes explicit.
    """
    assert isinstance(result.value, dict)
    return result.value


def _without(snapshot: MacroDataSnapshot, field: str) -> MacroDataSnapshot:
    """A copy of ``snapshot`` with one series emptied.

    Emptied rather than deleted because the schema requires the field to exist:
    what is being modelled is a *fetch that returned no observations*, which is
    the shape Section 21.4 actually describes.
    """
    return snapshot.model_copy(update={field: []})


def test_an_absent_unemployment_rate_yields_a_thesis_not_an_error(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """The regime is a READ, not a gate — so a missing axis must not block.

    Measured while wiring ``_regime_leg``: the first version called ``_realised``,
    which raises on an empty series, and ``snapshot_to_thesis_inputs`` then
    raised ``OrchestrationError`` on any snapshot without ``unemployment_rate``.
    That inverts Section 16.2's order — the reads come *before* Q6's significance
    test, and Q6 is what stands a thesis down — and it contradicts the rule
    ``_output_gap_change`` states explicitly for the same situation
    ("refusing would make the whole thesis unavailable over a term Section 6.1
    weights separately").

    So the contract this pins is: an absent optional axis produces inputs with
    ``regime is None``, a derivation note that says NOT_COMPUTED, and nothing
    raised.
    """
    inputs = snapshot_to_thesis_inputs(_without(consistent_snapshot, "unemployment_rate"))
    assert inputs.regime is None
    note = next(n for n in inputs.notes if n.name == "regime")
    assert note.value == "NOT_COMPUTED"
    assert "unemployment_rate" in note.source


def test_an_absent_cpi_headline_refuses_in_the_policy_leg_not_the_regime_leg(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """CPI absence IS fatal, but the refusal must come from the policy leg.

    A deliberate contrast with the test above rather than another copy of it.
    ``cpi_headline`` is not optional: ``_inflation_leg`` computes ``pi_current``
    for both policy rules from it, so with no CPI there is no policy gap and no
    thesis — the refusal is correct and must stay.

    What this pins is *where* it comes from. The regime's inflation guard must
    not be what fires, because that would mean the regime leg had become load-
    bearing for a quantity the thesis needs independently — the coupling the
    test above exists to prevent. Measured: this raises from ``_inflation_leg``
    before ``_regime_leg`` is reached, which is the ordering Section 16.2
    specifies.
    """
    with pytest.raises(OrchestrationError) as caught:
        snapshot_to_thesis_inputs(_without(consistent_snapshot, "cpi_headline"))
    assert "cpi_headline" in str(caught.value)
    # An empty series refuses earlier than a too-short one and says so — the
    # distinction matters, because "no observations at all" and "not enough for
    # a year-over-year" have different remedies (widen the lookback vs fix the
    # fetch), and the message is the only thing that tells a reader which.
    assert "is empty" in str(caught.value)


def test_a_short_cpi_history_refuses_in_the_policy_leg_not_the_regime_leg(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """Three CPI observations also fail the policy leg first, for the same reason.

    ``_inflation_momentum_3m`` needs four observations. The regime leg guards
    that; the policy leg does not, because the momentum term feeds a rule there.
    Reaching the policy leg's raise proves the guard ordering is the specified
    one rather than the regime leg silently absorbing a fatal input error.
    """
    short = consistent_snapshot.model_copy(
        update={"cpi_headline": consistent_snapshot.cpi_headline[:3]}
    )
    with pytest.raises(OrchestrationError) as caught:
        snapshot_to_thesis_inputs(short)
    assert "cpi_headline" in str(caught.value)


def test_a_present_regime_is_classified_and_its_warnings_ride_along(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """The non-degraded path still classifies, and still carries its warnings.

    The counterpart to the three tests above: a guard that returned ``None``
    unconditionally would satisfy them and fail this one. ``unemployment_rate``
    is added here because the shared fixture omits it.
    """
    with_unrate = consistent_snapshot.model_copy(
        update={"unemployment_rate": _monthly([4.0, 4.1, 4.2], series_id="unemployment_rate")}
    )
    inputs = snapshot_to_thesis_inputs(with_unrate)
    assert inputs.regime is not None
    assert isinstance(inputs.regime.value, dict)
    assert inputs.regime.value.get("state") is not None
    # The classifier's caveats are exactly what a reader needs to interpret the
    # label, so they must reach the caller rather than being dropped at the seam.
    assert inputs.regime.warnings


# ---------------------------------------------------------------------------
# Module 7.1's national-accounts divergence: wired, and degrading
# ---------------------------------------------------------------------------


def test_absent_gdp_nominal_leaves_the_divergence_uncomputed(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """No expenditure-side series means no pair — disclosed, not raised.

    The fixture carries neither ``gdp_nominal`` nor ``gdi``, so this is also the
    test that every other orchestration test has been exercising silently.
    """
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)
    assert inputs.national_accounts is None
    note = next(n for n in inputs.notes if n.name == "gdp_gdi_divergence")
    assert note.value == "NOT_COMPUTED"
    assert "empty" in note.source


def test_a_same_quarter_pair_produces_the_divergence_on_a_growth_basis(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """The unit contract: two YoY **growth rates**, differenced — not two levels.

    ``GdpGdiInputs`` takes growth rates, and the model's docstring is explicit
    that a caller passing levels would compute a quantity dominated by BEA's
    construction asymmetry while the model's warnings describe the mean-zero
    residual. Two anonymous floats cannot reveal that mistake, so this test is
    the only thing standing between the wiring and that defect.

    The numbers are chosen so the expectation is checkable by hand: with a
    year-ago level of 100 and a latest of 110, growth is exactly ``+10%``.
    """
    five_quarters = [100.0, 100.0, 100.0, 100.0, 110.0]
    with_pair = consistent_snapshot.model_copy(
        update={
            "gdp_nominal": _quarterly(five_quarters, series_id="gdp_nominal"),
            "gdi": _quarterly([100.0, 100.0, 100.0, 100.0, 115.0], series_id="gdi"),
        }
    )
    inputs = snapshot_to_thesis_inputs(with_pair)
    assert inputs.national_accounts is not None

    value = _value_dict(inputs.national_accounts)
    assert value["gdp_growth_pct"] == pytest.approx(10.0)
    assert value["gdi_growth_pct"] == pytest.approx(15.0)
    # GDP minus GDI, in percentage points — the signed difference of the two
    # growth rates, which is the whole quantity Module 7.1 reports.
    assert value["divergence_pp"] == pytest.approx(-5.0)
    # The average is named `average_growth_pct`, deliberately not `average`:
    # averaging is only valid for the growth form, and the name is what stops
    # a reader transferring it to levels.
    assert value["average_growth_pct"] == pytest.approx(12.5)

    note = next(n for n in inputs.notes if n.name == "gdp_gdi_divergence")
    assert "growth" in note.source


def test_the_divergence_never_reads_a_mismatched_quarter(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """A pair is same-quarter or it is not formed.

    This is Section 20.7's pairing requirement, and the failure it prevents is
    specific: differencing two quarters that are not a year apart measures a
    statistical discrepancy **plus** one quarter of growth, which is a number
    that looks like a divergence and is not one.

    The fixture is built to separate the two candidate implementations, which a
    naiver version of this test did **not** do. A five-quarter series ending
    2026-04 spans 2025-04 .. 2026-04, so its *earliest* observation happens to
    be the year-ago one — meaning "take the first point" and "look up the
    year-ago point" agree, and a test built on it passes either way (measured:
    a first draft asserted ``+10%`` here and got ``+120%``, because the two
    hypotheses were not actually distinguishable).

    So this fixture makes them differ. The series is 2024-10 .. 2026-04, and the
    year-ago level is deliberately *between* two observations' dates: the lookup
    must land on the latest quarter at or before the anniversary, not on the
    first quarter in the series.
    """
    # Dates: 2024-10(90), 2025-01(95), 2025-04(100), 2025-07(100),
    #        2025-10(100), 2026-01(100), 2026-04(110)
    levels = [90.0, 95.0, 100.0, 100.0, 100.0, 100.0, 110.0]
    with_pair = consistent_snapshot.model_copy(
        update={
            "gdp_nominal": _quarterly(levels, series_id="gdp_nominal"),
            "gdi": _quarterly(levels, series_id="gdi"),
        }
    )
    inputs = snapshot_to_thesis_inputs(with_pair)
    assert inputs.national_accounts is not None

    # The anniversary of 2026-04 is 2025-04, whose level is 100.0, so growth is
    # 110/100 - 1 = +10%. Taking the FIRST observation (90.0) instead would give
    # +22.2%, and skipping to the nearest later quarter would alter it again —
    # both are wrong, and only a lookup answers +10%.
    assert _value_dict(inputs.national_accounts)["gdp_growth_pct"] == pytest.approx(10.0)
    note = next(n for n in inputs.notes if n.name == "gdp_gdi_divergence")
    assert note.window is not None
    assert "2025-04-01" in note.window
    assert "2024-10-01" not in note.window


def test_a_series_too_short_for_a_year_over_year_pair_abstains(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """Three quarters cannot contain a year-ago quarter, so nothing is computed."""
    short = consistent_snapshot.model_copy(
        update={
            "gdp_nominal": _quarterly([100.0, 100.0, 110.0], series_id="gdp_nominal"),
            "gdi": _quarterly([100.0, 100.0, 110.0], series_id="gdi"),
        }
    )
    inputs = snapshot_to_thesis_inputs(short)
    assert inputs.national_accounts is None
    note = next(n for n in inputs.notes if n.name == "gdp_gdi_divergence")
    assert note.value == "NOT_COMPUTED"


def test_the_divergence_carries_its_warnings_and_base_rate(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """The model's corrections must reach the reader, not stop at the seam.

    Module 7.1 defends six corrections; the two a consumer is most likely to
    undo are that the SIGN carries no information and that averaging is only
    valid on a growth basis. Both are carried as warnings, and the base rate
    travels on the value dict so a boolean is never read without its frequency
    (D-029).
    """
    with_pair = consistent_snapshot.model_copy(
        update={
            "gdp_nominal": _quarterly([100.0, 100.0, 100.0, 100.0, 110.0], series_id="gdp_nominal"),
            "gdi": _quarterly([100.0, 100.0, 100.0, 100.0, 106.0], series_id="gdi"),
        }
    )
    inputs = snapshot_to_thesis_inputs(with_pair)
    assert inputs.national_accounts is not None
    assert inputs.national_accounts.warnings
    assert _value_dict(inputs.national_accounts)["divergence_base_rate"] == pytest.approx(0.217)


# ---------------------------------------------------------------------------
# Modules 8.1/8.2: the curve reads, and the tenor vocabulary seam
# ---------------------------------------------------------------------------


def test_the_config_tenor_maps_onto_the_curves_own_vocabulary() -> None:
    """``2y`` (config, for instrument names) -> ``2yr`` (the curve's key).

    This is the defect the wiring exposed, and it is worth stating precisely
    because neither vocabulary is wrong:

    * ``settings.instrument_selection.curve_default_short_tenor`` is ``2y``, and
      that spelling is CORRECT for its purpose — it is interpolated into
      ``"Duration-weighted 2y/10y UST steepener"``, which is how a desk writes
      it. ``D-058`` recorded these strings are "never parsed", which was true
      only because nothing had ever compared them to curve data.
    * The snapshot's ``yield_curve.tenors`` is keyed ``2yr``, from the registry's
      ``2yr: DGS2`` and FRED's own spelling, and ``validation.py`` reads
      ``tenors["2yr"]``.

    Measured before the mapping existed: feeding the config label straight to
    ``curve_slope`` raised ``KeyError: short tenor '2y' is not in the supplied
    curve``. Changing either side instead would have broken the instrument name
    or the validation layer.
    """
    available = {"3mo": 4.6, "2yr": 4.25, "10yr": 4.1, "30yr": 4.5}
    assert _config_tenor_for("2y", available) == "2yr"
    assert _config_tenor_for("10y", available) == "10yr"
    assert _config_tenor_for("30y", available) == "30yr"
    # An exact match is not second-guessed: a caller already speaking the
    # curve's vocabulary must get its own label back, not a transformation.
    assert _config_tenor_for("2yr", available) == "2yr"
    # No unambiguous mapping -> None, so the caller abstains. A guessed tenor is
    # a wrong number, which is worse than a missing one.
    assert _config_tenor_for("9y", available) is None
    assert _config_tenor_for("6m", available) is None


def test_the_curve_slope_is_the_configured_pair_in_basis_points(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """The slope is long-minus-short on the configured pair, and it is NEGATIVE here.

    The fixture's curve is inverted (10yr 4.1 < 2yr 4.25), so this also pins that
    the sign convention is not silently flipped: ``(10yr - 2yr) * 100 = -15.0bp``,
    which ``curve_slope`` must report as ``inverted``.
    """
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)
    slope = next(r for r in inputs.curve if r.model_name == "curve_slope")

    assert slope.value == pytest.approx(-15.0)
    assert "inverted" in slope.interpretation
    # The labels in the interpretation are the CURVE's, not the config's -- the
    # whole point of the mapping, and the thing a reader sees.
    assert "10YR" in slope.interpretation
    assert "2YR" in slope.interpretation


def test_every_matched_tenor_gets_a_breakeven_and_unmatched_ones_do_not(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """A breakeven needs the SAME tenor on both curves, or it prices the slope.

    The fixture's nominal curve carries 3mo/1yr/2yr/10yr/30yr; giving TIPS only
    10yr and 30yr must produce exactly two breakevens — not five, and not one
    computed from a mismatched maturity.
    """
    with_tips = consistent_snapshot.model_copy(
        update={
            "tips_yields": YieldCurveSnapshot(
                as_of=date(2026, 9, 15),
                tenors={"10yr": 1.8, "30yr": 2.1},
            )
        }
    )
    inputs = snapshot_to_thesis_inputs(with_tips)
    breakevens = [r for r in inputs.curve if r.model_name == "breakeven_inflation"]

    assert len(breakevens) == 2
    by_tenor = {t: r.value for t, r in zip(("10yr", "30yr"), breakevens, strict=True)}
    # 10yr: 4.1 - 1.8 = 2.3 ; 30yr: 4.5 - 2.1 = 2.4
    assert by_tenor["10yr"] == pytest.approx(2.3)
    assert by_tenor["30yr"] == pytest.approx(2.4)

    note = next(n for n in inputs.notes if n.name == "breakeven_inflation")
    assert "10yr" in str(note.window)
    assert "2yr" not in str(note.window)


def test_an_absent_tips_curve_leaves_the_breakevens_uncomputed(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """No TIPS curve means no breakeven — disclosed, and the slope still runs.

    The two reads are independent, which is why the leg returns a list: a missing
    real curve must not suppress the nominal slope.
    """
    assert consistent_snapshot.tips_yields is None
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)

    assert any(r.model_name == "curve_slope" for r in inputs.curve)
    assert not any(r.model_name == "breakeven_inflation" for r in inputs.curve)
    note = next(n for n in inputs.notes if n.name == "breakeven_inflation")
    assert note.value == "NOT_COMPUTED"


def test_an_absent_curve_refuses_in_the_short_yield_leg_not_the_curve_leg(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """A snapshot with NO curve is already fatal — and the refusal predates the curve leg.

    A deliberate contrast with the other curve tests rather than another copy of
    them. The curve *slope* degrades gracefully, but the **short yield** does not:
    ``_short_yield_from_curve`` runs earlier (``snapshot_to_thesis_inputs`` line
    ~1531 vs the curve leg at ~1598) and a policy-path thesis cannot be built
    without it, because ``derive_market_implied_policy_path`` reads it.

    So "no curve at all" is not a case the curve leg ever sees. What this pins is
    **where** the refusal comes from — if the curve leg were reached first, the
    ordering would have changed and the short yield would silently fall back.
    """
    without = consistent_snapshot.model_copy(update={"yield_curve": None})
    with pytest.raises(OrchestrationError) as caught:
        snapshot_to_thesis_inputs(without)
    assert "no yield curve" in str(caught.value)


def test_a_curve_missing_the_short_yield_tenor_refuses_before_the_curve_leg(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """A curve without the configured short tenor is refused by the short-yield leg.

    The curve leg would abstain here (``_config_tenor_for`` returns ``None``), but
    it never gets the chance: the short-yield read needs ``api.short_yield_tenor``
    and names the available tenors when it is absent. That is the correct failure
    — a policy path priced off a substituted tenor would be a different thesis —
    and the error message names the config key so the remedy is visible.

    Measured: this raises before ``_curve_leg`` is reached, which is why the
    abstention path in ``_curve_leg`` is exercised by the test below rather than
    by a malformed curve.
    """
    odd = YieldCurveSnapshot(
        as_of=date(2026, 9, 15),
        tenors={"3mo": 4.6, "1yr": 4.5},
    )
    without = consistent_snapshot.model_copy(update={"yield_curve": odd})
    with pytest.raises(OrchestrationError) as caught:
        snapshot_to_thesis_inputs(without)
    assert "2yr" in str(caught.value)
    assert "api.short_yield_tenor" in str(caught.value)


def test_the_curve_leg_abstains_when_its_long_tenor_is_unmappable(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """With the short tenor satisfied, an unmappable LONG leg makes the slope abstain.

    This is the branch the two refusal tests above cannot reach, and it is the one
    that matters: the curve leg must **abstain**, not substitute. Substituting
    ``3yr`` for a missing ``10y`` would produce a slope that looks right and
    answers a different question.

    The curve here carries ``2yr`` (so the short-yield leg is satisfied) but no
    ``10yr`` and nothing ``_config_tenor_for`` can map to it.
    """
    partial = YieldCurveSnapshot(
        as_of=date(2026, 9, 15),
        tenors={"3mo": 4.6, "2yr": 4.25, "5yr": 4.3},
    )
    without = consistent_snapshot.model_copy(update={"yield_curve": partial})
    inputs = snapshot_to_thesis_inputs(without)

    assert not any(r.model_name == "curve_slope" for r in inputs.curve)
    note = next(n for n in inputs.notes if n.name == "curve_slope")
    assert note.value == "NOT_COMPUTED"
    assert "not a key on the live curve" in note.source


# ---------------------------------------------------------------------------
# Module 4.1 — the balance-sheet leg (D-085)
# ---------------------------------------------------------------------------
#
# ``qe_qt_stance`` had NO caller in ``src/`` before this increment: it was
# reachable only from ``tests/models/test_policy_rules.py`` and
# ``scripts/live_labor_check.py``, so no thesis carried a balance-sheet read and
# Section 22.11's QT/repo-stress chain had no live input. The leg below closes
# that, and these tests pin the four things that can silently go wrong:
#
#   1. the 13-RESULT window is weekly rows, not a calendar subtraction;
#   2. the units are MILLIONS for WALCL/WRESBAL and BILLIONS for RRPONTSYD, and
#      the leg refuses a 1000x mismatch rather than classifying on it;
#   3. an absent balance sheet abstains with a NOT_COMPUTED note rather than
#      substituting zero (which would divide by zero or read as full expansion);
#   4. an absent RRP buffer degrades the scarcity disclosure, not the stance.


def test_balance_sheet_leg_classifies_from_the_snapshot(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """The fixture's round numbers produce QE_EXPANDING by hand arithmetic.

    assets 6,700,000 -> 6,750,000 over thirteen weekly rows is +50,000mn, and
    50,000 / 6,750,000 * 100 = **+0.740740...%**, which is above the `qe_qt`
    neutral band, so the stance is QE_EXPANDING. Reserves fall 50,000mn over the
    same window, so the direct-reserve-drain disclosure must be present — but
    only *with* QT, which is the branch that must NOT fire here.
    """
    inputs = snapshot_to_thesis_inputs(consistent_snapshot)

    assert inputs.balance_sheet is not None, "the leg abstained on a full snapshot"
    value = inputs.balance_sheet.value
    assert isinstance(value, dict)
    assert value["stance"] == "QE_EXPANDING"
    assert _model_float(value["balance_sheet_change_3mo"]) == pytest.approx(50_000.0)
    # ``qe_qt_stance`` publishes ``balance_sheet_change_pct`` rounded to FOUR
    # decimal places (see the ``round(change_pct, 4)`` in the model's value
    # dict), so the published precision — not full float precision — is what the
    # leg's output is allowed to carry. Asserting at ``rel=1e-6`` against the
    # unrounded quotient fails on 0.7407 vs 0.7407407407407408: the leg is
    # correct and the assertion was wrong. Pin the rounding contract instead, so
    # a future change that silently drops digits still fails here.
    assert _model_float(value["balance_sheet_change_pct"]) == round(
        50_000.0 / 6_750_000.0 * 100.0, 4
    )
    assert value["on_rrp_supplied"] is True

    note = next(n for n in inputs.notes if n.name == "qe_qt_stance")
    assert note.value == "QE_EXPANDING"
    # The window is 13 WEEKLY rows: 2026-06-13 -> 2026-09-12 given the fixture's
    # weekly helper. Asserting the note names both endpoints keeps the offset
    # auditable rather than implied.
    assert "13 weeks" in (note.window or "")


def test_balance_sheet_leg_refuses_a_units_swap(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """A 1000x unit error must refuse, not classify.

    WALCL in BILLIONS reads ~6,750 instead of ~6,750,000. The relative change is
    unaffected by a uniform scale, so the *stance* would come out identical while
    every published magnitude is wrong by 1000x — the exact failure mode the
    guard exists for. The expectation is a refusal naming the field.
    """
    swapped = consistent_snapshot.model_copy(
        update={
            "fed_total_assets": _weekly(
                [6_700.0, *[6_720.0] * 12, 6_750.0], series_id="fed_total_assets"
            )
        }
    )
    with pytest.raises(OrchestrationError, match="fed_total_assets"):
        snapshot_to_thesis_inputs(swapped)


def test_balance_sheet_leg_refuses_assets_below_reserves(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """The cross-series check: total assets must exceed reserves.

    Catches the two series being mapped to each other's symbols, which is
    otherwise invisible because both are plausible millions figures.
    """
    crossed = consistent_snapshot.model_copy(
        update={
            "fed_total_assets": _weekly(
                [3_000_000.0, *[3_010_000.0] * 12, 3_020_000.0],
                series_id="fed_total_assets",
            ),
            "reserve_balances": _weekly(
                [6_700_000.0, *[6_720_000.0] * 12, 6_750_000.0],
                series_id="reserve_balances",
            ),
        }
    )
    with pytest.raises(OrchestrationError, match="not above reserves"):
        snapshot_to_thesis_inputs(crossed)


def test_balance_sheet_leg_abstains_when_the_series_are_absent(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """No data -> NOT_COMPUTED, never a zero-substituted stance.

    A zero level would make the relative change divide by zero; a zero *change*
    would read as NEUTRAL_HOLD, which is a fabricated verdict rather than a
    disclosed absence. The expectation is the abstention plus its note.
    """
    empty = consistent_snapshot.model_copy(update={"fed_total_assets": [], "reserve_balances": []})
    inputs = snapshot_to_thesis_inputs(empty)

    assert inputs.balance_sheet is None
    note = next(n for n in inputs.notes if n.name == "qe_qt_stance")
    assert note.value == "NOT_COMPUTED"
    assert "Section 21.4" in note.source


def test_balance_sheet_leg_abstains_on_too_short_a_window(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """Thirteen rows cannot yield a thirteen-week change; thirteen is needed.

    The boundary is inclusive of the change window, so 13 common rows is one
    short and 14 is the minimum. Feeding exactly 13 pins the ``<=`` rather than
    letting an off-by-one through as a one-week-short change.
    """
    short = consistent_snapshot.model_copy(
        update={
            "fed_total_assets": _weekly([6_700_000.0] * 13, series_id="fed_total_assets"),
            "reserve_balances": _weekly([3_050_000.0] * 13, series_id="reserve_balances"),
        }
    )
    inputs = snapshot_to_thesis_inputs(short)

    assert inputs.balance_sheet is None
    note = next(n for n in inputs.notes if n.name == "qe_qt_stance")
    assert note.value == "NOT_COMPUTED"
    assert "at least 14" in note.source


def test_balance_sheet_leg_discloses_a_missing_rrp_buffer(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """A missing ON-RRP buffer degrades the disclosure, not the stance.

    ``BalanceSheetInputs.on_rrp_level`` is optional by the model's own signature
    because the stance is decidable without it — but ``rrp_drained`` is then
    unknown, and the leg must say so rather than let the model's scarcity
    warning imply a buffer it never read.
    """
    without_rrp = consistent_snapshot.model_copy(update={"on_rrp_volume_bn": []})
    inputs = snapshot_to_thesis_inputs(without_rrp)

    assert inputs.balance_sheet is not None
    value = inputs.balance_sheet.value
    assert isinstance(value, dict)
    assert value["on_rrp_supplied"] is False
    assert value["on_rrp_level"] is None

    note = next(n for n in inputs.notes if n.name == "qe_qt_rrp_buffer")
    assert note.value == "NOT_AVAILABLE"


def test_balance_sheet_leg_measures_thirteen_rows_back_not_to_the_first_row(
    consistent_snapshot: MacroDataSnapshot,
) -> None:
    """The 13-week window must be the *offset*, and only a bent fixture can prove it.

    The ``consistent_snapshot`` fixture is a straight line whose early values are
    identical to its recent ones, so a regression that paired the latest week
    against ``common[0]`` instead of ``common[-14]`` would publish the *same*
    change and pass every assertion above — the "13 weeks" string is built from
    ``window_weeks`` and never from ``prior_week``, so it cannot catch it. This
    mutation was tried: swapping in ``common[0]`` left all six sibling tests
    green. The guard was fine; the fixture was too flat to see the defect.

    So give the series a shape the offset can be read off: a **strictly
    increasing** balance sheet longer than the window. The length matters and is
    the part that is easy to get wrong — with a series of exactly 14 rows,
    ``common[-1 - 13]`` *is* ``common[0]``, so the correct offset and the naive
    ``common[0]`` pairing are the same date and no assertion can separate them.
    Twenty rows put the correct prior week in the middle of the series, so any
    other offset names a different date and therefore a different change.
    """
    # 20 rows, strictly increasing by 10,000mn: rows 0..19 read 6,300,000 ..
    # 6,490,000. The correct 13-row window is row 6 -> row 19:
    #   6,490,000 - 6,360,000 = +130,000mn.
    # The naive common[0] pairing would report 6,490,000 - 6,300,000 = +190,000mn,
    # so the two readings differ by a clearly non-round number of millions.
    assets = [6_300_000.0 + 10_000.0 * index for index in range(20)]
    bent = consistent_snapshot.model_copy(
        update={
            "fed_total_assets": _weekly(assets, series_id="fed_total_assets"),
            "reserve_balances": _weekly([3_050_000.0] * 20, series_id="reserve_balances"),
        }
    )
    inputs = snapshot_to_thesis_inputs(bent)

    assert inputs.balance_sheet is not None
    value = inputs.balance_sheet.value
    assert isinstance(value, dict)
    # exactly row19 - row6, which is the 13-row offset into a 20-row series
    assert _model_float(value["balance_sheet_change_3mo"]) == pytest.approx(130_000.0)
    # and the window's own endpoints name those two rows — an off-by-one offset
    # or a common[0] pairing reports a different pair and fails here.
    note = next(n for n in inputs.notes if n.name == "qe_qt_stance")
    assert "6,360,000 -> 6,490,000mn" in note.source
    assert "6,300,000" not in note.source
    assert (note.window or "").endswith("(13 weeks, +130,000mn)"), note.window
