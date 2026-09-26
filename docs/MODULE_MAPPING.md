# Module Mapping

**Specification section → module → function → test.**

Generated from the **code and the test suite**, not transcribed from `AGENTS.md`.
That distinction is deliberate and is the reason this file is worth having: the
specification has been corrected repeatedly (D-001 … D-046), so a mapping copied
from its text would describe a system that no longer exists. Every row below was
produced by reading `src/macro_engine/**` with `ast`, resolving each function's
test file from the test suite's actual `import` statements, and cross-checking
the tier assignment against `docs/PROGRESS.md`.

**Scope reminder (Section 22.3):** Phases 0–4 are **US-only**.
`country="us"` is a label on a system that currently works for one value of it,
not a generalization. Nothing in this table is country-generic.

---

## How to read this table

| Column | Meaning |
|---|---|
| **Spec** | The specification section that names the function. Blank means the function was added by an amendment (§22.x), a backfill, or a correction; the *decision record* column then carries the authority. |
| **Module** | `AGENTS.md`'s module number (Section 20). |
| **Function** | The public name, as it appears in the module's `__all__` or as a module-level `def`. |
| **Source** | `file` — the one place it is defined. There are no re-exports or shadow copies. |
| **Test** | The test file that **imports** it. Resolved from the import graph, so a function whose test file does not import it shows as `—` and is a genuine gap, not a guess. |
| **Tier** | `§21.3` dependency tier. 1 = no dependencies, 2 = depends on Tier 1, 3 = synthesis, 4 = construction. |
| **Decision** | The record that governs it, where the implementation differs from the specification's literal text. |

The **§20 functions** in `models/` are all listed — 66 public `def`s, of which
the two evidence functions are §15.19-D's. Private helpers
(`_thresholds_calibrated`, `_gdp_gdi_settings`, …) are **not** listed: they are
implementation detail, they are covered by their caller's tests, and their names
are not a contract.

---

## Tier 1 — 23 functions, no dependencies

Pure computation or single-series arithmetic. Each takes numbers in and returns
a number or a small structure, so a unit test is sufficient to prove it.

| Spec | Module | Function | Source | Test | Decision |
|---|---|---|---|---|---|
| 11.1 | Bond math | `price_bond` | `models/bond_math.py` | `test_bond_math.py` | — |
| 11.1 | Bond math | `macaulay_duration` | `models/bond_math.py` | `test_bond_math.py` | — |
| 11.1 | Bond math | `modified_duration` | `models/bond_math.py` | `test_bond_math.py` | — |
| 11.1 | Bond math | `convexity` | `models/bond_math.py` | `test_bond_math.py` | — |
| 11.1 | Bond math | `price_change_with_convexity` | `models/bond_math.py` | `test_bond_math.py` | — |
| 20.2 | Bond math | `repo_stress_check` | `models/bond_math.py` | `test_bond_math.py` | **D-031** |
| 6.5 | National accounts | `output_gap` | `models/gdp_nowcast.py` | `test_output_gap.py` | **D-009**, **O-7** |
| 20.3 | National accounts | `gdp_deflator` | `models/national_accounts.py` | `test_national_accounts.py` | — |
| 20.3 | National accounts | `savings_investment_identity` | `models/national_accounts.py` | `test_national_accounts.py` | — |
| 20.2 | National accounts | `quantity_theory_implied_inflation` | `models/national_accounts.py` | `test_national_accounts.py` | — |
| 20.5 | Index numbers | `laspeyres_index` | `models/national_accounts.py` | `test_national_accounts.py` | — |
| 20.5 | Index numbers | `paasche_index` | `models/national_accounts.py` | `test_national_accounts.py` | — |
| 20.5 | Index numbers | `fisher_index` | `models/national_accounts.py` | `test_national_accounts.py` | — |
| 20.6 | Labor | `openings_to_unemployed_ratio` | `models/national_accounts.py` | `test_national_accounts.py` | — |
| 6.6 | Yield curve | `curve_slope` | `models/yield_curve.py` | `test_yield_curve.py` | — |
| 6.6 | Yield curve | `breakeven_inflation` | `models/yield_curve.py` | `test_yield_curve.py` | — |
| 6.6 | Yield curve | `decompose_yield` | `models/yield_curve.py` | `test_yield_curve.py` | **D-033** |
| 6.10 | Risk | `realized_vol_simple` | `models/risk.py` | `test_risk.py` | — |
| 17 | Risk | `historical_var` | `models/risk.py` | `test_risk.py` | — |
| 17 | Risk | `expected_shortfall` | `models/risk.py` | `test_risk.py` | — |
| 17 | Risk | `parametric_var` | `models/risk.py` | `test_risk.py` | — |
| 15.20 | Risk | `portfolio_volatility_two_asset` | `models/risk.py` | `test_risk.py` | — |
| 15.20 | Risk | `portfolio_volatility_n_asset` | `models/risk.py` | `test_risk.py` | **D-028** |

`z_score_for_confidence` (`models/risk.py`, `test_risk.py`) sits in Tier 1's file
but is a helper for the confidence rule rather than a §20 function — it is
listed here for completeness because it is public.

---

## Tier 2 — 29 functions, depend on Tier 1

| Spec | Module | Function | Source | Test | Decision |
|---|---|---|---|---|---|
| 6.1 | Policy rules | `taylor_rule` | `models/policy_rules.py` | `test_policy_rules.py` | — |
| 6.1 | Policy rules | `balanced_approach_rule` | `models/policy_rules.py` | `test_policy_rules.py` | — |
| 6.1 | Policy rules | `first_difference_rule` | `models/policy_rules.py` | `test_policy_rules.py` | — |
| 6.1 | Policy rules | `policy_rule_ensemble` | `models/policy_rules.py` | `test_policy_rules.py` | — |
| 22.4 | Policy rules | `canonical_policy_gap` | `models/policy_rules.py` | `test_policy_rules.py` | — |
| 20.4 | Policy rules | `qe_qt_stance` | `models/policy_rules.py` | `test_policy_rules.py` | **D-040** |
| 3.3 | Inflation | `phillips_curve_inflation` | `models/inflation_dynamics.py` | `test_inflation_dynamics.py` | **D-026** |
| 5.1 | Inflation | `project_shelter_cpi` | `models/inflation_nowcast.py` | `test_inflation_nowcast.py` | **D-028** |
| 5.4 | Inflation | `ppi_pipeline_signal` | `models/ppi_pipeline.py` | `test_ppi_pipeline.py` | **D-029** |
| 3.5 | Production | `potential_gdp_cobb_douglas` | `models/production_function.py` | `test_production_function.py` | **D-027** |
| 7.2 | Production | `growth_accounting_decomposition` | `models/production_function.py` | `test_production_function.py` | **D-027** |
| 6.3 | Labor | `inflation_breadth_score` | `models/labor_synthesis.py` | `test_labor_synthesis.py` | **D-022/24** |
| 6.4 | Labor | `labor_tightness_score` | `models/labor_synthesis.py` | `test_labor_synthesis.py` | — |
| 20.6 | Labor | `claims_trend_signal` | `models/labor_synthesis.py` | `test_labor_synthesis.py` | — |
| 20.6 | Labor | `claims_corroboration` | `models/labor_synthesis.py` | `test_labor_synthesis.py` | **D-027** |
| 20.6 | Labor | `two_survey_divergence` | `models/labor_synthesis.py` | `test_labor_two_survey.py` | — |
| 20.6 | Labor | `nfp_revision_adjusted_read` | `models/labor_synthesis.py` | `test_labor_two_survey.py` | — |
| 20.6 | Labor | `ahe_composition_flag` | `models/labor_synthesis.py` | `test_labor_two_survey.py` | — |
| 20.6 | Labor | `beveridge_curve_position` | `models/labor_synthesis.py` | `test_labor_two_survey.py` | — |
| 20.6 | Labor | `beveridge_shift_tolerance` | `models/labor_synthesis.py` | `test_labor_two_survey.py` | — |
| 20.7 | GDP | `gdp_gdi_divergence` | `models/gdp_nowcast.py` | `test_gdp_gdi_divergence.py` | **D-031** |
| 20.7 | GDP | `leading_indicator_proxy` | `models/lei_proxy.py` | `test_lei_proxy.py` | **D-032** |
| 6.5 | GDP | `simple_gdp_nowcast` | `models/gdp_nowcast.py` | `test_gdp_nowcast.py` | **D-034**, **D-035** |
| 20.8 | Auctions | `auction_demand_signal` | `models/auctions.py` | `test_auctions.py` | **D-036**, **O-15** |
| 20.8 | Credit | `credit_spread_attribution` | `models/credit_spread.py` | `test_credit_spread.py` | **D-037** |
| 22.7 | Financial conditions | `compute_fci` | `models/financial_conditions.py` | `test_financial_conditions.py` | **D-038** |
| 20.3 | National accounts | `policy_mix_classifier` | `models/national_accounts.py` | `test_national_accounts.py` | **D-039** |
| 20.3 | National accounts | `minsky_composition_drift` | `models/national_accounts.py` | `test_national_accounts.py` | **D-041**, **D-043** |
| 20.11 | Probability | `bayesian_update` | `models/probability.py` | `test_probability.py` | **D-042** |
| 20.11 | Probability | `expected_value` | `models/probability.py` | `test_probability.py` | **D-042** |
| 17.1 | Risk | `marginal_risk_contributions` | `models/risk.py` | `test_risk.py` | **D-042** |

`output_gap_from_snapshot` (`models/gdp_nowcast.py`) is the snapshot-taking form
of `output_gap` — tested by `test_output_gap.py` and `test_phase1_data_layer.py`.
It is the function Tier 3/4 code should call, because it applies the section 21.0
`as_of` discipline the bare `output_gap` leaves to its caller.

---

## Tier 3 — synthesis (15 / 15 ✅ COMPLETE)

These compose Tier 1/2 outputs, so their reviews are about **interaction** —
date, window, span, parameter, cadence, base rate, unit, estimand, and
estimand-horizon — rather than arithmetic. A Tier 3 defect is a number that is
arithmetically correct and measures the wrong thing.

| Spec | Module | Function | Source | Test | Decision |
|---|---|---|---|---|---|
| 22.5 | Policy rules | `derive_market_implied_policy_path` | `models/policy_rules.py` | `test_policy_rules.py` | — |
| 6.2 | Regime | `classify_regime_rule_based` | `models/regime.py` | `test_regime.py` | **D-045**, **D-045a** |
| 15.20-A | Module 1 | `check_trilemma_tension` | `models/regime.py` | `test_trilemma.py` | **D-048** |
| 5.3 | Inflation | `inflation_convergence_classifier` | `models/inflation_convergence.py` | `test_inflation_convergence.py` | **D-047** |
| 15.19-D | Evidence | `tag_evidence_source` | `models/evidence.py` | `test_evidence.py` | **D-046** |
| 15.19-D | Evidence | `count_independent_families` | `models/evidence.py` | `test_evidence.py` | **D-046** |
| 15.20-B | Module 8 | `inversion_probability_adjustment` | `models/yield_curve.py` | `test_yield_curve.py` | **D-049** |
| 20.11 | Module 12.2 | `four_pillar_scorecard` | `models/scorecard.py` | `test_scorecard.py` | **D-050**, corrected **D-051** |
| 22.10 | Module 12 | `classify_convergence` | `models/convergence.py` | `test_convergence.py` | **D-051** |
| 20.5 | Module 5.6 | `cross_asset_transmission` | `models/inflation_dynamics.py` | `test_transmission.py` | **D-052** |
| 16.2 | Module 3.6 | `project_inflation_trajectory` | `models/inflation_trajectory.py` | `test_inflation_trajectory.py` | **D-053** |
| 6.6c | Module 17.3 | `evaluate_drawdown_rules` | `portfolio/risk_budget.py` | `test_risk_budget.py` | **D-054** |
| 20.13 | Module 17.3 | `check_rebalancing_drift` | `portfolio/risk_budget.py` | `test_rebalancing_drift.py` | **D-055** |
| 20.13 | Module 17.2 | `volatility_target_scaling` | `portfolio/risk_budget.py` | `test_volatility_target.py` | **D-056** |
| 20.14 / 22.6 | Module 17.3 | `generalized_kelly_fraction` | `portfolio/risk_budget.py` | `test_fractional_kelly.py` | **D-057** |
| 20.14 / 22.6 | Module 17.3 | `apply_fractional_kelly` | `portfolio/risk_budget.py` | `test_fractional_kelly.py` | **D-057** |

### Module 13's vocabulary is shared, and it is declared once

`EvidenceSourceFamily` (31 members) is defined **only** in
`models/evidence_family.py`. It was previously declared in
`thesis_layer/schemas.py`, where it was an **orphan** — no constructor, no
importing test — and where no model-layer convergence classifier could reach it
downward, since `models/` is the lower layer and does not import from
`thesis_layer/`.

`thesis_layer/schemas.py` now **re-exports** it, so `ConfirmationSignal.source_family`
and every existing import resolve unchanged. The re-export is a second import
path, **not** a second definition; `test_the_enum_is_reachable_from_both_layers_as_one_object`
asserts the two paths yield the **same object**, because a forked copy would
satisfy an `==` check and still be the defect.

A family is a **shared upstream production process**, not a topic and not a
publisher: two series share a family when one failure — a survey redesign, a
rebenchmarking, a collection outage, a methodology revision — would corrupt both
at once. That is why `BLS_CPI` and `BLS_PPI` are **separate** while headline and
core CPI are the **same** member.

### `inversion_probability_adjustment` — a probability with a measured denominator

Implemented 2026-09-17 (**D-049**). §15.20-B supplies a base rate of **`0.15`**;
the measured 12-month-forward recession rate conditional on inversion is
**`0.489`** over **592** monthly observations of a positive-`DGS10 − DGS2`
history (1976-06 … 2026-09). The literal was **not** shipped. `0.15` is not a
rounded 0.489 and it is not a prior — the specification also hardcodes the two
confidences (`0.3` / `0.35`) that §22.8 reserves for `compute_confidence()`. The
base rate is now a **required input with no default**, so a caller cannot
silently inherit a number that disagrees with the data by **3.1×**.

The published `value` carries `inverted_base_rate` and `not_inverted_base_rate`
**beside** `adjusted_probability`, per the D-029 rule: a probability travels with
its measured base rate or it is a number without a denominator.

### `four_pillar_scorecard` — a blocking verdict that missed 32 of 50 splits

Implemented 2026-09-17 (**D-050**). The scorecard reduces four directional pillar
reads to one `ConvergenceVerdict`, and **five specification defects** were
corrected — four found before implementation, one found **by the mutation sweep**.

**The headline one is the opposition gate.** §20.11's own logic classified a read
as `CONFLICTED` only when the *net* score was zero, so a `+1, +1, −1, −1` read —
genuinely opposed — was not conflicted, and neither was `+1, +1, +1, −1`. The
shipped gate tests whether **both directions are present at all**
(`up > 0 and down > 0`), which is the property the verdict name claims. The
specification form missed **32 of 50** opposed pillar configurations; the shipped
form misses none, pinned by `test_the_specification_form_misses_opposed_reads`.

**The compositional defect is the one the sweep found, and it is D-047's
"declared, unreachable" class inside the repair itself.** Because `CONFLICTED` is
tested **first** and consumes every opposed read, a read that reaches the dissent
gates has all non-neutral pillars pointing the same way — so `max(up, down) == n`
and therefore **`dissent = n − max(up, down) == 0` always**. The three dissent
ceilings (`<= 0`, `<= 1`, `<= 2` from config) are therefore **the same predicate
in practice**, the MEDIUM dissent ceiling **cannot bind**, and the `LOW` "weak
agreement" branch is **unreachable by construction**.

Measured by enumerating all **80** non-neutral pillar combinations against three
family sets: past the `CONFLICTED` gate the reachable dissent values are exactly
**`{0}`**. `MEDIUM` is reachable — but only through the **family floor** (3
directional pillars over 2 independent families), never through the dissent
ceiling.

**The gates were kept, with tripwire tests, rather than deleted.** Deleting them
would silently freeze the current gate *order* as permanent: a future reordering
that made dissent non-zero would find the branches gone rather than untested.
`test_the_medium_band_is_reachable_through_the_family_floor`,
`test_no_read_reaches_the_dissent_gates_with_a_dissenter` and
`test_the_weak_agreement_low_branch_is_unreachable_by_construction` pin the
structure and fail if it changes.

**Two shares that disagree, and the disagreement is informative.** `CONFLICTED`
is **61.7%** of the *admissible input space* (350 of 567 configurations) but
**66.2%** of **761 real monthly readings** (1963-01 … 2026-09). The historical
share is **higher** than the space share because real pillars are **correlated** —
a random draw over the input space over-represents mixed-direction configurations
that the economy rarely produces. `1963-01` … `1965-01` and `1973-11` … `1975-03`
are contiguous `CONFLICTED` runs. `HIGH` is 33.0% of history and `NO_SIGNAL`
0.8%.

**The all-neutral live finding.** Real history produces **6** readings where every
pillar is neutral — `1963-05, 1964-08, 2013-10, 2014-07, 2015-11, 2017-10` — which
only reach `NO_SIGNAL` because `allow_all_neutral=True` is passed explicitly. The
default is `False`, so the ordinary path refuses them. Whether that opt-in should
be a documented contract or a dedicated entry point is **O-32**.

**§15.19-D's obligation is discharged here, and it changes the answer.** Four
unanimous pillars all tagged `BLS_CPI` are **one vote**, not four: the function
tags its inputs, calls `count_independent_families()`, and passes
`distinct_families` — never the pillar count — to `compute_confidence()`. The
published `value` carries `independent_families` and `family_names` **beside**
`agreement_fraction` and `pillar_directions`. Measured: 4 families → confidence
**0.700**, 2 → **0.600**, 1 → **0.500**.

### The duration cap sits at the turning point of the curve it depends on

The function's adjustment is `max_adjustment × depth_factor × duration_factor`,
and both factors saturate at a configured cap (`100bp`, `26wk`). The live check
measured the conditional rate in buckets and found the two dimensions are **not
the same shape** over 592 observations:

```
depth is MONOTONE      -0..-25bp 0.412   -25..-50bp 0.417
                       -50..-100bp 0.552  -100bp+   0.857
duration is HUMP-SHAPED  0-4wk 0.250   4-13wk 0.286   13-26wk 0.412
                         26-52wk 0.769  >=52wk  0.520
```

**Depth is monotone; duration is not — it peaks in the 26-52 week bucket and
falls beyond it.** The configured 26-week cap therefore sits **exactly at the
peak**, so the mechanism never enters the region where its own monotonicity
assumption is contradicted. The fall is not obviously censoring: the `>=52wk`
bucket is dominated by the **2022-07 … 2024-09** inversion (**113 weeks**), which
has not yet been followed by a recession, and the check therefore runs a
**censoring control** excluding any bucket whose window is truncated. The hump
survives it. Recorded as an open calibration item in **OPEN_ISSUES**, not
silently absorbed by the cap.

### The forward window is `t+1 .. t+12`, and getting it wrong is nearly invisible

Every base rate above is conditional on a recession within the **next** twelve
months, **excluding the current month `t`**. Including `t` counts a recession
already underway as a forecast and moves the unconditional rate `0.2095 →
0.2196` and the not-inverted rate `0.1566 → 0.1687` — while the **inverted** rate,
the only one the function consumes, is **unchanged at `0.4894`**. Validating only
the number the function uses would have passed with the wrong window in the
checker. A month is counted as observed only if the data extends a full twelve
months past it; the trailing twelve are excluded as a contiguous tail.

### `classify_regime_rule_based` — what it is and what is wrong upstream of it

Implemented 2026-09-17. The specification's own sample logic reaches **6 of its
9 declared states**; `slowdown`, `recovery` and `reflation` are unreachable, and
the whole `trend < 0, -1.5 <= gap < -0.5` region — the textbook slowdown zone —
is labelled `early_expansion` by a catch-all `else`. Two of its four declared
inputs (`inflation_yoy`, `unemployment_gap`) were never read. All three defects
are corrected in the shipped function and pinned by
`test_specification_form_cannot_reach_three_of_its_nine_states`.

**The live check found a fourth, later, and it is not in this function.** Over
240 real quarters (1966-07 … 2026-04) the inflation axis reads `rising` in
**225 of 240 quarters (93.75%)**, because it is defined on the sign of a
**3-month annualized** change — a month-over-month measure — and the price level
falls in only a small minority of months. The consequence is that `disinflation`
fires twice and `early_expansion` never fires in sixty years, not because those
states are rare economically but because the axis is a near-constant.

That is a defect in the **input definition**, which is the specification's, not
in the grid. It is disclosed on every output with its measured share, recorded in
`config/settings.yaml` as `regime.measured_rising_inflation_rate`, and tracked as
**O-23**. Changing which input defines the axis is a redefinition of §6.2's own
declared input and was left for an explicit decision.

### `inflation_convergence_classifier` — the first §15.19-D consumer

Implemented 2026-09-17 (**D-047**). It is the **first function obligated by
§15.19-D**, and it discharges the obligation: each direction is tagged with its
evidence family, `count_independent_families()` is called on the tagged set, and
the **family count — not the number of inputs — goes to `compute_confidence()`**.
The published verdict carries `independent_families` and `family_names`
**alongside** `measures_used`, so the divergence between the two numbers is
visible rather than implied.

Three specification defects were corrected, each measured on **522 real months**:
the conflict gate read only `headline` and `core` (**6 months, 1.15%**,
misclassified — `2008-12` and `2020-03/04/05` among them), `HIGH` is the **base
state at 89.5%** rather than a finding, and the thresholds are **degenerate below
`n = 5`** (at `n = 3`, `>= 0.8` is unanimity and `MEDIUM` is unreachable).

**Two of the three §21.1-"blocked" dispersion measures were live** — the **O-21
defect class for the third time** — so the function runs at **six measures, not
three**. `supercore_direction` remains blocked.

**The input space caps `independent_families ∈ {2, 3}`.** `core_pce_direction` is
required, so the floor is 3 measures spanning `BLS_CPI` + `BEA_PCE`. §15.19-D's
single-family warning and the configured confidence ceiling are therefore both
**unreachable through the API** — pinned by tests as unreachable rather than left
as untested branches.

### `check_rebalancing_drift` — a drift check that cannot see an instrument it was not told about

Implemented 2026-09-18 (**D-055**). The **second** function in
`portfolio/risk_budget.py`, with its own test module
(`tests/portfolio/test_rebalancing_drift.py`, 58 tests) because the two functions
answer different questions about the same book.

```text
for target in targets:
    signed = current.get(target.instrument, 0.0) - target.target_risk_contribution_pct
    if abs(signed) > threshold:                       # STRICT
        drifted.append((instrument, signed, "over" if signed > 0 else "under"))
unbudgeted = sorted(set(current) - seen)              # census, not a warning
missing    = [t.instrument for t in targets if t.instrument not in current]
```

**All four specification defects are one shape: an input the function was not
given is treated as a confident zero.** `.get(..., 0.0)` makes an omission a
maximal underweight; iterating `targets` makes a position with no target
invisible, so a book drifted **entirely** into unbudgeted instruments reports
`balanced`. The fix is a **census** (`unbudgeted_instruments`,
`missing_instruments`) rather than a warning string — the §15.19-D discipline,
and the same defect D-050 found in `four_pillar_scorecard`.

**The failure direction is opposite to D-054's**: that ladder failed toward
*silence*, this function fails toward **false confidence**.

**The boundary fixture did not sit on the boundary.** `0.25 + 0.10 - 0.25` is
`0.09999999999999998` — a hair *below* `0.10` — so the "exactly at the threshold"
test could not distinguish `>` from `>=` and the mutant survived. Rebuilt on the
binary-exact pair `0.225 - 0.125 == 0.10`.

**The `Literal` here is the reachability-checked kind.** `RebalancingOutcome`
(`balanced` / `rebalance`) and `DriftDirection` (`over` / `under`) are both
pinned with `typing.get_args()` tests *and* driven to every member — D-045a's two
halves, both covered.

**It carries `_EXPECTED_INERT` entries for the first time in this repository**
(see `scripts/mutation_rebalancing.py`): `M4.6` is **unconditionally** inert and
`CX3` is inert **conditional on the shipped config**. The harness refuses to
certify either without its proof.

Remaining Tier 3 (0). **Tier 3 is COMPLETE at 15 / 15** as of **D-057**
(`apply_fractional_kelly`). The prediction recorded here proved correct on the
first half and wrong on the second: §17.3 **did** contain a wrong implementation
of the function (`raw_kelly = ev / 100`) beside the correct one in §22.6, and
§22.13 made its deletion mandatory — but **the placeholder was not where the
hazard was**. The unit contract (§22.6 requires payoffs normalized to a fraction
of capital) is contradicted by the schema the payoffs arrive on, three modules
away (**O-50**), and the failure direction is neither silence nor false
confidence but **prudence** — a 100× unit error produces a **smaller** number
that looks safer. Read every declared number for what it is a **measurement of**,
and read every contract for **who consumes it**.

### `evaluate_drawdown_rules` — the de-risking ladder that could never fire

Implemented 2026-09-18 (**D-054**). A **new package**
(`portfolio/risk_budget.py`, Module 17.3) — the first code in the repo outside
`models/` and `thesis_layer/`, which is why `tests/portfolio/` was created
alongside it. One function plus two input models and one `Literal`.

```text
drawdown = (high_water_mark - current_value) / high_water_mark
trigger  = max({r : drawdown >= r.threshold_pct}, key=risk_reduction_pct)
```

**It is not what the specification's shape suggested.** `docs/PROGRESS.md`
recorded this function (and `volatility_target_scaling`) as a **"gate chain over a
path"** — the compositional shape that produced defects in D-050, D-051 and
D-052. The probe showed there is **no path** (two scalars in, no sequence), **no
chain** (every rung reads the *same* operand; nothing is consumed), and the resolve
step is a **max, not an accumulating ladder**. The composition defect is
unreachable here — and so is the ladder-accumulation question, which the
specification's "evaluated in order" phrasing implies but never realises.

**The hazard was a unit convention with no converting consumer.** §6.6c writes
`DrawdownRule`'s `threshold_pct` and `risk_reduction_pct` as **fractions**
(`le=1.0`); `config/settings.yaml` writes `drawdown_tiers` as **percents**
(`{drawdown_pct: 10.0, risk_reduction_pct: 50.0}`). Fed across unconverted that is
a **100×** error and **every rung becomes unreachable** — the ladder reports *"no
risk-reduction rule triggered"* at a **90% drawdown**. **The direction was the
opposite of the probe's prediction**, and it is the worse direction: a de-risking
rule that fails toward **inaction** is silently unsafe, where "every tier fires"
would have been merely wrong. Normalised at exactly one boundary (`_tiers()`), with
a magnitude floor on `DrawdownTier` so the file's convention is **checkable at load
time** (`_reject_fraction_scale_entry`). The accessor had **no consumer at all**
before this — a clean "declared, consumed, unreachable" instance, and its first
genuine consumer is this function.

Four further specification defects: unbounded `risk_reduction_pct` (a 500%
"reduction" was legal); "evaluated in order" contradicting "most severe wins" (the
result is permutation-invariant); `max(key=severity)` vs `max(key=threshold)`
indistinguishable on the shipped ladder and divergent off it; and `0.0` ambiguous
between "nothing fired" and "fired, prescribed zero" — repaired with a
`RuleOutcome` `Literal`, which then needed **both** a runtime value test *and* a
`get_args()` type test, because a `Literal` is not enforced at runtime.

**The base-state rule (lesson 5g) does not apply**, and the non-application is a
recorded part of the deliverable — an unrecorded non-application is
indistinguishable from an oversight. `no_action` is modal **and correct**: 82.9% of
2 513 real trading days genuinely warrant no intervention.

Cross-check against `volatility_target_scaling` (§20.13) on three structural
invariants — no shared input exists, so it compares the shared **shape**
(**O-43**: currently a re-implementation, to be re-pointed at the real function).

### `project_inflation_trajectory` — the threshold that made `stable` the base state

Implemented 2026-09-18 (**D-053**). A **new model module**
(`models/inflation_trajectory.py`, Module 3.6) holding one function: an affine map
from the labor-slack score to a projected inflation change.

```text
change_pp = beta * score * fiscal_scale
```

It is the **smallest input space of the remaining Tier 3 functions**, and it
carried the increment's most consequential finding anyway — because the hazard was
**dimensional** rather than compositional.

**The specification negates twice and the negations cancel.** §16.2 writes
`slack = -s/100` and then `pc = -beta*slack`, so `pc = +beta*s/100`. The
implementation now states the substitution in its docstring. This survived the
smoke test, mypy, and **every unit test written at that moment**, because
`_change_pp` was the same expression factored into a helper — the suite was
comparing the function to its own misconception. Only a **functional run on real
input** caught it, which is §21.0's whole argument.

**The band's score-width *is* `band_pp / beta`**, so the band and the slope are
**not independently choosable**. §16.2's `±0.15pp` against a `beta` of `0.043`
labels **79.1% of 296 real months** `stable` — D-047's base-state failure, in a
module with no structural relation to D-047, and a **new sub-shape**: all three
`TrajectoryDirection` members are reachable, so D-045a's reachability check passes,
and the classifier is effectively two-member regardless.

The repair separates the two estimands — `beta` from the **OLS slope of the
6-month forward change** (`+0.00598`, se 0.00159, t +3.76, R² 0.047, n 290; stable
across three subsamples) and the band from a claim about what a meaningful move is
— which is what exposed a **7× config error** (`0.043 → 0.006`, band `±0.05pp`). The
label mix becomes 40.5% / 31.4% / 28.0%.

The relation is **real but small**: it survives 12-month detrending (+0.348),
holds over 3-9 months, and **reverses at 24 months** (−0.0114, t −2.94) — a policy
reaction, not instability.

### `cross_asset_transmission` — the gold rule that did not run its own trigger

Implemented 2026-09-18 (**D-052**). The **largest input space of the six remaining
Tier 3 functions** — a same-day cross-market matrix — and the increment the brief
asked to be built with a cross-check from the start, because this is where the
D-050 composition defect was most likely to appear. **It did appear, and it was
proven.**

**Seven specification defects.** The two that change what a reader sees:

**The gold rule does not run the trigger its own paragraph states.** §20.5 says
gold falls when the **nominal** yield rises; the shipped rule keys on the **real**
leg — the correct economics, and the *opposite* of the prose, because the section's
own next sentence describes the breakeven-driven nominal rise the naive reading
gets wrong. The actual trigger is now inspectable: `driver_channel` names the
single leg a call came from, on every output.

**Three published keys are one predicate.** `gold_call` and two long-duration
equity reads all derive from the same `bonds` direction, so a consumer counting
"three asset classes agreeing" is counting **one cause three times** — §15.19-D's
concern, one level up from the confidence denominator it protects. The coupling is
published and the census treats the three keys as **one vote**; whether the
coupling should be machine-readable in the `value` schema is **O-37**.

Also corrected: `inflation_surprise_bp` is declared, listed in `inputs_used`, and
read by nothing (kept as a **disclosed** input, never a hidden one — the registry
now records its `blocked:` status with four verbatim probes, O-39); `usd` was a
sentence rather than a direction, so it emits `unresolved` instead of guessing a
regime fact it has no input for; `surprise_driver: str` became a `Literal`;
`confidence=0.45` was refused per §22.8.

**The composition defect, and the third kind of inertness.** `both_channels` is
tested before `real_driven`, so every input that would reach `real_driven` is
consumed earlier — D-050's shape exactly. **M2.7** and **M2.8** survived, and both
were **proven inert by enumeration: 643 200 cases, 0 differences**, with the proof
re-runnable via `--probe-inert`. **M9.2** established a **third** kind — it rewrites
a published key's **name**, not a value, so it is neither threshold nor composition
inertness but **name-not-value**. Three kinds, three remedies.

**The live check indicted two already-shipped config leaves.** `gold_call_base_rate`
read **0.7779**; the monthly recomputation is **0.7556** (daily **0.8846**) and **no
population reproduced the shipped figure**. `measured_breakeven_negative_share` was
wrong the same way (0.2754 → **0.2652**), and a third note quoted a **daily**
denominator under a **monthly** heading. Both were written from the authoring probe
rather than fetched — **O-30's class arriving in the config layer** — and every
gate passed while they were wrong. The live check's **>0.5pp** drift bar is the only
mechanism that can catch it; post-fix drift is **0.0000**. See **O-38**.

**And the cross-check had to be *changed*, which is the subtle part.** Comparing
the derived real yield to the observed one is **arithmetic, not evidence**: the
check's own first step proves the identity `DGS10 − T10YIE − DFII10` is exact
(**max error 0.000000 over 5 931 observations**). Rather than discard it, it was
repurposed — the identity is the **proof the derivation is a restatement, not a
proxy** — and the cross-check runs against `inversion_probability_adjustment`
(D-049), which is **disjoint by construction**: a same-day long-end decomposition
against a short-end level, directional calls against a probability, **no shared
series**. Agreement there is evidence; agreement with the identity would have been
tautology (D-027, lesson 46).

Harness finding: **a wording collision masquerading as coverage.** `M10.3`
survived because the warning guard matched `"below the"`, which occurs in **two**
branch texts — deleting one branch left the guard matching the neighbour. Fixed
with mutually non-colliding markers plus a guard asserting each warning matches
**exactly one** marker.

**55/58 killed, 3 proven-inert, 0 defects**; 58 mutations in 13 groups; 52 tests.

**§15.19-D's integration requirement is now wired for five callers of the
section's own list, and remains open for the rest.** The obligation is
per-function and it is not discharged by any one implementation. Wired so far:
`inflation_convergence_classifier` (**D-047**), the `evidence` supplier itself
(**D-046**), `four_pillar_scorecard` (**D-050**), `classify_convergence`
(**D-051**) — the section's own general classifier, which takes an arbitrary
`list[ModelResult]` and censuses its **directional** subset — and
`cross_asset_transmission` (**D-052**), which is the first caller whose
**published output** is the correlated thing: three keys from one predicate counted
as one vote rather than three. Still owing: the remaining convergence classifiers.
**`source_independence_count=0` at a call site that could supply a family count
is now a defect, not a starting state** — **26 such sites remain across 14
modules**, measured after D-047; one is the legitimate self-census in
`evidence.py`.

**All five callers now census the same population, and it took four increments to
get there.** `inflation_convergence_classifier` (D-047) censuses its fixed
sub-measure set; `four_pillar_scorecard` (D-050) censused **all four pillars**
until D-051 corrected it; `classify_convergence` (D-051) censuses only the
directional signals and publishes the exclusion; `cross_asset_transmission`
(D-052) censuses the three keys it derives from **one** predicate as one vote. The
pattern is the same one this document's defect class names — *declared, consumed,
unreachable* — one level in: the census is **called** at every site, but the
question "over which population?" was never asked until two implementations could
be compared. See the Tier 3 note below.

---

## Tier 4 — construction (11 / 11 ✅ COMPLETE)

`select_instrument` shipped in **D-058** (Module 15, `models/instrument_selection.py`),
`construct_duration_weighted_curve_trade` in **D-059** (Module 15.1,
`models/yield_curve.py`), `construct_breakeven_trade` in **D-060** (Module 15.2,
same file), and `construct_cross_market_rv` in **D-062** (Module 15.3, same file —
**Module 15 is now complete, all four of its functions**). Four thesis-layer
functions have since shipped: `derive_invalidation_conditions` in **D-063**
(Module 14, `thesis_layer/invalidation.py`), `build_scenario_distribution` in
**D-064** (Module 12, `thesis_layer/scenarios.py`), `next_catalyst_calendar` in
**D-065** (Module 13-adjacent, `thesis_layer/catalysts.py`), and
`build_confirmation_signals` in **D-066** (Module 14, `thesis_layer/signals.py`),
and `collect_all_warnings` in **D-067** (Module 14, `thesis_layer/warnings.py`),
and `no_trade_thesis` in **D-068** (Module 14, `thesis_layer/no_trade.py`), and
finally `build_us_macro_thesis` in **D-069** (Section 7.2/§16.2, the seam —
`thesis_layer/builder.py`). **Tier 4 is COMPLETE: 11 / 11.**
**Phase 4's instrument half is done** and **Phase 3's thesis-layer half is now
buildable** — but Phase 3 itself has **not started**: `src/macro_engine/api/`
does not exist, and §7.3's example objects are not signed off.

**The instrument half of this tier is finished, and the thesis-layer half closed
at D-069 — the tier is complete.** The four Phase 4 functions landed in
D-058/D-059/D-060/D-062, and **seven** thesis-layer functions have shipped —
`derive_invalidation_conditions` in **D-063**, `build_scenario_distribution` in
**D-064**, `next_catalyst_calendar` in **D-065**, `build_confirmation_signals` in
**D-066**, `collect_all_warnings` in **D-067**, `no_trade_thesis` in **D-068** and
`build_us_macro_thesis` in **D-069**. The last of these is the **seam function**
on both checklists, and the hazard changed shape with it: D-063's four
defects were a type mismatch, a dead parameter, a gate that could not distinguish
two states, and a model named for a condition it cannot express; D-064's were a
defaulted one-member `Literal` that accepted the *wrong unit*, and a distribution
**blind to the sign of the gap it distributes around** — the second found **only**
by the live check, because every fixture used the same sign. **D-065's were
different again: they were not in our arithmetic at all but in the *sources*,
which were wrong in five measurable ways** (a pagination total read as an event
count; one HTTP request per calendar day; a release id that answers for every day
of the year; a flat-text parse that invents future meetings; and a TLS
fingerprint that drops two of the three transports tried) — **plus three defects
in our own code, every one of them surfaced because the sweep refused to certify
rather than asserting its survivors away.** **D-066's were different a third
time**: they were neither arithmetic nor sources but **representability** — a bare
`else` that claimed `contradicts` for every outcome the condition could not
express (a dict, `0.0`, `True`, a zero gap), `source_family` never populated, a
`detail` string that could undercut itself unflagged, and a return type too narrow
for its own question. **D-068's were different a fourth time**: they were **presence**
defects — a sample body that cannot run (six required fields), a stand-down with one
string slot for three triggers, three rich gate objects discarded on the way out, an empty
reason accepted as a valid explanation, and a `"n/a"` sentinel that satisfies the very LTCM
gate it stands down from. **D-069's were different a fifth time — and the shape is
the one to remember:** the seam function's real defect was an **INTERACTION**
defect, invisible to every fixture. `_render` collected **no warnings at all**, so
**every stand-down silently dropped the model warnings and §22.5's market-path
contamination disclosure** — and *no offline test could see it*, because each one
asserted the trigger line was **present** and it was; the defect was that it was
**alone**. It was found by the **live check** printing `contaminated=0 proxy=0`
on a path where the contaminated branch had definitely been taken, and fixed by
rendering first and **appending** the warnings behind the trigger line (the
renderer *owns* `warnings` and refuses to be handed it). After the fix:
**`warnings=13`, `contaminated=1 proxy=1`**. **D-069's sweep then refused to
certify** — six survivors on the first run, the headline being **the very defect
just fixed**, whose regression test had been written **only in the deselected
live file**; all six were closed by **adding** tests (40 → 51), not by exempting
mutants. And its **second** run killed the **honesty control**, because a guard
asserted the fallback's **literal source text** rather than its meaning — a test
asserting **spelling instead of behaviour** (lessons **5be**, **5bf**).
**None of the nine pairing axes would have found any of
them** (see the `Next` section of `PROGRESS.md`).

**This tier straddles a phase boundary, which is why it gates Phase 3.** Of the
11: four are *instruments* (`select_instrument`,
`construct_duration_weighted_curve_trade`, `construct_breakeven_trade`,
`construct_cross_market_rv`) and belong to **Phase 4**; the thesis layer's four
(`build_us_macro_thesis`, `no_trade_thesis`, `collect_all_warnings`,
`derive_invalidation_conditions`) belong to **Phase 3**; the remaining three are
supporting construction for Phase 3. `build_us_macro_thesis` therefore appears
**both** here and in the Phase 3 checklist in `PROGRESS.md` — that duplication is
the seam, not an inconsistency. **§21.3 is the sole authority on when a stub
becomes IMPLEMENTED (§22.1).**

`build_us_macro_thesis` now **composes them all**, and it is the seam.

**`build_scenario_distribution` (D-064) is where two layers meet.** Its own module
is `thesis_layer/scenarios.py`, but the schema it publishes is the models layer's
`ScenarioOutcome` — re-exported rather than redeclared, which closed **O-51** (the
duplicated class across the two layers). Its consumer is the **Kelly payoff
contract** in `portfolio/risk_budget.py`, and that seam is where the increment's
headline defect lived: `KellyInputs.payoff_unit` was a **one-member `Literal` with
no `default=`**, which pydantic treats as **optional**, so a `bp_pnl_proxy`
distribution was accepted and silently relabelled `fraction_of_capital` (**O-50**,
closed). The unit is now **required** and the vocabulary is **nameable and
refused**.

### `select_instrument` is the standard the rest must meet

Section 22.3 singles it out: it is the representative example of what
"multi-country-ready" has to mean. A function may not claim country-genericity
it has not earned, and `select_instrument` is where a country label would
otherwise hide — the instrument set, the curve conventions and the settlement
mechanics all differ per country, so a `country` parameter that switches a label
without switching the instrument universe is a claim, not a feature.

**Shipped D-058.** It obeyed that standard the only honest way available at this
point: a non-`us` country is **refused outright**
(`BLOCKED_MULTI_COUNTRY_NOT_BUILT`) rather than receiving a US instrument under
a foreign label. The interesting half of the increment was not that refusal,
though — it was that the *production universe itself* was consulted rather than
restated. `select_instrument` takes the universe as a **required argument**
(D-046's repair pattern, because `models/` may not import `thesis_layer/`) and
asks the real `ProductionUniverse` whether the instrument it just constructed is
admitted. That question found **two latent defects in already-shipped code**:
the class had no **curve vocabulary at all** — so §22.3.1's own worked example,
`"2y10y US Treasury steepener"`, was inadmissible — and its FX matcher admitted
any six-letter word whose first three letters were a G10 code, so
`"europe equity"` read as a currency pair. `ProductionUniverse` had **never had a
test**; it now has 30.

The generalisable form, which is why this stays in the mapping rather than only
in the decision record: **a router that re-implements its universe's admission
rule cannot discover that the universe's rule is wrong.** The increment's
architectural payoff was making the lower layer *ask* the upper layer instead of
copying it — and the second-order payoff was that the asking immediately
indicted the answerer.

**Shipped D-059.** `construct_duration_weighted_curve_trade` met the same
standard, and the standard caught something different. §15.1b's only defence
against a wrong duration is a published residual with a warning attached —
and that residual is `notional_long`'s own definition algebraically simplified,
so it is zero for **every** input. The function publishes it anyway (it is part
of the declared output) with a machine-readable
`net_duration_residual_is_definitional` flag, and replaces the dead guard with a
**real** one: a duration/tenor plausibility band whose floor and ceiling carry
their measured provenance, plus an explicit attestation for the one error the
band structurally **cannot** see.

Two mapping-level consequences worth stating here rather than only in the record:

* **The unit trap is invisible from inside the function.** `bond_math` returns
  Macaulay duration in *periods*; this contract wants Modified duration in
  *years*. Because the notional depends on the **ratio** `D_s/D_l`, a unit error
  cancels out of the arithmetic and shifts the notional by `(1 + y/f)` — about
  1–2%, with no error raised. Nothing inside the function can detect it, which is
  exactly why the contract requires a **caller attestation** and why the live
  check's cross-check runs against a *different* module.
* **The D-058/D-059 seam now exists and is exercised.** D-058's router emits the
  instrument name for a curve trade; D-059 computes the trade behind it. The live
  check confirms the router's name (`'Duration-weighted 2y/10y UST steepener'`)
  is admitted by the production universe as `rates`, so the two increments agree
  about the trade they describe. Neither function imports the other — the
  agreement is at the vocabulary, which is where D-058 put it.

**Shipped D-060.** `construct_breakeven_trade` is §15.1b's other half — the same
duration-matching rule across a **TIPS / nominal** pair, so Module 15 is
complete. It met the same standard and the standard caught something the sibling
could not: §15.1b's breakeven constructor publishes **no residual and no
`warnings` list at all**, so where D-059 had a *dead* guard this one had **none**.
The contract now carries both the per-leg band (D-059's pattern) and a **ratio**
band, because a single `tenor` field serves two legs and a per-leg check alone
cannot see a swapped pair.

* **The finding is a stronger form of O-57.** D-059 recorded that
  duration-weighting equals level-cancellation only when the legs price alike —
  a 1.23% discrepancy for cash curve legs. For a breakeven the legs are a TIPS
  against a nominal, so the price ratio is far from 1, and the correction runs
  **−56.4% .. +98.7%** over 48 real configurations. Crucially it is
  **two-signed**: with a par nominal the identity `shipped/exact = P_nom/P_tips`
  reduces to `100/P_tips − 1`, so the sign flips at the TIPS leg's own par price.
  A one-signed error is calibratable; a two-signed one is a modelling error.
  **O-59**, and the fix needs the legs' *prices*, which the contract does not
  carry — a §20.11 interface decision.
* **The same unit trap as the sibling, with a worse consequence.** The ratio is
  unit-free so a periods-for-years error still cancels from the *arithmetic* —
  but here the two legs have different yields, so the mismatch is a **relative**
  error between the legs on the order of the real/nominal spread, not a small
  shared scaling. The attestation warning says so explicitly.
* **The D-058/D-060 seam is a two-keyword round-trip.** The router emits
  `'Duration-matched TIPS long / nominal short (breakeven trade)'` for
  `INFLATION_EXPECTATIONS_GAP`; the universe admits it as `rates` only because
  **both** `"tips"` and `"breakeven"` survive in `_RATES_KEYWORDS`. The live
  check asserts both, so dropping either keyword fails loudly.

### Defects carried by Modules 15.1 / 15.2 (D-059, D-060)

| Issue | Bears on | State |
|---|---|---|
| **O-56** | the unreachability exemption both sweeps reuse | A "unreachable" exemption is a **scale condition** — ~10× float-noise margin, lapses above ~$2–5tn notional. **Second** increment where the same margin justifies the same exemption. |
| **O-57** | the curve constructor's level-cancellation claim | Holds only at **equal prices**; §20.11 interface question. |
| **O-58** | `bond_math.price_bond` | Its `coupon_rate` docstring says **annual**; behaviour is **per-period**. |
| **O-59** | the **breakeven** constructor | The rule hedges **duration**, not **dollar** duration; correction is **two-signed** (−56.4% .. +98.7%) so no constant hedges it. Fix needs the legs' **prices**, which the contract does not carry. |
| **O-60** | `curve_trade.breakeven_duration_ratio_min/max` | The note's *range* came from a **simplified probe pricer**, not shipped `bond_math`. |
| **O-61** | the sweep harness itself | A sweep killed mid-run leaves the tree **mutated**, silently (the *pattern-not-found* path reports a survivor). **Incident** — see `PROGRESS.md`. |
| **O-62** | `scripts/*` | **Three** sweeps broken; **no sweep-health check** exists. |
| **O-63** | the gate invocation | ruff has **no `files` key**; a bare `ruff check` reports 1703 errors over `.probe/`. |

### `build_us_macro_thesis` — the seam, and the defect no fixture could see (D-069)

Section 7.2/§16.2. **The only function in this tier that appears on two
checklists**, which is why it is the phase seam rather than a Tier 4 footnote:
with it implemented, the models layer stops producing numbers and the thesis layer
starts making claims. It composes **all eleven** Tier 4 functions plus the model
layer beneath them.

**Layout: nine modules, one function each.** `thesis_layer/` now holds
`invalidation.py`, `scenarios.py`, `catalysts.py`, `signals.py`, `warnings.py`,
`no_trade.py` and `builder.py`, and the builder **composes** rather than
reimplements. The deliberate choice worth recording is that **Q1's three economy
reads are a PARAMETER** (`EconomyReads`, a frozen dataclass), not something the
builder computes: the census of snapshot-taking helpers is **`[]`** for
`inflation_nowcast`, `labor_synthesis`, `regime` and `national_accounts`, so no
honest transform exists and **faking one would have hidden the gap**. The same
restraint appears at the second boundary: `MarketPricingGap` is **not** a
`ModelResult`, so §16.2's sample fails pydantic validation — bridged by an
explicit `_as_signal` adapter rather than by loosening a contract.

**The gates fire in order Q6 → Q7 → Q8**, and each routes to a helper that
**owns its own trigger literal** rather than re-deriving it from the caller's
sentence (D-068's O-85 constraint, honoured one function on).

**THE DEFECT, and why it belongs in this mapping rather than only in the record.**
The builder's real defect was an **INTERACTION** defect: `_render` collected **no
warnings at all**, so **every one of the three stand-downs silently dropped the
model warnings and §22.5's market-path contamination disclosure**. **No offline
test could see it** — each test asserted the trigger line was **present**, and it
was; the defect was that the trigger line was **alone**. What found it was the
**live check**, printing `contaminated=0 proxy=0` on a run where the contaminated
branch had definitely been taken. The repair renders first and **appends** the
warnings behind the trigger line, because `render_no_trade_thesis` **owns**
`warnings` and raises rather than accept an override — respecting D-068's contract
instead of relaxing it. Measured after the fix: **`warnings=13`, `contaminated=1
proxy=1`**.

**The mapping-level consequence, stated plainly:** D-068 established that a
corpus of presence defects invites a clean first sweep. D-069 shows the converse
and it is the more useful half — **a defect that is an *interaction* is
invisible to a fixture suite that tests each field's presence**, and the only
instrument that saw it was the one that ran the whole pipeline on real data.
**D-069's sweep refused to certify on its first run — six survivors, the headline
being the very defect just fixed**, whose regression test had been written **only
in `test_builder_live.py`**, which `-m "not live"` deselects. All six were closed
by **adding** tests (the file went 40 → 51), never by exempting mutants. The
**second** run killed the **honesty control**, because a strictness guard asserted
the fallback's **literal source text** rather than its meaning — a test pinning
**spelling instead of behaviour**, rewritten to pin **order and structure via
`ast.parse`**. **Lessons 5be and 5bf.**

| Issue | Bears on | State |
|---|---|---|
| **O-87** | `select_instrument`'s return contract | **Two value shapes**: a dict on the executable routes, a **bare sentinel string** on the refused ones — while `_selection_value` declares *"always returns a dict value"* and raises otherwise. **The sibling claim is wrong.** Read defensively on both shapes at the boundary (`_instrument_from`). |
| **O-88** | the published gate table | The D-068 row claimed `mypy --strict` was clean at **176 files** while **29 errors** sat in D-068's own files. Found by D-069 running the full gate; **all 29 fixed**, so the gate is now **true at 182**. A gate row is a **claim** and must be re-derived, never carried forward. |
| **O-89** | the mypy/robustness debt this increment surfaced | The residue of the O-88 sweep, recorded separately so the fix is auditable. |
| **O-70** | §21.4's blocked-input obligation | **Now DISCHARGED — close it.** D-067 built the mechanism with **no production call path**; the builder passes `unattributed` through to `collect_all_warnings` on **every** return path, including all three stand-downs, and a live run measures `warnings=13`. |
| **O-84** | the `iorb` live failure | **Diagnosis CORRECTED**: not a frozen clock. The tolerance **is** compared against the current date (*"after retrieval date 2026-09-19 by 2 day(s)"*), and **the provider publishes `iorb` 2–3 days ahead** of the calendar while `future_date_tolerance_days` is `1`. The ERROR path is armed and firing **correctly**. Needs a **data-layer** decision. |

---

| File | Responsibility | Test |
|---|---|---|
| `models/contracts.py` | `ModelResult`, `compute_confidence()`, `utc_now()` | every model test |
| `models/evidence_family.py` | `EvidenceSourceFamily` — the one declaration, shared by both layers | `test_evidence.py` |
| `models/inflation_convergence.py` | `inflation_convergence_classifier` + its `InflationConvergenceVerdict` / `InflationConvergenceInputs` contract | `test_inflation_convergence.py` |
| `models/as_of.py` | The single point-in-time filter (O-7) | `test_phase1_data_layer.py` |
| `config.py` | Typed, validated config; `CalibrationStatus` | `test_infrastructure.py` |
| `data_layer/openbb_client.py` | Two-path fetch, retries, normalization | `test_phase1_data_layer.py` |
| `data_layer/snapshot_builder.py` | The **one** place a snapshot is assembled | `test_phase1_data_layer.py` |
| `data_layer/validation.py` | Range/staleness checks — flags, never fixes | `test_phase1_data_layer.py` |
| `data_layer/persistence.py` | Timestamped parquet audit trail | `test_phase1_data_layer.py` |
| `data_layer/logging_json.py` | One JSON object per line; credential redaction | `test_infrastructure.py` |
| `deployment.py` | Every endpoint/port/credential as a declared variable | `test_infrastructure.py` |
| `settings_store.py` | Bitemporal, append-only revisions | `test_infrastructure.py` |
| `audit.py` | Append-only ledgers; inputs stored by value | `test_infrastructure.py` |
| `thesis_layer/schemas.py` | `MacroThesis` and its gates | `thesis_layer/` |
| `api_layer/orchestration.py` | **The derivation** — snapshot → the builder's six required arguments | `test_orchestration.py` |
| `api_layer/snapshot_provider.py` | The memoized build, its disclosed age, and its `SnapshotUnavailableError` | `test_snapshot_provider.py` |
| `api_layer/app.py` | The app factory; CORS from config; `SERVICE_VERSION` | `test_routes.py` |
| `api_layer/routes_health.py` | `/health` (shallow + `?deep=true`) | `test_routes.py` |
| `api_layer/routes_thesis.py` | `/thesis/{country}` — the status contract | `test_routes.py` |
| `api_layer/routes_dashboard.py` | `/dashboard_data` — panels, capping, withheld counts | `test_routes.py` |
| `api_layer/routes_query.py` | `/query` — keyword routing, and the admission that it is | `test_routes.py` |
| `api_layer/reasoning_stream.py` | The SSE stream — each frame reports what was measured | `test_routes.py`, `test_strictness.py` |

---

### `api_layer/` — the derivation gap, and a sweep that certified a selection it never ran (D-070)

Section 8. **Phase 3 is complete.** Eight modules under `api_layer/` (3383 lines)
implement all five surfaces.

**Why the layer needed a new module at all.** `build_us_macro_thesis` takes **six
required arguments**, and Section 8.2's sample calls it with a snapshot alone —
`TypeError: missing 6 required argument(s)`. The derivation of those six is the
increment's actual work, and it lives in **`orchestration.py` alone** so that the
gap is one auditable file and every router obtains its arguments from the same
place. The strictness file asserts this structurally: a router that reads a guarded
snapshot field directly is a failure, because the three labor-leg **unit traps**
(thousands vs percent; rate vs percentile; persons vs 4-week percent change) would
be re-opened one endpoint at a time.

**The boundary the router must not cross.** `snapshot_to_thesis_inputs` **refuses**
rather than defaults: `OrchestrationError` maps to **502**, `NotImplementedError`
(an unimplemented country) to **501**, a bad `thesis_type` to **422**, and **500 is
reserved for real bugs**. A stand-down is a **completed analysis** and returns
**200** — because Section 16.3 forbids mapping missing data onto `WATCH`, and a
fabricated stand-down is indistinguishable from a genuine "no edge" verdict.

**The increment's own defect was a lookup that succeeded when it should have
failed.** `_yoy_percent` took "the latest observation at or before the anniversary",
which happily returns a point **31 days away** and publishes the ratio under the
words *"year-over-year"*. Fixed by a **config-driven tolerance**
(`api.yoy_match_tolerance_days`, default 5) whose whole purpose is that it
**excludes the adjacent month** — a tolerance of 28 would silently restore the
defect.

**The mapping-level lesson, and it is the same shape as D-069's.** D-069 found a
defect invisible to a fixture suite because it was an **interaction**. D-070 found
one invisible to a *sweep* because it was in **the harness**: `PYTEST_TARGETS`
declared four test files, `run_pytest` ran three, and `check_tests_collect`
validated the declaration the run never used. **A green gate certified a selection
nobody executed**, and the three mutants whose tests lived in the unselected file
survived looking exactly like inert mutants. The remedy is structural — both
functions splat **one** constant, and a new gate refuses to run if either re-inlines
a path. **Lesson 5be, and the stronger form of it: a target list is a claim, and a
claim is only true where it is consumed.**

Three further guards **manufactured a green** and were replaced: the version check
compared `app.version` to the constant the app itself reads (self-referential); the
`loopback_only` guard compared a constant to a computation that agreed with it
under the shipped loopback config (a tautology); and the M7.1 guard validated a
list no run consumed. **A guard that cannot fail on the tree it guards converts
"untested" into "verified" (lesson 80).**

**And a third lesson, from the live check rather than the sweep.** The check's first
three runs failed, and **every failure looked like a defect in the service while the
service was correct.** The reusable part is the diagnostic shape:

* a **routing-shaped symptom with a transport-shaped cause** — a 404 from a
  registered route, because a proxy rewrote the request line. The status code cannot
  tell the two apart; **the request line can**, and finding it required tapping the
  socket rather than re-reading the route;
* **a check that supplies the wrong input** — a hardcoded `:3000` origin against a
  config that allows `:8000`. The service was right and the check was wrong, and the
  fix (derive the origin from config) is the stronger assertion;
* **a check that pins a rendering rather than a value** — searching for a spacing the
  stream never promised. Lesson 5bf applies to checks, not only to tests.

Every one was invisible to the 125 green unit tests, because those drive
`TestClient`, which **never opens a socket**. A check that exercises the transport is
the only thing that can see a transport defect.

| Issue | Bears on | State |
|---|---|---|
| **O-90** | the memoized snapshot's **scope** | `_CACHE` is process-global, so `--workers N` silently multiplies the build cost (measured **223.6s** live). The response discloses the age but not *whose* cache. Needs a `workers=1` contract or a shared store — a deployment decision. |
| **O-91** | the stream's execution model | The async generator awaits a **synchronous** build, blocking the event loop so `/health` goes unanswered during a slow build. Needs `to_thread`/executor. Not fixed here because it would invalidate the provider mutants that certify the current behaviour. |
| **O-81** | §21.4's blocked-input obligation | **DISCHARGED at the API layer** — `EconomyReads` now has a producer. |
| **O-83** | the scoped leftover scan | **Remedy IMPLEMENTED.** `sweep_health.py` now scans the whole tree for mutant **shapes** with no catalogue; verified live by catching an in-flight `# MUTANT`. |
| **O-84** | the `iorb` live failure | Unmoved — a **data-layer** decision (see the D-069 block above). |
| **O-92** | the **live check's transport**, and the production clients it mirrors | **Found by the live check and mitigated for the check only.** `httpx` defaults to `trust_env=True`, so the check's loopback traffic went through the environment's `HTTP_PROXY`. A forward proxy must use the **absolute-URI** request form (RFC 7230 §5.3.2); the proxy forwarded that URI to uvicorn, which read it as the *path*, and `/health` returned a **404 from a route that is registered and correct**. The intermittency — the first request on a fresh connection survived, a reused keep-alive one did not — is what made it read as a routing bug. Fixed in the check (`trust_env=False` on every client, with the proxy variables printed so runs stay reproducible) and guarded by an `ast` read of the script. **The same root cause is present in two production clients** (`openbb_client.py:91`, `catalysts.py:213`), where the OpenBB client's mounts against `http://127.0.0.1:6900` are `{http://: HTTPProxy, https://: HTTPProxy}`. The provider works here (21/21 fields) — which is the environment's proxy forwarding loopback, not design. **Filed rather than fixed**, because it changes data-layer network behaviour this increment did not touch and would have invalidated the sweep that certifies the provider. |

---

## Gaps this mapping exposes

1. **`api_layer/` is now implemented (D-070); `thesis_layer/` and `api_layer/`
   are both full layers.** Phase 3 is complete. The gap that remains is the
   service's **execution model** (O-90, O-91) rather than a missing surface.
   `thesis_layer/` gained `invalidation.py` in **D-063**, `scenarios.py` in
   **D-064**, `catalysts.py` in **D-065**, `signals.py` in **D-066**,
   `warnings.py` in **D-067**, `no_trade.py` in **D-068**, and finally
   `builder.py` in **D-069** — so the layer is **complete and no longer a
   collection of orphans**. `build_us_macro_thesis` **now exists** (1174 lines)
   and is the caller **O-70** was waiting for: the Q8 round-trip is no longer
   asserted only against a hand-built `TradeIdea`, and the builder passes
   `unattributed` through to `collect_all_warnings` on **every** return path,
   which is the production call site §21.4 requires. **O-70 can be closed.**
   **D-064 adds a second instance of the cross-layer shape:** `scenarios.py`
   is consumed by the Kelly contract in `portfolio/risk_budget.py`, and that
   seam is exactly where that increment's headline defect lived (**O-50**,
   closed) — a schema-side default that the consumer's own contract forbids.
   **D-069 adds a third:** the builder consumes `select_instrument`, whose
   return value is a **dict on the executable routes and a bare sentinel string
   on the refused ones**, while that module's `_selection_value` declares
   *"always returns a dict value"* — the **O-87** contradiction, read
   defensively on both shapes at the boundary (`_instrument_from`).
2. **`models/extensions/*` are Phase 4+ stubs**, correctly signed per the
   "stubs are never silently empty" rule.
3. **0 of 15 Tier 3 and 0 of 11 Tier 4 functions remain. BOTH TIERS ARE
   COMPLETE.** **Tier 3** closed at **D-057**; **Tier 4** closed at **D-069
   (11 / 11)** (`select_instrument` D-058,
   `construct_duration_weighted_curve_trade` D-059,
   `construct_breakeven_trade` D-060, `construct_cross_market_rv` D-062 — Module
   15 complete — `derive_invalidation_conditions` D-063,
   `build_scenario_distribution` D-064, `next_catalyst_calendar` D-065,
   `build_confirmation_signals` D-066, `collect_all_warnings` D-067,
   `no_trade_thesis` D-068, and `build_us_macro_thesis` D-069).
   **Both halves of Tier 4 are finished** — the instrument half at D-062 and the
   thesis-layer half at D-069.
   **The tier count no longer blocks §7:** `build_us_macro_thesis` exists and
   runs, and it is listed on both the Tier 4 and the Phase 3 checklists — that
   overlap *is* the phase seam, now **crossed**. Phase 3 is open, and what
   remains is Phase 3's own work (the §7.3 example-object sign-off and the
   §8 API layer, which does not exist). **Phase 2's 13 outstanding items are all
   Tier 5** — the §22.3 deferral list, not a backlog.

   **D-065 interaction with this table (the D-060 lesson, fifth occurrence — and
   the first time the lesson applies to a *new* file rather than an edited one):**
   `next_catalyst_calendar` is not a function whose edits land in an already-swept
   module. It is a function whose **data sources** are the seam — and the
   project's sweep habit does not naturally cover a seam that lives at the *other
   end of a socket*. The five source defects (the `ptic` pagination total, the
   per-day request fan-out, release 101's daily answer, the flat-text phantom
   meetings, the dropped transports) are invisible to every offline test the
   project writes, so this increment is the first whose **live check carries
   defects no mutation could express** — the check does not merely confirm the
   function runs, it **measures the sources' own failure modes** (rid=101 covers
   41/41 days; the flat parse yields 55 hits against 53 structured). It also
   produced the first **config-owned live identifiers** (`cpi_release_id: 10`,
   `nfp_release_id: 50`, `pce_release_id: 54`, measured, with a distinctness
   validator), because a release id is a fact about a third party that can change
   without our code changing — **O-74** and **O-75** are the two halves of what
   that costs.

   **D-068 interaction with this table (the D-060 lesson, EIGHTH occurrence — and
   the first where the interaction is with a function that **does not exist
   yet**):** `no_trade_thesis` (D-068) lands in a **new** file
   (`thesis_layer/no_trade.py`), so as with D-067 no existing sweep's anchors were
   touched — all 36 sweeps still load and resolve (`tools/sweep_health.py`: **36, 0
   failures, 0 leftovers**), and the four newest siblings (`mutation_curve_trade`,
   `mutation_breakeven_trade`, `mutation_scenario_distribution`,
   `mutation_warnings`) were re-run to confirm the counts still reproduce. The
   interaction that matters is the one the previous block **predicted**: D-068's
   `NoTradeDecision` changes what `build_us_macro_thesis` must do at **three** call
   sites (Q6/Q7/Q8), because each must now **derive the `trigger` from the gate it
   observed** and hand over the gate object as `evidence` — rather than passing a
   sentence, which is what §16.4's signature asked for. **A `no_trade_thesis` that
   the builder calls with a hand-written trigger is the defect this increment
   recorded as O-85, and the builder is the only place it can be closed.** With
   D-068, §16.2's Q1–Q8 sample diverges from the shipped contracts in **seven**
   places, and every one of them lands in that one function.

   **D-067 interaction with this table (the D-060 lesson, SEVENTH occurrence — and
   the first where the interaction was with the GATE rather than with a sibling's
   source):** `collect_all_warnings` (D-067) lands in a **new** file
   (`thesis_layer/warnings.py`), so no existing sweep's anchors were touched. The
   interaction that mattered was elsewhere: **D-064's leftover `M6.3` mutant was
   still applied in `config.py`** — a file this increment never edited — because
   `tools/sweep_health.py`'s leftover scan is **per-sweep**, and `config.py` belongs
   to the *scenario* sweep, which was target-clean **only because the mutation had
   already fired** (**O-83**). It surfaced only because that sweep independently
   refused on an unrelated absent anchor; restoring the constraint took the scenario
   sweep from refusing to **23 applied / 22 killed**. The lesson generalises past
   D-060's "a tier is not finished when its functions exist": **a green gate is not
   evidence when the gate's search space is derived from the thing being checked** —
   and it is the same failure D-060 named, one layer up.

   **D-066 interaction with this table (the D-060 lesson, SIXTH occurrence — and
   the first time the interaction is with a *sibling in the same tier* rather than
   with an earlier one):** `build_confirmation_signals` (D-066) and
   `derive_invalidation_conditions` (D-063) read **the same three `ModelResult`s**
   and publish into **the same `MacroThesis`**, and they now share the same
   narrowing rule and the same three-outcome philosophy — but they are still two
   functions, and §16.4's two halves still declare **different contracts** for the
   same input (§20.15 compares `value < 0` unguarded; §16.4 guards it). The new
   row's interaction is therefore **with the record, not the file**: D-066's
   `ConfirmationSignalAssessment` changes what `build_us_macro_thesis` must unpack,
   so **§16.2's Q1–Q8 sample now diverges from the shipped contracts in four
   places** (Q7's return is not a list; Q8 must pass `invalidation.text`; the Kelly
   call must pass `payoff_unit`; the calendar must be real) and the builder is
   where all four land. **A tier is not finished when its functions exist; it is
   finished when the composition function that consumes them has been checked
   against each.**

   **D-064 interaction with this table (the D-060 lesson, fourth occurrence):**
   `build_scenario_distribution` is the first Tier 4 function whose edits landed
   in a file (`portfolio/risk_budget.py`) already holding **three** swept
   siblings (`mutation_kelly.py`, `mutation_drawdown.py`,
   `mutation_rebalancing.py`). Making `KellyInputs.payoff_unit` **required**
   invalidated `mutation_kelly.py`'s `M4`-group anchors and its `M9.2` anchor, so
   the sweep was re-anchored and **extended 25 → 27** so the seam is covered from
   both sides; it now reports **27 / 27 killed, 0 survivors**. Both sibling sweeps
   were left untouched and their recorded counts still reproduce.

   **D-062 interaction with this table (the D-060 lesson, third occurrence):**
   adding `construct_cross_market_rv` to `models/yield_curve.py` — which by then
   held TWO swept constructors — was checked against both siblings **before**
   declaring the increment done, and both reproduce their original counts exactly
   (`mutation_curve_trade.py` **31/26/5**, `mutation_breakeven_trade.py`
   **26/23/3**). It also produced a **new** failure mode the older gates could not
   see: an anchor that is unique in the file but belongs to a **neighbouring
   function** (`M8.1`'s `confidence=compute_confidence(` occurs first in
   `curve_slope`). `check_targets` passed; only a landing-site audit found it, and
   that audit is now the sweep's `check_anchor_landings` gate (**O-67**).

   **D-060 interaction with this table:** adding `construct_breakeven_trade` to
   `models/yield_curve.py` — the same file as D-059's
   `construct_duration_weighted_curve_trade` — turned **eight** of D-059's
   `mutation_curve_trade.py` anchors AMBIGUOUS (the **D-051** trap: two classes
   in one module sharing byte-identical validator source). Repaired by extending
   each anchor past the shared prefix; the sweep reproduces `31/26/5` exactly.
   **A row added to this table is not the only thing a new function touches** —
   it also re-anchors its file's existing sweeps.
4. **No function in this table is verified multi-country.** By construction —
   and **D-058 is the first function to *enforce* that refusal rather than merely
   be scoped by it**: a non-`us` country returns `BLOCKED_MULTI_COUNTRY_NOT_BUILT`
   instead of an instrument. The remaining three Tier 4 functions have the same
   obligation and only one of them (`build_us_macro_thesis`) has an instrument or
   a `country` parameter at all. **D-062 found the obligation violated in the
   specification rather than in the code**: §20.12 labels its output
   `country="global"` while `ModelResult.country`'s own field description says
   *'"us" only through Phase 4'* — the function now publishes `"us"` and carries a
   mandatory scope warning (**O-64**), but §20.12's text still says `global`, so
   the next author will write it again.
5. **`thesis_layer/schemas.py` is now a *consumed* dependency of `models/` —
   without an import edge.** D-058's router receives the universe as a required
   argument typed by a `Protocol` declared in `models/`, so the layering rule
   holds while the vocabulary stays owned at the top. The cost is **O-54**: a
   `Protocol` is a static promise and nothing validates conformance at runtime.
   This is the shape to reuse for any further `models/`-needs-`thesis_layer/`
   need, and the shape to watch for the same reason.
6. **Module 13 now has five consumers, and the contract is only partly
   closed — with a sixth that is deliberately *not* one.** `tag_evidence_source` and `count_independent_families` shipped in
   D-046 with nothing calling them; `inflation_convergence_classifier` (D-047)
   was the first caller, `four_pillar_scorecard` (D-050) the second,
   `classify_convergence` (D-051) the third, and `cross_asset_transmission`
   (D-052) the fourth, so `source_independence_count` is no longer *universally*
   `0`. **But the
   obligation is per-function**: **26 sites across 14 modules**
   still pass a literal `0` (measured after D-047; D-046's "~15" was an
   estimate), and each is a defect to be worked off one increment at a time
   rather than a neutral default. The one exception is `evidence.py` itself,
   where the census must not score its own output (D-027). See the Tier 3 note above.
   **D-058 added a site that is *not* in that count**: `select_instrument` passes
   `0` because it consumes **no series at all** (its inputs are a thesis label and
   a direction), which is an honest zero rather than a placeholder — the
   distinction the issue asks future increments to make explicitly.
   **D-065 is a *second* instance of that honest exemption, and a plainer one:**
   `next_catalyst_calendar` consumes no series either — it consumes **a calendar**
   — so it passes `source_independence_count=0` for the same reason `select_instrument`
   does, and for one more: a release date is **not evidence about the economy**, it
   is evidence about when evidence arrives. Tagging it through Module 13's family
   vocabulary would be a category error, and the function's absence from the sweep
   of `0`-sites is therefore correct rather than an omission.
7. **Three of Module 5's recorded input blocks were false.** §21.1 declared
   `median_cpi_direction` and `trimmed_mean_direction` unreachable; both are
   live FRED series (`MEDCPIM157SFRBCLE`, `PCETRIM1M158SFRBDAL`). This is a
   **data-availability** gap, not a code gap, and it is the third occurrence of
   the O-21 class — see `docs/OPEN_ISSUES.md`.

## Keeping this file true

Regenerate rather than hand-edit. The three checks that make it trustworthy:

- **Functions** — `ast`-walk `src/macro_engine/models/*.py` for module-level
  `def`s whose names do not start with `_`.
- **Tests** — resolve from the test suite's `ImportFrom` nodes, so a function
  with no importing test shows as a gap rather than inheriting a neighbour's
  coverage.
- **Tiers** — read from `docs/PROGRESS.md`, which is updated in place at each
  milestone and is the authoritative count.

A hand-edited row is a claim about the specification; a generated row is a claim
about the code. This project has corrected the specification fifty-four times,
so the code is the side worth reading.

**Note (D-054): the generator walks `models/`, and `evaluate_drawdown_rules`
does not live there.** It is the first Tier 3 function in `portfolio/`, so the
`ast`-walk above now needs `portfolio/*.py` added to its roots or this row will be
silently dropped by the next regeneration. Recorded here because a generator whose
roots are hardcoded fails by **omission**, which is invisible in the output. **D-055 added a second function to the same file, so the
omission would now drop two rows, not one** — and the file (`risk_budget.py`)
holds both, which means the root fix is per-*package*, not per-function: a
generator that walks `portfolio/*.py` picks up both, and one that does not picks
up neither.

**A re-export is not a second definition, and this file must not read it as
one.** The generator resolves a function's `Source` to the module that *defines*
it; `thesis_layer/schemas.py` re-exporting `EvidenceSourceFamily` is an import
path, not a home. Read the `from … import` line before recording a source, or
the table will show a vocabulary living in two places at once.

### `volatility_target_scaling` — the constraint that is inert where the risk is

Implemented 2026-09-18 (**D-056**). The **second** function in
`portfolio/risk_budget.py` (Module 17.2), sharing the file with the §6.6c ladder
and the §15.18 drift check — which is why `RiskLimits` now lives there as the
shared hard-constraint vocabulary.

```text
raw_scale       = target_vol_annualized / current_portfolio_vol
scaled_exposure = current_gross_exposure * raw_scale
final_exposure  = min(scaled_exposure, limits.max_leverage)   # ONE-SIDED
```

**The whole of §20.13's enforcement is that `min`, and `min` is an upper bound by
construction.** On the de-risking side — the side a vol target exists for — it is
a no-op. Measured over a real 5-ETF path: the clip fires on **0 of 444 sessions**
while the reflexivity warning fires on **13.1%**. The failure **direction** is
D-054's (toward silence), reached through a different mechanism (arithmetic rather
than a unit convention). The repair is a published `de_risking_fraction`, because
`clipped=False` on a book cut by **94%** reads as "no constraint engaged".

**Four of the five limits §17.3 declares beside it had zero references anywhere in
the repository** — the **D-037 class** ("declared, consumed, unreachable") for the
fifth time. The repair is **disclosure, not enforcement**
(`limits_declared_but_not_enforced`), and the distinction is recorded as **O-48**
rather than papered over: a consumer that reads the field and assumes it binds
would repeat the original mistake.

**§20.14's mandatory golden test is a HIT, not a PARTITION** (lesson 49): it names
`max_leverage` and passes while four limits stay unenforced. A test written from a
specification's wording inherits the specification's blind side — and the sweep
reproduced this exactly, with a mutant that **relocates the one-sided clip to the
up-scaling side** and passes the entire test file.

**O-45 resolved by deletion.** `RiskLimits.max_drawdown_trigger_pct` was the
**same trigger** as the ladder's first rung and is unreachable from this signature
(no drawdown input), so the ladder governs and the duplicate is gone —
`RiskLimits` ships with **4** fields.

**O-43 discharged.** `live_drawdown_check.py` §4 now **calls** this function
instead of re-implementing §20.13, so the D-054 cross-check is a real comparison
rather than a restatement (lesson 5's distinction).

**The unit trap, fourth increment running:** `max_position_pct_of_portfolio:
0.15` is a **fraction despite `_pct`**. The guard is a magnitude bound enforced in
**two layers covering different objects** — `RiskLimits`'s field bounds, and
`RiskSettings._reject_percent_in_fraction_field` for the bare `CalibratedValue`
leaves that have no bound of their own.

**The base-state rule does not apply**, and the non-application is recorded: the
output is a **magnitude**, not a label, so no state is modal by construction.

Cross-checks against **two** siblings, both **real calls**:
`evaluate_drawdown_rules` on the shared *invariant* (monotone in stress, flat at
zero stress) and `check_rebalancing_drift` on the shared *disclosure shape* —
the second is what makes the one-sided flag legible.

### `apply_fractional_kelly` — the hazard was in the unit, three modules away

Implemented 2026-09-18 (**D-057**). The **third** function in
`portfolio/risk_budget.py` (Module 17.3, §20.14/§22.6), and **the last Tier 3
function**: Tier 3 closes at **15 / 15**.

```text
generalized_kelly_fraction:  f* = argmax_f  SUM_i [ p_i * log(1 + f * r_i) ]   # grid search
fraction = index / (grid_points - 1)                                           # step = 1e-5
multiplier = settings.kelly.kelly_fraction_multiplier                          # 1 / divisor, k >= 2
final_fraction = min(requested * multiplier, cap)
```

**§17.3 was wrong and §22.6 was right, and both were in the specification.**
§17.3 declares `raw_kelly = ev / 100` — a placeholder **incorrectly labelled
Kelly** — beside §22.6's expected-log-growth optimum. §22.13 makes the deletion
mandatory, so the increment's first act was **deleting a formula the
specification itself had shipped in prose**. **Only `generalized_kelly_fraction`
may call itself Kelly.**

**The deletion is not mutation-testable**, and the sweep's docstring says so
rather than pretending otherwise: you cannot kill a mutant you removed. What the
sweep *can* check is that the survivors' claims hold — and the false claim is
guarded by `test_the_context_states_the_placeholder_is_not_implemented`, which
asserts the context says **replaced**, not merely that it says something.

**The payoff-unit contract is only half guarded.** §22.6 requires payoffs
**already normalized to a fraction of capital**. The function's guard catches the
**loss** side (`r_i < -1.0` is impossible for a fractional return) and is silent
on `+120` — a legal 12000% gain. The contradiction is not in this file at all: it
is `thesis_layer.schemas.ScenarioOutcome`'s `unit="bp_pnl_proxy"` **default**,
and it is recorded as **O-50**. **This is the project's fourth distinct failure
direction, and it fails toward prudence** — the wrong unit yields a **smaller**
`f*`, a cap that *slips* rather than binds, and a number that looks **safer** than
the correct one.

**`M7.1`'s unreachability proof corrects this module's own docstring.**
`SizingOutcome` documents a state — `clipped_by_position_limit` **with a zero
result** — that cannot occur, because the cap carries a field bound `gt=0.0` and a
zero cap is a `ValidationError`. The closing test asserts that reachability fact,
so a future bound change is **visible rather than silent**.

**The central cross-check is an ARITHMETIC oracle, not a sibling call.** Kelly's
input is a caller-supplied distribution, so `live_kelly_check.py` is **offline by
design**: there is no series that could falsify it. The check instead runs the
**shipped grid** against the **binary closed form** `f* = (p·b − q·a)/(a·b)` —
**3.33e-16** worst absolute error over 80 combinations — and then reproduces the
search-edge collapse on real inputs (`distinct REQUESTS: 1 of 3`, `distinct
GROWTHS: 3 of 3`) so the disclosure is **measured**, not asserted.

**The two classes named `ScenarioOutcome` are a class-level collision** (O-51),
and `mypy --strict` does not see it: both are types, both construct, and a test
that imports one of them passes. It is D-045's property-vs-field collision one
level up.

### The risk-budget seam — two functions that never appear in the tiers, and should not

**`compute_risk_parity_weights` (D-071) and `translate_thesis_to_position` (D-072)
are Module 17.1 / 17.4 functions, not tier functions, and the tier tables above
correctly do not list them.** Tier 3 closed at 15 / 15 at **D-057** with
`apply_fractional_kelly` as its last member; Tier 4 closed at 11 / 11 at
**D-069**. Adding these two to either count would be the same defect this mapping
exists to prevent — a **declared** membership that the code does not have. They
live in `portfolio/risk_budget.py`, the same file as D-054/D-055/D-056/D-057, and
the generator note above (`portfolio/*.py` must be in the `ast` roots, **D-054**)
applies to them for the same reason.

**What the seam exposes is a *shape* contradiction, and it is the fourth
cross-layer shape this mapping has recorded.** The three prior ones were
D-064 (`scenarios.py` ↔ Kelly's unit contract, closing **O-50**), D-069
(`select_instrument` returning a dict on executable routes and a bare sentinel
string on refused ones, **O-87**), and D-063's `NoTradeDecision`. This one is
arithmetic rather than structural:

| Layer | Quantity | Defined by |
|---|---|---|
| Module 17.1 | **risk share** — `RC_i = w_i (Σw)_i / σ_p²` | needs `Σ` |
| §9.3 | **notional share** — what the position size may be | takes `MacroThesis` + a risk budget, **no covariance** |

**§9.3's signature cannot supply the covariance §17.1's identity requires**, and
the two quantities are not equal. Measured on a real two-asset book, the naive
conversion (risk share used directly as notional share) is **6.7x wrong**: `0.018`
where the correct answer is `0.12`. **This is the strongest argument in the
codebase for §9.3's own output contract** — that `translate_thesis_to_position`
returns a **proposed** position requiring human sign-off and never a sized order.
The `SIGN_OFF_REQUIRED` sentinel is not a formality; it is the composition of two
specification sections that cannot be composed numerically.

**The second current in this seam is the declared-consumed-unreachable class
(D-045/D-046/D-048, O-53) — for the sixth and seventh time.** `PositionTranslationOutcome`
is a six-member `Literal`, and the file's docstring makes a *counting* claim about
it. **The claim shipped saying "nine members" for a `Literal` that had six.** The
sweep's first run proved it was changeable to any number with every test green
(`M10.2`, `M10.3` both SURVIVED — `get_args` reads the type; a docstring is a
string), and the repair is a test that recounts the members and the gates from the
docstring itself. **A docstring claim about a type is a claim, and it needs a
receipt (lesson 5bo, extending O-88 from gate rows to prose).**

**The gates are four, and the count is now pinned.** The removed fifth gate is
recorded in the file as a comment, not as code, and the docstring states the rule
the deletion established: **"There are four, not five: a gate that cannot stop a
proposal is not a gate."** The sweep's `M10.3` mutant flips that sentence's
numerals and is now killed.

**Defect class this increment added to the mapping's vocabulary: "the right outcome
with the wrong reason."** Several refusals returned the correct `outcome` while
naming a **different gate's** reason. No numeric assertion can see it — the
outcome, the size and the struct all match — and only the reason phrase differs.
It is D-056's (false confidence) neighbour on the *diagnostic* axis rather than the
numeric one, and it is why `scripts/live_thesis_position_check.py` re-reads the
reason on **all seven** paths instead of checking only the outcome.

**The instrument universe is a real measured object, not a fixture.**
`ProductionUniverse().permits` returns `True` for `TY futures`, `EURUSD` and
`"NONE"`, and `False` for `SPY`, `TLT`, `GLD`, credit and
`ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT`. **All four US thesis families**
(`policy_path_gap`, `curve_shape_gap`, `inflation_expectations_gap`,
`equity_macro`) produce `status=WATCH`, `instrument="NONE"`, an empty
`scenario_distribution` and `scenario_sizing_permitted=False` **on today's data**,
so they all refuse at **gate 1**. The measured 24-cell census had **8 schema-refused
and 16 measured** cells. That is the Section 21.0 record for this increment, and it
is why the sweep needs hand-built fixtures to reach gates 2–4: **the live pipeline
cannot reach them, and a sweep that only ran green paths would certify nothing.**

**O-93 is the documentation half of the same seam.** Two no-instrument sentinels
are **different strings**, and **four documentation sites** asserted they were the
same. The correction is sharper than the original claim: `is_trade` returns `True`
for the sentinel, so it reads as a **live trade in an unexecutable instrument**.
`§16.2` Q12's **exposure** half is computed nowhere (**O-94**) and needs Module 18.

### The §17.4 axis — the third layer that consumes the seam, and the bound that could not bind (D-073)

**`_apply_risk_axis` (D-073) is not a Module 17 function either.** It lives in
`thesis_layer/builder.py`, not in `portfolio/risk_budget.py`, and it is **consumed
from a distance**: §17.4 asks the *thesis layer* to read a *risk-layer* output and
change a *lifecycle* decision. The mapping's three-layer picture therefore gains a
back-edge:

| Layer | Reads | Writes |
|---|---|---|
| `portfolio/risk_budget.py` (Module 17.1/17.4) | a thesis + a risk budget | a proposed size, or a refusal |
| `thesis_layer/builder.py`'s `_apply_risk_axis` (§17.4) | that proposal **and** its outcome | the thesis's **`status`** |

**This is the only back-edge in the system**, and it is why O-96 is worth a row:
the rule that defines it names `CANDIDATE → WATCH`, and **`CANDIDATE` is a state
nothing in the tree produces.** The edge therefore operates on `DRAFT`, the state
that actually reaches sizing. **A back-edge whose source state has no producer is
the declared-consumed-unreachable class in a new vocabulary** — the mapping has now
recorded it through a guard (D-045/D-046/D-048), an instrument sentinel (O-53) and
a lifecycle state (O-96), and the third one was only visible by asking *"who writes
this value?"* rather than *"does this branch run?"*

**The bound is a config leaf whose validity depends on the model's OUTPUT, and that
is a mapping consequence, not a tuning one.** `thesis_demotion_fraction` is only
meaningful relative to the set of sizes the pipeline can publish — and that set is
**six discrete values**, not an interval:

```
0.02941 · 0.03472 · 0.042735 · 0.069445 · 0.125 · 0.15
```

The reason is Module 17's own shape: **full Kelly is the argmax of expected log
growth**, and for a two-branch distribution with a positive edge that objective is
**monotone in `f`**, so `f*` pins at the search-domain edge and the Module 17.3
position cap (`0.15`) produces the number. **Only asymmetric branch sets land
strictly inside the domain.** The bound shipped at `0.02` — **below every reachable
value** — so §17.4 could not fire and the test that would have caught it **skipped**.
The bound is now `0.03`, and the three constraints it carries are: `> 0`,
`< max_position_fraction` (`0.15`), and **`>= the smallest reachable size`
(`0.02941`)**.

**The mapping rule this adds: a config leaf whose valid range depends on another
module's reachable OUTPUT cannot be validated at the config layer.** It needs a
consumer that re-derives that output — here
`scripts/live_risk_axis_check.py`, which recomputes the six values and fails if the
bound stops splitting them. **D-035's gate-count discipline, one layer up: a bound
is a CLAIM about a set the config cannot see.**

**The two amended guards are mapping consequences too.** `thesis_layer/` now
legitimately imports `macro_engine.portfolio` (§17.4 requires it), so the
strictness guard forbidding that edge was removed with a written reason — **a guard
forbidding the wiring the specification mandates is a guard against the
specification.** And the Kelly guard in `test_integrity_gates.py` was
**strengthened**, not relaxed: it now enumerates the **permitted** consumer surface
(`translate_thesis_to_position` being the one sanctioned route to Kelly per §25)
instead of merely testing where Kelly is called.


---

## The D-075..D-079 pass — three mapping rules it adds

This pass found no new module and no new tier. It found **four classes of defect
whose home is the seam between two layers**, and each adds a mapping rule.

### 1. `nan` is a READABLE value in every fallthrough axis helper (D-078)

**The mechanism, stated once so it is checkable everywhere:** every axis/bucket/
direction helper in the project is a **fallthrough** —

```python
if x < lo:  return LOW
if x < hi:  return MID
return HIGH            # <- the branch a NaN reaches
```

`nan` fails **every** comparison, so it does not fall out of the band tests as an
error and does not take a neutral branch. It arrives at the **final `return`**, the
most extreme bucket the grid has. Measured, before the fix:

| call | returned | i.e. |
| --- | --- | --- |
| `classify_regime_rule_based(output_gap=nan)` | `growth_axis='above_trend'` | the most expansionary state |
| `classify_regime_rule_based(inflation_trend_3m=nan)` | `inflation_axis='flat'` | a fabricated *stable* |
| `classify_regime_rule_based(inflation_trend_3m=inf)` | `inflation_axis='rising'` | a fabricated *rising* |
| `taylor_rule(pi_current=nan)` | `value=nan` | a prescription that is not a number |
| `MarketPricingGap(raw_gap=nan)` | `direction='aligned'`, `is_meaningful=False` | **"model and market agree, insignificantly" — a silent NO-TRADE from absent data** |
| `_direction_for(nan, +1)` | `'contradicts'` | a fabricated disagreement |
| `derive_market_implied_policy_path(short_tenor_term_premium=inf)` | `-inf` | a **sign inversion** in the reference path |
| `api_layer/orchestration.py` | `else 0.0` | an output gap of *exactly zero* |

**The mapping rule: guard the input DOMAIN, not the output RANGE.** A range check
written on the result (`0 <= value <= 1`) *passes* for `nan` — every comparison a
plausibility check is made of returns `False` for `NaN`, so a poison reports CLEAN
(the D-074.1 mechanism, now confirmed at a second layer). The only sound place to
refuse a non-finite value is **where it enters**, as a pydantic `model_validator`
on the inputs object, or an explicit `isfinite` gate at a free function's boundary.

**Two consequences for this mapping:**

- `pydantic`'s `float` **accepts** `nan`/`inf` by default (`allow_inf_nan=True`).
  *Class membership is not a validity test* — `isinstance(x, (int, float))` is
  `True` for `nan`. A field typed `float` is **unconstrained** unless the validator
  says otherwise.
- `models/as_of.py`'s `dropna` does **not** remove `nan` — `nan` is not null. The
  point-in-time path is therefore not a defence against this class, and a reader
  that trusts `dropna` to sanitise its input is trusting the wrong thing.

Consumer sites fixed this pass: `models/regime.py`, `models/policy_rules.py`,
`thesis_layer/signals.py`, `api_layer/orchestration.py`. Regression surface:
`tests/models/test_non_finite_inputs.py` (43 tests) and
`tests/thesis_layer/test_signals.py` (+11).

### 2. A live check may test TODAY'S MARKET and call it the WIRING (D-079)

`scripts/live_labor_check.py` asserted `len(set(verdicts.values())) > 1` to prove
that `default_rate_trend` actually **reaches** the credit-attribution verdict. On
2026-09-20 the HY OAS **tightened** (`-2.0bp`), so `widening_observed` was `False`
for all three trends and every verdict legitimately read `NO_WIDENING` — the model
was correct and the **check failed**. The assertion conflated two different claims:

| claim | what it needs | why a live row cannot supply it |
| --- | --- | --- |
| **is the wiring correct?** | a row where the branch is *reached* | days when the branch is unreached |
| **is today's reading right?** | today's actual row | cannot prove reachability |

**The mapping rule: an instrument's WIRING and its reading are two claims and need
two rows.** A live check that can only see one market state can only prove one of
them. Fix: pin the wiring claim on a **constructed** row (`hy_spread_change_bp=1.0`)
that is *labelled* as constructed, and print the live row separately as the reading.
This is `live_risk_axis_check.py`'s pattern (D-073) generalised — a check recomputes
the reachable set rather than hoping the market supplies it. Classed as **O-100**.

### 3. An anchor is a CLAIM about source text (D-075)

`mutation_drawdown.py` `CX5` and `mutation_regime.py` `M8d` were recorded for two
sessions as *"targets absent by design — DO NOT FIX."* Both were **stale anchors**
matching 0 occurrences: a defensive `get("tiers", [])` default added to the live
config accessor, and a four-line comment block inserted between two lines the anchor
pinned as adjacent. Neither mutation surface had changed. **A sweep that reports
`target ABSENT` cannot distinguish "this mutation no longer applies" from "this
mutation never existed"** — the O-95 self-concealing class, where the stale anchor
destroys its own evidence. After repair both sweeps certify: `mutation_drawdown.py`
47/47, `mutation_regime.py` 40/40.

**The mapping rule: O-88's "a gate row is a claim, not a receipt" applies to anchors
too, and the do-not-fix list is not exempt from re-measurement.** A "known, by
design" failure that no one has re-derived from the source in N sessions is a
carried claim, not a measured fact.

### 4. A code fix citing a decision number is citing a receipt (D-075.3)

Two docstrings in the tree cited `(D-076)` and `(D-077)` while **no such entry
existed in any record file**. The numbers were real (the entries were written this
pass) but the *sequence was inverted*: the code claimed the decision before the
decision was recorded. **The mapping rule: write the decision entry in the same
increment as the code that cites it.** A citation is a pointer to a receipt; a
pointer to a missing receipt is worse than no citation, because it reads as
authority.

---

## The D-080 addendum — the fifth mapping rule: an assertion has a *reach* as well as a *meaning*

The four rules above (D-075..D-079) each described a defect at a **seam between two
layers**. This one is a defect at a **seam between a test and the branch it claims to
cover** — and it is the first mapping rule in this file about the *test* layer rather
than the *code* layer.

### The rule

> **A test has two properties, and the suite measures only one of them.**
>
> - Its **meaning** — does the assertion match the specification? This is what a
>   reviewer reads, and what the docstring usually states.
> - Its **reach** — does the input actually take the path the mutation moves? This
>   is what makes the assertion *load-bearing*, and **nothing measures it.**
>
> A test whose input never enters the mutated branch is **equivalent to no test**
> while reading — in the suite, in review, and in the coverage number — **exactly
> like one.** (Lesson 5ce.)

The instance: `test_the_tolerance_is_not_applied_to_forward_looking_series` asserted
the correct property, and its docstring named the correct hazard. But its input was a
point dated **2030-01-01** against a retrieval of **2026-09-16** with
`future_date_tolerance_days=1`. The ~1,570-day lead routed the point into
`future_dates`, **not** `tolerated_future_dates` — so the guard
`if tolerated_future_dates and not forward_looking:` was **never consulted**, and the
mutant that deletes `and not forward_looking` moved a value nothing read. **The
mutation sweep found in one run what review had not found in two sessions.**

### Why this belongs in the mapping, not just the decision log

**Because the failure mode is invisible to every instrument the project already has.**

| instrument | why it cannot see this |
| --- | --- |
| the test suite | the test **passes** — it is green in both the correct and the mutated tree |
| a coverage number | the test **executes** the function; it simply never enters the branch |
| reading the test | it asserts the right thing, in the right words, citing the right hazard |
| mutation testing | **only** this sees it — and only if the sweep is actually **run** |

**The mapping consequence: a mutation sweep is not a redundant gate on top of the
test suite. It is the ONLY instrument that measures an assertion's reach**, and the
suite is the only instrument that measures its meaning. They are orthogonal, and the
project's habit of treating a certified sweep as *"extra assurance"* understates what
it is. `mutation_lei_proxy.py` — a sweep that had been annotated *"target absent by
design, do not fix"* for two sessions — was the **single** thing standing between this
gap and production.

### The corollary — the do-not-fix label is where reach goes unmeasured

The same file that carried this gap also carried the label that hid it. **Three
entries were annotated "target ABSENT — do not fix, by design" and all three were
wrong** (`CX5`, `M8d`, `M8e` — D-075, D-080). In each case the label described the
*check's* failure, not the *code's* property, and the correct response was to fix
the check.

> **A do-not-fix list is a place where the project has agreed to stop measuring.
> Everything on it should be treated as unmeasured, and the honest default reading of
> a persistent failure list is: this is a to-do list, not a risk acceptance.**

Note what the fix for this class looks like in each case, because it is always the
same shape: **re-derive the claim from the source.** `CX5`'s anchor was compared
against the live accessor; `M8d`'s against the live block; `M8e`'s against the live
field; and the new test's input was chosen by **measuring which input populates
`tolerated_future_dates`** rather than by reasoning about what ought to. Every one of
these is O-88 — *a row is a claim, not a receipt* — applied to whatever object the
claim was written about: a gate, an anchor, or an assertion's own input.

---

## The D-082 addendum - the sixth mapping rule: a *protection* has a reach too

D-080 established that an **assertion** has a reach as well as a meaning, and that
a mutation sweep is the only instrument that measures reach. D-082 adds the same
distinction for a **protection**: a safety mechanism has a *reach* - the set of
failure modes it actually intercepts - and that reach is **not** inferred from its
existence, its description, or the fact that it is a recognised pattern.

### The rule

> **A protection's reach is measured by reproducing the failure it claims to
> intercept, on the platform it will run on - never by reading the code that
> installs it.**

### The case that produced it

After D-081, the remedy for "a killed sweep leaves mutated source" looked settled:
add a signal handler, as `mutation_api_layer.py` already had. A shared
`install_signal_restore()` was written into `scripts/_sweep_gate.py`, wired into
`mutation_regime.py`, and **described in the record as the defence**.

It intercepts nothing on this platform. Measured, in three probes:

| probe | expectation | measurement |
| --- | --- | --- |
| self-`SIGTERM` | handler restores the file | file stays `MUTATED`; **handler body never entered** |
| self-`SIGINT` | handler's `SystemExit(130)` | exit **2** (`KeyboardInterrupt`) - the handler did not run |
| trace wrapper | a trace line per invocation | **no trace line at all**, with the handler confirmed installed *and* the payload confirmed armed |

The third probe is the one that matters methodologically. It ruled out the two
comfortable explanations - *the handler was never installed* and *the payload was
never set* - and left only the true one: **on `win32`, `os.kill(pid, SIGTERM)` maps
to `TerminateProcess`, so the signal never reaches Python code.** `SIGINT` is
delivered as a `KeyboardInterrupt` rather than routed to the registered handler.

**The consequence is a retraction, not just a gap:** `mutation_api_layer.py`'s
`_restore_in_flight` - credited in the record at D-057/D-062 as the defence
against leftover mutants - **is inert here.** It is kept, because it is correct
and does work on POSIX, but the record that counted it as protection on this
platform is wrong.

### What the mapping should point at

The protection with real reach is the one that depends on the least: the
**sidecar**. `record_pristine()` writes the target's pristine text next to it
*before* the first mutation; `restore_from_sidecar()` restores from it on the next
run. No signal, no catalogue, no in-process state - only the filesystem, which
survives a kill that bypasses every Python-level mechanism.

It is also **strictly stronger than the existing `repair_leftover_mutations`**,
and the comparison is worth keeping: that function inverts a leftover by *matching
the catalogue* (`old` absent AND `new` present), so it can only heal a mutation it
still recognises. Restoring from recorded bytes needs to recognise nothing.

### The ordering rule this exposes (5co)

The heal must run **before** `check_targets`. Reversed, the gate reads the mutanted
source, reports `MUTATION STILL APPLIED` (D-081's discriminator working perfectly),
and **refuses the run** - so the gate blocks its own repair.

> **A recovery mechanism must be positioned before the gate that would refuse the
> run it is there to enable.**

### And the same rule applied to the tool that gates the gates

Wiring the 14 sweeps to import `_sweep_gate` broke `tools/sweep_health.py`, which
reported **all 14 as `IMPORT FAILED`** - they work standalone (the script directory
is on `sys.path`) but not under `spec_from_file_location`. This is **O-62** in its
purest form: *a sweep that cannot run is indistinguishable from a sweep nobody
ran*, produced by the change meant to strengthen them.

> **A gate change must be verified through the gate's own entry point, not through
> whichever path the developer happened to use.** (5cn)

---

## The D-087 addendum - the seventh mapping rule: a check that is *only* dirty-relative cannot see a defect that *is* the baseline

D-080 established that an assertion has a *reach*; D-082 established that a
protection has one. D-087 adds the same distinction for a **check**, and the
reach it exposes is the widest gap found so far - because the failure mode is
not "the check is wrong" but "the check is **structurally unable to look** at the
place the defect is".

### The rule

> **A check whose reference is the working tree cannot see a defect that has been
> committed. The only instrument with reach over that case is the one that reads
> the committed blob as data (`git show <rev>:<path>`) and compares a catalogue
> against it.**

### Why this is not just "check harder"

`models/lei_proxy.py` carried an applied mutation - `else: lead_direction =
"broad_based_advance"` where `"mixed"` belongs - and it was in **`HEAD`**. The
reach of each existing instrument, measured:

| instrument | reference | sees a working-tree mutant | sees a committed mutant |
| --- | --- | --- | --- |
| `git diff HEAD` | `HEAD` | yes | **no** - the mutant *is* `HEAD` |
| sweep `check_targets` | anchor vs working tree | yes | **no** |
| `sweep_health.py` leftover scan | catalogue vs working tree | yes | **no** |
| **`_committed_mutant_scan`** | **catalogue vs `git show HEAD:`** | (n/a) | **yes** |

Every row but the last is *dirty-relative*. A mutation is a **text substitution**;
if that substitution is committed, then compared to `HEAD` the tree is **clean**,
and every dirty-relative check reports success. This is why the defect survived
under green gates: the checks were not lying, they were **looking elsewhere**.

### What the mapping should point at

The predicate must also be right, or the newly-reached check produces noise from
its new vantage point. The count-stable form - *applied ⟺ `old` is absent AND
re-applying does not raise `new`'s count* - is exact here because a genuine
left-over already contains the replacement: applying it again **duplicates** it.
A drifted anchor leaves the count unchanged. Measured **0 false positives / 0
misses** over the 622 reachable entries; the membership form it replaces measured
**52 / 0**.

### And the tiebreaker hierarchy, completed

D-087 also settles what to believe when checks disagree. The order is:

1. `git diff HEAD` - scope-free, but **blind to a committed defect**.
2. The sweeps' catalogue **vs `HEAD`** - catches what (1) cannot.
3. `git show HEAD:<path>` **read as data** - the ground truth both are compared
   against.
4. What the **demanding test** does when the defect is re-injected - the only
   check that measures *meaning* rather than *text*.

> **When three checks disagree, believe `git diff HEAD` (O-102, 5ck) - unless
> `git diff HEAD` is itself clean, in which case the defect is either absent or
> committed, and only (2) distinguishes them.** (5cp)

---

## Module 18 — Quantitative Tools (`models/econometrics.py`), 5 of 6

**These four rows were missing from the tier tables for three increments.** Module
18 is **not** a §21.3 tier member in the way the rest of this file is: its functions
are Tier 5, so they have no row above, and `run_regression` (D-092) and
`test_stationarity` (D-094) shipped without ever being added here. A mapping whose
stated purpose is *"spec → module → function → test, generated from the code"* was
therefore silent about two implemented functions and their tests. Added at
**D-097**, with the third function of the same file.

| Spec | Module | Function | Source | Test | Decision |
|---|---|---|---|---|---|
| **15.20-F** | 18 | `run_regression` | `models/econometrics.py:222` | `test_econometrics.py` | **D-092**, **D-093** |
| **15.20-F** | 18 | `test_stationarity` | `models/econometrics.py:373` | `test_econometrics.py` | **D-094** |
| **15.20-F** | 18 | `test_cointegration` | `models/econometrics.py:514` | `test_econometrics.py` | **D-097** |
| **15.20-F** | 18 | `compute_pca` | `models/econometrics.py:816` | `test_econometrics.py` | **D-099**, **D-100** |
| **15.20-F** | 18 | `kalman_latent_state` | `models/econometrics.py:1845` | `test_econometrics.py` | **D-101** |
| **6.6** | **8** | `yield_curve_pca` | `models/yield_curve.py:1899` | `test_yield_curve.py` | **D-102** |

**The line numbers above were RE-MEASURED at D-101, and ALL FOUR older ones had
drifted AGAIN** — by exactly `+3`, the size of the Kalman block inserted above them
(`219`/`370`/`511`/`813` → `222`/`373`/`514`/`816`). This is the **second**
consecutive increment in which the same rows went stale, and the mechanism is
structural rather than careless: **every addition to `econometrics.py` inserts text
above the rows below it**, so a line number in this table has a half-life of one
increment. The D-100 note predicted exactly this and it happened anyway. **A line
number is a claim, and it must be re-derived with `grep -n` at every close** — or the
column should be replaced by something that does not rot.

**The Module 18 table is now COMPLETE except for its Module-8 consumer.** `yield_curve_pca`
shipped at **D-102**, so all five §15.20-F signatures AND the §6.6 consumer are
implemented; **Module 18 is 5 of 6** and the sixth is Module 8's, which is why the
count and the row's module number disagreed until D-101 corrected it.

**`classify_regime_markov_switching` SHIPPED at D-105** — the Tier-5 REPLACEMENT
for `classify_regime_rule_based` (§21.3; see D-096's reconciliation: Phase 5+
builds the sophisticated version of each deferred item and deletes nothing). It is
**Module 3**, `models/regime.py`, and it does **not** touch Module 18's count.
**Tier 5 = 7/23.**

**`monte_carlo_var` SHIPPED at D-106** — the Tier-5 REPLACEMENT for `historical_var` /
`parametric_var` / `expected_shortfall` (all Tier 1, all shipped in Phase 4, all in
`models/risk.py`), with §17.4's risk axis as the consumer. It is **Module 17**,
`models/risk.py`, and it too does **not** touch Module 18's count. **Tier 5 = 8/23.**
**Same shape as D-105:** a Phase-4 SIMPLE version exists and the Phase-5 version
replaces it without deleting anything.

**Next = `cip_check`** — **Module 9's** FX-parity function, the head of §21.3's Tier-5
list, and the first of the **14** Tier-5 functions that do **not** yet exist in `src/`
(they need **creating**, not un-stubbing). `compute_risk_parity_weights` was previously
named here as "the next function" — **it is not outstanding: it shipped at D-071, in
Phase 4** (see the correction below). The same "ask what it replaces" rule applies.

> **⚠️ CORRECTED 2026-09-25 (D-108): this row said "Module 8's FX-parity half", and the
> module number was WRONG.** Resolved at the line, not from memory: `AGENTS.md:1002` is
> `### 6.7 FX Carry / Parity Models (Module 9)`. **Module 8 is Yield Curve / Credit**
> (§6.6, `AGENTS.md:964`), which is where `yield_curve_pca` and the breakeven live. The
> two modules are adjacent in §6, which is the likely origin of the slip — and the
> `models/` file name confirms it: `fx_carry.py` is Module 9's file, exactly as
> `yield_curve.py` is Module 8's. **A module number is a citation, and a citation is a
> claim** — the same discipline that resolved §15.20-F at D-095.

**One row was also WRONG about its module.** `yield_curve_pca` was recorded against
Module 18; §21.1's table puts it in **Module 8** (Yield Curve/Credit) and it lives in
`models/yield_curve.py`, not `models/econometrics.py`. Corrected here. It is Module
18's *output* in §15.18's narrative (which is where the error came from) but Module
8's *function*, and those are different claims.

**The citation is §15.20 block F, not "§15.18-F".** §15.18 is Module 18's
*narrative*; **§15.20 holds the signatures** (AGENTS.md:3137). Three decisions
invented the wrong number and it was corrected in 30 places at **D-095**. Resolve a
section number with `grep -n` before citing it — a citation is a claim like any
other.

**The Spec column reads `15.20-F` on every row, and that is correct rather than lazy.**
§15.20's block **F** (*"Module 18 — Regression / Stationarity / Cointegration Stubs"*)
is a **single** block carrying **four** signatures under one heading — verified with
`grep -n` at D-100 against AGENTS.md:3137. There is no `15.20-A`, `-B`, `-D` or `-E`;
those letters were invented by the earlier rows and have been corrected. The only real
sub-lettering in §15.20 is **A–F for six different modules**, not six parts of Module
18. **Both the section number and the block letter are claims to resolve with
`grep -n`, never to carry forward from the row above.**

> **`run_regression`, `test_stationarity`, `test_cointegration`, `compute_pca` AND
> `kalman_latent_state` all cite §15.20-F.** That is not a transcription slip: §15.20's
> block **F** is the block that carries *all five* signatures, which is exactly why the
> "§15.18-F" error was made in the first place. Resolved by `grep -n` at D-100 and
> **re-counted at D-101**: D-100 recorded "FOUR of them under ONE heading" while
> implementing the fourth, and the fifth (`kalman_latent_state`, AGENTS.md:3187) was
> already in the block. The count was taken from the functions that were implemented
> rather than from the block — the same "a citation is a claim" failure D-100 had just
> recorded, one increment earlier.

### What `kalman_latent_state` supersedes and what it feeds

**Supersedes: nothing.** There was no prior Kalman implementation in the tree, and
`pykalman` is prohibited (§1) as unmaintained.

**Feeds: `r_star` and potential GDP — a stated path, not live wiring.** §21.1's input
table records `policy.r_star` as **CONFIG** (`settings.yaml`, default 0.5) and marks it
**NOT OBSERVABLE**, with *"Phase 5+ replaces with Kalman estimate"* as the upgrade
path. That is the `confidence` upgrade §15.18's Module 18 narrative describes:
`policy_view` and `growth_view` gain a measured latent state in place of a static
constant. **No module imports `kalman_latent_state` today**, so as with its siblings
the integration is a *contract* rather than live wiring, and it does **not** appear in
the reachability audit's set for the same reason (that audit tracks §21.3's wiring
obligations, and Module 18 is Tier 5 by design).

**The static `r_star` is a real consequence, and it is recorded rather than implied.**
Until a caller wires this function into the thesis layer, `policy.r_star` remains a
configured constant, and §21.1 already names its uncertainty as *"the single largest
driver of policy-rule dispersion"*. The function makes the replacement possible; it
does not perform it.

### What `compute_pca` supersedes and what it feeds

**Supersedes: nothing.** There was no prior PCA implementation in the tree.

**Feeds: `yield_curve_pca` (Module 8, the §6.6 stub) — and that is a stated
dependency rather than a live wiring.** `yield_curve_pca` is the natural consumer of
this decomposition, but **no module imports `compute_pca` today**, so as with
`test_cointegration` the integration is a *contract*, not live wiring. It does **not**
appear in the reachability audit's set for the same reason: that audit tracks §21.3's
wiring obligations and Module 18 is Tier 5 by design.

### The ninth mapping rule, from D-100: a RELATIVE guard needs a DIVERGENT case

The eighth rule (below) says a duplicate test name is a silent deletion. D-100 adds
one about **what it takes to prove a tolerance**:

> **A guard whose tolerance is relative can only be proven relative by a case where
> the relative and absolute answers DIVERGE.** `compute_pca`'s constant-series guard
> uses a tolerance scaled to each series' own magnitude. Mutation **M66** reverted it
> to a fixed `eps * 100` and **SURVIVED**, because every constant the tests then used
> (`4.2`, `0.0`, `-3.0`) leaves a floating-point residue that a fixed epsilon *also*
> catches — so the two guards were indistinguishable and the tests agreed with both.
> **Measured: the residue is not monotone in magnitude** (`4.2` → `7.1e-14`,
> `271.83` → `1.1e-13`, `314.16` → `4.3e-14`, `1e6` → exactly `0.0`), so the
> magnitudes that *do* diverge had to be found by measurement rather than chosen as
> "large". The generalisable form: **for any guard, mutating it to the plausible
> weaker version is the only way to learn whether the tests actually constrain it.**

### What `test_cointegration` supersedes and what it feeds

**Supersedes: nothing.** There was no prior cointegration implementation in the
tree, so this is an addition rather than a replacement — unlike the Tier-5 items
D-096 identified as *upgrade-pass* work (`classify_regime_rule_based` ->
`classify_regime_markov_switching`, `realized_vol_simple` -> GARCH,
`historical_var`/`parametric_var`/`expected_shortfall` -> `monte_carlo_var`).

**Feeds: the pair/relative-value leg, and nothing yet.** The `ModelResult` carries
the statistic, the **spread series**, the **half-life** and a **regime-stability
verdict** — that shape is the contract a later `statistical_arbitrage` /
pair-selection consumer reads. **No module imports it today**, and that is stated
rather than implied: the integration is a *contract*, not live wiring. This is why
it does **not** appear in the `Gaps this mapping exposes` reachability set — that
audit tracks §21.3's wiring obligations, and Module 18 is Tier 5 by design.

### The eighth mapping rule, from D-097: a duplicate test NAME is a silent deletion

The file's existing rules cover assertions (D-080), protections (D-082) and anchors
(D-075). D-097 adds one at the level *above* them:

> **A test's name is an identifier, and a duplicated identifier silently deletes the
> earlier test.** Python binds a function name to the **last** definition; two
> module-level `def test_x()` with the same name leave one test, and pytest reports
> nothing. The suite stays green while losing coverage.

**Measured at D-097:** four new `test_cointegration` refusal tests reused names
already owned by `test_stationarity`'s guards, and a fifth collided with
`run_regression`'s confidence test — so **five earlier guards were absent from the
run** for the whole increment. **No test could see it; only `ruff`'s F811 did**, and
that only at the `ruff check .` gate. The remedy is a naming convention (the
`cointegration` qualifier) plus the count as evidence: **2872 -> 2923 passed**, so
the restoration is measurable rather than asserted.

**And the damage was NOT confined to the test count.** Restating those five names took
the mutation sweep from **52/56 to 55/56 with no mutation changed at all**: **M2, M30
and M32** had been reported as surviving because the sweep asks *"does any test fail?"*
and the only tests remaining under those names no longer covered the mutated code
(`M30`/`M32` were "saved" by `test_cointegration`'s refusals, which assert on different
messages and a different function; `M2` by nothing at all, its covering test having been
deleted from the run). Re-applying each mutation in isolation, with the sweep's **own
anchors**, gives a swap that **compiles OK** and a suite that **fails** — so all three
were always genuine kills. **A shadowed test name therefore corrupts the SWEEP's
verdicts as well as the run's coverage**, and the two symptoms point in opposite
directions: the suite looks green because it LOST tests, the sweep looks red because it
is USING THE WRONG ONES.

**This is D-093's lesson one level up.** D-093 came from two silent-failure paths in
*parameter column names* — a `const`-named column overwriting a coefficient — and
concluded *"review the IDENTIFIERS, not just the arithmetic."* D-097 shows the same
defect class in the **test namespace**. Any module that grows sibling tests needs
its new names checked against the existing set, and a rising pass count is the proof
rather than the absence of failures.

---

## D-105 — Module 3's `classify_regime_markov_switching` (2026-09-24)

**Tier 5 = 7/23.** §6.2, Module 3, `models/regime.py`. **Module 18 is untouched at
5 of 6** — this is Module 3's Tier-5 replacement, not a Module-18 row.

**It lands in the SAME MODULE as the function it supersedes**, and that is a
mapping fact worth stating: `classify_regime_rule_based` and
`classify_regime_markov_switching` are both **Module 3**, both in `models/regime.py`,
and §6.2 fixes the new signature "so the thesis layer's contract doesn't change
when this replaces the rule-based version". **§21.3's tier table is the authority
on WHEN a stub becomes IMPLEMENTED; the MODULE column is the authority on WHERE.**
The Tier-5 list names 23 functions and they do not all belong to one module:
`yield_curve_pca` is Module 8 (D-102), `classify_regime_markov_switching` is Module
3 (D-105), and the rest of §15.20-F is Module 18. **A tier is a dependency depth,
never a module.**

**The supersession map, which is the only correct instrument for this list
(D-096):** `classify_regime_rule_based` → `classify_regime_markov_switching`
(this increment) · `realized_vol_simple` → GARCH · `historical_var` /
`parametric_var` / `expected_shortfall` → `monte_carlo_var` (next). A keyword grep
of the Tier-5 list for a capability answers the wrong question; **ask what each
entry replaces.**

**The output shape is deliberately NOT the rule-based one.** §6.2 asks for
"smoothed regime probabilities per period, not a hard label", so `value` carries
the probability path as its primary output and the hard label is a derived argmax
published beside its own probability. A consumer reading the two classifiers as
the same object is reading a partition and a posterior as if they were
interchangeable — they are not, and the function's `decision_prohibition` says so.

---

## D-106 — Module 17's `monte_carlo_var` (2026-09-24)

**Tier 5 = 8/23.** §17.1 (AGENTS.md:3680–3696) and §18.2 (3870–3886), Module 17,
`models/risk.py`. **Module 18 is untouched at 5 of 6.**

**Where it lands — and the row that already exists for it.** `MONTE_CARLO` has no
row of its own above because it is Tier 5; but the row it supersedes does: line 64
lists **Module 17 · Risk · `historical_var` · `models/risk.py` · `test_risk.py`**.
`monte_carlo_var` lands in the **same module and the same file** as the three Tier-1
functions it replaces, exactly as D-105's comparator landed beside its rule-based
sibling. **§21.3's tier table is the authority on WHEN a stub becomes IMPLEMENTED;
the MODULE column is the authority on WHERE.**

**The supersession map, which is the only correct instrument for this list
(D-096):** `classify_regime_rule_based` → `classify_regime_markov_switching`
(D-105) · **`historical_var` / `parametric_var` / `expected_shortfall` →
`monte_carlo_var` (this increment)** · `realized_vol_simple` → GARCH (still
outstanding) · the inverse-volatility weighting → `compute_risk_parity_weights`
(**DONE — D-071, Phase 4, NOT outstanding; the pointer that named it "next" was
stale and was corrected 2026-09-25**). A keyword grep of the Tier-5 list for a
capability answers the wrong question; **ask what each entry replaces.**

**The output shape is deliberately NOT the Phase-4 one.** The three Phase-4
functions take a **return series** and read a quantile of it; this one takes the
**factor covariance matrix** and a **loading vector** and draws **joint** (correlated)
factor shocks through a Cholesky factor, so the portfolio P&L is a **co-moving** sum.
That is the mechanism §18.2 names for the LTCM detection rule — a *sum of marginals*
understates tail loss precisely in the high-correlation state, and the published
`diversification_ratio_normal` / `diversification_ratio_stressed` are the pair that
exposes the gap. A consumer reading the four as interchangeable risk numbers is
reading a **sample quantile** and a **model quantile** as if they were the same
object — they are not, and the function's `decision_prohibition` says so.

---

## D-107 — no new mapping; a mapping RULE is added (2026-09-25)

**Tier 5 is unchanged at 8/23.** No function was added, moved, or promoted. **Module 18
is untouched at 5 of 6.** `monte_carlo_var` remains Module 17 · `models/risk.py`, the
Tier-5 replacement for `historical_var` / `parametric_var` / `expected_shortfall` — the
**same module and file** as the three it supersedes (D-106).

**What this increment adds to the mapping discipline is a eighth rule, about the
mapping's own vocabulary:**

> **An eighth mapping rule — "implemented" is a statement about a FILE, and a prose
> claim about a file is not a mapping.** D-106 mapped `monte_carlo_var` to
> `models/risk.py` correctly, and that mapping was true throughout. What was **not**
> true was the accompanying sentence that a docstring *inside* that file had been
> corrected: `git show HEAD:src/macro_engine/models/risk.py` still carried the wrong
> unit. The mapping table answers *where a function lives*; it does not and cannot
> certify *what a file says*, and an increment that lets the second inherit the
> credibility of the first has smuggled a claim past its own instrument. **The rule:
> the column names the artefact; the artefact is verified by reading it.** Here that
> verification is now a test
> (`test_the_documented_unit_of_factor_volatilities_matches_the_arithmetic`) that
> parses the docstring bullet and the field `description` **out of `risk.py`'s own
> source** with `ast` — the prose is checked against the file, not against a report.

**The supersession map is unchanged** (D-096): `classify_regime_rule_based` →
`classify_regime_markov_switching` (D-105) · `historical_var` / `parametric_var` /
`expected_shortfall` → `monte_carlo_var` (D-106) · `realized_vol_simple` → GARCH
(outstanding) · the inverse-volatility weighting → `compute_risk_parity_weights`
(**the next function**). **Ask what each entry replaces, never grep the list for a
keyword.**

**A ninth mapping rule — a VERDICT is a mapping claim, and a verdict that varies with
the environment maps nothing (O-132).** D-107 found that `mutation_rebalancing.py`'s
verdict on `M2.6` was a function of the interpreter's **hash seed**: a sort-determinism
test pinned a sorted order using a **two-name** fixture, and `list({'zzz','aaa'})`
coincides with sorted for some seeds and not others — so the same sweep reported the
mutant as killed in one process and **surviving** in the next. Since the mutation sweeps
are how this project maps *a guard to the defect it catches*, a verdict that depends on
`PYTHONHASHSEED` maps the guard to **nothing**; it is worse than an absent row, because
an absent row is visibly absent. **The rule: a mapped guard must FAIL for the same
reason in every process.** For any test that pins an **order**, the fixture must be
large enough that container-iteration order cannot coincide with the expected order —
measured here, seven names differ from sorted for **every** seed `0..7`, two do not.



**A tenth mapping rule — a NAME is not a COVERAGE claim, and a name-grep maps nothing
(O-133).** A substring grep of the test files for a function's name reports
`run_regression` → **0** while the same function's tests execute **64 of its 65 executable
lines**. `monte_carlo_var` → **43** and `yield_curve_pca` → **32** only because their name is
also the **module** name, so their test file is named after them; `run_regression` shares
`econometrics.py` with four siblings and its tests are named after the **assertions** they
make (`test_mechanism_is_recorded_on_the_result`), so the grep finds nothing. **The count
measures naming convention, and its error is unbounded in both directions.** Since this file
exists to map *a function to the tests and sweeps that witness it*, a name-grep maps a
function to **nothing** — the same class as O-132's environment-dependent verdict, reached
from the reporting side. **The rule: ask what the tests EXECUTE, never what they are
CALLED.** The instruments are `tools/tier5_line_coverage.py` (a `sys.settrace` line tracer;
measured **828/847 = 97.8%** across the nine Tier-5 functions) and the **mutation sweep**,
which kills against live code and is naming-independent. **A `def` line always reads as
uncovered** under the tracer — the `def` STATEMENT runs at import — so subtract it before
judging a gap, and read a **defensive guard** whose condition is false on every legitimate
call as **correctly** uncovered rather than as a hole.

---

## D-108 — Module 9's `cip_check` (`models/fx_carry.py`, a NEW file) (2026-09-25)

**Tier 5 = 10/23.** Module 18 is untouched at 5 of 6.

| function | module | file | spec | supersedes | status |
| --- | --- | --- | --- | --- | --- |
| `cip_check` | **9 — FX Carry / Parity** | `models/fx_carry.py` (**created here**) | `AGENTS.md:1013` (§6.7) | **nothing named** — Phase 0–4 had no parity check at all | **IMPLEMENTED** (D-108) |

**An eleventh mapping rule — a module number is a citation, and a citation is a claim.**
The row above is the first in this file to be *created* rather than *corrected*, and the
correction it carries is its own: the previous "Next" pointer called `cip_check`
**"Module 8's FX-parity half"**, and Module 8 is **Yield Curve / Credit** (§6.6,
`AGENTS.md:964`). The authority says `### 6.7 FX Carry / Parity Models (Module 9)`
(`AGENTS.md:1002`) — resolved with `grep -n` at D-108, not recalled. **The same discipline
that resolved §15.20-F at D-095 and `yield_curve_pca`'s module at D-100.** Two adjacent §6
sections is all it takes for a module number to drift by one, and the drift is invisible
because both readings name a real module.

**A twelfth mapping rule — a mapping can be a FILE that does not exist, and the mapping is
what creates it.** Every other Tier-5 row maps a function to an existing module, so the
mapping's question was *"which file does this belong in?"* — a filing decision. Here the
answer was `models/fx_carry.py`, which **did not exist**, so the mapping was not a filing
decision but a **creation**: the file, its config block, its tests, its sweep and its live
check were all produced by the same increment that recorded the row. **The consequence for
this table:** a Tier-5 row whose file is absent is not a gap in the mapping — it is the
mapping's *most informative* state, because the module number and the file name are the
only two facts available before the work starts, and a wrong module number (see above) is
invisible until someone resolves the section. `carry_score` and `dollar_smile_regime` are
now rows against the **same file**, so the next two increments test a different property:
whether a mapping that was correct for one function survives a second function landing
beside it (D-055/D-060's anchor-ambiguity class).

**The supersession map, updated (D-096):** `classify_regime_rule_based` →
`classify_regime_markov_switching` (D-105) · `historical_var` / `parametric_var` /
`expected_shortfall` → `monte_carlo_var` (D-106) · **`cip_check` supersedes NOTHING NAMED**
— it is new capability, and the honest answer to "what does this replace?" is *"no function;
it is the first FX function in the project"* · `realized_vol_simple` → GARCH
(outstanding) · the inverse-volatility weighting → `compute_risk_parity_weights`
(**shipped at D-071, Phase 4 — not outstanding**). **Ask what each entry replaces, never
grep the list for a keyword.**

**Reachability mapping.** `cip_check` classifies as **SCRIPT-ONLY — Tier 5** (its only
caller is `scripts/live_cip_check.py`), so the Tier 1-4 unreachable baseline stays
**58 = 58**. Its `decision_relevance` names the intended consumer (Module 9's
funding-stress read for a carry or dollar view) and states plainly that it is script-only
until a forward source exists — the same honest gap D-107 recorded for a different
function.

---

## D-109 — Module 9's `carry_score` (same file, second function) (2026-09-26)

**Tier 5 = 11/23.** Module 18 is untouched at 5 of 6.

| function | module | file | spec | supersedes | status |
| --- | --- | --- | --- | --- | --- |
| `carry_score` | **9 — FX Carry / Parity** | `models/fx_carry.py` (**exists** — created at D-108) | `AGENTS.md:1027` (§6.7) | **nothing named** — Phase 0–4 had no carry model | **IMPLEMENTED** (D-109) |

**A thirteenth mapping rule — the second function in a file tests a DIFFERENT
property than the first, and it is the mapping's ANCHORS that are at risk.**
D-108's twelfth rule said a Tier-5 row whose file is absent is the mapping's most
informative state. This row is the complement: the file **exists**, the module
number was already resolved, and the mapping itself was a formality — **and yet
adding one function broke the sweep that maps the other.** Measured: two of
`mutation_fx_carry.py`'s anchors failed `check_targets` before the sweep would
run — one became **AMBIGUOUS** (the new input model opens its validator with the
same ``if not math.isfinite(value):`` line the old one does) and one went
**ABSENT** (it pinned a helper this increment renamed). **Both were fixed by
widening or following the anchor — D-055/D-060's remedy — and the gate caught
both rather than reporting them as survivors.** The mapping lesson is that **a
row's file and its module number are the cheap half of the mapping; the anchors
are the half that decays**, and only re-running the file's existing sweep
measures it.

**A fourteenth mapping rule — a MAPPING CAN CREATE A SECOND MAPPING, and the
second one is where the tests live.** `carry_score` maps to the same file as
`cip_check` but to a **different set of anchors, a different config leaf, a
different calibration helper and a different live check**. The single most
consequential mapping decision in this increment was therefore not
*"which file?"* — that was settled at D-108 — but **`_thresholds_are_calibrated`
was a GENERIC name mapping one function's confidence to one leaf**, and a second
function with its own threshold made it a lie. It is now
`_cip_bands_are_calibrated` (reading `fx_carry.notable_deviation_pct`) beside
`_carry_floor_is_calibrated` (reading `fx_carry.carry_vol_floor`) — the same
discipline `_r_squared_floor_is_calibrated`'s docstring states in
``models/econometrics.py``: **a helper is named for the leaf it reads, because a
generic name silently claims coverage of leaves added later.**

**The supersession map, updated (D-096):** `classify_regime_rule_based` →
`classify_regime_markov_switching` (D-105) · `historical_var` / `parametric_var` /
`expected_shortfall` → `monte_carlo_var` (D-106) · `cip_check` supersedes
**nothing named** (D-108) · **`carry_score` supersedes nothing named** — Phase 0–4
had no carry model either · `realized_vol_simple` → GARCH (outstanding, and now
also the cross-check partner for `carry_score`'s live volatility) · the
inverse-volatility weighting → `compute_risk_parity_weights` (**shipped at D-071,
Phase 4 — not outstanding**). **Ask what each entry replaces, never grep the list
for a keyword.**

**Reachability mapping.** `carry_score` also classifies as **SCRIPT-ONLY — Tier 5**
(its only caller is `scripts/live_carry_score_check.py`), so the Tier 1-4
unreachable baseline stays **58 = 58** and the Tier-5 script-only set grows from
9 to 10. Its `decision_relevance` names the intended consumer — Module 9's carry
read, paired with `cip_check`'s funding-stress read and the dollar-smile regime —
and states that it is script-only because no snapshot field carries a rate
differential or an FX realised volatility.

---

## D-110 — no new mapping; a mapping rule about RECOMMENDED GATES (2026-09-26)

**Tier 5 is unchanged at 11/23.** No function was added, moved, or promoted, and
**the sweep census is unchanged at 45** — this increment corrected the leftover
predicate *inside* every sweep's gate rather than adding one.

**A fifteenth mapping rule — a SUGGESTED GATE is a claim about what a gate would
CATCH, and an unmeasured one maps nothing.** This file and `OPEN_ISSUES.md`
carried, for three sessions, the recommendation that `tests/test_infrastructure.py`
should *"assert that every settings model is constructible from its own
`model_dump()`"* — offered as the remedy for the O-127 class, which has fired
**five times** (D-048, D-105 ×2, D-106, D-109). **Measured at D-110: it does not
work.** A valid `FxCarrySettings` round-trips through `model_dump()` →
`model_validate` **whether or not a test fixture elsewhere omits the new field**,
because `model_dump()` of an instance always carries every field. The breakage
lives in the **fixtures**, and a round-trip of a healthy instance cannot see them.

**Why this belongs in a mapping file.** A suggested gate is a claim of the form
*"this check would map the defect class to a failure"* — which is exactly the kind
of claim this file exists to keep honest. The proposed gate would have passed on a
healthy tree and on a broken one alike, so it would have mapped the class to
**nothing** while being cited as its remedy. **That is D-087.23's class — a wrong
instruction in the record — applied to a recommendation**, and it is worse than an
absent gate, because an absent gate is visibly absent whereas a false one
manufactures assurance. **The rule: a recommended gate is verified the way a
mutation is — by making it fire on the defect it names.** Until someone builds it
and watches it fail, it is a hypothesis with a citation count.

**The correct containment, and it is already mandatory** (so the class is
contained without the withdrawn gate): (i) **run the sweep's selection
GREEN-UNMUTATED first** — this is what caught D-105's collection error and D-109's
four broken constructions; (ii) **every guard test carries `match=`** on the field
it tests, so an unrelated `ValidationError` cannot satisfy it; (iii) **a negative
control per guard** — at D-109 the three `pytest.raises` guard tests **passed**
and only the control failed, which is the whole argument for having one.

**And the companion rule, from the same increment: a DISCLOSURE is not a
MEASUREMENT.** D-109's live check disclosed in prose that its euro-area leg is
monthly and stale — a real defect in the check, described honestly and left
unmeasured. D-110 turned it into a measurement: the check now runs the function
under **both** reachable foreign legs and asserts the read is robust to the choice
(`+0.205227` vs `+0.158000`, both `long_domestic`). **The direction is robust and
the level is not**, and that difference is now a printed number rather than a
sentence. **A caveat that can be converted into an assertion should be.**
