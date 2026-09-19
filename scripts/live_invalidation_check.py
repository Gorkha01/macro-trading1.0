"""Live check: ``derive_invalidation_conditions`` against the REAL upstream models.

Not a test. Operator scripts are deliberately excluded from the default test run
because they exercise the real settings tree and other real modules. Run with::

    uv run python scripts/live_invalidation_check.py

Section 21.0: unit tests prove the arithmetic, this proves the wiring. Here the
wiring is the whole subject, because **the defect this increment fixes is a
wiring defect**: Section 20.15 compares ``inflation.value < 0`` against a
``ModelResult`` whose ``value`` the shipped classifier publishes as a **dict**.

So this check does the one thing a fixture cannot: it pulls real series, runs the
**real** ``inflation_convergence_classifier``, ``inflation_breadth_score``,
``labor_tightness_score`` and ``output_gap``, and feeds their actual published
shapes through both programs.

What this check establishes
---------------------------

1. **The three real upstream shapes, measured.** One dict, two floats. The check
   prints each ``ModelResult.value``'s type rather than describing it, so a
   future change to any of those models' contracts fails here loudly.

2. **The specification's body raises on real data.** Section 20.15's
   ``derive_invalidation_conditions`` is executed **verbatim** against the real
   classifier output, and the ``TypeError`` is reproduced. This is not a
   synthetic reproduction: the input is what the shipped model publishes today.

3. **The shipped function reads all three, and names which is which.** Every real
   input produces a condition or a stated neutral, and nothing is unreadable.

4. **The gate, end to end, on real output.** The assessment's ``text`` is handed
   to a real ``TradeIdea`` and accepted; an assessment that identified nothing is
   handed to the same constructor and **refused**. That is the LTCM hard gate
   becoming load-bearing instead of satisfiable by a sentence.

5. **The three-name confusion is observable, not just documented.** §16.2's Q1
   passes ``inflation_breadth_score``; §20.15's docstring names
   ``inflation_convergence_classifier``; ``build_confirmation_signals`` labels
   the slot ``"inflation_convergence"``. The check runs both real models through
   the same call and shows the falsifier **form** differs — a reversal versus an
   agreement collapse — so which one is passed is visible in the output.

What this check CANNOT validate
-------------------------------
**Whether a condition is the RIGHT one.** The function states the falsifier
implied by each signal's own sign. Whether that signal is the one the thesis
actually leans on is the caller's judgement, and no pull can supply it. The
output names its model and its threshold so the judgement is checkable, not so it
is automated.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
from pydantic import ValidationError

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from macro_engine.config import get_settings  # noqa: E402
from macro_engine.data_layer.openbb_client import OpenBBClient  # noqa: E402
from macro_engine.models.contracts import ModelResult, utc_now  # noqa: E402
from macro_engine.models.gdp_nowcast import (  # noqa: E402
    OutputGapInputs,
    output_gap,
)
from macro_engine.models.inflation_convergence import (  # noqa: E402
    InflationConvergenceInputs,
    inflation_convergence_classifier,
)
from macro_engine.models.labor_synthesis import (  # noqa: E402
    InflationSubMeasures,
    LaborInputs,
    inflation_breadth_score,
    labor_tightness_score,
)
from macro_engine.thesis_layer.invalidation import (  # noqa: E402
    derive_invalidation_conditions,
)
from macro_engine.thesis_layer.schemas import TradeIdea  # noqa: E402

#: Transcribed from ``config/series_registry.yaml`` — the registry is the only
#: place that should name providers, and this script mirrors how the snapshot
#: builder fetches a registry series.
_SERIES: dict[str, str] = {
    "CPIAUCSL": "cpi_headline",
    "CPILFESL": "cpi_core",
    "PCEPILFE": "pce_core",
    "ICSA": "initial_claims",
    "JTSJOL": "jolts_openings",
    "PAYEMS": "nfp",
    "GDPC1": "real_gdp",
    "GDPPOT": "potential_gdp",
}


def _fetch(client: OpenBBClient, symbol: str) -> pd.DataFrame:
    return client.fetch_series(
        provider="fred",
        endpoint="economy.fred_series",
        params={"symbol": symbol},
        series_label=_SERIES[symbol],
    )


def _values(frame: pd.DataFrame) -> tuple[list[date], list[float]]:
    """Extract ``(dates, values)``, dropping nulls."""
    clean = frame.loc[frame["value"].notna(), ["date", "value"]]
    dates = [value if isinstance(value, date) else value.date() for value in clean["date"]]
    return dates, [float(value) for value in clean["value"]]


def _mom_pct(values: list[float]) -> float:
    """Latest month-over-month percent change."""
    return (values[-1] / values[-2] - 1.0) * 100.0


def _sign(value: float) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0


def _specification_body(growth: ModelResult, inflation: ModelResult, labor: ModelResult) -> str:
    """Section 20.15's ``derive_invalidation_conditions``, VERBATIM.

    Reproduced here on purpose: this is the program whose behaviour the
    increment's finding is about, and running it against real model output is
    the only way to show the failure is reachable rather than theoretical.
    """
    conditions = []
    if labor.value < 0:  # type: ignore[operator]
        conditions.append(
            "labor_tightness_score reverses positive (claims fall, JOLTS openings stabilize)"
        )
    if inflation.value < 0:  # type: ignore[operator]
        conditions.append(
            "inflation_convergence_classifier shows broad-based reacceleration "
            "(not narrow, single-measure)"
        )
    return (
        " OR ".join(conditions)
        if conditions
        else (
            "No clear evidence-based invalidation condition identified — DO NOT "
            "promote this thesis past DRAFT (Module 14 Q8 requirement)"
        )
    )


def _real_results(
    client: OpenBBClient,
) -> tuple[ModelResult, ModelResult, ModelResult, ModelResult]:
    """Run the real upstream models. Returns (growth, breadth, convergence, labor)."""
    fetched: dict[str, tuple[list[date], list[float]]] = {}
    for symbol in _SERIES:
        dates, values = _values(_fetch(client, symbol))
        fetched[symbol] = (dates, values)
        print(f"    {symbol:10} n={len(values):6}  through {dates[-1]}")

    cpi_headline = _mom_pct(fetched["CPIAUCSL"][1])
    cpi_core = _mom_pct(fetched["CPILFESL"][1])
    pce_core = _mom_pct(fetched["PCEPILFE"][1])

    breadth = inflation_breadth_score(
        InflationSubMeasures(
            cpi_headline_mom=cpi_headline, cpi_core_mom=cpi_core, pce_core_mom=pce_core
        )
    )
    convergence = inflation_convergence_classifier(
        InflationConvergenceInputs(
            headline_cpi_direction=_sign(cpi_headline),  # type: ignore[arg-type]
            core_cpi_direction=_sign(cpi_core),  # type: ignore[arg-type]
            core_pce_direction=_sign(pce_core),  # type: ignore[arg-type]
        )
    )

    claims = fetched["ICSA"][1]
    claims_4wk = sum(claims[-4:]) / 4.0
    claims_prior_4wk = sum(claims[-8:-4]) / 4.0
    jolts = fetched["JTSJOL"][1]
    nfp = fetched["PAYEMS"][1]
    labor = labor_tightness_score(
        LaborInputs(
            initial_claims_4wk_avg_change_pct=(claims_4wk / claims_prior_4wk - 1.0) * 100.0,
            jolts_openings_yoy_pct=(jolts[-1] / jolts[-13] - 1.0) * 100.0,
            jolts_quits_level_percentile=50.0,
            nfp_3m_avg=(nfp[-1] - nfp[-4]) / 3.0,
        )
    )

    gdp = fetched["GDPC1"][1]
    potential = fetched["GDPPOT"][1]
    growth = output_gap(OutputGapInputs(actual_gdp=gdp[-1], potential_gdp=potential[-1]))

    return growth, breadth, convergence, labor


def _flat(name: str) -> ModelResult:
    """A real-shaped result whose value sits exactly ON the crossing.

    Used for the gate section: three readable, directionless signals are the case
    that must produce an EMPTY text. The values are not invented — ``0.0`` is the
    configured crossing, which is what "no direction" means here.
    """
    return ModelResult(
        model_name=name,
        country="us",
        as_of=utc_now(),
        value=0.0,
        confidence=0.5,
        interpretation=f"{name} at the crossing",
        context="",
        inputs_used=[],
    )


def _section_1_shapes(
    growth: ModelResult, breadth: ModelResult, convergence: ModelResult, labor: ModelResult
) -> None:
    print("=" * 78)
    print("1. THE REAL UPSTREAM SHAPES")
    print("=" * 78)
    for result in (growth, breadth, convergence, labor):
        print(
            f"    {result.model_name:34} value={result.value!r:>12} "
            f"type={type(result.value).__name__}"
        )
    print()
    print("  Section 20.15 compares TWO of these with `< 0`. One is a dict.")
    assert isinstance(convergence.value, dict), (
        "the classifier no longer publishes a dict; the crash this increment "
        "fixed may no longer be reachable and the finding needs re-deriving"
    )
    assert isinstance(labor.value, (int, float)) and not isinstance(labor.value, bool)
    assert isinstance(breadth.value, (int, float)) and not isinstance(breadth.value, bool)


def _section_2_crash(growth: ModelResult, convergence: ModelResult, labor: ModelResult) -> None:
    print()
    print("=" * 78)
    print("2. THE SPECIFICATION'S BODY, ON REAL DATA")
    print("=" * 78)
    try:
        out = _specification_body(growth, convergence, labor)
        print(f"    returned: {out[:90]}...")
        print("    (the comparison did not raise — the finding needs re-deriving)")
    except TypeError as exc:
        print(f"    !! TypeError: {exc}")
        print()
        print("  Reproduced on the REAL classifier output, not a fixture. The")
        print("  builder happens to pass `inflation_breadth_score` (a float) today,")
        print("  so the crash is latent — and Section 20.15's own docstring names")
        print("  the dict-valued model, which is what makes it reachable.")
        return
    raise AssertionError("expected the specification's body to raise on real data")


def _section_3_shipped(
    growth: ModelResult, breadth: ModelResult, convergence: ModelResult, labor: ModelResult
) -> str:
    print()
    print("=" * 78)
    print("3. THE SHIPPED FUNCTION, ON THE SAME REAL RESULTS")
    print("=" * 78)
    assessment = derive_invalidation_conditions(growth, breadth, labor)
    print(f"    identified: {assessment.identified}")
    for condition in assessment.conditions:
        print(f"      [{condition.trigger}] {condition.statement}")
    for note in assessment.neutral:
        print(f"      [neutral]  {note}")
    for unreadable in assessment.unreadable:
        print(f"      [UNREADABLE] {unreadable.model_name} ({unreadable.value_type})")
    assert not assessment.unreadable, "a real float-valued result must be readable"
    assert assessment.identified, "at least one real signal must carry a direction"

    # And the dict-valued model, which the specification crashes on.
    via_classifier = derive_invalidation_conditions(growth, convergence, labor)
    assert not via_classifier.unreadable, (
        "the dict-valued classifier must be readable — that is the whole repair"
    )
    print()
    print("    through the dict-valued classifier instead:")
    for condition in via_classifier.conditions:
        print(f"      [{condition.trigger}] {condition.statement}")
    return assessment.text


def _section_4_gate(text: str) -> None:
    print()
    print("=" * 78)
    print("4. THE LTCM HARD GATE, ON REAL OUTPUT")
    print("=" * 78)
    live = TradeIdea(
        instrument="UST 2yr note futures",
        direction="long",
        timeframe="6-12 months",
        stop_or_invalidation=text,
    )
    print(f"    a real falsifier is ACCEPTED: is_trade={live.is_trade}")
    print(f"      {live.stop_or_invalidation[:100]}...")

    fallback = (
        "No clear evidence-based invalidation condition identified — DO NOT "
        "promote this thesis past DRAFT (Module 14 Q8 requirement)"
    )
    accepted = TradeIdea(
        instrument="UST 2yr note futures",
        direction="long",
        timeframe="6-12 months",
        stop_or_invalidation=fallback,
    )
    print()
    print(f"    and so is the SPECIFICATION'S FALLBACK: is_trade={accepted.is_trade}")
    print("      -> a live trade whose stated falsifier is 'no falsifier was found'")
    print("         passes the gate the falsifier exists for. The gate is a")
    print("         presence check on a field whose sentinel is a valid presence.")

    empty = derive_invalidation_conditions(
        _flat("output_gap"),
        _flat("inflation_breadth_score"),
        _flat("labor_tightness_score"),
    )
    assert empty.identified is False and empty.text == ""
    try:
        TradeIdea(
            instrument="UST 2yr note futures",
            direction="long",
            timeframe="6-12 months",
            stop_or_invalidation=empty.text,
        )
    except ValidationError as exc:
        first = str(exc).splitlines()[1].strip() if len(str(exc).splitlines()) > 1 else str(exc)
        print()
        print(f"    the SHIPPED assessment's empty text is REFUSED: {first[:96]}")
        print("      -> the gate is load-bearing: nothing identified means no live")
        print("         trade, which is what the fallback sentence was asking for.")
        return
    raise AssertionError("an empty stop_or_invalidation must be refused for a live trade")


def _section_5_three_names(breadth: ModelResult, convergence: ModelResult) -> None:
    print()
    print("=" * 78)
    print("5. THE THREE NAMES §16 USES FOR ONE ARGUMENT SLOT")
    print("=" * 78)
    print("    §16.2 Q1            passes inflation_breadth_score")
    print("    §20.15 docstring    names  inflation_convergence_classifier")
    print('    build_confirmation  labels the slot "inflation_convergence"')
    print()
    settings = get_settings().invalidation
    print(f"    breadth_score value type      = {type(breadth.value).__name__}")
    print(f"    convergence value type        = {type(convergence.value).__name__}")
    verdict = convergence.value
    assert isinstance(verdict, dict), "the classifier's value must be a dict"
    print(f"    convergence classification    = {verdict['classification']}")
    print(f"    supporting agreement class    = {settings.agreement_class_supporting_a_thesis}")
    print()
    print("    The two produce DIFFERENT falsifier FORMS — a sign reversal versus an")
    print("    agreement collapse — so which model is passed is visible in the output")
    print("    rather than hidden in the prose. The classifier reports agreement")
    print("    STRENGTH, not direction, so it cannot express the 'reacceleration'")
    print("    §20.15 attributes to it.")


def main() -> int:
    print("=" * 78)
    print("LIVE CHECK: derive_invalidation_conditions (Module 14, D-063)")
    print("=" * 78)

    client = OpenBBClient()
    print("  fetching real series via OpenBB:")
    growth, breadth, convergence, labor = _real_results(client)

    _section_1_shapes(growth, breadth, convergence, labor)
    _section_2_crash(growth, convergence, labor)
    text = _section_3_shipped(growth, breadth, convergence, labor)
    _section_4_gate(text)
    _section_5_three_names(breadth, convergence)

    print()
    print("=" * 78)
    print("RESULT: the specification's body raises TypeError on the REAL output of")
    print("        the model its own docstring names; the shipped function reads all")
    print("        three shapes, names each model and each threshold, and leaves the")
    print("        text EMPTY when nothing was identified — so the LTCM hard gate")
    print("        refuses a live trade instead of being satisfied by a sentence")
    print("        that says no falsifier was found.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
