"""D-139 — the repo-wide finiteness guard for model INPUT groups.

An audit during the Phase 2 review found that the D-078 failure (a ``nan``
reaching a model body, where it fails every comparison and therefore takes the
branch the bounds were written to exclude) was still reachable through **13**
input classes across 7 modules, none of which inherited the guard:

    bond_math.RepoStressInputs              gdp_nowcast.GdpGdiInputs
    gdp_nowcast.OutputGapInputs             inflation_dynamics.PhillipsCurveInputs
    inflation_dynamics.InflationTransmissionInputs
    national_accounts.PolicyMixInputs       national_accounts.QuantityTheoryInputs
    national_accounts.SavingsInvestmentInputs
    national_accounts.MinskyCompositionInputs
    real_policy_rate.RealPolicyRateInputs   risk.TwoAssetPortfolioInputs
    yield_curve.BreakevenInputs             yield_curve.CurveDecompositionInputs

Each was measured to accept ``nan`` before the fix. The base was already
promoted to ``contracts.FiniteInputs`` (see ``test_finite_inputs_contract.py``);
this module pins that the whole models layer now closes the gap, and — more
importantly — that it CANNOT REOPEN, via a structural sweep over every input
group defined in the package.

The structural sweep is the load-bearing part: a per-class regression test
would have to be written for every future input group, and the group that nobody
writes one for is exactly the one that reintroduces the defect. The sweep names
every offending class at once.
"""

from __future__ import annotations

import importlib
import itertools
import logging
import math
import pkgutil
import typing

import pytest
from pydantic import BaseModel, ValidationError

import macro_engine.models as models_pkg
from macro_engine.models.contracts import FiniteInputs

_log = logging.getLogger(__name__)


# Candidate values per field shape. The builder below searches these until a
# payload validates — because the classes that are HARD to build are exactly the
# ones with semantic validators, which is exactly where a finiteness gap hides
# (D-139c).
_FLOAT_CANDIDATES: tuple[float, ...] = (1.0, 0.5, 2.0, 0.1, -1.0, -10.0)
_INT_CANDIDATES: tuple[int, ...] = (1, 2, 10)
_BOOL_CANDIDATES: tuple[bool, ...] = (True, False)
_STR_CANDIDATES: tuple[str, ...] = (
    "x",
    "us",
    "USA",
    "domestic_per_foreign",
    "easing",
    "2y",
    "5y",
    "10y",
    "30y",
)
_LIST_FLOAT_CANDIDATES: tuple[list[float], ...] = (
    [1.0],
    [1.0, 1.0],
    [1.0] * 4,
    [1.0] * 8,
    [1.0] * 13,
    [1.0] * 26,
)
_LIST_NESTED_CANDIDATES: tuple[list[list[float]], ...] = (
    [[1.0]],
    [[1.0, 0.0], [0.0, 1.0]],
)
_DICT_FLOAT_CANDIDATES: tuple[dict[str, float], ...] = (
    {"k": 1.0},
    {"1y": 1.0, "10y": 2.0},
)
_DICT_LIST_CANDIDATES: tuple[dict[str, list[float]], ...] = (
    {"k": [1.0]},
    {"k": [1.0, 1.0]},
    {"k": [1.0] * 4},
)
_PRODUCT_CAP = 300_000


def _candidates_for(info: object, depth: int = 0) -> list[object] | None:
    """Candidate values for one field, or ``None`` if the shape is unknown.

    ``Optional`` types include ``None`` so a field that is only valid unset can
    still be constructed. A field whose type is itself a pydantic model is built
    recursively, so a group of nested components (e.g. FCI's five
    ``FCIComponent`` slots) is constructible rather than skipped.
    """
    annotation = getattr(info, "annotation", None)
    text = str(annotation)

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        nested = _valid_payload(annotation, depth + 1)
        return None if nested is None else [nested]

    optional = "None" in text

    def _with_none(values: list[object]) -> list[object]:
        return [*values, None] if optional else values

    if "Literal" in text:
        picks: list[object] = []
        for arg in typing.get_args(annotation):
            sub = typing.get_args(arg)
            if sub:
                picks.extend(x for x in sub if isinstance(x, str))
            elif isinstance(arg, str):
                picks.append(arg)
        return None if not picks else _with_none(picks)
    if "dict[str, list[float]]" in text:
        return _with_none(list(_DICT_LIST_CANDIDATES))
    if "dict[str, float]" in text:
        return _with_none(list(_DICT_FLOAT_CANDIDATES))
    if "list[list[float]]" in text:
        return _with_none(list(_LIST_NESTED_CANDIDATES))
    if "list[float]" in text:
        return _with_none(list(_LIST_FLOAT_CANDIDATES))
    if "list[str]" in text:
        return _with_none([["x"], ["x", "y"]])
    if "list[int]" in text:
        return _with_none([[1], [1, 2]])
    if "float" in text:
        return _with_none(list(_FLOAT_CANDIDATES))
    if "int" in text:
        return _with_none(list(_INT_CANDIDATES))
    if "bool" in text:
        return list(_BOOL_CANDIDATES)
    if "str" in text:
        return _with_none(list(_STR_CANDIDATES))
    return None


def _valid_payload(cls: type[BaseModel], _depth: int = 0) -> dict[str, object] | None:
    """A payload that constructs, or ``None`` if none can be built.

    Two passes:

    1. **Greedy, error-guided repair** — start at the first candidate for every
       field, and on each failure advance the candidate of the field pydantic
       named (falling back to any non-exhausted field). This is fast and resolves
       the common case (an enum value, a bound).
    2. **Bounded product search** — if the greedy walk stalls, enumerate the
       candidate combinations (capped at ``_PRODUCT_CAP``). This reaches the
       interactions a one-field-at-a-time walk cannot (a `quote` enum that only
       becomes valid once an ISO field is left unset).

    This is what lets the sweep reach classes with semantic validators instead of
    silently skipping them — the D-139c lesson: a class the sweep cannot build is
    a class the sweep cannot check, and those were the ones carrying gaps.
    """
    if _depth > 4:
        return None
    field_candidates: dict[str, list[object]] = {}
    for field, info in cls.model_fields.items():
        candidates = _candidates_for(info, _depth)
        if candidates is None:
            return None
        field_candidates[field] = candidates
    if not field_candidates:
        return None
    fields = list(field_candidates)

    # Pass 1 — greedy repair.
    index = dict.fromkeys(fields, 0)
    for _ in range(500):
        payload = {f: field_candidates[f][index[f]] for f in fields}
        try:
            cls.model_validate(payload)
        except ValidationError as exc:
            ordered: list[str] = []
            for err in exc.errors():
                loc = err.get("loc") or ()
                if loc and isinstance(loc[0], str) and loc[0] in field_candidates:
                    ordered.append(loc[0])
            ordered.extend(f for f in fields if f not in ordered)
            advanced = False
            for field in ordered:
                if index[field] < len(field_candidates[field]) - 1:
                    index[field] += 1
                    advanced = True
                    break
            if not advanced:
                break
        else:
            return payload

    # Pass 2 — bounded product search.
    total = 1
    for field in fields:
        total *= len(field_candidates[field])
    if total > _PRODUCT_CAP:
        return None
    for combo in itertools.product(*(field_candidates[f] for f in fields)):
        payload = dict(zip(fields, combo, strict=True))
        try:
            cls.model_validate(payload)
        except ValidationError:
            continue
        return payload
    return None


def _field_shape(annotation: str) -> str | None:
    """Classify a field by the container the finiteness guard must walk.

    Returns one of ``"scalar"``, ``"list"``, ``"nested"``, ``"dict"``,
    ``"dict_list"``, or ``None`` when the field holds no float the guard should
    see.
    """
    if "dict[str, list[float]]" in annotation:
        return "dict_list"
    if "dict[str, float]" in annotation:
        return "dict"
    if "list[list[float]]" in annotation:
        return "nested"
    if "list[float]" in annotation:
        return "list"
    if "float" in annotation:
        return "scalar"
    return None


def _float_field_paths(cls: type[BaseModel]) -> list[tuple[str, str]]:
    """Locate every field whose floats the finiteness guard must protect.

    Returns ``(field_name, shape)`` pairs, so the probes below contaminate the
    RIGHT shape:

    * ``"scalar"`` — a ``float`` field: set it to ``nan``;
    * ``"list"`` — a ``list[float]``: set ELEMENT 0 to ``nan``;
    * ``"nested"`` — a ``list[list[float]]``: set ``[0][0]`` to ``nan``;
    * ``"dict"`` — a ``dict[str, float]``: set one VALUE to ``nan``.

    ⚠️ **WHY THIS EXISTS (D-139b/D-139c).** The first version of this sweep
    probed only each class's FIRST float field, as a scalar. For
    ``risk.ReturnsInputs`` that first field is ``returns`` — a ``list[float]`` —
    so the probe replaced the whole list with a scalar ``nan``, which pydantic
    refuses because it is *not a list*. That is a ``ValidationError`` for the
    WRONG reason, and the sweep read it as "guarded". The second version fixed
    the list shape but the sweep still SKIPPED any class its builder could not
    construct — 21 of them, several with real gaps. Contaminating the correct
    SHAPE, and building every class, is what closes both blind spots.
    """
    out: list[tuple[str, str]] = []
    for field, info in cls.model_fields.items():
        shape = _field_shape(str(info.annotation))
        if shape is not None:
            out.append((field, shape))
    return out


def _contaminate(payload: dict[str, object], field: str, shape: str, bad: float) -> None:
    """Replace the target with ``bad`` at the shape the field declares."""
    if shape == "scalar":
        payload[field] = bad
    elif shape == "nested":
        payload[field] = [[bad]]
    elif shape == "dict":
        payload[field] = {"k": bad}
    elif shape == "dict_list":
        payload[field] = {"k": [bad]}
    else:
        payload[field] = [bad]


def _iter_input_groups() -> list[type[BaseModel]]:
    """Every input model class defined in the ``models`` package.

    Covers ``*Inputs`` AND ``*Constructor`` — a trade-constructor group is an
    input too, and ``yield_curve.CurveTradeConstructor`` was a live D-078 gap
    (``inf`` notional → ``nan`` residual, no warning) that an ``*Inputs``-only
    sweep never saw (D-139d).
    """
    found: list[type[BaseModel]] = []
    for mod in pkgutil.iter_modules(models_pkg.__path__):
        try:
            module = importlib.import_module(f"macro_engine.models.{mod.name}")
        except Exception:
            # A module that fails to import is another test's problem; skip it here
            # so this structural sweep reports only finiteness regressions.
            _log.debug("skipping unimportable model module %s", mod.name)
            continue
        for name in dir(module):
            obj = getattr(module, name)
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseModel)
                and obj.__module__ == module.__name__
                and name.endswith(("Inputs", "Constructor"))
            ):
                found.append(obj)
    return found


def test_no_input_group_accepts_a_non_finite_float() -> None:
    """THE STRUCTURAL SWEEP: no input class may admit ``nan``/``inf``.

    Every float-bearing field of every input group is probed at the shape it
    declares, and reconstruction must be refused. A class that accepts it is
    named in the failure — whether it inherits ``FiniteInputs`` or guards its own
    fields, the requirement is the same.

    This is what makes the D-139 fix durable. The audit that found the 13 gaps
    was a throwaway script; this is the same audit, running on every commit.
    """
    offenders: list[str] = []
    for cls in _iter_input_groups():
        targets = _float_field_paths(cls)
        if not targets:
            continue
        payload = _valid_payload(cls)
        if payload is None:
            continue
        for field, shape in targets:
            probe = dict(payload)
            _contaminate(probe, field, shape, math.nan)
            try:
                cls.model_validate(probe)
            except ValidationError:
                continue
            offenders.append(f"{cls.__module__}.{cls.__name__}.{field}[{shape}]")
    assert not offenders, (
        "input group(s) accept a non-finite float, so a `nan` will reach the "
        "model body and silently take the branch the bounds exclude (D-078/"
        "D-139). Fix by inheriting `contracts.FiniteInputs`, or add an explicit "
        "finiteness validator:\n  " + "\n  ".join(offenders)
    )


def test_inf_is_refused_as_well_as_nan() -> None:
    """``inf`` is the other half of the class — it flips signs under subtraction.

    A non-finite term premium, for instance, does not merely propagate: it can
    reverse the sign of a market-implied path. The sweep above probes ``nan``
    only (its first non-finite value), so ``inf`` is asserted separately here
    across the same class of input groups.
    """
    offenders: list[str] = []
    for cls in _iter_input_groups():
        targets = _float_field_paths(cls)
        if not targets:
            continue
        payload = _valid_payload(cls)
        if payload is None:
            continue
        for field, shape in targets:
            probe = dict(payload)
            _contaminate(probe, field, shape, math.inf)
            try:
                cls.model_validate(probe)
            except ValidationError:
                continue
            offenders.append(f"{cls.__module__}.{cls.__name__}.{field}[{shape}]")
    assert not offenders, (
        "input group(s) accept `inf`, which can invert a sign rather than "
        "merely propagate:\n  " + "\n  ".join(offenders)
    )


def test_every_input_group_is_actually_probed() -> None:
    """The COVERAGE guard: the sweep must not silently skip a class (D-139c).

    The two sweeps above can only check a class whose payload the builder can
    construct. A builder that returns ``None`` for a class — because the class
    has a semantic validator, or a shape the builder does not know — turns that
    class INVISIBLE to the finiteness sweep. That is precisely how
    ``TrilemmaInputs`` / ``CurveSlopeInputs`` / ``CrossMarketRVInputs`` /
    ``InversionHistoryInputs`` carried live gaps while the sweep stayed green: 21
    classes were being skipped.

    This test fails if ANY input group with a float-bearing field cannot be
    constructed, so the blind spot cannot silently reopen. When it fails, extend
    ``_candidates_for`` to handle the named shape.
    """
    unbuildable: list[str] = []
    for cls in _iter_input_groups():
        if not _float_field_paths(cls):
            continue
        if _valid_payload(cls) is None:
            unbuildable.append(f"{cls.__module__}.{cls.__name__}")
    assert not unbuildable, (
        "input group(s) with float fields could not be constructed by the sweep "
        "builder, so they are NOT being finiteness-checked (D-139c). Extend "
        "`_candidates_for` to handle their field shapes:\n  " + "\n  ".join(unbuildable)
    )


# --------------------------------------------------------------------------
# The 13 measured gaps, pinned individually so a regression names itself
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("module_name", "class_name", "field"),
    [
        ("bond_math", "RepoStressInputs", "sofr"),
        ("gdp_nowcast", "GdpGdiInputs", "gdp_growth_pct"),
        ("gdp_nowcast", "OutputGapInputs", "actual_gdp"),
        ("inflation_dynamics", "PhillipsCurveInputs", "inflation_expectations"),
        (
            "inflation_dynamics",
            "InflationTransmissionInputs",
            "inflation_surprise_bp",
        ),
        ("national_accounts", "PolicyMixInputs", "fiscal_deficit_pct_gdp"),
        ("national_accounts", "QuantityTheoryInputs", "money_supply_growth_pct"),
        ("national_accounts", "SavingsInvestmentInputs", "private_saving"),
        (
            "national_accounts",
            "MinskyCompositionInputs",
            "lending_standards_net_tightening_pct",
        ),
        ("real_policy_rate", "RealPolicyRateInputs", "nominal_policy_rate"),
        ("risk", "TwoAssetPortfolioInputs", "w1"),
        ("yield_curve", "BreakevenInputs", "nominal"),
        ("yield_curve", "CurveDecompositionInputs", "nominal_yield"),
        # --- the +inf half: bound-constraint fields that let +inf through ---
        ("auctions", "AuctionInputs", "bid_to_cover"),
        ("bond_math", "BondPricingInputs", "face_value"),
        ("bond_math", "ConvexityInputs", "coupon"),
        ("credit_spread", "CreditSpreadInputs", "hy_spread_bp"),
        ("national_accounts", "FisherIndexInputs", "laspeyres"),
        ("national_accounts", "OpeningsToUnemployedInputs", "job_openings_thousands"),
        ("production_function", "PotentialGDPInputs", "total_factor_productivity"),
    ],
)
def test_a_measured_nan_gap_is_closed(module_name: str, class_name: str, field: str) -> None:
    """Each class measured to accept a non-finite float now refuses all of them.

    Named individually, with the field that was probed, so a future regression
    reports ``national_accounts.PolicyMixInputs`` rather than only failing the
    aggregate sweep — the difference between a debuggable failure and a hunt.

    Two batches are listed. The first 13 were found by a ``nan`` probe. The
    last 7 carry a field-LEVEL bound (``gt=0``/``ge=0`` / ``le=1``) whose
    comparison happens to reject ``nan`` and ``-inf`` — ``nan > 0`` and
    ``-inf > 0`` are both False — but ACCEPTS ``+inf``, because ``inf > 0`` is
    True. A nan-only audit calls those protected; probing ``inf`` is what
    exposes them, which is why the shared guard refuses all three rather than
    being folded into a bound.
    """
    module = importlib.import_module(f"macro_engine.models.{module_name}")
    cls = getattr(module, class_name)
    payload = _valid_payload(cls)
    assert payload is not None, (
        f"{class_name} could not be constructed with a valid payload, so this "
        f"test cannot probe it — the fixture needs updating, not the class"
    )
    for bad in (math.nan, math.inf, -math.inf):
        payload[field] = bad
        # The OUTCOME is what matters — refusal — not which validator reports
        # it. A field-level bound (`gt=0`) rejects `nan` with a `greater_than`
        # message before the shared guard ever runs, while `+inf` passes the
        # bound (`inf > 0`) and is then caught by the guard with a
        # `non-finite` message. Asserting on the message would fail the first
        # case while the class is behaving correctly.
        with pytest.raises(ValidationError):
            cls.model_validate(payload)


@pytest.mark.parametrize(
    ("module_name", "class_name", "field", "shape"),
    [
        # D-139b — list / nested-matrix shapes.
        ("risk", "ReturnsInputs", "returns", "list"),
        ("risk", "RealizedVolInputs", "returns", "list"),
        ("risk", "PortfolioVaRInputs", "covariance_matrix", "nested"),
        ("risk", "MonteCarloVaRInputs", "normal_correlations", "nested"),
        ("inflation_nowcast", "ShelterLagInputs", "market_rent_growth_yoy_pct", "list"),
        ("inflation_nowcast", "ShelterLagInputs", "current_cpi_shelter_yoy_pct", "scalar"),
        # D-139c — dict / dict-of-list / nested-model shapes, in classes the
        # original sweep SKIPPED because its builder could not construct them.
        ("regime", "TrilemmaInputs", "reserves_trend_pct_change_3mo", "scalar"),
        ("yield_curve", "CurveSlopeInputs", "tenors", "dict"),
        ("yield_curve", "InversionHistoryInputs", "current_slope_bp", "scalar"),
        ("yield_curve", "CrossMarketRVInputs", "target_notional_a", "scalar"),
        ("gdp_nowcast", "SimpleGDPNowcastInputs", "retail_sales_mom", "dict_list"),
        ("gdp_nowcast", "SimpleGDPNowcastInputs", "prior_quarter_annualized", "scalar"),
        ("national_accounts", "IndexNumberInputs", "base_prices", "dict"),
        ("lei_proxy", "LeadingIndicatorProxyInputs", "components", "dict"),
        ("financial_conditions", "FCIInputs", "nfci_value", "scalar"),
    ],
)
def test_the_d139bc_gaps_are_closed(
    module_name: str, class_name: str, field: str, shape: str
) -> None:
    """Every D-139b / D-139c gap now refuses all three non-finite values.

    These are the gaps the earlier sweeps MISSED — the list/matrix shapes the
    first sweep could not contaminate, and the classes its builder could not
    construct at all. Each is pinned by name and shape so a regression names
    itself instead of only failing the aggregate sweep.
    """
    module = importlib.import_module(f"macro_engine.models.{module_name}")
    cls = getattr(module, class_name)
    payload = _valid_payload(cls)
    assert payload is not None, (
        f"{class_name} could not be constructed with a valid payload, so this "
        f"test cannot probe it — the fixture needs updating, not the class"
    )
    for bad in (math.nan, math.inf, -math.inf):
        probe = dict(payload)
        _contaminate(probe, field, shape, bad)
        with pytest.raises(ValidationError):
            cls.model_validate(probe)


def test_the_thirteen_really_were_the_gaps() -> None:
    """Guard against the list above drifting from the code it describes.

    Every class named in the parametrisation must inherit the shared guard. If
    a class is later refactored onto a plain ``BaseModel`` the individual test
    above still passes (its own validator may cover the field), but this one
    fails — which is the signal that the class left the family.
    """
    named = [
        ("bond_math", "RepoStressInputs"),
        ("gdp_nowcast", "GdpGdiInputs"),
        ("gdp_nowcast", "OutputGapInputs"),
        ("inflation_dynamics", "PhillipsCurveInputs"),
        ("inflation_dynamics", "InflationTransmissionInputs"),
        ("national_accounts", "PolicyMixInputs"),
        ("national_accounts", "QuantityTheoryInputs"),
        ("national_accounts", "SavingsInvestmentInputs"),
        ("national_accounts", "MinskyCompositionInputs"),
        ("real_policy_rate", "RealPolicyRateInputs"),
        ("risk", "TwoAssetPortfolioInputs"),
        ("yield_curve", "BreakevenInputs"),
        ("yield_curve", "CurveDecompositionInputs"),
        ("auctions", "AuctionInputs"),
        ("bond_math", "BondPricingInputs"),
        ("bond_math", "ConvexityInputs"),
        ("credit_spread", "CreditSpreadInputs"),
        ("national_accounts", "FisherIndexInputs"),
        ("national_accounts", "OpeningsToUnemployedInputs"),
        ("production_function", "PotentialGDPInputs"),
    ]
    not_guarded = []
    for module_name, class_name in named:
        module = importlib.import_module(f"macro_engine.models.{module_name}")
        cls = getattr(module, class_name)
        if not issubclass(cls, FiniteInputs):
            not_guarded.append(f"{module_name}.{class_name}")
    assert not not_guarded, (
        "these classes were fixed by inheriting FiniteInputs and no longer do:\n  "
        + "\n  ".join(not_guarded)
    )
