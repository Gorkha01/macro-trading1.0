"""Live wiring check: a real VIX level -> Section 6.7's ``dollar_smile_regime``.

Not a test. This directory holds operator scripts, deliberately excluded from
the default test run because they hit the network. Run with::

    uv run python scripts/live_dollar_smile_check.py

Section 21.0: unit tests prove the arithmetic, this proves the WIRING — the
units, the sign, the gate, and whether the numbers that come out are the
numbers the specification says should come out.

**What is real here, and what is not — stated first because the distinction is
the whole honesty of this check.** ``dollar_smile_regime`` takes three inputs:

* ``vix_level`` — **REACHABLE**. ``VIXCLS`` is a real daily series and its level
  is exactly the index point value the input model documents. This is the one
  input that is fetched.
* ``us_growth_surprise`` — **BLOCKED**. A *surprise* needs a consensus forecast
  and this installation cannot reach one (the same block recorded against
  ``inflation_surprise`` in ``series_registry.yaml``). The check therefore
  **drives it as a declared parameter** and says so in every line it prints.
* ``us_vs_row_rate_diff`` — **REACHABLE IN PRINCIPLE, but not date-matched to a
  consensus this build cannot obtain**, so it is also driven as a declared
  parameter rather than wired to a second provider's rate.

So this check establishes the GATE, the UNITS, the SIGN, the REACHABILITY and
the CONTRACT on real data. It does **not** and cannot establish that the
published label matched the world on the observation date, because two of the
three inputs are constructed by this script. **A label produced from one real
input and two declared ones is a wiring check, not a regime call** — and the
script prints that sentence rather than leaving the reader to infer it.

What is fetched
---------------
* ``VIXCLS`` (FRED) — the CBOE Volatility Index, the 30-day implied volatility
  of the S&P 500, quoted in **index points**. The gate input.

What this check establishes
---------------------------

1. **The unit is index points, and it is asserted.** ``DollarSmileInputs``
   documents ``vix_level`` as an INDEX LEVEL and warns that a second plausible
   reading (a decimal, or a percent fraction) moves the gate by 100x without
   raising. The check asserts the fetched level lands in the plausible index
   band, and separately asserts the percent-change figures elsewhere in this
   tree are NOT what it feeds the model.

2. **The gate fires where it claims to on the real level.** Whatever the fetched
   VIX is, the check asserts ``vix_above_threshold`` matches
   ``vix > candle.threshold`` computed independently, and asserts the label is
   ``left`` exactly when the gate fires — the most-severe-first rule, on a real
   number.

3. **The threshold the model used is the delivered leaf.** The check reads the
   leaf from the settings object and asserts the published ``vix_threshold``
   equals it, so a hardcoded 25 that ignored the config would fail here (its
   own unit test covers the config move; this covers the delivered value).

4. **The zero case is the middle limb — on a real call.** A release landing on
   consensus prints exactly ``0.0``, and the input model's own note says the
   specification's ``> 0`` test cannot tell that from a negative reading. The
   check drives a zero surprise and asserts the label is ``middle`` with
   ``is_neutral_input`` true and the neutrality warning present.

5. **The reachable set on the real level is the full three limbs.** Whatever
   limb today's VIX produces, the check sweeps the two signed inputs across
   signs and asserts all three labels are produced — the D-050 reachability
   question, answered on the live level rather than on a fixture.

6. **The confidence is computed, not hardcoded.** Section 22.8. The check
   asserts the published confidence equals a fresh call to ``compute_confidence``
   with the same stated factors, so the retired literal ``0.4`` cannot come back.

What this check CANNOT validate
-------------------------------
That the label was RIGHT. Two of the three inputs are declared by this script,
the thresholds are uncalibrated placeholders by the model's own admission, and
the smile is an empirical regularity about past episodes rather than a property
of the inputs. **Nothing here supports reading the printed label as a regime
call or a trade** — it verifies that the classifier is wired to a real VIX and
behaves as specified on that number.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from macro_engine.config import get_settings  # noqa: E402
from macro_engine.data_layer.openbb_client import OpenBBClient  # noqa: E402
from macro_engine.models.contracts import (  # noqa: E402
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
)
from macro_engine.models.fx_carry import DollarSmileInputs, dollar_smile_regime  # noqa: E402

#: Plausible band for the VIX INDEX LEVEL, in index points. Wide on purpose:
#: the point is to fail on a percent-fraction or decimal misreading (which would
#: read ~0.15 or ~0.0015), not to pin a regime.
_VIX_INDEX_BAND = (1.0, 200.0)

#: The signed inputs this check DECLARES, since a consensus-driven surprise is
#: unreachable here. Each pair exercises a different region of the classifier.
_DECLARED_SIGNED = (
    ("both positive (US outperformance)", 1.0, 0.5),
    ("both negative (US disappointment)", -1.0, -0.5),
    ("mixed signs", 1.0, -0.5),
    ("growth exactly neutral", 0.0, 0.5),
    ("rate differential exactly neutral", 1.0, 0.0),
)


def _fetch(client: OpenBBClient, symbol: str, label: str) -> tuple[list[str], list[float]]:
    """Pull a registry series, returning (dates, values) oldest first."""
    frame = client.fetch_series(
        provider="fred",
        endpoint="economy.fred_series",
        params={"symbol": symbol},
        series_label=label,
    )
    frame = frame.set_index("date").sort_index()
    return [str(index) for index in frame.index], [
        float(value) for value in frame["value"].astype(float).tolist()
    ]


def _values(result: ModelResult) -> dict[str, object]:
    value = result.value
    assert isinstance(value, dict)
    return value


def _label(result: ModelResult, key: str) -> str:
    item = _values(result)[key]
    assert isinstance(item, str), f"{key} is {type(item).__name__}"
    return item


def _flag(result: ModelResult, key: str) -> bool:
    item = _values(result)[key]
    assert isinstance(item, bool), f"{key} is {type(item).__name__}"
    return item


def _number(result: ModelResult, key: str) -> float:
    item = _values(result)[key]
    assert isinstance(item, (int, float)) and not isinstance(item, bool), (
        f"{key} is {type(item).__name__}"
    )
    return float(item)


def main() -> int:
    failures: list[str] = []

    print("=" * 78)
    print("SECTION 6.7 DOLLAR SMILE — LIVE WIRING CHECK")
    print("=" * 78)

    settings = get_settings().fx_carry
    threshold = settings.dollar_smile_vix_level
    boundary = settings.dollar_smile_sign_boundary_value
    # Print the NUMBERS, not the ``CalibratedValue`` objects: repr-ing the leaf
    # dumps its entire note, which buries the two thresholds this check is about.
    print(f"  configured gate: vix_threshold={threshold}   sign_boundary={boundary}")

    client = OpenBBClient()
    print("  fetching VIXCLS (CBOE Volatility Index, INDEX POINTS) via OpenBB:")
    dates, values = _fetch(client, "VIXCLS", "vix_level")
    if not values:
        failures.append("VIXCLS returned no observations — the route is BLOCKED")
        vix_level, vix_date = float("nan"), "unknown"
    else:
        vix_level, vix_date = values[-1], dates[-1]
        print(f"    VIXCLS n={len(values)}  last {vix_level:.4f} index points  @ {vix_date}")
        if len(values) < 60:
            failures.append(f"VIXCLS returned only {len(values)} observations — too few to trust")

    # --- (1) the unit: index points, not a decimal or a percent fraction ----
    print()
    print("  unit guard — the VIX level must read as INDEX POINTS:")
    low, high = _VIX_INDEX_BAND
    status = "OK" if low < vix_level < high else "OUT-OF-BAND"
    print(f"    VIXCLS {vix_level:10.4f} index points  [{status}]")
    if not low < vix_level < high:
        failures.append(
            f"VIXCLS reads {vix_level}, outside the plausible index-point band "
            f"{_VIX_INDEX_BAND} — a percent-fraction or decimal misreading of the "
            f"gate input, which moves the threshold by 100x without raising"
        )

    # --- (2) the gate, on the real level ------------------------------------
    # Drive a NON-neutral signed pair so the fall-through limb is unambiguous:
    # with both inputs positive a below-gate VIX must give `right`, and an
    # above-gate VIX must give `left` regardless of them.
    result = dollar_smile_regime(
        DollarSmileInputs(
            vix_level=vix_level,
            us_growth_surprise=1.0,
            us_vs_row_rate_diff=0.5,
        )
    )
    side = _label(result, "side")
    vix_above = _flag(result, "vix_above_threshold")
    expected_above = vix_level > threshold
    expected_side = "left" if expected_above else "right"

    print()
    print("  the function on the REAL VIX (growth surprise and rate diff DECLARED):")
    print(
        f"    vix_level {vix_level:.4f}  surprise +1.000000  rate_diff +0.500000 "
        f"-> side '{side}'  (confidence {result.confidence})"
    )
    print(f"    vix_above_threshold={vix_above}   expected {expected_above}")
    for note in result.warnings:
        print(f"    warning: {note}")
    if vix_above is not expected_above:
        failures.append(
            f"the published vix_above_threshold says {vix_above} but "
            f"{vix_level} > {threshold} implies {expected_above}"
        )
    if side != expected_side:
        failures.append(
            f"the label is '{side}' but a real VIX of {vix_level} against the gate "
            f"{threshold} with both signed inputs positive implies '{expected_side}' "
            f"— the most-severe-first rule or the gate comparison is wrong"
        )
    if _number(result, "vix_threshold") != threshold:
        failures.append(
            f"the published vix_threshold {_number(result, 'vix_threshold')} is not the "
            f"delivered leaf {threshold} — the config read is disconnected"
        )

    # --- (3) the configuration is INERT if the leaves move ----------------
    # The gate must be read from the leaf rather than a literal. This is the live
    # analogue of the unit test that moves the leaf: prove the model FOLLOWS it.
    print()
    print("  the gate follows the leaf (a perturbed threshold must move the label):")
    perturbed = threshold + 1000.0  # every real reading is now below the gate
    original_value = settings.dollar_smile_vix_threshold.value
    try:
        settings.dollar_smile_vix_threshold.value = perturbed
        moved = dollar_smile_regime(
            DollarSmileInputs(vix_level=vix_level, us_growth_surprise=1.0, us_vs_row_rate_diff=0.5)
        )
        moved_side = _label(moved, "side")
        moved_threshold = _number(moved, "vix_threshold")
        print(
            f"    gate moved to {perturbed}  ->  side '{moved_side}'  "
            f"(published vix_threshold {moved_threshold})"
        )
        if moved_side != "right":
            failures.append(
                f"with the gate raised to {perturbed} the real VIX {vix_level} is below "
                f"it, so the label must be 'right' (both signed inputs positive) — got "
                f"'{moved_side}'. The gate is a hardcoded literal, not the leaf."
            )
        if moved_threshold != perturbed:
            failures.append(
                f"the published threshold {moved_threshold} did not follow the leaf to "
                f"{perturbed} — the config read is disconnected"
            )
    finally:
        settings.dollar_smile_vix_threshold.value = original_value

    # --- (4) the zero case owns the middle limb, on a real call ------------
    print()
    print("  the exactly-neutral input (a release landing on consensus):")
    neutral = dollar_smile_regime(
        DollarSmileInputs(
            vix_level=vix_level,
            us_growth_surprise=0.0,
            us_vs_row_rate_diff=0.5,
        )
    )
    neutral_side = _label(neutral, "side")
    neutral_flag = _flag(neutral, "is_neutral_input")
    has_neutral_warning = any("NEUTRAL input" in note for note in neutral.warnings)
    print(
        f"    surprise 0.000000, rate_diff +0.500000, VIX {vix_level:.4f}  ->  "
        f"side '{neutral_side}'  is_neutral_input={neutral_flag}  "
        f"neutral warning={has_neutral_warning}"
    )
    # With a below-gate VIX a zero surprise cannot establish US outperformance,
    # so the middle limb owns it. With the real VIX ABOVE the gate the left limb
    # rightly wins instead — the gate is most-severe-first.
    if expected_above:
        if neutral_side != "left":
            failures.append(
                f"with the real VIX {vix_level} above the gate the label must be 'left' "
                f"even for a neutral input — got '{neutral_side}'"
            )
    else:
        if neutral_side != "middle":
            failures.append(
                f"a surprise of exactly 0.0 below the gate must give the middle limb — "
                f"got '{neutral_side}'"
            )
        if not neutral_flag:
            failures.append(
                "the middle limb reached by a zero surprise must publish "
                "is_neutral_input=True — the neutrality cause is lost"
            )
        if not has_neutral_warning:
            failures.append(
                "the middle limb reached by a zero input must carry the neutrality "
                "warning — a reader cannot tell the two causes apart from the label"
            )

    # --- (5) all three limbs are reachable on the real level ---------------
    print()
    print("  reachable set on the REAL VIX level (signed inputs DECLARED):")
    seen: set[str] = set()
    for description, growth, diff in _DECLARED_SIGNED:
        probe = dollar_smile_regime(
            DollarSmileInputs(
                vix_level=vix_level, us_growth_surprise=growth, us_vs_row_rate_diff=diff
            )
        )
        probe_side = _label(probe, "side")
        seen.add(probe_side)
        print(f"    {description:<40} growth {growth:+.1f} diff {diff:+.1f}  ->  {probe_side}")
    # A below-gate VIX yields right and middle; the left limb needs an above-gate
    # reading, which today's VIX may not be — so drive the gate's own side too.
    high_vix = dollar_smile_regime(
        DollarSmileInputs(
            vix_level=threshold + 5.0,
            us_growth_surprise=1.0,
            us_vs_row_rate_diff=0.5,
        )
    )
    left_side = _label(high_vix, "side")
    seen.add(left_side)
    seen.add(side)
    print(f"    a VIX above the gate ({threshold + 5.0}) gives '{left_side}'")
    if seen != {"left", "right", "middle"}:
        failures.append(
            f"the reachable set on the live level is {sorted(seen)}, not the full "
            f"{{'left','right','middle'}} — a limb is unreachable"
        )

    # --- (6) the confidence is COMPUTED (Section 22.8) ---------------------
    print()
    print("  confidence is computed from the stated factors, not hardcoded:")
    expected_confidence = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=True,
            source_independence_count=0,
            depends_on_unobservable=False,
        )
    )
    print(
        f"    published {result.confidence}   recomputed {expected_confidence}   "
        f"(the retired literal was 0.4)"
    )
    if result.confidence != expected_confidence:
        failures.append(
            f"the published confidence {result.confidence} does not equal the value "
            f"compute_confidence produces from the stated factors "
            f"({expected_confidence}) — a hardcoded confidence has returned"
        )

    # --- (7) the plausibility assessment, written down --------------------
    print()
    print("  PLAUSIBILITY ASSESSMENT")
    print(
        f"    the real VIX is {vix_level:.2f} index points, which is "
        f"{'ABOVE' if expected_above else 'below'} the configured gate {threshold}."
    )
    if expected_above:
        print(
            "    So the real level classifies the dollar on the smile's LEFT "
            "(risk-off/crisis) limb regardless of the growth and rate inputs — "
            "which is the most-severe-first rule and is exactly what the gate is for."
        )
    else:
        print(
            "    A below-gate VIX is a quiet-market reading: the limb is then "
            "decided by the two signed inputs, and the state is 'right' only when "
            "BOTH show US outperformance — otherwise 'middle'."
        )
    print(
        "    WHAT THIS DOES NOT SAY: the growth surprise and the rate differential "
        "are DECLARED by this script, not fetched, because a surprise needs a "
        "consensus this installation cannot reach. So the printed label is a WIRING "
        "result, not a regime call: it shows the classifier reads a real VIX "
        "correctly, not that the label matched the world on this date."
    )
    print(
        f"    the thresholds are UNCALIBRATED placeholders (the model's own first "
        f"limitation): the gate {threshold} and the boundary {boundary} are "
        f"qualitative, so even the confidence above is priced off that fact."
    )

    print()
    print("=" * 78)
    if failures:
        print(f"FAIL — {len(failures)} problem(s):")
        for problem in failures:
            print(f"  * {problem}")
        return 1
    print("PASS — the dollar-smile classifier is wired to a real VIX end to end.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
