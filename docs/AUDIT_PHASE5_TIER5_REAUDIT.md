# RE-AUDIT FINDINGS — Phase 5+ / Tier 5 (23 functions), FRESH PASS

**Re-audit run:** 2026-09-29, `HEAD = c61a6ed204303ffb0465a96d50d135969a63d0a7` (= `origin/main`).
**Brief:** `docs/AUDIT_PHASE5_TIER5_BRIEF.md`.
**Prior audit:** `docs/AUDIT_PHASE5_TIER5_FINDINGS.md` (run at `HEAD = c16427d`) — 22 CLEAN · 1 DEFECT
(`statement_text_diff`, fixed at D-126). **This is a fresh INDEPENDENT pass**, not a re-read of that
document: every check is re-measured against the current tree.
**Rule:** every claim MEASURED (command + output). No `src/` changes. One function at a time.

**Resolution note (added after the pass):** the two DEFECTs below (functions 14 and 15) were fixed in a
separate increment, **D-129** (`docs/DECISIONS.md:21482`), with a guard test + a defect-reintroduction
mutant each. The cards carry a **RESOLVED at D-129** block with the fix and its guard-kill measurement.
The audit findings themselves are unchanged — a reader can see exactly what the fresh pass found and how
it was closed.

**Status legend:** `CLEAN` (positive measurement) | `DEFECT` (measured fault) | `UNMEASURED` (no measurement).

---

## PRE-FLIGHT (re-derived, not carried)

```
$ git rev-parse HEAD
c61a6ed204303ffb0465a96d50d135969a63d0a7
$ git status --short
(clean)
$ grep -rn "MUTANT|if False:|if True:|and True:|or False:" src/macro_engine/
(no matches)
```

**Tier-5 table re-derived** (`grep -rn "def <name>" src/macro_engine/`): all **23** names resolve to a
real `def`. File map confirmed identical to brief §2.

**Byte-check vs the audited HEAD `c16427d`** (`git diff --stat c16427d..HEAD -- <file>`):
**22 of 23 Tier-5 hosting files are byte-IDENTICAL**; only `policy_rules.py` (function 23) changed
(+78/−24: D-126 confidence product, D-127 the two `_TILT_*_ADDITIONS` members). So the *source* of
functions 1–22 is unchanged — but this pass re-measures each check rather than trusting the prior card.

**Shared gates (all green at session start):**

| Gate | Result |
|---|---|
| `ruff check src tests tools scripts` | **All checks passed** |
| `ruff format --check ...` | **292 files already formatted** |
| `mypy --strict ...` | **Success: no issues in 292 source files** (= format count, D-035 ✅) |
| full suite (`--junitxml`) | **4101 passed / 0 failed / 0 errors / 1 skipped** (4102 total, default `not live and not slow`) |
| reachability | Tier-5 SCRIPT-ONLY **21** + NO-CALLER Tier-5 **1** = **22 unwired** |
| `sweep_health.py` (LAST) | **52 sweeps · 0 leftovers · 0 shapes · 0 committed · 0 failures · OK** |

---

## FUNCTION 1 — `cip_check` (`src/macro_engine/models/fx_carry.py:533`)

**DECISION:** D-108. **SPEC CITE:** §6.7.

| # | Check | Result |
|---|---|---|
| A | MATH | **PASS** — hand case reproduced to every digit + the `basis == (1+i_d)*dev_frac` identity holds to 1e-12 |
| B | ECONOMICS | **PASS** — at exact parity deviation=0.0/severity=none; quote-inversion normalizes `1/1.10→1.10` and returns the identical deviation |
| C | WIRING | **PASS** — 7 fields, annualised-decimal contract documented; inversion once, before the identity |
| D | DATA | **PASS (honest block, RE-PROBED)** — `fx_forward_rate` still not reachable (`obb.currency` = `price/search/snapshots` only) |
| E | INPUT-TAKEN | **PASS** — 7 declared fields = 7 read in body (AST-measured) |
| F | INTEGRATION | **PASS (known-open)** — unwired in `src/`; exercised by `scripts/live_cip_check.py` |
| G | CONFIDENCE | **PASS** — `compute_confidence(...)`, heuristic flag from `_cip_bands_are_calibrated()` |
| H | EVIDENCE | **PASS** — `mutation_fx_carry.py` **171/171 killed**, 0 survivors; sidecars byte-verified + removed |

**A — MATH (measured):**
```
$ uv run python -c "... cip_check(CIPInputs(spot=1.10, forward=1.11, i_domestic_annualized=0.04, i_foreign_annualized=0.02, tenor_days=90, day_count_basis='actual_360')) ..."
HAND implied_forward = 1.10547264  published = 1.10547264
HAND deviation_pct   = 0.409541    published = 0.409541
IDENTITY basis_period 0.004136363636 == (1+i_d)*dev_frac 0.004136363636 -> True
```

**B — ECONOMICS / QUOTE CONVENTION (measured):**
```
AT PARITY: deviation_pct = 0.0  severity = none  side = none
F>implied: deviation_pct = 0.1  side = none  basis_bp = 40.4
INVERTED quote: normalized spot = 1.1 forward = 1.11 inverted = True
  deviation_pct = 0.409541  (same as the direct quote — inversion is applied once, before the identity)
```

**D — DATA re-probe (measured):**
```
$ uv run python -c "from openbb import obb; print([n for n in dir(obb.currency) if not n.startswith('_')])"
['price', 'search', 'snapshots']   # still no forward route — the block HOLDS
```

**STATUS: CLEAN.** Class: —. Evidence attached to every check.

---

## FUNCTION 2 — `uip_expected_move` (`src/macro_engine/models/fx_carry.py:1800`)

**DECISION:** D-112. **SPEC CITE:** §6.7.

| # | Check | Result |
|---|---|---|
| A | MATH | **PASS** — exact `((1+i_d t)/(1+i_f t)-1)*100` and simple `(i_d-i_f)*t*100` both reproduced |
| B | ECONOMICS | **PASS** — direction sign correct in all three regimes |
| C | WIRING | **PASS** — annualised-decimal contract, `uip_reliability_value` leaf |
| D | DATA | **PASS** — no forward consulted (by design); rates are caller-supplied |
| E | INPUT-TAKEN | **PASS** |
| F | INTEGRATION | **PASS (known-open)** — script-only |
| G | CONFIDENCE | **PASS (documented exception)** — `fx_carry.uip_reliability_value` (0.15), a config leaf with a `[0,1]` validator; §22.8 factors have no "method known to be false" factor |
| H | EVIDENCE | **PASS** — covered by `mutation_fx_carry.py` 171/171 |

**A/B — MATH + DIRECTION (measured):**
```
HAND exact  = 0.497512  published = 0.497512
HAND simple = 0.5       published = 0.5
direction = domestic_depreciation  (i_d>i_f)
i_d<i_f direction = domestic_appreciation
equal direction = flat  move = 0.0
confidence = 0.15
```

**STATUS: CLEAN.** Class: —.

---

## FUNCTION 3 — `ppp_valuation` (`src/macro_engine/models/fx_carry.py:2314`)

**DECISION:** D-117. **SPEC CITE:** §6.7 / Module 9.2.

| # | Check | Result |
|---|---|---|
| A | MATH | **PASS** — `(spot-ppp)/ppp*100` and ratio reproduced |
| B | ECONOMICS | **PASS** — status correct overvalued/undervalued/at_parity |
| C | WIRING | **PASS** — spot needs the PPP leg (fetch or caller override) |
| D | DATA | **PASS** — `ppp_implied_rate` fetch is the live path; caller override for deterministic tests |
| E | INPUT-TAKEN | **PASS** |
| F | INTEGRATION | **PASS (known-open)** — script-only |
| G | CONFIDENCE | **PASS (documented exception)** — `fx_carry.ppp_reliability_value` (0.2) |
| H | EVIDENCE | **PASS** — `mutation_fx_carry.py` 171/171 (P1–P5 mutations cover this function) |

**A/B — MATH + STATUS (measured):**
```
HAND dev = 10.000000000000009  pub = 10.0  ratio pub = 1.1  status = overvalued  conf = 0.2
spot<ppp status = undervalued
at-parity status = at_parity
```

**STATUS: CLEAN.** Class: —.

---

## FUNCTION 4 — `carry_score` (`src/macro_engine/models/fx_carry.py:906`)

**DECISION:** — (D-109 lineage).

| # | Check | Result |
|---|---|---|
| A | MATH | **PASS** — score = differential / max(vol, floor); both branches reproduced |
| B | ECONOMICS | **PASS** — outcome sign correct (pos/neg/zero) |
| C | WIRING | **PASS** — ANNUALISED DECIMALS, both inputs same unit (the naming prevents the unit trap) |
| D | DATA | **PASS** — inputs caller-supplied (no rate-diff / FX-vol field exists) |
| E | INPUT-TAKEN | **PASS** |
| F | INTEGRATION | **PASS (known-open)** — script-only |
| G | CONFIDENCE | **PASS** — `compute_confidence(...)` with `_carry_floor_is_calibrated()` |
| H | EVIDENCE | **PASS** — `mutation_fx_carry.py` 171/171 |

**A/B — MATH + BRANCHES (measured):**
```
configured volatility_floor = 0.1
denominator = 0.1 (floor binds)  HAND 0.02/0.1 = 0.19999999999999998  pub score = 0.2
vol above floor: binds = False  denom = 0.3  score = 0.066667  HAND = 0.06666666666666665
F4 neg diff outcome = long_foreign  score = -0.2
F4 zero diff outcome = flat  score = 0.0
```

**STATUS: CLEAN.** Class: —. (The apparent 0.2-vs-0.25 discrepancy was the floor binding — the floor
is the denominator, and the code is right.)

---

## FUNCTION 5 — `dollar_smile_regime` (`src/macro_engine/models/fx_carry.py:1320`)

**DECISION:** D-111.

| # | Check | Result |
|---|---|---|
| A | MATH | **PASS** — base rates sum to 1.0; fractions internally consistent |
| B | ECONOMICS | **PASS** — all 3 limbs reachable (D-050 hazard cleared); left dominates regardless of signs |
| C | WIRING | **PASS** — VIX INDEX LEVEL, not a decimal (unit trap documented) |
| D | DATA | **PASS** — growth surprise is caller-supplied (no consensus source; disclosed) |
| E | INPUT-TAKEN | **PASS** |
| F | INTEGRATION | **PASS (known-open)** — script-only |
| G | CONFIDENCE | **PASS** — `compute_confidence(...)`, both thresholds uncalibrated |
| H | EVIDENCE | **PASS** — `mutation_fx_carry.py` 171/171 |

**B — BRANCH REACHABILITY (measured):**
```
vix_threshold = 25.0  sign_boundary = 0.0
labels over grid: {'middle': 24, 'right': 3, 'left': 18}
vix=30 g=1 r=1 -> left    neutral=False
vix=10 g=1 r=1 -> right   neutral=False
vix=10 g=-1 r=-1 -> middle neutral=False
vix=10 g=0 r=0 -> middle neutral=True
```

**A — BASE RATES (measured):**
```
published base rates: left 0.5785, right 0.0674, middle 0.3540  sum = 1.0
1750+204+1071 = 3025  (denominator matches)
```

**STATUS: CLEAN.** Class: —.

---

## FUNCTION 6 — `intervention_capacity` (`src/macro_engine/models/intervention.py:290`)

**DECISION:** D-118. **SPEC CITE:** §20.9 / §22.11.

| # | Check | Result |
|---|---|---|
| A | MATH | **PASS** — direction→label mapping correct; burn-boundary correct |
| B | ECONOMICS | **PASS** — strengthen→RESERVE_CONSTRAINED (finite stock), weaken→MECHANICALLY_UNCONSTRAINED (printing press) |
| C | WIRING | **PASS** — reserves in BILLIONS, fetcher converts from source MILLIONS via named constant |
| D | DATA | **PASS (LIVE, fourth false block re-probed)** — `TRESEGJPM052N` 1,083,420.49 mn → 1083.42 bn |
| E | INPUT-TAKEN | **PASS** — reserves_to_gdp_pct read; its absence disclosed in assumptions |
| F | INTEGRATION | **PASS (known-open)** — script-only; feeds `check_trilemma_tension` conceptually |
| G | CONFIDENCE | **PASS** — the D-118 **product** `compute_confidence()*cap`; supplied 0.03 vs fetched 0.066 |
| H | EVIDENCE | **PASS** — covered by its sweep |

**G — THE CONFIDENCE PRODUCT (measured — the D-118 rule, confirmed intact):**
```
computed(SUPPLIED) = 0.25  cap = 0.12  product = 0.03   (min() would give 0.12)  -> observed 0.03 ✅
computed(FETCHED)  = 0.55  cap = 0.12  product = 0.066  (min() would give 0.12)  -> observed 0.066 ✅
```
A `min()` would have published the cap alone (0.12) on BOTH paths, making the `compute_confidence()`
branch dead code — the exact defect D-118 forbids. The shipped code multiplies; both halves are
load-bearing, and the published number differs between a typed and a fetched reserve.

**D — LIVE FETCH (measured):**
```
MILLIONS_PER_BILLION = 1000.0
jpn -> 1,083,420.49 mn -> 1083.42 bn  chg12m = -11.98%  sym = TRESEGJPM052N
gbr ->   169,355.66 mn ->  169.36 bn  chg12m =  +1.62%  sym = TRESEGGBM052N
chn -> 3,482,385.62 mn -> 3482.39 bn  chg12m =  +2.89%  sym = TRESEGCNM052N
```
Fetched JPN strengthening: capacity = RESERVE_CONSTRAINED_breakable, confidence = 0.066,
provenance = "FETCHED — TRESEGJPM052N @ 2026-08-01 (source unit: millions of USD; converted…)",
source_family = IMF, burn warning fires (CRITICAL_PEG_STRESS setup).

**STATUS: CLEAN.** Class: —.

---
## FUNCTION 7 — `em_vulnerability_checklist` (`src/macro_engine/models/em_vulnerability.py:216`)

**DECISION:** D-119. **SPEC CITE:** §20 / Module 9.4.

| # | Check | Result |
|---|---|---|
| A | MATH | **PASS** — count of failed checks → verdict ladder (0/1/2/3 → LOW/MODERATE/HIGH/CRITICAL) |
| B | ECONOMICS | **PASS** — all three threshold directions correct; `blocks_fx_selection` true exactly at n_failed≥2 |
| C | WIRING | **PASS** — USD-debt share a fraction in [0,1] (unit-error refused) |
| D | DATA | **PASS** — two legs LIVE (World Bank); USD-debt share caller-supplied (no source), disclosed |
| E | INPUT-TAKEN | **PASS** — all three inputs read |
| F | INTEGRATION | **PASS (known-open)** — script-only; gates FX selection by flag |
| G | CONFIDENCE | **PASS** — the D-118 product; 0-legs 0.025, 2-legs 0.06 |
| H | EVIDENCE | **PASS** — covered by its sweep |

**B — THRESHOLD DIRECTIONS (measured):**
```
thresholds: ca_deficit = -3.0  usd_debt_share = 0.5  reserves/ST = 1.0
ALL FAIL: n_failed = 3  verdict = CRITICAL_VULNERABILITY  blocks = True
  failed_checks = ['current_account_deficit_exceeds_3pct_gdp', 'majority_usd_denominated_debt_original_sin', 'reserves_below_short_term_external_debt']
ALL PASS: n_failed = 0  verdict = LOW_VULNERABILITY  blocks = False
TWO FAIL: n_failed = 2  blocks = True
```

**G — THE CONFIDENCE PRODUCT (measured):**
```
computed(0 legs) = 0.25  cap = 0.1  -> product 0.025  (min() would give 0.1)  -> observed 0.025 OK
computed(2 legs) = 0.60  cap = 0.1  -> product 0.06   (min() would give 0.1)  -> observed 0.06  OK
```

**D — LIVE FETCH (measured):**
```
TR fetched: confidence = 0.06, source_family = WORLD_BANK
provenance = FETCHED TUR BN.CAB.XOKA.GD.ZS @ 2024 (per cent of GDP) ;
             FETCHED Reserves / short-term external debt (reserves 185,567,690,700 2025 / ST debt 178,133,840,000 2024)
```

**STATUS: CLEAN.** Class: —.

---

## FUNCTION 8 — `oil_balance_signal` (`src/macro_engine/models/commodities.py:198`)

**DECISION:** D-120. **SPEC CITE:** §6.8.

| # | Check | Result |
|---|---|---|
| A | MATH | **PASS** — `tightness = -deviation` reproduced on all three cases |
| B | ECONOMICS | **PASS** — draw → positive tightness (tightening), build → negative (loosening) |
| C | WIRING | **PASS** — inventory in THOUSAND BARRELS seasonal deviation; spare in MB/D |
| D | DATA | **PASS (LIVE)** — EIA WCESTUS1 + COPS_OPEC both fetch; 15 future rows discarded |
| E | INPUT-TAKEN | **PASS** |
| F | INTEGRATION | **PASS (known-open)** — transmission input, not a trade |
| G | CONFIDENCE | **PASS** — the D-118 product; supplied 0.075, fetched 0.18 |
| H | EVIDENCE | **PASS** — covered by its sweep |

**A/B — TIGHTNESS SIGN (measured):**
```
DRAW -5000: tightness = 5000.0 (HAND = -(-5000)) direction = tightening  conf = 0.075
BUILD +3000: tightness = -3000.0 (HAND = -3000)     direction = loosening
ZERO: tightness = -0.0                              direction = loosening
```

**G/D — PRODUCT + LIVE FETCH (measured):**
```
computed(0 legs)=0.25 -> 0.075 (observed); computed(2 legs)=0.60 -> 0.18; min() would give 0.25
LIVE: tightness = -7761.2  dev = 7761.2  spare = 0.02  conf = 0.18
provenance = FETCHED EIA WCESTUS1 @ 2026-09-18 (level 426,398, seasonal deviation +7,761) ;
             FETCHED EIA COPS_OPEC @ 2026-09-01 (0.02 mb/d; 15 future-dated rows discarded)
```

**STATUS: CLEAN.** Class: —.

---
## FUNCTION 9 — `gold_driver_attribution` (`src/macro_engine/models/commodities.py:528`)

**DECISION:** D-121. **SPEC CITE:** Appendix D / §6.8.

| # | Check | Result |
|---|---|---|
| A | MATH | **PASS** — three-branch layer attribution, Appendix-D order |
| B | ECONOMICS | **PASS** — all-3 → real_yield dominant; real-yield is the MECHANICAL/reversing layer, CB structural/durable, crisis acute — matches Appendix D |
| C | WIRING | **PASS** — real-yield change in BP (10Y TIPS); threshold from config |
| D | DATA | **PASS (LIVE)** — DFII10 + VIXCLS fetch; CB trend is a documented measured block |
| E | INPUT-TAKEN | **PASS** |
| F | INTEGRATION | **PASS (known-open)** — informational only |
| G | CONFIDENCE | **PASS** — product; independence count = **1** (both legs FRED), not 2 |
| H | EVIDENCE | **PASS** — covered by its sweep |

**A/B — LAYER ORDERING (measured):**
```
ALL THREE: dominant = real_yield   active = ['real_yield','cb_diversification','crisis_confidence']
ONLY CB:   dominant = cb_diversification
NONE:      dominant = none_identified
```

**G/D — PRODUCT + LIVE FETCH (measured):**
```
computed(2 legs, 1 provider) = 0.55 -> 0.1925 ; computed(0 legs) = 0.25 -> 0.0875
LIVE: dominant = none_identified  conf = 0.1925
  FETCHED FRED DFII10: 2.85% on 2026-09-24, prior 2.76 => change +9.0 bp (inside the 10 bp threshold)
  central_bank_net_purchases_trend NOT RESOLVED (measured block — World Bank FI.RES.GOLD.CD refuses)
  FETCHED FRED VIXCLS @ 2026-09-22: level 14.21 vs threshold 30.0 => crisis=False
```

**STATUS: CLEAN.** Class: —.

---

## FUNCTION 10 — `metals_complex_divergence` (`src/macro_engine/models/commodities.py:947`)

**DECISION:** D-122. **SPEC CITE:** §20.10.

| # | Check | Result |
|---|---|---|
| A | MATH | **PASS** — all three verdicts reproduced |
| B | ECONOMICS | **PASS** — construction requires aluminum QUIET; broad requires all three falling — mutually exclusive (measured) |
| C | WIRING | **PASS** — changes are `_change_pct` (a level is never read as a change) |
| D | DATA | **PASS (LIVE)** — all 3 legs via FRED (PCOPPUSDM/PIORECRUSDM/PALUMUSDM) |
| E | INPUT-TAKEN | **PASS** |
| F | INTEGRATION | **PASS (known-open)** — informational only |
| G | CONFIDENCE | **PASS** — product; independence count = **1** (all 3 legs one provider), not 3 |
| H | EVIDENCE | **PASS** — covered by its sweep |

**A/B — VERDICTS + MUTUAL EXCLUSIVITY (measured):**
```
CONSTRUCTION: verdict = CHINA_CONSTRUCTION_SPECIFIC
BROAD:        verdict = BROAD_INDUSTRIAL_WEAKNESS
MIXED:        verdict = MIXED_no_clear_pattern
grid cells satisfying BOTH branches: 0 (mutually exclusive — the dead "ambiguous" branch was correctly removed)
```

**G/D — PRODUCT + LIVE FETCH (measured):**
```
computed(3 legs, 1 provider) = 0.55 -> 0.165  (min() would have given 0.30)
LIVE: verdict = MIXED_no_clear_pattern  conf = 0.165
  copper -0.1%, iron ore -2.1%, aluminum -8.2% (all three legs FRED, two vintages each)
```

**STATUS: CLEAN.** Class: —.

---
## FUNCTION 11 — `sector_rotation_prior` (`src/macro_engine/models/equity_macro.py:227`)

**DECISION:** D-123. **SPEC CITE:** §6.9.

| # | Check | Result |
|---|---|---|
| A | MATH | **PASS** — pure lookup; sector lists verbatim |
| B | ECONOMICS | **PASS** — recession → defensive sectors (utilities/staples/healthcare) |
| C | WIRING | **PASS** — `regime_state` typed as the classifier's `RegimeState` Literal (imported, not re-typed) |
| D | DATA | **PASS** — constructed prior, no fetch (correctly declared) |
| E | INPUT-TAKEN | **PASS** |
| F | INTEGRATION | **PASS (known-open)** — script-only |
| G | CONFIDENCE | **PASS** — product; 0.55×0.4 = 0.22 |
| H | EVIDENCE | **PASS** — `mutation_equity_macro.py` (58/58, run below) |

**A/B — MAP EXHAUSTIVENESS (measured):** sector map covers all 9 `REGIME_STATES` (True);
extension regimes = `('slowdown','recovery','reflation')`; recession → `['utilities','staples','healthcare']`; conf 0.22.

**STATUS: CLEAN.** Class: —.

---

## FUNCTION 12 — `duration_sensitivity` (`src/macro_engine/models/equity_macro.py:429`)

**DECISION:** D-124. **SPEC CITE:** §6.9.

| # | Check | Result |
|---|---|---|
| A | MATH | **PASS** — `-duration*(bp/10000)*100` reproduced on 3 cases |
| B | ECONOMICS | **PASS** — rise → negative (down); growth falls exactly 3× value |
| C | WIRING | **PASS** — `style` Literal (not a bare bool); bp band validated |
| D | DATA | **PASS** — constructed (illustrative proxy), declared |
| E | INPUT-TAKEN | **PASS** |
| F | INTEGRATION | **PASS (known-open)** — script-only |
| G | CONFIDENCE | **PASS** — product; 0.55×0.3 = 0.165 |
| H | EVIDENCE | **PASS** — `mutation_equity_macro.py` |

**A/B — FORMULA (measured):**
```
duration_growth = 15.0  duration_value = 5.0
growth +50bp: published = -7.5  HAND = -7.5  direction = down
value  +50bp: published = -2.5  HAND = -2.5
growth -25bp: published = 3.75  HAND = 3.75  direction = up
growth/value ratio = 3.0 (15/5)
band refuses 3000bp: ValidationError
```

**STATUS: CLEAN.** Class: —.

---

## FUNCTION 13 — `factor_tilt_prior` (`src/macro_engine/models/equity_macro.py:623`)

**DECISION:** D-124. **SPEC CITE:** §20.20-E.

| # | Check | Result |
|---|---|---|
| A | MATH | **PASS** — pure lookup; recession row matches the map verbatim |
| B | ECONOMICS | **PASS** — recession → defensive (quality +1, low_vol +1, momentum -1, size -1) |
| C | WIRING | **PASS** — `RegimeState` Literal |
| D | DATA | **PASS** — constructed prior (spec table), declared |
| E | INPUT-TAKEN | **PASS** |
| F | INTEGRATION | **PASS (known-open)** — script-only |
| G | CONFIDENCE | **PASS** — product; 0.55×0.35 = 0.1925 |
| H | EVIDENCE | **PASS** — `mutation_equity_macro.py` |

**A/B — MAP + WARNINGS (measured):** all 9 regimes return the full 5-factor dict; the momentum-crash
warning (the specification's sharpest caveat) is present on every path; conf 0.1925.

**STATUS: CLEAN.** Class: —.

---
## FUNCTION 14 — `monte_carlo_var` (`src/macro_engine/models/risk.py:1224`)

**DECISION:** D-106. **SPEC CITE:** §17.1 / §18.2. **BYTE-CHECK:** `risk.py` byte-IDENTICAL to
`c16427d`.

| # | Check | Result |
|---|---|---|
| A | MATH | **DEFECT (sibling helper)** — `_uniform_correlation_stress` applies `min` not `max` |
| B | ECONOMICS | **DEFECT (same site)** — the fallback stress never raises a positive correlation |
| C | WIRING | PASS — production transform received, not restated (the correct design) |
| D | DATA | PASS — factor vols/weights from the book; no fetch |
| E | INPUT-TAKEN | PASS |
| F | INTEGRATION | PASS (known-open) — no caller in `src/` (Tier-5 script-only) |
| G | CONFIDENCE | **OBSERVATION (era-correct)** — pre-D-118 `compute_confidence()`-only form |
| H | EVIDENCE | **DEFECT (false disclosure)** — the fallback warning claims a stress that did not happen |

### A/B — the defect, MEASURED

`_uniform_correlation_stress` (`risk.py:1192`) DOCSTRING (lines 1195–1207) states, verbatim:

> *"**Raise** every cross-correlation toward `target`; keep the diagonal at 1."*
> *"`min(rho, target)` rather than `max`: a correlation already above the target is left alone, so a
> book whose factors are ALREADY more correlated than the stress level does not have its
> correlations *lowered* by a 'stress'."*

The implementation is `raised = min(correlations[i][j], target)` (line **1218**). Measured from a
clean tree at `c61a6ed`:

```
$ uv run python /tmp/probe_f14.py
target=0.90 -> 0.3   (docstring: RAISE toward target)
target=0.10 -> 0.1   (docstring: does NOT lower)
corr=0.95 target=0.90 -> 0.9  (docstring: left alone)
```

Every one of the three claims is INVERTED by the code. `min` **never raises** a correlation below the
target (0.30 stays 0.30 at target 0.90), and it **does** lower a correlation above the target
(0.95 → 0.90 at target 0.90). The docstring's rationale for `min`-over-`max` describes a `max`
behaviour the code does not implement.

### B/H — end-to-end consequence, MEASURED

Fallback path (`stress_correlations` omitted, `stressed_correlation=0.9`) vs the production path
(`portfolio/risk_budget.py::stress_correlations`, which is correct — it does
`max(current, stressed) if current >= 0 else current`, preserving hedges):

```
$ uv run python /tmp/probe_f14b.py
production: ratio=3.0137 div_norm=0.806226 div_strs=0.974679
fallback  : ratio=2.5000 div_norm=0.806226 div_strs=0.806226
```

* Production: the correlation genuinely breaks — diversification collapses 0.806 → **0.975**.
* Fallback: `ratio = 2.5000` = **exactly the volatility multiple alone**
  (`risk.monte_carlo.stressed_volatility_multiplier = 2.5`); `div_strs = 0.806226` = `div_norm`,
  i.e. **no correlation stress was applied at all**.

### H — the false disclosure

The call site (`risk.py:1363–1369`) warns, verbatim:

> *"No stress_correlations transform was supplied, so a uniform correlation target of 0.9 was applied
> instead."*

For the ordinary positive-correlation book the fallback target (0.9) is ABOVE the book's
correlations (0.3), so `min(0.3, 0.9) = 0.3` — **nothing was applied**, yet the warning says a stress
"was applied". The text names a correlation stress as done; the measurement shows the only surviving
stress is the volatility multiple. A reader of that warning cannot tell the correlation term is
inert. This is a false disclosure (Class H) stacked on the mechanism defect (Classes A/B).

### Why the suite is green despite this

`tests/models/test_monte_carlo_var.py::test_falls_back_to_a_uniform_correlation_stress_and_warns`
(`:696`) asserts ONLY that the warning string contains `"uniform correlation"` — it never checks that
a correlation actually moved. The defect therefore survives a green suite. The production path is
correct and the LTCM-detection tests (`test_a_negative_correlation_is_preserved_by_the_production_rule`,
`:712`) exercise the RECEIVED transform, not the fallback — so no existing test reaches the bug.

### Reachability of the defect

The fallback is reachable whenever a caller omits `stress_correlations` AND passes
`stressed_correlation`. Production wiring (`portfolio/risk_budget.py`) supplies the real transform,
so the live path is unaffected — but the code path and its warning are live and wrong, and
`monte_carlo_var` has **NO caller in `src/`** (Tier-5, script-only), so the fallback is a documented
public branch with no guard rail.

### G — OBSERVATION (era-correct, not a defect)

`monte_carlo_var`'s own confidence (`risk.py:1456`) is the pre-D-118 `compute_confidence()`-only form
— no cap/product. D-106 predates D-118, so this is **era-correct**; recorded as a Class-G OBSERVATION
identical to the prior audit's treatment. (The Function-23 `policy_rules.py` D-126 fix is the model
for how a later increment retrofits this; it is out of scope for a measurement-only audit.)

**STATUS: DEFECT.** Class: A/B (mechanism) + H (false disclosure). Two findings:

1. **`_uniform_correlation_stress` (`risk.py:1218`)** — `min` should be `max` to match its own
   docstring (and the production rule). As written the fallback applies NO correlation stress to a
   normal (positive-correlation) book and LOWERS an already-high correlation.
2. **The call-site warning (`risk.py:1363–1369`)** — claims a correlation stress "was applied" when
   the `min` bug means none was. Fixing (1) fixes (2); they are one defect with two faces.

Recorded for a SEPARATE fix increment — the audit changes no `src/` file (operator: *"without
changing logic"*).

**RESOLVED at D-129** (`docs/DECISIONS.md:21482`). `min` → `max` at `risk.py:1223`; the docstring
(now `:1196–1213`) and the call-site warning (now `:1367–1376`) rewritten to state the `max` semantics
truthfully ("raises toward the target, never lowers"). A guard was added so the defect cannot return
silently: mutant **`M4e`** in `scripts/mutation_monte_carlo_var.py` (`_UNIFORM_RAISE` anchor reverts
`max` to `min`) and test **`test_the_fallback_raises_a_positive_correlation_d129`** in
`tests/models/test_monte_carlo_var.py` (observable = the stressed diversification ratio must exceed the
normal one; `min` leaves it unchanged). **Coverage note:** the fixed path is the *fallback*
(`stress_correlations=None`); `scripts/live_monte_carlo_check.py` passes the *production* transform at
both call sites (`:247`, `:341`), so the fallback's evidence is the unit test + the sweep, not the live
check — the correct §21.0 scope, since the live check proves *wiring* and the fallback is off the
production wiring path.

*Guard-KILL verified (guards are detectors, not mere passers).* Re-applying the mutation by hand
(`max` → `min`) and running the new test alone: **`1 failed`**, with
`AssertionError: stressed diversification ratio 0.806226 is not materially above the normal one
0.806226` — the two ratios are **exactly equal**, which is a direct measurement that `min` applies
**no** correlation stress to a positively-correlated book. The sweep's `M4e` reports the same mutant
**KILLED** in the full 40/40 run.

**Contrast with the prior audit (why a fresh pass was warranted):** `docs/AUDIT_PHASE5_TIER5_FINDINGS.md`
(line 1762) rated `monte_carlo_var` **CLEAN** — *"the model is clean"*, with only an era-correct
Class-G OBSERVATION. That pass did not catch the `min`-not-`max` at `risk.py:1218` or the false
disclosure at its call site. This is direct evidence that the fresh independent pass (operator's
chosen option *"Re-audit all 23 Tier-5 functions"*) surfaced a real defect a prior read-only pass
missed — the reason a re-measure beats a re-read.

---
## FUNCTION 15 — `compute_risk_parity_weights` (`src/macro_engine/portfolio/risk_budget.py:1767`)

**DECISION:** D-071 (Phase 4 opens). **SPEC CITE:** §9.2 / §17.1. **BYTE-CHECK:** `risk_budget.py`
byte-IDENTICAL to `c16427d`.

| # | Check | Result |
|---|---|---|
| A | MATH | PASS — reproduces the closed-form oracle exactly (measured below) |
| B | ECONOMICS | PASS — risk contributions hit the budget, notional ≠ risk, both published |
| C | WIRING | PASS — `RiskBudgetInputs` validates panel/budget rigorously |
| D | DATA | PASS — sample covariance from the caller's panel; window published |
| E | INPUT-NOT-TAKEN | **DEFECT** — `settings.risk.risk_parity_tolerance` is never read |
| F | INTEGRATION | PASS (known-open) — no `src/` caller (Tier-5 script-only) |
| G | CONFIDENCE | **OBSERVATION (era-correct)** — D-071 predates D-118 |
| H | EVIDENCE | **DEFECT (false disclosure)** + no mutation sweep covers this region |

### A — the oracle, MEASURED

Two-asset uncorrelated book, annualised vols 20% / 5%, 50/50 risk budget. The closed-form
risk-parity answer is `w ∝ 1/σ` ⇒ `[0.20, 0.80]` with equal risk contributions.

```
$ uv run python /tmp/probe_f15.py
weights: {'A': 0.200238, 'B': 0.799762}
RCs    : {'A': 0.5, 'B': 0.5}
sum RC : 1.0
worst_target_error: 4.5e-11
converged: True iters: 17
```

Multi-asset (SPY/TLT/GLD, budget 0.40/0.35/0.25) hits the targets to 6 dp exactly
(`RC = {0.25, 0.4, 0.35}`), and `inputs.instruments == sample_covariance(...)[0] == sorted(panel)`,
so the index↔name mapping is reproducible. **A and B are PASS.**

### E — the DEFECT, MEASURED

`compute_risk_parity_weights` accepts `tolerance: float = DEFAULT_RISK_PARITY_TOLERANCE`
(`= 1e-10`, line 1770) and passes **that parameter** to `_solve_risk_parity` (line 1846). The
module comment above `DEFAULT_RISK_PARITY_TOLERANCE` (lines 1559–1562) states, verbatim:

> *"Read from config as `risk.risk_parity_tolerance`; the module default here is only a parameter
> default for a directly-constructed call and **is never used by `compute_risk_parity_weights`,
> which reads the config**."*

**The function does NOT read the config.** Every `settings.risk` access in the body is:

```
$ grep -n "settings.risk" src/macro_engine/portfolio/risk_budget.py
1834:    annualization = settings.risk.risk_parity_annualization_periods
1835:    stress_correlation = settings.risk.stress_corr
1885:    if max_weight_shift > settings.risk.risk_parity_stress_shift_threshold:
```

`risk.risk_parity_tolerance` appears **nowhere** in the call path, and no file anywhere passes
`tolerance=` to the solver (`grep -rn "tolerance=" risk_budget.py` → empty). The parameter default
is what is actually used. Measured — the parameter moves the solve; the config leaf cannot:

```
$ uv run python /tmp/probe_f15b.py
config tolerance (shipped): 1e-10
default (=1e-10 param)   iters=17 converged=True worst_err=4.50e-11
param tol=1e-14          iters=24 converged=True worst_err=0.00e+00
param tol=1e-2           iters= 4 converged=True worst_err=2.54e-03
```

The parameter is fully live (1e-2 → 4 sweeps; 1e-14 → 24 sweeps). The config leaf
`risk.risk_parity_tolerance_value` — created with a 15-line note (`settings.yaml:1519–1533`) whose
whole subject is *why this function's tolerance is 1e-10* — **has no effect on the function.** Edit
the YAML and the solve is byte-identical. The leaf is dead for the only function it was authored to
parameterise.

### H — the false disclosure, and why no gate catches it

The comment's claim ("never used by `compute_risk_parity_weights`, which reads the config") is the
inverse of the code — a reader is told the config governs when it is the parameter default. The three
readers of the property exist:

```
$ grep -rn "\.risk_parity_tolerance\b" src/ tests/ scripts/ tools/
risk_budget.py:1560   (the comment making the false claim)
tests/portfolio/test_risk_parity.py:793   assert perturbed.risk_parity_tolerance == approx(1e-6)
tests/portfolio/test_risk_parity.py:808   assert risk.risk_parity_tolerance == approx(1e-10)
scripts/live_risk_parity_check.py:146      (prints it in a banner)
```

The two tests assert the **property parses and can be perturbed** — neither calls
`compute_risk_parity_weights` with the perturbed config to show the solve changes (it would not).

**No mutation sweep covers this region.** `test_risk_parity.py` appears in no `mutation_*.py`
`PYTEST_TARGETS`; the sweeps that rewrite `risk_budget.py` (`mutation_voltarget.py`,
`mutation_thesis_position.py`) target the vol-target / thesis-position regions, not risk parity.
So the defect is unreachable by every gate.

### G — OBSERVATION (era-correct, not a defect)

`compute_risk_parity_weights`' confidence is the D-071-era `compute_confidence()`-only form
(`is_heuristic_not_calibrated=True`) with no cap/product. D-071 predates D-118, so this is
**era-correct**, recorded as a Class-G OBSERVATION like `monte_carlo_var` (D-106).

### Check H — test evidence

`tests/portfolio/test_risk_parity.py` = **33 tests**, including the closed-form two-asset oracle
(`test_the_ccd_step_solves_the_two_asset_oracle_exactly`). No mutation sweep covers the region (see
above) — the suite is the only evidence, and it passes on the otherwise-correct arithmetic while the
tolerance defect stands.

**STATUS: DEFECT.** Class: E (input-not-taken) + H (false disclosure). One finding with two faces:

1. **`compute_risk_parity_weights` ignores `settings.risk.risk_parity_tolerance`** — it solves with
   its `tolerance` **parameter** (default `1e-10`), so the config leaf
   `risk.risk_parity_tolerance_value` is dead for the function it was authored to parameterise.
   Contrast `risk.risk_parity_stress_shift_threshold`, which **is** correctly read (line 1885).
2. **The module comment (lines 1559–1562) claims the opposite** — the inversion of the code.

Recorded for a SEPARATE fix increment — the audit changes no `src/` file.

**RESOLVED at D-129** (`docs/DECISIONS.md:21482`). `compute_risk_parity_weights` now takes
`tolerance: float | None = None` (`risk_budget.py:1773`) and resolves `None` to
`settings.risk.risk_parity_tolerance` (`:1845–1846`); an explicit caller value is the only override, so
the config leaf is live. The module comment above `DEFAULT_RISK_PARITY_TOLERANCE` (`:1559–1565`) was
rewritten to say the constant is a **named mirror** of the shipped leaf, *not* the signature default. A
mover test guards it: `test_the_config_tolerance_leaf_is_actually_taken_d129` in
`tests/portfolio/test_risk_parity.py` monkeypatches `get_settings` to a proxy with
`risk_parity_tolerance_value = 5e-2` and asserts the published `worst_target_error > 1e-6` (a dead leaf
would still solve to `< 1e-9`). It is a *mover* not a *pinner* because the shipped leaf equals the old
parameter default (the D-031 shape). **No mutation sweep covers risk parity** (the module comment above
says so), so the suite + the mover test are the evidence.

*Guard-KILL verified (a mover, not merely a passer).* Re-applying the pre-D-129 form by hand (restore the
`DEFAULT_RISK_PARITY_TOLERANCE` parameter default and delete the `if tolerance is None:` resolution) and
running the new test alone: **`1 failed`**, with `assert 7.1e-11 > 1e-06` — the monkeypatched loose leaf
(5e-2) is ignored, the solver drives to `7.1e-11`, and the assertion fires. That is precisely the
distinction between a **mover** and a **pinner**: a pinner would pass on both forms.

**Contrast with the prior audit:** `docs/AUDIT_PHASE5_TIER5_FINDINGS.md` (line 1908) rated
`compute_risk_parity_weights` **CLEAN**, stating *"all params read (E)"* and *"the model is clean"*.
That pass did not catch that `risk_parity_tolerance` is read by the *parametrised* call and NOT by the
function via config, nor the module comment that claims the reverse. **A second real defect the fresh
pass surfaced that the prior read-only pass missed** (same lesson as Function 14).

---
## FUNCTION 16 — `classify_regime_markov_switching` (`src/macro_engine/models/regime.py:1771`)

**DECISION:** D-105. **SPEC CITE:** §6.2 / §21.3. **BYTE-CHECK:** `regime.py` byte-IDENTICAL to
`c16427d` (verified after the O-156 repair below).

| # | Check | Result |
|---|---|---|
| A | MATH | PASS — every published identity holds (measured below) |
| B | ECONOMICS | PASS — latent-state posterior, ranked by mean, disclosures complete |
| C | WIRING | PASS — 9 refusal paths raise with correct type + named cause |
| D | DATA | PASS — series supplied by caller; provenance/limitations published |
| E | INPUT-TAKEN | PASS — all 4 config leaves read (max_regimes, switching_variance, modal_share, max_iterations) |
| F | INTEGRATION | PASS (known-open) — no `src/` caller (Tier-5 script-only) |
| G | CONFIDENCE | **OBSERVATION (era-correct)** — D-105 predates D-118 |
| H | EVIDENCE | PASS — `mutation_regime.py` (D-105 group) + ~35 tests |

### A — the identities, MEASURED (live 3-regime fit, 600 obs)

```
$ uv run python /tmp/probe_f16.py
parameters_for(3)=12 (6 transitions + 3 intercepts + 3 variances); length floor = 60
regime_means: [-0.992, 1.022, 3.005]  ascending? True
means == [raw[i] for i in order]?  True        (order_raw_index = [0,1,2])
regime_period_counts: [200, 200, 200]  sum = 600
regime_shares: [0.3333, 0.3333, 0.3333]  sum = 1.0
transition rows sum to 1: [1.0, 1.0, 1.0]
expected_durations == 1/(1-p_ii)?  [472.061866, 472.076084, 173.249523]
max_smoothed_filtered_gap = 0.00109784  (positive, published, not asserted)
confidence = 0.3   (heuristic + unobservable + source_independence_count=0)
```

Every stated identity holds exactly: the parameter-count derivation (`k(k-1)+k+k`), the
mean-ascending canonical order, the permutation↔means consistency, the share/count partition, the
row-stochastic orientation, and `expected_durations = 1/(1-p_ii)`. **No rounding** (deliberate — see
the module note), so the identities survive to full float precision.

### C — refusal paths, MEASURED (all 9 raise)

```
k_regimes=True        -> TypeError   (bool refused; isinstance(True,int) guard)
k_regimes=1.5         -> TypeError   (float refused)
k_regimes=1           -> ValueError  (< 2)
k_regimes=7           -> ValueError  (> regime.markov.max_regimes_value=6)
series=str            -> TypeError   (not a pd.Series)
empty series          -> ValueError
series with NaN       -> ValueError  ("200 non-finite value(s) out of 400")
constant series       -> ValueError  ("range is 0.0 against a magnitude of 2.0")
50 obs, k=3           -> ValueError  ("50 observations ... requiring at least 60")
```

Each names the offending property and the measured library failure it prevents. The `bool` guard is
the subtle one (`isinstance(True, int)` is True → would silently select a 2-regime model).

### E — config leaves taken

`max_regimes` (:1877), `switching_variance` (:1897, :1915), `max_iterations` (:1919),
`em_iterations` (:1920), `search_reps` (:1921), `modal_share_warning_threshold` (:2063), and
`parameters_for` (:1892) are all read from `settings.regime.markov`. The D-105 tests assert each is
read from config (`test_markov_k_ceiling_is_read_from_config`, `..._switching_variance...`,
`..._modal_share_bar...`, `..._max_iterations...`), so no leaf is shadowed by a literal.

### G — OBSERVATION (era-correct, not a defect)

`classify_regime_markov_switching`' confidence (:2097) is the D-105-era `compute_confidence()`-only
form (three factors, no cap/product). D-105 predates D-118, so this is **era-correct**, recorded as a
Class-G OBSERVATION like functions 14–15.

### H — the O-156 event during this audit (evidence-integrity note, NOT a model defect)

Running `scripts/mutation_regime.py` in the FOREGROUND was **SIGTERM'd mid-loop** (the tool's
600 s budget). Per the standing trap (O-156: *an ad-hoc harness SIGTERM'd mid-loop leaves a LIVE
mutation*), the tree was inspected before any retry:

```
$ find src -name "*.sweepbackup"
src/macro_engine/config.py.sweepbackup
src/macro_engine/models/regime.py.sweepbackup
$ git diff --stat src/
 src/macro_engine/models/regime.py | 2 +-
```

The live mutation was precisely identified by DIFF against the sidecar:

```
1714c1714
<         smoothed=smoothed,              (MUTATED — canonical re-indexing removed)
---
>         smoothed=smoothed[:, order],    (sidecar = known-good)
```

`config.py` was byte-IDENTICAL. `regime.py` was RESTORED from the sidecar, re-verified
byte-IDENTICAL, and both sidecars removed — the tree is clean. The sweep was then re-run **in the
background** so it can complete without a SIGTERM (the O-156 root cause). **This event is a
harness/harness-invocation artifact, not a defect in `classify_regime_markov_switching`.**

### Check H — evidence

~35 markov tests in `tests/models/test_regime.py` (canonicalisation invariance under a label switch,
ascending order, tiebreak, transition orientation, durations, filtered endpoint, look-ahead gap, all
refusals, config-leaf reads, non-convergence, warning-branch reachability, determinism, confidence)
plus `mutation_regime.py`. **Result: 71/71 killed, `EXIT=0`** (background run, 20m18s). Static
`--check-targets` reported the census consistent.

```
$ uv run python scripts/mutation_regime.py > /tmp/regime_sweep.log 2>&1 ; echo "EXIT=$?"
EXIT=0
...
KILLED            MX29 the regime counts are published from the library's index order
KILLED            MX30 the base rate is measured on the FILTERED path instead of the smoothed one

71/71 killed
```

### H — a SECOND evidence-integrity event: a CLEAN-EXIT leftover (NEW shape, NOT a model defect)

The sweep exited **0** with **71/71 killed** and wrote **no sidecar**. By the standing triage that would
look clean — but a post-sweep `git status` showed `regime.py` still modified:

```
$ git status --porcelain
 M src/macro_engine/models/regime.py
$ git diff HEAD -- src/macro_engine/models/regime.py
-    if trend > neutral_band:
+    if trend > 0.0:
-    if trend < -neutral_band:
+    if trend < 0.0:
```

The file was left with a **live mutation** (the neutral-band guard removed) despite a clean exit and an
empty sidecar set. Note the **docstring no longer matches the code** (`abs(trend) <= neutral_band` is
documented; `0.0` is implemented) — the signature of a mutation, not an edit. Restored with
`git checkout HEAD -- src/macro_engine/models/regime.py`; re-verified byte-clean (`git diff` empty).

**This is a NEW leftover-repair shape**, distinct from O-155 (prefix-collision false-positive) and
O-156 (SIGTERM mid-loop): a **clean exit that nevertheless failed to repair its target**, with no
sidecar surviving to signal it. The lesson: *`EXIT=0` + no sidecar is NOT sufficient evidence the tree
is clean — always `git status` after a sweep.* Recorded as an evidence-integrity note; the model
(`classify_regime_markov_switching`) is unaffected, and no `src/` change was made.

**STATUS: CLEAN.** Class: — (G is an era-correct OBSERVATION). Two evidence-integrity events occurred
during the audit (an O-156-shaped SIGTERM, then a clean-exit leftover); both were repaired by
byte-verifying the target against HEAD and disclosed rather than hidden. **Neither is a model defect.**

---
## FUNCTION 17 — `yield_curve_pca` (`src/macro_engine/models/yield_curve.py:1899`)

**DECISION:** D-102. **SPEC CITE:** §6.6 / §15.20-F. **BYTE-CHECK:** `yield_curve.py` byte-IDENTICAL to
`c16427d`.

| # | Check | Result |
|---|---|---|
| A | MATH | PASS — sign changes and ratios match the docstring's own measurement |
| B | ECONOMICS | PASS — mature ordering IS the analysis; names forbidden at the sharpest point |
| C | WIRING | PASS — 5 refusal paths raise with correct type + named cause |
| D | DATA | PASS — daily changes supplied; level-vs-change limitation disclosed |
| E | INPUT-TAKEN | PASS — `is_heuristic_not_calibrated` reads a real config leaf (not hardcoded) |
| F | INTEGRATION | PASS (known-open) — no `src/` caller (Tier-5 script-only) |
| G | CONFIDENCE | **OBSERVATION (era-correct)** — D-102 predates D-118 |
| H | EVIDENCE | PASS — `mutation_yield_curve.py` (D-102 group) + 73 tests |

### A/B — measured against the docstring's own claim

Five-tenor panel (3mo/2yr/5yr/10yr/30yr) constructed with a level+slope+curvature structure plus
idiosyncratic noise, **input columns shuffled** to `['10yr','3mo','30yr','2yr','5yr']`:

```
$ uv run python /tmp/probe_f17b.py
tenors (maturity order): ['3mo','2yr','5yr','10yr','30yr']   (input was shuffled)
ratios: [0.8746, 0.0742, 0.0218, 0.0157, 0.0137]   sum = 1.0
cumulative: [0.8746, 0.9488, 0.9706, 0.9863, 1.0]
sign_changes: {'PC1': 0, 'PC2': 1, 'PC3': 2}
warnings: 1  ->  "THE INPUT COLUMNS WERE NOT IN MATURITY ORDER, ..."
```

* **The re-ordering works**: a shuffled panel publishes tenors in maturity order, and the
  "not in maturity order" warning fires.
* **`sign_changes = {PC1: 0, PC2: 1, PC3: 2}`** — **exactly** the docstring's stated measurement
  (":"PC1 changes sign **0** times, PC2 once, PC3 twice"). The components are labelled `PC1/PC2/PC3`
  numerically — the §15.20-F prohibition (no level/slope/curvature naming) is honoured.
* Ratios sum to 1.0; cumulative reaches 1.0; `standardisation='correlation'` published.

### C — refusal paths, MEASURED (all 5 raise)

```
list                -> TypeError   ("must be a pandas DataFrame, got list")
empty DataFrame     -> ValueError  ("at least one tenor column; it has none")
duplicate label     -> ValueError  ("duplicate column name(s) ['10yr']")
only 2 tenors       -> ValueError  ("has 2 tenor(s), but Section 6.6 names 3 components")
unparseable tenor   -> ValueError  ("tenor 'abc' is not a maturity label ...")
```

The tenor parser `_curve_tenor_years` was probed directly: `3mo→0.25`, `6mo→0.5`, `1yr→1`, `2yr→2`,
`5yr→5`, `10yr→10`, `30yr→30`, `2y→2` (all correct); `3m`/`yr`/`0yr`/`-1yr`/`abc`/`1month` all
refused. This is the registry's actual label set (`config/series_registry.yaml`), and the docstring's
claim that the *sibling* `_tenor_years` refuses all eleven registry labels is consistent with the two
parsers' different acceptance sets.

Bonus behaviour (not a defect): a genuinely rank-deficient panel is **refused by `compute_pca`** with
a negative-eigenvalue explanation, rather than publishing an incoherent negative variance — measured
when a level/slope/curvature panel was built with no idiosyncratic noise.

### E — the config leaf is taken

Unlike `classify_regime_markov_switching` (which hardcodes `is_heuristic_not_calibrated=True`),
`yield_curve_pca` computes that factor from a **real leaf**:

```
is_heuristic_not_calibrated=not settings.is_calibrated("econometrics.pca_near_zero_tolerance")
```

`econometrics.pca_near_zero_tolerance` exists (`config.py:5053`, `config/settings.yaml:3812`). So this
function prices the disclosure off the same threshold `compute_pca` uses — a Class-E PASS.

### G — OBSERVATION (era-correct, not a defect)

`yield_curve_pca`' confidence is the D-102-era `compute_confidence()`-only form (three factors, no
cap/product). D-102 predates D-118, so this is **era-correct**, recorded as a Class-G OBSERVATION
like functions 14–16.

### Check H — evidence

73 tests in `tests/models/test_yield_curve.py` plus `mutation_yield_curve.py`. **Result: 89/90 killed
(1 expected-inert canary), `EXIT=0`.** One survivor, triaged per D-031 below.

```
$ uv run python scripts/mutation_yield_curve.py > /tmp/yc_sweep.log 2>&1 ; echo "EXIT=$?"
EXIT=0
...
KILLED            CANARY1 the module literal is replaced with a syntax error (CONTROL)

89/90 killed
(1 expected-inert by design)
```

**Survivor triage (D-031 — measured, not assumed):**

```
SURVIVED  MX2d the depth factor applies `>` instead of `>=` at the cap
```

`MX2d` replaces `min(abs(slope)/saturation, 1.0)` with
`1.0 if abs(slope) > saturation else abs(slope)/saturation`. **Measured EQUIVALENT** — the two forms
agree at every point including the boundary, so no test can (or should) distinguish them:

```
$ python -c "for sat in (0.25,0.5,1.0,1.5,2.0): for s in [0, sat*0.999, sat, sat*1.001, sat*2,-sat,-sat*1.5]: ..."
non-equivalent (sat, slope, orig, mut) pairs: []
total non-equivalent pairs: 0
```

At `abs(slope) == saturation` both return exactly `1.0` (`min(1.0, 1.0)` vs `sat/sat`), and for
`abs(slope) > saturation` both return `1.0`. This is **D-031's second category: an inert mutation**,
NOT a weak test and NOT a defect — it is recorded, not "fixed" by inventing a test that asserts a
distinction the maths does not make. `yield_curve.py` verified byte-clean vs `HEAD` (`git diff` empty)
after the sweep.

**STATUS: CLEAN.** Class: — (G is an era-correct OBSERVATION; H is 89/90 with the one survivor
measured EQUIVALENT).

---
## FUNCTION 18 — `run_regression` (`src/macro_engine/models/econometrics.py:222`)

**DECISION:** D-092 (Module 18 begins). **SPEC CITE:** §15.18. **BYTE-CHECK:** `econometrics.py`
byte-IDENTICAL to `c16427d`.

| # | Check | Result |
|---|---|---|
| A | MATH | PASS — recovers the true coefficients to 3 dp (measured below) |
| B | ECONOMICS | PASS — mechanism-first gate; spurious-regression prohibition stated |
| C | WIRING | PASS — 10 refusal paths raise with correct type + named cause |
| D | DATA | PASS — both sides supplied; alignment refused rather than assumed |
| E | INPUT-TAKEN | PASS — 4 config leaves read (min_obs, mechanism_min_length, low_r2, vif) |
| F | INTEGRATION | PASS (known-open) — no `src/` caller (Tier-5 script-only) |
| G | CONFIDENCE | **OBSERVATION (era-correct)** — D-092 predates D-118 |
| H | EVIDENCE | PASS — `mutation_econometrics.py` + 236 tests |

### A — the fit, MEASURED

`y = 2.0*x1 - 1.5*x2 + N(0,0.5)`, 200 observations:

```
$ uv run python /tmp/probe_f18.py
beta: {'const': 0.0031, 'x1': 2.0079, 'x2': -1.5073}   (true: 0, 2.0, -1.5)
r2: 0.9568   adj_r2: 0.9564
p_values: {'const': 0.931256, 'x1': 0.0, 'x2': 0.0}
n_obs: 200   dof: 197
vif: {'x1': 1.003, 'x2': 1.003}
```

Exact OLS — the coefficients recover the data-generating values, the intercept is reported under
`const`, and independent regressors carry VIF ≈ 1.

### C — refusal paths, MEASURED (all 10 raise)

```
empty mechanism       -> ValueError  ("must state the economic mechanism hypothesised BEFORE fitting")
whitespace mechanism  -> ValueError  (stripped length < 20)
too-short mechanism   -> ValueError  (< mechanism_min_length=20)
non-str mechanism     -> TypeError
len mismatch          -> ValueError  ("y has 200, X has 100")
rank-deficient (x3=x1)-> ValueError  ("4 columns but rank 3")
const collision       -> ValueError  ("contains a column named 'const', which collides")
constant regressor    -> ValueError  ("Regressor(s) ['const2'] are constant across the sample")
NaN in y              -> ValueError  ("y contains non-finite values")
too few obs (3)       -> ValueError  ("3 observations is below the configured floor of 8")
```

Two of these are the documented measured traps: the **rank-deficiency check uses `matrix_rank`
(SVD)**, not the VIF — because a singular design returns a LARGE FINITE VIF and would pass a
finiteness test; and the **`const` collision** would otherwise produce a duplicated params index and
silently drop a coefficient.

### E — config leaves taken

`econometrics.min_observations` (:3125), `mechanism_min_length` (:3013),
`low_r_squared_threshold` (:304), `vif_concern_threshold` (:305) are all read from config, and
`is_heuristic_not_calibrated=not _r_squared_floor_is_calibrated()` reads
`econometrics.low_r_squared_threshold`'s calibration status (probed: `False` → factor `True` →
confidence `0.5`). No leaf is shadowed by a literal.

### G — OBSERVATION (era-correct, not a defect)

`run_regression`'s confidence (:320) is the D-092-era `compute_confidence()`-only form (two factors:
heuristic + source_independence_count=0). D-092 predates D-118, so this is **era-correct**, recorded
as a Class-G OBSERVATION like functions 14–17.

### Check H — evidence

236 tests in `tests/models/test_econometrics.py` plus `mutation_econometrics.py`. Result recorded
below.

```
$ uv run python scripts/mutation_econometrics.py > /tmp/econ_sweep.log 2>&1 ; echo "EXIT=$?"
EXIT=0
...
108/109 killed
  SURVIVOR (inert-by-route): M34 non-finite p-value refusal removed
```

**Result: 108/109 killed, `EXIT=0`.** The one survivor, **`M34`**, is the sweep's OWN recorded
**`INERT_BY_ROUTE`** member (not a weak test): `coint` terminates before its p-value can go
non-finite — whenever the first-step regression degenerates, the MacKinnon **critical values** come
back `(nan, nan, nan)` first, so the `M35` critical-value guard raises and `M34`'s branch is never
evaluated. The sweep re-measured this over **93 (configuration × trend) combinations** (indep random
walks n=30..1600 ×4 seeds; near-collinear pairs at scales 1e-9/1e-12/1e-15/0.0; constant y; constant
x; y≡x; each across `c`/`ct`/`n`) → **31 with non-finite critical values, ZERO with a non-finite
p-value**. `econometrics.py` verified **byte-clean vs `HEAD`** and sidecar-free after the sweep.

**STATUS: CLEAN.** Class: — (G is an era-correct OBSERVATION).

---
## FUNCTION 19 — `test_stationarity` (`src/macro_engine/models/econometrics.py:373`)

**DECISION:** D-094 (Module 18 #2). **SPEC CITE:** §15.18. **BYTE-CHECK:** `econometrics.py`
byte-IDENTICAL to `c16427d`.

| # | Check | Result |
|---|---|---|
| A | MATH | PASS — the inverted-null verdict table reproduced on real series (measured) |
| B | ECONOMICS | PASS — disagreement reported, never resolved by picking a test |
| C | WIRING | PASS — 6 refusal paths raise with correct type + named cause |
| D | DATA | PASS — one series supplied; floor (30) higher than regression's (8) |
| E | INPUT-TAKEN | PASS — 4 config leaves read (alpha, adf_regression, adf_autolag, kpss_nlags, floor) |
| F | INTEGRATION | PASS (known-open) — no `src/` caller (Tier-5 script-only) |
| G | CONFIDENCE | **OBSERVATION (era-correct)** — D-094 predates D-118 |
| H | EVIDENCE | PASS — `mutation_econometrics.py` D-094 group + 236 tests |

### A/B — the verdict table, MEASURED

```
$ uv run python /tmp/probe_f19.py
white_noise:  verdict='stationary'      ADF p=0.0000 (rej)  KPSS p=0.1000 (not rej) clipped=True
random_walk:  verdict='non_stationary'  ADF p=0.0591 (not)  KPSS p=0.0100 (rej)      clipped=True
sine:         verdict='stationary'      ADF p=0.0000 (rej)  KPSS p=0.038  (not)      clipped=True
```

The two agreeing cases are reproduced exactly: white noise is `stationary`, a random walk is
`non_stationary`. The **KPSS clip is disclosed** on every run — the p-value sits at the look-up
table's boundary (0.01 / 0.10), and the warning says "A BOUND, NOT A POINT ESTIMATE" with the
direction (`at least 0.10` / `at most 0.01`). The inverted-null booleans
(`adf_rejects_unit_root`, `kpss_rejects_stationarity`) are named rather than inlined, so the
inversion cannot be silently transposed.

### C — refusal paths, MEASURED (all 6 raise)

```
list            -> TypeError   ("must be a pandas Series, got list")
empty           -> ValueError  ("series is empty; there is nothing to test")
NaN             -> ValueError  ("series contains non-finite values")
10 obs          -> ValueError  ("below the configured floor of 30")
bool dtype      -> ValueError  ("series must be numeric, got dtype bool")
constant series -> ValueError  ("series is constant across the sample, so it has no dynamics")
```

The constant-series refusal is the function's OWN (code at :2988), not a library error — measured
explicitly. The floor (30) is deliberately higher than `run_regression`'s (8) because both tests'
critical values are asymptotic.

### E — config leaves taken

`econometrics.significance_level` (:418), `adf_regression` (:419), `adf_autolag` (:424),
`kpss_nlags` (:429), `stationarity_min_observations` (:2979) are all read from config; the
confidence's heuristic factor reads `_r_squared_floor_is_calibrated()` (the same leaf
`run_regression` prices).

### G — OBSERVATION (era-correct, not a defect)

`test_stationarity`'s confidence (:476) is the D-094-era `compute_confidence()`-only form. D-094
predates D-118, so this is **era-correct**, recorded as a Class-G OBSERVATION like functions 14–18.

### Check H — evidence

The `mutation_econometrics.py` D-094 group (line 220) plus 236 tests in
`tests/models/test_econometrics.py`. Result recorded below.

```
mutation_econometrics.py (shared run): 108/109 killed, EXIT=0
  the D-094 test_stationarity group: all KILLED
  the single survivor is M34 (cointegration, INERT_BY_ROUTE — see Card 18)
```

**STATUS: CLEAN.** Class: — (G is an era-correct OBSERVATION).

---
## FUNCTION 20 — `test_cointegration` (`src/macro_engine/models/econometrics.py:514`)

**DECISION:** D-097 (Module 18 #3). **SPEC CITE:** §15.18-F. **BYTE-CHECK:** `econometrics.py`
byte-IDENTICAL to `c16427d`.

| # | Check | Result |
|---|---|---|
| A | MATH | PASS — cointegration correctly detected; hedge ratio recovered; half-life phi valid (measured) |
| B | ECONOMICS | PASS — spread/half-life/regime-stability + mandatory warnings on every call |
| C | WIRING | PASS — 4 refusal paths raise with correct type + named cause (incl. the -inf trap) |
| D | DATA | PASS — both series supplied; I(1) presumption stated, not tested |
| E | INPUT-TAKEN | PASS — trend, split_fraction, min_obs, family_size all read from config |
| F | INTEGRATION | PASS (known-open) — no `src/` caller (Tier-5 script-only) |
| G | CONFIDENCE | **OBSERVATION (era-correct)** — D-097 predates D-118 |
| H | EVIDENCE | PASS — `mutation_econometrics.py` D-097 group (M33–M55) + 236 tests |

### A/B — the tests, MEASURED

```
$ uv run python /tmp/probe_f20.py
COINTEGRATED (y = 2x + stationary noise):
  engle_granger stat=-19.1046 p=0.0   critical=[-3.9241,-3.3515,-3.0551]
  is_cointegrated=True   hedge_ratio=1.9973  (true 2.0 — recovered to 3 dp)
  half_life_periods=0.7269  phi=-0.9536  (in the valid -1 < phi < 0 range)
  regime_stability='stable'  agreement=True
  n_obs=400  spread len=400
  family_size=10  fwer=0.4013  corrected_per_test_size=0.0051
  spread_adf_p_value=0.0  spread_is_stationary=True

NON-COINTEGRATED (two independent random walks):
  is_cointegrated=False  p=0.7408

JOHANSEN:
  method='johansen'  is_cointegrated=True
  hedge_ratio=None (no normalised slope on a pair)  spread len=0  n_obs=400 (NOT 0)
  discarded_imaginary=4 (disclosed)
```

The cointegrated pair is detected, the hedge ratio recovers the data-generating 2.0, and the
non-cointegrated pair is correctly not rejected. The three mandated extras are all published: the
**spread** (a real series, 400 long), the **half-life** (`phi=-0.954` inside the estimator's validity
bound), and **regime stability**. The **multiple-testing numbers are computed** (FWER 0.4013,
per-test 0.0051), not asserted. On the Johansen path `n_obs=400` is the input length, not the
(empty) spread's length — the documented "wrong number that looks like a missing one" trap is
avoided.

### C — refusal paths, MEASURED (all 4 raise)

```
near-collinear (y=2x+1e-9 noise) -> ValueError  ("first-step regression was rank-deficient")
length mismatch                  -> ValueError  ("y has 100, x has 400")
constant series                  -> ValueError  ("y is constant across the sample")
bad method                       -> ValueError  ("method must be one of ['engle_granger','johansen']")
```

The near-collinear refusal is **trap 1** from the docstring: `coint` returns `coint_t=-inf,
pvalue=0.0` on a degenerate regression, and an `-inf` statistic would pass a finiteness check on the
p-value alone — so the function refuses instead.

### E — config leaves taken

`econometrics.significance_level` (:604), `cointegration_trend` (:605),
`regime_stability_split_fraction` (:639), `cointegration_min_observations` (:640),
`assumed_test_family_size` (:645) are all read from config; the confidence's heuristic factor reads
`_cointegration_thresholds_calibrated()` (the split fraction + assumed family size leaves).

### G — OBSERVATION (era-correct, not a defect)

`test_cointegration`'s confidence (:683) is the D-097-era `compute_confidence()`-only form. D-097
predates D-118, so this is **era-correct**, recorded as a Class-G OBSERVATION like functions 14–19.

### Check H — evidence

The `mutation_econometrics.py` D-097 group **M33–M55** (line 48/315) plus 236 tests in
`tests/models/test_econometrics.py`. Result recorded below.

```
mutation_econometrics.py (shared run): 108/109 killed, EXIT=0
  the D-097 cointegration group: all KILLED except M34 (INERT_BY_ROUTE — this card's group)
  M34 = "non-finite p-value refusal removed"; the branch is unreachable because the
  MacKinnon CRITICAL-VALUE guard (M35) raises first (docs/DECISIONS.md, prior audit line 3061)
```

**STATUS: CLEAN.** Class: — (G is an era-correct OBSERVATION).

---
## FUNCTION 21 — `compute_pca` (`src/macro_engine/models/econometrics.py:816`)

**DECISION:** D-099 / D-100 (Module 18 #4). **SPEC CITE:** §15.20-F. **BYTE-CHECK:** `econometrics.py`
byte-IDENTICAL to `c16427d`.

| # | Check | Result |
|---|---|---|
| A | MATH | PASS — eigenvalues match `eigh` exactly; sign rule holds (measured) |
| B | ECONOMICS | PASS — no auto-labelling; level-vs-change discipline + suspicion warning |
| C | WIRING | PASS — 6 refusal paths raise with correct type + named cause |
| D | DATA | PASS — daily changes supplied; levels presumed-refused by shape, warned |
| E | INPUT-TAKEN | PASS — standardisation + near-zero tolerance read from config |
| F | INTEGRATION | PASS (known-open) — no `src/` caller (Tier-5 script-only) |
| G | CONFIDENCE | **OBSERVATION (era-correct)** — D-099/100 predate D-118 |
| H | EVIDENCE | PASS — `mutation_econometrics.py` group (line 480) + 236 tests |

### A — the decomposition, MEASURED

Four correlated series (one dominant factor), `correlation` standardisation:

```
$ uv run python /tmp/probe_f21b.py / _f21c.py
published eigenvalues: [1.975088, 0.777538, 0.653485, 0.593889]
manual eigh(corr):     [1.975088, 0.777538, 0.653485, 0.593889]   match = True
sum = 4.0  (= n_variables, the correlation-matrix identity)
sign rule: PC1 +0.5391, PC2 +0.7814, PC3 +0.8466  (largest-|loading| positive in every component)
covariance route: fn eigenvalues == unbiased eigh  (match = True)
```

The published eigenvalues equal `numpy.linalg.eigh` on the **unbiased** (`ddof=1`) matrix to 1e-9 on
**both** the `correlation` and `covariance` routes, and they sum to `n_variables` on the correlation
route as required. The **sign rule** (sklearn's `svd_flip`: largest-|loading| element positive) holds
in every component — reproducibility across builds.

### B — OBSERVATION (docstring nuance, NOT a code defect)

The docstring (:852–858) says the *unbiased* `1/(n-1)` denominator is load-bearing because *"using
`1/n` here would bias every published ratio by `(n-1)/n`"*. Measured: the **eigenvalues** do depend on
`ddof` (the choice is correct and matters — they are published), but the **ratios are invariant**,
because a ratio cancels the shared `(n-1)/n` factor:

```
$ uv run python /tmp/probe_f21c.py
covariance route: ratio diff (PC1) unbiased vs biased = 0.00e+00
correlation route: ratio diff = 1.11e-16
```

So the code is correct; the prose attributes the effect to the ratios when the quantity that actually
moves is the eigenvalue. Recorded as a Class-B **OBSERVATION** (documentation precision), not a
defect — the implementation is right and the disclosure is conservative.

### C — refusal paths, MEASURED (all 6 raise)

```
n_components=5 (>4 vars) -> ValueError  ("exceeds the number of series (4)")
n_components=0           -> ValueError  ("must be at least 1")
duplicate column         -> ValueError  ("duplicate column name(s) ['a']")
collinear (c=2a)         -> ValueError  ("rank-deficient: 4 columns but rank 3")
constant column          -> ValueError  ("Series ['const'] are constant across the sample")
NaN panel                -> ValueError  ("contains non-finite values")
```

These are the three documented silent-failure paths (negative eigenvalue on a rank-deficient panel;
out-of-range `n_components`; NaN propagation) plus the constant-column guard that the covariance
route's *relative* `matrix_rank` tolerance would otherwise miss.

### E — config leaves taken

`econometrics.pca_standardisation` (:916, shipped `"correlation"`), `pca_near_zero_tolerance` (:975)
are read from config; the confidence's heuristic factor reads `_pca_choices_calibrated()` (the
standardisation choice + near-zero tolerance).

### G — OBSERVATION (era-correct, not a defect)

`compute_pca`'s confidence (:988) is the D-099/D-100-era `compute_confidence()`-only form. Both
decisions predate D-118, so this is **era-correct**, recorded as a Class-G OBSERVATION like functions
14–20.

### Check H — evidence

The `mutation_econometrics.py` `compute_pca` group (line 480) plus 236 tests in
`tests/models/test_econometrics.py`. Result recorded below.

```
mutation_econometrics.py (shared run): 108/109 killed, EXIT=0
  the compute_pca group: all KILLED (the lone survivor M34 is the cointegration route — Card 20)
```

**STATUS: CLEAN.** Class: B is a docstring-precision OBSERVATION; G is universe (era-correct).

---
## FUNCTION 22 — `kalman_latent_state` (`src/macro_engine/models/econometrics.py:1845`)

**DECISION:** D-101 (Module 18 #5). **SPEC CITE:** §15.20-F / AGENTS.md:3147/3157/3166/3178/3187.
**BYTE-CHECK:** `econometrics.py` byte-IDENTICAL to `c16427d`.

| # | Check | Result |
|---|---|---|
| A | MATH | PASS — three specs select correctly; band identity + scale-invariance hold (measured) |
| B | ECONOMICS | PASS — unobservable state published with its band; filtered vs smoothed discipline enforced |
| C | WIRING | PASS — 5 refusal paths raise with correct type + named cause |
| D | DATA | PASS — level series + regressor pair supplied; the level-not-change discipline documented |
| E | INPUT-TAKEN | PASS — diff(use) scale, max-iterations, optimizer, band coverage read from config |
| F | INTEGRATION | PASS (known-open) — no `src/` caller (Tier-5 script-only) |
| G | CONFIDENCE | **OBSERVATION (era-correct)** — D-101 predates D-118; `depends_on_unobservable=True` is its one non-judgement flag |
| H | EVIDENCE | PASS — `mutation_econometrics.py` Kalman group + 236 tests |

### A — the three specifications, MEASURED

```
$ uv run python /tmp/probe_f22d.py
local_level             states=['level']        (1 col, state_dim=1)
local_linear_trend      states=['level','slope'] (1 col, state_dim=2)
time_varying_hedge_ratio states=['beta']         (2 cols, state_dim=1, regressor design)
```

`_select_kalman_model` picks the correct `_KalmanSpec` for each `(n_columns, state_dim)` pair from the
declared table — the pair design is selected only for `(2 cols, dim 1)` and the regressor's column
order names the dependent/regressor roles explicitly (see E). **This is a claim about the SELECTION
TABLE, not about the caller** — an unsupported combination refuses rather than improvising (see C).

### A — the band identity and scale-invariance, MEASURED

```
$ uv run python /tmp/probe_f22d.py
band width (upper[-1]-lower[-1]) == 2*z*se[-1]  ->  True
latest: {'level': {'state': 1.39074, 'std_error': 0.169306,
                   'lower': 1.05891, 'upper': 1.72257}}
revision_in_band_units: {'level': 1.95130}
scale-invariance of sigma2.level/scale^2:
    0.044675 at scale 1
    0.044675 at scale 1e-3
    0.044675 at scale 1e3
    0.044675 at scale 1e6
    0.044675 at scale 1e9
```

Two identities that a silently-wrong filter would break:

1. **The band is derived, not stored.** `upper[-1] − lower[-1]` equals `2·z·se[-1]` exactly — the
   published bounds and the published standard error cannot disagree.
2. **The estimated variance is scale-equivariant.** Rescaling the observed series by `s` rescales
   `σ²_level` by `s²` (so `σ²_level/scale²` is constant across nine orders of magnitude, spread
   **0.000**). This is the property whose failure D-101's docstring records as a **147× spread**
   defect in the original formulation; the current block reproduces the invariant exactly.

### A — the time-varying hedge ratio is genuinely time-varying, MEASURED

```
$ uv run python /tmp/probe_f22d.py
spec: time_varying_hedge_ratio  states=['beta']
final beta estimate: 0.5613   true beta: 0.6029   mean abs err: 0.0406   mean: 0.5166   std: 0.1658
```

The **FILTERED** β path (the only path a real-time decision may read — see B) tracks the true
coefficient with a non-trivial spread (`std 0.1658` across the run). This distinguishes a state-space
β from the rec-OLS-to-full-sample quantity that a naive implementation would produce: the estimate
moves with the data rather than jumping once to a final value.

### B — the filtered-vs-smoothed discipline

The result publishes BOTH the filtered and smoothed states, plus `revision_in_band_units` (measured
`1.95130` for the level — the revision is under two band-widths, a real number, not a placeholder).
The `decision_prohibition` block refuses three uses by name: quoting the filtered state without its
band; using the smoothed state for a real-time decision (look-ahead bias); and comparing a state
across two fits as though it were the same quantity. `depends_on_unobservable=True` is set with the
module's own justification (the ONLY such flag setting in the module that is not a judgement call):
`r*`, potential GDP and a time-varying hedge ratio are unobservable by nature — no data can confirm
the filter's answer directly (see `_kalman_limitations`).

### C — refusal paths, MEASURED (5 of 5 raise)

```
unsupported (1col,dim3) -> ValueError ("No specification for 1 column(s) with state_dim=3 ...")
3 columns               -> ValueError ("observations has 3 columns, but this function estimates a "
                                        "latent LEVEL or a 2-column pair ...")
state_dim=bool          -> TypeError  ("state_dim must be an int, got bool ...")
state_dim=float         -> TypeError  ("state_dim must be an int, got float ...")
too few obs (5)         -> ValueError ("5 observations is below the configured floor of 60 ...")
```

Note the **bool** case is caught separately from **float**: `isinstance(True, int)` is `True` in
Python, so a `bool` would silently pass an `isinstance(..., int)` check — the function tests for
`bool` explicitly. The `state_dim=float` refusal is a `TypeError` (wrong type), the `1-col/dim-3` and
`too-few-obs` refusals are `ValueError` (right type, unusable value) — trap 4: the *type* is asserted
because the *cause* is named in the message.

### D — the level-not-change discipline

`_kalman_assumptions` states outright that the series is a **LEVEL, not a change**, and calls this
"the same discipline `compute_pca` enforces in the opposite direction" — a stationary difference
passed to the level filter is filtered as though it were a level, so the state means nothing. This is
a *documented* refusal-to-guess (the function cannot detect intent), consistent with D-099/D-100's
"no auto-labelling" stance in the PCA sibling.

### E — config leaves taken

`econometrics.kalman_diffuse_scale`, `kalman_max_iterations`, `kalman_optimizer`, `kalman_band_coverage`
are read from config; `_kalman_thresholds_calibrated()` (:2564) backs
`is_heuristic_not_calibrated`. `_kalman_inputs_used` (:2436) names each column by its **role**
(`dependent:` / `regressor:` / `observed:`), putting the column-order convention into the result where
it can be checked rather than leaving it in prose.

### G — OBSERVATION (era-correct, not a defect)

`kalman_latent_state`'s confidence (:2106) is the D-101-era `compute_confidence()`-only form.
**Measured decision date vs the D-118 line:** `## D-101` sits at `docs/DECISIONS.md:16633`;
`## D-118` sits at `:19584`. D-101 is ABOVE D-118, i.e. it predates it, so the `compute_confidence()`
form here is **era-correct** — recorded as a Class-G OBSERVATION like functions 14–21. Cross-checked
against D-126 (`:20986`) and D-128 (`:21319`): D-126 fixed only `statement_text_diff`; D-128's
"Card 22" is `select_instrument`, in a different module. Neither touches this function — consistent
with the byte-identity to `c16427d`.

### Check H — evidence

The `mutation_econometrics.py` Kalman group plus 236 tests in `tests/models/test_econometrics.py`.
Result recorded below.

```
mutation_econometrics.py (shared run): 108/109 killed, EXIT=0
  the Kalman group (M103–M108 etc.): all KILLED
  the lone survivor M34 is the cointegration route (Card 20), INERT_BY_ROUTE
```

**STATUS: CLEAN.** Class: — (G is an era-correct OBSERVATION).

---
## FUNCTION 23 — `statement_text_diff` (`src/macro_engine/models/policy_rules.py:1180`)

**DECISION:** D-125 (created) → **D-126** (confidence `min()`→product) → **D-127** (two `_TILT_*`
label members). **SPEC CITE:** §20.4. **BYTE-CHECK:** `policy_rules.py` byte-IDENTICAL to `HEAD`
(`git diff HEAD -- src/.../policy_rules.py` is EMPTY) — this is the ONE Tier-5 file changed since
`c16427d`, and at the audit's HEAD it carries both post-D-125 fixes.

| # | Check | Result |
|---|---|---|
| A | MATH | PASS — tilt identity, per-occurrence diff, exact-cancellation all measured |
| B | ECONOMICS | PASS — all 8 directions reachable and each keyed on the SIGN of BOTH nets |
| C | WIRING | PASS — blank-vs-floor refusals raise with correct type + named cause |
| D | DATA | PASS — both texts required; no fetch in the model (§20.4 scopes it to the diff) |
| E | INPUT-TAKEN | PASS — cap, floor, both marker sets, calibration flag read from config |
| F | INTEGRATION | PASS (known-open) — no `src/` caller (Tier-5 script-only) |
| G | CONFIDENCE | **PASS — the post-D-118 CAP-PRODUCT form (D-126)**; both halves published |
| H | EVIDENCE | PASS — `mutation_statement_text.py` **34/34**, `--check-targets 34, 0 problems` |

### A — the tilt identity and the per-occurrence diff, MEASURED

```
tilt = (h - d) / (|h| + |d|)   when either is non-zero, else 0.0
  A hawkish enters only : h=+1 d=0  -> tilt=+1.0  MORE_HAWKISH
  B hawkish leaves only : h=-1 d=0  -> tilt=-1.0  MORE_DOVISH
  G one each way        : h=+1 d=+1 -> tilt= 0.0  MIXED_BOTH_DIRECTIONS_NET_FLAT
  I hawkish doubled->one: h=-1 d=0  -> tilt=-1.0  MORE_DOVISH   (per-occurrence, not membership)
```

The value published is `net_tilt = round(tilt, 4)` and the label is a separate field, so the signed
bounded ratio is never overwritten by the label. Case **I** is the per-occurrence discipline
(`_markers_entering_and_leaving` + `_net_marker_change`): a phrase appearing twice and dropping to
once is a MOVE (−1), not "unchanged" — measured, not assumed.

### B — all eight directions, MEASURED (the D-125/D-127 heart)

The label must name the sign of **BOTH** sides' nets, not just `tilt`. Brute-forcing every
`(h, d)` in `[-3..3]²` and running the model's own branch logic shows **all eight values are
reachable**, and each is keyed on the correct predicate:

```
reachable labels over the (h,d) lattice:
  HAWKISH_TILT_WITH_DOVISH_ADDITIONS   (e.g. h=+2 d=+1, tilt=+0.333)
  HAWKISH_TILT_WITH_DOVISH_REMOVALS    (e.g. h=-1 d=-2, tilt=+0.333)  <-- both nets NEGATIVE
  DOVISH_TILT_WITH_HAWKISH_ADDITIONS   (e.g. h=+1 d=+2, tilt=-0.333)
  DOVISH_TILT_WITH_HAWKISH_REMOVALS    (e.g. h=-3 d=-1, tilt=-0.500)  <-- both nets NEGATIVE
  MORE_HAWKISH / MORE_DOVISH / MIXED_BOTH_DIRECTIONS_NET_FLAT / UNCHANGED
```

Confirmed against the live function:

```
$ uv run python /tmp/probe_f23c.py
HAWKISH tilt + dovish ADDITIONS (h=2 d=1) -> HAWKISH_TILT_WITH_DOVISH_ADDITIONS   (d>0: ADDED)
DOVISH  tilt + hawkish ADDITIONS (h=1 d=2) -> DOVISH_TILT_WITH_HAWKISH_ADDITIONS   (h>0: ADDED)

$ uv run python /tmp/probe_f23e.py
h=-1 d=-2 (both REMOVED, dovish more) -> HAWKISH_TILT_WITH_DOVISH_REMOVALS         (d<0)
h=-3 d=-1 (both REMOVED, hawkish more)-> DOVISH_TILT_WITH_HAWKISH_REMOVALS         (h<0)
```

**The D-125 defect is fixed, MEASURED (not assumed):** the earlier reduction keyed the label on
`tilt > 0` alone, so `d > 0` (dovish language ADDED) and `d < 0` (dovish REMOVED) both read
`..._WITH_DOVISH_REMOVALS`. The current label reads the SIGN of the opposite side's own net
(`dovish_net < 0` → REMOVALS, else ADDITIONS), and the two labels are `d`-sign-distinguished — the
ADDITIONS case at `h=2 d=+1` returns ADDITIONS. **A structural note the enumeration makes explicit:**
the two `..._REMOVALS` labels are reachable ONLY when **both** nets are negative (`h<0 AND d<0`),
because `hawkish_ward`/`dovish_ward` both being true requires a `d>0` XOR-path otherwise — so a
`HAWKISH_TILT_WITH_DOVISH_REMOVALS` always reports a statement where the hawkish net also fell by
less than the dovish net did. This is correct and total; recorded as a measured reachability fact,
not a defect.

### B — the direction-of-movement predicate, MEASURED

```
$ uv run python /tmp/probe_f23.py   (real marker vocabulary from config)
B: hawkish LEAVES only        -> MORE_DOVISH  (a hawkish REMOVAL is dovish-ward)
C: dovish ADDED, hawkish flat -> MORE_DOVISH  (only one direction moved)
D: dovish REMOVED, hawkish flat-> MORE_HAWKISH
```

Case **B** is the D-125 model defect's own fix: a hawkish phrase *leaving* is a move in the DOVISH
direction (`MORE_DOVISH`), where the pre-D-125 reduction read it `MORE_HAWKISH`. The predicate is
now `hawkish_ward = hawkish_net > 0 or dovish_net < 0` / `dovish_ward = hawkish_net < 0 or
dovish_net > 0` — a reduction over the DIRECTION OF MOVEMENT, not over "which side is non-zero"
(REFERENCE trap 7, the D-125 rule).

### C — refusal paths, MEASURED (2 of 2 reachable raise; floor is 1, so a 2-token text is legal)

```
blank prior   -> ValidationError (pydantic) "prior_text is blank. An empty statement ..."
blank current -> ValidationError (pydantic) "current_text is blank. ..."
short text    -> NO RAISE   <-- CORRECT: min_tokens = 1, so a 2-token text is above the floor
```

The blank-text guard is a pydantic `@model_validator(mode="after")` on `StatementTextInputs`
(refuses at construction, before the model ever sees a blank), and the token floor is the model's
own `ValueError` (`min_tokens = 1` shipped: only a genuinely empty/whitespace text trips it — measured
that a real short text does NOT, i.e. the guard is not over-firing). Both guards exist because an
empty statement is a **partial input read as a complete one** (D-054), and diffing against it would
report every marker on one side as newly entered.

### E — config leaves taken

`statement_text.confidence_cap` (0.35), `min_tokens` (1), `hawkish_markers` (5) / `dovish_markers` (5),
and `vocabularies_are_calibrated` (False) are all read from config; every one is a `CalibratedValue`
with `uncalibrated_illustrative` status. The marker vocabulary is externalised (5 + 5 phrases) because
"transitory was dovish until it was retired" — a frozen in-code list would keep scoring a word the
Committee no longer says. `is_heuristic_not_calibrated=not settings.vocabularies_are_calibrated`
**tracks the leaf** rather than asserting `True` (the post-D-118 sibling pattern).

### G — the CAP-PRODUCT confidence, MEASURED (the D-126 fix)

```
$ uv run python /tmp/probe_f23.py
conf_computed = 0.5   cap = 0.35   ->  published = 0.175
recomputable: confidence == round(0.5 * 0.35, 3)  ->  True   (every path, all 9 cases)
```

This is the **only** Tier-5 confidence that is the post-D-118 form, and it is the D-126 fix in the
flesh:

* **The form is the PRODUCT** (`confidence = round(computed * settings.confidence_cap, 3)`), never
  `min()`. D-118's rule: a `min()` would publish the **cap alone** whenever the computed value sits
  above it (here **0.5 > 0.35**, so a `min()` would give 0.35 on every path and make the whole
  `compute_confidence()` half **dead code**). Measured: published **0.175**, not 0.35.
* **Both halves are published** (`confidence_computed = 0.5`, `confidence_cap = 0.35`) so the number
  is **recomputable from the output** (D-009) — measured `recomputable: True` on all nine probe
  cases. This is exactly the disclosure D-126 added so a reader can tell a dead half from a live one.
* Cross-checked against D-126 (`docs/DECISIONS.md:20986`): D-126's subject IS this function, and the
  sweep's **C2b** mutant (`min()`-reintroduction) is the defect-reintroduction guard.

### G — the other Tier-5 confidences (comparison, measured)

Every other Tier-5 function (Cards 14–22) uses the pre-D-118 `compute_confidence()`-only form and is
recorded as an era-correct OBSERVATION. Function 23 is the **only** one carrying the product form —
which is consistent: it is the only Tier-5 function created or touched by a post-D-118 decision
(D-125/D-126/D-127 all sit at `docs/DECISIONS.md` line **> 19584**).

### Check H — evidence

`scripts/mutation_statement_text.py` — **34 mutations, `--check-targets 34, 0 problem(s)`** (measured;
every anchor resolves to exactly one site, O-138 — the static check writes no sidecar). The suite is
**83 tests** in `tests/models/test_policy_rules.py`. The D-125/D-127-specific mutants are present by
name: **D4c/D4d** (the tilt label reverts to the sign-blind REMOVALS spelling), **D4e/D4f** (the tilt
split inverted), **C1a** (confidence hardcoded), **C2a** (cap dropped), **C2b** (`min()`
reintroduced). Full-sweep kill count recorded below.

```
mutation_statement_text.py: 34/34 killed, EXIT=0, 0 survivors, no sidecar left
  (measured 2026-09-29; every mutant KILLED — CANARY1 control, M1a/M1b, M2a/M2b,
   D1a/D1b, D2a/D2b, D3a/D3b, D4a..D4f, D5a, D6a/D6b, C1a/C1b, C2a/C2b, R1a/R1b,
   R2a, W1a, N1a, N2a, N3a)
```

Verified after exit: `src/macro_engine/models/policy_rules.py` restored **byte-IDENTICAL** to its
pre-sweep state (`git status --porcelain -- src/` shows only the two authorised D-129 fixes, `risk.py`
and `risk_budget.py`); `config.py` likewise clean; **no `.sweepbackup` sidecar remained** (so no O-157
leftover). The `--check-targets` pre-flight inside the sweep re-confirmed **34 mutations, 0 problem(s)**,
so all 34 anchors resolved to exactly one site (O-138). This closes the last open Check-H measurement
in the re-audit.

**STATUS: CLEAN.** Class: — (G is the CORRECT post-D-118 form; the only Tier-5 function whose
confidence is a product AND whose D-125/D-127 label fixes are live and measured).

---



# SUMMARY — the fresh Tier-5 re-audit (23 functions)

**Verdict: 21 CLEAN · 2 DEFECT.** Every card carries a measured A–H result. The audit changed **no
`src/` file** (operator: *"without changing logic"*).

## The two DEFECTs (both NEW — missed by the prior audit)

| # | Function | Class | One-line |
|---|---|---|---|
| 14 | `monte_carlo_var` (`risk.py`) | A/B + H | `_uniform_correlation_stress` (`:1218`) uses `min` not `max` — the fallback applies **no** correlation stress and **lowers** an already-high one; its call-site warning claims a stress that did not happen |
| 15 | `compute_risk_parity_weights` (`risk_budget.py`) | E + H | the function solves with its `tolerance` **parameter** and ignores the `risk.risk_parity_tolerance` config leaf; the module comment (`:1559–1562`) claims the reverse |

**Both were rated CLEAN by `docs/AUDIT_PHASE5_TIER5_FINDINGS.md`.** The fresh pass surfaced them — the
empirical justification for the operator's chosen option (*"Re-audit all 23 Tier-5 functions"*).

## The G-check pattern (era rule, measured)

The decision's `## D-NNN` line number vs `## D-118` (`docs/DECISIONS.md:19584`) predicts the confidence
form **exactly**, in every one of the 23 cards:

* **Post-D-118** (line > 19584): functions **6, 7, 8, 9, 10, 11, 12, 13, 23** → G = **PASS (product)**.
* **Pre-D-118** (line < 19584): functions **1–5, 14–22** → G = **OBSERVATION (era-correct)**.

No card contradicts the rule — the audit's own internal consistency check.

## Evidence-integrity events (harness artifacts, NOT model defects)

1. **Card 16, event 1 (O-156 shape):** a FOREGROUND `mutation_regime.py` run was SIGTERM'd mid-loop,
   leaving a **live mutation** + two sidecars. Repaired by byte-verifying against the sidecar and
   restoring; the sweep was re-run in the background.
2. **Card 16, event 2 (NEW shape):** the re-run exited **0** with **71/71 killed** and wrote **no
   sidecar**, yet left a **live mutation** (`if trend > 0.0` vs `trend > neutral_band`). Repaired with
   `git checkout HEAD`. **Lesson: `EXIT=0` + no sidecar is NOT sufficient — always `git status` after a
   sweep.** (Distinct from O-155 and O-156.)
3. **Card 17 pre-flight:** a timed-out `--check-targets` left sidecars; the sweep's own pre-flight
   **self-healed** them (O-131 lifecycle working as designed).
4. **Post-D-129 sweep verification (NEW shape, O-158):** after the `monte_carlo_var` and
   `statement_text` sweeps both exited **`EXIT=0`** with every mutant killed and **no refusal
   `WARNING`**, two `.sweepbackup` sidecars survived (`config.py`, `risk.py`), each **byte-IDENTICAL to
   its live file** — inert, but a hazard for the *next* run (which heals from them). `sweep_health.py`
   correctly still reported **`OK` / `leftover mutations: 0`** because a content-equal sidecar is not a
   leftover *mutation*. Removed after byte-verification. **Standing probe:** `find src -name
   '*.sweepbackup'` after every sweep, `diff` each survivor vs its live file. Recorded as **O-158**.

## Mutation-sweep results (Check H)

| Sweep | Result |
|---|---|
| `mutation_regime.py` (function 16) | **71/71 killed**, `EXIT=0` (leftover repaired) |
| `mutation_statement_text.py` (function 23) | **34/34 killed**, `EXIT=0`, 0 survivors, no leftover (O-157 did not recur) — `--check-targets 34, 0 problems` |
| `mutation_yield_curve.py` (function 17) | **89/90 killed** (1 inert canary); 1 survivor `MX2d` measured **EQUIVALENT** (D-031) |
| `mutation_econometrics.py` (functions 18–22) | **108/109 killed** (1 `INERT_BY_ROUTE`: `M34`, unreachable behind the M35 critical-value guard) |
| `mutation_monte_carlo_var.py` (function 14) | **40/40 killed**, `EXIT=0` (was 39 before D-129 added `M4e`); the new `M4e` — `max` reverted to `min` — is **KILLED** by the new guard test |

**Every sweep was run ONE AT A TIME (D-114); no gate ran concurrently.**

## Gate results after the D-129 fixes (measured, quiescent)

| Gate | Result |
|---|---|
| `ruff check src tests tools scripts` | **All checks passed** (after the N802 rename of the f14 guard — see D-129 §3) |
| `ruff format --check ...` | **292 files already formatted** |
| `mypy --strict ...` | **Success: no issues in 292 source files** (= format count, D-035 ✅) |
| full suite (`--junitxml`, default `not live and not slow`) | **4104 total / 4103 passed / 0 failed / 0 errors / 1 skipped** — **+2 vs the pre-fix 4102**, exactly the two new `_d129` guards |
| `reachability_audit.py --check-baseline` | **PASS 58/58** (regressions: none; newly wired: none) |
| `openbb_reachability.py` | **OK** — serving **278 paths** |
| mutant-shape greps (`src/`) | **nothing** |
| `.sweepbackup` under `src/` | **none** |
| `sweep_health.py` **LAST** | **52 sweeps · 0 leftovers · 0 shapes · 0 committed · 0 failures · OK** |
