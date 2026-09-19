"""The reasoning-object contract (economic-integrity directive Sections 3-4).

Section 3's requirement is that a model returns a *reasoning object* rather
than a number wearing prose, and Section 4 enumerates the fields that object
must be able to carry. The fields are additive and all default to an honest
"not supplied", and the tests here pin the two properties that make that
defaulting safe rather than merely convenient:

1. **Absence is visible.** A model that declares no unit reports ``unit=None``,
   which a consumer must read as *unknown* — never as *dimensionless*. Same for
   ``direction`` and ``decision_relevance``; a missing justification must look
   missing, not look complete.
2. **The prohibitions are real.** ``decision_prohibition`` is a list a consumer
   is expected to act on, so a result that carries one must round-trip it
   unchanged through serialization rather than have it dropped.

The second test class is the one that would catch a future regression: adding a
field to ``ModelResult`` and then constructing instances positionally, or
redeclaring ``extra="forbid"`` as ``ignore``, would silently start discarding
whatever a model tried to say.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from macro_engine.models.contracts import ModelResult


def _result(**overrides: object) -> ModelResult:
    """A minimal valid result, so each test varies exactly one thing."""
    base: dict[str, object] = {
        "model_name": "unit_test_model",
        "country": "us",
        "as_of": datetime(2026, 9, 19, 16, 28, tzinfo=UTC),
        "value": 4.72,
        "confidence": 0.5,
        "interpretation": "a value, interpreted",
        "context": "vs a comparison point",
        "inputs_used": ["cpi_headline"],
    }
    base.update(overrides)
    return ModelResult(**base)  # type: ignore[arg-type]


class TestAbsenceIsVisible:
    """Every new field defaults to 'not supplied', never to a plausible fill."""

    def test_unit_direction_and_relevance_default_to_none(self) -> None:
        r = _result()
        assert r.unit is None, "an undeclared unit must read as UNKNOWN, not dimensionless"
        assert r.direction is None
        assert r.decision_relevance is None

    def test_the_list_fields_default_to_empty_not_to_a_placeholder(self) -> None:
        r = _result()
        assert r.assumptions == []
        assert r.data_provenance == []
        assert r.limitations == []
        assert r.decision_prohibition == []
        assert r.source_families == []
        assert r.observation_dates == {}
        assert r.release_dates == {}
        assert r.vintage_dates == {}

    def test_release_dates_empty_is_a_true_statement_of_unavailability(self) -> None:
        """Section 6: no reachable route returns release dates.

        The empty dict is therefore a *claim about the data source*, and the
        contract must distinguish it from a model that merely forgot. The way it
        does so is that the field ALWAYS exists — a caller can read it and learn
        that the information is absent, rather than getting an AttributeError and
        concluding it was never asked for.
        """
        r = _result()
        assert isinstance(r.release_dates, dict)
        assert r.release_dates == {}, "measured: no route returns release dates"

    def test_retrieved_at_defaults_to_none_and_is_distinct_from_as_of(self) -> None:
        """`as_of` is when the COMPUTATION ran; `retrieved_at` is when data was read."""
        r = _result()
        assert r.retrieved_at is None
        assert r.as_of is not None
        # Retroactively claiming the data was read when the model ran is exactly
        # the conflation this field exists to prevent, so it must stay None
        # unless a caller threaded a real value through.
        assert r.retrieved_at != r.as_of


class TestProhibitionsAndProvenance:
    """The populated path: fields carry content unchanged and survive a round-trip."""

    def test_decision_prohibition_round_trips_unchanged(self) -> None:
        """A prohibition a consumer is meant to obey must not be dropped in transit."""
        prohibitions = [
            "MUST NOT be traded — this is a PROXY, not an observed market price",
            "MUST NOT be sized — the scenario distribution is uncalibrated",
        ]
        r = _result(decision_prohibition=prohibitions, unit="bp", direction="restrictive")
        assert r.decision_prohibition == prohibitions
        assert r.unit == "bp"
        assert r.direction == "restrictive"

        restored = ModelResult.model_validate_json(r.model_dump_json())
        assert restored.decision_prohibition == prohibitions
        assert restored.unit == "bp"

    def test_source_families_accepts_the_typed_plural_set(self) -> None:
        """`source_families` is the set a conclusion rests on, not just its own tag."""
        r = _result(source_families=["bls_cpi", "treasury_official"])
        assert set(r.source_families) == {"bls_cpi", "treasury_official"}
        assert len(r.source_families) == 2
        # And the singular provenance tag stays independent.
        assert r.source_family is None

    def test_source_families_rejects_an_invented_family(self) -> None:
        """The vocabulary is closed: a family must be one the registry actually tags.

        This is the guard against the plural field becoming a free-text dumping
        ground, which would quietly defeat Section 5.17's independence count —
        two strings that mean the same independent source would count as two.
        """
        with pytest.raises(ValidationError):
            _result(source_families=["market_pricing"])

    def test_observation_dates_maps_field_to_iso_date(self) -> None:
        """Section 4: a reader must be able to see which vintage each input is."""
        r = _result(
            observation_dates={
                "cpi_headline": "2026-08-01",
                "unemployment_rate": "2026-09-01",
            },
            limitations=["rule-based, so it partitions but does not estimate"],
        )
        assert r.observation_dates["cpi_headline"] < r.observation_dates["unemployment_rate"]
        assert "partitions" in r.limitations[0]

    def test_assumptions_are_claims_not_comforts(self) -> None:
        r = _result(assumptions=["the projected path is the CBO baseline, not a policy forecast"])
        assert len(r.assumptions) == 1
        assert "CBO baseline" in r.assumptions[0]


class TestContractDiscipline:
    """Properties that would let a future edit silently start dropping reasoning."""

    def test_extra_fields_are_still_forbidden(self) -> None:
        """`extra="forbid"` is what makes a typo a loud failure rather than a silent drop.

        If this were relaxed to "ignore", a model could pass
        ``decision_prohitibion=`` and have its prohibition vanish with no error —
        the exact class of silent loss Sections 3-4 exist to prevent.
        """
        with pytest.raises(ValidationError):
            _result(decision_prohitibion=["typo'd key"])

    def test_the_reasoning_fields_are_all_optional(self) -> None:
        """Adding them must not have made any existing construction site fail.

        The whole point of defaulting every field is that the ~77 existing model
        call sites keep working untouched. If one of these fields had been made
        required, this minimal construction would raise — and so would every
        model in the tree.
        """
        required_by_contract = {
            "model_name",
            "country",
            "as_of",
            "value",
            "confidence",
            "interpretation",
            "context",
            "inputs_used",
        }
        _result()  # raises if any newly-added field had been made required
        for name in ModelResult.model_fields:
            if name in required_by_contract:
                continue
            assert ModelResult.model_fields[name].is_required() is False, (
                f"{name} must be optional so existing call sites do not break"
            )


class TestLivePathReasoningIsPopulated:
    """The two results on the live decision path must carry a reason, not just a number.

    Schematising the reasoning fields is not the same as populating them, and the
    gap between the two is invisible from the outside: a result with
    ``limitations=[]`` and one with ``limitations=["..."]`` are both valid, both
    serialize, and both pass every test that only checks the schema. These tests
    exist because that is exactly how the fields could be added, documented, and
    then silently never used.

    The two functions chosen are the ones the live thesis actually reads:
    ``classify_regime_rule_based`` (Q1's fourth read) and ``_as_signal`` (Q6's
    significance carrier). If reasoning is populated anywhere, it must be here —
    a field nobody on the live path fills is a field nobody consumes.
    """

    @staticmethod
    def _regime_result() -> ModelResult:
        from macro_engine.models.regime import RegimeInputs, classify_regime_rule_based

        return classify_regime_rule_based(
            RegimeInputs(
                output_gap=-0.25,
                inflation_yoy=2.9,
                inflation_trend_3m=0.4,
                unemployment_gap=0.15,
                output_gap_change=-0.05,
            )
        )

    @staticmethod
    def _gap_signal() -> ModelResult:
        from datetime import UTC, datetime

        from macro_engine.models.policy_rules import MarketPricingGap
        from macro_engine.thesis_layer.builder import _as_signal

        gap = MarketPricingGap(
            model_implied_value=4.25,
            market_implied_value=4.00,
            raw_gap=0.25,
            dispersion=0.86,
            is_meaningful=False,
            interpretation="test gap",
        )
        return _as_signal(gap, as_of=datetime(2026, 9, 19, tzinfo=UTC))

    def test_regime_declares_its_unit_and_direction(self) -> None:
        r = self._regime_result()
        assert r.unit is not None, "a categorical label must still declare what it is"
        assert "categorical" in r.unit
        assert r.direction is not None
        # The direction sentence must name BOTH axes, because the state is their
        # joint read and a single-axis restatement is the §21 defect in words.
        assert "growth" in r.direction
        assert "inflation" in r.direction

    def test_regime_states_its_standing_limitations(self) -> None:
        """`limitations` are the caveats that hold even when the run succeeded.

        They are the field a reader needs most and is least likely to be given:
        `warnings` fires only on a condition of THIS run, so on a quiet run the
        result would look unqualified without these.
        """
        r = self._regime_result()
        joined = " ".join(r.limitations).lower()
        assert r.limitations, "a rule-based label must declare that it is not a probability"
        assert "rule-based" in joined
        assert "momentum" in joined, "the inflation axis is momentum, and that is a trap"
        assert len(r.limitations) >= 4

    def test_regime_prohibits_being_read_as_a_probability(self) -> None:
        r = self._regime_result()
        joined = " ".join(r.decision_prohibition).lower()
        assert r.decision_prohibition
        assert "probability" in joined
        assert "stand a thesis down" in joined, "the read must not be used as the gate"

    def test_regime_names_its_downstream_consumer(self) -> None:
        r = self._regime_result()
        assert r.decision_relevance is not None
        assert "16.2" in r.decision_relevance, "Q1 is the gate this feeds"

    def test_gap_carrier_admits_it_is_not_a_measurement(self) -> None:
        """The highest-risk field on the live path.

        `_as_signal` carries `confidence=1.0` as a census carrier. Populated
        reasoning is what stops that carrier value from being read as a
        measurement — the prohibition has to say so in words, because the number
        itself cannot.
        """
        r = self._gap_signal()
        joined = " ".join(r.limitations).lower()
        assert "carrier" in joined
        assert "not a measurement" in joined or "not a" in joined

    def test_gap_declares_its_unit_and_both_readings(self) -> None:
        r = self._gap_signal()
        assert r.unit == "percentage points"
        assert r.direction is not None
        # A positive gap is policy MORE restrictive than priced — the inverse of
        # the naive reading of "the gap is positive".
        assert "more restrictive" in r.direction

    def test_gap_requires_dispersion_to_be_interpretable(self) -> None:
        r = self._gap_signal()
        joined = " ".join(r.decision_prohibition).lower()
        assert "dispersion" in joined, "a bare gap has no scale and must say so"

    def test_gap_direction_sentence_handles_the_exact_zero_case(self) -> None:
        """Zero is a third state, not a rounding of either direction.

        Asserted through the helper rather than through `_as_signal` because
        building a zero gap through the model would exercise the model's own
        validation, not this function's branch.
        """
        from macro_engine.thesis_layer.builder import _gap_direction_sentence

        assert "flat" in _gap_direction_sentence(0.0)
        assert "more restrictive" in _gap_direction_sentence(0.01)
        assert "less restrictive" in _gap_direction_sentence(-0.01)


class TestAllThreeLiveReadsArePopulated:
    """Q1's three economy reads must each carry reasoning, not just a value.

    The previous class pins the regime (a derived read) and the gap (the
    significance carrier). These three are the reads the regime and the thesis
    are computed FROM, so a reasoning gap here propagates: a reader who cannot
    see that the output gap is revision-dependent, or that the labour score's
    weights are illustrative, has no way to weigh any conclusion built on them.

    Each of the three has a different load-bearing limitation, which is the
    reason all three are asserted rather than one exemplar being generalised:
    the growth read is REVISION-DEPENDENT, the inflation read is WEAK because a
    sign test is weak, and the labour read is a LEVEL with one input missing on
    the live path.
    """

    @staticmethod
    def _growth() -> ModelResult:
        from macro_engine.models.gdp_nowcast import OutputGapInputs, output_gap

        return output_gap(OutputGapInputs(actual_gdp=20_000.0, potential_gdp=20_300.0))

    @staticmethod
    def _inflation() -> ModelResult:
        from macro_engine.models.labor_synthesis import (
            InflationSubMeasures,
            inflation_breadth_score,
        )

        return inflation_breadth_score(
            InflationSubMeasures(cpi_headline_mom=0.2, cpi_core_mom=0.3, pce_core_mom=0.1)
        )

    @staticmethod
    def _labor() -> ModelResult:
        from macro_engine.models.labor_synthesis import LaborInputs, labor_tightness_score

        return labor_tightness_score(
            LaborInputs(
                initial_claims_4wk_avg_change_pct=-0.4,
                jolts_openings_yoy_pct=3.0,
                jolts_quits_level_percentile=60.0,
                nfp_3m_avg=180.0,
            )
        )

    @pytest.mark.parametrize(
        "factory",
        ["_growth", "_inflation", "_labor"],
    )
    def test_each_read_declares_unit_direction_and_reasoning(self, factory: str) -> None:
        """The four fields every §3 result must carry, asserted uniformly.

        Parametrised rather than written three times so a NEW live read added to
        the pipeline can be added here in one line, and so the failure names the
        read rather than a method.
        """
        r = getattr(self, factory)()
        assert r.unit, f"{factory} must declare its unit (None means UNKNOWN, not dimensionless)"
        assert r.direction, f"{factory} must state what its value means, in words"
        assert r.limitations, f"{factory} must state what it cannot tell you"
        assert r.decision_relevance, f"{factory} must name its downstream consumer"
        assert r.assumptions, f"{factory} must state what it depends on"
        assert r.data_provenance, f"{factory} must name where its inputs came from"

    def test_growth_read_flags_revision_dependence(self) -> None:
        """The output gap's dominant real-world risk is that it is a revision artifact.

        Both inputs (BEA GDP, CBO potential) are revised, so a gap read today is
        not the gap that was available at the time. A reader using this for a
        backtest must be told; the field says it in those terms.
        """
        joined = " ".join(self._growth().limitations).lower()
        assert "revision" in joined
        assert "unobservable" in joined or "not a measurement" in joined

    def test_growth_read_separates_the_zero_case(self) -> None:
        """A gap of exactly zero is 'at potential', a third state."""
        from macro_engine.models.gdp_nowcast import _gap_direction_sentence

        assert "at potential" in _gap_direction_sentence(0.0)
        assert "above" in _gap_direction_sentence(0.5)
        assert "below" in _gap_direction_sentence(-0.5)

    def test_inflation_read_admits_the_sign_test_is_weak(self) -> None:
        """Breadth is a sign test, so convergence says nothing about magnitude.

        This is the limitation a consumer is most likely to skip, and skipping it
        is how "inflation is broad" gets asserted from three readings of +0.01%.
        """
        joined = " ".join(self._inflation().limitations).lower()
        assert "sign test" in joined
        assert "three" in joined, "counting only 3 measures is the proxy's whole caveat"

    def test_inflation_read_forbids_being_quoted_as_a_rate(self) -> None:
        """The value is an average of m/m changes — not a level, not an annual rate."""
        joined = " ".join(self._inflation().decision_prohibition).lower()
        assert "rate" in joined
        assert "average" in joined or "mean" in joined

    def test_inflation_divergent_read_has_no_direction(self) -> None:
        """On a divergent read there IS no direction, and the field must say so.

        Three states are not a boolean: all-rising, all-falling, and CONFLICTED.
        Collapsing the third into either of the others is the defect the helper
        exists to prevent.
        """
        from macro_engine.models.labor_synthesis import (
            InflationSubMeasures,
            _breadth_direction_sentence,
            inflation_breadth_score,
        )

        r = inflation_breadth_score(
            InflationSubMeasures(cpi_headline_mom=0.5, cpi_core_mom=-0.4, pce_core_mom=0.1)
        )
        assert r.direction is not None
        assert "CONFLICTED" in r.direction
        # And the standalone helper must agree with the branch that produced it.
        assert "CONFLICTED" in _breadth_direction_sentence(False, False)
        assert "rising" in _breadth_direction_sentence(True, False)
        assert "falling" in _breadth_direction_sentence(False, True)

    def test_labor_read_admits_it_is_an_uncalibrated_level(self) -> None:
        """The score's scale is this model's own, so it cannot be compared outward."""
        r = self._labor()
        joined = " ".join(r.limitations).lower()
        assert "heuristic" in joined or "not calibrated" in joined
        assert "level" in joined
        prohibited = " ".join(r.decision_prohibition).lower()
        assert "index" in prohibited, "must forbid comparison to an external tightness index"

    def test_labor_read_discloses_the_missing_nfp_on_the_live_path(self) -> None:
        """NFP is not in the snapshot, so the LIVE score uses three components.

        The unit test above passes all four, so this asserts the disclosure
        exists in `limitations` rather than asserting the live value — the
        orchestrator owns redistribution, and the model must still say that a
        live run differs from the tested one.
        """
        joined = " ".join(self._labor().limitations).lower()
        assert "nfp" in joined or "payrolls" in joined
        assert "absent" in joined or "redistribut" in joined

    def test_labor_read_separates_the_balanced_case(self) -> None:
        """A score of exactly zero is 'balanced', not a rounding."""
        from macro_engine.models.labor_synthesis import _tightness_direction_sentence

        assert "balanced" in _tightness_direction_sentence(0.0)
        assert "tightening" in _tightness_direction_sentence(0.5)
        assert "loosening" in _tightness_direction_sentence(-0.5)


class TestCurveReadsArePopulated:
    """The curve reads on the live path: slope and breakevens.

    Both are pure arithmetic on observed yields, which is what makes them the
    easiest results in the tree to *look* self-explanatory and therefore the
    easiest to leave undocumented. The reasoning is not in the subtraction — it
    is in what the subtraction cannot separate, and that is what these pin.

    The two differ in an important way. `curve_slope` HAS a meaningful direction
    (normal / flat / inverted). `breakeven_inflation` deliberately does NOT: it is
    a compensation level in percent with no target or equilibrium in the model to
    compare against. Asserting both properties is the point — a future edit that
    "helpfully" gives the breakeven a direction would be wrong, and only a test
    that asserts its absence would catch that.
    """

    @staticmethod
    def _slope(spread: float) -> ModelResult:
        from macro_engine.models.yield_curve import CurveSlopeInputs, curve_slope

        return curve_slope(
            CurveSlopeInputs(
                tenors={"2yr": 4.0, "10yr": 4.0 + spread / 100}, short="2yr", long="10yr"
            )
        )

    @staticmethod
    def _breakeven(nominal: float, real: float) -> ModelResult:
        from macro_engine.models.yield_curve import BreakevenInputs, breakeven_inflation

        return breakeven_inflation(BreakevenInputs(nominal=nominal, tips_real=real, tenor="10yr"))

    def test_slope_declares_basis_points_and_a_three_state_direction(self) -> None:
        assert self._slope(+120.0).unit == "basis points"
        assert "normal" in (self._slope(+120.0).direction or "")
        assert "inverted" in (self._slope(-50.0).direction or "")
        assert "flat" in (self._slope(0.0).direction or "")

    def test_slope_forbids_being_read_as_a_timing_signal(self) -> None:
        """The 6-24 month variable lead is the model's most misused property.

        An inversion that precedes a recession by two years is, in real time,
        indistinguishable from one that precedes nothing — and that is the
        sentence a consumer must have before treating the spread as dated.
        """
        r = self._slope(-50.0)
        joined = " ".join(r.decision_prohibition).lower()
        assert "timing" in joined or "forecast" in joined
        limitations = " ".join(r.limitations).lower()
        assert "6-24" in limitations or "variable" in limitations

    def test_slope_says_it_cannot_separate_level_from_shape(self) -> None:
        """+100bp at 1%/2% and at 5%/6% are different regimes, same number."""
        joined = " ".join(self._slope(+120.0).limitations).lower()
        assert "level" in joined
        assert "two" in joined or "curvature" in joined

    def test_breakeven_refuses_to_state_a_direction(self) -> None:
        """The breakeven must say it is a LEVEL with no target to compare against.

        A model that has no equilibrium, no target and no neutral band cannot
        legitimately say a breakeven is 'high' or 'rising is hawkish'. Asserting
        the ABSENCE of a directional claim is the only way to stop a later edit
        from adding one, because adding one would look like an improvement.
        """
        r = self._breakeven(nominal=4.25, real=1.85)
        assert r.direction is not None
        joined = r.direction.lower()
        assert "level" in joined
        assert "not a direction" in joined or "no target" in joined

    def test_breakeven_distinguishes_the_impossible_from_the_unusual(self) -> None:
        """A negative breakeven is a liquidity signal, not a market inflation view.

        Nominal below real at the same tenor would make the implied real yield
        exceed the nominal, which cannot reflect an inflation expectation. The
        sentence must name it as a distortion rather than fold it into a
        generic 'below' state.
        """
        r = self._breakeven(nominal=4.00, real=4.10)
        assert r.direction is not None
        joined = r.direction.lower()
        assert "negative" in joined
        assert "liquidity" in joined or "distortion" in joined

    def test_breakeven_forbids_the_market_expects_phrasing(self) -> None:
        """'The market expects X% inflation' is the reading most likely to be published."""
        joined = " ".join(self._breakeven(nominal=4.25, real=1.85).decision_prohibition).lower()
        assert "expect" in joined
        assert (
            "compensation" in " ".join(self._breakeven(nominal=4.25, real=1.85).limitations).lower()
        )

    def test_breakeven_forbids_being_fed_to_the_policy_path(self) -> None:
        """derive_market_implied_policy_path consumes the NOMINAL curve, not a breakeven."""
        joined = " ".join(self._breakeven(nominal=4.25, real=1.85).decision_prohibition).lower()
        assert "nominal" in joined
        assert "policy path" in joined

    def test_both_curve_reads_declare_unit_assumptions_and_provenance(self) -> None:
        for r in (self._slope(+120.0), self._breakeven(nominal=4.25, real=1.85)):
            assert r.unit, f"{r.model_name} must declare its unit"
            assert r.assumptions, f"{r.model_name} must state its assumptions"
            assert r.data_provenance, f"{r.model_name} must name its sources"
            assert r.decision_relevance, f"{r.model_name} must name its consumer"
            assert r.limitations, f"{r.model_name} must state its limits"


class TestGapInputsArePopulated:
    """The two results that produce the SIGNIFICANCE GAP itself.

    `derive_market_implied_policy_path` is the market side of Q6's gap and
    `gdp_gdi_divergence` is the corroborating read about the growth read's
    quality. Both are on the live path, and both have a property that makes the
    reasoning object load-bearing rather than decorative:

    * the market path's live branch is a CONTAMINATED proxy — the raw short
      yield, with no term premium stripped — and the returned VALUE looks
      identical to the adjusted branch. Only the prose can say which ran, so a
      consumer reading `value` alone cannot know whether the gap's sign is
      trustworthy.
    * the divergence's SIGN is a coin flip, so a `direction` that reported the
      sign without disclaiming it would invite exactly the reading the model
      forbids.
    """

    @staticmethod
    def _market_path(premium: float | None) -> ModelResult:
        from macro_engine.models.policy_rules import derive_market_implied_policy_path

        return derive_market_implied_policy_path(4.25, premium)

    @staticmethod
    def _divergence(gdp: float, gdi: float) -> ModelResult:
        from macro_engine.models.gdp_nowcast import GdpGdiInputs, gdp_gdi_divergence

        return gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=gdp, gdi_growth_pct=gdi))

    def test_market_path_declares_percent_and_branch_dependent_direction(self) -> None:
        adjusted = self._market_path(0.35)
        unadjusted = self._market_path(None)
        assert adjusted.unit == "percent"
        assert "expectations component" in (adjusted.direction or "")
        # The NO-PREMIUM branch must say the premium was NOT removed, in those terms.
        assert "RAW" in (unadjusted.direction or "") or "not" in (unadjusted.direction or "")

    def test_market_path_distinguishes_the_two_branches_in_prose(self) -> None:
        """The values are indistinguishable; the warnings must not be.

        Both branches return a float in the same range. If the reasoning object
        did not distinguish them, a consumer could not tell a contaminated
        reading from an adjusted one — which is precisely what Section 22.5
        requires to be impossible.
        """
        adjusted = self._market_path(0.35)
        unadjusted = self._market_path(None)
        assert adjusted.warnings != unadjusted.warnings
        assert any("NO TERM PREMIUM" in w for w in unadjusted.warnings)
        assert not any("NO TERM PREMIUM" in w for w in adjusted.warnings)

    def test_market_path_forbids_probability_readings(self) -> None:
        """A single yield cannot support a likelihood statement about policy."""
        joined = " ".join(self._market_path(None).decision_prohibition).lower()
        assert "probability" in joined or "likelihood" in joined
        assert "rate" in joined, "must forbid being read as a policy RATE"

    def test_market_path_marks_the_live_branch_as_contaminating_the_gap(self) -> None:
        """The strongest claim in this class: the live gap's sign inherits it.

        On the live path no term premium is wired, so the raw-yield branch runs.
        That means the gap the thesis reports is computed against a market leg
        that still contains the premium, and at the front end that premium has
        been large enough to invert the reading. A consumer has to be told.
        """
        joined = " ".join(self._market_path(None).limitations).lower()
        assert "contaminat" in joined
        assert "sign" in joined, "the consequence is about the gap's SIGN"

    def test_divergence_direction_disclaims_itself(self) -> None:
        """The sign is reported AND disclaimed in the same field.

        GDP leads GDI ~47.8% of the time, so the sign carries no information.
        Putting the disclaimer in `direction` rather than only in `warnings`
        means a consumer that reads one field cannot miss it.

        **Asserted as an AND, not an OR.** The first version of this test used
        ``"not a finding" in joined or "coin flip" in joined`` and was proven
        WEAK by planting a regression: stripping only the "NOT a finding" clause
        left "coin flip" behind, so the test still passed even though the
        disclaimer had been removed from the sentence. Both clauses are asserted
        now, because either alone can survive the removal of the other.
        """
        r = self._divergence(gdp=2.5, gdi=2.1)
        assert r.direction is not None
        joined = r.direction.lower()
        assert "not a finding" in joined
        assert "coin flip" in joined
        assert "residual" in joined

    def test_divergence_forbids_reading_its_sign_as_a_finding(self) -> None:
        joined = " ".join(self._divergence(gdp=2.5, gdi=2.1).decision_prohibition).lower()
        assert "sign" in joined
        assert "coin flip" in joined or "47.8" in joined or "finding" in joined

    def test_divergence_states_the_growth_vs_level_unit_trap(self) -> None:
        """Growth basis is load-bearing: the level wedge is systematically negative.

        In growth terms the divergence is mean-zero; in level terms the wedge
        averages -0.459% and is negative in seven of nine decades. A caller
        passing levels would compute a different quantity entirely, and two
        anonymous floats cannot reveal which happened.
        """
        joined = " ".join(self._divergence(gdp=2.5, gdi=2.1).assumptions).lower()
        assert "year-over-year" in joined or "growth rates" in joined
        assert "level" in joined

    def test_divergence_flags_revision_exposure_as_unrepairable(self) -> None:
        """BEA revises the two sides on different schedules, and vintages are gone."""
        joined = " ".join(self._divergence(gdp=2.5, gdi=2.1).limitations).lower()
        assert "revision" in joined or "revise" in joined
        assert "vintage" in joined

    def test_divergence_reports_its_own_base_rate(self) -> None:
        """A one-in-five event must travel with its frequency."""
        r = self._divergence(gdp=2.5, gdi=2.1)
        assert isinstance(r.value, dict)
        assert "divergence_base_rate" in r.value
        assert 0.0 < float(r.value["divergence_base_rate"]) < 1.0

    def test_both_gap_inputs_declare_the_required_fields(self) -> None:
        for r in (self._market_path(None), self._divergence(gdp=2.5, gdi=2.1)):
            assert r.unit, f"{r.model_name} must declare its unit"
            assert r.direction, f"{r.model_name} must state what its value means"
            assert r.assumptions, f"{r.model_name} must state its assumptions"
            assert r.data_provenance, f"{r.model_name} must name its sources"
            assert r.decision_relevance, f"{r.model_name} must name its consumer"
            assert r.decision_prohibition, f"{r.model_name} must state prohibitions"
