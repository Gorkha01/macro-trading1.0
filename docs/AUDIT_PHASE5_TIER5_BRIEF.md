# AUDIT BRIEF — Phase 5+ / Tier 5 (all 23 functions)

**Written 2026-09-28, close of session** at `HEAD = c16427d` (`origin/main`, CI green).
**Purpose:** a cold-start brief so a NEW session can audit the **completed** Tier-5 / Phase-5+
implementations for real defects — bugs, logic mismatches, wrong math, wrong reasoning,
unavailable data, wrong inputs, un-integrated inputs — **without changing logic** and with
**every claim MEASURED, never recalled**.

> **OPERATOR'S STANDING RULE FOR THIS AUDIT (verbatim intent):**
> *"without changing logic and as per production grade check or audit must be done… all must be
> real not guessing."* So: **audit = find and EVIDENCE defects. Do not refactor. Do not
> redesign. Every finding must carry a measurement** (a command + its output), and a finding
> that cannot be measured is reported as **UNMEASURED**, never asserted.

---

## 0. THE ONE THING TO UNDERSTAND FIRST

**Tier 5 is COMPLETE — 23/23 as of D-125.** This audit is **not** auditing stubs. The functions
are **implemented, gated, swept and committed**. So the audit question is **NOT** "does it
exist?" but:

> **"Is the shipped implementation CORRECT — and does the evidence that certifies it actually
> hold?"**

That reframing is the whole audit. A green gate proves *layout, types and mutation coverage*. It
does **NOT** prove:
- the **math** is right (only that a test asserts *some* number),
- the **economics/reasoning** is right (only that a docstring says so),
- the **input wiring** is right (a wrong field with the right type passes every gate),
- the **data source** actually returns what the code assumes.

Those four are the audit's hunting grounds.

---

## 1. STATE AT HANDOFF (MEASURED — re-derive, do not trust this table)

| Item | Value |
|---|---|
| `HEAD` | `c16427d` (= `origin/main`; CI green) |
| Tier-5 completeness | **23 / 23** (D-125) |
| Latest decision | **D-125** (`docs/DECISIONS.md:20789`) |
| Newest open issue | **O-154** |
| Uncommitted in tree | `docs/OPENBB_ENDPOINT_RECONCILIATION.md`, `scripts/cross_asset_reaction.py`, `scripts/cross_asset_reaction_board.html`, `scripts/probability_demo.py` (operator tooling — **NOT** part of `src/`) |

**RE-DERIVE AT SESSION START** (a carried counter is a CLAIM — O-147):
```bash
git rev-parse HEAD
git status --short
grep -c "^## D-" docs/DECISIONS.md   # decision count
```

---

## 2. THE 23 TIER-5 FUNCTIONS AND THEIR FILES (MEASURED via grep)

| # | Function | File | Decision |
|---|---|---|---|
| 1 | `cip_check` | `models/fx_carry.py` | D-11x |
| 2 | `uip_expected_move` | `models/fx_carry.py` | D-112 |
| 3 | `ppp_valuation` | `models/fx_carry.py` | D-117 |
| 4 | `carry_score` | `models/fx_carry.py` | — |
| 5 | `dollar_smile_regime` | `models/fx_carry.py` | D-111 |
| 6 | `intervention_capacity` | `models/intervention.py` | D-118 |
| 7 | `em_vulnerability_checklist` | `models/em_vulnerability.py` | D-119 |
| 8 | `oil_balance_signal` | `models/commodities.py` | D-120 |
| 9 | `gold_driver_attribution` | `models/commodities.py` | D-121 |
| 10 | `metals_complex_divergence` | `models/commodities.py` | D-122 |
| 11 | `sector_rotation_prior` | `models/equity_macro.py` | D-123 |
| 12 | `duration_sensitivity` | `models/equity_macro.py` | D-124 |
| 13 | `factor_tilt_prior` | `models/equity_macro.py` | D-124 |
| 14 | `monte_carlo_var` | `models/risk.py` | — |
| 15 | `compute_risk_parity_weights` | `portfolio/risk_budget.py` | — |
| 16 | `classify_regime_markov_switching` | `models/regime.py` | D-105 |
| 17 | `yield_curve_pca` | `models/yield_curve.py` | D-102 |
| 18 | `run_regression` | `models/econometrics.py` | D-092 |
| 19 | `test_stationarity` | `models/econometrics.py` | D-094 |
| 20 | `test_cointegration` | `models/econometrics.py` | D-097 |
| 21 | `compute_pca` | `models/econometrics.py` | D-100 |
| 22 | `kalman_latent_state` | `models/econometrics.py` | D-101 |
| 23 | `statement_text_diff` | `models/policy_rules.py` | D-125 |

> ⚠️ **RE-DERIVE THIS TABLE.** A citation is a claim. Use the grep in §7 Step 1.

---

## 3. THE AUDIT FINDING CLASSES (what to look for — 8 classes)

Each class has **cost a session before** in this repo. Each is **measurable**.

### CLASS A — MATH: the arithmetic is wrong but the test asserts the wrong number
- **Symptom:** a test compares against a literal that was *copied from the implementation*.
- **Precedent:** `simple_gdp_nowcast` shipped with its **sign inverted** (corr **−0.057**
  against the thing it predicts); D-124 replaced hardcoded confidences.
- **MEASURE:** for each function, **hand-compute one case from the published formula in the
  docstring**, then run the function on that case, and **compare**. The docstring is the claim;
  the function is the artifact. They must agree.
- **Look for:** a sign that could be negated and still pass (the "two negations cancel" trap in
  `project_inflation_trajectory`), a `*` that could be `/`, a scale error (pp vs fraction vs bp).

### CLASS B — REASONING/ECONOMICS: the math is right but the economics are backwards
- **Symptom:** the sign of a relationship is wrong (e.g. "hot CPI → gold up" when the model's own
  measured base rate says 75.56% of the time gold reads **down**).
- **Precedent:** D-125's *"a hawkish REMOVAL read as hawkish"*.
- **MEASURE:** state the economic claim in one sentence; find its **measured base rate** in
  `config/settings.yaml` (many exist — `measured_gold_down_on_nominal_rise_share: 0.7556`,
  `measured_breakeven_negative_share: 0.2652`); check the code agrees with the measurement.
- **Look for:** a direction that would read as plausible either way — those are the dangerous ones.

### CLASS C — INPUT WIRING: the function reads the WRONG FIELD (right type, wrong meaning)
- **Symptom:** a correct-typed wrong variable. **No gate can catch this** — mypy sees `float`,
  the test supplies a `float`.
- **Precedent:** `cpi_core` supplied where `pce_core` was intended would pass every gate.
- **MEASURE:** for every input parameter, trace it **back to the snapshot `field` name** and read
  the registry entry (`data_layer/registry.py` or equivalent) to confirm the **unit and the
  definition match**. Then read the *caller* to confirm it passes the field the docstring names.
- **Look for:** two fields with similar names (`cpi_core`/`pce_core`, `gdp_real`/`gdp_potential`).

### CLASS D — DATA AVAILABILITY: the input does not actually exist / is never fetched
- **Symptom:** the code consumes a field that is declared-but-never-fetched.
- **Precedent — SEVEN FALSE BLOCKS:** functions were marked "BLOCKED / data unavailable" that
  were **LIVE on measurement** (D-118, D-119 half, D-120, D-121, D-122, D-117…), **and the
  reverse** — `fx_spot` / `sp500_index` are **declared-but-never-fetched (DEF-005)**.
- **MEASURE:** `grep -rn "<field>" src/` — if the **only** hit is a schema declaration and no
  fetcher consumes it, the data **does not arrive**. Then check the **latest snapshot parquet**:
  ```bash
  uv run python -c "import pandas as pd,glob; df=pd.read_parquet(sorted(glob.glob('data/raw/us/*.parquet'))[-1]); print(sorted(df['field'].unique()))"
  ```
- **⚠️ BOTH DIRECTIONS ARE DEFECTS:** claiming BLOCKED when it's live (wasted capability) AND
  consuming a field that never arrives (silent zero). **Measure, do not infer from the heading.**

### CLASS E — INPUT NOT TAKEN: the function ignores something it should consume
- **Symptom:** a parameter exists and is accepted but **never read** in the body — or a known
  input is simply absent from the signature.
- **Precedent:** `oil_balance_signal`'s `fetch_series` symbol-drop (O-148/149) — the transport
  silently dropped the symbol.
- **MEASURE:** for each function, list every parameter; `grep` the body for each name. An unused
  parameter is a candidate defect (**unless** the docstring says it is reserved — verify).
- **Look for:** the same value re-derived instead of the parameter used (D-057's P5).

### CLASS F — INTEGRATION: nothing calls it / it is called wrong
- **Symptom:** a function is perfect but **never reached** by the pipeline, or reached with
  arguments in the wrong order.
- **Precedent:** the reachability partition — Tier-5 has **18 unwired** functions.
- **MEASURE:** run the reachability tool (see §7 Step 5). For each function, find its caller and
  read the call site's arguments against the signature.
- **Look for:** a caller passing `(a, b)` where the signature is `(b, a)` — same types pass mypy.

### CLASS G — CONFIDENCE / PROVENANCE: the confidence number is not actually computed
- **Symptom:** a hardcoded `confidence=0.5` where §22.8 requires `compute_confidence()`.
- **Precedent:** D-124 replaced **hardcoded confidences** with the §22.8 product; `output_gap`'s
  spec'd literal `0.5`.
- **MEASURE:** `grep -n "confidence=" <file>` — a **literal** is a defect; a call to
  `compute_confidence()` is correct. Confirm the inputs to that call are the right flags.
- **Look for:** a `0.0` that is indistinguishable from "not computed".

### CLASS H — EVIDENCE INTEGRITY: the test/sweep certifies something false
- **Symptom:** a mutation **survivor** (test too weak), a **shadowed test** (same name twice),
  a **false survivor** from a leftover mutation, a **clock-dependent** test, a **name-grep
  mistaken for coverage**.
- **Precedents (many):** O-131 (leftover mutation → false survivor), O-133 (name-grep ≠ coverage),
  O-134 (wall-clock test), O-150 (six tests defined twice ⇒ six DEAD), D-121 (six shadowed tests).
- **MEASURE:** run the mutation sweep for the target file **in full** and **read every survivor**;
  triage each (D-031): a hardcoded-shipped-value survivor = **weak test** (perturb the LEAF);
  a boundary survivor needs a fixture **ON the threshold**.
- **⚠️** verify tree clean + sidecar **ABSENT** before AND after every sweep (O-131).
- **⚠️** NEVER run a gate while a sweep runs (D-114).

---

## 4. THE EIGHT TRAPS (each has cost a session — read `REFERENCE.md` for full text)

Work from `REFERENCE.md`, **never from memory** (a restated list drifts — lesson 5cn):

1. **No claim of an edit without RE-READING the line from disk** (O-130). No gate reads prose.
2. **A name-grep is not a coverage proxy** (O-133) — **measure EXECUTION**.
3. **A test whose verdict depends on the wall clock is a CLOCK, not a test** (O-134) — control
   the input time (`as_of=`).
4. **`pytest.raises(SomeError)` asserts the TYPE, never the CAUSE** (O-127) — add `match=`, keep a
   negative control, run the selection GREEN-UNMUTATED first.
5. **A suggested gate is a claim about what a gate would CATCH** (D-110). **A DISCLOSURE is not a
   MEASUREMENT. A false gate is worse than none.**
6. **Adding a function to a SWEPT module makes the OLD anchors AMBIGUOUS; WIDEN, never delete**
   (D-109/111/112/118/119/120/121/123/124). **A widening is a claim about BYTES** — measure
   `count() == 1` by reading the file in Python.
7. **A LEFTOVER mutation manufactures a FALSE SURVIVOR** (O-131) — sidecar ABSENT before AND after.
8. **Re-derive every count** (O-147). **A dated D-narrative counter is HISTORY — do not rewrite it.**

---

## 5. GATES — THE EXACT COMMANDS (re-derive counts; D-035: counts must MATCH)

**ORDER IS LOAD-BEARING.** `ruff check` FIRST → format → mypy → live check → reachability →
suite → sweep → `sweep_health.py` LAST.

```bash
# 0. Pre-flight — tree clean + sidecar ABSENT, then the WIDE shape grep (MUST print nothing)
git status --short
grep -rn "MUTANT\|if False:\|if True:\|and True:\|or False:" src/macro_engine/

# 1. ruff check FIRST (CI short-circuits on it — D-119 lost a cycle to 12 lint errors)
uv run ruff check src tests tools scripts

# 2. format == mypy --strict == the pinned count (⚠️ RE-DERIVE the number; it is
#    asserted by the gate list, and a stale count is itself a defect — O-147)
uv run ruff format --check src tests tools scripts
uv run mypy --strict src tests tools scripts

# 3. TARGET SUITE for the module under audit (run GREEN-UNMUTATED first)
uv run pytest tests/models/ -q

# 4. FULL suite via junitxml (the safe-delete hook leaks exit=1 on a green run)
uv run pytest --junitxml=C:/Users/Hp/AppData/Local/Temp/audit.xml -q
#    read the XML from: C:\Users\Hp\AppData\Local\Temp\   (/tmp in Git Bash is NOT /tmp to Python)
#    NOTE: the `slow` marker is EXCLUDED — run a changed slow test explicitly with `-m slow`

# 5. Reachability (Tier-5 partition is DIFFERENT from Tier 1-4 — re-derive BOTH headings)
#    the tool's "SCRIPT-ONLY — Tier 5" heading EXCLUDES the one under "NO CALLER — Tier 5"

# 6. Mutation sweep for the target file — FULL run, read every survivor
uv run python scripts/mutation_<module>.py
#    ⚠️ tree clean + sidecar ABSENT before AND after (O-131)

# 7. sweep_health.py LAST → expect: 50 sweeps · 0 leftovers · 0 shapes · 0 committed · 0 failures · OK
#    ⚠️ The sweep census lives in THREE places and must be edited TOGETHER:
#    tests/test_sweep_sidecar_lifecycle.py (x2: function NAME + assertion) and
#    tests/test_sweep_health_leftover_predicate.py (x1). MEASURED this session: the
#    census reached **50 at D-125** (48->49 at D-123 `mutation_equity_macro.py`,
#    49->50 at D-125 `mutation_statement_text.py`) — RE-DERIVE, do not trust "50".
uv run python scripts/sweep_health.py
```

**⚠️ NEVER run ANY gate while a sweep is running (D-114)** — the sweep rewrites its target
between runs, so a gate would read the MUTATED source.

---

## 6. THE AUDIT METHOD — one function at a time, no batching

For **each** of the 23 functions, produce a **finding card**:

```
FUNCTION:        <name>  (<file>:<line>)
DECISION:        D-<n>  (read it in docs/DECISIONS.md first)
SPEC CITE:       §<n>   (resolve with `grep -n` — a citation is a claim)
--- 8 CHECKS ---
A MATH:          hand-compute 1 case from the docstring formula → run → compare. RESULT: ___
B ECONOMICS:     state the claim; find its measured base rate; code agrees? RESULT: ___
C WIRING:        each param traced to snapshot field + registry unit. RESULT: ___
D DATA:          field fetched? (grep src + read latest parquet). RESULT: ___
E INPUT-TAKEN:   every param read in body? RESULT: ___
F INTEGRATION:   caller found? args match signature? RESULT: ___
G CONFIDENCE:    compute_confidence() or literal? RESULT: ___
H EVIDENCE:      sweep run in full; every survivor triaged. RESULT: ___
--- VERDICT ---
STATUS:          CLEAN | DEFECT | UNMEASURED
EVIDENCE:        <the exact command + its output>   ← MANDATORY. No evidence ⇒ UNMEASURED.
DEFECT CLASS:    A|B|C|D|E|F|G|H
```

**RULES for the verdict:**
- **`CLEAN`** requires a **positive measurement**, not the absence of a finding.
- **`UNMEASURED` is a legitimate and required verdict** — never upgrade it to CLEAN by assumption.
- **A defect finding must NOT be fixed in this audit** (operator: "without changing logic"). Record
  it; the fix is a separate increment under the normal D-number process.
- **The audit changes NO `src/` file.** It writes findings only.

---

## 7. START-OF-SESSION SEQUENCE (do this before anything else)

```bash
# 1. Re-derive the function table (§2) — do NOT trust the table
grep -rn "def cip_check\|def uip_expected_move\|def ppp_valuation\|def carry_score\|def dollar_smile_regime\|def intervention_capacity\|def em_vulnerability_checklist\|def oil_balance_signal\|def gold_driver_attribution\|def metals_complex_divergence\|def sector_rotation_prior\|def duration_sensitivity\|def factor_tilt_prior\|def monte_carlo_var\|def compute_risk_parity_weights\|def classify_regime_markov_switching\|def yield_curve_pca\|def run_regression\|def test_stationarity\|def test_cointegration\|def compute_pca\|def kalman_latent_state\|def statement_text_diff" src/macro_engine/

# 2. Read the authority order
#    .workbuddy-ai/memory/HANDOFF.md  (cold-start router)
#    docs/DECISIONS.md                (the AUTHORITY; D-125 newest)
#    docs/OPEN_ISSUES.md              (O-154 newest)
#    .workbuddy-ai/memory/REFERENCE.md (ALL standing rules + full trap list)

# 3. Confirm pre-flight (§5 Step 0)

# 4. Pick ONE function. Read its D-decision. Then run the 8 checks.

# 5. Per-module sweep; then sweep_health.py LAST.
```

---

## 8. WHAT IS ALREADY KNOWN-OPEN (do not re-discover — verify, then extend)

These are documented open items that touch Tier-5 functions. **Verify each still holds**, then
look for *new* ones (the audit's real value):

| Issue | Relevant to | Summary |
|---|---|---|
| **O-152** | D-122 probe | a probe needed a **CONTROL** (`DCOILWTICO` 2,926 vs 139) |
| **O-153** | D-122 | the unit must come from the **PROVIDER's metadata**, not a web search |
| **O-154** | D-122 | a survivor's kill can live in a **DIFFERENT gate** (a mypy-only mutation looked like a weak test) |
| **O-147** | counters | a running counter is a CLAIM — measure, never carry |
| **O-75** | catalysts | the catalyst horizon `120` is **uncalibrated** — no measurement stands behind it |
| **O-105** | calendar | the economic calendar is **UA-blocked** on transport |
| **DEF-005** | `fx_spot`, `sp500_index` | declared-but-never-fetched — **no FX spot, no equity price** |

**⚠️ THE RECURRING THEME:** the repo's **own history says the biggest risk is not a wrong
function — it is accepting a boundary claim as measured.** 7 FALSE BLOCKS, 1 CONFIRMED block,
O-131 false survivors, O-133 name-grep-as-coverage. **When in doubt, MEASURE.**

---

## 9. WHAT THIS AUDIT IS **NOT**

- **NOT** a refactor. No logic changes. No "cleaner" rewrites.
- **NOT** a re-implementation of Tier 5 — it is already 23/23.
- **NOT** permission to trust D-narratives: **a decision entry is a claim about the tree.**
  Verify it against the tree (O-130).
- **NOT** a place to fix what it finds — findings are recorded, fixes are separate increments.
- **NOT** a demo build: the three uncommitted `scripts/*` viewers are **operator tooling**, not
  audit targets, and not `src/`.

---

## 10. THE SUCCESS CRITERION

The audit is **done** when every one of the 23 functions has a finding card with:
1. all **8 checks** attempted,
2. a **STATUS** of `CLEAN | DEFECT | UNMEASURED`,
3. **EVIDENCE** attached to **every** claim (a command + its output), and
4. **zero** `src/` modifications.

A **`DEFECT`** card is a success. An **`UNMEASURED`** card is a success (it is honest). A **`CLEAN`**
card with no evidence is a **failure** — it is the exact shape of the FALSE BLOCK that has cost
this project seven times.

---

*Written at the close of session 2026-09-28. `HEAD = c16427d`. Next: a fresh session reads §7,
picks a function, and runs the 8 checks. **Measure everything. Assume nothing.***
