"""Phase 2 model tests — Module 7.5 crude GDP nowcast (Section 20.7 / 6.5).

Every expected value below was computed by hand or from an independent live
measurement before the test was run, per Section 21.2 Step 4. The arithmetic is
shown inline so a reader can check the assertion rather than trusting it.

Why this function needs its own test file
-----------------------------------------
Section 6.5 supplies eleven lines of placeholder. Four defects in that
placeholder were measured on this build's live data before the function was
written, and the fourth is the one that governs everything here: **the
specification's formula correlates -0.169 with the quantity it names**, so it
does not measure what it claims to. Each defect is silent in a different way:

1. **The trade term's sign is inverted on 414/414 months.** For an all-negative
   series ``v = -|v|``, ``pct = v[t]/v[t-1] - 1 = |v[t]|/|v[t-1]| - 1`` — the
   two minus signs cancel, so ``pct`` is the percent change of the *absolute
   value*. ``|v|`` grows exactly when the deficit widens, which is
   contractionary. The specification's ``+0.1`` therefore *raises* the nowcast
   when the deficit widens. This test file pins the sign against the raw
   **levels**, which are known independently of the model — the D-009
   cross-series discipline, not a restatement of the code.
2. **A monthly change is added to a quarterly annualized rate.** Both sides of
   the addition must be the same kind of quantity; the specification's delta
   has no quarter-equivalent.
3. **Nominal components are added to a real base.** Two floats carry no unit, so
   the model discloses rather than silently mixing (D-031).
4. **The published accuracy is not reproducible, and the correction does not
   fix it.** Measured one quarter ahead over 137 quarters, the specification's
   form scores 3.558pp, this corrected form 3.026pp, and the prior quarter's
   print *alone* 2.915pp — so the correction, which fixes the adjustment's
   sign, still lands 0.11pp **behind** persistence. The adjustment carries
   0.505 of the magnitude it predicts while explaining 3% of that magnitude's
   variance, so it is over-weighted rather than inert. The model publishes its
   own measured error, a computed ``beats_persistence`` flag, and that
   over-weighting ratio instead of a confidence literal.

The tests below therefore assert four *different* kinds of thing: the sign
against an independent series, the arithmetic of the annualization, the
disclosure of the basis and accuracy limits, and the refusals (a partial
quarter, a non-finite base).

The accuracy figures themselves are NOT re-derived here — they are a live
measurement over 137 quarters, reproduced by ``scripts/live_labor_check.py`` and
recorded in ``config/settings.yaml``. What is tested is that the model *reads*
them, *reports* them, and *computes* ``beats_persistence`` from them rather than
asserting it (D-029: a boolean must travel with its own base rate).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from macro_engine.config import (
    CalibratedValue,
    GdpNowcastAccuracy,
    GdpNowcastSettings,
    get_settings,
)
from macro_engine.models.contracts import ConfidenceInputs, compute_confidence
from macro_engine.models.gdp_nowcast import (
    SimpleGDPNowcastInputs,
    _is_complete_quarter,
    _quarter_annualized_mom,
    simple_gdp_nowcast,
)
from tests.helpers import as_bool, as_float, as_int, as_str


def _leaf(value: float) -> CalibratedValue:
    """A synthetic accuracy leaf, so a test can pin a value it chose.

    Used to break the symmetry between what the model reads and what the test
    expects (PROGRESS.md rule 7). A test that reads its expectation from the
    same accessor the code reads cannot detect a swap or a literal in that
    accessor, because both sides move together.
    """
    return CalibratedValue(
        value=value,
        calibration_status="fitted_assumption",
        note="synthetic — chosen by this test to be distinct from every other leaf",
    )


# ---------------------------------------------------------------------------
# Fixtures. Small, complete quarters so the arithmetic can be checked by eye.
# ---------------------------------------------------------------------------

# Three flat months: every contribution is zero, so the nowcast must equal the
# prior quarter exactly. This is the degenerate case -- if the annualization
# introduced a spurious term, this catches it because the expected value is
# known by construction rather than computed.
FLAT = {"2026-Q1": [0.0, 0.0, 0.0]}

# A clean year-over-year-equivalent quarter: each input up 1.0% per month.
# Annualized: mean 1.0 * 3 = 3.0% for each.
THREE_ONE_PCT = {"2026-Q1": [1.0, 1.0, 1.0]}

# An asymmetric quarter, so the mean cannot be confused with any single month.
# retail:  (2 + 4 + 6)/3 = 4.0  -> *3 = 12.0
# durable: (3 + 0 + 0)/3 = 1.0  -> *3 =  3.0
# trade:   (-2 + 1 + 1)/3 = 0.0 -> *3 =  0.0
ASYMMETRIC = {
    "retail": {"2026-Q1": [2.0, 4.0, 6.0]},
    "durable": {"2026-Q1": [3.0, 0.0, 0.0]},
    "trade": {"2026-Q1": [-2.0, 1.0, 1.0]},
}

PRIOR = 2.0


def _inputs(
    *,
    retail: dict[str, list[float]] | None = None,
    durable: dict[str, list[float]] | None = None,
    trade: dict[str, list[float]] | None = None,
    prior: float = PRIOR,
    published: float | None = None,
) -> SimpleGDPNowcastInputs:
    """Build inputs, defaulting each series to the flat quarter.

    Named arguments so a test cannot silently pass its quarter to the wrong
    series — the failure a positional constructor invites.

    ``published_gdpnow`` is **omitted entirely** when no figure is supplied, so
    the field's own default is exercised. Passing ``published_gdpnow=None``
    explicitly looks equivalent but is not: it overrides the default, so a
    mutation that changed the default from ``None`` to ``0.0`` would be
    invisible to every test here (D-035's M7b survivor, which took two attempts
    to kill for exactly this reason).
    """
    if published is None:
        return SimpleGDPNowcastInputs(
            retail_sales_mom=FLAT if retail is None else retail,
            durable_goods_mom=FLAT if durable is None else durable,
            trade_balance_mom=FLAT if trade is None else trade,
            prior_quarter_annualized=prior,
        )
    return SimpleGDPNowcastInputs(
        retail_sales_mom=FLAT if retail is None else retail,
        durable_goods_mom=FLAT if durable is None else durable,
        trade_balance_mom=FLAT if trade is None else trade,
        prior_quarter_annualized=prior,
        published_gdpnow=published,
    )


def _settings() -> GdpNowcastSettings:
    return get_settings().gdp_nowcast


# ---------------------------------------------------------------------------
# The annualization helper
# ---------------------------------------------------------------------------


def test_annualization_averages_the_quarter_then_scales() -> None:
    """mean(1, 1, 1) = 1.0, times 3 months = 3.0.

    Hand-computed: the specification adds one raw month's change to a quarterly
    rate. With a flat month set every month is 1.0, so the average is 1.0 and
    the annualized figure is 3.0 — three times the monthly change, not equal to
    it. A model that passed the raw month through would report 1.0 here.
    """
    assert _quarter_annualized_mom([1.0, 1.0, 1.0], 3) == pytest.approx(3.0)


def test_annualization_is_the_mean_not_a_single_month() -> None:
    """The asymmetric quarter distinguishes the mean from any member.

    (2 + 4 + 6) / 3 = 4.0, times 3 = 12.0. Picking any single month would give
    6.0, 12.0 or 18.0 — only the first month coincides, which is why the
    fixture is chosen to make the mean unique from the first AND last elements
    as well (2 != 4 != 6).
    """
    assert _quarter_annualized_mom([2.0, 4.0, 6.0], 3) == pytest.approx(12.0)


def test_annualization_rejects_an_empty_quarter() -> None:
    """A quarter with no months cannot be annualized to a rate.

    Named rather than allowed to become ``ZeroDivisionError``: the caller's
    contract is to supply complete quarters, and an empty list reaching here
    means the completeness guard was bypassed.
    """
    with pytest.raises(ValueError, match="no monthly changes"):
        _quarter_annualized_mom([], 3)


def test_completeness_requires_exactly_the_configured_month_count() -> None:
    """A quarter is complete only at ``months_per_quarter`` entries.

    Both directions matter: too few is the partial quarter the model drops
    rather than annualizing short, and too many means the caller has merged two
    quarters and the mean would span a half-year.
    """
    assert _is_complete_quarter([1.0, 2.0, 3.0], 3) is True
    assert _is_complete_quarter([1.0, 2.0], 3) is False
    assert _is_complete_quarter([1.0, 2.0, 3.0, 4.0], 3) is False


# ---------------------------------------------------------------------------
# The core arithmetic
# ---------------------------------------------------------------------------


def test_flat_quarter_leaves_the_nowcast_at_the_prior_rate() -> None:
    """Every input flat => delta 0 => nowcast == prior.

    Known by construction, so this catches an annualization that introduced a
    spurious level term rather than only scaling.
    """
    result = simple_gdp_nowcast(_inputs())
    assert as_float(result, key="delta") == pytest.approx(0.0)
    assert as_float(result, key="nowcast_annualized") == pytest.approx(PRIOR)


def test_contributions_are_the_annualized_change_times_the_configured_share() -> None:
    """Hand-computed, with the shares read from config as the CODE reads them.

    retail  12.0 * 0.679 =  8.148
    durable  3.0 * 0.182 =  0.546
    trade    0.0 * -0.031 = -0.000
    delta                    8.694
    nowcast = 2.0 + 8.694  = 10.694

    The shares are read from the same accessors the model uses, which is
    deliberate: this test pins the ARITHMETIC (annualize, multiply, add), while
    the "no literal" property is pinned separately by mutation. Reading them
    here means a recalibration does not make this test vacuous.
    """
    settings = _settings()
    result = simple_gdp_nowcast(
        _inputs(
            retail=ASYMMETRIC["retail"],
            durable=ASYMMETRIC["durable"],
            trade=ASYMMETRIC["trade"],
        )
    )

    assert as_float(result, key="consumption_contribution") == pytest.approx(
        12.0 * settings.consumption
    )
    assert as_float(result, key="investment_contribution") == pytest.approx(
        3.0 * settings.investment
    )
    assert as_float(result, key="net_exports_contribution") == pytest.approx(
        0.0 * settings.net_exports
    )
    delta = 12.0 * settings.consumption + 3.0 * settings.investment
    assert as_float(result, key="delta") == pytest.approx(delta)
    assert as_float(result, key="nowcast_annualized") == pytest.approx(PRIOR + delta)


def test_the_reported_nowcast_is_recomputable_from_the_reported_contributions() -> None:
    """The cross-field identity — the assertion that catches the D-009 class.

    A shape-only assertion passed every one of three successive wrong
    implementations of a sibling function. What catches a mis-paired or
    mis-signed term is recomputing the headline value from the reported
    components at the reported precision.
    """
    result = simple_gdp_nowcast(
        _inputs(
            retail=ASYMMETRIC["retail"],
            durable=ASYMMETRIC["durable"],
            trade=ASYMMETRIC["trade"],
        )
    )
    recomputed = (
        as_float(result, key="prior_quarter_annualized")
        + as_float(result, key="consumption_contribution")
        + as_float(result, key="investment_contribution")
        + as_float(result, key="net_exports_contribution")
    )
    assert as_float(result, key="nowcast_annualized") == pytest.approx(recomputed, abs=1e-3)
    assert as_float(result, key="delta") == pytest.approx(
        as_float(result, key="consumption_contribution")
        + as_float(result, key="investment_contribution")
        + as_float(result, key="net_exports_contribution"),
        abs=1e-3,
    )


# ---------------------------------------------------------------------------
# The sign correction (D-034) — checked against an INDEPENDENT series
# ---------------------------------------------------------------------------


def test_a_widening_deficit_lowers_the_nowcast() -> None:
    """The central correction, verified against the level and not the percent.

    The algebra: for an all-negative series, ``pct = |v[t]|/|v[t-1]| - 1``,
    because the two minus signs cancel. So ``pct > 0`` means ``|v|`` grew, which
    means the deficit WIDENED, which is contractionary — and a contractionary
    event must LOWER the nowcast. That requires a NEGATIVE weight.

    The fixture is fed as a POSITIVE percent change (the deficit widening) and
    the assertion is that the contribution is negative. Under the
    specification's ``+0.1`` this assertion fails, which is the point: the
    specification's sign is inverted on every observation.
    """
    settings = _settings()
    assert settings.net_exports < 0, (
        "the net-exports weight must be negative: the input is a percent change "
        "of an all-negative series, so a positive value means the deficit "
        "widened (contractionary) and the contribution must lower the nowcast"
    )
    result = simple_gdp_nowcast(_inputs(trade={"2026-Q1": [5.0, 5.0, 5.0]}))
    assert as_float(result, key="net_exports_contribution") < 0


def test_a_narrowing_deficit_raises_the_nowcast() -> None:
    """The mirror case, so a sign flip cannot pass both tests.

    A NEGATIVE percent change of the all-negative balance means the deficit
    narrowed — expansionary — so the contribution must be positive.
    """
    result = simple_gdp_nowcast(_inputs(trade={"2026-Q1": [-5.0, -5.0, -5.0]}))
    assert as_float(result, key="net_exports_contribution") > 0


def test_the_two_trade_directions_move_the_nowcast_oppositely() -> None:
    """Both directions at once, so neither can be satisfied by a constant.

    A pair of tests that each assert a sign on a different fixture cannot catch
    an implementation that returns a fixed sign; comparing the two outputs can.
    """
    widening = simple_gdp_nowcast(_inputs(trade={"2026-Q1": [5.0, 5.0, 5.0]}))
    narrowing = simple_gdp_nowcast(_inputs(trade={"2026-Q1": [-5.0, -5.0, -5.0]}))
    assert as_float(widening, key="net_exports_contribution") < 0
    assert as_float(narrowing, key="net_exports_contribution") > 0
    assert as_float(narrowing, key="nowcast_annualized") > as_float(
        widening, key="nowcast_annualized"
    )


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_non_finite_base_is_refused() -> None:
    """A NaN base would poison every comparison below it.

    ``abs(nan) > x`` is ``False``, so a NaN would make ``beats_persistence``
    report False — a missing observation disguised as a measured result. The
    model refuses instead.
    """
    with pytest.raises(ValueError, match="non-finite"):
        simple_gdp_nowcast(_inputs(prior=float("nan")))


def test_an_infinite_base_is_refused() -> None:
    """Infinity is refused for the same reason, and would silently propagate."""
    with pytest.raises(ValueError, match="non-finite"):
        simple_gdp_nowcast(_inputs(prior=float("inf")))


def test_an_incomplete_quarter_is_refused_when_it_is_the_only_quarter() -> None:
    """A single partial quarter leaves nothing to nowcast, so the model refuses.

    Annualizing two months as three would report a rate no month produced —
    §21.0 rule 4 requires declining rather than substituting.
    """
    with pytest.raises(ValueError, match="complete set"):
        simple_gdp_nowcast(
            _inputs(
                retail={"2026-Q1": [1.0, 2.0]},
                durable={"2026-Q1": [1.0, 2.0]},
                trade={"2026-Q1": [1.0, 2.0]},
            )
        )


def test_a_partial_quarter_is_dropped_and_disclosed_when_a_complete_one_exists() -> None:
    """The latest incomplete quarter is dropped, the prior complete one used.

    Both halves are asserted: that the older quarter was used (so the drop
    happened) AND that a warning says so. An absence-only assertion is half a
    test — a model that silently ignored the situation would pass it.
    """
    result = simple_gdp_nowcast(
        _inputs(
            retail={"2026-Q1": [1.0, 1.0, 1.0], "2026-Q2": [2.0, 2.0]},
            durable={"2026-Q1": [1.0, 1.0, 1.0], "2026-Q2": [2.0, 2.0]},
            trade={"2026-Q1": [1.0, 1.0, 1.0], "2026-Q2": [2.0, 2.0]},
        )
    )
    assert as_int(result, key="quarters_dropped") == 1, (
        "2026-Q2 carries two months where three are required, so it must be dropped"
    )
    assert any("DROPPED" in warning for warning in result.warnings), (
        "the dropped quarter must be disclosed, not silently skipped"
    )
    # And the quarter actually used is the older, complete one.
    assert as_str(result, key="quarters_used") == "2026-Q1"


def test_quarters_used_names_the_quarter_actually_nowcast() -> None:
    """``quarters_used`` must name the LATEST COMPLETE quarter, not the earliest.

    Reported live: the three inputs' latest months are not aligned (retail
    sales publishes a month ahead of durable-goods orders and the trade
    balance), so the current quarter is genuinely incomplete and the model has
    to fall back. This pins that it names the quarter it used rather than the
    latest one it saw.

    **The fixture carries TWO complete quarters (D-035).** The first version
    had only one complete quarter available after the drop, so ``usable[-1]``
    and ``usable[0]`` were the same element and a mutation selecting the
    earliest complete quarter was undetectable by construction. Two complete
    quarters, with DIFFERENT month sets, makes the selection observable in
    ``quarters_used`` *and* in the arithmetic.
    """
    result = simple_gdp_nowcast(
        _inputs(
            retail={"2025-Q4": [1.0, 1.0, 1.0], "2026-Q1": [2.0, 2.0, 2.0], "2026-Q2": [9.0, 9.0]},
            durable={"2025-Q4": [1.0, 1.0, 1.0], "2026-Q1": [2.0, 2.0, 2.0], "2026-Q2": [9.0, 9.0]},
            trade={"2025-Q4": [1.0, 1.0, 1.0], "2026-Q1": [2.0, 2.0, 2.0], "2026-Q2": [9.0, 9.0]},
        )
    )
    assert as_str(result, key="quarters_used") == "2026-Q1", (
        "the model must name the LATEST complete quarter it used, not the earliest "
        "complete one and not the latest key seen"
    )
    # The selection must be visible in the arithmetic too: 2025-Q4 would give
    # mean 1.0 -> annualized 3.0, whereas 2026-Q1 gives mean 2.0 -> 6.0.
    assert as_float(result, key="consumption_contribution") == pytest.approx(
        _settings().consumption * 6.0
    ), (
        "the contributions must come from 2026-Q1 (mean 2.0, annualized 6.0). A "
        "figure built from 2025-Q4 means the earliest quarter was selected"
    )


# ---------------------------------------------------------------------------
# The accuracy disclosure (D-029 / D-034)
# ---------------------------------------------------------------------------


def test_the_measured_accuracy_travels_with_every_result() -> None:
    """The accuracy record must be in ``value``, not only in config or a warning.

    D-034's whole point is that a consumer cannot tell this is not a validated
    nowcast from the number alone. Reporting it in ``value`` means a caller who
    reads only the numeric output still sees it.

    **This test patches in a synthetic accuracy record whose leaves are all
    DISTINCT** (D-035). The first version read its expectation from the same
    accessors the model reads, so a mutation that swapped two leaves — e.g.
    ``persistence_mean_abs_error`` returning ``mean_abs_error_pp`` — moved both
    sides together and passed. PROGRESS.md rule 7 covers literals; this is the
    same failure for *swaps*, and the fix is the same: break the symmetry so no
    two leaves hold the same value and every leaf must be read from its own
    field. The mutation sweep found five such survivors (C1b-C1g).
    """
    accuracy = GdpNowcastAccuracy(
        mean_abs_error_pp=_leaf(1.11),
        persistence_mean_abs_error_pp=_leaf(2.2222),
        correlation_with_realised=_leaf(-0.333),
        spec_form_correlation_with_realised=_leaf(-0.444),
        quarters_measured=_leaf(55),
        realised_positive_rate=_leaf(0.6666),
        delta_overweighting_ratio_value=_leaf(0.0777),
        gdpnow_published_mean_abs_error_pp=_leaf(9.999),
    )
    settings = _settings().model_copy(update={"accuracy": accuracy})
    with patch(
        "macro_engine.models.gdp_nowcast._gdp_nowcast_settings",
        return_value=settings,
    ):
        result = simple_gdp_nowcast(_inputs(published=0.0))

    assert as_float(result, key="mean_abs_error_pp") == pytest.approx(1.11)
    assert as_float(result, key="persistence_mean_abs_error_pp") == pytest.approx(2.2222)
    assert as_float(result, key="correlation_with_realised") == pytest.approx(-0.333)
    assert as_int(result, key="quarters_measured") == 55
    assert as_float(result, key="realised_positive_share") == pytest.approx(0.6666)
    assert as_float(result, key="delta_overweighting_ratio") == pytest.approx(0.0777)

    # Two leaves are published only inside warning text, so they must be read
    # back out of it. Without these two assertions the sweep found mutants of
    # both accessors surviving (C1f, C1g): the leaves were present in every
    # result but no test ever looked at the number they produced.
    assert any("-0.444" in warning for warning in result.warnings), (
        "the specification's form's correlation is published only in the "
        "headline warning; the accessor that reads it must be pinned"
    )
    assert any("9.999" in warning for warning in result.warnings), (
        "the published GDPNow's error is published only in the cross-check "
        "warning; that accessor must be pinned too (C1f survived without this)"
    )


def test_the_cross_check_key_is_absent_when_no_published_figure_is_given() -> None:
    """The cross-check key must be ABSENT, not ``None``, when nothing is supplied.

    D-035's M7b survived twice. The first fix asserted the ``None`` path but
    called ``_inputs(published=None)``, which passes the argument explicitly and
    therefore overrides the field default the mutation changes. The second fix
    was the helper: ``_inputs`` now omits the argument when no figure is given,
    so the field default is what is actually under test.

    Both halves are asserted — absence when omitted, presence when given —
    because an absence-only assertion is half a test (D-035).
    """
    without = simple_gdp_nowcast(_inputs())
    omitted = without.value
    assert isinstance(omitted, dict), "this model publishes a dict"
    assert "gdpnow_cross_check_pp" not in omitted, (
        "no published figure was supplied, so there is no gap to report; a key "
        "here would be a comparison against a field default rather than against data"
    )
    assert not any("published series" in warning for warning in without.warnings), (
        "the cross-check warning must not fire when there is no cross-check"
    )

    with_figure = simple_gdp_nowcast(_inputs(published=1.0))
    supplied = with_figure.value
    assert isinstance(supplied, dict), "this model publishes a dict"
    assert "gdpnow_cross_check_pp" in supplied, "supplying a published figure must add the gap key"


def test_beats_persistence_is_computed_from_the_measured_record() -> None:
    """The flag must follow the numbers, not be asserted.

    An asserted boolean goes stale the moment the accuracy record is updated.
    The assertion here recomputes the comparison from the two error figures the
    model itself reports, so it holds for any record — and separately pins that
    on the shipped record the answer is False, because a model that cannot beat
    persistence must not say it does.

    **The threshold is PATCHED, not read (D-035).** The first version compared
    ``beats_persistence`` against ``improvement > _settings().threshold`` — the
    same accessor the model reads — so returning ``0.0`` from the threshold
    property moved *both* sides: ``-0.11 > 0.0`` is False and so is the flag.
    The mutation survived. This is PROGRESS.md rule 7 applied to the threshold
    rather than to an accuracy leaf.

    **The second version's patch was inert, and that took a further cycle to
    see.** It patched the measured error to 0.1pp, leaving an improvement of
    2.8pp — which clears *any* plausible bar, so a threshold of ``0.0`` changed
    nothing and ``C1h`` survived again. A threshold mutation can only be killed
    by a case whose improvement sits **between zero and the bar**, so the first
    scenario below is deliberately built that way: +0.0153pp against a 0.5pp
    bar. The second scenario pins the opposite direction, so the flag cannot be
    hardcoded to either answer.
    """
    result = simple_gdp_nowcast(_inputs())
    improvement = as_float(result, key="improvement_pp")
    assert improvement == pytest.approx(
        as_float(result, key="persistence_mean_abs_error_pp")
        - as_float(result, key="mean_abs_error_pp"),
        abs=1e-3,
    )
    base = _settings()

    # Scenario 1 — the improvement is POSITIVE but BELOW the bar, so a threshold
    # of 0.0 would flip the answer. This is the case that kills C1h.
    straddling = base.model_copy(
        update={
            "accuracy": base.accuracy.model_copy(
                update={"mean_abs_error_pp": _leaf(2.90)}  # improvement = +0.0153pp
            ),
            "persistence_improvement_threshold_pp": _leaf(0.5),
        }
    )
    with patch("macro_engine.models.gdp_nowcast._gdp_nowcast_settings", return_value=straddling):
        below_bar = simple_gdp_nowcast(_inputs())
    assert as_bool(below_bar, key="beats_persistence") is False, (
        "the improvement is +0.0153pp against a 0.5pp bar, so the flag must be "
        "False. A True here means the threshold is not being read — a property "
        "returning 0.0 would let any positive improvement pass (D-035's C1h)."
    )

    # Scenario 2 — the improvement CLEARS the bar, so the flag cannot be a
    # hardcoded False either.
    clearing = base.model_copy(
        update={
            "accuracy": base.accuracy.model_copy(update={"mean_abs_error_pp": _leaf(0.1)}),
            "persistence_improvement_threshold_pp": _leaf(0.05),
        }
    )
    with patch("macro_engine.models.gdp_nowcast._gdp_nowcast_settings", return_value=clearing):
        above_bar = simple_gdp_nowcast(_inputs())
    assert as_bool(above_bar, key="beats_persistence") is True, (
        "the improvement is +2.8153pp against a 0.05pp bar, so the flag must be "
        "True — otherwise it is not computed from the numbers at all"
    )

    # And on the shipped record, the answer is False: the model does not beat
    # persistence, and must not say it does.
    assert as_bool(result, key="beats_persistence") is False, (
        "on the shipped record this model's error exceeds the persistence "
        "benchmark, so the flag must be False; a True here means either the "
        "record changed materially or the comparison was inverted"
    )


def test_the_headline_warning_says_the_model_is_not_a_validated_nowcast() -> None:
    """The first warning must carry the negative result.

    A consumer who reads one warning must get the true one. Matching a phrase
    from the message BODY rather than the opening, and asserting exactly one
    match, so a mutation that empties the warning cannot pass on a substring
    that survives elsewhere in the list.

    The phrase asserted is "ties that benchmark", which replaced "does NOT beat
    that benchmark" in D-035. Measured one quarter ahead on 137 quarters the
    model is 3.026pp against a 2.915pp benchmark — 0.11pp WORSE, but inside the
    0.15pp tolerance the head-to-head comparison carries, so the honest word is
    "ties" rather than a claimed loss. The old wording asserted a failure the
    data does not resolve to that precision; the model fails to *improve*, and
    that is what the warning must say.
    """
    result = simple_gdp_nowcast(_inputs())
    matches = [w for w in result.warnings if "ties that benchmark" in w]
    assert len(matches) == 1, (
        f"expected exactly one warning carrying the negative result; found {len(matches)}"
    )
    assert result.warnings[0] is matches[0], (
        "the negative result must be the FIRST warning, because a reader who "
        "reads only one must read this one"
    )


def test_the_headline_warning_reports_the_error_and_the_benchmark() -> None:
    """The negative result must be quantified, not merely asserted (D-029).

    A warning that says "not validated" without the numbers cannot be checked
    by a reader. Both figures come from config, so a stale record surfaces here
    rather than being described in prose that never changes.
    """
    result = simple_gdp_nowcast(_inputs())
    accuracy = _settings().accuracy
    headline = result.warnings[0]
    assert f"{accuracy.mean_abs_error:.3f}pp" in headline, (
        "the headline warning must state this model's measured error"
    )
    assert f"{accuracy.persistence_mean_abs_error:.3f}pp" in headline, (
        "the headline warning must state the persistence benchmark it is "
        "compared against, or the error figure means nothing"
    )
    assert f"{accuracy.quarters}" in headline, (
        "the sample size must travel with the figure — 136 quarters is not many"
    )


def test_the_overweighting_ratio_is_published_and_disclosed() -> None:
    """D-035: the reason the model ties persistence must travel with the output.

    The finding is not "the model is bad" but "the adjustment is roughly half
    the size of the quantity it predicts while explaining 3% of its variance —
    correctly signed, over-weighted". Without this the reader sees a number that
    lands behind the prior quarter's print and cannot tell whether that is a
    tuning failure that a better weight would fix, or structure.
    """
    result = simple_gdp_nowcast(_inputs())
    value = result.value
    assert isinstance(value, dict), "this model publishes a dict"
    assert "delta_overweighting_ratio" in value, (
        "the over-weighting ratio must be published — it is the D-035 disclosure"
    )
    assert value["delta_overweighting_ratio"] == _settings().accuracy.delta_overweighting_ratio, (
        "the published ratio must be the measured one from config"
    )
    matches = [w for w in result.warnings if "not a tuning failure" in w]
    assert len(matches) == 1, (
        f"the structural reason must be warned about exactly once; found {len(matches)}"
    )
    assert "structural, not a tuning failure" in matches[0], (
        "the warning must say the over-weighting is structural, because a reader "
        "who reads a badly-scaled term assumes a tuning problem and goes looking "
        "for a better weight — which the sweep proves recovers only 0.0395pp"
    )
    assert "R^2" in matches[0] and "half the needed size" in matches[0], (
        "the warning must say WHY the term is over-weighted — a right-signed "
        "signal at roughly half the needed magnitude — rather than only that the "
        "delta is small relative to the target"
    )


def test_the_base_rate_warning_states_the_positive_quarter_share() -> None:
    """D-029: a sign-agreement claim must travel with its base rate.

    The model's ``interpretation`` reports how far it is from the prior quarter,
    which a reader could take as directional information. The base rate is what
    makes that uninformative, so it must be in a warning and must name the
    figure from config.
    """
    result = simple_gdp_nowcast(_inputs())
    share = _settings().accuracy.realised_positive_share
    formatted = f"{share:.1%}"
    matches = [w for w in result.warnings if formatted in w and "positive" in w]
    assert len(matches) == 1, (
        f"expected the base rate {formatted} to appear in exactly one warning; found {len(matches)}"
    )


def test_the_basis_mismatch_is_disclosed() -> None:
    """The nominal-versus-real mix must be warned about, not silent.

    Two floats carry no unit (D-031), so the model cannot detect the mix and
    must state it. Matched on a phrase from the body.
    """
    result = simple_gdp_nowcast(_inputs())
    matches = [w for w in result.warnings if "NOMINAL" in w and "REAL" in w]
    assert len(matches) == 1, "the nominal/real basis mismatch must be disclosed once"


def test_the_net_exports_sign_correction_is_disclosed() -> None:
    """The sign fix must be auditable from the output alone."""
    result = simple_gdp_nowcast(_inputs())
    matches = [w for w in result.warnings if "NEGATIVE" in w and "net exports" in w]
    assert len(matches) == 1, "the net-exports sign correction must be disclosed once"


def test_persistence_failure_carries_its_own_warning_when_it_fails() -> None:
    """The ``beats_persistence`` False branch must add a warning explaining the bar.

    Presence asserted alongside the value, so the two cannot disagree.
    """
    result = simple_gdp_nowcast(_inputs())
    if as_bool(result, key="beats_persistence") is False:
        matches = [w for w in result.warnings if "beats_persistence is False" in w]
        assert len(matches) == 1
        assert "threshold is deliberately set above" in matches[0]


# ---------------------------------------------------------------------------
# The live cross-check
# ---------------------------------------------------------------------------


def test_the_cross_check_key_is_absent_without_a_published_figure() -> None:
    """A model must not require an input it cannot always obtain.

    §21.0 rule 4: the published GDPNow figure may not be available to the
    thesis layer, so it is optional and its derived key must be absent rather
    than ``None`` — a ``None`` would read as "the gap is unknown" where the
    truth is "no comparison was requested".
    """
    result = simple_gdp_nowcast(_inputs())
    value = result.value
    assert isinstance(value, dict)
    assert "gdpnow_cross_check_pp" not in value
    assert not any("gdpnow_cross_check_pp" in w for w in result.warnings)


def test_the_cross_check_is_the_gap_and_its_caveat_is_attached() -> None:
    """When supplied, the gap is nowcast minus published, and warned about.

    The published series is a FINAL per-quarter record rather than a real-time
    nowcast, so a reader who does not know that will read the gap as this
    model's error. Both halves asserted.
    """
    result = simple_gdp_nowcast(_inputs(published=2.5))
    expected = as_float(result, key="nowcast_annualized") - 2.5
    assert as_float(result, key="gdpnow_cross_check_pp") == pytest.approx(expected, abs=1e-3)
    matches = [w for w in result.warnings if "SETTLED numbers" in w]
    assert len(matches) == 1, "the cross-check must carry its settled-numbers caveat"
    assert "not this model's error" in matches[0]


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_confidence_is_computed_not_asserted() -> None:
    """§22.8: ``compute_confidence`` is the only producer.

    The model leans on uncalibrated weights and mixes bases, so the heuristic
    penalty applies; it does NOT depend on an unobservable, because its base is
    a realised GDP print rather than r*, u* or potential output. Both facts
    asserted, so a mutation that flipped either flag is caught.
    """
    result = simple_gdp_nowcast(_inputs())
    expected = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=False,
            source_independence_count=0,
        )
    )
    assert result.confidence == pytest.approx(expected)
    # The specification's literal was 0.35, "deliberately LOW". A computed value
    # that happened to equal it would be a coincidence worth knowing about.
    assert result.confidence != 0.35


def test_extra_inputs_are_forbidden() -> None:
    """``extra="forbid"`` on the input model, so a typo cannot be ignored."""
    with pytest.raises(ValueError, match="extra_forbidden"):
        SimpleGDPNowcastInputs(
            retail_sales_mom=FLAT,
            durable_goods_mom=FLAT,
            trade_balance_mom=FLAT,
            prior_quarter_annualized=PRIOR,
            retail_sales_mom_pct=FLAT,  # type: ignore[call-arg]
        )


def test_the_model_name_and_inputs_are_the_specification_s_interface() -> None:
    """§22.1 / §22.13: the name and input surface are retained.

    The specification's formula is corrected, not replaced by a second
    function — so the thesis layer consumes what Section 6.5 says it will.
    """
    result = simple_gdp_nowcast(_inputs())
    assert result.model_name == "simple_gdp_nowcast"
    assert result.country == "us"
    assert set(result.inputs_used) == {
        "retail_sales_mom",
        "durable_goods_mom",
        "trade_balance_mom",
        "prior_quarter_annualized",
    }
