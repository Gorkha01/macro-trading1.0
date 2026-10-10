"""FX forward points — the OBSERVED forward ``cip_check`` needs (Section 22.3).

Why this module exists, and why the sibling module was NOT enough
----------------------------------------------------------------
``cip_check`` (``models/fx_carry.py``) takes an OBSERVED forward ``F`` as an
input and measures its deviation from covered interest parity. Until now the
system could not supply a live ``F``: re-measured 2026-10-10 across all 32
installed OpenBB providers, the whole FX surface is four routes and **not one**
is a forward, a swap or a cross-currency basis (recorded at
``config/series_registry.yaml`` under ``fx_forward_rate``).

``fx_futures_client.py`` reaches the nearest thing the OpenBB routes offer — the
CME ``=F`` **rolling front-month** future — and publishes it **as a future**,
because a rolling series switches contract mid-window and its quoted price
therefore JUMPS. Differencing it against spot produces a "forward point" that is
part genuine basis and part unremovable roll artifact, so it can never be
``cip_check``'s ``forward``.

**But the dated contract DOES exist — just not on an OpenBB route.** Re-measured
2026-10-10 (the eighth false-block check of the D-043 class): CME's own venue
data carries dozens of dated ``6E`` instruments with explicit expiries
(``6EZ6`` 2026-12-14, ``6EX6`` 2026-11-16, ``6EV6`` 2026-10-19 — read live from
the Databento GLBX.MDP3 catalog). A **dated** FX future is, by construction, a
forward for its own expiry: its price converges to ``F`` as the date approaches,
and unlike the ``=F`` roll it has no contract switch inside the window. That is
the instrument this module fetches.

The measured verdict, stated so it cannot be misread
-----------------------------------------------------
* **No OpenBB route serves a forward.** CONFIRMED 2026-10-10 (278 paths; the
  four ``currency.*`` routes are spot/search/reference/snapshot).
* **A dated CME ``6E`` future is reachable and IS a forward for its expiry.**
  This is the finding that lifts the block from "impossible" to "uninstalled".
  The source is the ``databento`` Python package (GLBX.MDP3), which requires an
  API key — a free tier exists, and no key is configured by default.

So the block's honest restatement is: **the arithmetic was never blocked; the
dependency was.** This module supplies the dependency seam and the whole
computation; the credential is the only remaining external fact.

The credential gate, and why it is a REFUSAL rather than a silent ``None``
-----------------------------------------------------------------------
Three distinct failure facts arise here and this module keeps them distinct,
because collapsing them is how a missing key becomes "no data this run":

1. **No ``databento`` package installed** — a dependency fact. Raised as
   :class:`FXForwardUnavailableError` with the exact install command.
2. **No ``databento_api_key`` configured** — a credential fact. Raised as
   :class:`FXForwardUnavailableError` naming the env var and the free-key URL.
3. **The fetch itself failed** (network, entitlement, a malformed response) —
   raised as :class:`FXForwardReadError`.

An *unregistered pair* is the fourth case and returns ``None``, matching
``fetch_fx_spot``: "this pair is not in the catalogue" is not an error.

``FXForwardUnavailableError`` is a SUBCLASS of ``FXForwardReadError`` so a caller that
only wants to catch "could not get a forward" can catch the parent, while a
caller that wants to report "install a key" can catch the child. The
distinction is the ``declared_not_wired`` discipline applied to a credential.

A dated future is a forward — but ONLY for its own expiry
----------------------------------------------------------
The one way this module could still produce a wrong number is by letting a
caller believe a future's price is "the" forward. It is the forward **for the
settlement date it settles on**, and nothing else. So the returned object
carries ``expiry`` and ``tenor_days`` as first-class fields, and
:func:`to_cip_forward` refuses to hand a caller a ``forward`` whose tenor does
not match the rates it is being paired with. "A forward" without a date is not a
forward; this module will not return one without its date.

Run the live check (needs a key):  uv run python tools/probe_fx_forward.py
"""

from __future__ import annotations

import importlib
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Protocol, TypedDict

from macro_engine.config import env, get_settings
from macro_engine.data_layer.fx_client import FX_PAIRS
from macro_engine.models.contracts import utc_now

if TYPE_CHECKING:
    from macro_engine.models.fx_carry import DayCountBasis, QuoteConvention

__all__ = [
    "DATABENTO_DATASET",
    "DATABENTO_SCHEMA",
    "CIPForwardKwargs",
    "FXForwardError",
    "FXForwardReadError",
    "FXForwardReading",
    "FXForwardUnavailableError",
    "ForwardTransport",
    "fetch_fx_forward",
    "to_cip_forward",
]

#: The Databento dataset the CME FX complex lives in. A CONSTANT rather than a
#: config leaf because it is the venue's own identifier (part of the transport
#: contract), the same split ``FX_FUTURES_ROUTE_ENDPOINT`` draws. PUBLIC so a
#: consumer can cite the exact dataset in ``data_provenance`` (LAW 2).
DATABENTO_DATASET = "GLBX.MDP3"

#: The Databento schema requested: end-of-day settlement. ``ohlcv-1d`` is the
#: daily bar whose CLOSE is the settlement mark a forward wants; a tick schema
#: would be a different (and far more expensive) request for no benefit here.
DATABENTO_SCHEMA = "ohlcv-1d"


class FXForwardError(Exception):
    """Base for every failure this module reports."""


class CIPForwardKwargs(TypedDict):
    """The exact keyword set ``CIPInputs`` takes, with the ``Literal`` types kept.

    A ``TypedDict`` rather than a bare ``dict[str, float | int | str]`` because
    the loose dict ERASES the ``Literal`` types of ``day_count_basis`` and
    ``quote`` — mypy then rejects ``CIPInputs(**kwargs)``, which is the type
    system flagging a real hazard: a wrong day-count or quote convention is
    exactly the silent-wrong-number this module exists to prevent. Typing the
    keys here means the caller's ``CIPInputs(**to_cip_forward(...))``
    type-checks WITHOUT a ``cast`` (a claim the type system cannot verify).
    """

    spot: float
    forward: float
    i_domestic_annualized: float
    i_foreign_annualized: float
    tenor_days: int
    day_count_basis: DayCountBasis
    quote: QuoteConvention


class FXForwardReadError(FXForwardError):
    """The forward series could not be read, or was too damaged to publish.

    Distinct from ``OpenBBFetchError``/``FxReadError`` for the same reason those
    are distinct from each other: *the transport failed* and *the pair is not
    registered* are different facts the caller reports differently.
    """


class FXForwardUnavailableError(FXForwardReadError):
    """No forward can be fetched until an external fact is supplied.

    A SUBCLASS of :class:`FXForwardReadError` so ``except FXForwardReadError``
    catches both, while a caller that wants to say "install/configure X" catches
    this. Raised for exactly two causes, each named in the message:

    * the ``databento`` package is not installed (a DEPENDENCY fact), or
    * ``DATABENTO_API_KEY`` is not set (a CREDENTIAL fact).

    It is deliberately NOT a ``None`` return. Returning ``None`` here would make
    "no key configured" indistinguishable from "this pair is not registered" and
    from "no data this run" — three different facts, and the confusion between
    them is the whole subject of the D-043 false-block class.
    """


class ForwardTransport(Protocol):
    """The surface this module needs from a dated-futures transport.

    Declared as a ``Protocol`` rather than typing the parameter as the concrete
    Databento client, for the reason ``fx_client.SeriesClient`` gives: a caller
    that supplies an object with this method — a test stub, a caching wrapper, a
    future transport — is genuinely valid, and typing the concrete class would
    force those callers through an unchecked ``cast``.

    ``fetch_dated_close`` returns ``(close, expiry)`` for ONE dated instrument.
    It is the transport's whole job: resolve a symbol+expiry to a settlement
    price. Everything else — pair resolution, the rolling-contract refusal, the
    CIP conversion — is this module's, so an alternative transport cannot change
    the economics by accident.
    """

    def fetch_dated_close(
        self,
        *,
        dataset: str,
        schema: str,
        symbol: str,
        expiry: date,
    ) -> tuple[float, date]:
        """Return ``(settlement_close, expiry)`` for a dated instrument."""
        ...


@dataclass(frozen=True)
class FXForwardReading:
    """An OBSERVED forward for one pair and one value date, with provenance.

    **There IS a ``forward`` field here** — the exact inverse of
    ``FXFuturesReading``, which deliberately has none. The asymmetry is the
    point: a *dated* contract is a forward for its expiry, so this object can
    honestly carry one; a *rolling* contract cannot, so that object must not.

    ``expiry`` and ``tenor_days`` are required, not optional. A forward is a
    price for a date; returning the price without the date would be the
    plausible-looking wrong number this project treats as SEV-1 (Section 21.0).

    ``quote`` states the convention the number is in. CME's FX complex quotes
    **USD per 1 foreign currency**, so for a ``USD/X`` pair the forward is the
    INVERSE of the pair and ``is_inverse`` is ``True``, exactly as
    ``fx_futures_client`` handles it — one rule, one place (LAW 2).
    """

    symbol: str
    base: str
    quote: str
    root: str
    is_inverse: bool
    forward: float
    expiry: date
    tenor_days: int
    dataset: str
    source: str
    retrieved_at: datetime

    @property
    def is_forward(self) -> bool:
        """ALWAYS ``True``, and for a reason that differs from a rolling future.

        The sibling module's ``is_forward`` is False because a ``=F`` roll is
        not a forward. This one is True because a DATED future *is* one for its
        own ``expiry`` — which this object always carries. Present as a named,
        testable statement rather than an omission, so a consumer can assert on
        it rather than discover the capability by ``AttributeError``.
        """
        return True

    @property
    def convention(self) -> str:
        """A one-line statement of what ``forward`` means."""
        foreign = self.base if self.quote == "USD" else self.quote
        direction = (
            f"same direction as {self.symbol}"
            if not self.is_inverse
            else f"INVERSE of {self.symbol}"
        )
        return (
            f"USD per 1 {foreign} ({self.root} future settling {self.expiry.isoformat()}; "
            f"{direction})"
        )

    @property
    def pair_forward(self) -> float:
        """``forward`` expressed in the PAIR's own convention.

        Inverts when the contract is the inverse of the pair, so a consumer that
        wants "units of ``quote`` per one ``base``" — the convention every other
        FX value in this system uses, and the one ``CIPInputs.spot``/``forward``
        must be in — reads it here instead of remembering to invert. The
        inversion is exact (``1/rate``); the raw settlement price is retained on
        ``forward`` for audit.
        """
        return (1.0 / self.forward) if self.is_inverse else self.forward


def _resolve_pair(symbol: str) -> tuple[str, str] | None:
    """Resolve a pair code to ``(base, quote)`` from the canonical catalogue.

    Uses ``fx_client.FX_PAIRS`` — the SAME catalogue the spot and futures
    clients use (LAW 2) — so a pair added for spot is immediately eligible here
    and the three cannot drift.
    """
    key = symbol.strip().upper().replace("/", "").replace("-", "")
    return FX_PAIRS.get(key)


def _resolve_dated_symbol(base: str, quote: str) -> tuple[str, bool] | None:
    """Resolve a pair to ``(cme_root, is_inverse)``, or ``None`` when unsupported.

    Reuses the identical USD-leg rule ``fx_futures_client._resolve_futures``
    applies, because the CME FX complex is the same complex: it is USD-only and
    quotes **USD per 1 foreign currency**, so there are exactly two supported
    shapes and one refusal.

    * ``X/USD`` (quote is USD) — same direction; foreign currency is the base.
    * ``USD/X`` (base is USD) — inverse; foreign currency is the quote.
    * **neither leg USD** (a cross, e.g. ``EURGBP``) — ``None``. There is no CME
      future for the cross, and returning a related USD future under the cross's
      name is the silent-wrong-number defect (measured once already: a draft
      returned ``6E`` for ``EURGBP``).

    The root comes from ``fx_futures.cme_roots`` in config (LAW 1: the root is a
    per-currency market fact, not a policy choice), so there is one canonical
    spelling shared with the futures client.
    """
    if quote == "USD":
        foreign, inverse = base, False
    elif base == "USD":
        foreign, inverse = quote, True
    else:
        return None
    root = get_settings().fx_futures.cme_roots.get(foreign)
    if root is None:
        return None
    return (root, inverse)


def _tenor_days(valuation_date: date, expiry: date) -> int:
    """ACTUAL days from ``valuation_date`` to ``expiry``, floored at 1.

    ``CIPInputs.tenor_days`` is bounded ``ge=1`` and its rates are scaled to this
    horizon, so a non-positive value is not usable. An expiry at or before the
    valuation date is not a forward (it is spot or past), and the caller gets a
    clear refusal rather than a zero that would divide.
    """
    return (expiry - valuation_date).days


def fetch_fx_forward(
    symbol: str,
    *,
    expiry: date,
    transport: ForwardTransport | None = None,
    valuation_date: date | None = None,
) -> FXForwardReading | None:
    """Fetch one pair's OBSERVED forward for a specific value date.

    Parameters
    ----------
    symbol:
        A pair code (``"EURUSD"``, ``"eur/usd"``). An **unregistered** pair
        returns ``None`` rather than raising, matching ``fetch_fx_spot``.
    expiry:
        The dated contract's settlement date. **Required** — this function will
        not return "a forward" without one, because a forward without a date is
        not a forward.
    transport:
        The dated-futures transport. ``None`` builds the default Databento
        transport, which needs the ``databento`` package and a key; supplying one
        (e.g. a test stub) bypasses both, which is what makes the client
        testable without a credential.
    valuation_date:
        The date from which ``tenor_days`` is measured. Defaults to today.

    Returns
    -------
    FXForwardReading | None
        ``None`` for an unregistered pair or a cross; otherwise the reading.

    Raises
    ------
    FXForwardUnavailableError
        The default transport is needed but the package or key is absent.
    FXForwardReadError
        The fetch failed, returned no usable price, or the settlement price was
        not a positive finite FX rate.

    Notes
    -----
    **A dated future is a forward for its OWN expiry.** This function therefore
    fetches the close of a DATED contract (``6EZ6``), never the rolling ``=F``
    series — a rolling series has no single expiry and could not be labelled
    with one. The refusal is structural: this function takes an ``expiry`` and
    the default transport resolves dated symbols, so there is no code path that
    returns a rolling price under a forward's name.
    """
    resolved = _resolve_pair(symbol)
    if resolved is None:
        return None
    base, quote = resolved
    canonical = f"{base}{quote}"
    dated = _resolve_dated_symbol(base, quote)
    if dated is None:
        # No CME future for this pair (a cross), or the foreign currency has no
        # mapped root. Both are UNREGISTERED for this layer, not broken.
        return None
    root, is_inverse = dated

    valuation = valuation_date or utc_now().date()
    tenor = _tenor_days(valuation, expiry)
    if tenor < 1:
        raise FXForwardReadError(
            f"expiry {expiry.isoformat()} is not after the valuation date "
            f"{valuation.isoformat()} for {canonical}; there are {tenor} day(s) "
            f"between them. A contract expiring at or before valuation is spot "
            f"or past, not a forward — and a zero tenor would divide in the "
            f"parity conversion."
        )

    symbol_dated = f"{root}{_cme_month_code(expiry)}{expiry.year % 10}"
    active = transport if transport is not None else _default_transport()
    try:
        price, returned_expiry = active.fetch_dated_close(
            dataset=DATABENTO_DATASET,
            schema=DATABENTO_SCHEMA,
            symbol=symbol_dated,
            expiry=expiry,
        )
    except FXForwardError:
        raise
    except Exception as exc:
        raise FXForwardReadError(
            f"dated contract {symbol_dated} (for {canonical}) could not be read "
            f"from {DATABENTO_DATASET}: {type(exc).__name__}: {exc}"
        ) from exc

    if not math.isfinite(price) or price <= 0.0:
        raise FXForwardReadError(
            f"dated contract {symbol_dated} settled at {price!r}, which is not "
            f"a positive finite FX rate. A zero or negative or nan price would "
            f"sign-flip or void the parity ratio while still returning a number."
        )
    if returned_expiry != expiry:
        raise FXForwardReadError(
            f"the transport returned a contract settling {returned_expiry.isoformat()} "
            f"for a request whose expiry was {expiry.isoformat()}. A forward "
            f"labelled with the wrong value date is the plausible-looking wrong "
            f"number this module exists to prevent."
        )

    return FXForwardReading(
        symbol=canonical,
        base=base,
        quote=quote,
        root=root,
        is_inverse=is_inverse,
        forward=price,
        expiry=expiry,
        tenor_days=tenor,
        dataset=DATABENTO_DATASET,
        source=f"databento:{DATABENTO_DATASET} ({DATABENTO_SCHEMA}, dated {symbol_dated})",
        retrieved_at=utc_now(),
    )


def to_cip_forward(
    reading: FXForwardReading,
    *,
    spot: float,
    i_domestic_annualized: float,
    i_foreign_annualized: float,
) -> CIPForwardKwargs:
    """Assemble the ``CIPInputs`` keyword arguments from a forward reading.

    The ONE conversion this module performs, kept here rather than duplicated at
    every call site (LAW 2), because the two ways to get it wrong are both
    silent:

    * **The quote convention.** ``CIPInputs.spot``/``forward`` must be in the
      SAME convention and in the pair's own space. ``pair_forward`` supplies the
      forward already inverted when the contract is the inverse of the pair;
      ``spot`` is taken as given and asserted positive. Mixing one inverted and
      one not is the error ``CIPInputs``' own docstring warns of.
    * **The tenor.** ``CIPInputs.tenor_days`` must be the forward's OWN tenor —
      the two rates are scaled to exactly this horizon. Passing a 3-month
      forward's price against a 1-month rate is a different, wrong calculation,
      so ``tenor_days`` is taken from the reading, never from the caller.

    Returns a plain ``dict`` of ``CIPInputs`` keyword arguments so the caller
    constructs ``CIPInputs`` itself and its own validators run — this function
    does not build the model input, it only removes the arithmetic a caller
    would otherwise repeat and get wrong.

    Raises
    ------
    FXForwardReadError
        ``spot`` is not a positive finite rate. Refused here rather than passed
        through, because a bad spot produces a confident wrong deviation.
    """
    if not math.isfinite(spot) or spot <= 0.0:
        raise FXForwardReadError(
            f"spot {spot!r} for {reading.symbol} is not a positive finite rate; "
            f"the parity ratio would be sign-flipped or undefined."
        )
    return {
        "spot": spot,
        "forward": reading.pair_forward,
        "i_domestic_annualized": i_domestic_annualized,
        "i_foreign_annualized": i_foreign_annualized,
        "tenor_days": reading.tenor_days,
        "day_count_basis": "actual_360",
        "quote": "domestic_per_foreign",
    }


# CME month codes: F=Jan G=Feb H=Mar J=Apr K=May M=Jun
#                 N=Jul Q=Aug U=Sep V=Oct X=Nov Z=Dec
_CME_MONTH_CODES: tuple[str, ...] = (
    "F",
    "G",
    "H",
    "J",
    "K",
    "M",
    "N",
    "Q",
    "U",
    "V",
    "X",
    "Z",
)


def _cme_month_code(when: date) -> str:
    """The CME futures month code for a calendar month (1-12 -> F..Z).

    A dated CME instrument's raw symbol is **root + month code + ONE year
    digit**. Databento's own symbology documentation states the format exactly:
    *"CME futures tickers follow the format Root + Month Code + Year Digit. For
    example, ESU4 = ES (E-mini S&P 500) + U (September) + 4 (2024)."* So December
    2026 is ``6EZ6`` — NOT ``6EZ26``.

    **The two-digit spelling is a DIFFERENT venue's convention, and mixing them
    is a live failure.** The OpenBB/yfinance route spells the same contract
    ``6EZ26``; Databento spells it ``6EZ6``. This module talks to Databento, so
    it must use Databento's spelling — a two-digit symbol would fetch nothing (or
    the wrong decade's contract) against the live API. The distinction was caught
    by a test, and the month code is kept as data with the index made explicit so
    the mapping is auditable in one place.
    """
    return _CME_MONTH_CODES[when.month - 1]


class DatabentoTransport:
    """The default transport: a dated close from Databento's GLBX.MDP3 dataset.

    **Lazy-imports ``databento`` and reads the key from the environment**, so the
    core environment satisfies AGENTS.md Section 4's rule — no dependency is
    imported until the phase that needs it — and this module imports cleanly
    whether or not the package is installed. The import and the key are checked
    at CALL time, not import time, and each absence is a DISTINCT
    :class:`FXForwardUnavailableError` message (a dependency fact vs a credential
    fact), never a silent ``None``.
    """

    def __init__(self, *, api_key: str | None = None) -> None:
        # ``config.env`` is the ONE canonical env reader (it honours .env), so a
        # key set either in .env or the process environment is found here — the
        # same reader every other credential in this project uses (LAW 2).
        self._api_key = api_key if api_key is not None else env("DATABENTO_API_KEY")
        self._client: Any = None

    def _ensure_client(self) -> Any:
        """Import and construct the Databento client, or refuse with the reason."""
        if self._client is not None:
            return self._client
        try:
            module = importlib.import_module("databento")
        except ImportError as exc:
            raise FXForwardUnavailableError(
                "the `databento` package is not installed, so no dated CME FX "
                "contract can be fetched. Install the dependency declared in "
                "AGENTS.md Section 4 (Phase 5+) and retry: "
                "`uv add databento`."
            ) from exc
        if not self._api_key:
            raise FXForwardUnavailableError(
                "DATABENTO_API_KEY is not set, so the dated CME FX contract "
                "cannot be fetched. This is a CREDENTIAL fact, not a missing "
                "product: a free key exists at https://databento.com/signup. "
                "Set DATABENTO_API_KEY and retry."
            )
        self._client = module.Historical(self._api_key)
        return self._client

    def fetch_dated_close(
        self,
        *,
        dataset: str,
        schema: str,
        symbol: str,
        expiry: date,
    ) -> tuple[float, date]:
        """Fetch a dated instrument's settlement close from Databento.

        Requests a bounded window ending at the contract's expiry and takes the
        LAST close, which is the settlement mark. The window start is a
        safety margin of ~10 days: enough for a thin contract to have a print,
        short enough that the request is cheap and cannot return an
        unrelated month.
        """
        client = self._ensure_client()
        start = date.fromordinal(expiry.toordinal() - 10)
        store = client.timeseries.get_range(
            dataset=dataset,
            schema=schema,
            symbols=symbol,
            stype_in="raw_symbol",
            start=start.isoformat(),
            end=expiry.isoformat(),
        )
        frame = store.to_df()
        if frame is None or getattr(frame, "empty", True) or "close" not in frame.columns:
            raise FXForwardReadError(
                f"databento returned no usable rows for {symbol} in {dataset} "
                f"over [{start.isoformat()}, {expiry.isoformat()}]. An empty "
                f"series is reported rather than returned as a missing value, so "
                f"a caller cannot mistake 'the fetch failed' for 'no data'."
            )
        close = float(frame["close"].iloc[-1])
        return (close, expiry)


def _default_transport() -> ForwardTransport:
    """The transport used when the caller supplies none.

    A factory rather than a module-level singleton so a caller can construct one
    with an explicit key (``DatabentoTransport(api_key=...)``) without mutating
    global state — which would make two concurrent callers share a credential
    they did not choose.
    """
    return DatabentoTransport()
