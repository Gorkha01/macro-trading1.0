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
| How many genuine *capability* gaps remain? | **2** — multi-country, and FX-forward/market-data coverage. **GARCH closed 2026-10-09 (§2.2); the crisis-shock engine closed the same day (§2.3.1 + §2.3.2), simulation half and scenario library included.** |
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


### 2.4 Multi-country (`de`, `jp`, `gb`) — **not implemented** (confirmed)

| Check | Result |
|---|---|
| `config/settings.yaml` → `country.implemented` | `["us"]` — with the comment *"Adding de/jp/gb requires its OWN data sources, its OWN central-bank reaction function, and its OWN instrument set — not a label change."* |
| `country.enabled` | `["us"]` |
| What exists for other countries | **Guards, not implementations.** Three functions raise `NotImplementedError` for any non-`us` country (`orchestration.py:1764`, `gdp_nowcast.py:571`, `regime.py:1234`); `snapshot_builder.py:846` raises for any country not in `country.implemented`. |
| What is genuinely *data-ready* for other countries | Three FX-reserve series only: `fx_reserves_japan`, `fx_reserves_uk`, `fx_reserves_china` (`config/series_registry.yaml:1744/1762/1779`), plus ISO-3 code maps in `em_vulnerability.py`. These exist because `check_trilemma_tension` NEEDS them as **fixtures** for the 1992/1997 case studies — a different act from supporting those countries as thesis countries (D-048). |
| A cross-country *trade* | `instrument_selection.py:121` defines `BLOCKED_MULTI_COUNTRY_NOT_BUILT`, returned for every `CROSS_COUNTRY_DIVERGENCE` thesis instead of an instrument |

**Status: OPEN, and correctly so.** AGENTS.md §22.3 (Finding #3) explicitly retracted any claim of
multi-country generality: *"Phases 0–4 build a US-only system. … `country: str = "us"` is not a
generalization — it is a label on a system that currently only works for one value of it."*
Multi-country is **Tier 5+**, and per §22.3 it is not one task but **three per country** (verified
sources, a genuinely distinct central-bank reaction function, and an instrument set). The ECB's
20-country compromise, the BoJ's deflation-scar bias, and the PBoC's non-Western reaction function
each need *different logic*, not a relabelled Taylor Rule.

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

**Three things are genuinely broken or missing:**

| # | Gap | Evidence | Nature |
|---|---|---|---|
| 1 | **FX forward points / cross-currency basis — HARD BLOCKED** | `config/series_registry.yaml:1908` — `blocked: fx_forward_rate`. Measured **2026-09-25 (D-108)** with three independent probes: (1) the OpenBB route inventory walks to **443 routes and none matches forward/swap/basis** under `currency` or `fixedincome`; (2) CME futures proxies `6E=F` / `6J=F` / `6B=F` all return `EmptyDataError` via yfinance; (3) FRED's H.10 family (`DEXUSEU`, `DEXJPUS`, …) is **spot only** — the release carries no forwards. **Consequence: `cip_check` takes `forward` as an INPUT and its arithmetic is complete, but its LIVE check cannot run, so the market's own CIP deviation cannot be measured on this build.** | Data block — no source on this install |
| 2 | **Four more blocked registry items** | Active `blocked:` entries are **5 in total** (with `fx_forward_rate`): `iron_ore_change_pct` (L1832), `supercore_direction` (L1844), `conference_board_lei` (L1861), `inflation_surprise_bp` (L1876), `fx_forward_rate` (L1909). A sixth, `ppp_implied_rate` (L1841), is **commented out**, not active. These are the **§21.4 Loophole Ledger** — the system returns `"unavailable"` rather than a plausible number, which is the intended behaviour, not a defect. | Loophole Ledger — by design |
| 3 | **`fx_spot` / `commodity_spot` / `equity_index` declared but never filled** | `schemas.py:337-339` declares all three (`dict[str, list[ObservationPoint]]`); `validation.py:735` validates `fx_spot`; `persistence.py:100` lists all three in `MAPPING_SERIES_FIELDS` — but **`snapshot_builder.py` never assigns any of them.** The plumbing exists; the fetch does not. Spot FX reaches models only where a live check pulls it explicitly. | Actionable — see 2.5.1 |

**Why these are not "Phase 5+ deferrals" like the others.** The shock engine is deferred
because a *dependency* is withheld — as GARCH was until 2026-10-09, when its gate opened and it
shipped (§2.2). Item 1 is blocked because **no source on this installation returns
the data**. Item 2 is a **recorded, deliberate refusal** (§21.4). Item 3 is **unfinished wiring**.
Only item 1 is a plan; the other two are a decision and an omission respectively.

#### 2.5.1 Revisit — the concrete next action on each

| # | Next action | Blocker to clear first |
|---|---|---|
| 1 | Re-probe FX forwards on a schedule (the block is recorded precisely so it *can* be re-probed). Candidate sources already identified in the registry note: any provider publishing forward points or a cross-currency basis — a licensed source, or CME settlement data via a credentialed provider (`fmp` / `polygon`). **The registry records that both currently fail on MISSING CREDENTIALS rather than a missing product** — i.e. this is potentially a *config* fix, not a code fix. | Credentials / licensed feed |
| 2 | No action — leave as `blocked:` so the block remains re-probeable. Any attempt to populate these would violate §21.0 rule 3 (*"no input may be invented"*). | None (intentional) |
| 3 | **Populate two of the three now.** `commodity_spot` and `equity_index` have verified FRED routes already in the registry (`metals_*`, `gold_*`, `crude_inventory_weekly`, `sp500_index`, `VIXCLS`). Only `fx_spot` is genuinely source-blocked, sharing item 1's block. Decide whether `snapshot_builder` should assign the two that are reachable. | A decision, not a dependency |

**Note on item 3:** it is the only one of the three where a *partial* fix is available today, and it is
also the only one that is currently invisible to any test — the fields exist on the schema, validate
clean, and persist, so an empty dict looks the same as "no data this run."

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
| `extensions/scenario_engine.py` | not built at all — see 2.3 | AGENTS.md:1749 |

Neither `monetary.py` nor `volatility.py` has ever existed in this repo's history. This is a
**spec/implementation naming divergence**, not a `bd96d5c` casualty (that re-init deleted *committed*
files, which `git log --all` can still find).

### 2.8 Deliberately-empty config surfaces

| Item | Location | Why it is empty |
|---|---|---|
| `bayesian.likelihoods.table: {}` | `config/settings.yaml:5301` | Populating it needs historical evidence-vs-outcome data (Phase 5+). Empty means `bayesian_update()` **refuses to run** rather than defaulting to a 0.5/0.5 likelihood ratio that would silently render the update a no-op. `config.py:4784` enforces this. |
| `country.implemented: ["us"]` | `config/settings.yaml:88` | §22.3 — US-only through Phase 4. `multi_country` (`de`, `jp`, `gb`) is Tier 5+. |
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
| `statement_text_diff` | `models/policy_rules.py:1172` |

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
| `extensions/scenario_engine.py` + `scenarios/*.yaml` | **Deferred — genuine gap** (distribution layer is done) | `vectorbt` / none |
| Multi-country (`de`, `jp`, `gb`) | **Deferred — genuine gap** (guards in place; `BLOCKED_MULTI_COUNTRY_NOT_BUILT`) | per-country series set + reaction function (§22.3: three tasks per country) |
| FX forward points / cross-currency basis | **Blocked — data unavailability**, not a plan | no source on this install (3 probes, D-108) |
| `fx_spot` / `commodity_spot` / `equity_index` as snapshot fields | **Plumbing exists, fetch does not** | `snapshot_builder.py` never populates them |
| 4 further Loophole-Ledger blocks (`iron_ore_change_pct`, `supercore_direction`, `conference_board_lei`, `inflation_surprise_bp`) | **By design — returns "unavailable"** | §21.4 — no source, and inventing one is forbidden || `bayesian.likelihoods.table` (data) | Deferred | historical evidence-vs-outcome data |
| Kalman-filtered `r_star` | Deferred | `statsmodels.tsa.statespace` |
| `models/monetary.py`, `models/volatility.py` (paths) | Doc-only divergence | — |

**Four genuine capability gaps: GARCH, the crisis-shock engine, multi-country, and FX-forward
coverage (a data block, not a plan).**
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
git log --all --oneline -- src/macro_engine/models/volatility.py   # empty

# 5. Scenario shock engine
ls -d scenarios/ 2>&1                            # No such file or directory

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
