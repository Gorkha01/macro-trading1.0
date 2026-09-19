"""Live wiring check: real pillar readings -> ``classify_convergence``.

Not a test. This directory holds operator scripts, deliberately excluded from the
default test run because they hit the network. Run with::

    uv run python scripts/live_convergence_check.py

Section 21.0: unit tests prove the arithmetic, this proves the wiring — the
units, the sign convention, the sampling cadence, and whether the shape the
specification asserts at its call site is the shape the pipeline actually has.

Why this is a separate script from ``live_scorecard_check.py``
-------------------------------------------------------------
The two classifiers take **different inputs** and that difference is the reason
both exist:

* ``four_pillar_scorecard`` takes ``ScorecardInputs`` — four pillars addressed
  by name, each a ``PillarRead``.
* ``classify_convergence`` takes ``ConvergenceInputs`` — an arbitrary
  ``list[ModelResult]``.

The specification calls this one at ``build_us_macro_thesis`` (Q7) as
``classify_convergence([growth, inflation, labor, gap])``, which is a **list** of
already-produced results, not a record of named fields. So the live check that
matters here is not "does it classify four things" — it is **"does it accept the
objects the pipeline is actually holding"**. This script therefore runs the four
pillar readings through ``ModelResult`` construction first and only then hands
them over, which is the step the specification's own version cannot do at all
(it indexes ``signals[0]`` and compares a ``ModelResult`` to an ``int``).

What this check does beyond running the function
------------------------------------------------

1. **Feeds it the real pipeline object, not a hand-built fixture.** Each pillar
   is a ``ModelResult`` carrying a real series-derived direction, a real source
   family, and a real interpretation — the same object the thesis builder would
   pass. A classifier that only works on synthetic ints would fail here.

2. **Cross-checks the two classifiers against each other on the same data.**
   The overlap cases are the ones where both are well-defined: a read with no
   opposition. Both must return the same verdict there, because the scorecard is
   the same predicate over four named pillars. Where they *differ* is reported
   and explained — the general classifier admits neutral signals to the list and
   the scorecard does not, which is a real behavioural difference and not a bug.

3. **Measures the CONFLICTED share over real history and compares it to the
   input-space figure.** ``config/settings.yaml`` publishes 61.73% for n=4 over
   the admissible space. Real pillars are correlated, so the realised share can
   differ sharply. Both are printed; the contrast is the finding. This mirrors
   the scorecard check deliberately — the two measurements should agree, and if
   they do not, at least one of them is wrong.

4. **Checks the §15.19-D census against real families.** The family count is
   measured by the supplier, not supplied. The check asserts that a real read
   spanning four families and a real read spanning one family produce different
   confidence, and that neutral signals contribute **no** families (Defect 7).

5. **Reports what the check cannot validate.** No series carries a source-family
   label; the mapping is a judgement encoded here and printed so a reviewer can
   disagree with any row.
"""

from __future__ import annotations

import itertools
from datetime import date
from typing import TYPE_CHECKING

from macro_engine.config import get_settings
from macro_engine.data_layer.openbb_client import OpenBBClient
from macro_engine.models.contracts import ModelResult, utc_now
from macro_engine.models.convergence import ConvergenceInputs, classify_convergence
from macro_engine.models.evidence_family import EvidenceSourceFamily
from macro_engine.models.scorecard import (
    PillarRead,
    ScorecardInputs,
    four_pillar_scorecard,
)

if TYPE_CHECKING:
    import pandas as pd

F = EvidenceSourceFamily

#: Months between readings. Matches ``live_scorecard_check.py`` so the two
#: CONFLICTED shares are measured over the same population and can be compared
#: as like-for-like — a different stride here would make any disagreement
#: unattributable.
_SAMPLE_STRIDE_MONTHS = 3

#: The four series and the sign rule applied to each, stated in prose so the
#: sign can be audited. Identical to the scorecard check's rules by design: a
#: shared derivation is what makes the cross-check meaningful.
_PILLAR_RULES: dict[str, str] = {
    "growth": (
        "UNRATE 3-month change, sign INVERTED. Unemployment rising = labor "
        "market loosening = growth weakening = easing-implying (-1)."
    ),
    "inflation": (
        "Core PCE year-over-year, 3-month delta, sign DIRECT. Accelerating "
        "inflation = tightening-implying (+1)."
    ),
    "financial_conditions": (
        "10-year yield 3-month change, sign DIRECT. Rising long yields are restrictive for credit."
    ),
    "policy_gap": (
        "Real fed funds (DFF minus core PCE yoy) 3-month change, sign DIRECT. "
        "A rising real policy rate is tightening."
    ),
}

#: The source family each series is assigned to. **A judgement, not a
#: measurement** — no FRED series carries a family label. Printed so a reviewer
#: can disagree with any row. The assignment matches the scorecard check's, so
#: the family counts in the two scripts are comparable.
_FAMILIES: tuple[EvidenceSourceFamily, ...] = (
    F.BLS_EMPLOYMENT_SITUATION,
    F.BEA_PCE,
    F.TREASURY_OFFICIAL,
    F.FED_H41,
)

_NAMES = ("growth", "inflation", "financial_conditions", "policy_gap")


def _fetch(client: OpenBBClient, symbol: str, label: str) -> pd.DataFrame:
    """Mirror how the snapshot builder fetches a registry series."""
    return client.fetch_series(
        provider="fred",
        endpoint="economy.fred_series",
        params={"symbol": symbol},
        series_label=label,
    )


def _monthly(frame: pd.DataFrame) -> dict[date, float]:
    """Collapse a series to one reading per month (last observation wins)."""
    out: dict[date, float] = {}
    for _, row in frame.iterrows():
        value = row["value"]
        if value is None or value != value:  # NaN is the only value != itself
            continue
        raw_date = row["date"]
        day: date = raw_date if isinstance(raw_date, date) else raw_date.date()
        out[date(day.year, day.month, 1)] = float(value)
    return out


def _shift_months(anchor: date, months: int) -> date:
    """Month arithmetic with day clamping."""
    total = anchor.year * 12 + (anchor.month - 1) + months
    year, month = divmod(total, 12)
    return date(year, month + 1, 1)


def _sign(value: float, band: float) -> int:
    """Map a change to a direction using a symmetric dead band."""
    if value > band:
        return 1
    if value < -band:
        return -1
    return 0


def _read(result: ModelResult, key: str) -> object:
    value = result.value
    assert isinstance(value, dict), f"{result.model_name}: expected a dict value"
    return value[key]


def _read_str(result: ModelResult, key: str) -> str:
    entry = _read(result, key)
    assert isinstance(entry, str), f"{result.model_name}: value[{key!r}] is not a str"
    return entry


def _read_int(result: ModelResult, key: str) -> int:
    entry = _read(result, key)
    assert isinstance(entry, int) and not isinstance(entry, bool), (
        f"{result.model_name}: value[{key!r}] is not an int"
    )
    return entry


def _signal(direction: int, family: EvidenceSourceFamily, source: str) -> ModelResult:
    """The pipeline object: a real pillar reading as a ``ModelResult``.

    This is the crux of the check. The specification hands
    ``classify_convergence`` four values and indexes them positionally; the
    pipeline hands it ``ModelResult``s. Constructing them here is what proves
    the general classifier accepts the shape it will actually receive.
    """
    return ModelResult(
        model_name=f"pillar_{source}",
        country="us",
        as_of=utc_now(),
        value=direction,
        confidence=0.5,
        interpretation=f"pillar read: {source} -> {direction:+d}",
        context="live convergence check",
        inputs_used=[source],
        source_family=family,
    )


def main() -> int:
    settings = get_settings().convergence
    rules = get_settings().scorecard.pillar_rules

    client = OpenBBClient()
    unrate = _monthly(_fetch(client, "UNRATE", "unemployment rate"))
    core_pce = _monthly(_fetch(client, "PCEPILFE", "core PCE price index"))
    dgs10 = _monthly(_fetch(client, "DGS10", "10-year constant maturity"))
    dff = _monthly(_fetch(client, "DFF", "effective fed funds rate"))

    print("=" * 78)
    print("LIVE CHECK — classify_convergence (Module 12, Section 22.10, D-051)")
    print("=" * 78)
    print()
    for name, series in (
        ("UNRATE", unrate),
        ("PCEPILFE", core_pce),
        ("DGS10", dgs10),
        ("DFF", dff),
    ):
        print(f"  {name:9s} {len(series):5d} months  {min(series)} .. {max(series)}")

    print()
    print("PILLAR RULES (the sign of each, stated before it is used)")
    for name, rule in _PILLAR_RULES.items():
        print(f"  {name:22s} {rule}")

    print()
    print("SOURCE FAMILIES — a JUDGEMENT, not a measurement (no series is labelled)")
    for name, family in zip(_NAMES, _FAMILIES, strict=True):
        print(f"  {name:22s} {family.value}")

    # --- derive a full four-pillar reading per month -------------------------
    common = sorted(set(unrate) & set(core_pce) & set(dgs10) & set(dff))
    if len(common) < 200:
        print(f"FATAL: only {len(common)} months shared across the four series.")
        return 1

    print()
    print(f"COMMON WINDOW  {common[0]} .. {common[-1]}  ({len(common)} months)")

    cpi_yoy: dict[date, float] = {}
    for anchor in common:
        prior = _shift_months(anchor, -12)
        if prior in core_pce and core_pce[prior] > 0:
            cpi_yoy[anchor] = (core_pce[anchor] / core_pce[prior] - 1.0) * 100.0

    readings: list[tuple[date, int, int, int, int]] = []
    for anchor in common:
        back3 = _shift_months(anchor, -3)
        back12 = _shift_months(anchor, -12)
        required = (back3, back12)
        if not all(k in unrate and k in dgs10 and k in dff and k in cpi_yoy for k in required):
            continue
        if anchor not in cpi_yoy:
            continue
        growth = -_sign(unrate[anchor] - unrate[back3], rules.unemployment_change_band.value)
        inflation = _sign(cpi_yoy[anchor] - cpi_yoy[back3], rules.inflation_change_band.value)
        fin = _sign(dgs10[anchor] - dgs10[back3], rules.yield_change_band.value)
        rn = dff[anchor] - cpi_yoy[anchor]
        rb = dff[back3] - cpi_yoy[back3]
        policy = _sign(rn - rb, rules.real_rate_change_band.value)
        readings.append((anchor, growth, inflation, fin, policy))

    if not readings:
        print("FATAL: no month produced a complete four-pillar reading.")
        return 1
    print(f"READINGS  {len(readings)} months with all four pillars computable")

    # --- sign audit ----------------------------------------------------------
    latest = readings[-1]
    back3 = _shift_months(latest[0], -3)
    print()
    print(f"SIGN AUDIT — the most recent reading ({latest[0]})")
    print(
        f"  unemployment {unrate[back3]:.1f} -> {unrate[latest[0]]:.1f}  "
        f"(change {unrate[latest[0]] - unrate[back3]:+.2f}) -> growth {latest[1]:+d}"
    )
    print(
        f"  core PCE yoy {cpi_yoy[back3]:.2f} -> {cpi_yoy[latest[0]]:.2f}  "
        f"(change {cpi_yoy[latest[0]] - cpi_yoy[back3]:+.2f}) -> inflation {latest[2]:+d}"
    )
    print(
        f"  10y          {dgs10[back3]:.2f} -> {dgs10[latest[0]]:.2f}  "
        f"(change {dgs10[latest[0]] - dgs10[back3]:+.2f}) -> fin_cond {latest[3]:+d}"
    )
    print(
        f"  real ff      {rb:.2f} -> {rn:.2f}  (change {rn - rb:+.2f}) -> policy_gap {latest[4]:+d}"
    )

    # --- the specification's call-site shape --------------------------------
    print()
    print("CALL-SITE SHAPE — the pipeline hands it ModelResults, not bare ints")
    live_signals = [
        _signal(d, fam, name) for d, fam, name in zip(latest[1:], _FAMILIES, _NAMES, strict=True)
    ]
    live = classify_convergence(ConvergenceInputs(signals=live_signals))
    print(f"  inputs: {[s.model_name for s in live_signals]}")
    print(f"  directions read back: {_read(live, 'directions')}")
    print(
        f"  verdict {_read_str(live, 'classification')}  "
        f"families {_read_int(live, 'independent_families')}  "
        f"confidence {live.confidence}"
    )
    assert _read(live, "directions") == list(latest[1:]), (
        "the classifier must read the directions the pillar derivation produced — "
        "a mismatch means the sign convention or the value envelope was lost in "
        "the hand-off"
    )

    # --- verdict distribution over real history -----------------------------
    counts: dict[str, int] = {}
    all_neutral_months: list[date] = []
    agree_with_scorecard = 0
    disagree_with_scorecard = 0
    for anchor, *dirs in readings:
        signals = [
            _signal(d, fam, name) for d, fam, name in zip(dirs, _FAMILIES, _NAMES, strict=True)
        ]
        verdict = _read_str(
            classify_convergence(ConvergenceInputs(signals=signals)), "classification"
        )
        counts[verdict] = counts.get(verdict, 0) + 1
        all_neutral = all(d == 0 for d in dirs)
        if all_neutral:
            all_neutral_months.append(anchor)

        # Cross-check against the scorecard on EVERY real month. The two take
        # different input records but are the same predicate over four named
        # pillars and an equivalent four-long list, so they must agree
        # everywhere — including the all-neutral months, which the scorecard
        # reaches through its explicit opt-in and the general classifier reaches
        # through its NO_SIGNAL branch.
        inputs = ScorecardInputs(
            **{
                n: PillarRead(direction=d, family=f, source=n)  # type: ignore[arg-type]
                for n, d, f in zip(_NAMES, dirs, _FAMILIES, strict=True)
            },
            allow_all_neutral=all_neutral,
        )
        other = _read_str(four_pillar_scorecard(inputs), "classification")
        if other == verdict:
            agree_with_scorecard += 1
        else:
            disagree_with_scorecard += 1
            if disagree_with_scorecard <= 3:
                print(f"    DISAGREE {anchor}: general={verdict} scorecard={other} dirs={dirs}")

    total = sum(counts.values())
    print()
    print(f"VERDICT DISTRIBUTION over {total} real monthly readings")
    for verdict in ("HIGH", "MEDIUM", "LOW", "CONFLICTED", "NO_SIGNAL"):
        n = counts.get(verdict, 0)
        if n:
            print(f"  {verdict:11s} {n:4d}  {n / total:6.1%}")

    print()
    print(
        f"  ALL-NEUTRAL readings: {len(all_neutral_months)} "
        f"({len(all_neutral_months) / total:.1%}) — these return NO_SIGNAL, which "
        "the specification's version cannot (Defect 4: it falls through to LOW)"
    )
    if all_neutral_months:
        print(
            f"    e.g. {', '.join(str(m) for m in all_neutral_months[:6])}"
            f"{' ...' if len(all_neutral_months) > 6 else ''}"
        )

    conflicted_share = counts.get("CONFLICTED", 0) / total
    space_share = settings.conflicted_base_share
    print()
    print(
        f"  CONFLICTED in HISTORY  {conflicted_share:6.1%}   "
        f"vs in the INPUT SPACE {space_share:6.1%}"
    )
    print(
        "  Both are real and they answer different questions. The space figure "
        "says what the classifier does to arbitrary inputs; the history figure "
        "says what real, correlated pillars produce. This check reports both "
        "rather than reconciling them."
    )

    print()
    print("CROSS-CHECK against four_pillar_scorecard (same data, same predicate)")
    print(f"  agree    {agree_with_scorecard}")
    print(f"  disagree {disagree_with_scorecard}")
    assert disagree_with_scorecard == 0, (
        "the two classifiers are the same predicate over four named pillars and "
        "an equivalent four-long list, so they must not disagree anywhere in the "
        "3^4 direction space — a disagreement means one of them has drifted. "
        "This assertion FAILED the first time it ran, on 95 of 761 months, and "
        "the cause was a defect in four_pillar_scorecard (its family census "
        "counted neutral pillars) rather than in the classifier under test. "
        "D-051."
    )

    # --- §15.19-D against real families -------------------------------------
    print()
    print("SECTION 15.19-D WIRING — measured families, not supplied")
    four_family = classify_convergence(ConvergenceInputs(signals=live_signals))
    one_family = classify_convergence(
        ConvergenceInputs(
            signals=[
                _signal(d, F.BLS_CPI, name) for d, name in zip(latest[1:], _NAMES, strict=True)
            ]
        )
    )
    print(f"  same directions {tuple(latest[1:])}, families varied:")
    print(
        f"    4 families -> {_read_str(four_family, 'classification'):11s} "
        f"(measured {_read_int(four_family, 'independent_families')}, "
        f"confidence {four_family.confidence})"
    )
    print(
        f"    1 family   -> {_read_str(one_family, 'classification'):11s} "
        f"(measured {_read_int(one_family, 'independent_families')}, "
        f"confidence {one_family.confidence})"
    )
    assert _read_int(one_family, "independent_families") == 1
    directional_count = sum(1 for d in latest[1:] if d != 0)
    assert _read_int(four_family, "independent_families") == directional_count, (
        "the measured family count must equal the number of DIRECTIONAL pillars, "
        "because the latest read's families are all distinct — if it exceeds that, "
        "neutral pillars are contributing families (the defect D-051 found in the "
        "scorecard)"
    )
    assert four_family.confidence > one_family.confidence, (
        "the directional families must carry MORE confidence than one repeated "
        "family — this is Section 15.19-D's whole point"
    )

    # --- Defect 7 on real data: neutral padding must not promote -------------
    print()
    print("DEFECT 7 ON REAL DATA — padding with neutral signals must not promote")
    before = classify_convergence(ConvergenceInputs(signals=live_signals))
    padded = classify_convergence(
        ConvergenceInputs(
            signals=[
                *live_signals,
                _signal(0, F.MARKET_BREAKEVEN, "neutral_breakeven"),
                _signal(0, F.MARKET_EQUITY_VOL, "neutral_vol"),
                _signal(0, F.MANUAL_ASSESSMENT, "neutral_manual"),
            ]
        )
    )
    print(
        f"  without padding: {_read_str(before, 'classification'):11s} "
        f"families {_read_int(before, 'independent_families')}  "
        f"confidence {before.confidence}"
    )
    print(
        f"  with 3 neutral : {_read_str(padded, 'classification'):11s} "
        f"families {_read_int(padded, 'independent_families')}  "
        f"confidence {padded.confidence}"
    )
    assert _read_int(padded, "independent_families") == _read_int(before, "independent_families"), (
        "three neutral signals from three new families must NOT add families to a "
        "directional verdict — that is §15.19-D's failure mode, reached by padding"
    )
    assert padded.confidence == before.confidence
    excluded = _read(padded, "families_excluded_as_neutral")
    print(f"  families excluded as neutral: {excluded}")
    # The latest reading may itself contain neutral pillars, so the excluded set
    # is the three added families PLUS any the reading already had. Assert the
    # added ones are present rather than asserting an exact length.
    assert isinstance(excluded, list)
    for added in ("market_breakeven", "market_equity_vol", "manual_assessment"):
        assert added in excluded, (
            f"{added} was added as a neutral signal and must appear in the "
            "published exclusion set, so the set-aside is visible"
        )

    # --- the input space, re-measured live ----------------------------------
    print()
    print("INPUT SPACE — re-measured here, for comparison with the config claim")
    space_counts: dict[str, int] = {}
    space_total = 0
    for combo in itertools.product((-1, 0, 1), repeat=4):
        signals = [
            _signal(d, fam, name) for d, fam, name in zip(combo, _FAMILIES, _NAMES, strict=True)
        ]
        verdict = _read_str(
            classify_convergence(ConvergenceInputs(signals=signals)), "classification"
        )
        space_counts[verdict] = space_counts.get(verdict, 0) + 1
        space_total += 1
    measured = space_counts.get("CONFLICTED", 0) / space_total
    print(f"  over all 3^4 = {space_total} direction combinations at 4 families:")
    for verdict in ("HIGH", "MEDIUM", "LOW", "CONFLICTED", "NO_SIGNAL"):
        n = space_counts.get(verdict, 0)
        if n:
            print(f"    {verdict:11s} {n:4d}  {n / space_total:6.1%}")
    print(f"  CONFLICTED measured {measured:.4f} vs config {space_share:.4f}")
    assert abs(measured - space_share) < 0.005, (
        f"the config publishes {space_share} for the CONFLICTED share of the "
        f"4-signal input space; this check measures {measured:.4f}. The config "
        "value must be recomputed whenever the classifier's arithmetic changes."
    )

    # --- what this check cannot validate ------------------------------------
    print()
    print("WHAT THIS CHECK CANNOT VALIDATE")
    print(
        "  * The family assignment is a JUDGEMENT. No series carries a source "
        "family label; the mapping above is a human decision. A reviewer could "
        "reasonably reclassify DGS10 and the confidence would move."
    )
    print(
        "  * The pillar bands are illustrative, not calibrated. They are config "
        "values with calibration_status: uncalibrated_illustrative, and this "
        "check has no labelled outcome to fit them against."
    )
    print(
        "  * Whether a CONFLICTED read PREDICTS anything is not tested. The "
        "check proves the wiring: the shape, the signs, the family behaviour and "
        "the published quantities."
    )
    print()
    print("LIVE CHECK PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
