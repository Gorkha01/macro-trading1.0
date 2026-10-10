# Unwired Functions — Complete Inventory

**Generated:** 2026-10-08 · **Repo:** `C:/Users/Hp/Documents/macro-trading`  
**Question answered:** which functions exist but are never called by the shipped pipeline, why, and where each must be wired.

> **Completeness claim.** This list is generated from the two project tools, not from memory, and the  
> counts reconcile: `reachability_audit.py` (model-function reachability) and `call_graph_audit.py`  
> (structural call graph). Every function either tool reports as unwired appears below. If a function  
> is not here, it is not unwired.

---

## 0. How this was measured (reproducible)

```bash
uv run python tools/reachability_audit.py            # model functions vs the shipped pipeline
uv run python tools/call_graph_audit.py --summary    # every definition vs every other definition
uv run python tools/call_graph_audit.py --uncalled   # the per-function list
```

Two tools, because they answer different questions and each has a blind spot:

| Tool                    | Question                                                        | Scope                           |
| ----------------------- | --------------------------------------------------------------- | ------------------------------- |
| `reachability_audit.py` | Is this **model** function reachable from the shipped pipeline? | `models/`, curated entry points |
| `call_graph_audit.py`   | Is this definition called by **any other production code**?     | all of `src/macro_engine`       |

`reachability_audit.py` is the tighter and more honest figure for "is it wired into the product".  
`call_graph_audit.py` is broader but **over-reports** — it cannot see FastAPI's decorator  
registration, so every HTTP route handler shows as "uncalled" (see §5).

---

## 1. Headline numbers

| Measure                                              | Count                                                    |
| ---------------------------------------------------- | -------------------------------------------------------- |
| Model functions defined                              | **102**                                                  |
| Called from the shipped pipeline                     | **21**                                                   |
| Called only from `scripts/`/`tools/` live checks     | **57**                                                   |
| No caller anywhere                                   | **24**                                                   |
| **Tier 1-4 model functions with no pipeline caller** | **59**                                                   |
| Tier 5 (Phase 5+ — **COMPLETE**, unwired by design)  | **23**                                                   |
| Production modules parsed (call-graph)               | 71                                                       |
| Definitions in `src/macro_engine`                    | 995 (334 `@property`)                                    |
| Used by other production code                        | 697                                                      |
| **NOT used by production code**                      | **298** (193 public · 105 private · 99 test/script-only) |

**The number to remember is 59** — that is the wiring debt in Phases 0-3 scope. The **23 Tier 5 are  
BUILT** (Phase 5+ is complete — §4), **not deferred**; and the 298 is a broader structural measure  
that includes routes and private helpers.

---

## 2. The three buckets — and which are real debt

| Bucket                                               | Count    | Real debt?                                                     |
| ---------------------------------------------------- | -------- | -------------------------------------------------------------- |
| Tier 1-4 model functions, no pipeline caller         | **59**   | **Mostly YES** — §21.3 assigns them to Phases 0-3              |
| ↳ of which Phase 4+ **by endpoint** (risk/portfolio) | ~8       | **NO** — legitimately deferred                                 |
| ↳ of which genuine Phases 0-3 wiring debt            | **~51**  | **YES**                                                        |
| Tier 5 — Phase 5+ **COMPLETE**                       | **23**   | **NO** — built and tested; unwired by design                   |
| Phase 5+ capability gaps                             | **6**    | **YES** — but they are *missing work*, not unwired code (§4.1). Items 2, 3 are now CLOSED; item 6 is *built but unwired* — see §4.2.1 |
| Non-model unreachable modules                        | 30 of 78 | Mixed — see §5                                                 |

**Two different kinds of "not done" — do not conflate them:**

|                        | The 23 Tier-5 functions                       | The 6 capability gaps (§4.1) |
| ---------------------- | --------------------------------------------- | ---------------------------- |
| Exists in `src/`?      | **Yes** — real bodies                         | **Mostly NO** — one exception since 2026-10-10: the §22.5 reader, model and builder wiring ARE built (§4.2.1) |
| Tested / live-checked? | **Yes**                                       | n/a — except the §22.5 path, which is tested |
| Problem                | it exists and nothing calls it                | it does not exist yet — or, for §22.5, the reader accepts the curve but the live path does not yet *fetch* it |
| Fix                    | a product decision (changes published output) | **build it** — for §22.5, supply the curve on the live path |

### Why this is a gap and not a design choice

`docs/OPEN_ISSUES.md` **O-162** (OPEN since 2026-09-30) states it directly:

> **WHY THIS IS A GAP AND NOT A DESIGN CHOICE:** `AGENTS.md` §21.3 assigns these functions to  
> **Phases 0-3**, and the reachability tool's own footer says *"these are specified for Phases 0-3  
> and implemented, but the thesis never calls them. Either wire them or move them to a later phase  
> in AGENTS.md 21.3 — but do not leave them silently unreachable."*

Each unwired function **is live-checked against the OpenBB server**, so they compute correct  
numbers. They are simply never invoked when the service runs.

### Why nobody has fixed it yet

> **The decision is an operator call, not a code defect to fix blind** — wiring a model into the  
> thesis changes published output, so each needs its own increment. *(O-162)*

That is the real blocker: it is not difficulty, it is that **every wiring changes what `MacroThesis`  
publishes**, so the work cannot be batch-applied.

### The caveat that must not be lost

`historical_var`, `expected_shortfall`, `parametric_var`, `realized_vol_simple`,  
`portfolio_volatility_*` and `marginal_risk_contributions` are **Tier 1-2 in §21.3** (so the tool  
counts them) but **Phase 4+ by endpoint** (§1787, §9.2/9.3). **Counting them as wiring debt is  
wrong.** They are excluded from the "genuine debt" figure above.

---

## 3. THE PRIMARY LIST — 59 Tier 1-4 model functions with no pipeline caller

Grouped by module. **Reason codes:** `DEBT` = Phases 0-3 obligation, genuinely unwired ·  
`DEFER` = Phase 4+ by endpoint, legitimately deferred · `2ND` = second-order (unreachable only  
because its callers are).

### 3.1 `bond_math.py` — 6 functions (all Tier 1) — **DEBT**

The entire bond-pricing family. Nothing in the pipeline prices a bond.

| Function                      | Tier | Why unwired                                                  | Where it must be wired                                                         | What it adds                                                                                                                          |
| ----------------------------- | ---- | ------------------------------------------------------------ | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------- |
| `price_bond`                  | 1    | No caller; the thesis never prices a fixed-coupon instrument | `thesis_layer/builder.py::build_us_macro_thesis` — the instrument/sizing stage | A priced bond for the duration leg, so `MacroThesis` can express a rate view through a cash instrument rather than only a curve trade |
| `macaulay_duration`           | 1    | Same                                                         | via `price_bond` / `construct_duration_weighted_curve_trade`                   | The duration weight that `construct_duration_weighted_curve_trade` needs (it is Tier 4 and also unwired)                              |
| `modified_duration`           | 1    | Same                                                         | same                                                                           | The rate sensitivity used for position sizing                                                                                         |
| `convexity`                   | 1    | No caller anywhere                                           | same                                                                           | Second-order price sensitivity — the asymmetry input to sizing                                                                        |
| `price_change_with_convexity` | 1    | No caller anywhere                                           | same                                                                           | The actual P\&L estimate for a rate move; this is what a sized position needs                                                         |
| `repo_stress_check`           | 1    | No caller anywhere                                           | `portfolio/risk_budget.py` (financing stress)                                  | Flags a funding-stress regime, which should gate leverage                                                                             |

**Root cause:** the Tier 4 construction functions that would consume these  
(`construct_duration_weighted_curve_trade`, `construct_breakeven_trade`, `construct_cross_market_rv`)  
are themselves unwired — see §3.5. Bond math is a **subtree**, not six independent gaps.

### 3.2 `national_accounts.py` — 9 functions (Tier 1-3) — **DEBT**


Index-number arithmetic and the accounting identities. Nothing in the pipeline uses them.

| Function                            | Tier | Why unwired                      | Where it must be wired                                | What it adds                                                                                       |
| ----------------------------------- | ---- | -------------------------------- | ----------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `gdp_deflator`                      | 1    | No caller anywhere               | `api_layer/orchestration.py` (GDP leg)                | The deflator that turns nominal growth into real growth — currently only `gdp_nowcast` is consumed |
| `fisher_index`                      | 1    | No caller anywhere               | `national_accounts` index family → GDP/inflation view | A symmetric price index (geometric mean), the theoretically preferred form                         |
| `laspeyres_index`                   | 1    | No caller anywhere               | same                                                  | The base-weighted index — the CPI/PPI convention, needed to reconcile against published CPI        |
| `paasche_index`                     | 1    | No caller anywhere               | same                                                  | The current-weighted index; Laspeyres vs Paasche brackets the true index                           |
| `savings_investment_identity`       | 1    | No caller anywhere               | `api_layer/orchestration.py`                          | The S=I accounting check — a consistency guard on the national accounts                            |
| `quantity_theory_implied_inflation` | 1    | No caller anywhere               | inflation view                                        | An independent MV=PY inflation estimate to cross-check the nowcast                                 |
| `openings_to_unemployed_ratio`      | 1    | No caller anywhere               | `labor_synthesis` → labor view                        | A labor-slack measure the Beveridge curve needs                                                    |
| `minsky_composition_drift`          | 2    | Live-checked, no pipeline caller | `portfolio/risk_budget.py`                            | Flags financing-composition drift — a fragility signal                                             |
| `policy_mix_classifier`             | 2    | Live-checked, no pipeline caller | `thesis_layer/builder.py` (policy view)               | Classifies the fiscal/monetary mix — currently the thesis sees only the monetary rule ensemble     |

**Root cause:** `national_accounts` is one of the 18 model modules that is **not reachable** from  
the entry point at all (O-162, module level).

### 3.3 `labor_synthesis.py` — 7 functions (Tier 2) — **DEBT (deepest: module IS wired)**

⚠️ **This module is wired** — the pipeline calls `labor_tightness_score`. But 7 of its other  
functions have no caller. Module-level reachability ≠ function-level wiring.

| Function                     | Tier | Why unwired                                         | Where it must be wired                                     | What it adds                                                                                |
| ---------------------------- | ---- | --------------------------------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `claims_corroboration`       | 2    | No caller; only `labor_tightness_score` is consumed | `labor_synthesis` composite → `orchestration.py` labor leg | Cross-checks the claims series against payrolls — the corroboration the module is named for |
| `claims_trend_signal`        | 2    | Same                                                | same                                                       | The trend read of initial claims                                                            |
| `nfp_revision_adjusted_read` | 2    | Same                                                | same                                                       | Revision-adjusted payrolls — the read the spec asks for                                     |
| `ahe_composition_flag`       | 2    | Same                                                | same                                                       | Flags whether wage growth is composition-driven                                             |
| `beveridge_curve_position`   | 2    | Same                                                | same                                                       | Where the economy sits on the Beveridge curve                                               |
| `two_survey_divergence`      | 2    | Same                                                | same                                                       | Household vs establishment survey divergence                                                |
| `beveridge_shift_tolerance`  | ?    | No caller anywhere                                  | same                                                       | Tolerance band for the Beveridge shift                                                      |

### 3.4 `yield_curve.py` — 5 functions — **DEBT**

| Function                                  | Tier | Why unwired                      | Where it must be wired                 | What it adds                                                              |
| ----------------------------------------- | ---- | -------------------------------- | -------------------------------------- | ------------------------------------------------------------------------- |
| `decompose_yield`                         | 1    | No caller anywhere               | `thesis_layer/builder.py` (curve view) | Level/slope/curvature decomposition — the spec's own Module 8 requirement |
| `inversion_probability_adjustment`        | 3    | Live-checked, no pipeline caller | `builder.py` (probability stage)       | Adjusts scenario probabilities for curve inversion                        |
| `construct_duration_weighted_curve_trade` | 4    | Live-checked, no pipeline caller | `builder.py` (instrument stage)        | The duration-neutral curve trade expression                               |
| `construct_breakeven_trade`               | 4    | Live-checked, no pipeline caller | same                                   | The breakeven trade expression                                            |
| `construct_cross_market_rv`               | 4    | Live-checked, no pipeline caller | same                                   | The cross-market relative-value expression                                |

### 3.5 `risk.py` — 8 functions — **DEFER (Phase 4+ by endpoint)**

**These are NOT wiring debt.** §1787 assigns the Risk/Portfolio suite the endpoint `(Phase 4+)`, and  
§9.2/9.3 defer `compute_risk_parity_weights` / `translate_thesis_to_position` to Phase 4. They are  
Tier 1-2 in §21.3, which is why the tool counts them — but counting them as debt would be wrong.

| Function                         | Tier | Why unwired          | Where it will be wired                               |
| -------------------------------- | ---- | -------------------- | ---------------------------------------------------- |
| `historical_var`                 | 1    | Phase 4+ by endpoint | `portfolio/risk_budget.py` when the risk suite lands |
| `expected_shortfall`             | 1    | Phase 4+ by endpoint | same                                                 |
| `parametric_var`                 | 1    | Phase 4+ by endpoint | same                                                 |
| `realized_vol_simple`            | 1    | Phase 4+ by endpoint | same                                                 |
| `portfolio_volatility_two_asset` | 1    | Phase 4+ by endpoint | same                                                 |
| `portfolio_volatility_n_asset`   | 1    | Phase 4+ by endpoint | same                                                 |
| `marginal_risk_contributions`    | 2    | Phase 4+ by endpoint | same                                                 |
| `z_score_for_confidence`         | ?    | No caller anywhere   | same                                                 |

⚠️ **`realized_vol_simple` is worth a second look** — `config.py:1018` says its value "must agree  
with `realized_vol_simple` and with the vol-target" convention, so the vol-target path references a  
function nothing calls. Worth checking whether that agreement is actually asserted.

### 3.6 `production_function.py` — 2 (Tier 2) — **DEBT**

| Function                          | Tier | Why unwired                      | Where it must be wired                 | What it adds                                                                              |
| --------------------------------- | ---- | -------------------------------- | -------------------------------------- | ----------------------------------------------------------------------------------------- |
| `potential_gdp_cobb_douglas`      | 2    | Live-checked, no pipeline caller | `api_layer/orchestration.py` (GDP leg) | Potential output — the denominator of the output gap; without it `output_gap` is unusable |
| `growth_accounting_decomposition` | 2    | Live-checked, no pipeline caller | same                                   | Splits growth into capital/labor/TFP — the supply-side read                               |

### 3.7 `gdp_nowcast.py` — 2 (Tier 1-2) — **DEBT (module IS wired)**

| Function             | Tier | Why unwired                      | Where it must be wired     | What it adds                                                                           |
| -------------------- | ---- | -------------------------------- | -------------------------- | -------------------------------------------------------------------------------------- |
| `output_gap`         | 1    | Live-checked, no pipeline caller | `orchestration.py` GDP leg | Actual vs potential — blocked in practice on `potential_gdp_cobb_douglas`              |
| `simple_gdp_nowcast` | 2    | Live-checked, no pipeline caller | same                       | The spec's Phase 1 "simple GDP nowcast"; `gdp_gdi_divergence` is wired but this is not |


### 3.8 `probability.py` — 2 (Tier 2) — **DEBT**

| Function          | Tier | Why unwired                      | Where it must be wired                        | What it adds                                            |
| ----------------- | ---- | -------------------------------- | --------------------------------------------- | ------------------------------------------------------- |
| `bayesian_update` | 2    | Live-checked, no pipeline caller | `thesis_layer/builder.py` (probability stage) | Bayesian thesis updating — §1.3 lists it as designed-in |
| `expected_value`  | 2    | Live-checked, no pipeline caller | same                                          | EV of the trade — the payoff-asymmetry input to sizing  |

### 3.9 `inflation_dynamics.py` — 2 — **DEBT**

| Function                   | Tier | Why unwired                      | Where it must be wired             | What it adds                        |
| -------------------------- | ---- | -------------------------------- | ---------------------------------- | ----------------------------------- |
| `phillips_curve_inflation` | 2    | Live-checked, no pipeline caller | inflation view                     | The Phillips-curve inflation read   |
| `cross_asset_transmission` | 3    | Live-checked, no pipeline caller | `builder.py` (regime/transmission) | How a shock transmits across assets |

### 3.10 `evidence.py` — 2 (Tier 3) — **DEBT**

| Function                     | Tier | Why unwired        | Where it must be wired                                                                                    | What it adds                                                     |
| ---------------------------- | ---- | ------------------ | --------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| `count_independent_families` | 3    | No caller anywhere | `builder.py` — **note `convergence.py:34` already calls it internally**, so this is a duplicate-name risk | The independence count the confidence ceiling depends on         |
| `tag_evidence_source`        | 3    | No caller anywhere | `builder.py` (evidence tagging)                                                                           | Tags each read with its source family — the §15.19-D requirement |

### 3.11 `as_of.py` — 2 — **DEBT**

| Function                   | Tier | Why unwired        | Where it must be wired            | What it adds                                                                           |
| -------------------------- | ---- | ------------------ | --------------------------------- | -------------------------------------------------------------------------------------- |
| `latest_observation`       | ?    | No caller anywhere | `data_layer` point-in-time filter | The most recent observation as of a date                                               |
| `observation_on_or_before` | ?    | No caller anywhere | same                              | The point-in-time lookup — **§6's look-ahead guard depends on this class of function** |

⚠️ **These two are the highest-risk entries on this list.** §6's point-in-time filter is what stops  
a backtest reading data from the future (`release_calendar.py`'s own docstring calls the gap "not  
cosmetic"). A point-in-time helper with no caller is worth understanding before anything else.

### 3.12 Remaining 12 modules — 1 each — **mostly DEBT**

| Module                     | Function                           | Tier | Why unwired                                                                                                 | Where it must be wired                                  |
| -------------------------- | ---------------------------------- | ---- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| `auctions.py`              | `auction_demand_signal`            | 2    | Live-checked only                                                                                           | `orchestration.py` (fiscal leg)                         |
| `credit_spread.py`         | `credit_spread_attribution`        | 2    | Live-checked only                                                                                           | `builder.py` (financial-conditions view)                |
| `financial_conditions.py`  | `compute_fci`                      | 2    | Live-checked only; **blocked** — O-162 notes the FCI is blocked on three series no reachable route supplies | `builder.py` (financial-conditions view)                |
| `scorecard.py`             | `four_pillar_scorecard`            | 3    | Live-checked only                                                                                           | `builder.py` — the four-pillar convergence gate         |
| `inflation_convergence.py` | `inflation_convergence_classifier` | 3    | Live-checked only                                                                                           | `builder.py` (inflation view)                           |
| `lei_proxy.py`             | `leading_indicator_proxy`          | ?    | Live-checked only                                                                                           | `builder.py` (growth view)                              |
| `ppi_pipeline.py`          | `ppi_pipeline_signal`              | 2    | Live-checked only                                                                                           | inflation view                                          |
| `inflation_trajectory.py`  | `project_inflation_trajectory`     | 3    | Live-checked only                                                                                           | `builder.py` (probability stage)                        |
| `inflation_nowcast.py`     | `project_shelter_cpi`              | 2    | Live-checked only                                                                                           | inflation view                                          |
| `real_policy_rate.py`      | `real_policy_rate`                 | ?    | No caller anywhere                                                                                          | `builder.py` (policy view)                              |
| `regime.py`                | `check_trilemma_tension`           | 3    | Live-checked only                                                                                           | `builder.py` (regime view)                              |
| `contracts.py`             | `require_finite_scalars`           | ?    | **2ND** — every caller is itself unwired (§3.1, §3.2, §3.6)                                                 | n/a — resolves automatically when its callers are wired |

---

## 4. Tier 5 — 23 functions — **BUILT (Phase 5+ COMPLETE), unwired by design — NOT debt**

**Phase 5+ is DONE, not pending.** `AGENTS.md` §21.3 lists these as **Tier 5 — Phase 5+**, and the  
project records them as  
**23/23 COMPLETE** (D-092 … D-125): every name has a real `def` with a real body — measured  
2026-10-08, **none of the 23 raises `NotImplementedError`**. The section's old heading, *"stubs only  
until their phase"*, was corrected on 2026-10-08 because it no longer described the shipped tree.  
They are unwired **by design**: Phase 5+ built the *sophisticated* version of each item while Phases  
0-4 shipped the *simple* one, and an upgrade pass **deletes nothing** — so both versions exist and  
only the simple one is called. **Do not wire them; do not count them as debt.**

`cip_check` · `uip_expected_move` · `ppp_valuation` · `carry_score` · `dollar_smile_regime` ·  
`intervention_capacity` · `em_vulnerability_checklist` · `oil_balance_signal` ·  
`gold_driver_attribution` · `metals_complex_divergence` · `sector_rotation_prior` ·  
`duration_sensitivity` · `factor_tilt_prior` · `monte_carlo_var` · `compute_risk_parity_weights` ·  
`classify_regime_markov_switching` · `yield_curve_pca` · `run_regression` · `test_stationarity` ·  
`test_cointegration` · `compute_pca` · `kalman_latent_state` · `statement_text_diff`

**Caveat on the count:** the tool reports 22 as "Tier 5"; §21.3's own list above contains **23**  
names. The discrepancy is one function the tool classifies as Tier 1-4 (`oil_balance_signal` appears  
as a Tier-5 orphan in the tool's output). **23 is authoritative** (§21.3's table, and only that  
table, governs — §22.1).

### 4.1 What is *genuinely* outstanding in Phase 5+ — 6 items, none of them these 23

Tier 5 being complete does **not** mean Phase 5+ has nothing left. Six things remain, and **none of  
them is a Tier-5 function**. Authority: `docs/PHASE5_DEFERRED.md` §2, plus item 6 (found 2026-10-08  
by reading §22.5 against the shipped body, and **re-measured 2026-10-10** — see §4.2).

Two of the six are now closed (items 2 and 3) and item 6's blocked-on has changed; the count of six
is kept because the six *slots* are still the register, and a closed slot is struck through rather
than deleted.

| # | Outstanding item                                                | Why                                                         | Blocked on                                                                                    |
| - | --------------------------------------------------------------- | ----------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| 1 | **`extensions/` — 6 modules**                                   | deliberate stubs (`raise NotImplementedError`)              | an uninstalled §4 package, one per module                                                     |
| 2 | ~~**GARCH-family conditional volatility**~~ | **CLOSED 2026-10-09** — `models/volatility.py` built, `arch` added | — |
| 3 | ~~**Crisis-scenario shock engine**~~                            | **CLOSED 2026-10-09** — engine, simulation half and all four §9.4 scenarios ship | — |
| 4 | **Multi-country (`de`, `jp`, `gb`)**                            | not implemented                                             | per country: its own data registry, **its own reaction function**, and its own instrument set |
| 5 | **Market/price data coverage** (incl. FX forwards)              | partially implemented                                       | **source availability**, not code — EXCEPT the §22.5 path, where a source WAS found (item 6)     |
| 6 | **`derive_market_implied_policy_path` — the §22.5 replacement** | **Partially DONE — source EXISTS, reader+model built, the live SUPPLY remains** | supplying a curve on the live path (a `OpenBBClient`-routed fetch), not the spec (see §4.2.1) |

**Corrected 2026-10-10 (pass two).** Item 6's blocked-on said *"nothing — it is simply unbuilt"*, and an
intermediate revision said the source *"needs data"*. Both were wrong. The data exists (item 6's source
was found — see §4.2.1), and pass one then said the block was the specification's *mechanism* — which was
also wrong: the promised *mechanism* (a pure body swap) is unusable, but the promised *outcome* is
achievable **additively**, and the reader + builder chain now do it. What remains is the live-path
*fetch*. Item 5's *"source availability, not code"* has one exception and is annotated accordingly.


### 4.2 ⚠️ The sixth item — the obligation that fell between two lists

**Every list missed this one, including the first version of this document.** It is recorded  
separately because its *shape* is the finding.

`AGENTS.md` **§22.5** obligates, in the spec's own words:

> *"**Phase 5+ REPLACES this entirely** with a real Fed-funds-futures-implied probability  
> distribution (Section 4/16's original intent) — this function's signature is stable so that  
> replacement is a body swap, not a caller-facing breaking change."*


**Phase 5+ is recorded COMPLETE (23/23) and the body was never swapped.**  
`derive_market_implied_policy_path` still returns `short_yield - short_tenor_term_premium`, and its  
warnings still say so — search for the exact prose rather than a line number, which drifts on every  
edit above it:

```bash
grep -n "Phase 5+ replaces this entirely" src/macro_engine/models/policy_rules.py
```

**Why no gate caught it:** the obligation is attached to a **Tier 3** function (`AGENTS.md:5531`),  
but the Phase-5+ work list was built from §21.3's **Tier 5** names. **The obligation fell between two  
lists and nothing owned it.** So "Tier 5 = 23/23" is true and does **not** mean Phase 5+ is complete.

**Why it outranks the other five:** `derive_market_implied_policy_path` is **the reference the entire  
gap is measured against.** `canonical_policy_gap` computes  
`raw_gap = model_implied − market_implied`, so **every thesis's gap inherits its error.** It is not a  
leaf — it is the fulcrum. Its confidence is **0.4** (`config/settings.yaml:165`,  
`uncalibrated_illustrative`), and that config note says of itself: *"Explicitly lower than a real  
futures-implied distribution would earn."*

**The macro error it leaves in place — a horizon mismatch:**

|                  | What it is                              | Horizon                                        |
| ---------------- | --------------------------------------- | ---------------------------------------------- |
| `model_implied`  | median of the three rules' prescription | **spot** — "what the rate should be now"       |
| `market_implied` | 2y yield − ACM term premium             | **average** expected policy **over two years** |

Subtracting a spot number from a two-year average is apples-to-oranges. Taylor says 5% and the  
2y-implied says 4% does **not** mean "the market is 100bp too dovish" — the market may expect 5% for a  
year and then 3%. **The path SHAPE is exactly what is lost**, and that is precisely what a  
futures-implied *distribution* restores: it yields a path, so the horizons can be aligned. The  
horizon mismatch is not a separate bug — it is **why §22.5 wanted the replacement.**

**What the system does well, and should not lose in the fix:** `canonical_policy_gap`'s noise-floor  
test — `is_meaningful = abs(gap) > dispersion`, the max-min spread of the three rules — is the  
strongest idea in this subsystem. *"Three rules differing by 80bp cannot support a claim about a  
50bp gap."* A replacement must preserve it.

### 4.2.1 ⚠️ MEASURED 2026-10-10 (two passes) — the source EXISTS; the swap is impossible, the change is not

**Two earlier claims in this document were wrong, and both are corrected here. A third claim — made in
the first version of this subsection — was ALSO wrong and is corrected in pass two.**

**(a) "It needs data" was false.** The source is `derivatives.futures.curve` with `symbol="ZQ"` and
`provider="yfinance"`, and it returns the 30-Day Fed Funds futures term structure. It was missed
because the D-108 route inventory was grepped for `forward|swap|basis` and **never for `futur`** —
the same false-block class this repository has now caught six times. Verified three ways: the front
contract (2026-10) implies **3.88%**, EQUAL to the measured `DFF` and `EFFR` (both 3.880) and inside
the 3.75–4.00% `DFEDTARL`/`DFEDTARU` range.

**Re-measure it:**
```bash
uv run python tools/probe_fed_funds_futures.py
# 16 expirations; front 3.88%; slope +80bp out to 2028-01
# SOURCE DEFECT: 6 of 16 carry a price near 47-48 → ~52% implied, deterministic (min 47.64, max 96.12)
```

**(b) A pure BODY SWAP is impossible — but the change is strictly ADDITIVE, and the first pass's
conclusion "therefore blocked" was wrong.** This distinction is the whole finding, so both halves are
stated. A futures curve is a **collection of expirations**; the proxy's original signature carried two
**scalars**:

```bash
uv run python -c "
import inspect
from macro_engine.models.policy_rules import (
    derive_market_implied_policy_path, futures_implied_policy_path)
print(list(inspect.signature(derive_market_implied_policy_path).parameters))
# ['short_yield', 'short_tenor_term_premium', 'futures_curve']   <- two scalars + an OPTIONAL curve
print(list(inspect.signature(futures_implied_policy_path).parameters))
# ['curve', 'proxy_horizon_months']                             <- a CURVE
"
```

* **The promised MECHANISM cannot be used.** No body can carry a curve through a two-float signature
  without reconstructing it from the scalars, which §21.0 rule 3 forbids. So §22.5's *"a body swap"* is
  unachievable as literally written.
* **But the change need not be BREAKING.** `futures_curve` is **keyword-only with a `None` default**, so
  every pre-existing call site keeps working unchanged. §22.5 promised the outcome — *"not a
  caller-facing breaking change"* — and that outcome **is** achievable; only its stated mechanism is
  not.

**Pass one mistook "impossible by the promised mechanism" for "impossible".** It read §22.5's *"body
swap"* as the *only* permitted change and concluded the obligation was blocked on the spec. Measured,
the replacement is dischargeable by an additive change, and this version does it.

**What is BUILT and TESTED, and what remains:**

| Piece | State |
|---|---|
| `data_layer/fed_funds_futures_client.py` | **BUILT.** Reads the curve; the six ~52% rows are **REJECTED and named**, never clamped. Tests: `tests/data_layer/test_fed_funds_futures_client.py` |
| `models/policy_rules.futures_implied_policy_path` | **BUILT.** Publishes the NEAR rate (not the path mean, which would rebuild the horizon mismatch in reverse) and reports the slope. Tests: `tests/models/test_policy_rules.py` |
| The reader's preference | **BUILT.** `derive_market_implied_policy_path(curve=…)` prefers the futures branch and keeps the proxy byte-for-byte when the curve is `None`. The extension is additive, so no caller breaks. Pinned by `test_the_reader_prefers_the_futures_branch_when_a_curve_is_supplied`. |
| The builder chain | **BUILT.** `build_policy_gap(..., futures_curve=…)` and `build_us_macro_thesis(..., futures_curve=…)` thread an optional curve to the market leg. Pinned by `test_build_policy_gap_threads_the_futures_curve_to_the_market_leg`. |
| **Supplying a curve on the LIVE path** | **NOT DONE — this is the remaining step.** `_reasoning_frames` (`api_layer/`) must **fetch** a curve and pass it down. That is a network read that must route through `OpenBBClient` (D-087.25) and is an explicit operator decision, not a silent default inside a builder. Until it is done, the proxy branch is what production runs. |
| `PHASE5_REPLACEMENT_OBLIGATION` | **still `"outstanding"`, correctly.** The reader and model accept a curve, but nothing SUPPLIES one live. Flipping the marker now would claim a live-path replacement that has not happened. The tripwire fires the moment the chain is wired without updating the record. |


### 4.3 Status of the three defects — ADDRESSED 2026-10-08

| #      | Defect                                  | Fix applied                                                                                                                                                                                                                                                                                                                        | Proof                                                                                                                      |
| ------ | --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| **D1** | horizon mismatch, undisclosed           | The horizon is now a **config leaf** (`policy.market_implied.proxy_horizon_months`), published in the market result's **`warnings`** (the only field `collect_all_warnings` reads), in its `context`, and in the **gap's own `interpretation`**. The pre-fix caveat sat in `assumptions` — which the thesis never collects.        | 4 tests + mutation proof (removing the warning FAILS the test)                                                             |
| **D2** | §22.5 obligation unowned                | `PHASE5_REPLACEMENT_OBLIGATION` marker + a **tripwire test** asserting BOTH that the body is still the proxy AND that the marker says so. Discharging the obligation now FAILS the suite until the record is updated in the same change.                                                                                           | tripwire + mutation proof (marker→`discharged` FAILS)                                                                      |
| **D3** | spot fields declared but never assigned | `SnapshotBuildReport.declared_not_wired` + a **`DECLARED_NOT_WIRED:<field>` data-quality flag**. An empty mapping is now distinguishable from "no data this run". Deliberately does **not** make a build report itself incomplete — the *declaration* is by design (D-137), the *absence of wiring* is what had to become visible. | 3 tests, incl. one that calls the **real builder** (an earlier version of that test passed against the mutant — see below) |

**A note on the D3 test, because it nearly shipped weak.** The first version built a  
`SnapshotBuildReport` by hand and checked `as_flags` — which stays GREEN even if `build_snapshot`  
never populates the field. Measured: replacing the population with `declared_not_wired = []` left it  
passing. The test now calls the real builder with an injected no-network client, so it fails on the  
**assertion** rather than on an escaping exception. *A test that exercises the renderer is not a test  
of the producer.*

**On the D-137 vs `PHASE5_DEFERRED.md` contradiction:** both readings are satisfied. D-137 is right  
that the fields are deliberate Tier-5 placeholders, so they must **not** make a build report itself  
incomplete. `PHASE5_DEFERRED.md` §2.5.1 is right that the omission must be visible. The fix does  
both: report the absence, do not cry failure on a state the project chose.

**Still open:** D2's *substance* — the actual Fed-funds-futures-implied replacement — needs a futures  
source (and, per §2.5, FX/rates market data is partly source-blocked). What is fixed is that the  
obligation can no longer be lost silently.

---

## 5. Non-model unreachable modules — 30 of 78

From O-162, module level. The four package `__init__` files are **benign** (their submodules are  
reached directly).

| Group                  | Modules                                                                                                                                                                                                                                                                                                                           | Verdict                                                               |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `models/` (20)         | `auctions`, `bond_math`, `commodities`, `credit_spread`, `em_vulnerability`, `equity_macro`, `financial_conditions`, `fx_carry`, `inflation_dynamics`, `inflation_nowcast`, `inflation_trajectory`, `intervention`, `lei_proxy`, `national_accounts`, `ppi_pipeline`, `production_function`, `real_policy_rate`, `scorecard` (+2) | **DEBT** — Phases 0-3 obligations                                     |
| Data-layer clients     | `data_layer.commodities_client`, `data_layer.reserves_client`, `data_layer.world_bank_client`                                                                                                                                                                                                                                     | **DEBT/blocked** — data discovery, some blocked on unavailable series |
| Ops modules            | `audit`, `deployment`, `settings_store`                                                                                                                                                                                                                                                                                           | **Partial** — `audit` has 8 uncalled methods; `settings_store` 10     |
| `extensions.*` (6)     | `backtest_vbt`, `bayesian_updater`, `duckdb_store`, `nautilus_adapter`, `scheduler`, `mlflow_tracking`                                                                                                                                                                                                                            | **DEFER** — Tier 5 by design (§1.3)                                   |
| Package `__init__` (4) | `models`, `portfolio`, `thesis_layer`, `extensions`                                                                                                                                                                                                                                                                               | **Benign** — submodules reached directly                              |

---

## 6. Structural: 298 definitions not called by production code

`call_graph_audit.py --uncalled`. **This bucket over-reports** — read the caveats before acting.

| Category                       | Count | Is it a problem?                                                    |
| ------------------------------ | ----- | ------------------------------------------------------------------- |
| Public, **test/script-only**   | 99    | Mixed — mostly the §3 model functions                               |
| Public, **no caller anywhere** | 94    | Mixed — includes the API route handlers                             |
| Private (`_`), uncalled        | 105   | Usually fine — helpers used only by their own module's tested paths |

### ⚠️ Known false positives — do not "fix" these

**Every HTTP route handler appears as uncalled**, because FastAPI registers them via decorator and  
the tool does not model that:

`stream_thesis_reasoning` · `dashboard_data` · `health` · `query` · `get_thesis` — all five are  
**wired** (they are the service's endpoints).

### Largest uncalled groups by module

| Module                           | Count | Note                                                         |
| -------------------------------- | ----- | ------------------------------------------------------------ |
| `config`                         | 23    | `NO CALLER ANYWHERE` — accessors whose consumers are unwired |
| `settings_store`                 | 10    | Ops surface                                                  |
| `models.national_accounts`       | 9     | §3.2                                                         |
| `audit`                          | 8     | Ops surface                                                  |
| `data_layer.validation`          | 8     | 5 no-caller, 3 test-only                                     |
| `models.econometrics`            | 8     | 4 no-caller, 4 test-only                                     |
| `models.risk`                    | 8     | §3.5 — **DEFER, not debt**                                   |
| `models.bond_math`               | 6     | §3.1                                                         |
| `models.labor_synthesis`         | 6     | §3.3                                                         |
| `models.yield_curve`             | 6     | §3.4                                                         |
| `deployment`                     | 5     | Ops surface                                                  |
| `models.fx_carry`                | 5     | Tier 5 by design                                             |
| `portfolio.risk_budget`          | 4     | Phase 4+                                                     |
| *(41 further modules, 1-4 each)* | 90    | See `.review-probe/callgraph_uncalled.txt` for the full list |


The full per-function list is reproducible with  
`uv run python tools/call_graph_audit.py --uncalled`.

---

## 7. THE WIRING MAP — where unwired functions belong

There are only **two pipeline entry points**. Every wiring is an import + a call added to one of  
them.

| Entry point                                                 | Currently consumes                                                                                                                     |
| ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `thesis_layer/builder.py::build_us_macro_thesis` (line 753) | `contracts`, `convergence`, `instrument_selection`, `policy_rules`, `probability`, `portfolio.risk_budget`, + 6 `thesis_layer` modules |
| `api_layer/orchestration.py`                                | `as_of`, `contracts`, `gdp_nowcast`, `instrument_selection`, `labor_synthesis`, `policy_rules`, `regime`, `yield_curve`                |

### Target stages, and what each unlocks

| Target stage                                      | Wires                                                                                                                                                                | Unlocks                                                                                                                           |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| **GDP / supply leg** (`orchestration.py`)         | `potential_gdp_cobb_douglas`, `growth_accounting_decomposition`, `output_gap`, `simple_gdp_nowcast`, `gdp_deflator`, `savings_investment_identity`, index family (5) | A real GDP view — today only `gdp_nowcast`/`gdp_gdi_divergence` are consumed, so `output_gap` has no potential-output denominator |
| **Labor leg** (`orchestration.py`)                | the 7 `labor_synthesis` functions                                                                                                                                    | The corroboration/divergence reads the module is named for                                                                        |
| **Inflation leg**                                 | `phillips_curve_inflation`, `project_shelter_cpi`, `ppi_pipeline_signal`, `project_inflation_trajectory`, `inflation_convergence_classifier`                         | A multi-measure inflation view                                                                                                    |
| **Policy leg** (`builder.py`)                     | `policy_mix_classifier`, `real_policy_rate`, `check_trilemma_tension`                                                                                                | Fiscal/monetary mix and real-rate context                                                                                         |
| **Financial-conditions leg** (`builder.py`)       | `compute_fci` (**blocked on data**), `credit_spread_attribution`, `minsky_composition_drift`, `leading_indicator_proxy`                                              | A conditions/fragility read                                                                                                       |
| **Probability stage** (`builder.py`)              | `bayesian_update`, `expected_value`, `inversion_probability_adjustment`                                                                                              | Bayesian updating + EV-based sizing                                                                                               |
| **Curve / instrument stage** (`builder.py`)       | `decompose_yield`, `construct_*` (3), bond math (6)                                                                                                                  | The Tier 4 trade-construction layer — the largest single unlock                                                                   |
| **Evidence stage** (`builder.py`)                 | `tag_evidence_source`, `count_independent_families`, `four_pillar_scorecard`                                                                                         | §15.19-D family census + the convergence gate                                                                                     |
| **Point-in-time** (`data_layer`)                  | `latest_observation`, `observation_on_or_before`                                                                                                                     | **§6's look-ahead guard**                                                                                                         |
| **Risk / portfolio** (`portfolio/risk_budget.py`) | `risk.py` suite, `repo_stress_check`                                                                                                                                 | **Phase 4+ — do not wire yet**                                                                                                    |

---

## 8. Recommended order, and how to keep this list honest

### Order (by user-visible value per unit of risk)

1. **Point-in-time helpers** (`latest_observation`, `observation_on_or_before`) — smallest change,  
   and §6's look-ahead guard is the one correctness concern on this list.
2. **Curve / instrument stage** — `decompose_yield` + the 3 `construct_*` + bond math. This is the  
   Tier 4 layer `MacroThesis` already has a slot for; it turns a rate *view* into a *trade*.
3. **GDP / supply leg** — unlocks `output_gap`, which is currently unusable.
4. **Labor leg** — the module is already wired, so the marginal cost is lowest here.
5. **Evidence stage** — `four_pillar_scorecard` + the family census.
6. Everything else.

### Do NOT wire

- **Tier 5 (§4)** — **BUILT, not deferred.** Phase 5+ is complete (23/23, D-092 … D-125); these are  
  the *sophisticated* versions that sit beside the simple ones the pipeline calls. Wiring them is a  
  product decision that changes published output, not a debt repayment.
- **`risk.py` (§3.5)** — Phase 4+ by endpoint. O-162 explicitly warns that treating these as debt is wrong.

### DO work on — the genuinely-outstanding Phase 5+ items (§4.1)

`extensions/` (6 stubs) · multi-country · market/price data coverage (FX forwards) ·
**the §22.5 `derive_market_implied_policy_path` replacement (§4.2)**. **None is a Tier-5
function** — they are capability gaps, and they are the real Phase-5 remainder.
**GARCH and the whole crisis-shock engine closed 2026-10-09** — `docs/PHASE5_DEFERRED.md` §2.2 and
§2.3.

⚠️ **On §22.5, re-measured 2026-10-10 (pass two) (§4.2.1): the CODE is done; what remains is to SUPPLY
a curve live.** The reader (`derive_market_implied_policy_path`) now accepts an optional curve and
prefers the futures branch; `build_policy_gap` and `build_us_macro_thesis` thread it. The extension is
**additive** (keyword-only, `None` default), so §22.5's promised *outcome* — *"not a caller-facing
breaking change"* — holds. Only its stated *mechanism* (a pure body swap) does not, and pass one's
"therefore blocked on the spec" was wrong. The last step is a live **fetch** of the curve on the
reasoning path (`_reasoning_frames`), which must route through `OpenBBClient` (D-087.25) and is an
operator decision. Until then the proxy branch runs and the marker stays `"outstanding"`.
**All the same, read §4.2 first:** the proxy is the reference every thesis's gap is measured against.

### How to keep this honest

| Guard                                          | Status                                                                                                                                                                                                                                             |
| ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tools/reachability_audit.py --check-baseline` | **Currently RED** — reports 59 vs a baseline of 58. The extra entry is `require_finite_scalars`, which is **2ND** (§3.12) and needs no code change; the baseline simply lacks an entry. Regenerate with `--write-baseline` to record the decision. |
| `tools/call_graph_audit.py --check-baseline`   | Pins the 298 unused definitions so the count cannot drift. **NOT in CI.**                                                                                                                                                                          |
| CI enforcement of either                       | **None** — both gates are local-only today.                                                                                                                                                                                                        |

### The standing rule this list exists to enforce

> *"Either wire them or move them to a later phase in AGENTS.md 21.3 — but do not leave them  
> silently unreachable."*

Every function in §3 is, today, silently unreachable.

---

## 9. Cross-references

| Source                                 | What it holds                                                 |
| -------------------------------------- | ------------------------------------------------------------- |
| `docs/OPEN_ISSUES.md` **O-162**        | The full finding, method, and the operator-call conclusion    |
| `AGENTS.md` §21.3                      | The authoritative five-tier phase assignment                  |
| `AGENTS.md` §21.4                      | The 14 BLOCKED items — what the system is allowed not to know |
| `config/reachability_baseline.txt`     | The 58 known-unreachable Tier 1-4 functions                   |
| `tools/call_graph_baseline.txt`        | The 290 pinned unused definitions                             |
| `.review-probe/reach_audit_full.txt`   | Raw audit output used to build §3                             |
| `.review-probe/callgraph_uncalled.txt` | Raw per-function list for §6                                  |

---


## APPENDIX A — EVERY uncalled definition (all 298, by name)

`tools/call_graph_audit.py` prints only the **193 public** uncalled under `--uncalled`; the **105  
private** helpers are counted in `--summary` but never listed. Both are enumerated below by calling  
the tool's own `build()` / `is_used()` — the tool's import-aware resolution, not a re-implementation.

**Reading this list.** `PUBLIC` = part of a module's surface. `private` = module-internal helper.  
Neither is automatically a defect: a private helper called only from its own module's tested path is  
normal. What matters is §3 (the 59) and §6's false-positive classes.

**Known false positives — do NOT "fix" these:**

- All 5 API route handlers (`stream_thesis_reasoning`, `dashboard_data`, `health`, `query`,  
  `get_thesis`) — FastAPI registers them by decorator; the tool does not model that.
- `start_params` / `transform_params` / `untransform_params` / `param_names` in  
  `models.econometrics` — **statsmodels `MLEModel` framework hooks**, called by statsmodels'  
  optimizer at runtime, never by name from our code.
- `@property` accessors are USED by attribute access, not calls; the tool models this via  
  `attr_accesses`, but a property whose only reader is itself uncalled still appears here.

#### `macro_engine`  (6)

- `env` — PUBLIC · L7157
- `get_audit_ledger` — PUBLIC · L380
- `get_settings_store` — PUBLIC · L581
- `reset_audit_ledger_cache` — PUBLIC · L391
- `reset_deployment_config_cache` — PUBLIC · L643
- `reset_settings_store_cache` — PUBLIC · L597

#### `macro_engine.api_layer`  (7)

- `_lifespan` — private · L53
- `dashboard_data` — PUBLIC · L169
- `get_thesis` — PUBLIC · L172
- `health` — PUBLIC · L83
- `query` — PUBLIC · L177
- `reset_cache` — PUBLIC · L180
- `stream_thesis_reasoning` — PUBLIC · L349

#### `macro_engine.api_layer.orchestration`  (1)

- `__init__` — private · L177

#### `macro_engine.api_layer.snapshot_provider`  (1)

- `warnings` — PUBLIC · L115

#### `macro_engine.audit`  (7)

- `__init__` — private · L145
- `computations_for` — PUBLIC · L290
- `create_schema` — PUBLIC · L152
- `model_latency_summary` — PUBLIC · L347
- `record_model` — PUBLIC · L156
- `record_thesis` — PUBLIC · L205
- `theses_for` — PUBLIC · L322

#### `macro_engine.config`  (63)

- `_apply_defaults_to_series` — private · L1934
- `_bands_must_be_non_negative` — private · L4574
- `_bands_must_be_ordered` — private · L4544
- `_bands_must_be_ordered_and_satisfiable` — private · L5171
- `_ceiling_must_be_reachable` — private · L5063
- `_ceiling_must_be_reachable_and_binding` — private · L3938
- `_derive_unit_scale` — private · L1569
- `_dissent_ceilings_must_be_ordered` — private · L4059
- `_enforce_fractional_kelly_floor` — private · L241
- `_floor_below_base` — private · L5085
- `_forward_looking_evidence_must_be_a_realised_observation` — private · L1636
- `_gates_must_be_ordered` — private · L4143
- `_leaves_must_be_usable` — private · L4333
- `_no_false_genericity_claim` — private · L4897
- `_order_the_stress_bands` — private · L5903
- `_permissive_cors_requires_loopback_bind` — private · L5383
- `_reject_a_stress_that_is_not_a_stress` — private · L778
- `_reject_a_sum_tolerance_that_could_never_discriminate` — private · L1224
- `_reject_a_warning_threshold_that_could_never_fire` — private · L1253
- `_reject_fraction_scale_entry` — private · L173
- `_reject_percent_in_fraction_field` — private · L1169
- `_release_calendar_joins_real_series` — private · L1961
- `_release_ids_must_be_distinct` — private · L554
- `_remaining_shares_must_sum_to_one` — private · L495
- `_require_a_resolution_path` — private · L1517
- `_resolve` — private · L7107
- `_thresholds_must_be_ordered` — private · L4222
- `_validate_base_state_warning_threshold` — private · L2882
- `_validate_calibration_status` — private · L219
- `_validate_cap_and_alert` — private · L6109
- `_validate_cap_and_label` — private · L6934
- `_validate_cap_decimals_and_bands` — private · L6665
- `_validate_cap_decimals_and_threshold` — private · L6384
- `_validate_cap_decimals_and_thresholds` — private · L6515
- `_validate_leaves` — private · L5492
- `_validate_marker_vocabulary` — private · L3434
- `_validate_thresholds_and_cap` — private · L6258
- `_validate_var_levels` — private · L1215
- `_verified_requires_evidence` — private · L1611
- `_vintage_eligibility_needs_a_single_fred_series` — private · L1531
- `_weights_must_sum_to_one` — private · L4829
- `calibrated` — PUBLIC · L7077
- `confidence_cap_is_calibrated` — PUBLIC · L3497
- `delinquency_trend_band_pp` — PUBLIC · L2803
- `families_for_full_credit` — PUBLIC · L2971
- `is_calibrated` — PUBLIC · L7084
- `min_families` — PUBLIC · L2966
- `min_meaningful_change` — PUBLIC · L3283
- `null_rate` — PUBLIC · L4706
- `openings_at` — PUBLIC · L3081
- `parameters_for` — PUBLIC · L4311
- `port` — PUBLIC · L5343
- `prob_tolerance` — PUBLIC · L5024
- `quits_percentile_window` — PUBLIC · L3327
- `r_star_value` — PUBLIC · L2123
- `require_likelihoods` — PUBLIC · L4773
- `require_verified` — PUBLIC · L2005
- `scalar` — PUBLIC · L7051
- `tail_draws_for` — PUBLIC · L766
- `up_share` — PUBLIC · L2848
- `var_lookback_days` — PUBLIC · L1011
- `version` — PUBLIC · L4766
- `vol_target` — PUBLIC · L921

#### `macro_engine.data_layer`  (15)

- `_is_non_finite` — private · L104
- `describe_route` — PUBLIC · L472
- `fetch_aluminum_change` — PUBLIC · L1045
- `fetch_copper_change` — PUBLIC · L1029
- `fetch_field_vintage` — PUBLIC · L344
- `fetch_iron_ore_change` — PUBLIC · L1034
- `get_logger` — PUBLIC · L258
- `has_persisted_snapshot` — PUBLIC · L159
- `load_latest_snapshot_frame` — PUBLIC · L305
- `load_snapshot` — PUBLIC · L419
- `release_dates_for_series` — PUBLIC · L349
- `to_observation_date` — PUBLIC · L715
- `validate_positive_index_level` — PUBLIC · L397
- `validate_snapshot` — PUBLIC · L686
- `validate_unemployment_rate` — PUBLIC · L385

#### `macro_engine.data_layer.alfred_client`  (3)

- `__eq__` — private · L234
- `__init__` — private · L227
- `__repr__` — private · L231

#### `macro_engine.data_layer.logging_json`  (1)

- `format` — PUBLIC · L180

#### `macro_engine.data_layer.openbb_client`  (17)

- `__enter__` — private · L206
- `__exit__` — private · L209
- `__init__` — private · L162
- `_coerce_records` — private · L404
- `_fetch_records_via_local_api` — private · L372
- `_fetch_records_via_package` — private · L386
- `_fetch_via_local_api` — private · L478
- `_fetch_via_package` — private · L498
- `_index_looks_like_dates` — private · L649
- `_lazy_import_obb` — private · L212
- `_normalize` — private · L518
- `_pick_date_column` — private · L680
- `_pick_value_column` — private · L687
- `close` — PUBLIC · L203
- `fetch_records` — PUBLIC · L282
- `fetch_series` — PUBLIC · L221
- `is_local_api_available` — PUBLIC · L457

#### `macro_engine.data_layer.release_calendar`  (2)

- `__bool__` — private · L149
- `get` — PUBLIC · L146

#### `macro_engine.data_layer.schemas`  (5)

- `_reject_unknown_tenors` — private · L174
- `assert_finite` — PUBLIC · L412
- `has_known_release_timing` — PUBLIC · L131
- `iter_curves` — PUBLIC · L396
- `iter_scalar_series` — PUBLIC · L377

#### `macro_engine.data_layer.snapshot_builder`  (4)

- `__init__` — private · L96
- `as_flags` — PUBLIC · L128
- `is_complete` — PUBLIC · L124
- `summary` — PUBLIC · L178

#### `macro_engine.data_layer.validation`  (5)

- `as_flag` — PUBLIC · L95
- `extend` — PUBLIC · L120
- `flags` — PUBLIC · L117
- `has_errors` — PUBLIC · L110
- `has_warnings` — PUBLIC · L114

#### `macro_engine.data_layer.world_bank_client`  (2)

- `vintage_label` — PUBLIC · L227
- `vintage_label` — PUBLIC · L262

#### `macro_engine.deployment`  (4)

- `is_local` — PUBLIC · L75
- `redacted` — PUBLIC · L223
- `resolve` — PUBLIC · L130
- `secret_variables` — PUBLIC · L248

#### `macro_engine.extensions`  (7)

- `build_scheduler` — PUBLIC · L21
- `log_model_result` — PUBLIC · L34
- `run_rule_backtest` — PUBLIC · L23
- `thesis_to_order_intent` — PUBLIC · L32
- `track_run` — PUBLIC · L26
- `update_thesis_posterior` — PUBLIC · L24
- `wrap_model` — PUBLIC · L44

#### `macro_engine.extensions.duckdb_store`  (2)

- `__init__` — private · L31
- `query_series` — PUBLIC · L37

#### `macro_engine.models`  (75)

- `_selection_value` — private · L747
- `ahe_composition_flag` — PUBLIC · L1050
- `auction_demand_signal` — PUBLIC · L149
- `bayesian_update` — PUBLIC · L91
- `beveridge_curve_position` — PUBLIC · L903
- `carry_score` — PUBLIC · L935
- `check_trilemma_tension` — PUBLIC · L1169
- `cip_check` — PUBLIC · L559
- `claims_corroboration` — PUBLIC · L594
- `claims_trend_signal` — PUBLIC · L394
- `classify_regime_markov_switching` — PUBLIC · L1815
- `compute_fci` — PUBLIC · L192
- `construct_breakeven_trade` — PUBLIC · L1159
- `construct_cross_market_rv` — PUBLIC · L1516
- `construct_duration_weighted_curve_trade` — PUBLIC · L858
- `convexity` — PUBLIC · L305
- `credit_spread_attribution` — PUBLIC · L165
- `cross_asset_transmission` — PUBLIC · L513
- `decompose_yield` — PUBLIC · L391
- `dollar_smile_regime` — PUBLIC · L1335
- `duration_sensitivity` — PUBLIC · L430
- `em_vulnerability_checklist` — PUBLIC · L201
- `expected_shortfall` — PUBLIC · L363
- `expected_value` — PUBLIC · L320
- `factor_tilt_prior` — PUBLIC · L634
- `fisher_index` — PUBLIC · L390
- `four_pillar_scorecard` — PUBLIC · L326
- `gdp_deflator` — PUBLIC · L421
- `gold_driver_attribution` — PUBLIC · L544
- `growth_accounting_decomposition` — PUBLIC · L295
- `historical_var` — PUBLIC · L291
- `inflation_convergence_classifier` — PUBLIC · L449
- `intervention_capacity` — PUBLIC · L286
- `inversion_probability_adjustment` — PUBLIC · L556
- `kalman_latent_state` — PUBLIC · L2025
- `laspeyres_index` — PUBLIC · L303
- `latest_observation` — PUBLIC · L183
- `leading_indicator_proxy` — PUBLIC · L275
- `macaulay_duration` — PUBLIC · L228
- `marginal_risk_contributions` — PUBLIC · L745
- `metals_complex_divergence` — PUBLIC · L945
- `minsky_composition_drift` — PUBLIC · L752
- `modified_duration` — PUBLIC · L273
- `monte_carlo_var` — PUBLIC · L1285
- `nfp_revision_adjusted_read` — PUBLIC · L1204
- `observation_on_or_before` — PUBLIC · L198
- `oil_balance_signal` — PUBLIC · L169
- `openings_to_unemployed_ratio` — PUBLIC · L462
- `paasche_index` — PUBLIC · L347
- `parametric_var` — PUBLIC · L431
- `phillips_curve_inflation` — PUBLIC · L200
- `policy_mix_classifier` — PUBLIC · L559
- `portfolio_volatility_n_asset` — PUBLIC · L684
- `portfolio_volatility_two_asset` — PUBLIC · L540
- `potential_gdp_cobb_douglas` — PUBLIC · L144
- `ppi_pipeline_signal` — PUBLIC · L171
- `ppp_valuation` — PUBLIC · L2316
- `price_bond` — PUBLIC · L177
- `price_change_with_convexity` — PUBLIC · L341
- `project_inflation_trajectory` — PUBLIC · L249
- `project_shelter_cpi` — PUBLIC · L117
- `quantity_theory_implied_inflation` — PUBLIC · L191
- `real_policy_rate` — PUBLIC · L42
- `realized_vol_simple` — PUBLIC · L491
- `repo_stress_check` — PUBLIC · L379
- `run_regression` — PUBLIC · L222
- `savings_investment_identity` — PUBLIC · L144
- `sector_rotation_prior` — PUBLIC · L228
- `simple_gdp_nowcast` — PUBLIC · L1152
- `statement_text_diff` — PUBLIC · L1172
- `test_cointegration` — PUBLIC · L603
- `test_stationarity` — PUBLIC · L409
- `two_survey_divergence` — PUBLIC · L712
- `uip_expected_move` — PUBLIC · L1809
- `yield_curve_pca` — PUBLIC · L1946

#### `macro_engine.models.as_of`  (1)

- `truncation_warning` — PUBLIC · L110

#### `macro_engine.models.commodities`  (1)

- `_validate_trend` — private · L508

#### `macro_engine.models.contracts`  (3)

- `_reject_non_finite` — private · L177
- `value_dict` — PUBLIC · L520
- `value_float` — PUBLIC · L545

#### `macro_engine.models.econometrics`  (5)

- `__init__` — private · L1961
- `start_params` — PUBLIC · L1982
- `transform_params` — PUBLIC · L1992
- `untransform_params` — PUBLIC · L2006
- `update` — PUBLIC · L2010

#### `macro_engine.models.em_vulnerability`  (1)

- `_validate_share_and_ratios` — private · L160

#### `macro_engine.models.equity_macro`  (1)

- `_rate_change_within_the_plausible_band` — private · L406

#### `macro_engine.models.fx_carry`  (4)

- `_validate_domain` — private · L1660
- `_validate_domain` — private · L2139
- `_validate_domain` — private · L312
- `_validate_domain` — private · L808

#### `macro_engine.models.gdp_nowcast`  (2)

- `warnings` — PUBLIC · L389
- `withheld_potential_points` — PUBLIC · L376

#### `macro_engine.models.inflation_dynamics`  (1)

- `_check_change_signs_are_not_degenerate` — private · L399

#### `macro_engine.models.instrument_selection`  (3)

- `_tenors_only_belong_to_curve_trades` — private · L208
- `category_for` — PUBLIC · L140
- `permits` — PUBLIC · L136

#### `macro_engine.models.intervention`  (1)

- `_validate_domain` — private · L258

#### `macro_engine.models.lei_proxy`  (1)

- `_weights_must_cover_components` — private · L201

#### `macro_engine.models.policy_rules`  (1)

- `_reject_blank_text` — private · L1111

#### `macro_engine.models.risk`  (2)

- `__call__` — private · L885
- `_validate_book_and_matrix` — private · L999

#### `macro_engine.models.scorecard`  (2)

- `_at_least_one_pillar_must_be_directional` — private · L238
- `pillar_reads` — PUBLIC · L250

#### `macro_engine.models.yield_curve`  (7)

- `_duration_must_match_the_sign` — private · L505
- `_durations_must_be_plausible` — private · L1474
- `_durations_must_be_plausible_for_the_tenor` — private · L1080
- `_durations_must_be_plausible_for_their_tenors` — private · L821
- `_durations_must_differ_and_stay_in_band` — private · L1112
- `_legs_must_be_distinct_and_ordered` — private · L809
- `_legs_must_name_two_distinct_markets` — private · L1445

#### `macro_engine.portfolio`  (4)

- `check_rebalancing_drift` — PUBLIC · L424
- `compute_risk_parity_weights` — PUBLIC · L1807
- `evaluate_drawdown_rules` — PUBLIC · L265
- `volatility_target_scaling` — PUBLIC · L769

#### `macro_engine.portfolio.risk_budget`  (4)

- `_budget_must_name_a_position_the_thesis_holds` — private · L2567
- `_panel_must_be_rectangular_and_budgeted` — private · L1496
- `_refusals_are_internally_consistent` — private · L2446
- `_reject_units_the_arithmetic_cannot_use` — private · L1008

#### `macro_engine.settings_store`  (11)

- `__init__` — private · L246
- `_database_snapshots_carry_full_provenance` — private · L199
- `_encode_scalar` — private · L568
- `create_schema` — PUBLIC · L260
- `decoded_value` — PUBLIC · L135
- `delete` — PUBLIC · L502
- `get` — PUBLIC · L271
- `history` — PUBLIC · L301
- `revision_instant` — PUBLIC · L220
- `set` — PUBLIC · L381
- `value_at` — PUBLIC · L328

#### `macro_engine.thesis_layer.builder`  (1)

- `as_sequence` — PUBLIC · L341

#### `macro_engine.thesis_layer.no_trade`  (3)

- `_evidence_matches_the_trigger` — private · L274
- `is_marginal` — PUBLIC · L308
- `warning_line` — PUBLIC · L297

#### `macro_engine.thesis_layer.schemas`  (10)

- `_bare_ticker_category` — private · L417
- `_enforce_conflicted_blocks_trade` — private · L687
- `_enforce_invalidation_gate` — private · L669
- `_enforce_scenario_probabilities` — private · L706
- `_enforce_scenario_status_matches_distribution` — private · L735
- `_no_trade_requires_consistency` — private · L546
- `_validate_direction` — private · L194
- `all_instruments` — PUBLIC · L351
- `category_for` — PUBLIC · L374
- `permits` — PUBLIC · L354

#### `macro_engine.thesis_layer.warnings`  (2)

- `all_texts` — PUBLIC · L278
- `shared_warnings` — PUBLIC · L289
