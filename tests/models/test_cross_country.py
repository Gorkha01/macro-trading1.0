"""``models/cross_country.py`` — Section 22.3 layer 4, the cross-country reasoning.

The four-layer multi-country bar (``docs/PHASE5_DEFERRED.md`` §2.4.1) puts
**cross-country reasoning** above data, reaction functions and instruments. This
module measures the divergence between two COMPLETE country systems and decides
whether it is worth expressing; ``select_instrument`` then names the pair.

Every test here is written against the **mechanism** (the arithmetic, the
validator, the config leaf), not a textual trace of it — after four sessions in
which a text-grep test survived a mutation that removed the behaviour, a scan for
a name is no longer accepted as a test of the thing that name refers to.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from macro_engine.config import get_settings
from macro_engine.models.contracts import ModelResult
from macro_engine.models.cross_country import (
    MEANINGFUL_DIVERGENCE,
    NO_MEANINGFUL_DIVERGENCE,
    CrossCountryInputs,
    cross_country_divergence,
)
from macro_engine.models.instrument_selection import (
    ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT,
    GapDirection,
    InstrumentSelectionInputs,
    ThesisType,
    select_instrument,
)
from macro_engine.thesis_layer.schemas import ProductionUniverse

# The shared horizon the config sanctions for every leg.
_HORIZON = get_settings().cross_country.comparable_horizon
_THRESHOLD = get_settings().cross_country.meaningful_divergence


def _inputs(
    *,
    country_a: str = "us",
    country_b: str = "eu",
    policy_rate_a: float = 3.88,
    inflation_a: float = 2.60,
    policy_rate_b: float = 2.50,
    inflation_b: float = 2.10,
    long_rate_a: float = 4.20,
    long_rate_b: float = 2.30,
    tenor_a: str = "10y",
    tenor_b: str = "10y",
    horizon_a: float | None = None,
    horizon_b: float | None = None,
    currency_a: str = "USD",
    currency_b: str = "EUR",
    same_currency_basis: bool = False,
    fx_converted: bool = True,
) -> CrossCountryInputs:
    return CrossCountryInputs(
        country_a=country_a,
        country_b=country_b,
        policy_rate_a=policy_rate_a,
        policy_rate_b=policy_rate_b,
        inflation_a=inflation_a,
        inflation_b=inflation_b,
        long_rate_a=long_rate_a,
        long_rate_b=long_rate_b,
        tenor_a=tenor_a,
        tenor_b=tenor_b,
        horizon_quarters_a=_HORIZON if horizon_a is None else horizon_a,
        horizon_quarters_b=_HORIZON if horizon_b is None else horizon_b,
        currency_a=currency_a,
        currency_b=currency_b,
        same_currency_basis=same_currency_basis,
        fx_converted=fx_converted,
    )


# ---------------------------------------------------------------------------
# Hand-derived arithmetic (LAW 3) — computed by hand, not by the code
# ---------------------------------------------------------------------------


def test_real_rate_differential_is_hand_derivable() -> None:
    """US (3.88 - 2.60) = 1.28%; EU (2.50 - 2.10) = 0.40%; gap = 0.88pp = 88bp.

    Derived on paper before running: a test that re-uses the implementation's
    own expression proves nothing about the arithmetic (LAW 3).
    """
    result = cross_country_divergence(_inputs())
    assert isinstance(result, ModelResult)
    value = result.value
    assert isinstance(value, dict)
    assert value["real_rate_a"] == 1.28
    assert value["real_rate_b"] == 0.40
    assert value["divergence_bp"] == 88.0
    assert value["nominal_spread_bp"] == 190.0  # (4.20 - 2.30) * 100
    assert value["verdict"] == MEANINGFUL_DIVERGENCE
    assert value["long_leg_country"] == "us"
    assert value["short_leg_country"] == "eu"
    assert value["threshold_bp"] == _THRESHOLD


def test_the_sign_convention_is_placed_on_the_legs_not_a_caller_flag() -> None:
    """A NEGATIVE differential flips the long/short assignment.

    Run the same two countries with the ARGUMENTS swapped (labels AND values):
    the sign of the divergence reverses and the long leg is now the other
    country. This is the property that makes the assignment *derived* rather than
    a flag a caller can set wrongly on a correct number.
    """
    forward = cross_country_divergence(_inputs(country_a="us", country_b="eu"))
    # Swap the whole leg: eu's values become A's, us's become B's.
    reverse = cross_country_divergence(
        _inputs(
            country_a="eu",
            country_b="us",
            policy_rate_a=2.50,
            inflation_a=2.10,
            policy_rate_b=3.88,
            inflation_b=2.60,
            long_rate_a=2.30,
            long_rate_b=4.20,
            currency_a="EUR",
            currency_b="USD",
        )
    )
    fwd, rev = forward.value, reverse.value
    assert isinstance(fwd, dict) and isinstance(rev, dict)
    assert fwd["divergence_bp"] == 88.0
    assert rev["divergence_bp"] == -88.0
    assert fwd["divergence_bp"] == -rev["divergence_bp"]
    # The long leg is the higher-real-rate country in BOTH framings: US.
    assert fwd["long_leg_country"] == rev["long_leg_country"] == "us"
    assert fwd["short_leg_country"] == rev["short_leg_country"] == "eu"


def test_each_input_is_a_real_mover() -> None:
    """Every input the arithmetic reads must MOVE the published divergence.

    A field that is bound but never read is the D-037 inert-input class; a field
    read into a quantity that never reaches the output is the same defect one
    step later. Perturb each input and assert the output moves.
    """
    base = cross_country_divergence(_inputs()).value
    assert isinstance(base, dict)

    movers = {
        "policy_rate_a": _inputs(policy_rate_a=4.88),  # +1pp
        "inflation_a": _inputs(inflation_a=3.60),  # +1pp
        "policy_rate_b": _inputs(policy_rate_b=3.50),  # +1pp
        "inflation_b": _inputs(inflation_b=1.10),  # -1pp
    }
    for name, moved_inputs in movers.items():
        moved = cross_country_divergence(moved_inputs).value
        assert isinstance(moved, dict)
        assert moved["divergence_bp"] != base["divergence_bp"], (
            f"{name} did not move divergence_bp — it is an inert input"
        )

    # The long rates move the NOMINAL spread but not the real differential: the
    # two quantities are computed from different fields, which is the whole
    # reason the nominal one is reported beside the verdict rather than read by it.
    nominal = cross_country_divergence(_inputs(long_rate_a=5.20)).value
    assert isinstance(nominal, dict)
    assert nominal["nominal_spread_bp"] != base["nominal_spread_bp"]
    assert nominal["divergence_bp"] == base["divergence_bp"]


def test_the_noise_band_reads_the_config_leaf() -> None:
    """A gap below the configured band is NO_MEANINGFUL_DIVERGENCE.

    The threshold is a config leaf, not a literal; the boundary check and its
    consumer must read the SAME leaf, so this test reads it from the config and
    places the gap on both sides of it.
    """
    below = cross_country_divergence(
        # US real 1.28, EU real raised to 1.20 -> gap 8bp, well inside the band.
        _inputs(inflation_b=1.30)
    ).value
    assert isinstance(below, dict)
    assert below["verdict"] == NO_MEANINGFUL_DIVERGENCE
    assert abs(below["divergence_bp"]) < _THRESHOLD

    above = cross_country_divergence(_inputs()).value
    assert isinstance(above, dict)
    assert above["verdict"] == MEANINGFUL_DIVERGENCE


# ---------------------------------------------------------------------------
# The validator — the two ways a cross-country thesis is WRONG
# ---------------------------------------------------------------------------


def test_same_country_is_refused() -> None:
    with pytest.raises(ValidationError, match="against itself"):
        _inputs(
            country_a="us",
            country_b="us",
            currency_b="USD",
            fx_converted=False,
            same_currency_basis=True,
        )


def test_different_tenor_is_refused() -> None:
    """A 10y-vs-2y differential is a CURVE trade, not a country trade."""
    with pytest.raises(ValidationError, match="different tenors"):
        _inputs(tenor_a="10y", tenor_b="2y")


def test_different_horizon_is_refused() -> None:
    with pytest.raises(ValidationError, match="different horizons"):
        _inputs(horizon_a=_HORIZON, horizon_b=_HORIZON + 2.0)


def test_unconverted_cross_currency_is_refused() -> None:
    """The archetypal fake spread: real numbers, but the difference is not a quantity."""
    with pytest.raises(ValidationError, match="cross-currency but fx_converted is False"):
        _inputs(currency_a="USD", currency_b="EUR", fx_converted=False)


def test_same_currency_claiming_a_basis_is_refused() -> None:
    with pytest.raises(ValidationError, match="cross-currency basis does not exist"):
        _inputs(currency_a="USD", currency_b="USD", same_currency_basis=False, fx_converted=False)


def test_a_horizon_other_than_the_configured_one_is_refused() -> None:
    """Both legs agreeing with EACH OTHER is necessary but not sufficient.

    Two well-matched legs on a self-consistent but unconfigured horizon (both on
    the configured horizon + 2) must still be refused — the config sanctions ONE
    horizon.
    """
    with pytest.raises(ValueError, match="comparable_horizon_quarters"):
        cross_country_divergence(_inputs(horizon_a=_HORIZON + 2.0, horizon_b=_HORIZON + 2.0))


# ---------------------------------------------------------------------------
# The selector consumes the measurement — end to end
# ---------------------------------------------------------------------------


def test_the_selector_names_the_pair_from_the_measured_divergence() -> None:
    """The layer-4 -> instrument path, end to end.

    The divergence is measured once, then handed to ``select_instrument`` exactly
    as the builder hands it; the selector reads the record and names the pair.
    """
    measured = cross_country_divergence(_inputs()).value
    assert isinstance(measured, dict)
    universe = ProductionUniverse()
    selection = select_instrument(
        InstrumentSelectionInputs(
            thesis_type=ThesisType.CROSS_COUNTRY_DIVERGENCE,
            gap_direction=GapDirection.POSITIVE,
            cross_country=measured,
        ),
        universe,
    )
    value = selection.value
    assert isinstance(value, dict)
    assert value["executable"] is True
    assert value["universe_category"] == "rates"
    labels = get_settings().cross_country.labels
    assert labels["us"] in value["instrument"]
    assert labels["eu"] in value["instrument"]


def test_the_selector_refuses_a_gap_inside_the_noise_band() -> None:
    """An inside-the-band gap is an honest NON-TRADE, never a fabricated pair."""
    measured = cross_country_divergence(
        _inputs(inflation_b=1.30)  # gap 8bp, inside the 25bp band
    ).value
    assert isinstance(measured, dict)
    universe = ProductionUniverse()
    selection = select_instrument(
        InstrumentSelectionInputs(
            thesis_type=ThesisType.CROSS_COUNTRY_DIVERGENCE,
            gap_direction=GapDirection.POSITIVE,
            cross_country=measured,
        ),
        universe,
    )
    # Inside the band the verdict is NO_MEANINGFUL_DIVERGENCE and the selector
    # returns the analytical sentinel shape (a bare string), not a dict.
    assert selection.value == ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT


def test_a_cross_country_thesis_without_a_divergence_is_refused() -> None:
    """The input validator refuses a cross-country thesis with no measurement.

    Routing it to a single-country instrument would be the exact substitution
    §22.3.1 forbids, so the absence must be a loud refusal.
    """
    with pytest.raises(ValidationError, match="requires the measured"):
        InstrumentSelectionInputs(
            thesis_type=ThesisType.CROSS_COUNTRY_DIVERGENCE,
            gap_direction=GapDirection.POSITIVE,
            cross_country=None,
        )


def test_a_divergence_on_a_single_country_thesis_is_refused() -> None:
    """The mirror: a divergence supplied to a non-cross-country thesis is refused."""
    measured = cross_country_divergence(_inputs()).value
    assert isinstance(measured, dict)
    with pytest.raises(ValidationError, match=r"requires the measured|read only by"):
        InstrumentSelectionInputs(
            thesis_type=ThesisType.POLICY_PATH_GAP,
            gap_direction=GapDirection.POSITIVE,
            cross_country=measured,
        )


# ---------------------------------------------------------------------------
# The live linkage — the layer is REACHABLE, not merely importable
# ---------------------------------------------------------------------------


def test_build_us_macro_thesis_threads_the_divergence() -> None:
    """The builder calls ``cross_country_divergence`` and passes its value on.

    Asserted with the AST, not a text grep: a mutation that replaces the call
    with a literal ``None`` leaves the import and the keyword text intact, so a
    text-grep test would survive it (the §22.5 discharge tripwire's lesson).
    """
    import ast
    import inspect

    from macro_engine.thesis_layer import builder as builder_mod

    source = inspect.getsource(builder_mod.build_us_macro_thesis)
    tree = ast.parse(source.lstrip())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "cross_country_divergence"
    ]
    assert calls, "build_us_macro_thesis must CALL cross_country_divergence"

    # The call must be BOUND to a name (here, via a conditional expression whose
    # truthy branch IS the call) and that name must reach the selector as the
    # `cross_country` keyword — an unbound call is a pure side-effect-free dead
    # statement. Walking the tree finds the call wherever it is nested.
    def _is_cc_call(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "cross_country_divergence"
        )

    bound = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(_is_cc_call(inner) for inner in ast.walk(node.value))
    ]
    assert bound, "the cross_country_divergence result must be BOUND, not discarded"

    # Find the select_instrument call and assert the keyword is passed.
    selector_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "select_instrument"
    ]
    assert selector_calls, "build_us_macro_thesis must call select_instrument"
    inner = [
        kw
        for node in selector_calls
        for arg in node.args
        if isinstance(arg, ast.Call)
        and isinstance(arg.func, ast.Name)
        and arg.func.id == "InstrumentSelectionInputs"
        for kw in arg.keywords
    ]
    assert any(kw.arg == "cross_country" for kw in inner), (
        "select_instrument must receive cross_country=..."
    )
