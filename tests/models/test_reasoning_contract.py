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
