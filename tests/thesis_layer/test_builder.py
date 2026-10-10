"""``thesis_layer/builder.py`` — the seam function, and two live defects.

The module docstring lists eight measured divergences between Section 16.2's
sample and the shipped contracts. Before 2026-10-06 there was **no test file for
this module at all** — ``build_us_macro_thesis`` and ``build_policy_gap`` were
referenced by zero tests — and the ``THESIS_TIMEFRAME_PHASE_1`` comment names a
guard test (``test_the_horizon_is_used_not_re_typed``) that did not exist.

Live defects found BY this review:

* ``F-BLD-001`` — ``build_policy_gap``'s docstring documented a **three**-element
  return while the function returns four.
* ``F-BLD-003`` — ``_apply_risk_axis`` guarded its shape with a bare ``assert``
  (stripped under ``-O``), against six typed, messaged raises elsewhere.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from macro_engine.models.contracts import ModelResult
from macro_engine.models.evidence_family import EvidenceSourceFamily
from macro_engine.models.instrument_selection import GapDirection
from macro_engine.models.policy_rules import (
    FirstDifferenceInputs,
    MarketPricingGap,
    TaylorRuleInputs,
)
from macro_engine.portfolio.risk_budget import RiskBudgetTarget
from macro_engine.thesis_layer import builder
from macro_engine.thesis_layer.builder import (
    THESIS_ID_PREFIX,
    THESIS_TIMEFRAME_PHASE_1,
    BoeRuleInputs,
    EconomyReads,
    build_policy_gap,
    new_thesis_id,
)
from macro_engine.thesis_layer.schemas import (
    ConvergenceClassification,
    MacroThesis,
    TradeIdea,
)

_AS_OF = datetime(2026, 10, 6, tzinfo=UTC)


_ValueT = float | int | str | bool | dict[str, Any] | list[Any] | None


def _result(
    name: str, value: _ValueT, *, family: EvidenceSourceFamily | None = None
) -> ModelResult:
    return ModelResult(
        model_name=name,
        country="us",
        as_of=_AS_OF,
        value=value,
        confidence=0.5,
        interpretation=f"{name} reading",
        context="test",
        inputs_used=["x"],
        source_family=family,
    )


def _reads() -> EconomyReads:
    return EconomyReads(
        growth=_result("output_gap", -1.0),
        inflation=_result("inflation_breadth_score", -0.5),
        labor=_result("labor_tightness_score", -0.8),
    )


def _gap(raw_gap: float = -1.4) -> MarketPricingGap:
    return MarketPricingGap(
        model_implied_value=2.9,
        market_implied_value=2.9 - raw_gap,
        raw_gap=raw_gap,
        dispersion=0.25,
        is_meaningful=abs(raw_gap) > 0.25,
        interpretation="test gap",
    )


def _thesis() -> MacroThesis:
    return MacroThesis(
        thesis_id="us-2026-10-06-deadbeef",
        regime={"state": "late-cycle"},
        growth_view={"output_gap": -1.0},
        inflation_view={"breadth_score": -0.5},
        policy_view={"taylor": 3.2},
        market_pricing_gap=_gap(),
        convergence_classification=ConvergenceClassification.HIGH,
        trade_idea=TradeIdea(
            instrument="UST cash (2yr, 5yr, 10yr, 30yr)",
            direction="long",
            stop_or_invalidation="10y above 4.75%",
        ),
        warnings=[],
    )


def _source() -> str:
    return Path(inspect.getfile(builder)).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# (F-BLD-002) the guard test the module NAMES
# ---------------------------------------------------------------------------


def test_the_horizon_is_used_not_re_typed() -> None:
    """(F-BLD-002) The test named at ``THESIS_TIMEFRAME_PHASE_1`` — it did not exist.

    The comment says the literal was promoted to a constant so a guard test can
    assert the call site binds the NAME. The failure it guards is real and was
    measured once already (audit finding B-1): the horizon was a bare
    ``"6-12 months"`` at the ``TradeIdea`` call site while its neighbour two lines
    away was already a constant.
    """
    source = _source()
    assert "timeframe=THESIS_TIMEFRAME_PHASE_1" in source, (
        "the TradeIdea call site must bind the constant, not re-type the string"
    )
    # No call site re-types it. (The literal itself appears twice by design: its
    # own definition, and the comment above it quoting the value it replaced.)
    assert 'timeframe="' not in source
    assert source.count(f'THESIS_TIMEFRAME_PHASE_1 = "{THESIS_TIMEFRAME_PHASE_1}"') == 1


def test_the_sizing_logic_is_used_not_re_typed() -> None:
    """The neighbour claim: "a test asserts the thesis carries it"."""
    source = _source()
    assert "sizing_logic=SIZING_LOGIC_PHASE_1" in source
    assert 'sizing_logic="' not in source


def test_no_generate_id_exists_anywhere() -> None:
    """§16.2's sample calls ``generate_id()`` — the docstring's ninth divergence.

    It says "No ``generate_id`` exists anywhere in the tree (measured)". Pinned
    here so the claim stays true: ``new_thesis_id`` is this project's generator.
    """
    root = Path(__file__).resolve().parents[2]
    offenders = [
        p
        for p in (root / "src").rglob("*.py")
        if "def generate_id(" in p.read_text(encoding="utf-8", errors="replace")
    ]
    assert offenders == [], f"a generate_id was defined: {offenders}"


# ---------------------------------------------------------------------------
# the thesis id
# ---------------------------------------------------------------------------


def test_the_thesis_id_is_date_first_and_reproducible_from_as_of() -> None:
    a = new_thesis_id(as_of=_AS_OF)
    b = new_thesis_id(as_of=_AS_OF)
    assert a.startswith(f"{THESIS_ID_PREFIX}-2026-10-06-")
    assert len(a.rsplit("-", 1)[-1]) == 8
    assert a != b  # the suffix is random, so two theses are distinguishable


def test_the_thesis_id_prefix_is_the_country_not_a_literal() -> None:
    """(§22.3) A gb thesis must not carry a ``us-`` id.

    The id is the first thing an operator greps, so a UK thesis labelled
    ``us-...`` would be the single most misleading field on the record. The
    prefix is the ``country`` argument, defaulting to ``THESIS_ID_PREFIX`` for
    the US case so there is one source for the "us" spelling.
    """
    us = new_thesis_id(as_of=_AS_OF)
    gb = new_thesis_id(as_of=_AS_OF, country="gb")
    assert us.startswith("us-")
    assert gb.startswith("gb-")
    # The default and the explicit "us" are the same thing.
    assert us.startswith(f"{THESIS_ID_PREFIX}-")
    assert new_thesis_id(as_of=_AS_OF, country="us").startswith("us-")


# ---------------------------------------------------------------------------
# (§22.3) build_policy_gap dispatches to the right central bank's rules
# ---------------------------------------------------------------------------


def _boe_inputs() -> BoeRuleInputs:
    from macro_engine.models.policy_rules import (
        BoeContemporaneousInputs,
        BoeFirstDifferenceInputs,
        BoeForwardLookingInputs,
    )

    return BoeRuleInputs(
        contemporaneous=BoeContemporaneousInputs(
            i_prev=4.25,
            pi_energy_gap_pp=2.0,
            pi_non_energy_gap_pp=1.4,
            output_gap=0.1,
        ),
        forward_looking=BoeForwardLookingInputs(
            i_prev=4.25, projected_inflation_pp=3.7, projected_output_gap=0.1
        ),
        first_difference=BoeFirstDifferenceInputs(
            i_prev=4.25, projected_inflation_pp=3.7, projected_gdp_growth=0.3
        ),
    )


def test_a_gb_policy_gap_runs_the_boe_rules_not_the_fed_trio() -> None:
    """(§22.3) ``country='gb'`` reads ``boe_inputs`` and the BoE's three rules.

    The discriminating check is the *names* of the three rule results: the BoE's
    trio and the Fed's trio are different functions with different model names,
    so a dispatch that fell through to the Fed's rules would produce the Fed's
    names on a gb thesis. ``build_policy_gap`` returns ``(gap, rules, ensemble,
    market_path)`` and the second element is the same length (three) for both
    countries — so the length alone would NOT catch a mis-dispatch, which is
    exactly why this asserts on the identities.
    """
    _gap, rules, _ensemble, _market = build_policy_gap(
        None,
        None,
        country="gb",
        boe_inputs=_boe_inputs(),
        short_yield=4.35,
        short_tenor_term_premium=None,
    )
    names = {r.model_name for r in rules}
    # EXACT names, not substrings: the BoE's names SUFFIX the Fed's, so
    # "boe_contemporaneous_taylor_rule" CONTAINS "taylor_rule" and a substring
    # check would report a false mis-dispatch. The Fed's three rule names, as
    # the us branch produces them, are exactly these — a gb thesis must match
    # none of them.
    fed_names = {"taylor_rule", "balanced_approach_rule", "first_difference_rule"}
    assert names & fed_names == set(), f"a gb thesis ran the Fed's rules: {names & fed_names}"
    # The BoE's three rules are all present, and they are the BoE's.
    assert len(names) == 3
    assert all(n.startswith("boe_") for n in names), names


def test_a_gb_policy_gap_without_boe_inputs_is_refused() -> None:
    """(§22.3) A gb thesis with no BoE inputs has no policy leg — refuse, don't guess."""
    with pytest.raises(TypeError, match="requires boe_inputs"):
        build_policy_gap(
            None,
            None,
            country="gb",
            boe_inputs=None,
            short_yield=4.35,
            short_tenor_term_premium=None,
        )


def test_a_gb_policy_gap_given_the_feds_records_is_refused() -> None:
    """(§22.3) ONE country's records per thesis — passing both is refused, not ignored.

    This is D-037's inert-input class at the country level: if the Fed's records
    were accepted alongside the BoE's, a caller would believe they mattered.
    """
    with pytest.raises(TypeError, match="requires boe_inputs"):
        build_policy_gap(
            TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0),
            FirstDifferenceInputs(i_prev=4.0, pi_current=3.0, output_gap_change=0.2),
            country="gb",
            boe_inputs=None,
            short_yield=4.35,
            short_tenor_term_premium=None,
        )


def test_a_us_policy_gap_given_the_boe_records_is_refused() -> None:
    """(§22.3) The other direction: a us thesis may not carry the BoE's records."""
    with pytest.raises(TypeError, match="was given boe_inputs"):
        build_policy_gap(
            TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0),
            FirstDifferenceInputs(i_prev=4.0, pi_current=3.0, output_gap_change=0.2),
            country="us",
            boe_inputs=_boe_inputs(),
            short_yield=4.35,
            short_tenor_term_premium=None,
        )


def test_a_country_with_no_rule_set_is_refused_not_borrowed() -> None:
    """(§22.3) An unimplemented country must not quietly run the Fed's rules.

    The dispatch is explicit rather than a ``getattr``/try-except fallback
    precisely so this is a loud refusal: a country without its own central-bank
    rules has no policy leg, and borrowing another's would be the relabeled-Fed
    failure §22.3 exists to prevent.
    """
    with pytest.raises(ValueError, match="no rule set for country"):
        build_policy_gap(
            TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0),
            FirstDifferenceInputs(i_prev=4.0, pi_current=3.0, output_gap_change=0.2),
            country="jp",
            short_yield=4.35,
            short_tenor_term_premium=None,
        )


# ---------------------------------------------------------------------------
# (F-BLD-001) build_policy_gap returns FOUR values
# ---------------------------------------------------------------------------


def test_build_policy_gap_returns_four_values() -> None:
    """(F-BLD-001) The docstring said three; the annotation and code say four.

    ``market_path`` is the fourth, and it is returned rather than discarded
    because it carries the Section 22.5 term-premium contamination warnings.
    """
    returned = build_policy_gap(
        TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0),
        FirstDifferenceInputs(i_prev=4.0, pi_current=3.0, output_gap_change=0.2),
        short_yield=4.3,
        short_tenor_term_premium=None,
    )
    assert len(returned) == 4
    gap, rules, ensemble, market_path = returned
    assert isinstance(gap, MarketPricingGap)
    assert len(rules) == 3
    assert ensemble.model_name  # the ensemble result
    assert market_path.model_name  # the fourth value the docstring omitted
    # The docstring's Returns line must list all four.
    doc = build_policy_gap.__doc__ or ""
    assert "(gap, rules, ensemble, market_path)" in doc


def test_build_policy_gap_threads_the_futures_curve_to_the_market_leg() -> None:
    """Section 22.5: the chain must PREFER the futures path when handed a curve.

    ``build_policy_gap`` threads ``futures_curve`` to
    ``derive_market_implied_policy_path``. The discriminating check is the
    returned ``market_path.model_name``: the proxy branch and the futures branch
    return results produced by different functions, so the name says which one
    built the market leg — and, with it, whose warnings the thesis will carry.

    Both directions are asserted, because a test that only checks the curve case
    would pass on a chain that ignored ``futures_curve`` whenever the default
    (proxy) was also the fallback.
    """
    from macro_engine.config import get_settings
    from macro_engine.data_layer.fed_funds_futures_client import (
        FedFundsFuturesCurve,
        FuturesExpiration,
    )

    def _curve() -> FedFundsFuturesCurve:
        rates = [("2026-11", 3.88), ("2026-12", 4.05), ("2027-01", 4.31), ("2027-03", 4.69)]
        expirations = tuple(
            FuturesExpiration(
                expiration=expiration,
                price=100.0 - rate,
                implied_rate_pct=rate,
                months_ahead=index,
                raw_price=100.0 - rate,
            )
            for index, (expiration, rate) in enumerate(rates)
        )
        return FedFundsFuturesCurve(
            symbol="ZQ",
            provider="yfinance",
            settlement_offset=100.0,
            as_of="2026-10-10",
            expirations=expirations,
            rows_returned=len(rates),
            rows_rejected=0,
            rows_dropped_past=0,
            rejected_detail=(),
            source_retrieved_at="2026-10-10T00:00:00+00:00",
        )

    taylor = TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0)
    first_diff = FirstDifferenceInputs(i_prev=4.0, pi_current=3.0, output_gap_change=0.2)

    _, _, _, proxy_path = build_policy_gap(
        taylor,
        first_diff,
        short_yield=4.3,
        short_tenor_term_premium=None,
    )
    assert proxy_path.model_name == "derive_market_implied_policy_path", (
        "with no curve the proxy branch must run"
    )

    _, _, _, futures_path = build_policy_gap(
        taylor,
        first_diff,
        short_yield=4.3,
        short_tenor_term_premium=None,
        futures_curve=_curve(),
    )
    assert futures_path.model_name == "futures_implied_policy_path", (
        "a supplied curve must reach the market leg; the chain dropped it"
    )
    # The near rate, not the mean: the identity every consumer relies on.
    horizon = get_settings().policy.market_implied.proxy_horizon_months_value
    assert futures_path.value == pytest.approx(3.88), (
        "the futures leg must publish the NEAR implied rate; a value of 3.88% "
        f"(horizon={horizon}mo) is what the near expiration implies"
    )
    assert futures_path.value != pytest.approx(proxy_path.value), (
        "the two branches must not coincide, or this test cannot tell them apart"
    )

    _, rules, ensemble, _ = build_policy_gap(
        TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0),
        FirstDifferenceInputs(i_prev=4.0, pi_current=3.0, output_gap_change=0.2),
        short_yield=4.3,
        short_tenor_term_premium=None,
    )
    view = builder.policy_view_dict(rules, ensemble)
    assert set(view) >= {
        "taylor",
        "balanced",
        "first_difference",
        "dispersion",
        "interpretation",
    }
    assert isinstance(view["taylor"], float)


# ---------------------------------------------------------------------------
# the small readers — each a named refusal
# ---------------------------------------------------------------------------


def test_rule_number_refuses_a_boolean_and_a_non_number() -> None:
    with pytest.raises(TypeError, match="must produce a rate in percent"):
        builder._rule_number(_result("taylor_rule", True))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="must produce a rate in percent"):
        builder._rule_number(_result("taylor_rule", "3.2"))  # type: ignore[arg-type]


def test_gap_direction_sentence_separates_the_three_states() -> None:
    assert "flat" in builder._gap_direction_sentence(0.0)
    assert "more restrictive" in builder._gap_direction_sentence(0.5)
    assert "less restrictive" in builder._gap_direction_sentence(-0.5)


def test_gap_direction_maps_the_sign_and_refuses_exactly_zero() -> None:
    assert builder._gap_direction(_gap(1.0)) is GapDirection.POSITIVE
    assert builder._gap_direction(_gap(-1.0)) is GapDirection.NEGATIVE
    zero = MarketPricingGap(
        model_implied_value=3.0,
        market_implied_value=3.0,
        raw_gap=0.0,
        dispersion=0.25,
        is_meaningful=True,  # the contradiction the raise exists for
        interpretation="contradictory",
    )
    with pytest.raises(ValueError, match=r"exactly 0\.0"):
        builder._gap_direction(zero)


def test_instrument_from_handles_both_shapes() -> None:
    """A sentinel is a bare string; an executable route is a dict (O-87)."""
    assert builder._instrument_from(_result("s", "ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT")) == (
        "ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT"
    )
    assert builder._instrument_from(_result("s", {"instrument": "ES futures"})) == "ES futures"


def test_instrument_from_refuses_an_empty_string_and_a_nameless_dict() -> None:
    with pytest.raises(ValueError, match="EMPTY string"):
        builder._instrument_from(_result("s", ""))
    with pytest.raises(KeyError, match="no non-empty 'instrument'"):
        builder._instrument_from(_result("s", {"direction": "long"}))
    with pytest.raises(TypeError, match="documented shapes"):
        builder._instrument_from(_result("s", 3))


def test_direction_prefers_the_selectors_own_output() -> None:
    """§16.2's rule is written for rates; the selector publishes the real one."""
    assert builder._direction_for(_result("s", {"direction": "short"}), _gap(-1.4)) == "short"
    # A sentinel route publishes no direction, so the rates fallback applies.
    assert builder._direction_for(_result("s", "SENTINEL"), _gap(-1.4)) == "long"
    assert builder._direction_for(_result("s", "SENTINEL"), _gap(1.4)) == "short"


def test_family_count_does_not_count_none_or_repeats() -> None:
    unlabelled = EconomyReads(
        growth=_result("a", 1.0), inflation=_result("b", 1.0), labor=_result("c", 1.0)
    )
    assert builder._family_count(unlabelled) == 0  # None is not a family

    same = EconomyReads(
        growth=_result("a", 1.0, family=EvidenceSourceFamily.MARKET_FX),
        inflation=_result("b", 1.0, family=EvidenceSourceFamily.MARKET_FX),
        labor=_result("c", 1.0),
    )
    assert builder._family_count(same) == 1  # a repeat is one family


def test_scalar_keeps_the_value_rather_than_stringifying_it() -> None:
    assert builder._scalar(_result("a", {"classification": "HIGH"})) == {"classification": "HIGH"}
    assert builder._scalar(_result("a", 3.5)) == 3.5


# ---------------------------------------------------------------------------
# catalysts — the one failure this builder catches
# ---------------------------------------------------------------------------


def test_an_explicit_empty_override_skips_the_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """``[]`` is the caller's own statement, not "nothing was fetched" (D-066)."""

    def boom(*a: object, **k: object) -> list[str]:
        raise AssertionError("the fetch must not run when an override is given")

    monkeypatch.setattr(builder, "next_catalyst_calendar", boom)
    assert builder._resolve_catalysts([], _AS_OF) == ((), ())
    assert builder._resolve_catalysts(["CPI — 2026-10-02"], _AS_OF) == (("CPI — 2026-10-02",), ())


def test_an_unreachable_calendar_is_a_labelled_warning_not_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from macro_engine.thesis_layer.catalysts import CatalystSourceError

    def boom(*a: object, **k: object) -> list[str]:
        raise CatalystSourceError("no source answered")

    monkeypatch.setattr(builder, "next_catalyst_calendar", boom)
    catalysts, warnings = builder._resolve_catalysts(None, _AS_OF)
    assert catalysts == ()
    assert len(warnings) == 1
    assert "UNREACHABLE" in warnings[0]
    assert "NOT because no catalyst is scheduled" in warnings[0]


def test_a_network_error_that_is_not_catalyst_source_error_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The docstring: "It does not catch anything but CatalystSourceError"."""

    def boom(*a: object, **k: object) -> list[str]:
        raise httpx.ConnectError("dns")

    monkeypatch.setattr(builder, "next_catalyst_calendar", boom)
    with pytest.raises(httpx.ConnectError):
        builder._resolve_catalysts(None, _AS_OF)


# ---------------------------------------------------------------------------
# (F-BLD-003) the risk axis guards its shape with a typed raise
# ---------------------------------------------------------------------------


def test_a_non_dict_translation_raises_a_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """(F-BLD-003) The guard was a bare ``assert`` — stripped under ``-O``.

    Every other narrowing in this module raises a typed error with a message
    explaining what the shape change means; this was the only exception.
    """
    monkeypatch.setattr(
        builder,
        "translate_thesis_to_position",
        lambda inputs: _result("translate_thesis_to_position", "not a dict"),
    )
    with pytest.raises(TypeError, match="translate_thesis_to_position returned a str"):
        builder._apply_risk_axis(
            _thesis(),
            # The instrument must MATCH the thesis's: ThesisPositionInputs refuses a
            # mismatch before the translation runs, which is its own guard.
            RiskBudgetTarget(
                instrument="UST cash (2yr, 5yr, 10yr, 30yr)",
                target_risk_contribution_pct=1.0,
            ),
        )


def test_no_bare_assert_remains_in_the_module() -> None:
    """The whole module, not just the one site: a bare assert is a vanishing guard."""
    offenders = [
        line
        for line in _source().splitlines()
        if line.strip().startswith("assert ") and not line.strip().startswith("assert isinstance(")
    ]
    assert offenders == [], f"bare assert(s) found: {offenders}"


def test_a_missing_risk_budget_is_a_disclosed_absence() -> None:
    """'unchecked' and 'checked and clear' must not read alike."""
    out = builder._apply_risk_axis(_thesis(), None)
    assert out.status is _thesis().status  # unchanged
    assert any("DID NOT RUN" in w for w in out.warnings)
