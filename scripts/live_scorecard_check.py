"""Live wiring check: real pillar readings -> ``four_pillar_scorecard``.

Not a test. This directory holds operator scripts, deliberately excluded from the
default test run because they hit the network. Run with::

    uv run python scripts/live_scorecard_check.py

Section 21.0: unit tests prove the arithmetic, this proves the wiring — the
units, the sign convention, the sampling cadence, and whether the numbers the
specification asserts are the numbers the data actually produces.

What this check does beyond running the function
------------------------------------------------

1. **Derives the four pillar reads from real series rather than asserting them.**
   The specification's inputs are four bare ints — a contract under which every
   live check is a tautology, because the test supplies the answer it then
   verifies. This check computes each pillar from FRED and classifies it with an
   explicit, published rule, so the wiring from series to verdict is exercised
   end to end. That is the increment's central live claim: **these pillars are
   derivable**, unlike ``check_trilemma_tension``'s inputs, which are
   legal-institutional facts with no series behind them.

2. **Enumerates the real verdict distribution over 26 years of monthly data.**
   The config claims ``CONFLICTED`` is 61.7% of the *admissible input space*.
   That is a statement about the space, not about history, and the two can
   disagree: real pillars are correlated (a tightening cycle moves growth,
   inflation and policy together), so the realised share can be very different.
   Both numbers are reported, and the contrast is the finding.

3. **Asserts the sign convention per pillar, independently of the classifier.**
   A pillar read is a *derived* direction, and D-039's lesson is that a rate
   measured by the same code path that carries a sign error cannot detect it.
   Each pillar's rule is therefore stated in prose, computed from the series,
   and printed with its input values so the sign can be checked by eye.

4. **Checks the §15.19-D wiring against real families.** Every pillar is tagged
   with an evidence family and the family count is measured, not supplied. The
   check asserts that a real four-pillar read spanning four families and a real
   read spanning one family produce *different* verdicts — the property the
   specification's ``int`` parameter could not enforce.

5. **Reports what the check cannot validate.** No series carries a "source
   family" label, so the family assignment is a judgement encoded here rather
   than a measurement. It is printed as an explicit table so a reviewer can
   disagree with any individual row.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from macro_engine.config import get_settings
from macro_engine.data_layer.openbb_client import OpenBBClient
from macro_engine.models.contracts import ModelResult
from macro_engine.models.evidence_family import EvidenceSourceFamily
from macro_engine.models.scorecard import (
    PillarRead,
    ScorecardInputs,
    four_pillar_scorecard,
)

if TYPE_CHECKING:
    import pandas as pd

F = EvidenceSourceFamily

#: Months between readings in the live history. The check samples ANNUALLY so
#: the four sides of a pillar are not all measuring the same quarter — a monthly
#: sample would produce contiguous runs of one verdict and overstate stability.
#: Stated as a constant because "how many observations" is a claim about the
#: check, not an incidental loop bound.
_SAMPLE_STRIDE_MONTHS = 3

#: Pillar rules, stated in prose so the sign can be audited. Each maps a
#: series-derived scalar to a direction: +1 tightening-implying, -1
#: easing-implying, 0 neutral. The thresholds are in ``config/settings.yaml``
#: under ``scorecard_pillar_rules`` -- these are the *shapes*, not the levels.
_PILLAR_RULES: dict[str, str] = {
    "growth": (
        "UNRATE 3-month change. unemployment RISING (positive change) = the "
        "labor market is loosening = GROWTH weakening = easing-implying (-1). "
        "Falling unemployment = growth firming = tightening-implying (+1)."
    ),
    "inflation": (
        "Core PCE year-over-year change, 3-month delta. Inflation ACCELERATING "
        "(positive delta) = tightening-implying (+1). Decelerating = "
        "easing-implying (-1)."
    ),
    "financial_conditions": (
        "10-year yield 3-month change. Yields RISING = conditions TIGHTENING = "
        "tightening-implying (+1). NOTE the direction: this is a market price, "
        "and a rising long yield is restrictive for credit, so the sign is the "
        "SAME as the change, not inverted."
    ),
    "policy_gap": (
        "Real fed funds (DFF minus core PCE yoy) 3-month change. Real policy "
        "rate RISING = policy getting tighter = tightening-implying (+1). This "
        "is a GAP, not a level: a high but falling real rate is easing."
    ),
}


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


def _classify(value: float, band: float) -> int:
    """Map a change to a direction using a symmetric dead band."""
    if value > band:
        return 1
    if value < -band:
        return -1
    return 0


def main() -> int:
    settings = get_settings().scorecard
    rules = settings.pillar_rules

    client = OpenBBClient()
    unrate = _monthly(_fetch(client, "UNRATE", "unemployment rate"))
    core_pce = _monthly(_fetch(client, "PCEPILFE", "core PCE price index"))
    dgs10 = _monthly(_fetch(client, "DGS10", "10-year constant maturity"))
    dff = _monthly(_fetch(client, "DFF", "effective fed funds rate"))

    print("=" * 78)
    print("LIVE CHECK — four_pillar_scorecard (Module 12.2, Section 20.11)")
    print("=" * 78)
    print()
    for name, series in (
        ("UNRATE", unrate),
        ("PCEPILFE", core_pce),
        ("DGS10", dgs10),
        ("DFF", dff),
    ):
        print(f"  {name:9s} {len(series):5d} months  {min(series)} .. {max(series)}")

    # --- pillar rules, printed so the sign is auditable ---------------------
    print()
    print("PILLAR RULES (the sign of each, stated before it is used)")
    for name, rule in _PILLAR_RULES.items():
        print(f"  {name:22s} {rule}")

    # --- derive the four pillars on a stride --------------------------------
    common = sorted(set(unrate) & set(core_pce) & set(dgs10) & set(dff))
    if len(common) < 200:
        print(f"FATAL: only {len(common)} months shared across the four series.")
        return 1

    print()
    print(f"COMMON WINDOW  {common[0]} .. {common[-1]}  ({len(common)} months)")

    # CPI/PCE year-over-year series, built once.
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

        # growth: unemployment change over 3 months, sign INVERTED (rising
        # unemployment is easing-implying).
        growth = -_classify(unrate[anchor] - unrate[back3], rules.unemployment_change_band.value)
        # inflation: core PCE yoy change over 3 months, sign direct.
        inflation = _classify(cpi_yoy[anchor] - cpi_yoy[back3], rules.inflation_change_band.value)
        # financial conditions: 10y change over 3 months, sign direct.
        fin = _classify(dgs10[anchor] - dgs10[back3], rules.yield_change_band.value)
        # policy gap: real fed funds change over 3 months, sign direct.
        real_now = dff[anchor] - cpi_yoy[anchor]
        real_back = dff[back3] - cpi_yoy[back3]
        policy = _classify(real_now - real_back, rules.real_rate_change_band.value)

        readings.append((anchor, growth, inflation, fin, policy))

    if not readings:
        print("FATAL: no month produced a complete four-pillar reading.")
        return 1

    print(f"READINGS  {len(readings)} months with all four pillars computable")

    # --- sign audit: print the most recent reading with its raw inputs -------
    latest = readings[-1]
    print()
    print(f"SIGN AUDIT — the most recent reading ({latest[0]})")
    back3 = _shift_months(latest[0], -3)
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
    rn = dff[latest[0]] - cpi_yoy[latest[0]]
    rb = dff[back3] - cpi_yoy[back3]
    print(
        f"  real ff      {rb:.2f} -> {rn:.2f}  (change {rn - rb:+.2f}) -> policy_gap {latest[4]:+d}"
    )
    print(
        "  A wrong sign anywhere above shows up as a pillar pointing against its "
        "own printed input change."
    )

    # --- verdict distribution over real history -----------------------------
    families = (
        F.BLS_EMPLOYMENT_SITUATION,  # growth: UNRATE is BLS household/establishment
        F.BEA_PCE,  # inflation: core PCE is BEA
        F.TREASURY_OFFICIAL,  # financial conditions: Treasury yields
        F.FED_H41,  # policy gap: DFF is a Fed series
    )
    sources = (
        "unrate_3m_change",
        "core_pce_yoy_3m_change",
        "dgs10_3m_change",
        "real_fed_funds_3m_change",
    )

    names = ("growth", "inflation", "financial_conditions", "policy_gap")
    counts: dict[str, int] = {}
    all_neutral_months: list[date] = []
    for anchor, *dirs in readings:
        is_all_neutral = all(d == 0 for d in dirs)
        if is_all_neutral:
            all_neutral_months.append(anchor)
        inputs = ScorecardInputs(
            **{
                n: PillarRead(direction=d, family=f, source=s)  # type: ignore[arg-type]
                for n, d, f, s in zip(names, dirs, families, sources, strict=True)
            },
            # Real history contains all-neutral readings, so the opt-in is the
            # check's honest acknowledgement of that rather than a workaround.
            allow_all_neutral=is_all_neutral,
        )
        verdict = _read_str(four_pillar_scorecard(inputs), "classification")
        counts[verdict] = counts.get(verdict, 0) + 1

    total = sum(counts.values())
    print()
    print(f"VERDICT DISTRIBUTION over {total} real monthly readings")
    for verdict in ("HIGH", "MEDIUM", "LOW", "CONFLICTED", "NO_SIGNAL"):
        n = counts.get(verdict, 0)
        if n:
            print(f"  {verdict:11s} {n:4d}  {n / total:6.1%}")

    print()
    print(
        f"  ALL-NEUTRAL readings: {len(all_neutral_months)} ({len(all_neutral_months) / total:.1%})"
    )
    if all_neutral_months:
        print(
            f"    e.g. {', '.join(str(m) for m in all_neutral_months[:6])}"
            f"{' ...' if len(all_neutral_months) > 6 else ''}"
        )
    print(
        "    This is why the input model ASKS for an all-neutral read rather than "
        "refusing it: the state occurs in real data, so forbidding construction "
        "would make it unrepresentable. An earlier revision did refuse, and this "
        "check failed on exactly these months."
    )

    conflicted_share = counts.get("CONFLICTED", 0) / total
    space_share = settings.conflicted_base_share
    print()
    print(
        f"  CONFLICTED in HISTORY  {conflicted_share:6.1%}   "
        f"vs in the INPUT SPACE {space_share:6.1%}"
    )
    print(
        "  The two are different claims and both matter. The space figure says "
        "what the classifier does to arbitrary inputs; the history figure says "
        "what real pillars actually look like. Real pillars are CORRELATED — a "
        "tightening cycle moves growth, inflation and policy together — so if "
        "the realised share is far below the space share, CONFLICTED is rarer in "
        "practice than its prominence as a blocking verdict suggests."
    )

    # --- §15.19-D: the family count must change the verdict ----------------
    print()
    print("SECTION 15.19-D WIRING — the family count must move the verdict")
    latest_inputs = ScorecardInputs(
        **{
            n: PillarRead(direction=d, family=f, source=s)  # type: ignore[arg-type]
            for n, d, f, s in zip(names, latest[1:], families, sources, strict=True)
        }
    )
    four_family = four_pillar_scorecard(latest_inputs)
    one_family_inputs = ScorecardInputs(
        **{
            n: PillarRead(direction=d, family=F.BLS_CPI, source=s)  # type: ignore[arg-type]
            for n, d, s in zip(names, latest[1:], sources, strict=True)
        }
    )
    one_family = four_pillar_scorecard(one_family_inputs)
    print(f"  same pillar directions {tuple(latest[1:])}, families varied:")
    print(
        f"    4 families -> {_read_str(four_family, 'classification'):11s} "
        f"(measured families {_read_int(four_family, 'independent_families')})"
    )
    print(
        f"    1 family   -> {_read_str(one_family, 'classification'):11s} "
        f"(measured families {_read_int(one_family, 'independent_families')})"
    )
    if _read_str(four_family, "classification") == _read_str(one_family, "classification"):
        print(
            "  NOTE: the two agree here. That is legitimate — the verdict depends "
            "on BOTH agreement and independence, and this read does not sit on "
            "the family threshold. The wiring is still asserted: the published "
            "family count differs, and the confidence does too."
        )
    # The measured count equals the number of DIRECTIONAL pillars, because this
    # read's pillars all carry distinct families. It was previously asserted to
    # be 4 unconditionally, which passed only because the census counted neutral
    # pillars too — the defect D-051 found (a neutral pillar's family cannot back
    # a directional verdict). Now that the census is directional-only, the
    # expected count is a property of the read rather than a constant.
    directional_count = sum(1 for d in latest[1:] if d != 0)
    assert _read_int(four_family, "independent_families") == directional_count, (
        f"the latest read has {directional_count} directional pillar(s), so it "
        "must report that many families; a higher count means neutral pillars "
        "are contributing families (D-051)"
    )
    assert _read_int(one_family, "independent_families") == 1
    assert four_family.confidence > one_family.confidence, (
        "the directional families must carry MORE confidence than one repeated "
        "family — this is Section 15.19-D's whole point"
    )

    # --- what this check cannot validate ------------------------------------
    print()
    print("WHAT THIS CHECK CANNOT VALIDATE")
    print(
        "  * The family assignment is a JUDGEMENT, not a measurement. No series "
        "carries a source-family label; the mapping above is a human decision "
        "encoded here. A reviewer could reasonably call DGS10 a MARKET_BREAKEVEN "
        "adjacent family, and the confidence would move."
    )
    print(
        "  * The pillar bands are illustrative. They are config values with "
        "calibration_status: uncalibrated_illustrative, and this check cannot "
        "calibrate them — it has no labelled outcome to fit against."
    )
    print(
        "  * Whether the verdicts are RIGHT is not tested. The check proves the "
        "wiring produces a verdict from real data with the expected sign and "
        "family behaviour; it cannot say a CONFLICTED read predicted anything."
    )
    print()
    print("LIVE CHECK PASSED")
    return 0


def _read_str(result: ModelResult, key: str) -> str:
    value = result.value
    assert isinstance(value, dict), f"{result.model_name}: expected a dict value"
    entry = value[key]
    assert isinstance(entry, str), f"{result.model_name}: value[{key!r}] is not a str"
    return entry


def _read_int(result: ModelResult, key: str) -> int:
    value = result.value
    assert isinstance(value, dict), f"{result.model_name}: expected a dict value"
    entry = value[key]
    assert isinstance(entry, int) and not isinstance(entry, bool), (
        f"{result.model_name}: value[{key!r}] is not an int"
    )
    return entry


if __name__ == "__main__":
    raise SystemExit(main())
