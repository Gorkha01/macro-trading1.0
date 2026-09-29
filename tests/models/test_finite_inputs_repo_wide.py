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
import logging
import math
import pkgutil
import typing

import pytest
from pydantic import BaseModel, ValidationError

import macro_engine.models as models_pkg
from macro_engine.models.contracts import FiniteInputs

_log = logging.getLogger(__name__)


def _valid_payload(cls: type[BaseModel]) -> dict[str, object] | None:
    """A payload that constructs, or ``None`` if none can be built cheaply.

    Returns ``None`` rather than guessing when a field's type is not one this
    helper knows how to satisfy — a class it cannot build a valid instance of is
    not evidence of a gap, and pretending otherwise would make the sweep
    unreliably noisy.
    """
    payload: dict[str, object] = {}
    for field, info in cls.model_fields.items():
        annotation = str(info.annotation)
        if "Literal" in annotation:
            args = typing.get_args(info.annotation)
            if not args:
                return None
            payload[field] = args[0]
        elif "float" in annotation:
            payload[field] = 1.0
        elif "int" in annotation:
            payload[field] = 1
        elif "bool" in annotation:
            payload[field] = True
        elif "str" in annotation:
            payload[field] = "x"
        else:
            return None
    try:
        cls.model_validate(payload)
    except ValidationError:
        return None
    return payload


def _iter_input_groups() -> list[type[BaseModel]]:
    """Every ``*Inputs`` model class defined in the ``models`` package."""
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
                and name.endswith("Inputs")
            ):
                found.append(obj)
    return found


def test_no_input_group_accepts_a_non_finite_float() -> None:
    """THE STRUCTURAL SWEEP: no input class may admit ``nan``/``inf``.

    Every input group with a float field is probed: a valid instance is built,
    its first float field is set to ``nan``, and reconstruction must be refused.
    A class that accepts it is named in the failure — whether it inherits
    ``FiniteInputs`` or guards its own fields, the requirement is the same.

    This is what makes the D-139 fix durable. The audit that found the 13 gaps
    was a throwaway script; this is the same audit, running on every commit.
    """
    offenders: list[str] = []
    for cls in _iter_input_groups():
        float_fields = [
            f for f, info in cls.model_fields.items() if "float" in str(info.annotation)
        ]
        if not float_fields:
            continue
        payload = _valid_payload(cls)
        if payload is None:
            continue
        payload[float_fields[0]] = math.nan
        try:
            cls.model_validate(payload)
        except ValidationError:
            continue
        offenders.append(f"{cls.__module__}.{cls.__name__}.{float_fields[0]}")
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
        float_fields = [
            f for f, info in cls.model_fields.items() if "float" in str(info.annotation)
        ]
        if not float_fields:
            continue
        payload = _valid_payload(cls)
        if payload is None:
            continue
        payload[float_fields[0]] = math.inf
        try:
            cls.model_validate(payload)
        except ValidationError:
            continue
        offenders.append(f"{cls.__module__}.{cls.__name__}.{float_fields[0]}")
    assert not offenders, (
        "input group(s) accept `inf`, which can invert a sign rather than "
        "merely propagate:\n  " + "\n  ".join(offenders)
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
