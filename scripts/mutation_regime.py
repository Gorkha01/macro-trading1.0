"""Mutation sweep for Module 3's ``classify_regime_rule_based``.

Each mutation reverts one D-045 correction to a plausible alternative, and each
must be killed:

* **M1** restores Section 6.2's own branch chain. ``M1a`` is the sweep's most
  important mutation: if the reachability test does not catch the specification's
  logic, the correction is decoration. ``M1b`` narrows only the ``recession``
  guard (the deep-contraction-with-rising-inflation defect), and ``M1c``
  collapses the grid back to the specification's single-level structure so the
  three unreachable states return.
* **M2** breaks the bands — hardcoding one, making an edge exclusive, or
  dropping the neutral band so a flat reading is classified by fallthrough.
* **M3** breaks the hysteresis — the growth-momentum band and the sign split
  inside it, which is what makes a revision of a few basis points unable to flip
  the label.
* **M4** breaks the corroboration logic — the sign pairing that a naive
  implementation gets backwards, and the zero-is-not-evidence rule.
* **M5** drops a disclosure.
* **M6** drops a published component, so the state stops being recomputable.
* **M7** weakens the input contract.
* **M8** restores the specification's hardcoded ``confidence=0.5`` or forces the
  heuristic factor off.
* **C1** swaps or hardcodes the config accessors.

A survivor is one of three things (D-031): a weak test, an **inert** mutation, or
a **broken** mutation. The runner reports a pattern-miss separately from a
survival, and it **heals before it measures** — an interrupted run leaves the
mutated file on disk, and a naive re-run would adopt it as the baseline (D-035
rule 19).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _sweep_gate import (
    _clear_in_flight,
    _set_in_flight,
    check_only,
    check_only_requested,
    check_targets,
    format_problems,
    install_signal_restore,
    line_buffer_stdout,
    record_pristine,
    restore_from_sidecar,
    sidecar_for,
)

SRC = Path("src/macro_engine/models/regime.py")
CONFIG = Path("src/macro_engine/config.py")

# --- M1: the branch logic --------------------------------------------------
# The three band tests, as shipped.
_GROWTH_AND_STATE = (
    '    if growth == "deep_contraction":\n'
    '        return "recession"\n'
    '    if growth == "contraction":\n'
    '        if inflation == "rising":\n'
    '            return "stagflation"\n'
    "        # Falling or flat momentum below trend. Split slowdown from recovery on\n"
    "        # the DIRECTION of the gap, which is the only thing that distinguishes\n"
    "        # them: recovery needs the gap to be closing.\n"
    '        if inflation == "falling" and gap_change is not None and gap_change > 0.0:\n'
    '            return "recovery"\n'
    '        return "slowdown"'
)

_RECESSION_GUARD = '    if growth == "deep_contraction":\n        return "recession"'

# The `_growth_axis` function body, as shipped.
_GROWTH_AXIS = (
    "    if gap < settings_recession:\n"
    '        return "deep_contraction"\n'
    "    if gap < settings_weak:\n"
    '        return "contraction"\n'
    '    return "above_trend"'
)

# The `_inflation_axis` function body, as shipped.
_INFLATION_AXIS = (
    "    if trend > neutral_band:\n"
    '        return "rising"\n'
    "    if trend < -neutral_band:\n"
    '        return "falling"\n'
    '    return "flat"'
)

# The at-trend / near-trend block, as shipped.
_AT_TREND_BLOCK = (
    "    if abs(gap) <= momentum_band:\n"
    "        # AT TREND: the gap is inside the hysteresis band. Which state this is\n"
    "        # depends on WHERE in the band, and the sign is the only thing that\n"
    "        # separates an economy still climbing into trend from one that has\n"
    "        # settled onto it — Section 6.2's own distinction between\n"
    "        # `early_expansion` and `mid_expansion`, kept, but read against the\n"
    "        # band rather than against a bare zero so it survives a revision.\n"
    '        if inflation == "rising":\n'
    "            # At trend with inflation turning up: reflation, not expansion.\n"
    '            return "reflation"\n'
    "        if gap < 0.0:\n"
    "            # Below potential but inside the band, inflation not rising:\n"
    "            # activity is climbing back toward trend. This is the state the\n"
    "            # specification declared and could not reach.\n"
    '            return "early_expansion"\n'
    '        return "mid_expansion"'
)

# --- M4: the corroboration logic -------------------------------------------
_CORROBORATION = (
    "        if self.output_gap == 0.0 or self.unemployment_gap == 0.0:\n"
    "            return False\n"
    "        return (self.output_gap < 0.0) == (self.unemployment_gap > 0.0)"
)
_ZERO_GUARD = (
    "        if self.output_gap == 0.0 or self.unemployment_gap == 0.0:\n            return False\n"
)

# --- M5/M6: disclosures and published components ---------------------------
_BASE_RATE_ABSENT_WARNING = (
    '"NO BASE RATE AVAILABLE: the published state frequencies have not been "'
)
_MOMENTUM_DISCLOSURE = (
    '"The inflation axis is MOMENTUM (3-month annualized change), not the level: "'
)
_FLAT_WARNING = 'f"Inflation momentum is FLAT ({inputs.inflation_trend_3m:+.2f}pp, inside the "'
_AT_TREND_WARNING = 'f"The output gap is AT TREND ({inputs.output_gap:+.2f}%, inside the "'
_RECESSION_WARNING = '"RECESSION is a severe label returned by a threshold comparison on a "'
_RECOVERY_UNDECIDABLE = (
    '"SLOWDOWN, NOT RECOVERY — the distinction was not decidable. This reading "'
)
_DISAGREE_WARNING = 'f"SLACK MEASURES DISAGREE: the output gap ({inputs.output_gap:+.2f}%) "'

_STATE_KEY = '            "state": state,'
_AXIS_KEYS = '            "growth_axis": growth,\n            "inflation_axis": inflation,'
_CORROB_KEY = '            "slack_corroborated": inputs.slack_corroborated,'
_BASE_RATE_KEY = '            "state_base_rate": state_base_rate,'
_AXIS_BASE_RATE_KEY = '            "rising_inflation_base_rate": axis_base_rate,'
_AXIS_BASE_RATE_WARNING = (
    "        warnings.append(\n"
    '            f"INFLATION-AXIS BASE RATE: over the same '
    '{base_rates.observations_measured} "'
)

# --- M7: the contract ------------------------------------------------------
_EXTRA_FORBID = '    model_config = ConfigDict(extra="forbid")\n\n    output_gap: float = Field('
_INPUTS_USED = (
    "        inputs_used=[\n"
    '            "output_gap",\n'
    '            "inflation_yoy",\n'
    '            "inflation_trend_3m",\n'
    '            "unemployment_gap",\n'
    "        ],"
)

# --- M8: confidence --------------------------------------------------------
_HEURISTIC = "            is_heuristic_not_calibrated=not _thresholds_calibrated(),"
# Each of these two lines occurs in BOTH `classify_regime_rule_based` and
# `check_trilemma_tension`, so the bare statement is AMBIGUOUS (D-048).
# `str.replace(..., 1)` happens to take the first, which IS the intended
# function — so these worked by luck, and this sweep had no `check_targets`
# to notice the day that luck ran out. D-064's `tools/sweep_health.py`
# found them by running its own target check on the ungated sweeps; each
# anchor is now extended through the regime-specific comment above it.
_INDEPENDENCE = (
    "            # Two surveys of ONE concept (slack), not two independent concepts.\n"
    "            source_independence_count=0,"
)
_UNOBSERVABLE = (
    "            # unemployment_gap against unobservable u*.\n"
    "            depends_on_unobservable=True,"
)

# --- config accessors ------------------------------------------------------
_RECESSION_PROP = "        return float(self.recession_output_gap_max.value)"
_WEAK_PROP = "        return float(self.weak_growth_output_gap_max.value)"
_NEUTRAL_BAND_PROP = "        return float(self.neutral_inflation_trend_band_pp.value)"
_MOMENTUM_BAND_PROP = "        return float(self.growth_momentum_band_pp.value)"
# Targets RegimeBaseRates.rate_map specifically. A bare token like
# `return self.base_rates` would match OTHER models' properties first, and the
# mutation would survive for the wrong reason — the D-031 scoping rule.
_REGIME_RATE_ENTRY = '            "slowdown": float(self.rates.slowdown_value.value),'
# The axis-base-rate property. A hardcoded return here would make the published
# disclosure and the warning constant, so the fixture's 0.775 would not follow.
_AXIS_BASE_RATE_PROP = "        return float(self.measured_rising_inflation_rate.value)"

_MUTATIONS: list[tuple[str, Path, str, str]] = [
    # -- O-72 canary (CONTROL) --------------------------------------------
    # NOT a revert of a project correction: a mutation that is CERTAIN to be
    # caught, so the sweep can REFUSE TO CERTIFY when it survives. A sweep
    # whose anchors resolve but whose test selection no longer reaches the
    # mutated module reports every mutant as killed -- the D-051 trap. The
    # canary is the only entry here that distinguishes 'the suite is strong'
    # from 'the sweep stopped testing'.
    #
    # It replaces a module-level literal with a SYNTAX ERROR, so the kill is
    # STRUCTURAL (`tests/` cannot collect) rather than incidental, and the
    # mutation cannot quietly become inert the way a behavioural one can.
    (
        # The anchor is the FUTURE IMPORT, not the `__all__` block it used to be.
        # MEASURED at D-105: adding a name to `__all__` (which every increment
        # that exports a function does) made the old anchor occur ZERO times, and
        # `sweep_health.py` correctly reported the canary as a LEFTOVER — the
        # leftover predicate cannot tell a drifted anchor from an applied
        # mutation (O-119). TWO sweeps anchor on this same file, so one `__all__`
        # edit broke both. The future import is the module's first statement and
        # does not churn; it occurs exactly once, which `check_targets` verifies.
        "CANARY1 the module literal is replaced with a syntax error (CONTROL)",
        SRC,
        "from __future__ import annotations",
        "__CANARY__ = <<<SYNTAX ERROR>>>",
    ),
    # --- M1: the branch logic --------------------------------------------
    (
        "M1a Section 6.2's single-level chain restored (three states die)",
        SRC,
        _GROWTH_AND_STATE,
        '    if growth == "deep_contraction" and inflation == "falling":\n'
        '        return "recession"\n'
        '    if growth == "contraction" and inflation == "rising":\n'
        '        return "stagflation"\n'
        '    if growth == "deep_contraction":\n'
        '        return "late_expansion"\n'
        '    if growth == "above_trend" and inflation == "falling":\n'
        '        return "disinflation"\n'
        '    if growth == "above_trend" and inflation != "rising":\n'
        '        return "mid_expansion"\n'
        '    return "early_expansion"',
    ),
    (
        "M1b the recession guard requires falling inflation (the spec's own narrow guard)",
        SRC,
        _RECESSION_GUARD,
        '    if growth == "deep_contraction" and inflation == "falling":\n'
        '        return "recession"',
    ),
    (
        "M1c recession demoted to require contraction depth twice (stagflation wins deep)",
        SRC,
        _RECESSION_GUARD,
        '    if growth == "deep_contraction" and inflation == "rising":\n'
        '        return "reflation"\n'
        '    if growth == "deep_contraction":\n'
        '        return "recession"',
    ),
    (
        "M1d the recovery split removed (recovery becomes unreachable again)",
        SRC,
        _GROWTH_AND_STATE,
        '    if growth == "deep_contraction":\n'
        '        return "recession"\n'
        '    if growth == "contraction":\n'
        '        if inflation == "rising":\n'
        '            return "stagflation"\n'
        '        return "slowdown"',
    ),
    # --- M2: the bands ---------------------------------------------------
    (
        "M2a the inflation axis band hardcoded to zero (the spec's bare comparison)",
        SRC,
        _INFLATION_AXIS,
        "    if trend > 0.0:\n"
        '        return "rising"\n'
        "    if trend < 0.0:\n"
        '        return "falling"\n'
        '    return "flat"',
    ),
    (
        "M2b the inflation band's edges made exclusive (a boundary flips bucket)",
        SRC,
        _INFLATION_AXIS,
        "    if trend >= neutral_band:\n"
        '        return "rising"\n'
        "    if trend <= -neutral_band:\n"
        '        return "falling"\n'
        '    return "flat"',
    ),
    (
        "M2c the growth bands made inclusive (the boundary value becomes a recession)",
        SRC,
        _GROWTH_AXIS,
        "    if gap <= settings_recession:\n"
        '        return "deep_contraction"\n'
        "    if gap <= settings_weak:\n"
        '        return "contraction"\n'
        '    return "above_trend"',
    ),
    (
        "M2d the growth bands collapsed to one (contraction merges into deep)",
        SRC,
        _GROWTH_AXIS,
        "    if gap < settings_recession:\n"
        '        return "deep_contraction"\n'
        '    return "above_trend"',
    ),
    # --- M3: the hysteresis ----------------------------------------------
    (
        "M3a the momentum band hardcoded to a wide value (at-trend never fires)",
        SRC,
        _AT_TREND_BLOCK,
        "    if abs(gap) <= 1e9:\n"
        '        if inflation == "rising":\n'
        '            return "reflation"\n'
        '        return "mid_expansion"',
    ),
    (
        "M3b the sign split inside the band made inclusive of zero on the wrong side",
        SRC,
        _AT_TREND_BLOCK,
        "    if abs(gap) <= momentum_band:\n"
        '        if inflation == "rising":\n'
        '            return "reflation"\n'
        "        if gap <= 0.0:\n"
        '            return "early_expansion"\n'
        '        return "mid_expansion"',
    ),
    (
        "M3c early_expansion folded into mid_expansion (the catch-all returns)",
        SRC,
        _AT_TREND_BLOCK,
        "    if abs(gap) <= momentum_band:\n"
        '        if inflation == "rising":\n'
        '            return "reflation"\n'
        '        return "mid_expansion"',
    ),
    # --- M4: the corroboration logic --------------------------------------
    (
        "M4a the two slack measures paired with the SAME sign (the D-031 trap)",
        SRC,
        _CORROBORATION,
        "        if self.output_gap == 0.0 or self.unemployment_gap == 0.0:\n"
        "            return False\n"
        "        return (self.output_gap < 0.0) == (self.unemployment_gap < 0.0)",
    ),
    (
        "M4b a zero gap counted as corroboration (product-of-signs behaviour)",
        SRC,
        _ZERO_GUARD,
        "        if False:\n            return False\n",
    ),
    (
        "M4c the corroboration flag hardcoded True",
        SRC,
        _CORROBORATION,
        "        return True",
    ),
    # --- M5: the disclosures ---------------------------------------------
    (
        "M5a the absent-base-rate disclosure dropped",
        SRC,
        _BASE_RATE_ABSENT_WARNING,
        '"Base rate pending."',
    ),
    (
        "M5b the momentum-not-level disclosure dropped",
        SRC,
        _MOMENTUM_DISCLOSURE,
        '"See documentation."',
    ),
    (
        "M5c the flat-momentum disclosure dropped",
        SRC,
        _FLAT_WARNING,
        'f"Momentum reading noted ({inputs.inflation_trend_3m:+.2f}pp)."',
    ),
    (
        "M5d the at-trend disclosure dropped",
        SRC,
        _AT_TREND_WARNING,
        'f"Gap noted ({inputs.output_gap:+.2f}%)."',
    ),
    (
        "M5e the recession caveat dropped",
        SRC,
        _RECESSION_WARNING,
        '"Recession label applied."',
    ),
    (
        "M5f the undecidable-recovery disclosure dropped",
        SRC,
        _RECOVERY_UNDECIDABLE,
        '"Slowdown label applied."',
    ),
    (
        "M5g the slack-disagreement disclosure dropped",
        SRC,
        _DISAGREE_WARNING,
        'f"Slack readings: {inputs.output_gap:+.2f} and {inputs.unemployment_gap:+.2f}."',
    ),
    # --- M6: the published components -------------------------------------
    (
        "M6a the state dropped from the published value",
        SRC,
        _STATE_KEY,
        '            "state": "unknown",',
    ),
    (
        "M6b the two axes dropped (the label stops being auditable)",
        SRC,
        _AXIS_KEYS,
        '            "growth_axis": "unknown",\n            "inflation_axis": "unknown",',
    ),
    (
        "M6c the corroboration flag hardcoded in the published value",
        SRC,
        _CORROB_KEY,
        '            "slack_corroborated": True,',
    ),
    (
        "M6d the state's own base rate dropped",
        SRC,
        _BASE_RATE_KEY,
        '            "state_base_rate": 0.0,',
    ),
    (
        "M6e the inflation-axis base rate dropped from the published value",
        SRC,
        _AXIS_BASE_RATE_KEY,
        '            "rising_inflation_base_rate": None,',
    ),
    (
        "M6f the axis-base-rate warning dropped (the axis artefact goes undisclosed)",
        SRC,
        _AXIS_BASE_RATE_WARNING,
        "        pass",
    ),
    # --- M7: the contract -------------------------------------------------
    (
        "M7a extra='forbid' removed from the input model",
        SRC,
        _EXTRA_FORBID,
        "    output_gap: float = Field(",
    ),
    (
        "M7b unemployment_gap dropped from inputs_used (the inert-input class)",
        SRC,
        _INPUTS_USED,
        "        inputs_used=[\n"
        '            "output_gap",\n'
        '            "inflation_yoy",\n'
        '            "inflation_trend_3m",\n'
        "        ],",
    ),
    # --- M8: confidence ---------------------------------------------------
    (
        "M8a the heuristic factor hardcoded False",
        SRC,
        _HEURISTIC,
        "            is_heuristic_not_calibrated=False,",
    ),
    (
        "M8b the two slack measures claimed as independent sources",
        SRC,
        _INDEPENDENCE,
        "            source_independence_count=1,",
    ),
    (
        "M8c the unobservable dependence dropped",
        SRC,
        _UNOBSERVABLE,
        "            depends_on_unobservable=False,",
    ),
    (
        "M8d confidence hardcoded to the specification's 0.5",
        SRC,
        # Same AMBIGUITY as the two above: `confidence=confidence,` is also in
        # `check_trilemma_tension`. Anchored through the regime-specific key.
        #
        # The key and the `confidence=` call are NO LONGER ADJACENT: a comment
        # block documenting the §21 two-axis disclosure was inserted between
        # them, and the old two-line anchor matched 0 occurrences. A sweep whose
        # target is ABSENT cannot see its own mutants (O-95), so this anchor is
        # pinned to the outer `}` and the `confidence=` line only — the lines
        # between them are prose and carry no mutation surface.
        (
            '            "rising_inflation_base_rate": axis_base_rate,\n'
            "            # Section 21: whether BOTH axes decided the label. A "
            "consumer that\n"
            "            # treats the state as a two-axis classification reads "
            "this first.\n"
            '            "regime_tension": tension,\n'
            '            "regime_tension_reasons": tension_reasons,\n'
            "        },\n"
            "        confidence=confidence,"
        ),
        (
            '            "rising_inflation_base_rate": axis_base_rate,\n'
            "            # Section 21: whether BOTH axes decided the label. A "
            "consumer that\n"
            "            # treats the state as a two-axis classification reads "
            "this first.\n"
            '            "regime_tension": tension,\n'
            '            "regime_tension_reasons": tension_reasons,\n'
            "        },\n"
            "        confidence=0.5,"
        ),
    ),
    # --- config accessors -------------------------------------------------
    (
        "C1a the recession threshold hardcoded in its property",
        CONFIG,
        _RECESSION_PROP,
        "        return -1.5",
    ),
    (
        "C1b the weak-growth threshold hardcoded in its property",
        CONFIG,
        _WEAK_PROP,
        "        return -0.5",
    ),
    (
        "C1c the neutral band hardcoded in its property",
        CONFIG,
        _NEUTRAL_BAND_PROP,
        "        return 0.0",
    ),
    (
        "C1d the momentum band hardcoded in its property",
        CONFIG,
        _MOMENTUM_BAND_PROP,
        "        return 0.0",
    ),
    (
        "C1e the regime rate mapping entry hardcoded instead of read from config",
        CONFIG,
        _REGIME_RATE_ENTRY,
        '            "slowdown": 0.5,',
    ),
    (
        "C1f the axis base rate hardcoded in its property",
        CONFIG,
        _AXIS_BASE_RATE_PROP,
        "        return 0.9375",
    ),
    # --- M7: the growth-axis vocabulary ----------------------------------
    # The axis is a published contract. A member nothing can produce is the
    # D-037 dead-branch class at the type level, so the removal of `at_trend`
    # needs a mutation that re-adds it: a test asserting membership must be
    # able to fail.
    (
        "M7a the growth axis re-declares an unreachable `at_trend` member",
        SRC,
        'GrowthAxis = Literal["deep_contraction", "contraction", "above_trend"]',
        'GrowthAxis = Literal["deep_contraction", "contraction", "at_trend", "above_trend"]',
    ),
    # =====================================================================
    # D-105 — `classify_regime_markov_switching` (Section 6.2, Tier 5)
    #
    # The function's four published corrections, each mutated back to the
    # plausible alternative it replaced. MX1..MX4 attack the CANONICAL ORDERING
    # (the mechanism); MX5..MX8 the ORIENTATION and the LOOK-AHEAD; MX9..MX16 the
    # input guards; MX17..MX22 the config accessors; MX23..MX28 the warnings.
    # =====================================================================
    # --- MX1..MX4: the canonical ordering (the increment's mechanism) -----
    (
        "MX1 the ordering returns the library's index unchanged (no sort at all)",
        SRC,
        '    return [int(index) for index in np.argsort(constants, kind="stable")]',
        "    return [int(index) for index in range(constants.size)]",
    ),
    (
        "MX2 the ordering sorts DESCENDING (highest mean first)",
        SRC,
        '    return [int(index) for index in np.argsort(constants, kind="stable")]',
        '    return [int(index) for index in np.argsort(constants, kind="stable")[::-1]]',
    ),
    (
        "MX3 the ordering uses a non-stable sort, losing the tiebreak",
        SRC,
        '    return [int(index) for index in np.argsort(constants, kind="stable")]',
        '    return [int(index) for index in np.argsort(constants, kind="quicksort")]',
    ),
    (
        "MX4 the smoothed path is not re-indexed into the canonical order",
        SRC,
        "        means=constants[order],\n        smoothed=smoothed[:, order],",
        "        means=constants[order],\n        smoothed=smoothed,",
    ),
    # --- MX5..MX8: the orientation and the look-ahead ---------------------
    (
        "MX5 the transition matrix is published in the LIBRARY's column-stochastic orientation",
        SRC,
        "    rows = raw_transition.T",
        "    rows = raw_transition",
    ),
    (
        "MX6 the transition matrix is not re-indexed into the canonical order",
        SRC,
        "        transition=transition[np.ix_(order, order)],",
        "        transition=transition,",
    ),
    (
        "MX7 the expected durations are not re-indexed into the canonical order",
        SRC,
        "        durations=durations[order],",
        "        durations=durations,",
    ),
    (
        "MX8 the smoothed/filtered look-ahead gap is published as zero",
        SRC,
        "    max_gap = float(np.max(np.abs(smoothed - filtered)))",
        "    max_gap = 0.0",
    ),
    # MX8b (`current = filtered[-1]` -> `smoothed[-1]`) was written, run, and
    # REMOVED. It SURVIVED, and correctly: MEASURED 2026-09-24, the smoothed and
    # filtered paths are EXACTLY equal at the final observation (they must be —
    # there is no future to smooth over), so the two forms are the same program
    # on the whole domain. That is D-059's **construction** class: INERT IN THE
    # STRONGEST SENSE, and no test can kill it because none should. This sweep
    # has no `_EXPECTED_INERT` table (that lives in `mutation_econometrics.py`),
    # and an entry whose verdict is permanently "survived" is exactly the noise
    # that teaches a reader to ignore survivors — so the honest home for the
    # observation is the record, not the catalogue. It is recorded in
    # `docs/DECISIONS.md` (D-105) and pinned by
    # `test_markov_current_read_is_the_filtered_endpoint_and_equals_the_smoothed_one`,
    # which asserts the equality the inertness depends on — so a change in the
    # library's smoothing that separated the two paths would be LOUD rather than
    # silently making this decision load-bearing.
    # --- MX9..MX16: the input guards --------------------------------------
    (
        "MX9 the pandas-Series type guard is disabled",
        SRC,
        "    if not isinstance(series, pd.Series):",
        "    if False:",
    ),
    (
        "MX10 the non-finite guard is disabled",
        SRC,
        "    if non_finite:",
        "    if False:",
    ),
    (
        "MX11 the no-variation guard is disabled",
        SRC,
        "    if _relative_span(values) <= _NO_VARIATION_RELATIVE_SPAN:",
        "    if False:",
    ),
    (
        "MX12 the no-variation guard is made ABSOLUTE (the O-121 / D-100 defect)",
        SRC,
        "    scale = float(np.max(np.abs(values)))\n    if scale == 0.0:\n        return 0.0\n    return float((np.max(values) - np.min(values)) / scale)",
        "    return float(np.max(values) - np.min(values))",
    ),
    (
        "MX13 the length floor is a hardcoded row count instead of the derived product",
        SRC,
        "    required = ceil(settings.min_observations_per_parameter * n_parameters)",
        "    required = 60",
    ),
    (
        "MX14 the k_regimes floor is relaxed to 1",
        SRC,
        "    if k_regimes < 2:",
        "    if k_regimes < 1:",
    ),
    (
        "MX15 the bool rejection is dropped (isinstance(True, int) is True)",
        SRC,
        "    if isinstance(k_regimes, bool) or not isinstance(k_regimes, int):",
        "    if not isinstance(k_regimes, int):",
    ),
    (
        "MX16 the library's raw LinAlgError is allowed to escape as a numpy exception",
        SRC,
        "    except np.linalg.LinAlgError as exc:",
        "    except ZeroDivisionError as exc:",
    ),
    # --- MX17..MX22: the config accessors ---------------------------------
    (
        "MX17 parameters_for drops the switching-variance term",
        CONFIG,
        "        variances = k_regimes if self.switching_variance else 1",
        "        variances = 1",
    ),
    (
        "MX18 the max_regimes accessor returns its shipped literal",
        CONFIG,
        '        """Ceiling on the caller\'s ``k_regimes``. See the YAML note."""\n        return int(self.max_regimes_value.value)',
        '        """Ceiling on the caller\'s ``k_regimes``. See the YAML note."""\n        return 6',
    ),
    (
        "MX19 the modal-share threshold accessor returns its shipped literal",
        CONFIG,
        '        """Share of periods above which the modal regime is called a base state."""\n        return float(self.modal_share_warning_threshold_value.value)',
        '        """Share of periods above which the modal regime is called a base state."""\n        return 0.9',
    ),
    (
        "MX20 the per-parameter floor accessor returns its shipped literal",
        CONFIG,
        '        """Observations required per estimated parameter, before the fit is attempted."""\n        return float(self.min_observations_per_parameter_value.value)',
        '        """Observations required per estimated parameter, before the fit is attempted."""\n        return 5.0',
    ),
    (
        "MX21 the max_iterations accessor returns its shipped literal",
        CONFIG,
        '        """``maxiter`` for the MLE step."""\n        return int(self.max_iterations_value.value)',
        '        """``maxiter`` for the MLE step."""\n        return 200',
    ),
    (
        "MX22 the k_regimes ceiling is removed entirely",
        SRC,
        "    if k_regimes > settings.max_regimes:",
        "    if False:",
    ),
    # --- MX23..MX28: the published evidence and the warnings --------------
    (
        "MX23 the library-warning count is published as zero",
        SRC,
        '            "library_warning_count": warning_count,',
        '            "library_warning_count": 0,',
    ),
    (
        "MX24 the base-state warning branch is disabled",
        SRC,
        "    if modal_share >= settings.modal_share_warning_threshold:",
        "    if False:",
    ),
    (
        "MX25 the library-warning branch is disabled",
        SRC,
        "    if warning_count:",
        "    if False:",
    ),
    (
        "MX26 the non-convergence branch is disabled",
        SRC,
        "    if not converged:",
        "    if False:",
    ),
    (
        "MX27 the published permutation is the identity",
        SRC,
        '            "regime_order_raw_index": order,',
        '            "regime_order_raw_index": list(range(k_regimes)),',
    ),
    (
        "MX28 the published raw-index means are the canonical ones",
        SRC,
        '            "regime_means_raw_index": [float(m) for m in constants],',
        '            "regime_means_raw_index": [float(m) for m in canonical_constants],',
    ),
    (
        "MX29 the regime counts are published from the library's index order",
        SRC,
        "    counts = [int(np.count_nonzero(period_labels == index)) for index in range(k_regimes)]",
        "    counts = [int(period_labels.size)] + [0] * (k_regimes - 1)",
    ),
    (
        "MX30 the base rate is measured on the FILTERED path instead of the smoothed one",
        SRC,
        "    period_labels = np.argmax(smoothed, axis=1)",
        "    period_labels = np.argmax(filtered, axis=1)",
    ),
]


def run_tests() -> bool:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_regime.py",
            "tests/test_infrastructure.py",
            "-q",
            "--no-header",
            # `-x` is MANDATORY here, and it is D-057's rule rather than a
            # preference: the selection takes ~28 s, so 72 mutations without it
            # is ~34 minutes of foreground — which is exactly the run that gets
            # interrupted, and on win32 an interrupted sweep leaves every mutant
            # applied so far on disk (D-082). A kill is a kill: the first failing
            # test is sufficient evidence, and `returncode != 0` is the verdict
            # either way. MEASURED at D-105: adding it did not change a single
            # mutation's outcome.
            "-x",
            "-m",
            "not live",
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _applied_mutations(originals: dict[Path, str]) -> list[tuple[str, Path, str, str]]:
    """Find mutations currently in the tree: ``old`` absent AND ``new`` present."""
    found: list[tuple[str, Path, str, str]] = []
    for name, target, old, new in _MUTATIONS:
        text = originals[target]
        if old not in text and new in text:
            found.append((name, target, old, new))
    return found


def repair_leftover_mutations(originals: dict[Path, str]) -> list[str]:
    """Invert any mutation left applied by an interrupted run."""
    repaired: list[str] = []
    for name, target, old, new in _applied_mutations(originals):
        originals[target] = originals[target].replace(new, old, 1)
        target.write_text(originals[target], encoding="utf-8", newline="")
        repaired.append(name)
    return repaired


def _check_targets_only() -> int:
    """Print the anchor verdict and STOP, touching nothing (O-138)."""
    return check_only(_MUTATIONS)


def main() -> int:
    # O-138: the check-only mode must be answered BEFORE the lifecycle
    # writes, and before ANY file is read -- see check_only's docstring.
    if check_only_requested():
        return _check_targets_only()
    # FIRST: a kill from here on must leave a log behind. This sweep does
    # not use `sweep_lifecycle`, so it does not inherit that helper's
    # buffering -- O-124, closed by calling it explicitly.
    line_buffer_stdout()
    # A truncated pipe (``| head``, ``| grep``) closes stdout and kills this
    # process - measured three times in one session, the last of them in THIS
    # file. Two defences, because the first does not work on Windows:
    #
    #   * install_signal_restore() is the POSIX convenience, and on win32 it
    #     cannot fire at all (see its docstring).
    #   * record_pristine() writes the pristine text to a sidecar BEFORE the
    #     first mutation, so a run killed with no chance to unwind is still
    #     restorable by the next run, by sweep_health, or by hand.
    install_signal_restore()

    originals: dict[Path, str] = {p: p.read_text(encoding="utf-8") for p in {SRC, CONFIG}}

    # Heal a previous kill BEFORE reading anything, so the sweep always starts
    # from real source rather than from a mutant wearing its costume (D-081).
    for path in restore_from_sidecar(sorted(originals)):
        print(f"RESTORED {path.name} from sidecar (previous run was killed)")
        originals[path] = path.read_text(encoding="utf-8")
        print()

    record_pristine(originals)

    repaired = repair_leftover_mutations(originals)
    if repaired:
        print("REPAIRED left over from an interrupted run:")
        for name in repaired:
            print(f"  reverted -> {name}")
        print()

    # Refuse to measure before anything is mutated (D-048, O-29). An anchor that
    # drifted reports as a survivor, which reads as "the suite has a hole" when
    # the truth is "the sweep aimed at the wrong text". A LEFTOVER mutant is
    # reported as such rather than as a drifted anchor (D-081), because those two
    # need opposite responses.
    #
    # This gate belongs IN the sweep, not only in `tools/sweep_health.py`. The
    # comment block above `_INDEPENDENCE`/`_UNOBSERVABLE` records that those two
    # anchors were ambiguous and "worked by luck" until an EXTERNAL tool noticed
    # — and a gate that lives only in that tool does not protect anyone who runs
    # this sweep directly, which is the normal case.
    problems = check_targets(originals, _MUTATIONS)
    print(f"check_targets: {len(_MUTATIONS)} mutations, {len(problems)} problem(s)")
    if problems:
        print(format_problems(problems))
        print()
        print("REFUSING TO RUN: fix the anchors above first. A sweep that cannot")
        print("prove it mutates the site it names certifies nothing.")
        return 4

    survivors: list[tuple[str, str]] = []
    try:
        for name, target, old, new in _MUTATIONS:
            pristine = originals[target]
            if old not in pristine:
                print(f"PATTERN MISSING   {name}  [{target.name}]")
                survivors.append((name, "pattern-not-found"))
                continue
            target.write_text(pristine.replace(old, new, 1), encoding="utf-8", newline="")
            _set_in_flight(target, pristine)
            caught = not run_tests()
            target.write_text(pristine, encoding="utf-8", newline="")
            _clear_in_flight()
            print(f"{'KILLED' if caught else 'SURVIVED':17} {name}")
            if not caught:
                survivors.append((name, "survived"))
    finally:
        for path, text in originals.items():
            path.write_text(text, encoding="utf-8", newline="")
            # The tree is clean again, so the recovery sidecar is spent. Leaving
            # it behind would make the NEXT run "restore" a file that never
            # needed it, silently reverting a legitimate edit made in between.
            sidecar_for(path).unlink(missing_ok=True)

    leftover = _applied_mutations({p: p.read_text(encoding="utf-8") for p in {SRC, CONFIG}})
    if leftover:
        print()
        print("ERROR: a mutation is still applied after the sweep:")
        for name, _, _, _ in leftover:
            print(f"  STILL APPLIED -> {name}")
        return 2

    print()
    total = len(_MUTATIONS)
    print(f"{total - len(survivors)}/{total} killed")
    for name, why in survivors:
        print(f"  SURVIVOR ({why}): {name}")
    # O-72's canary gate. A canary that SURVIVES means the sweep ran but tested
    # nothing: its selection no longer reaches the mutated module, so every
    # "killed" above is a statement about the harness rather than the suite.
    # This is the D-051 trap, and it is why CANARY1 is REQUIRED to be killed
    # rather than tolerated as a survivor.
    if any(name.startswith("CANARY1 ") for name, _ in survivors):
        print()
        print("REFUSING TO CERTIFY: the honesty canary SURVIVED.")
        print("  !! CANARY1 -- the test selection no longer reaches the mutated")
        print("     module, so no kill above is evidence about the suite (O-72).")
        return 3

    return 0 if not survivors else 1


if __name__ == "__main__":
    raise SystemExit(main())
