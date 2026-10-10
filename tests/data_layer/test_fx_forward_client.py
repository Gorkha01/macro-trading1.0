"""``data_layer/fx_forward_client.py`` — the OBSERVED forward (Section 22.3).

What these tests are for, and how they differ from the futures tests
--------------------------------------------------------------------
``fx_futures_client`` publishes the rolling ``=F`` future **as a future** and its
tests exist to pin that it is NOT a forward. This module is the exact inverse:
it publishes a **dated** contract, which IS a forward for its own expiry, and
these tests exist to pin the three ways that could still be wrong.

The distinction matters because the failure mode is severe in BOTH directions:
a rolling future passed off as a forward, or a dated forward labelled with the
wrong value date, each produces a plausible-looking wrong CIP deviation — the
SEV-1 class (Section 21.0).

The tests assert, in the order the module's own docs raise them:

(a) **A dated future is a forward, and ``is_forward`` is True** — with an
    ``expiry`` always present. "A forward" without a date is not a forward.
(b) **The rolling ``=F`` is never reachable from this module.** There is no code
    path that returns a rolling price under a forward's name; the function takes
    an ``expiry`` and the default transport resolves dated symbols.
(c) **The CME month/year symbol is built correctly** (``6E`` + ``Z`` + ``26`` =
    ``6EZ6``), because a malformed symbol fetches nothing or the wrong contract.
(d) **A cross is REFUSED, not substituted** (the same rule as the futures
    client, and for the same measured reason).
(e) **The USD-leg rule decides ``is_inverse``**, and ``pair_forward`` inverts so
    the caller reads the pair's own convention — the convention ``CIPInputs``
    requires for BOTH legs.
(f) **The dependency and credential refusals are DISTINCT facts**, each with its
    own message — the D-043 discipline applied to a credential. Neither is a
    silent ``None``.
(g) **A bad price is refused, not published** — non-finite, non-positive, or a
    ``nan`` (which passes every comparison, D-078).
(h) **A returned expiry that disagrees with the request is refused** — a forward
    with the wrong value date is the plausible-looking wrong number.
(i) **``to_cip_forward`` carries the tenor from the READING, and refuses a bad
    spot** — the two ways a caller could feed ``cip_check`` a mismatched leg.
(j) **The economics are right**: with US rates above EUR rates the EUR/USD
    forward sits BELOW spot, so the parity deviation is negative and the foreign
    currency is the stressed side. This is the sign rule, on an OBSERVED forward.

**How the transport is stubbed, and why it matters.** Every test injects a stub
at the ``ForwardTransport`` boundary (the SOURCE of the data), never the function
under test. Stubbing ``fetch_fx_forward`` itself would let a mutant that removed
the guards survive, because the test would no longer call the code being tested
(the fault-injection rule, Lesson 4).
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from macro_engine.data_layer.fx_forward_client import (
    DATABENTO_DATASET,
    CIPForwardKwargs,
    FXForwardReadError,
    FXForwardReading,
    FXForwardUnavailableError,
    _cme_month_code,
    _resolve_dated_symbol,
    fetch_fx_forward,
    to_cip_forward,
)
from macro_engine.models.contracts import utc_now


class StubTransport:
    """A ``ForwardTransport`` that answers with fixed values.

    Injected at the TRANSPORT boundary — the source of the data — so the real
    ``fetch_fx_forward`` (and every guard inside it) runs. ``raise_on_call`` lets
    a test make the transport itself fail, which is how the "any transport
    failure becomes one FXForwardReadError" contract is proved.
    """

    def __init__(
        self,
        close: float,
        *,
        expiry: date | None = None,
        raise_on_call: Exception | None = None,
    ) -> None:
        self.close = close
        self._expiry = expiry
        self._raise = raise_on_call
        self.calls: list[tuple[str, str, str, date]] = []

    def fetch_dated_close(
        self, *, dataset: str, schema: str, symbol: str, expiry: date
    ) -> tuple[float, date]:
        self.calls.append((dataset, schema, symbol, expiry))
        if self._raise is not None:
            raise self._raise
        return (self.close, self._expiry if self._expiry is not None else expiry)


_EXPIRY = date(2026, 12, 14)
_VALUATION = date(2026, 10, 9)


# --------------------------------------------------------------------------
# (a) a dated future IS a forward, and always carries its expiry
# --------------------------------------------------------------------------
def test_a_dated_contract_is_a_forward_with_its_expiry() -> None:
    """``is_forward`` is True AND ``expiry`` is present — the two travel together.

    A forward is a price for a DATE. This module will not return one without the
    date, so the two are asserted together rather than separately: a mutant that
    returned a price with no expiry would fail here.
    """
    reading = fetch_fx_forward(
        "EURUSD",
        expiry=_EXPIRY,
        transport=StubTransport(1.1150),
        valuation_date=_VALUATION,
    )
    assert reading is not None
    assert reading.is_forward is True
    assert reading.expiry == _EXPIRY
    assert reading.tenor_days == (_EXPIRY - _VALUATION).days


def test_the_reading_states_the_forward_is_for_the_technically_correct_date() -> None:
    """The convention string names the settlement date, not just the root."""
    reading = fetch_fx_forward(
        "EURUSD", expiry=_EXPIRY, transport=StubTransport(1.1150), valuation_date=_VALUATION
    )
    assert reading is not None
    assert _EXPIRY.isoformat() in reading.convention
    assert reading.is_inverse is False


# --------------------------------------------------------------------------
# (b) the rolling series is NOT reachable from this module
# --------------------------------------------------------------------------
def test_the_transport_is_asked_for_a_dated_symbol_never_the_rolling_series() -> None:
    """The symbol handed to the transport is the DATED one (``6EZ6``), not ``6E=F``.

    This is the structural guard against the SEV-1 substitution: if the client
    ever requested the rolling ``=F`` series, a forward built from it would be a
    contract-switch artifact. Asserting on the ACTUAL symbol the transport
    received proves the code path, not a comment about it.
    """
    transport = StubTransport(1.1150)
    fetch_fx_forward("EURUSD", expiry=_EXPIRY, transport=transport, valuation_date=_VALUATION)
    assert len(transport.calls) == 1
    _dataset, _schema, symbol, expiry = transport.calls[0]
    assert symbol == "6EZ6"  # Databento: root+month+ONE year digit
    assert "=F" not in symbol
    assert expiry == _EXPIRY


# --------------------------------------------------------------------------
# (c) the CME month/year symbol
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("month", "code"),
    [
        (1, "F"),
        (2, "G"),
        (3, "H"),
        (4, "J"),
        (5, "K"),
        (6, "M"),
        (7, "N"),
        (8, "Q"),
        (9, "U"),
        (10, "V"),
        (11, "X"),
        (12, "Z"),
    ],
)
def test_the_cme_month_code_maps_every_month(month: int, code: str) -> None:
    """All twelve codes, because a wrong one silently fetches the wrong month."""
    assert _cme_month_code(date(2026, month, 1)) == code


def test_the_dated_symbol_is_root_plus_month_plus_one_year_digit() -> None:
    """``6E`` + ``Z`` + ``6`` = ``6EZ6`` — Databento's ONE-year-digit spelling."""
    transport = StubTransport(1.1150)
    fetch_fx_forward(
        "EURUSD", expiry=date(2026, 12, 14), transport=transport, valuation_date=_VALUATION
    )
    assert transport.calls[0][2] == "6EZ6"  # NOT 6EZ26: Databento uses one year digit


# --------------------------------------------------------------------------
# (d) a cross is refused, not substituted
# --------------------------------------------------------------------------
def test_a_cross_pair_returns_none_and_fetches_nothing() -> None:
    """``EURGBP`` has no CME future; it must return None, not a related 6E series.

    Measured: an earlier draft returned ``6E`` for ``EURGBP`` — a wrong answer
    wearing a right-looking label. The assertion is that the transport is NEVER
    CALLED for a cross, so no substitution can occur.
    """
    transport = StubTransport(1.1150)
    assert fetch_fx_forward("EURGBP", expiry=_EXPIRY, transport=transport) is None
    assert transport.calls == []


def test_an_unregistered_pair_returns_none_not_an_error() -> None:
    """'Not in the catalogue' is a different fact from 'the fetch failed'."""
    assert fetch_fx_forward("ZZZZZZ", expiry=_EXPIRY, transport=StubTransport(1.1)) is None


# --------------------------------------------------------------------------
# (e) the USD-leg rule and the inverse convention
# --------------------------------------------------------------------------
def test_a_usd_base_pair_is_the_inverse_and_pair_forward_inverts() -> None:
    """``USDJPY`` is the INVERSE of the future; ``pair_forward`` brings it back.

    The future quotes USD-per-JPY, but the pair quotes JPY-per-USD, so a caller
    needing the pair's own space must read ``pair_forward``. Proven by
    construction: the inverse of the raw close.
    """
    reading = fetch_fx_forward(
        "USDJPY", expiry=_EXPIRY, transport=StubTransport(0.006325), valuation_date=_VALUATION
    )
    assert reading is not None
    assert reading.is_inverse is True
    assert reading.forward == pytest.approx(0.006325)
    assert reading.pair_forward == pytest.approx(1.0 / 0.006325)
    assert "INVERSE" in reading.convention


def test_a_usd_quote_pair_is_same_direction_and_pair_forward_is_unchanged() -> None:
    """``EURUSD`` is the SAME direction; no inversion."""
    reading = fetch_fx_forward(
        "EURUSD", expiry=_EXPIRY, transport=StubTransport(1.1150), valuation_date=_VALUATION
    )
    assert reading is not None
    assert reading.is_inverse is False
    assert reading.pair_forward == pytest.approx(1.1150)


def test_resolve_dated_symbol_returns_none_for_a_cross_and_a_root_for_a_major() -> None:
    """The bare resolver, asserted directly so its two branches are covered."""
    assert _resolve_dated_symbol("EUR", "USD") == ("6E", False)
    assert _resolve_dated_symbol("USD", "JPY") == ("6J", True)
    assert _resolve_dated_symbol("EUR", "GBP") is None


# --------------------------------------------------------------------------
# (f) dependency vs credential — two DISTINCT refusals, neither silent
# --------------------------------------------------------------------------
def test_without_the_package_or_key_the_default_transport_refuses_loudly() -> None:
    """The default transport raises, naming the cause — it is NOT a ``None``.

    In this environment ``databento`` is not installed, so the refusal is the
    dependency one. The assertion is on the TYPE (a discriminated exception) and
    on the message content, not on a textual trace of the code.
    """
    with pytest.raises(FXForwardUnavailableError) as excinfo:
        fetch_fx_forward("EURUSD", expiry=_EXPIRY)
    message = str(excinfo.value)
    assert "databento" in message
    # It is a subclass of the read error, so `except FXForwardReadError` catches it.
    assert isinstance(excinfo.value, FXForwardReadError)


def test_the_unavailable_error_is_a_read_error_subclass() -> None:
    """The hierarchy is the contract: catch the parent for 'could not get one'."""
    assert issubclass(FXForwardUnavailableError, FXForwardReadError)


# --------------------------------------------------------------------------
# (g) a bad price is refused, not published
# --------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [0.0, -1.12, float("nan"), float("inf"), float("-inf")])
def test_a_non_positive_or_non_finite_price_is_refused(bad: float) -> None:
    """Each bad price is INJECTED, so the guard itself is what is proved.

    ``nan`` is the important case: it passes every comparison (D-078), so a
    guard written only as ``price <= 0`` would let it through — this test fails
    if the explicit ``isfinite`` test is removed.
    """
    with pytest.raises(FXForwardReadError):
        fetch_fx_forward(
            "EURUSD", expiry=_EXPIRY, transport=StubTransport(bad), valuation_date=_VALUATION
        )


def test_a_nan_price_is_specifically_refused_by_the_finiteness_guard() -> None:
    """A direct statement of the D-078 case, since it is the subtle one.

    ``nan <= 0`` is False, so a mutant removing ``isfinite`` from the guard would
    be caught by nothing else in the suite — this test is the one that kills it.
    """
    with pytest.raises(FXForwardReadError):
        fetch_fx_forward(
            "EURUSD",
            expiry=_EXPIRY,
            transport=StubTransport(float("nan")),
            valuation_date=_VALUATION,
        )


# --------------------------------------------------------------------------
# (h) a wrong returned expiry is refused
# --------------------------------------------------------------------------
def test_a_transport_returning_the_wrong_expiry_is_refused() -> None:
    """A forward labelled with the wrong value date is the SEV-1 wrong number."""
    wrong = date(2027, 3, 15)
    with pytest.raises(FXForwardReadError):
        fetch_fx_forward(
            "EURUSD",
            expiry=_EXPIRY,
            transport=StubTransport(1.1150, expiry=wrong),
            valuation_date=_VALUATION,
        )


def test_an_expiry_at_or_before_valuation_is_refused() -> None:
    """A contract expiring at/before valuation is spot or past, and divides at 0."""
    with pytest.raises(FXForwardReadError):
        fetch_fx_forward(
            "EURUSD",
            expiry=_VALUATION,
            transport=StubTransport(1.1150),
            valuation_date=_VALUATION,
        )


# --------------------------------------------------------------------------
# (i) to_cip_forward: tenor from the reading, and a bad spot refused
# --------------------------------------------------------------------------
def test_to_cip_forward_takes_the_tenor_from_the_reading() -> None:
    """The horizon the arithmetic uses is the FORWARD's, not a caller's choice.

    A caller passing a 3-month forward against 1-month rates would otherwise get
    a wrong calculation with no complaint; taking ``tenor_days`` from the reading
    makes that impossible by construction.
    """
    reading = fetch_fx_forward(
        "EURUSD", expiry=_EXPIRY, transport=StubTransport(1.1150), valuation_date=_VALUATION
    )
    assert reading is not None
    kwargs = to_cip_forward(
        reading, spot=1.1206, i_domestic_annualized=0.0404, i_foreign_annualized=0.0205
    )
    assert kwargs["tenor_days"] == reading.tenor_days
    assert kwargs["forward"] == pytest.approx(reading.pair_forward)
    assert kwargs["spot"] == pytest.approx(1.1206)
    assert kwargs["day_count_basis"] == "actual_360"
    assert kwargs["quote"] == "domestic_per_foreign"


@pytest.mark.parametrize("bad_spot", [0.0, -1.0, float("nan"), float("inf")])
def test_to_cip_forward_refuses_a_non_positive_or_non_finite_spot(bad_spot: float) -> None:
    """A bad spot would sign-flip or void the parity ratio; refused here."""
    reading = FXForwardReading(
        symbol="EURUSD",
        base="EUR",
        quote="USD",
        root="6E",
        is_inverse=False,
        forward=1.1150,
        expiry=_EXPIRY,
        tenor_days=66,
        dataset=DATABENTO_DATASET,
        source="test",
        retrieved_at=utc_now(),
    )
    with pytest.raises(FXForwardReadError):
        to_cip_forward(
            reading, spot=bad_spot, i_domestic_annualized=0.04, i_foreign_annualized=0.02
        )


def test_to_cip_forward_returns_the_typed_kwargs_for_cip_inputs() -> None:
    """The return is the exact ``CIPInputs`` keyword set (proved by constructing it)."""
    from macro_engine.models.fx_carry import CIPInputs

    reading = fetch_fx_forward(
        "EURUSD", expiry=_EXPIRY, transport=StubTransport(1.1150), valuation_date=_VALUATION
    )
    assert reading is not None
    kwargs: CIPForwardKwargs = to_cip_forward(
        reading, spot=1.1206, i_domestic_annualized=0.0404, i_foreign_annualized=0.0205
    )
    inputs = CIPInputs(**kwargs)
    assert inputs.tenor_days == reading.tenor_days


# --------------------------------------------------------------------------
# (j) the economics: the sign rule, on an OBSERVED forward
# --------------------------------------------------------------------------
def test_us_rates_above_euro_rates_put_the_forward_below_spot() -> None:
    """With i_d > i_f the higher-yielding currency is at a forward DISCOUNT.

    US 4.04% vs euro 2.05%: the EUR/USD forward (1.1150) must sit BELOW spot
    (1.1206), so the parity deviation is NEGATIVE and the FOREIGN (EUR) funding
    is the stressed side. This is the sign rule the live script described —
    asserted here on a DATED contract rather than on a parity-implied number.
    """
    from macro_engine.models.fx_carry import CIPInputs, cip_check

    reading = fetch_fx_forward(
        "EURUSD", expiry=_EXPIRY, transport=StubTransport(1.1150), valuation_date=_VALUATION
    )
    assert reading is not None
    kwargs = to_cip_forward(
        reading, spot=1.1206, i_domestic_annualized=0.0404, i_foreign_annualized=0.0205
    )
    result = cip_check(CIPInputs(**kwargs))
    assert result.value_dict()["deviation_pct"] < 0.0
    assert result.value_dict()["stressed_currency"] == "foreign"


def test_parity_consistent_inputs_give_a_near_zero_deviation() -> None:
    """Sanity: when F EQUALS the parity-implied forward the deviation is ~0.

    Constructs the implied forward from the same inputs so the identity is
    checked against itself — if the conversion or the convention were wrong the
    deviation would NOT be ~0.
    """
    from macro_engine.models.fx_carry import CIPInputs, cip_check

    spot = 1.1206
    i_d, i_f, tenor = 0.0404, 0.0205, 66
    basis = 360.0
    implied = spot * (1.0 + i_d * tenor / basis) / (1.0 + i_f * tenor / basis)

    reading = FXForwardReading(
        symbol="EURUSD",
        base="EUR",
        quote="USD",
        root="6E",
        is_inverse=False,
        forward=implied,
        expiry=_EXPIRY,
        tenor_days=tenor,
        dataset=DATABENTO_DATASET,
        source="test",
        retrieved_at=utc_now(),
    )
    kwargs = to_cip_forward(reading, spot=spot, i_domestic_annualized=i_d, i_foreign_annualized=i_f)
    result = cip_check(CIPInputs(**kwargs))
    assert result.value_dict()["deviation_pct"] == pytest.approx(0.0, abs=1e-9)


# --------------------------------------------------------------------------
# a transport failure becomes ONE fact
# --------------------------------------------------------------------------
def test_any_transport_failure_becomes_a_read_error() -> None:
    """A network fault in the transport is reported as an FXForwardReadError.

    The transport RAISES ``RuntimeError`` (a non-module exception) — the module
    must translate it, not leak it, so a caller has one exception family.
    """
    with pytest.raises(FXForwardReadError):
        fetch_fx_forward(
            "EURUSD",
            expiry=_EXPIRY,
            transport=StubTransport(1.1, raise_on_call=RuntimeError("socket closed")),
            valuation_date=_VALUATION,
        )


def test_a_module_error_from_the_transport_propagates_unchanged() -> None:
    """An ``FXForwardError`` raised INSIDE the transport is not re-wrapped.

    The two come from different layers — a transport that raises the module's
    own error already speaks its language — so re-wrapping would double the
    message without adding a fact.
    """
    with pytest.raises(FXForwardReadError, match="already-classified"):
        fetch_fx_forward(
            "EURUSD",
            expiry=_EXPIRY,
            transport=StubTransport(1.1, raise_on_call=FXForwardReadError("already-classified")),
            valuation_date=_VALUATION,
        )


def test_the_dataset_and_schema_are_passed_to_the_transport() -> None:
    """The dataset/schema are the transport contract; asserted on the real call."""
    transport = StubTransport(1.1150)
    fetch_fx_forward("EURUSD", expiry=_EXPIRY, transport=transport, valuation_date=_VALUATION)
    dataset, schema, _symbol, _expiry = transport.calls[0]
    assert dataset == DATABENTO_DATASET
    assert schema == "ohlcv-1d"


def test_a_finite_positive_price_is_accepted() -> None:
    """The happy-path guard: a normal rate is published, not refused."""
    reading = fetch_fx_forward(
        "GBPUSD", expiry=_EXPIRY, transport=StubTransport(1.3233), valuation_date=_VALUATION
    )
    assert reading is not None
    assert math.isfinite(reading.forward)
    assert reading.forward == pytest.approx(1.3233)
    assert reading.root == "6B"
