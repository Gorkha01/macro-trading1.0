# Economic-Integrity Audit — Phase 0 through Phase 3

**Date:** 2026-09-19
**Directive:** FINAL PRODUCTION-GRADE REASONING + ECONOMIC INTEGRITY DIRECTIVE (47 sections)
**Scope:** make the implemented Phase 0–3 system economically honest, production-grade,
fully traceable, reasoning-first. **Phase 4 NOT started.**
**Method:** every claim measured against the live tree and a live US thesis, never
carried forward from a prior report.

Companion documents: `docs/DEFECTS_2026-09-19.md` (the wiring defects), and
`tools/integrity_audit.py` (the machine-produced censor this report summarises).

---

## 0. The one-paragraph verdict

The directive asks for four things, in priority order: **truthfulness > complexity,
traceability > plausible output, evidence > confidence, NO TRADE > fabricated edge.**
Measured against those four, the system is in materially better shape than its
specification: it does not fabricate, it discloses its own gaps, and on the live run
it **correctly refused to make a trade** rather than manufacturing one from a
sub-noise gap. The directive's genuine code gaps — **§25**'s scenario-probability
integrity gate, **§21**'s regime single-factor flag, **§6**'s point-in-time
provenance fields, and **§3/§4**'s reasoning-object contract — **did not exist and
are now implemented or modelled and pinned by 40 new tests.** Everything else the
directive names was either already satisfied, satisfied by construction, or blocked
on data rather than on code. The largest outstanding issue is unchanged and is a
*capability* gap, not an integrity one: **59 of 77 model functions remain
unreachable from the thesis** (DEF-001).

---

## Part A–M — the §45 audit summaries

### A. Models on the live decision path

| | value |
|---|---|
| Model functions defined in `src/macro_engine/models/` | 77 |
| Reachable from the shipped pipeline (call sites in the package) | 18 |
| **Execute on one real `POLICY_PATH_GAP` thesis** | **12** |
| Tier 1–4 with no pipeline caller | 59 (34 live-checked / 25 true orphans) |
| Tier 5 (Phase 5+) falsely wired | **0** |

The 12 that execute: `utc_now`, `observation_as_of`, `output_gap_from_snapshot`,
`output_gap`, `labor_tightness_score`, `inflation_breadth_score`, `taylor_rule`,
`balanced_approach_rule`, `first_difference_rule`, `policy_rule_ensemble`,
`canonical_policy_gap`, `derive_market_implied_policy_path`.

**Does the chain have a reasoning object at every step?** Yes. Every function returns
`ModelResult`, which implements the spec's "reason object": `model_name`, `country`,
`as_of`, `value`, `confidence`, `interpretation`, `context`, `inputs_used`, `warnings`,
`source_family`, `data_quality_flags_present`.

**§3/§4 gap, stated honestly.** The directive lists a wider required contract than
`ModelResult` carries today. Present: economic meaning (`interpretation`), inputs
(`inputs_used`), method (`context`), result (`value`), evidence (`source_family`),
uncertainty (`confidence`), warnings, decision relevance (via the thesis views).
**Not present as typed fields:** `unit`, `assumptions`, `data_provenance`,
`observation_dates`, `release_dates`, `vintage_dates`, `retrieved_at`,
`source_families` (plural), `limitations`, `decision_prohibition`. Of these, `unit`
is carried *ad hoc* on individual schemas (`MarketPricingGap.unit`,
`ScenarioOutcome.unit`) rather than on the contract, and the date fields are the
subject of §6 below. This is a **real, acknowledged gap** and its remediation is
scoped in §6/Part M — it is a schema addition, not a logic change, and it was **not**
implemented in this increment because it touches all 77 models and belongs with a
deliberate contract-version bump.

### B. Blocked / not-computed outputs, and why

| Output | State | Reason |
|---|---|---|
| `regime.state` | **populated** (`late_expansion`) | Wired this increment-set; was `None` (DEF-003, fixed) |
| `compute_fci` | **blocked** | 3 of 5 inputs have no series; §22.5 defers the ACM premium to Phase 5+ (DEF-008) |
| `decompose_yield` | **not wired** | Needs a term premium; none exists. Wiring it half-done is what §22.5 forbids |
| `supercore` / trimmed-mean CPI | **blocked** | BLS key exists; it is a modelling gap, not a credential gap |
| `prior/posterior_probability` | `None` | **Correct** — Phase 5+ by spec (§22.11) |
| Risk suite (7 fns) | not wired | **Phase 4+ by endpoint** (`AGENTS.md:1787`), not an obligation |

Nothing is blocked and *presented as complete*. Every blocked item is either absent
with a `NOT_COMPUTED` note or absent silently in a field whose emptiness is documented.

### C. Proxies in the live path

| Proxy | Unit | Disclosed? | Classification |
|---|---|---|---|
| `derive_market_implied_policy_path` | raw 2yr yield, no term premium | **Yes** — unconditional warning + confidence 0.2 | disclosed PROXY, correct to §22.5 |
| Output gap via `gdp_potential` | Cobb-Douglas ESTIMATE | **Yes** — *"ESTIMATE, not observed"* warning | ESTIMATED |
| `inflation_convergence` measure set | 6 measures, no supercore | **Yes** — *"NOT supercore, which is BLOCKED"* | disclosed substitution-avoidance |
| `scenario_distribution` | `bp_pnl_proxy` | **Yes** — `unit` field says so | **§25-gated, see G** |

Every proxy announces itself. §24's "equity 15yr/5yr duration proxy" **does not exist
in the tree** — there is no such code to classify; `bond_math.py`'s
`macaulay_duration`/`modified_duration` are exact bond mathematics, not proxies.

### D. Economic calibration parameters

Every tunable is a `CalibratedValue` = `{value, calibration_status, note}`. Census of
`config/settings.yaml`: **266 leaves**, distributed as

| status | count | meaning |
|---|---|---|
| `uncalibrated_illustrative` | 123 | placeholder awaiting calibration — DO NOT trust |
| `fitted_assumption` | 75 | estimated from data, documented |
| `institutional_convention` | 29 | industry default |
| `mechanical_rule` | 20 | pre-committed hard rule |
| `externally_sourced` | 0 | (none carry this label) |

**§2 satisfied.** Structural constants (e.g. `percent_to_bp = 100`) are distinguished
from economic parameters, every parameter is named, config-backed, and carries its
calibration status, and `CalibratedValue.is_trustworthy` makes the distinction
machine-readable. **Proportion to keep an eye on:** 123 of 266 leaves are uncalibrated —
those are the ones whose outputs the system itself flags.

### E. Series coverage

- Registry: **46 series**, all `provider: fred`.
- Snapshot fetch list (`snapshot_fields.us`): **22 scalar + 2 curves**.
- Declared-but-never-fetched: `fx_spot`, `commodity_spot`, `equity_index`,
  `ppi_stage_crude`, `ppi_stage_intermediate`, `field_sources`.
- Curves: UST 11 tenors, TIPS 5 tenors — live-populated.
- **DEF-002 (`gdi`) fixed** this increment-set: now 20 observations, GDI/GDP = 0.9926.

The `fx_spot`/`equity_index` emptiness is by design for a US-only thesis but is the
binding constraint on the FCI (DEF-008).

### F. Confidence provenance

`compute_confidence(ConfidenceInputs(...))` is the **sole** producer. AST census for a
live `confidence=<constant>` on a result constructor returns exactly **two** — both
documented census-carriers/adapters whose confidence is a declared placeholder and
**neither is published as a measurement** (AUDIT-007).

**§5 labelling added this increment.** `ModelResult.confidence`'s own schema
description now states explicitly that it is a **reliability** measure, *not* a
probability-of-correctness — the directive's §5 requirement, previously only in prose.

### G. Scenario-distribution status (§25) — **NEW**

`SCENARIO_DISTRIBUTION_UNAVAILABLE` **did not exist anywhere** in the codebase before
this increment and is now implemented:

- `ScenarioDistributionStatus` — closed 3-member vocabulary in
  `models/probability.py`.
- `MacroThesis.scenario_distribution_status` — defaults to the **fail-closed**
  `empty_no_trade`.
- `MacroThesis.scenario_sizing_permitted` — `True` **only** when `calibrated`.
- `scenario_probabilities_are_calibrated()` — reads the config's own
  `calibration_status` leaves, so the gate is **metadata-driven, not hardcoded**.

**Measured live:** every probability leaf is `uncalibrated_illustrative`, so every
live thesis is `SCENARIO_DISTRIBUTION_UNAVAILABLE` and `scenario_sizing_permitted` is
`False`. **§25's prohibition is in force on every path.**

### G-bis. Regime single-factor switch (§21) — **NEW**

§21 forbids the regime label from being a single-factor switch. The pre-existing code
already selected on one axis at a time (a two-threshold partition), but it did so
**silently** — the consumer could not tell whether `late_expansion` was a joint read of
both axes or a growth-only read with the inflation axis not consulted. That ambiguity is
the defect, and it is now closed:

- `RegimeTension` / `REGIME_TENSIONS` — closed 2-member vocabulary in `models/regime.py`.
- `regime_tension(growth, inflation, *, inflation_trend_3m, neutral_band)` — pure
  helper returning `(flag, reasons)`. It fires when **either** (a) inflation momentum
  sits inside the ±neutral band, so the axis read `rising`/`falling` without
  distinguishing a direction and the state was chosen on the growth axis alone, **or**
  (b) growth is `deep_contraction`, for which the classifier returns `recession`
  **regardless of the inflation axis by design** — i.e. the inflation reading was not
  consulted.
- Published in every regime result as `regime_tension` + `regime_tension_reasons`, and
  mirrored into a structured warning so the flag and the prose cannot diverge.

**Measured live:** momentum **+0.1822pp** is outside the ±0.10pp band and growth is
`above_trend`, so the live thesis reports **`NO_REGIME_TENSION`** with empty reasons.
The regime read is genuinely joint *this run* — and on a run where it is not, the
system now says so instead of leaving the reader to infer it.

### H. Sizing reachability (§26/§27)

**Kelly is not reachable from the thesis or the API at all.** AST-asserted:neither `thesis_layer/` nor `api_layer/` imports `risk_budget`. §16.2 Q11 is *"Phase 1:
human-determined; Phase 4+: fractional_kelly"*, so this is correct-by-construction —
there is no live path on which an unsizable distribution could be sized by accident.

§26/§27 are satisfied at the boundary: `KellyInputs` accepts only
`fraction_of_capital` and **raises on `bp_pnl_proxy`**; the producer publishes
`bp_pnl_proxy`; the two cannot be accidentally connected. The placeholder
`raw_kelly = ev / 100` is **absent from the tree** (§22.13), confirmed by AST.

### H-bis. Reasoning-object contract (§3/§4) — **NEW**

`ModelResult` now carries the full field set §4 enumerates, **additively and with
every field optional**:

`unit` · `direction` · `assumptions` · `data_provenance` · `observation_dates` ·
`release_dates` · `vintage_dates` · `retrieved_at` · `source_families` ·
`limitations` · `decision_relevance` · `decision_prohibition`

Two design choices matter more than the list:

- **Every default is an honest "not supplied", never a plausible fill.** A model
  that declares no unit reports `unit=None`, which a consumer MUST read as
  *unknown* — not as *dimensionless*. A default that looked complete would
  destroy §3's entire purpose, which is to make the *absence* of a justification
  visible. Pinned by `TestAbsenceIsVisible`.
- **`decision_prohibition` is the load-bearing field.** It is where a proxy
  declares it must not be traded, an uncalibrated distribution declares it must
  not be sized, and a rule-based label declares it must not be read as a
  probability. It round-trips through serialization unchanged — pinned by
  `TestProhibitionsAndProvenance`, because a prohibition dropped in transit is
  worse than one never written.

**Scope, stated plainly:** the contract is *schematised*, not *populated*. All 77
models can now say these things; they do not yet all do so. Populating is
per-model work, and doing it wholesale would be a large mechanical edit whose
correctness could not be checked in one pass. That is the honest remaining item.

### I. No-trade gates and what fires them

| Gate | Fires on | Live run |
|---|---|---|
| Q6 (gap vs dispersion) | `|gap| <= dispersion` | **FIRED** — 0.26pp < 0.86pp |
| `CONFLICTED` blocks trade | convergence `CONFLICTED` | not reached |
| `_enforce_invalidation_gate` | a live trade with no falsifier | not reached |
| §25 sizing gate | distribution not `calibrated` | **FIRED** — `empty_no_trade` |

The live thesis is **`WATCH`** with 11 warnings and an explicit trigger
`No trade [gap_below_dispersion]`. **This is the system doing exactly what §47 asks:**
NO TRADE in preference to a fabricated edge.

### J. Hardcoded-value census (§1/§42) — AST-level

| §42 item | Result |
|---|---|
| `raw_kelly = ev / 100` | **0** (absent from the tree) |
| Hardcoded confidence on the live path | 2, both documented carriers, neither published |
| Illustrative weights | Confined to config as `uncalibrated_illustrative` leaves |
| Placeholder probabilities/payoffs | Config leaves, **now §25-gated** |
| `datetime.utcnow()` | **0** at AST level (3 text hits are docstring prose) |
| Silent series substitution | 3 `supercore` mentions, **all disclosures**, none a substitution |
| `except: pass` swallows | **0** |
| Empty snapshots | `SnapshotStoreEmptyError` + `strict=` (AUDIT-001 family) |

### K. Timestamp discipline (§6)

- Naive-UTC calls: **0** (AST). All timestamps via `utc_now()` (UTC-aware).
- `ObservationPoint` carries `observation_date`, `value`, `series_id`, `source`,
  `retrieved_at`.
- Point-in-time filtering by `observation_date` is real and well-built
  (`as_of.py`, O-7): the live snapshot withheld **42 forward-dated CBO projections**
  and named the horizon.
- **`release_datetime`, `vintage_datetime`, `decision_cutoff` are now MODELLED but
  NOT POPULATED — and the data is genuinely unreachable, not merely unimplemented.**
  Measured 2026-09-19: the FRED `economy.fred_series` payload returns only `date` +
  value plus descriptive metadata — **no `realtime_start`/`realtime_end`**;
  `economy.fred_release_table` returns a **table of contents with no date field at
  all** (keys are `element_id`, `element_type`, `level`, `line`, `name`, `parent_id`,
  `symbol` — verified, zero date-like fields); `economy.calendar` raises
  `TimeoutError` on the FRED route and demands credentials on `fmp`/
  `tradingeconomics`. Those two endpoints are the *only* release-related routes in
  the platform's OpenAPI spec. So the schema now lets the system **name** the gap
  while keeping it **visible**: `release_datetime=None` means UNKNOWN and is never
  back-filled from `observation_date`. The consequence is written into
  `as_of.py`'s module docstring in bold: **the point-in-time filter is sufficient
  but not sound** — an `as_of` inside one reporting lag of the newest observation
  may admit not-yet-public data, so the honest use today is backtesting at or after
  the release, not replaying a decision made before it.

### L. Live-data fact sheet (snapshot `2026-09-19 16:28Z`)

- Build: **22/22 fields succeeded**, 0 failures.
- Ranges: CPI headline 334.131 @ 2026-08; unemployment 4.10; fed funds 3.63;
  SOFR 3.85; IORB 3.90; ON-RRP 3.75; HY OAS 2.70; IG 0.78.
- Curve: UST 2yr 4.67 / 10yr 4.94 (2s10y **+27bp**); TIPS 5yr 2.46 / 10yr 2.61
  (10yr breakeven **+2.33%**).
- Reading: positively-sloped curve, properly-ordered administered corridor,
  tight-but-not-stressed credit, unemployment 4.10 — a **normalising, non-crisis US**.

### M. Limitations the system discloses about itself

On the single live run: **11 warnings**, every one traceable to a real data condition —
Cobb-Douglas estimate, 42 withheld projections, NFP weighted low deliberately, 86bp
dispersion between the 50/100bp bands, no term-premium adjustment, Phase-1
three-measure proxy, sign-test weakness. Plus **19 derivation notes** carrying
value + source + window for every derived input.

The system's failure mode is **under-delivery with disclosure**, which is the correct
mode. That is why the central defect (DEF-001) is a *wiring* gap and not a fabrication
scandal.

---

## Part §46 — one real live US thesis, 18 questions

Thesis `us-2026-09-19-15fbcac3`, live, 2026-09-19.

| # | Question | Answer | Label |
|---|---|---|---|
| 1 | What is the growth read? | Output gap **+0.83%** above potential | `MODELLED` |
| 2 | What is the inflation read? | CPI **+3.35% YoY**, breadth 0.31 | `OBSERVED`+`DERIVED` |
| 3 | What is the labor read? | Unemployment **4.10%**, tightness percentile-based | `OBSERVED` |
| 4 | What is the regime? | **`late_expansion`**, growth `above_trend`, inflation `rising`, **`NO_REGIME_TENSION`** (momentum +0.18pp, outside the ±0.10pp band), confidence 0.30 | `MODELLED` + `INTERPRETATION` |
| 5 | What do the policy rules say? | Taylor **4.94%**, Balanced **5.36%**, First-diff **4.36%**, ensemble median **4.94%**, dispersion **~86bp**, MIXED | `MODELLED` |
| 6 | Is the gap significant? | **NO** — raw gap **+0.26pp** inside dispersion **0.86pp** | `DERIVED` + `BLOCKED` (Q6) |
| 7 | What does the market price? | **2yr 4.67%** — a **raw, term-premium-contaminated** proxy, *not* FFF-implied | **`PROXY`** + `WARNING` |
| 8 | What is the curve shape? | 2s10y **+27bp**; 10yr breakeven **2.33%** | `OBSERVED`+`DERIVED` |
| 9 | Growth/income divergence? | GDP +6.56% vs GDI +6.61% YoY, divergence −0.05pp, not significant | `DERIVED` |
| 10 | What instrument? | **NONE** — no clean edge | `BLOCKED` |
| 11 | Sizing? | **NONE.** Scenario distribution `empty_no_trade`; `scenario_sizing_permitted=False` | **`BLOCKED`** (§25) |
| 12 | What are the scenarios? | **No distribution** — the verdict cannot carry a thesis | `BLOCKED` |
| 13 | What invalidates it? | Gap must exceed rule dispersion; currently 0.26pp vs 0.86pp | `ASSUMPTION` |
| 14 | Catalysts? | Calendar resolved or explicitly `[]` | `OBSERVED` |
| 15 | Convergence? | **`NO_SIGNAL`** — every pillar read neutral | `MODELLED` |
| 16 | Source independence? | Counted from `EvidenceSourceFamily` tags | `DERIVED` |
| 17 | What is uncertain? | 11 warnings; output gap inherits Cobb-Douglas uncertainty; market leg contaminated | `WARNING` |
| 18 | Decision? | **`WATCH` — NO TRADE.** Trigger: `gap_below_dispersion` | `INTERPRETATION` |

**The thesis answers every question, and where it cannot, it says so rather than
guessing.** Questions 6, 10, 11, 12 are `BLOCKED` — and that is the correct output.

---

## Section 47 — the tie-breakers, assessed

| Principle | Assessment |
|---|---|
| Truthfulness > complexity | The system returns `None`/`[]`/`NOT_COMPUTED` with a reason in preference to a plausible number |
| Traceability > plausible output | 19 derivation notes + 11 warnings on one thesis; every input names its source and window |
| Evidence > confidence | Confidence is reliability-only and mostly modest (0.2–0.7); the ensemble reports dispersion rather than pretending to a point estimate |
| **NO TRADE > fabricated edge** | **Demonstrated live**: the gap is sub-noise, so the system stands down |

---

## What changed in this increment

| File | Change |
|---|---|
| `src/macro_engine/models/probability.py` | **NEW** `ScenarioDistributionStatus` (§25) + `scenario_distribution_status()` |
| `src/macro_engine/thesis_layer/scenarios.py` | **NEW** `scenario_probabilities_are_calibrated()` — metadata-driven calibration read |
| `src/macro_engine/thesis_layer/schemas.py` | `scenario_distribution_status` field (fail-closed default) + consistency validator + `scenario_sizing_permitted` property |
| `src/macro_engine/thesis_layer/builder.py` | Stamps the status on both the live path and the stand-down path |
| `src/macro_engine/models/contracts.py` | `confidence` description now states **reliability, not probability-of-correctness** (§5); **+12 reasoning-object fields** (§3/§4), all optional so no call site breaks |
| `src/macro_engine/models/regime.py` | **NEW** `RegimeTension`/`REGIME_TENSIONS` + `regime_tension()` (§21); classifier publishes `regime_tension` + reasons + structured warning |
| `src/macro_engine/data_layer/schemas.py` | **+`release_datetime`/`vintage_datetime`/`has_known_release_timing`** on `ObservationPoint`; **+`decision_cutoff`** on `MacroDataSnapshot` (§6) |
| `src/macro_engine/models/as_of.py` | Docstring now states the point-in-time filter is **sufficient but not sound** (§6) |
| `tests/thesis_layer/test_scenario_distribution.py` | +6 §25 tests |
| `tests/thesis_layer/test_integrity_gates.py` | **NEW** 11 tests (§25/§26/§27 + Kelly-unreachability AST guard) |
| `tests/models/test_regime.py` | +7 §21 tests (`TestRegimeTension`) |
| `tests/models/test_reasoning_contract.py` | **NEW** 11 tests (§3/§4 contract: absence-is-visible, prohibitions round-trip, extra still forbidden) |
| `tests/data_layer/test_phase1_data_layer.py` | +5 §6 tests (`TestPointInTimeProvenance`) |
| `tools/integrity_audit.py` | **NEW** — the §45/§46 censor, `--strict`-capable |

**Gates after:** `ruff` clean · `ruff format` clean (205 files) · `mypy --strict`
clean (67 source files) · **pytest 2113 passed, 1 skipped, 0 failed** (full suite,
live tests included) · reachability Tier 1–4 gap unchanged at 59 (no new wiring
this increment).

**Tool correction made while re-measuring.** Re-running the reachability audit
after adding `regime_tension` reported the gap as **60**, with the new function
listed as a *true orphan*. It is not one: `regime_tension` is called at
`regime.py:598` from inside `classify_regime_rule_based`, which **is** pipeline-wired.
The audit skipped the defining module wholesale (a guard against counting its own
docstring prose as a caller), so it could not see a same-module call. Fixed by
adding a `local` bucket plus a **one-hop** resolution: a helper called by a wired
function is reported as wired, in a form that keeps the weaker evidence legible
(`<- regime.py (via classify_regime_rule_based)`). One hop only, deliberately —
counting two removes would invent reachability. With the fix the gap is **59**,
matching the pre-existing figure, now measured more accurately.

---

## Open items for your decision — and the honest scope of what remains

1. **§3/§4 contract widening — DONE (additively).** `ModelResult` now carries the
   full reasoning-object field set: `unit`, `direction`, `assumptions`,
   `data_provenance`, `observation_dates`, `release_dates`, `vintage_dates`,
   `retrieved_at`, `source_families`, `limitations`, `decision_relevance`,
   `decision_prohibition`. **Every field is optional and defaults to an honest
   "not supplied"** — `unit=None` means *unknown*, not *dimensionless* — so no
   existing construction site broke (2113 passed). What is **not** done is
   *populating* them across all 77 models: that is per-model work, and doing it
   wholesale would be a large mechanical edit whose correctness could not be
   checked in one pass. **Recommend: populate field-by-field as each model is
   next touched**, starting with the models on the live decision path.

2. **§6 release/vintage modelling — MODELLED, NOT POPULATED (measured dead end).**
   `ObservationPoint` now carries optional `release_datetime` / `vintage_datetime`
   and a `has_known_release_timing` predicate; `MacroDataSnapshot` carries
   `decision_cutoff`; `as_of.py`'s docstring now states the sufficiency-not-soundness
   limitation in bold. **Measured 2026-09-19, the data is genuinely unreachable:**
   `economy.fred_series` returns only date + value; `economy.fred_release_table`
   returns a table of contents with **no date field at all** (verified: keys are
   `element_id`, `element_type`, `level`, `line`, `name`, `parent_id`, `symbol`);
   `economy.calendar` raises `TimeoutError` on the FRED route and demands
   credentials on the `fmp`/`tradingeconomics` routes. Only those two endpoints
   exist in the platform's OpenAPI spec. **So the fields are modelled so the gap
   is *nameable*, and left `None` so it stays *visible*.** Recommend revisiting
   when a credentialed calendar provider is available.

3. **DEF-001 remains the largest item** — 59 unwired Tier 1–4 functions (7 of them
   Phase 4+ by endpoint). Unchanged by this increment, and correctly so: the directive
   said *integrity first, no Phase 4*.

4. **Multi-country is Phase 5 by design** (§22.3). No `INSTRUMENT_REGISTRY` exists;
   `build_snapshot` raises for non-`us`. The expectation should be set accordingly.

5. **`externally_sourced` is an unused calibration label** (0 of 266 leaves). When a
   value genuinely comes from outside (e.g. a published equilibrium rate), use it —
   otherwise consider removing it to keep the vocabulary honest.

---

## Bottom line

**The integrity directive's core requirements are met, and its three genuine code
gaps are closed**: §25's distribution gate, §21's regime-tension flag, and §6's
point-in-time provenance fields. The system does not fabricate, cannot size an
uncalibrated distribution, does not use naive UTC, does not silently substitute
series, cannot present a single-axis regime read as a joint one without saying so,
and correctly refuses to trade on a sub-noise gap.

What remains is honest and named: (a) **populating** — not schematising — the
reasoning fields across all 77 models; (b) release/vintage **data**, which is
unreachable on this installation rather than unimplemented; and (c) the standing
capability gap DEF-001. None is an integrity failure. **No Phase 4 work was
started.**
