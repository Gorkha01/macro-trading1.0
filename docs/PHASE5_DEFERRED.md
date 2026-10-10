# Phase 5+ — What Is Deferred, and What Is Not

**Measured, not assumed.** Every row below was verified against the working tree on
**2026-10-06**: `find`/`grep` on `src/`, `tests/`, `tools/`, `scripts/`; `git log --all -- <path>`
for anything claimed absent; and `pyproject.toml` for every dependency claim.

Scope: everything this file calls *deferred* was checked to be genuinely unimplemented. Everything
it calls *done* was checked to have a real body — not a `NotImplementedError`.

---

## 1. Verdict

| Question | Measured answer |
|---|---|
| Are Phases 0–4 done? | **Yes.** All 101 functions named in AGENTS.md §21.3 Tier 1–5 exist in `src/`. |
| Is Tier 5 (the spec's "stubs only") stubbed? | **No — 23 of 23 Tier 5 functions have real bodies.** |
| How many `extensions/` modules are stubbed? | **6** — each gated on an uninstalled §4 package. |
| How many genuine *capability* gaps remain? | **2** — multi-country (**partially closed: `gb` and the euro area `eu` done 2026-10-10, §2.4; `de`/`jp` remain**), and FX-forward/market-data coverage. **GARCH closed 2026-10-09 (§2.2); the crisis-shock engine closed the same day (§2.3.1 + §2.3.2), simulation half and scenario library included.** |
| Why are they not implemented? | Mostly AGENTS.md §4 (*"no dependency before its phase"*); two are **data-availability** blocks, not code gaps. |

**Correction on the record:** AGENTS.md §21.3 heads Tier 5 *"Phase 5+ (stubs only until their
phase)"*. That heading does **not** describe the shipped tree — the Tier 5 models were built. The
"stubs only" rule bites only in `extensions/`.

---

## 2. The genuinely deferred items

### 2.1 `extensions/` — six stub modules, all deliberate

> **AMENDED 2026-10-09.** This section used to read *"six modules, all deliberate stubs … This is the
> **only** place in `src/` where a stub body exists"* and *"No other file in `extensions/` exists."*
> **`extensions/scenario_engine.py` now exists and is NOT a stub** — it is a real module with no
> dependency gate (see §2.3). So the directory is **six stubs plus one real module**, and the
> "only place a stub body exists" claim still holds for the SIX.

The six below raise `NotImplementedError` naming the §4 dependency that gates them.

| # | Module | Blocking dependency | Interface (already fixed) | What it unlocks |
|---|---|---|---|---|
| 1 | `extensions/backtest_vbt.py` | `vectorbt` | `run_rule_backtest(*, returns, entry_signals, exit_signals, fees_bp)` | Rule-set backtesting over the Section 18 crisis windows |
| 2 | `extensions/bayesian_updater.py` | `pymc` | Bayesian full-posterior update | Populates `MacroThesis.prior_probability` / `posterior_probability` |
| 3 | `extensions/duckdb_store.py` | `duckdb` | `DuckDBStore` | Query path over the existing Parquet store (same file format) |
| 4 | `extensions/mlflow_tracking.py` | `mlflow` | `track_run()` | Experiment tracking once multiple model variants exist |
| 5 | `extensions/nautilus_adapter.py` | `nautilus_trader` | Adapter over `MacroThesis.trade_idea` | Event-driven execution simulation (still never auto-executes) |
| 6 | `extensions/scheduler.py` | `apscheduler` | `build_scheduler(*, cron, job_kwargs)` | Scheduled thesis refresh; `build_us_macro_thesis` is already a pure function of a snapshot, so this is trivially schedulable |

**Read-only confirmation:** `grep -c NotImplementedError src/macro_engine/extensions/*.py` →
`backtest_vbt=1, bayesian_updater=1, duckdb_store=2, mlflow_tracking=3, nautilus_adapter=1, scheduler=1`.
**Six stubs; one real module now shares the directory.** `extensions/scenario_engine.py` was added
2026-10-09 (§2.3) and carries no dependency gate, so it is **not** one of the six.

### 2.2 GARCH-family conditional volatility — **IMPLEMENTED 2026-10-09**

> **This section previously read *"not implemented"* and was correct until 2026-10-09.** It is kept
> as the record of what was true then; the shipped state follows. **This is the first of §1's four
> capability gaps to close.**

| Check | Result at 2026-10-06 (when deferred) | Result now |
|---|---|---|
| `arch` in `pyproject.toml`? | **No** | **Yes** — `arch>=7.0.0`, resolved to `8.0.0` |
| Any `import arch` in the tree? | **No** | **Yes** — `models/volatility.py` |
| Count of the string "GARCH" in the tree | **3**, all prose, zero code | code + prose |
| Does `models/volatility.py` exist? | **No** — *"never existed"* | **Yes** — created |

**What shipped.** `models/volatility.py` — the file §6.10 and §4 both name — now holds
`garch_conditional_volatility(inputs)`, a GARCH(p, q) conditional-variance forecast fitted by
maximum likelihood through `arch`, annualised and published in **percent** on the same basis as
`realized_vol_simple` so the two are directly comparable. The parameters (`garch_p`, `garch_q`,
`min_observations`, `persistence_ceiling`, `confidence`) are config leaves under `volatility:`, and
the model **refuses** below `min_observations` rather than warning, per §21.4.

**How it was gated.** §4's dependency table already assigned it —
`| arch | GARCH-family conditional volatility | models/volatility.py | 5+ |` — and §1639 adds
*"gated individually — do not batch"*. Phase 5 is started, so the gate was open; the operator
approved the dependency explicitly.

**The starter did NOT move.** `realized_vol_simple` is still defined in `models/risk.py` and is
**re-exported** by `volatility.py`, so the spec-named module exposes both the starter and the
upgrade with ONE canonical implementation (LAW 2). A test asserts the re-export is the same object.

**Spec-vs-shipped note (unchanged, and still true).** AGENTS.md §6.10 gives
`# src/macro_engine/models/volatility.py` as the file header, and the module map at §230 reads
`volatility.py  # Module 17 (starter; arch/GARCH hook)` with `risk.py` reserved for
*"Modules 17–18 ↔ VaR/CVaR/drawdown"*. **The starter's canonical definition is therefore still in
the wrong file per the map** — a divergence this section recorded before the upgrade and which the
upgrade deliberately did not fix, because moving it touches `risk.py`, which carries mutation
anchors, and the re-export already satisfies the spec's intent.

**Verification.** Parameter recovery on a simulated series (true persistence 0.98 → fitted 0.9800);
the units chain cross-checked against an independent recompute of the raw `arch` objects
(24.0208 == 24.0208); a mutation proof showing `rescale=False` is load-bearing (`rescale=True`
publishes **2319.912** instead of **24.0208**); 12 behavioural tests. See
`tests/models/test_volatility.py`.

**⚠️ A limitation measured while building it, recorded so it is not mistaken for a defect later.**
On near-IGARCH data the GARCH MLE does **not** identify alpha and beta separately: three simulated
series with true persistence 0.9800 / 0.9900 / 0.9995 all fitted to **0.9800**, redistributing weight
between alpha and beta rather than raising their sum. The non-stationarity check therefore has
**limited power against a genuinely near-integrated process** — which is why that warning branch is
exercised through config rather than from a simulated series.

### 2.3 Crisis-scenario shock engine — **CLOSED 2026-10-09 (engine, simulation and library)**

> **AMENDED 2026-10-09.** This section read *"split: distribution done, engine not"*. The engine half
> now exists as `extensions/scenario_engine.py` — see §2.3.1 immediately below.

The spec's §13.2 "Example B" wants a named shock vector (`scenarios/gfc_2008.yaml`) applied to
portfolio exposures. Status is split:

**Done (the distribution half):**

| Component | Location | Status |
|---|---|---|
| `build_scenario_distribution()` | `thesis_layer/scenarios.py:165` | Real — four branches (base / partial / reversal / tail), config-driven probabilities + payoff multiples, guards for sub-noise-floor gaps, unknown units, zero gap |
| `expected_value()` | `models/probability.py:320` | Real — consumes the distribution |
| `generalized_kelly_fraction()` | `portfolio/risk_budget.py:1109` | Real — consumes the scenarios for sizing |
| `monte_carlo_var()` | `models/risk.py:1285` | Real — **already simulates normal AND stressed correlation regimes and reports both** (`_uniform_correlation_stress`, `stressed_volatility_multiplier`). This is Module 17.2's "coherent scenario, not isolated shock" principle already working. |
| schema enforcement | `thesis_layer/schemas.py:706,735` | Real — `_enforce_scenario_probabilities`, `_enforce_scenario_status_matches_distribution` |

**Not done (the shock-engine half): — AMENDED 2026-10-09, see §2.3.1. The table below was written
before the engine existed and is kept as the record; the four rows are now:**

| Missing item | Evidence |
|---|---|
| `extensions/scenario_engine.py` | **BUILT 2026-10-09 — §2.3.1.** Was absent; `git log --all -- <path>` was empty (never committed) |
| `scenarios/` directory + YAML shock files | **No such directory and no scenario YAML anywhere** in the tree |
| A function applying a named shock vector | **None.** No `def ...scenario.../stress.../shock...` applies `growth_shock` / `credit_spread_hy_shock` / `equity_shock` / `rate_shock` / `correlation_override` to a book |

Spec reference: AGENTS.md §13.2 line 1735 (the example YAML) and §14.1 line 1786
(*"15–16 — Case Studies | `extensions/` scenario YAMLs (Phase 5+) | scenario engine | (Phase 5+)"*).
AGENTS.md line 1749 phrases the module as optional: *"`extensions/backtest_vbt.py` (or a dedicated
`extensions/scenario_engine.py`)"*.

#### 2.3.1 AMENDMENT 2026-10-09 — the engine half is BUILT

**Shipped:** `extensions/scenario_engine.py` (the file §13.2 and §14.1 both name), plus
`scenarios/gfc_2008.yaml` (the spec's own Example B, committed verbatim in its numeric content), plus
the **named factor set** that had to exist first.

**Why the factor set was the prerequisite.** The system's exposure representation is POSITIONAL —
`models/risk.py`'s `factor_loadings: list[float]`, `MonteCarloVaRInputs` likewise. A positional vector
can be *simulated* but not *reported*, and §13.2 asks for `factor_exposure_breakdown`. The names come
from **§17.2's own words** (`AGENTS.md:3686`): *"correlated shocks across the portfolio's risk factors
**(rates, FX, credit, equity)**"* — now a config leaf, `scenario_engine.factors`, whose **order is
load-bearing** because index `i` of the set is index `i` of every exposure vector.

**What it does.** `apply_scenario_shock(exposures, scenario)` returns a `ModelResult` whose `value` is
the portfolio P&L estimate in **percent**, and whose `context` carries the per-factor breakdown. The
identity **`total == sum(breakdown.values())`** is asserted on every result, not trusted — a breakdown
whose parts do not sum to its whole is the same defect as a risk budget whose contributions do not
reconcile.

**What it deliberately does NOT do.** It does not simulate. §13.2 also asks for
`var_95_under_scenario` / `expected_shortfall_under_scenario` / `max_drawdown_estimate_pct`, which need
the *distribution* under the shocked correlation matrix — machinery that already exists
(`models/risk.py`'s `_simulate_regime_pnls`, `portfolio/risk_budget.py`'s `stress_correlations`).
The correlation override is **parsed and published but not yet consumed**, and the result says so in a
warning rather than implying a coherence it does not yet have.

**A driver is never applied.** `growth_shock` has no position in the factor vector — it is the cause
whose effect arrives through the rate and credit legs — so applying it would double-count. It is
carried and disclosed.

**Verification.** 13 behavioural tests; the units chain hand-derived and mutation-proved (treating a
bp shock as a percent shock publishes `rates: 1200.0` instead of `12.0` — a factor of 100); the
additivity guard asserted against a deliberately mismatched pair.

**Still open in this item:**
1. **The simulated VaR/ES/drawdown** under the shocked correlation matrix — `models/risk.py`'s
   `_simulate_regime_pnls` and `portfolio/risk_budget.py`'s `stress_correlations` already exist to be
   wired.
2. **Three of the four scenario files.** `AGENTS.md` §9.4 (line 1549) names a **library** —
   `black_wednesday.yaml`, `gfc_2008.yaml`, `covid_2020.yaml`, `ltcm_1998.yaml`. **Only `gfc_2008.yaml`
   is committed** (the one §13.2 gives a full example for). The engine loads any of them, so the other
   three are data, not code — but until they exist, §9.4's library is one-quarter built and this
   document should say so rather than implying four.

#### 2.3.2 CLOSED 2026-10-09 — the simulation half and the library

**Both items above are now done.**

**The simulation half** is `simulate_scenario_stress(...)`, which publishes **all five** of §13.2's
outputs — `portfolio_pnl_estimate_pct`, `var_95_under_scenario`, `expected_shortfall_under_scenario`,
`max_drawdown_estimate_pct`, `factor_exposure_breakdown`. It **consumes the correlation override**,
which is the part §13.2 cares about: the override is applied to the covariance (variances preserved
exactly, so any VaR change is attributable to the correlation assumption alone), and the book is
replayed under it.

**Measured, and the direction is the assertion.** With `treasuries_vs_hy_credit = -0.7` applied to a
book that is long treasuries and short credit, the tail **shrinks**: VaR −0.0154 → **−0.0146**,
ES −0.0192 → **−0.0182**, drawdown −0.0361 → **−0.0341**. That is flight to quality working — the
hedge becomes a hedge again. The sign convention is §13.2's own (negative = loss, matching its
`-22.1`).

**It reuses the canonical simulator.** `_simulate_regime_pnls`, `_loss_quantile` and
`_expected_shortfall_from_pnls` are imported from `models/risk.py` rather than reimplemented — LAW 2
forbids a second joint draw, and a local copy could silently stop being correlated. They are private,
and the precedent is `portfolio/risk_budget.py`, which already imports `_quadratic_form` for the same
reason.

**Two limitations are disclosed, not papered over.** `max_drawdown_estimate_pct` is a **one-step**
statistic — the covariance describes a single period, so there is no honest multi-step path to draw
from it, and a true path drawdown needs a serial model this engine does not hold. And the simulation
assumes **joint normality**, which understates the extreme tail — precisely where a stress test
matters most.

**The library is complete: all four of §9.4's case studies.** Each encodes a *different* crisis, and
the test asserts the overrides are **four distinct values**, because a library whose every scenario
assumed the same correlation response would be one scenario written four times:

| Scenario | The crisis | `treasuries_vs_hy_credit` |
|---|---|---|
| `black_wednesday` | 1992 ERM — an **FX** event; UK equities **rose**, credit flat | −0.1 |
| `covid_2020` | 2020 — the dash for cash **broke** the flight to quality | −0.3 |
| `gfc_2008` | 2008 — the credit crisis | −0.7 |
| `ltcm_1998` | 1998 — the correlation-breakdown episode | −0.8 |


### 2.4 Multi-country (`de`, `jp`, `gb`, `eu`) — **`gb` and the euro area (`eu`) implemented end-to-end 2026-10-10; `de`/`jp` remain**

> **RE-MEASURED 2026-10-10 (twice).** The row below that read "not implemented (confirmed)" was true
> when written and is no longer: the **first multi-country increment (gb)** landed as three §22.3
> workstreams and was wired through the API. Later the same day the **second (the euro area, `eu`)**
> landed the same way. This section is the doc that *tracks* the gap, so it is re-measured in full
> rather than having the one stale row edited (the §2.2 pair-defect lesson, restated in D-148).

| Check | Result |
|---|---|
| `config/settings.yaml` → `country.implemented` | **`["us", "gb", "eu"]`**. `gb` and `eu` were each added when their own data sources, their own reaction function and their own instrument set all existed. `de`/`jp` are still absent — adding one requires the same three things, not a label change. |
| `country.enabled` | **`["us", "gb", "eu"]`** — `enabled` gates the *snapshot build*, `implemented` gates the *derivation*. Both lists now carry `eu`; they were emptied of the false "US-only" claim when each country's pipeline landed. `_no_false_genericity_claim` rejects `enabled - implemented`. |
| What exists for other countries | **For `gb`: a full pipeline.** (1) Seven verified `gb_*` series in the registry (`gb_cpi_headline`, `gb_cpi_core`, `gb_unemployment_rate`, `gb_gdp_growth_qoq`, `gb_bank_rate`, `gb_gilt_10y_yield`, `gb_short_rate_3m`); (2) the Bank of England's **three published rules** (`boe_contemporaneous_taylor_rule`, `boe_first_difference_rule`, `boe_forward_looking_taylor_rule`, `models/policy_rules.py`) — genuinely distinct, not a relabelled Fed rule; (3) a country-aware `ProductionUniverse` carrying the UK plan (gilts, index-linked gilts, short-sterling, SONIA OIS, FTSE 100); (4) `snapshot_to_thesis_inputs` dispatching to `_gb_thesis_inputs`, so `/thesis/gb` runs. **For `eu`: a full pipeline, as of D-148.** (1) Eight verified `eu_*` series (HICP index, ECB main-refi and deposit rates, ESTR, euro-area unemployment, real GDP, 3m and 10y rates); (2) the ECB's **three WP-258 rules** (`ecb_contemporaneous_taylor_rule`, `ecb_error_correction_rule`, `ecb_restricted_cointegration_rule`) whose **long rate is a regressor** and whose form is **error-correction** — structurally unlike Fed and BoE, so not a relabelled rule; (3) a `ProductionUniverse(country="eu")` carrying the euro-area plan (Bunds/BTPs/OATs/Bonos/SPGBs, Eurex Bund/BTP futures, ESTR futures, Euro Stoxx 50); (4) `snapshot_to_thesis_inputs` dispatching to `_eu_thesis_inputs`, so `/thesis/eu` runs. **For `de`/`jp`: guards only.** `gdp_nowcast.output_gap_from_snapshot` and `regime.check_trilemma_tension` remain US-only (`NotImplementedError`), and `_gb_thesis_inputs` sets `regime=None` — neither the gb nor the eu path reaches them, which is correct, not a gap. |
| What is genuinely *data-ready* for other countries | The three FX-reserve fixtures (`fx_reserves_japan`, `fx_reserves_uk`, `fx_reserves_china`) remain **fixtures** for the 1992/1997 case studies (D-048) — a different act from supporting those countries. |
| A cross-country *trade* | `instrument_selection.py` still defines `BLOCKED_MULTI_COUNTRY_NOT_BUILT`, returned for every `CROSS_COUNTRY_DIVERGENCE` thesis. **Still correct but now a coverage statement, not a pattern statement:** a cross-country RV trade needs *two* fully-built country systems and the FX bridge converted between them; with `us`, `gb` and `eu` each complete and `fx_spot` live, the remaining block is that the cross-country *reasoning* layer itself is not built, not that fewer than two countries exist. |

**Status: PARTIALLY CLOSED — the pattern is proven for TWO countries, the coverage is not.** §22.3
(Finding #3) retracted any claim of multi-country generality, and that retraction still holds: the
system is *not* country-generic, it has **three** countries with a shared, now-tested dispatch. What
the `gb` and `eu` increments earned is the *pattern* — three workstreams per country, wired
end-to-end, with mutation proofs on the dispatch — and, in `eu`'s case, the proof that a **second
genuinely different reaction-function shape** fits the same dispatch (a level rule plus **two** change
rules, and a long rate as a regressor). What they did **not** earn is a claim that `de` or `jp` are
straightforward: the BoJ's deflation-scar + YCC and the PBoC's non-Western reaction function each need
*different logic* again, and the UK's own increment already required three disclosed stand-ins (no
published output-gap series, no JOLTS/claims/payrolls, no BoE projection path) — the euro area needed
its own (no published output-gap series, no euro-area JOLTS, a HICP *rate* that stops in 2025-12 so
the rule input is derived from the index and overlap-checked).


**Status: OPEN, and correctly so.** AGENTS.md §22.3 (Finding #3) explicitly retracted any claim of
multi-country generality: *"Phases 0–4 build a US-only system. … `country: str = "us"` is not a
generalization — it is a label on a system that currently only works for one value of it."*
Multi-country is **Tier 5+**, and per §22.3 it is not one task but **three per country** (verified
sources, a genuinely distinct central-bank reaction function, and an instrument set).

#### 2.4.1 What "multi-country" actually means — the four-layer bar

> **Added 2026-10-10 when the operator asked, in one line: *"What is Multi-country? This one is very
> important."*** The answer was not in any single place in the repo — §22.3 names the three
> *per-country* workstreams but never states what the *engine* must become. This subsection is that
> statement, so the scope is legible rather than inferred.

A true multi-country engine is **not** "the US engine with a country label". It is four capabilities,
each only real if the one below it is:

| # | Capability | What it requires | Trap if faked |
|---|---|---|---|
| **1** | **Country-specific data** | Its own verified series: policy rate, inflation (on ITS target measure), labor, GDP, curve, fiscal calendar — each with provenance and plausibility bounds | A series fetched, never cross-checked against the country's own conventions |
| **2** | **Country-specific reaction function** | Genuinely distinct logic: ECB's 20-country compromise + 2% HICP, BoJ's deflation-scar + YCC, BoE's energy/non-energy split + 5-quarter horizon | **The Fed's Taylor rule with a foreign label** — the single most common fake |
| **3** | **Country-specific instruments + FX** | Its own rates system (gilts, JGBs, Bunds), its equity index, and **an FX layer to compare across countries** | Comparing two countries' yields without converting — the comparison is meaningless |
| **4** | **Cross-country reasoning** | Two countries at 1–3, plus a shared basis (FX-converted, same horizon): *Fed vs ECB*, *US vs EU inflation*, *USD vs EUR* | A "spread" between two numbers measured on different bases |

**Layers 1, 3 and 4 are carry work** (data + plumbing). **Layer 2 is where a system either
understands a foreign central bank or merely relabels the Fed.** The repo has taken layer 2 seriously:
gb runs the BoE's *published* Annex 1 rules, not a Taylor rule with a British accent.

**Measured against the bar (2026-10-10):**

| Layer | US | UK (`gb`) | Euro area (`eu`) | `de` / `jp` | Cross-country |
|---|---|---|---|---|---|
| 1 · Data | ✅ | ✅ 7 `gb_*` series | ✅ 8 `eu_*` series | ❌ | — |
| 2 · Reaction function | ✅ Fed trio | ✅ 3 BoE rules | ✅ 3 ECB WP-258 rules (level + **two** error-correction; long rate a regressor) | ❌ | — |
| 3 · Instruments | ✅ | ✅ gilt / short-sterling / SONIA / FTSE | ✅ Bund/BTP/OAT curve, ESTR futures, Euro Stoxx 50 | ❌ | — |
| **FX (the bridge)** | ✅ **`fx_spot` fetched since 2026-10-10** (spot; forwards still blocked) | — | — | — | ⚠️ convertible |
| 4 · Cross-country reasoning | — | — | — | — | ❌ **`BLOCKED_MULTI_COUNTRY_NOT_BUILT`** |

**The three things genuinely missing for the engine the operator described** (Fed-vs-ECB,
US-vs-EU inflation, USD-vs-EUR), in dependency order:

1. ~~**An FX layer.**~~ **CLOSED 2026-10-10.** The FX *spot* layer is now fetched end-to-end:
   `data_layer/fx_client.py` fetches the configured pairs (`config/settings.yaml` → `fx_pairs.enabled`)
   and `build_snapshot` populates `snapshot.fx_spot`; `models/fx_conversion.py` converts between two
   currencies with the direction **derived from the codes**. `fx_spot` therefore left
   `declared_not_wired`. **What remains blocked is only the FORWARD**: no forward/swap/basis route
   exists on this installation (D-108), so `cip_check`'s live check stays unavailable. See §2.5 item 3
   for the corrected record — the field was unwired AND the *spot* data was thought absent; only the
   first was true.
2. ~~**A second country next to `gb`.**~~ **CLOSED 2026-10-10 — the euro area (`eu`), D-148.** The
   ECB arm is a full three-workstream increment, and it proved the harder case: the euro area has no
   single labour market, a 20-country inflation aggregate and a two-rate policy system, and its
   reaction function is **structurally** different from the Fed's and the BoE's (error-correction
   with the long rate as a regressor), not a re-parameterisation. `/thesis/eu` runs end-to-end.
3. **Cross-country reasoning itself.** `CROSS_COUNTRY_DIVERGENCE` is refused
   (`BLOCKED_MULTI_COUNTRY_NOT_BUILT`) — correctly, because it needs *two* fully-built country
   systems **and** the FX bridge between them. Both conditions are now met for `us`↔`gb`/`eu`; what
   remains is the reasoning layer itself, so the block is now the last leg of the dependency chain
   rather than a wall with no bridge under it.

**What the repo CAN honestly say today:** *"Three countries — `us`, `gb` and the euro area `eu` — are
modelled end-to-end on their own data, their own central-bank rules and their own instruments, with
two genuinely different reaction-function shapes proving the dispatch general; an FX spot layer
converts between currencies; the cross-country reasoning layer itself is the one capability still
refused."* That is a real, defensible statement — and it is finally within one increment of the
multi-country engine described in this subsection.


### 2.5 Market / price data — **partially implemented; the gap is source availability**

> **REVISIT REGISTER — carry these three forward.** They are *not* phase-gated the way the shock
> engine is (and the way GARCH was until 2026-10-09). One is a hard data block to re-probe; one is
> a known Loophole-Ledger set; one is actionable now for two of its three fields. Tracked here so
> they are not lost behind the
> "Phase 5+" label. See §2.5.1 for the concrete next action on each.

This needs care, because "market data is not fetched" is **too broad**. What was measured:

**Fetched and verified — 59 verified series** (`config/series_registry.yaml` `series:` block, all
`status: verified`), including real *market* series:

| Field | Symbol | What it is |
|---|---|---|
| `equity_volatility` / `gold_crisis_vix` | `VIXCLS` | CBOE VIX, index points |
| `sp500_index` | `SP500` | S&P 500 index level |
| `treasury_curve`, `tips_yields`, `curve_slope_10y3m` | FRED | Nominal + real curve |
| `metals_copper`, `metals_iron_ore`, `metals_aluminum` | FRED | Metals complex |
| `gold_real_yield_10y` | FRED | Gold's real-yield leg |
| `crude_inventory_weekly`, `ppi_stage_crude` | FRED | Energy / PPI stage |

Three dedicated clients back this: `openbb_client.py` (35 KB), `commodities_client.py` (47 KB, with
`fetch_vix_level`, `fetch_metal_change`, `fetch_copper_change`, `fetch_crude_inventories`,
`fetch_opec_spare_capacity`), plus `alfred_client.py` (vintages), `world_bank_client.py`,
`reserves_client.py`, `release_calendar.py`.

**Two things are genuinely broken or missing** (a third — the unwired spot fields — was first closed
2026-10-09 by DISCLOSING the gap, and then **half-fetched 2026-10-10**: `fx_spot` was re-measured as
reachable and wired, while `commodity_spot`/`equity_index` keep the disclosure; see item 3 below and
§2.5.1):

| # | Gap | Evidence | Nature |
|---|---|---|---|
| 1 | **FX forward points / cross-currency basis — HARD BLOCKED** | `config/series_registry.yaml:1908` — `blocked: fx_forward_rate`. Measured **2026-09-25 (D-108)** with three independent probes: (1) the OpenBB route inventory walks to **443 routes and none matches forward/swap/basis** under `currency` or `fixedincome`; (2) CME futures proxies `6E=F` / `6J=F` / `6B=F` all return `EmptyDataError` via yfinance; (3) FRED's H.10 family (`DEXUSEU`, `DEXJPUS`, …) is **spot only** — the release carries no forwards. **Consequence: `cip_check` takes `forward` as an INPUT and its arithmetic is complete, but its LIVE check cannot run, so the market's own CIP deviation cannot be measured on this build.** | Data block — no source on this install |
| 2 | **Four more blocked registry items** | Active `blocked:` entries are **5 in total** (with `fx_forward_rate`): `iron_ore_change_pct` (L1832), `supercore_direction` (L1844), `conference_board_lei` (L1861), `inflation_surprise_bp` (L1876), `fx_forward_rate` (L1909). A sixth, `ppp_implied_rate` (L1841), is **commented out**, not active. These are the **§21.4 Loophole Ledger** — the system returns `"unavailable"` rather than a plausible number, which is the intended behaviour, not a defect. | Loophole Ledger — by design |
| 3 | **`fx_spot` / `commodity_spot` / `equity_index` declared but never filled** | **PARTLY CLOSED 2026-10-09 as a DISCLOSURE; `fx_spot` then WIRED 2026-10-10.** The 2026-10-09 disposition made the absence **visible** (`SnapshotBuildReport.declared_not_wired` + a `DECLARED_NOT_WIRED:<field>` flag) on the reading that the data was unavailable. **Re-measured 2026-10-10: that reading was half wrong — the field was unwired (true) and the SPOT data was reachable (false).** `currency.price.historical` returns ~1501 daily observations per G10 pair through this installation's OpenBB service, so `fx_client.fetch_fx_spot` was written and `build_snapshot` now fills `snapshot.fx_spot`; `fx_spot` left `declared_not_wired`. **This is the sixth FALSE BLOCK of the D-043 class.** `commodity_spot` / `equity_index` remain declared-but-unwired (no fetch step; not re-probed). Tests: `test_fx_client.py` (20), `test_phase1_data_layer.py::test_the_builder_itself_records_the_unwired_mapping_fields`. | **`fx_spot` done — fetched. Others: disclosure retained** |

**⚠️ A caution about probe (1) above, added 2026-10-10.** The D-108 inventory walk is cited as
evidence that no forwards route exists, and it searched for `forward|swap|basis`. **It never searched
for `futur`** — and `derivatives.futures.curve` DOES exist, which is how the §22.5 fed-funds curve was
missed for a whole session (see §5.1; the same false-block class as `commodities_client`, the fifth
FALSE BLOCK). This does **not** overturn item 1 — the three probes above are specific and the
`blocked:` entry is legitimate — but it means the *route-inventory* probe alone is not sufficient
evidence of absence. Re-probing on a schedule (item 1's §2.5.1 action) should search the inventory for
the *economic concept*, not only the instrument's usual name.

**⚠️ And a second caution, about the probe PROCESS rather than its search term.** Writing a probe is
not enough; the probe must CALL the source, not enumerate it. The §22.5 probe originally printed
route NAMES and a statement of what would be needed, which reads as a finding and is not one — so the
first probe agreed with the wrong conclusion instead of overturning it (§5.1). **Two independent
defects, one in the search term and one in the method, both pointed the same wrong way.** A probe's
deliverable is a verdict derived from a call; anything else is a restated hypothesis.

**Why these are not "Phase 5+ deferrals" like the others.** The shock engine is deferred
because a *dependency* is withheld — as GARCH was until 2026-10-09, when its gate opened and it
shipped (§2.2). Item 1 is blocked because **no source on this installation returns
the data**. Item 2 is a **recorded, deliberate refusal** (§21.4). Item 3 is **unfinished wiring**.
Only item 1 is a plan; the other two are a decision and an omission respectively.

#### 2.5.1 Revisit — the concrete next action on each

| # | Next action | Blocker to clear first |
|---|---|---|
| 1 | Re-probe FX forwards on a schedule (the block is recorded precisely so it *can* be re-probed). Candidate sources already identified in the registry note: any provider publishing forward points or a cross-currency basis — a licensed source, or CME settlement data via a credentialed provider (`fmp` / `polygon`). **The registry records that both currently fail on MISSING CREDENTIALS rather than a missing product** — i.e. this is potentially a *config* fix, not a code fix. **Search the route inventory for the ECONOMIC CONCEPT, not only the instrument name** — see the caution above. | Credentials / licensed feed |
| 2 | No action — leave as `blocked:` so the block remains re-probeable. Any attempt to populate these would violate §21.0 rule 3 (*"no input may be invented"*). | None (intentional) |
| 3 | ~~Populate two of the three now~~ **CLOSED 2026-10-09 as a DISCLOSURE, then WIRED 2026-10-10.** The 2026-10-09 step was correct as far as it went — the invisibility *was* a real defect and the disclosure fixed it — but it accepted a second claim it never measured: that the data was unavailable. It is not. `fx_spot` is now fetched (spot only; forwards remain item 1) and no longer appears in `declared_not_wired`. `commodity_spot` / `equity_index` keep the disclosure. | Done |

**Note on item 3 (updated 2026-10-10):** this used to say it was "the only one currently invisible to
any test — an empty dict looks the same as 'no data this run'." That was the defect, and it is now
fixed: the invisibility was the bug, and it is asserted by `test_phase1_data_layer.py:2303` and
`:2363`. The original framing — *"decide whether `snapshot_builder` should assign the two reachable
fields"* — turned out to be the RIGHT question, but it was answered in the wrong direction: it
concluded the fields were unreachable and settled for disclosing them. **`fx_spot` was reachable all
along.** The 2026-10-10 increment split the three: `fx_spot` got a fetch step
(`_fetch_fx_spot_map`), the other two kept the disclosure, and the disclosure is now scoped to the
fields that genuinely have no fetch step (`FX_UNWIRED_ALWAYS`) instead of all three.

**The reusable lesson (the sixth instance of it, so it is now a named pattern rather than an
incident).** *A disposition recorded as "the data is unavailable" must be re-measured like any other
claim.* The first probe's own method note (§2.5, above) already warned that *"a probe's deliverable
is a verdict derived from a call"* — and the D-137 disposition was a verdict derived from
**enumeration** (*no route is named `fx_spot`*), which is the same class of error. The repository now
carries six FALSE BLOCKs: `ppp_implied_rate`, `commodities_client`, `fx_reserves`, the two EM legs,
the §22.5 futures curve, and this one.

### 2.6 "Conditional" forecasting — what the word means here

Asked directly ("is this GARCH, I mean forecasting?"), so answered directly.

**Yes — in this specification, "conditional forecast" IS the GARCH item.** They are the same gap,
not two. The chain is:

- "Volatility is **conditional**" means today's variance depends on yesterday's — volatility
  **clusters**. A GARCH-family model estimates that dependence and therefore *forecasts* the next
  period's variance.
- "A **realized** volatility" is *unconditional*: it measures the past and asserts nothing about
  the future.

Evidence in the tree:
- `models/risk.py:500` — *"a conditional forecast is a Phase 5+ GARCH item"*
- `models/risk.py:531` — warning on `realized_vol_simple`: *"Backward-looking by construction — no
  conditional forecast."*
- `models/fx_carry.py:906` — *"the GARCH family that replaces `realized_vol_simple`"*
- AGENTS.md §6.10's docstring: *"Simple rolling std dev — **NOT a forecast**, purely backward-looking"*

**So: the system does do forecasting — just not variance forecasting.** The conditional forecasts it
**does** produce:

| Forecasting model | Location | Status |
|---|---|---|
| `project_shelter_cpi` | `models/inflation_nowcast.py` | Real |
| `project_inflation_trajectory` | `models/inflation_trajectory.py` | Real |
| `simple_gdp_nowcast`, `output_gap` | `models/gdp_nowcast.py` | Real |
| `classify_regime_markov_switching` | `models/regime.py:1815` | Real — publishes *probabilities*, i.e. a likelihood, not just a label |
| `phillips_curve_inflation` | `models/inflation_dynamics.py` | Real |

The single missing forecast type is the **conditional variance** forecast. That is GARCH, and it is §2.2.

### 2.7 File-layout divergences (spec names a path; the code chose another)

Documentation-surface only — no functional impact. Recorded because *"a named path is a claim you
can check in one command."*

| Spec path | Where the code actually lives | Spec reference |
|---|---|---|
| `models/monetary.py` (marked **"NEW FILE — Phase 2 backfill"**) | `models/national_accounts.py:191` → `quantity_theory_implied_inflation` | AGENTS.md:4097, §20.1 |
| `models/volatility.py` | `models/risk.py:491` → `realized_vol_simple` (**starter only** — see 2.2) | AGENTS.md:230, 280, 300, 1128, 1787 |
| `extensions/scenario_engine.py` | **BUILT 2026-10-09** at the spec path itself — see 2.3.1. This row said *"not built at all"* until 2026-10-10; corrected. | AGENTS.md:1749 |

Neither `monetary.py` nor `volatility.py` has ever existed in this repo's history. This is a
**spec/implementation naming divergence**, not a `bd96d5c` casualty (that re-init deleted *committed*
files, which `git log --all` can still find).

**A fourth false negative, found 2026-10-10 the same way.** `models/volatility.py` DID get built
(2026-10-09) with the GARCH estimator, and §2.2 records it — but this table kept pointing at
`risk.py`'s `realized_vol_simple` and calling that the implementation. Both rows above for
`volatility.py` were reconciled in that change; the `scenario_engine` row was missed, which is the
*pair* defect: a doc that tracks a gap must be re-read in full, not only the row being edited.

### 2.8 Deliberately-empty config surfaces

| Item | Location | Why it is empty |
|---|---|---|
| `bayesian.likelihoods.table: {}` | `config/settings.yaml:5301` | Populating it needs historical evidence-vs-outcome data (Phase 5+). Empty means `bayesian_update()` **refuses to run** rather than defaulting to a 0.5/0.5 likelihood ratio that would silently render the update a no-op. `config.py:4784` enforces this. |
| `country.implemented: ["us", "gb", "eu"]` | `config/settings.yaml` | §22.3 — the US-only-through-Phase-4 gate. **`gb` was added 2026-10-10** when the first multi-country increment landed end-to-end, and **`eu` later the same day** (D-148) when the euro area did (see §2.4); `de`, `jp` remain Tier 5+. |
| `r_star_estimate: 0.5` | `config/settings.yaml:1594` | Placeholder until the Kalman-filtered r* (Phase 5+). |

---

## 3. What is NOT deferred (verified done, despite the spec calling it Phase 5+)

The spec labels these Phase 5+ or Tier 5. **All of them ship with real bodies.** This is the part
an earlier read of mine got wrong, so it is stated with the verification method.

**Also now in this section, added 2026-10-09:** `arch`'s GARCH-family conditional volatility. It was
**not** one of the 23 Tier-5 functions — it was a *capability gap*, tracked at §2.2 — so it is listed
here only as a pointer, not as a 24th function. See §2.2 for its evidence and its measured limitation.

**All 23 Tier 5 functions — real bodies, zero stubs:**

| Function | Location |
|---|---|
| `cip_check`, `uip_expected_move`, `ppp_valuation`, `carry_score`, `dollar_smile_regime` | `models/fx_carry.py` |
| `intervention_capacity` | `models/intervention.py` |
| `em_vulnerability_checklist` | `models/em_vulnerability.py` |
| `oil_balance_signal`, `gold_driver_attribution`, `metals_complex_divergence` | `models/commodities.py` |
| `sector_rotation_prior`, `duration_sensitivity`, `factor_tilt_prior` | `models/equity_macro.py` |
| `monte_carlo_var` | `models/risk.py:1285` |
| `compute_risk_parity_weights` | `portfolio/risk_budget.py:1807` |
| `classify_regime_markov_switching` | `models/regime.py:1815` |
| `yield_curve_pca` | `models/yield_curve.py:1946` |
| `run_regression`, `test_stationarity`, `test_cointegration`, `compute_pca`, `kalman_latent_state` | `models/econometrics.py` |
| `statement_text_diff` | `models/policy_rules.py:1461` |

Two of these deserve a specific note, because the spec calls them Phase 5+ *replacements*:

- **`classify_regime_markov_switching`** (`models/regime.py:1815`) — a real
  `statsmodels` Markov-switching fit publishing smoothed + filtered probabilities, transition matrix,
  expected durations, and regime shares. The spec's §6.2 shows a `raise NotImplementedError("Phase 5+
  — see docs/DECISIONS.md for rollout plan")` placeholder; that placeholder is **not** what shipped.
- **`yield_curve_pca`** (`models/yield_curve.py:1946`) — a real decomposition that parses tenors to
  years, sorts the maturity order, counts `sign_changes` per component, and refuses to auto-label
  level/slope/curvature (per §15.20-F).

**Backend substitutions — a dependency that was deliberately NOT used:**

| Spec backend | What shipped instead | Where the decision is recorded |
|---|---|---|
| `riskfolio-lib` | A hand-rolled cyclical-coordinate risk-parity solver, cross-checked against a **closed-form two-asset oracle**. Reason: the algorithm is ~20 lines; the library pulls a CVXPY/CLARABEL solver stack whose solution is not reproducible to the last digit, and a desk reconciles a risk budget against its previous run. | `portfolio/risk_budget.py:1831` docstring records the decision; `docs/DECISIONS.md:15979` lists the Riskfolio-Lib construction row (cross-reference: the docstring cites DECISIONS.md, so the two should be read together) |
| `pymc` (full posterior) | `scipy.stats` point update via `bayesian_update()` (`models/probability.py:91`) — sufficient for Phase 1 point updates | AGENTS.md §4: *"scipy.stats suffices for Phase 1 point updates"* |

**Note on `NotImplementedError` count.** `grep -rn "raise NotImplementedError" src/` returns **16**
sites across 13 files. Only **9** are stubs (all in `extensions/`). The other **7** are **guards**,
not stubs:

| Guard site | What it guards |
|---|---|
| `api_layer/orchestration.py:1764` | non-`us` country |
| `models/gdp_nowcast.py:571` | non-`us` country |
| `data_layer/snapshot_builder.py:846` | country not in `settings.country.implemented` |
| `models/regime.py:1234` | non-`us` country (`check_trilemma_tension`) |
| `config.py:2016` | series is BLOCKED with no reachable source (§21.4 Loophole Ledger) |
| `config.py:2026` | series status is not `verified` (§21.1) |
| `config.py:4784` | `bayesian.likelihoods.table` is empty (§21.1 — refuse to invent) |

That is `1 + 1 + 1 + 1 + 1 + 1 + 1 = 7` guard sites, and `7 + 9 = 16`. ✓

A guard that raises for an out-of-scope input is **not** a stub. Misreading the two inflated an
earlier count in this review; the distinction is recorded here so it is not repeated.

---

## 4. Summary table

| Item | Status | Gate |
|---|---|---|
| Phases 0–4 | **Done** | — |
| Tier 1–4 functions (78) | **Done** | — |
| Tier 5 functions (23) | **Done** (spec calls them "stubs only") | — |
| `extensions/backtest_vbt.py` | Deferred | `vectorbt` |
| `extensions/bayesian_updater.py` | Deferred | `pymc` |
| `extensions/duckdb_store.py` | Deferred | `duckdb` |
| `extensions/mlflow_tracking.py` | Deferred | `mlflow` |
| `extensions/nautilus_adapter.py` | Deferred | `nautilus_trader` |
| `extensions/scheduler.py` | Deferred | `apscheduler` |
| ~~GARCH conditional volatility~~ | **CLOSED 2026-10-09 — shipped** (§2.2) | `arch` added; `models/volatility.py` created |
| ~~`extensions/scenario_engine.py` + `scenarios/*.yaml`~~ | **CLOSED 2026-10-09 — shipped** (§2.3.1); corrected 2026-10-10 | file exists at the spec path, 0 `NotImplementedError`, 4 `scenarios/*.yaml` |
| Multi-country — **`gb` and `eu`** | **CLOSED 2026-10-10 for `gb` and the euro area `eu`** — the first two multi-country increments (§2.4), wired end-to-end, 4 mutation proofs on the gb dispatch and 7 on the eu rules + units | `de`/`jp` still need their own series set + reaction function + instrument set (§22.3: three tasks per country) |
| Multi-country — **`de`, `jp`** | **Deferred — genuine gap** (guards in place; `BLOCKED_MULTI_COUNTRY_NOT_BUILT`) | per-country series set + reaction function (§22.3: three tasks per country) |
| FX forward points / cross-currency basis | **Blocked — data unavailability**, not a plan | no source on this install (3 probes, D-108) |
| **FX spot (`fx_spot`, the layer-3→4 bridge)** | **CLOSED 2026-10-10 — fetched** | `data_layer/fx_client.py` + `snapshot_builder._fetch_fx_spot_map` + `models/fx_conversion.py`; `fx_spot` left `declared_not_wired`. Spot only — the forward is the row above |
| `commodity_spot` / `equity_index` as snapshot fields | **Plumbing exists, fetch does not** | `snapshot_builder.py` never populates them (`FX_UNWIRED_ALWAYS`) |
| 4 further Loophole-Ledger blocks (`iron_ore_change_pct`, `supercore_direction`, `conference_board_lei`, `inflation_surprise_bp`) | **By design — returns "unavailable"** | §21.4 — no source, and inventing one is forbidden |
| §22.5 Fed-funds-futures-implied policy path | **DISCHARGED 2026-10-10 — live fetch shipped, fail-safe to proxy** (§5.1) | the SOURCE exists; the reader + builder chain + live fetch are wired; marker `"discharged"` |
| `bayesian.likelihoods.table` (data) | Deferred | historical evidence-vs-outcome data |
| Kalman-filtered `r_star` | Deferred | `statsmodels.tsa.statespace` |
| `models/monetary.py`, `models/volatility.py` (paths) | Doc-only divergence for `monetary.py`; **`volatility.py` path reconciled** | — |

**Two genuine capability gaps remain: multi-country (`de`/`jp`; `gb` and the euro area `eu` closed
2026-10-10), and
FX-forward coverage** (a data block, not a plan). **The FX SPOT layer closed 2026-10-10** — it was
recorded as a data block and re-measured as an unwired field (the sixth FALSE BLOCK). Three closures
now landed 2026-10-09/10, and this table said four until 2026-10-10 — GARCH (§2.2) and the
crisis-shock engine (§2.3.1) were both built, and the count was not decremented. The multi-country
row was likewise left whole until 2026-10-10, when the `gb` increment closed one of its three
countries.
Everything else the spec defers is either an `extensions/` backend gated on an uninstalled package,
a Loophole-Ledger data block, or a documentation path that drifted from the code.

---

## 4.1 Revisit register — items to look at later

Three market-data items are flagged for a follow-up pass (§2.5.1). Summary:

| # | Item | Status | Next action | Effort |
|---|---|---|---|---|
| 1 | FX forward points (`fx_forward_rate`) | Hard block, 3 probes exhausted | Re-probe, then try credentialed `fmp`/`polygon` (both fail on **missing credentials**, not a missing product — so this may be a *config* fix) | Needs a key |
| 2 | **5 blocked registry entries total** — `fx_forward_rate` (see item 1) plus `iron_ore_change_pct`, `supercore_direction`, `conference_board_lei`, `inflation_surprise_bp` | Intentional — §21.4 | None; leave `blocked:` so they stay re-probeable | — |
| 3 | `commodity_spot` + `equity_index` (2 of 3 snapshot fields) | Wiring omission | Decide whether `snapshot_builder` should populate them — FRED routes already verified (`sp500_index`, `metals_*`, `gold_*`, `crude_inventory_weekly`) | Small, actionable |
| 3b | `fx_spot` (the third field) | Shares item 1's block | Blocked with item 1 | Blocked |

**Item 3 is the one worth doing first** — it is the only partial fix available without a new data
source, and today an unpopulated `commodity_spot` / `equity_index` is indistinguishable from "no data
this run", because both validate clean and persist as empty dicts.

Count reconciliation: Tier 1–5 = 23 + 29 + 15 + 11 + 23 = **101** named functions, all present in
`src/`; 78 of them are Tier 1–4 (done in Phases 1–4) and 23 are Tier 5 (done ahead of the phase the
spec assigned them).

---

## 5. How these numbers were produced

Reproduce with:

```bash
# 1. Every NotImplementedError site, and which are guards vs stubs
grep -rn "raise NotImplementedError" --include=*.py src/

# 2. Every function named in AGENTS.md §21.3 Tier 1-5, checked against src/
#    (script: parse the Tier blocks, regex `def <name>(` across src/**/*.py)

# 3. Dependency claims
sed -n '/dependencies/,/^\]/p' pyproject.toml
grep -rn "import arch" --include=*.py src/     # empty

# 4. Paths named in the spec but absent from disk, and whether they ever existed
grep -oE "(models|extensions)/[a-z_]+\.py" AGENTS.md | sort -u
git log --all --oneline -- src/macro_engine/models/volatility.py   # empty BEFORE 2026-10-09; now created
git log --all --oneline -- src/macro_engine/models/volatility.py   # 2026-10-09: the GARCH build
git log --all --oneline -- src/macro_engine/extensions/scenario_engine.py  # 2026-10-09: the shock engine

# 5. Scenario shock engine — CORRECTED 2026-10-10 (this printed "No such file or directory" when
#    written, and kept printing it after the file was built; a repro that must be re-run, not copied)
ls -d scenarios/ 2>&1                            # four files: the four §9.4 scenarios
ls -l src/macro_engine/extensions/scenario_engine.py
grep -c "raise NotImplementedError" src/macro_engine/extensions/scenario_engine.py   # 0 — it is not a stub

# 6. Multi-country
grep -n "implemented:" config/settings.yaml      # implemented: ["us"]
grep -rn "BLOCKED_MULTI_COUNTRY_NOT_BUILT" --include=*.py src/

# 7. Market data: what IS verified vs what is blocked
#    (59 `series:` entries, all status: verified; 5 `blocked:` entries)
python -c "
import re,pathlib
L=pathlib.Path('config/series_registry.yaml').read_text(encoding='utf-8').splitlines()
for key in ('series:','blocked:'):
    st=[i for i,l in enumerate(L) if l==key][0]; out=[]
    for l in L[st+1:]:
        if l and not l[0].isspace(): break
        if re.match(r'^  - field:|^  [a-z_]',l): out.append(l.split(':')[0].strip())
    print(key,len(out))
"

# 8. Conditional forecast = GARCH (they are the same gap, not two)
grep -rn "conditional forecast" --include=*.py src/
```

Finding IDs in `.review-evidence/module_findings.json`:
`F-MOD-001` (path divergences, SEV-3, OPEN), `F-MOD-002` (census verified, INFO),
`F-MOD-003` (scenario shock engine deferred, SEV-3, OPEN — **GARCH half CLOSED 2026-10-09, §2.2**).

### 5.1 §22.5 — the Fed-funds-futures path: DISCHARGED (source exists, mechanism not, change additive, live fetch shipped)

Measured 2026-10-10, in **two passes**. **Pass two reverses part of pass one.** Pass one recorded the
obstacle as *"the SIGNATURE"* and concluded the obligation was **blocked on the spec**. Measured again,
that conclusion was wrong: the promised *mechanism* is unusable, but the promised *outcome* is
achievable, and the reader and builder chain now do it.

An earlier pass still had recorded §22.5 as *"needs data"*, on the strength of a D-108 route inventory
that had been grepped for `forward|swap|basis` — and **never for `futur`**. The source was there the
whole time:

```bash
uv run python tools/probe_fed_funds_futures.py
# → derivatives.futures.curve, symbol="ZQ", provider="yfinance" returns 16 expirations
# → front contract (2026-10) implies 3.88%, EQUAL to measured DFF and EFFR (both 3.880)
# → inside the 3.75-4.00% DFEDTARL/DFEDTARU range
# → SOURCE DEFECT: 6 of the 16 expirations carry a price near 47-48 → ~52% implied rate,
#   deterministic across three calls (min 47.64, max 96.12 every time)
```

**A second, independent defect: the probe itself had to be fixed to reach that verdict.** The first
version of `tools/probe_fed_funds_futures.py` walked the route registry, printed route-shaped
strings, and closed with *"VERDICT CRITERIA: … requires a futures settlement or a CME-probability
route"* — a statement of what WOULD be needed, phrased like a conclusion it had not reached. It could
not tell *"the route exists and returns a curve"* from *"no such route exists"*, and its verdict
nudged a reader toward the second. **That is the same class as the mis-recorded finding above: a
route NAME is a hypothesis, and only a CALL tests it.** The probe now has a section D that invokes
the route with the symbol and derives the verdict from what returns, and the double defect is pinned
by tests in `tests/data_layer/test_fed_funds_futures_client.py` (the guard is itself AST-based
because a string match survived a `for route in []:` mutation — see that test's docstring).

The read is now implemented and tested — `data_layer/fed_funds_futures_client.py` (the data leg) and
`models/policy_rules.futures_implied_policy_path` (the model leg), with the six ~52% rows **rejected
and named**, never clamped.

**The mechanism problem, stated precisely — because pass one overstated it.** §22.5 promises the
replacement is *"a body swap, not a caller-facing breaking change"* because *"this function's
signature is stable"*. The premise splits into two claims, and only the first survives:

```bash
uv run python -c "
import inspect
from macro_engine.models.policy_rules import (
    derive_market_implied_policy_path, futures_implied_policy_path)
print(list(inspect.signature(derive_market_implied_policy_path).parameters))
# ['short_yield', 'short_tenor_term_premium', 'futures_curve']  <- two scalars + an OPTIONAL curve
print(list(inspect.signature(futures_implied_policy_path).parameters))
# ['curve', 'proxy_horizon_months']                            <- a CURVE
"
```

* **A pure body swap is impossible.** A curve is a **collection of expirations**. No body can carry one
  through a two-float signature without reconstructing it from the scalars, which §21.0 rule 3 forbids.
  So the *stated mechanism* cannot be used.
* **But the change need not be breaking.** `futures_curve` is **keyword-only with a `None` default**, so
  every pre-existing call site is unaffected. §22.5 promised the *outcome* — *"not a caller-facing
  breaking change"* — and that outcome **is** achievable.

**Pass one mistook "impossible by the promised mechanism" for "impossible".** It read §22.5's *"body
swap"* as the only permitted change and concluded the block was the spec. What the reader now does:
`derive_market_implied_policy_path(curve=…)` **prefers** the futures branch and keeps the proxy
byte-for-byte when the curve is `None`; `build_policy_gap` and `build_us_macro_thesis` thread the
optional curve. The extension is additive, so the promise's *outcome* holds.

**The last step — and it is now DONE. The obligation is DISCHARGED (2026-10-10, third pass).**
`_reasoning_frames` (`api_layer/reasoning_stream.py`) now **fetches** the ZQ curve and threads it down:

```bash
grep -n "_fetch_futures_curve\|futures_curve=futures_curve" src/macro_engine/api_layer/reasoning_stream.py
# futures_curve, curve_detail = _fetch_futures_curve()      <- the LIVE supply
#     futures_curve=futures_curve,                          <- passed to build_policy_gap
#     futures_curve=futures_curve,                          <- passed to build_us_macro_thesis
```

The fetch routes through `fetch_fed_funds_futures_curve`, which routes through `OpenBBClient`
(D-087.25). It is **fail-safe by the operator's choice**: on `FuturesCurveError` / `OpenBBFetchError`
it returns `None` and the **proxy runs**, with the fallback NAMED as a `warning` frame on the
reasoning trace — so a futures outage degrades the market leg but never breaks a live thesis run.
Because the live path now supplies a curve, `PHASE5_REPLACEMENT_OBLIGATION` is **`"discharged"`**: both
halves of §22.5 hold — the market leg is genuinely futures-implied when the source is reachable, AND
the change was additive (the proxy body is intact as the fail-safe).

`tests/models/test_policy_rules.py` pins the discharged state (the tripwire
`test_the_section_22_5_replacement_obligation_is_now_discharged`, which asserts the proxy body
survives, the marker agrees, and — by **AST**, not a string scan — that the fetched value is actually
passed downstream). `tests/api_layer/test_reasoning_stream.py` pins both live paths: the market leg uses
the curve when available, and a fetch failure warns and falls back to the proxy.

⚠️ **A string-based version of that tripwire SURVIVED a mutation**, caught and fixed in the same
change: replacing the fetch with a literal `None` left every searched name present (the import and the
builder call remain) while the value was discarded. The check is now an AST assertion that
`_fetch_futures_curve()`'s result is unpacked and its first element passed as `futures_curve=`. *This is
the fourth instance in two sessions of a textual-trace assertion surviving a mutation a
mechanism-assertion kills — see `MEMORY.md` lesson 4.*

