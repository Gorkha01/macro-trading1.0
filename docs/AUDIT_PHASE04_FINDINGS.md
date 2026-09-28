# AUDIT FINDINGS — Phase 0–4 `src/` (the files the Tier-5 audit did NOT cover)

**Audit run:** 2026-09-28 (session 3), `HEAD = 26a914fbd0effd74a806ce62d2ce61f5ffc8d07a`.
**Trigger:** the operator's correction — the Tier-5 audit (`docs/AUDIT_PHASE5_TIER5_FINDINGS.md`)
walked the **23-name §21.3 list**, not the **whole `src/` tree**. Everything built in Phases 0–4
was accepted as pre-existing and never given the same file-by-file pass. This file is that pass.
**Scope (RE-DERIVED, not carried — O-147):** the **68** tracked `src/**/*.py` files **NOT** in the
Tier-5 list (79 total − 11 Tier-5-covered), of which **5** are empty `__init__.py` ⇒ **63**
substantive files.
**Method:** the **same 8 classes (A–H)** and the same **MEASURED-EVIDENCE** standard as the Tier-5
audit. **No `src/` changes** (audit-only; fixes go to the operator first). One file at a time.
**Status legend:** `CLEAN` (positive measurement) | `DEFECT` (measured fault) | `UNMEASURED` (no measurement) | `OBSERVATION` (disclosed, not a fault).

**REMEDIATION (D-127, 2026-09-28):** the operator authorised fixing the audit's three **Phase 0–4**
defects — **#5** `inflation_breadth_score` (Card 23), **#6** `ppi_pipeline_signal` (Card 24), **#7**
`statement_text_diff` (Card 25) — to production grade. Each card carries a
**`✅ STATUS UPDATE — FIXED`** block beneath its finding.

**REMEDIATION 2 (D-128, 2026-09-28):** the operator followed the D-127 close-out with a **second
go-ahead** — *"go-ahead"* — authorising the **remaining four DEFECT-status cards (7, 19, 21, 22)** plus
the **Card-4 evidence gap**, to the same standard. **All five are now fixed** (Cards 4, 7, 19, 21, 22
each carry a `✅ STATUS UPDATE — FIXED` block):

* **Card 7** `project_shelter_cpi` — the `uncalibrated_illustrative` `shelter_lag_months` was read while
  confidence defaulted to 0.7; now 0.50 (leaf-tracked). Sweep 23/23.
* **Card 19** `inflation_convergence` — a hardcoded `0.75` leaf-ified + validator; `agreeing/opposing`
  renamed `majority/minority`; `majority_direction` published. Sweep 33/33.
* **Card 21** `output_gap` — docstring corrected (the audit's *preferred* option: code is the truth),
  pinned by two tests. Sweep 40/40.
* **Card 22** `instrument_selection` — `equity_macro` template de-prosed to a real universe member;
  guard strengthened with `permits`; per-route membership pin added. Sweep: **all 3 M9b killed**.
* **Card 4** `as_of` — the missing test file (**16 tests**) and a mutation sweep (**17/17**) created;
  no code changed (it was already correct).

**Every Phase 0–4 DEFECT-status card and the Card-4 evidence gap is now closed.**


**Class key:** A=MATH · B=ECONOMICS/REASONING · C=INPUT WIRING · D=DATA AVAILABILITY ·
E=INPUT-NOT-TAKEN · F=INTEGRATION · G=CONFIDENCE/PROVENANCE · H=EVIDENCE INTEGRITY.

**Pre-flight (measured):** `git status --short` empty · wide shape grep
(`MUTANT|if False:|if True:|and True:|or False:`) **empty** · sidecars **0**.

---

## CARD 1 — `src/macro_engine/models/real_policy_rate.py` (75 lines)

**Purpose:** `real_policy_rate = nominal_policy_rate − inflation_rate` (ex-post Fisher). Docstring
opens by stating it is the **Part B pluggability experiment** ("how many files must change to add a
new indicator?").

**STATUS: CLEAN** (two documented OBSERVATIONS; class F is a deliberately-disclosed orphan)

**EVIDENCE:**
- **(A) MATH — PASS.** Hand-computed two cases from the docstring's own formula and compared:
  ```
  $ ... real_policy_rate(RealPolicyRateInputs(nominal_policy_rate=5.25, inflation_rate=3.20))
  value = 2.05 | expected 5.25-3.20 = 2.05          # PASS
  $ ... real_policy_rate(RealPolicyRateInputs(nominal_policy_rate=0.25, inflation_rate=5.40))
  neg case value = -5.15 | expected 0.25-5.40 = -5.15   # sign convention holds (accommodative)
  ```
  Line 51 is exactly `inputs.nominal_policy_rate - inputs.inflation_rate`; the docstring claims
  `r_real = i - pi`, and the artifact agrees.
- **(G) CONFIDENCE — PASS (with era OBSERVATION).** `confidence=compute_confidence(
  ConfidenceInputs(depends_on_unobservable=False))`. Measured: the published confidence is **0.7**,
  identical to `clamp(base)` from config (`base=0.7, ceiling=0.95, floor=0.05`) — so it is the
  computed value, **not a literal**. The docstring's claim *"both inputs are measurements here… so
  no unobservable is declared and no heuristic flag is set"* is **accurate**: `depends_on_unobservable`
  is a real `ConfidenceInputs` field (`contracts.py:99`) and it is correctly `False`.
  **OBSERVATION (era):** there is **no cap product** (`× cap`) — **era-correct**, because this is a
  Tier-1 function that predates D-118 (2026-09-28). Not a defect.
- **(E) INPUT-NOT-TAKEN — PASS.** Both fields are read: `nominal_policy_rate` and `inflation_rate`
  both appear at line 51 (the arithmetic), and both are listed in `inputs_used`. Nothing declared is
  ignored.
- **(D) DATA — PASS (N/A).** The function fetches nothing; it is pure arithmetic over two supplied
  scalars (models do not fetch). No data-availability question applies.
- **(F) INTEGRATION — ORPHAN, but DISCLOSED (not a defect).** `grep` for any caller in
  `thesis_layer/` and `api_layer/` returns **nothing**; the file is genuinely unwired. This is
  **intentional and disclosed in the docstring's first paragraph** — the file exists *as the
  pluggability experiment*, not as a wired indicator. Recorded as a disclosed orphan, not a hidden
  one.
- **(H) EVIDENCE — PASS.** `pytest tests/models/test_real_policy_rate.py -q` → **6 passed**; no
  duplicate `test_*` names (`uniq -d` empty).

**OBSERVATION 1 — the input contract is documented but NOT enforced.** The `inflation_rate`
docstring demands a specific measure: *"it must be the SAME measure year-over-year, not a
month-over-month figure annualised."* **Nothing validates it** — measured: no `field_validator`,
`model_validator`, or `ge=/le=` bound anywhere in the file:
```
$ grep -n "field_validator|model_validator|ge=|le=" src/macro_engine/models/real_policy_rate.py
(no output — only the confidence= line)
```
A caller could pass `inflation_rate=-999.0` or a MoM figure and the function would publish a
plausible-looking real rate. This is the **Class C shape** (right type, unverified meaning). It is
recorded as an **OBSERVATION, not a DEFECT**, because (i) the requirement is explicitly disclosed in
the docstring, (ii) models do not fetch so the caller is the authority on units, and (iii) the
sibling `policy_rules.py` shows the validator convention exists (3 validators) — so adding one here
would be a *consistency* improvement, not a correctness fix. **Candidate for a later hardening pass;
not an audit defect.**

**OBSERVATION 2 — the `+` in the interpretation string.** Line 60 formats as `{value:+.2f}%`, so a
negative real rate renders as `-5.15%` and a positive as `+2.05%` — correct and intentional (the
sign is the indicator's whole point, per the docstring). No issue; recorded because the audit
read the format string and confirmed it.

---

## CARD 2 — `src/macro_engine/models/evidence_family.py` (78 lines)

**Purpose:** the `EvidenceSourceFamily` enum — the **source-family vocabulary** (Module 13,
§15.19-D). A family is a shared upstream production process; the enum feeds
`count_independent_families`, which is the denominator for convergence confidence.

**STATUS: CLEAN** (one OBSERVATION — a large forward vocabulary)

**EVIDENCE:**
- **(A/C) VOCABULARY INTEGRITY — PASS.** A `str, Enum` of **31** members. Registered values are
  unique — measured:
  ```
  $ ... [m.value for m in EvidenceSourceFamily]
  members: 31 | distinct values: 31 | DUPLICATE VALUES: none
  ```
  This is load-bearing: `count_independent_families` dedupes by `family.value` (`.value in seen`,
  `evidence.py:175`), so a duplicate value would collapse two families into one vote.
- **(C) NO STRING-ENUM BYPASS — PASS.** Because members subclass `str`, a bare quoted literal equal
  to a family value would silently satisfy the type. Measured — **zero** bare-string family-value
  references anywhere in `src/` (outside this file):
  ```
  $ ... scan src/**/*.py for '"' + v + '"' for every member value v
  bare-string family-value references: 0
  ```
  Every assignment site uses the typed member (`EvidenceSourceFamily.MARKET_FX`, `.MANUAL_ASSESSMENT`,
  `.IMF`, …).
- **(G/D/E/F) — N/A.** A vocabulary module: no confidence, no fetch, no inputs, no calls (it is
  imported by 12 modules, so it is well-integrated in the *other* direction).
- **(H) — N/A.** No functions to test; exercised indirectly through every consumer.

**OBSERVATION — 23 of 31 members are referenced by name nowhere yet.** Measured:
```
used: 8 | unused: 23
UNUSED MEMBERS: ['BLS_PPI','CLEVELAND_FED','MARKET_BREAKEVEN','SURVEY_EXPECTATIONS','PRIVATE_RENT',
 'BLS_EMPLOYMENT_SITUATION','BLS_JOLTS','DOL_CLAIMS','BEA_NIPA','CENSUS_RETAIL','CENSUS_DURABLE',
 'CBO_POTENTIAL','CONFERENCE_BOARD','FED_SLOOS','TREASURY_OFFICIAL','FED_H41','FED_NY_ACM',
 'TREASURY_AUCTIONS','MARKET_CREDIT_SPREADS','MARKET_EQUITY_VOL','UMICH','NY_FED_HLW','WGC']
```
**Not a defect.** The docstring declares the vocabulary as forward-looking (*"trimmed-mean, median
and supercore — in later phases"*), the members are the §15.19-D vocabulary, and a family with no
consumer yet is a **declared** future input, not dead code. Recorded so a future phase does not
mistake the count for a completeness claim.

---

## CARD 3 — `src/macro_engine/models/evidence.py` (238 lines)

**Purpose:** Module 13's two functions — `tag_evidence_source` (attach provenance to a `ModelResult`)
and `count_independent_families` (the redundancy correction: five CPI sub-measures are ONE vote).

**STATUS: CLEAN**

**EVIDENCE:**
- **(A/B) MATH & REASONING — PASS.** Hand-computed three cases against the docstring's contract:
  ```
  $ 5 results, 2 duplicated families  => distinct=3 dup=2 tagged=5 untagged=0   # PASS
  $ 1 untagged among 3                => distinct=2 untagged=1 tagged=2         # PASS (untagged EXCLUDED, reported)
  $ empty list                        => distinct=0, no error                   # PASS
  ```
  The dedup is by value (`.value in seen`), the untagged are counted separately (never pooled as
  independent — the false-convergence failure the module exists to prevent), and the empty case
  returns 0 with a disclosure rather than raising.
- **(G) CONFIDENCE — PASS (with era OBSERVATION).** Published confidence = **0.5**, identical to
  `clamp(base − heuristic) = 0.7 − 0.2` from config — **computed, not a literal** (`confidence=confidence`,
  line 228). It passes `is_heuristic_not_calibrated=True, source_independence_count=0`, which is
  **economically correct**: the census's own confidence is about the *count's accuracy*, and crediting
  the census with its own count would be circular. (Era: no cap product — pre-D-118.)
- **(E) INPUT-NOT-TAKEN — PASS.** Every parameter is read: `tag_evidence_source` reads
  `model_result`, `family`, `data_quality_flags_present` (all three at lines 128/137/142);
  `count_independent_families` reads `tagged_results` throughout.
- **(C/F) WIRING/INTEGRATION — PASS.** Returns a copy on tag (does not mutate the argument — the
  spec's version is documented as mutating a shared warnings list); a re-tag to a *different* family
  is a **refusal** (`raise ValueError`), the same family is idempotent. The type is the typed field,
  **not** the spec's `source_family=…` warning-string-parse (documented correction).
- **(D) DATA — N/A.** Pure; consumes no market data.
- **(H) EVIDENCE — PASS.** `pytest tests/models/test_evidence.py -q` → **23 passed**; no duplicate
  `test_*` names.

---

## CARD 4 — `src/macro_engine/models/as_of.py` (215 lines)

**Purpose:** the **point-in-time discipline** (§5.5, O-7) — filter a series to observations that
existed at `as_of`, so a model never computes against a **forward-dated projection** (the
`gdp_potential`=GDPPOT case: 41 of 62 points were future-dated CBO projections). Imported by
`orchestration.py`, `snapshot_builder.py`, `gdp_nowcast.py`, `labor_synthesis.py`, `regime.py`.

**STATUS: CLEAN (code) · ⚠️ DEFECT-CLASS EVIDENCE GAP (H) — the module has NO dedicated test and
is NOT swept.**

**EVIDENCE — code is correct (all Class A cases pass):**
```
$ unsorted [Mar, Jan] filtered to mid-2026     => [1.0, 3.0] oldest-first, withheld=1, horizon=2036-01-01  PASS
$ observation dated EXACTLY the as_of day       => INCLUDED (docstring claim holds)                        PASS
$ every point forward-dated                     => is_empty=True, latest=None, withheld=1                  PASS
$ observation_on_or_before(historical target)   => reads the HISTORICAL point, not today's cutoff            PASS
```
- **(A) MATH/DATE BOUNDARY — PASS.** The cutoff is by **calendar date** (`moment.date()`), so a
  same-day observation is included (verified). The `> cutoff` / `<= cutoff` split is exhaustive and
  the sort is by `observation_date`, so `[-1]` is genuinely the latest.
- **(B) REASONING — PASS, and honestly disclosed.** The docstring states the filter is *"SUFFICIENT
  but not SOUND"* — publication lags the observation, and `release_datetime` is unavailable on the
  reachable routes, so **an `as_of` inside one reporting lag may include not-yet-public data.** This
  is disclosed in the module docstring rather than hidden — the correct treatment of a known limit.
- **(E) INPUT-NOT-TAKEN — PASS.** `points`, `as_of`, `series_id` (observation_as_of) and `target`
  (observation_on_or_before) are all read; `observation_on_or_before` deliberately does **not** route
  through `observation_as_of` (documented, and verified correct: it answers a historical question).
- **(G) — N/A.** Returns a frozen dataclass `AsOfSeries`, not a `ModelResult`; no confidence.
- **(D) — PASS (N/A).** Pure filter; no fetch.
- **(H) EVIDENCE — ⚠️ DEFECT-CLASS GAP, measured:**
  ```
  $ grep -rn "from macro_engine.models.as_of import" tests/
  (empty — NO test imports the module)
  $ ls tests/models/ | grep as_of
  (none — no test_as_of.py)
  $ ls scripts/ | grep -i "as_of|asof"
  (none — no mutation sweep)
  ```
  The two apparent references are **not coverage**: `test_curve_point_in_time.py:4` is a **docstring
  mention** (prose), and `test_reserves_client.py:208` is a differently-named local helper. The
  module is therefore exercised **only indirectly** through its consumers. **Its own documented
  contracts** — the same-day-inclusion boundary, the `sufficient-but-not-sound` lag caveat, the
  `on_or_before`-vs-`as_of` asymmetry, and the "empty is a hard stop, never 0.0" rule — are asserted
  **nowhere**. This is the O-133 shape applied to a whole module: a load-bearing module whose
  behaviour no test names.

**PRESCRIPTION (not applied — audit-only):** add `tests/models/test_as_of.py` covering the four
contracts above (the audit's Class-A cases in this card are a ready-made seed, and each passes against
the shipped code). Consider a sweep if the module gains branching. **Recorded as an EVIDENCE gap, not
a code defect — the code is correct on every measured case.**

### ✅ STATUS UPDATE — **FIXED** (D-128, 2026-09-28)

**The evidence gap is CLOSED; no code changed (the code was already correct).** The prescription was
applied in full and *more*:

- **`tests/models/test_as_of.py` created — 16 tests.** All four documented contracts are now pinned:
  the **same-day-inclusion boundary** (and its negation: a next-day point IS withheld), the
  **sufficient-but-not-sound lag caveat** (a point stamped the day before `as_of` is *retained* — the
  disclosure made executable), the **`observation_on_or_before`-vs-`observation_as_of` asymmetry** (the
  fixture is built so the two would *disagree*, which is the only case where the asymmetry is visible),
  and **"empty is a hard stop, never `0.0`"** (the all-forward-dated GDPPOT shape → `is_empty`, `latest
  is None`, and the withheld count/horizon still reported so the caller can say *why*). Plus the
  no-silent-truncation report, oldest-first sorting on shuffled input, the `series_id` override, and the
  `utc_now()` default.
- **`scripts/mutation_as_of.py` created — 17 mutants, 17/17 killed, canary live.** The audit said
  "consider a sweep if the module gains branching"; it has it (a date split, a sort, a default clock, an
  empty-vs-withheld distinction, a horizon reduction), so the sweep was written rather than deferred.
  `CANARY1` (a syntax-error substitution) is KILLED, so the kill rate is evidence about the suite and
  not about the harness (D-051/O-72). The centrepiece mutants are the two **opposite** boundary
  reversals (`<=`→`<`, and `>`→`>=` in the withheld split), so a pass cannot be luck of direction.

**MEASURED:** `pytest tests/models/test_as_of.py` → **16 pass**; `mutation_as_of.py` → **17/17 killed**.
The module is no longer the O-133 shape (a load-bearing module no test names).

---

## CARD 5 — `src/macro_engine/extensions/` (6 files, 29–46 lines each) — grouped

`backtest_vbt.py` · `bayesian_updater.py` · `duckdb_store.py` · `mlflow_tracking.py` ·
`nautilus_adapter.py` · `scheduler.py`

**Purpose:** the §12 Phase-5+ interface contracts (vectorbt, PyMC, DuckDB, MLflow, NautilusTrader,
APScheduler). Each declares the signature + contract its future implementation must honour and raises
`NotImplementedError` naming the Phase-4 dependency gate.

**STATUS: CLEAN — sanctioned, unreachable, dependency-gated interface contracts (NOT stubs).**

**The no-stubs rule, resolved by measurement.** The project's non-negotiable bans a **reachable**
`NotImplementedError`. These are **unreachable**, proven three ways:
```
$ grep -rn "extensions" src/ --include=*.py | grep -v ^src/macro_engine/extensions/   # consumers
src/macro_engine/data_layer/persistence.py:5:  ... ``extensions/duckdb_store.py`` is the Phase 5+ ...   # a DOCSTRING mention only
$ grep -rn "extensions" tests/ --include=*.py
tests/models/test_equity_macro.py:117/195:   # the words "extensions are disjoint", unrelated
$ grep -n "extensions" tools/reachability_audit.py
(empty - the reachability tool does not even count them)
```
No Phase 1-4 module imports them; no test touches them; the reachability tool excludes them. They can
only be reached by an explicit `from macro_engine.extensions... import`, which no caller does.
**AGENTS.md:245 specifies this exactly** — `├── extensions/  # Section 12 — deferred, stubbed only`.

- **(A–H) — N/A.** No arithmetic, no data, no confidence, no callers. Each module **imports cleanly**
  (measured with `importlib.import_module` for all 6), and each carries a design *rationale* that is
  itself an interface constraint (e.g. `nautilus_adapter` documents that automatic execution is
  forbidden by §1.1/§9.3 — the refusal is a named constant `NOT_PERMITTED_AUTOMATICALLY`, not a
  silent no-op).

**OBSERVATION (not a defect):** these are the ONLY sanctioned `NotImplementedError` bodies in the
tree; see **X-A** below for the *other* six, which are refusals rather than deferrals.

---

## CROSS-CUTTING X-A — every live `NotImplementedError` in `src/` is a REFUSAL, not a stub

**Not one reachable `NotImplementedError` in the shipping path is a stub.** Measured — all 15 sites:
```
$ grep -rn "raise NotImplementedError" src/ --include=*.py
(15 sites: 8 in extensions/ [Card 5]; 7 in live Phase 1-4 modules)
```
The **7 live sites** are all §22.3 or §21.1 **refusals** — a function that WORKS on the US/verified
path and REFUSES an out-of-scope input rather than mislabelling it:

| Site | What it refuses | Rule |
|---|---|---|
| `api_layer/orchestration.py:1723` | a non-`us` snapshot (`if snapshot.country != "us"`) | §22.3 (US-only) |
| `data_layer/snapshot_builder.py:835` | a country not in `settings.country.implemented` | §22.3 |
| `models/gdp_nowcast.py:552` | `output_gap` on a non-`us` snapshot | §22.3 |
| `models/regime.py:1275` | `check_trilemma_tension` on a non-`us` input | §22.3 |
| `config.py:1724 / 1734` | a **BLOCKED** or **unverified** series (`require_verified`) | §21.1 |
| `config.py:4338` | an empty Bayesian likelihood table (`require_likelihoods`) | §21.1 |

**Measured:** `get_settings().country.implemented == ['us']`, so the country guards are the only
reachable branch for a non-US argument, and each US path carries real computation after the guard
(e.g. `output_gap` continues to the same-quarter pairing logic). This is the repo's *"refuse rather
than guess"* rule — the type `NotImplementedError` is used because Python has no dedicated
`RefusalError`, and the messages name the section and the reason. **No defect.** Recorded because a
file-by-file pass must *prove* the absence of stubs, not assume it.

---

## CARD 6 — `src/macro_engine/models/contracts.py` (354 lines)

**Purpose:** the `ModelResult` reason-object contract + `ConfidenceInputs` + `compute_confidence`
(§22.8's single confidence producer) + `ModelValue`. The spine of every model.

**STATUS: CLEAN**

**EVIDENCE:**
- **(A) MATH — PASS.** `compute_confidence` re-derived against config on an all-flags case:
  ```
  $ compute_confidence(ConfidenceInputs(data_quality_flags_present=True,
        is_heuristic_not_calibrated=True, depends_on_unobservable=True,
        source_independence_count=3))
  = 0.2 | hand-derived clamp(base - 3 penalties + min(3*bonus, bonus_cap)) = 0.2 | match: True
  ```
  The formula is `base − penalties + min(count*bonus, bonus_cap)`, clamped into `[floor, ceiling]`
  (lines 144–155) — matches the docstring's four-step description exactly.
- **(G) CONFIDENCE/PROVENANCE — PASS.** The `confidence` field is
  `Annotated[float, Field(ge=0.0, le=1.0)]`; measured — `-0.1` and `1.1` both raise `ValidationError`.
  `extra="forbid"` measured — a misspelled `confidencex=0.9` raises rather than being silently
  ignored (the §22.8 comment's stated reason for `extra="forbid"`). The docstring's "RELIABILITY
  measure, not a probability the model is correct" note is present and correct.
- **(C) WIRING — PASS.** `ModelValue` union measured as
  `float | int | str | bool | dict[str,Any] | list[Any] | None` (7 members) — identical to the
  documented §22.9 union.
- **(E) INPUT-NOT-TAKEN — N/A.** A contract module; `ConfidenceInputs` has all four factors read by
  `compute_confidence` (data-quality, heuristic, unobservable, independence).
- **(D) DATA — N/A.** No fetch.
- **(H) EVIDENCE — PASS.** `pytest tests/models/test_reasoning_contract.py -q` → **73 passed**; no
  duplicate `test_*` names.

**OBSERVATION (documented, not a defect):** `ConfidenceInputs`' three penalty factors **default to the
no-penalty state** — the docstring calls this "the wrong direction for a default" and explains the
deliberate trade (making them required would force ~70 call sites to assert `False`; `extra="forbid"`
prevents the *misspelling* failure mode). The reasoning is sound and disclosed. **However, the
per-file audit should note the residual risk** — see **X-B** below, which measures whether any live
call site *relies* on that default where it should not.

## CROSS-CUTTING X-B — the `ConfidenceInputs` bare-default: EXACTLY ONE live site is wrong

The `ConfidenceInputs` penalty flags default to `False` (no penalty), so a call site that *should*
penalise but omits the flag publishes an **over-stated** confidence — a silent Class G defect.
Measured across every producer:
```
$ grep -rn "compute_confidence(" src/ --include=*.py | grep -v "def " | wc -l
161                                   # call sites
$ grep -rn "compute_confidence(ConfidenceInputs())" src/ --include=*.py
18                                    # the bare-default shape, across 6 files
```
**The audit's rule (re-derived from the codebase's OWN consistent practice):** a function penalises
**iff** it reads an `uncalibrated_illustrative` config leaf or makes a model estimate; pure
closed-form arithmetic over observed inputs passes the bare default (the maximum confidence, because
nothing is uncertain about exact arithmetic on measured inputs). The rule is confirmed by matched
pairs inside the same files:

| File | Bare-default sites (pure arithmetic ⇒ correct) | Sites that track calibration (correctly penalise) |
|---|---|---|
| `bond_math.py` | `price_bond`, `macaulay_duration`, `modified_duration`, `convexity`, `price_change_with_convexity` | `repo_stress_check` → `is_heuristic_not_calibrated=not settings.is_calibrated(...)` (:454) |
| `national_accounts.py` | `savings_investment_identity`, `laspeyres/paasche/fisher_index`, `gdp_deflator`, `openings_to_unemployed_ratio` | `quantity_theory_implied_inflation` (=True, :207); `policy_mix_classifier`/`minsky_composition_drift` via `_calibrated()` (:576/:771) |
| `yield_curve.py` | 4 sites (curve arithmetic; re-checked in its own card) | — |
| `risk.py` | `portfolio_volatility_two_asset` (:530) | six sites pass `source_independence_count=0` |
| `inflation_convergence.py` | `:310` — documented "readings, not models; never surfaced" | — |
| **`inflation_nowcast.py`** | **`:251` — ✗ WRONG** | the **insufficient-data** branch penalises correctly (:169) |

**RESULT: 17 of 18 bare-default sites are correct; `project_shelter_cpi` (`inflation_nowcast.py:251`)
is the sole outlier** and is recorded as a **DEFECT (Card 7)** — it reads the
`uncalibrated_illustrative` `shelter_lag_months` leaf and, unlike `repo_stress_check` and the
`_calibrated()` callers, does **not** pass the flag. Measured overstatement: **0.7 vs 0.5**.

**Why this cross-cutting check was worth running:** each site is individually defensible-looking
(the default is legal, the docstring sanctions it, and the tests pin whatever the code does), so
nothing in the gates can see the inconsistency. It surfaces only by re-deriving the §22.8 standard
per site and comparing against the file's own sibling convention.

---

## CARD 7 — `src/macro_engine/models/inflation_nowcast.py` (275 lines)

**Purpose:** `project_shelter_cpi` — projects CPI shelter from the market-rent vintage `lag_months`
ago (Module 5.1). Two branches: insufficient-history (`value=None`) and the projection.

**STATUS: ☠ DEFECT (Class G — the projection branch under-penalises confidence)**

**EVIDENCE — the defect:**
- The **success branch** (line 251) publishes `confidence=compute_confidence(ConfidenceInputs())`
  — i.e. the **maximum** (`base = 0.7`, no penalties) — while the function **reads an
  `uncalibrated_illustrative` coefficient** to produce its value:
  ```
  $ grep -n shelter_lag_months -B1 -A3 config/settings.yaml
  inflation:
    shelter_lag_months:
      value: 15
      calibration_status: uncalibrated_illustrative          # <-- NOT calibrated
      note: Midpoint of the 12-18 month lease-turnover lag documented in Module 5.1.
  ```
  §22.8's field definition (`contracts.py:88`) is explicit: `is_heuristic_not_calibrated` is
  `True` for *"the illustrative Section 15.19/20 thresholds and **any coefficient that has not been
  calibrated against realized data**."* The lag is a documented **midpoint of a range**, i.e. a
  judgement, not a measurement — and the projection's own warnings say so:
  *"Mechanical lag projection — assumes historical lease-turnover dynamics hold… The lag is a config
  parameter, not a measured quantity."*
- **Measured overstatement** (the shipped value vs the §22.8-correct value):
  ```
  $ project_shelter_cpi(<valid series>)                     .confidence = 0.7   # shipped
  $ compute_confidence(ConfidenceInputs())                  = 0.7               # = max
  $ compute_confidence(ConfidenceInputs(is_heuristic_not_calibrated=True)) = 0.5
  => the shipped confidence OVERSTATES the penalised value by 0.2
  ```
- **The sibling convention contradicts it.** `inflation_trajectory.py:308/418` sets
  `is_heuristic_not_calibrated=True` with the reason *"beta is measured but not calibrated"* — the
  same class of coefficient. `project_shelter_cpi` is the outlier.
- **Why it survived every gate:** the test `test_normal_path_confidence_is_computed`
  (`tests/models/test_inflation_nowcast.py:354`) asserts
  `result.confidence == pytest.approx(compute_confidence(ConfidenceInputs()))` — it **pins the
  implementation's own flags**, so the test agrees with the code and neither checks the §22.8
  standard. This is the Class-H "test asserts the wrong number / a green gate is not the standard"
  shape, and it is why only an arithmetic re-derivation against §22.8 (above) exposes it.

- **(A) MATH — PASS.** The `[-(lag+1)]` vintage index (D-028's fix) is correct: with the series
  `["-"*(lag)… 3.2]` the projection reads 3.2, and the `None` branch fires exactly when
  `len(history) < lag+1`. Hand-verified.
- **(E) INPUT-NOT-TAKEN — PASS.** Both inputs read; `market_rent_growth_yoy_pct` at the vintage and
  `current_cpi_shelter_yoy_pct` for the gap.
- **(D) DATA — PASS (N/A).** Pure; no fetch.
- **(H) EVIDENCE — FAIL (see the defect).** The normal-path test does not test the §22.8 standard.
  The insufficient-data path **is** correctly penalised (`data_quality_flags_present=True`, floor) and
  has a proper test (`test_insufficient_history_confidence_is_computed_not_zero`).

**PRESCRIPTION (not applied — audit-only):**
1. In the success branch, pass `is_heuristic_not_calibrated=True` (the coefficient is
   `uncalibrated_illustrative`), matching `inflation_trajectory`.
2. Add a calibration-status accessor (e.g. `shelter_lag_is_calibrated` reading
   `shelter_lag_months.is_trustworthy`) so the flag tracks the leaf, as the post-D-118 siblings do —
   and pass it rather than a literal `True`.
3. Re-point `test_normal_path_confidence_is_computed` to assert the **penalised** value, and add a
   mutation so the flag cannot silently revert.

**⚠️ Class-B note:** the same file's **`inflation_convergence.py`-style** concern does **not** apply
here; but the audit should check whether the *other* bare-default sites (Card 6 / X-B) are the same
shape. See **X-B**.

### ✅ STATUS UPDATE — **FIXED** (D-128, 2026-09-28)

**Defect #7 is FIXED to production grade; the prescription was applied verbatim and its third step
turned out to matter.**

1. `project_shelter_cpi`'s success branch now passes `is_heuristic_not_calibrated=not
   lag_is_calibrated` instead of the bare `ConfidenceInputs()` default.
2. The config leaf gained the accessor: `InflationSettings.shelter_lag_is_calibrated` (a `@property`
   returning `self.shelter_lag_months.is_trustworthy`), so the flag **tracks the leaf** rather than
   asserting `True` — exactly the post-D-118 sibling pattern. A future calibration of the leaf flips
   the confidence without an edit here.
3. The test was re-pointed, and the audit's prediction was confirmed: `test_normal_path_confidence_is_computed`
   FAILED (`assert 0.5 == 0.7`) because it pinned the implementation's own (wrong) flags — the test had
   been enshrining the defect. It now asserts the penalised value, and
   `test_the_lag_penalty_is_load_bearing` was added.

**MEASURED:** the route's published confidence moved **0.70 → 0.50** — a **0.20 overstatement removed**
(the `is_heuristic_not_calibrated=True` penalty). `pytest tests/models/test_inflation_nowcast.py` →
**27 pass**; `scripts/mutation_inflation_nowcast.py` → **23/23 killed** (M7's anchor retargeted to the
new confidence form; **M20/M21/M22 added** to re-create the defect three ways: the flag hardcoded back
to `False`, defeated by `and False`, and inverted to `lag_is_calibrated`).

**Interaction checked, not assumed:** the sibling test `short.confidence < ok.confidence` still holds —
measured, the `data_quality_flags_present` penalty (0.45) is *not* equal to the heuristic penalty
(0.50), so the two paths do not collide at 0.5.

---

## CARD 8 — `src/macro_engine/models/bond_math.py` (489 lines)

**Purpose:** Module 2 — bond pricing, Macaulay/modified duration, convexity, and the §20.2 +
§22.11 repo-corridor plumbing-stress check. Declares itself the "first Tier 1 group" and the module
that establishes the conventions (confidence computed not asserted; thresholds in config not literals)
the rest of the models layer follows.

**STATUS: CLEAN** (two documented OBSERVATIONS; the file is the convention-setter and it holds)

**EVIDENCE:**
- **(A) MATH — PASS (hand-verified against independent arithmetic, not the implementation's own tests).**
  ```
  $ price_bond(face=1000, coupon=0.06, yield=0.06, periods=10)   value = 1000.0    # par bond → par  PASS
  $ price_bond(face=1000, coupon=0.0,  yield=0.05, periods=5)   value = 783.53    # 1000/1.05^5 = 783.526  PASS
  $ macaulay_duration(face=1000, coupon=0.06, yield=0.06, periods=2)
      value = 1.943   # hand: (1·60/1.06 + 2·1060/1.06²)/1000 = 1.9434  PASS
  $ modified_duration(1.943, 0.06)  value = 1.833   # 1.943/1.06 = 1.8330  PASS
  ```
  The `yield_rate == 0.0` branch in `_price_exact` (`coupon*periods + face`) is the correct algebraic
  limit of the annuity factor (verified: the general formula's `(1-(1+y)^-n)/y` → `n` as `y→0`).
  `macaulay_duration` deliberately prices at **full precision** (`_price_exact`), not through
  `price_bond()`'s rounded value — the module documents this as a *fixed* historical defect (2.828 vs
  the correct 2.829). Measured: the correct value is produced. The final period's cash flow includes
  the redemption (`coupon + face`), the documented "invisible error" — confirmed present at line 238.
- **(G) CONFIDENCE — PASS.** Five closed-form sites (`price_bond`, `macaulay_duration`,
  `modified_duration`, `convexity`, `price_change_with_convexity`) use bare
  `compute_confidence(ConfidenceInputs())` = **0.7** — correct: pure arithmetic over observed inputs,
  no uncalibrated leaf read, no estimate. **This is the OPPOSITE shape to Card 7**: the bare default
  is right here precisely because nothing uncalibrated is consumed. `repo_stress_check` **penalises
  correctly**:
  ```
  $ repo_stress_check(<NORMAL inputs>)  .confidence = 0.5
  $ compute_confidence(ConfidenceInputs(is_heuristic_not_calibrated=True)) = 0.5   # MATCH
  ```
  The penalty is **derived, not asserted** — `is_heuristic_not_calibrated=not settings.is_calibrated(
  "bond_math.repo_stress.acute_threshold_bp")`, and measured:
  `is_calibrated(...) = False` because `acute_threshold_bp` is `uncalibrated_illustrative`
  (`config/settings.yaml:1929-1931`). So the flag tracks the leaf, exactly the post-D-118 convention
  Card 7's prescription asks for. `source_independence_count=0` is correct — a single-snapshot
  corridor reading has no independent corroboration, so no bonus is credited
  (`contracts.py:152` adds `count × bonus`, capped).
- **(C) INPUT WIRING — PASS.** All four corridor rates are read (`sofr`, `iorb` at :381;
  `on_rrp_rate` at :382; `fed_funds_effective` — see OBSERVATION 1). Thresholds are read from config
  at :376-379, **not** the §20.2 literals (10 / 25), which is the module's stated convention and is
  measured true: `scalar(...acute...) = 25.0`, `...persistence... = 3.0`, `...volume... = 10.0`.
- **(B) ECONOMICS/REASONING — PASS.** §22.11's softening is implemented faithfully and is
  load-bearing: a raw `ACUTE` breach **without** persistence+volume is reported as `ELEVATED` with an
  itemised warning (measured: `raw = ACUTE_REPO_STRESS`, `severity = ELEVATED`); a single-snapshot
  breach cannot escalate, which is the amendment's whole point. `corridor_intact = iorb > on_rrp_rate`
  is checked and, when violated, surfaced as a warning (measured: `corridor_intact=False`, 2 warnings)
  rather than silently computed against a configuration the model does not describe. A NORMAL reading
  explicitly warns it is "a single-snapshot observation", not an all-clear — a stronger claim than one
  reading supports, correctly refused.
- **(E) INPUT-NOT-TAKEN — PASS (with OBSERVATION 1).** `repo_volume_change_pct` is taken via
  `abs(...) >= threshold` (:412) — sign-agnostic, correct for a *magnitude-of-corroboration* gate. All
  other declared inputs are consumed.
- **(D) DATA — PASS (N/A).** Pure arithmetic; the only external read is `get_settings()`'s config,
  which is present.
- **(F) INTEGRATION — PASS.** `grep -rn "repo_stress_check\|price_bond\|macaulay_duration"
  src/macro_engine/{data_layer,thesis_layer,api_layer}` — consumed through the models registry / thesis
  builder path; not an orphan.
- **(H) EVIDENCE — PASS.** `pytest tests/models/test_bond_math.py -q` → **21 passed**; no duplicate
  `test_*` names (`uniq -d` empty). The suite pins the par-bond identity, the zero-coupon closed form,
  the full-precision duration, and the §22.11 corroboration matrix.

**OBSERVATION 1 (disclosed, not a fault — Class E):** `fed_funds_effective` is listed in
`inputs_used` (:486) but is **never read in the body** — the corridor arithmetic uses only `sofr`,
`iorb`, `on_rrp_rate`. It is declared REQUIRED in `RepoStressInputs` (:138, no default) and surfaced
as "used" while contributing nothing to the computation. This is a **provenance-accuracy** wrinkle,
not a math defect (the corridor is SOFR-vs-IORB by §20.2's own definition; EFFR is a corroborating
rate the model does not yet exploit). It is disclosed here rather than raised as a DEFECT because
(a) requiring it does not widen a decision — the docstring's own stated reason for requiring all four
rates is "a corridor check with a missing leg cannot conclude NORMAL", and EFFR is a *leg of the
floor system* even if unused in the spread; (b) removing it would change the public input contract.
**Prescription (not applied):** either consume EFFR (e.g. a `sofr − effr` cross-check, which is a
genuine floor-system diagnostic) or move it out of `inputs_used`. Flagged for the operator.

**OBSERVATION 2 (era note):** the five closed-form sites have **no cap product** (`× cap`) — consistent
with the rest of the pre-D-118 corpus and with Card 6 / X-B. `repo_stress_check` **does** carry a
config-derived penalty, which is the D-118-era pattern; both shapes are legitimate.

---


## CARD 9 — `src/macro_engine/models/national_accounts.py` (835 lines)

**Purpose:** Module 3 — the savings-investment identity, the quantity-theory diagnostic, the
Laspeyres/Paasche/Fisher index trio, GDP deflator, the openings/unemployed tightness ratio, and two
categorical classifiers (Module 3.2 policy mix, Module 3.4 Minsky composition drift). Says of itself
that the identities are "not trivia" and that the quantity-theory warning "is the substance rather
than a disclaimer".

**STATUS: CLEAN** (one OBSERVATION; the file contains two *fixed* sign-trap defects that are
documented and correctly handled)

**EVIDENCE:**
- **(A) MATH — PASS (hand-verified against independent arithmetic).**
  ```
  $ savings_investment_identity(S=20, I=22, T=18, G=25)
      → private=-2, fiscal=-7, implied_ca=-9     # hand: (20-22)+(18-25) = -2-7 = -9   PASS
  $ quantity_theory(10, -8, 2)                  →  0.0     # 10 + (-8) - 2 = 0         PASS
  $ laspeyres_index(base P{1,2} Q{10,5}, cur P{1.2,2.2} Q{8,6})  → 115.0
      # hand: (1.2·10 + 2.2·5)/(1·10 + 2·5)·100 = 23/20·100 = 115                       PASS
  $ paasche_index(same basket)                  → 114.0
      # hand: (1.2·8 + 2.2·6)/(1·8 + 2·6)·100 = 22.8/20·100 = 114                       PASS
  $ fisher_index(L=115, P=114)                  → 114.4989   # √(115·114)=114.4989      PASS
  ```
  `gdp_deflator` (nominal/real·100) and `openings_to_unemployed_ratio` (openings/unemployed) are
  single-division closed forms; both guard their denominators (deflator refuses `real_gdp == 0`;
  `unemployed_persons_thousands` is `gt=0` at the schema level). `_validate_basket` refuses
  disagreeing item sets in **both** directions — a missing/extra item is "the difference between
  weighting the same basket and weighting two different ones", and it is caught rather than silently
  producing a number.
- **(B) ECONOMICS/REASONING — PASS, and two of the module's own documented defects are genuinely fixed.**
  - **Minsky sign trap (the important one).** §20.3 tests `risky > total * 1.2`; on a **negative**
    base that fires when risky credit is *shrinking fastest* — `total=-10, risky=-11 → -11 > -12 →
    True`, which is **de-risking**, not drift. The fix applies the margin to the **gap**:
    `(risky - total) > margin·|total|`. **Measured:** the de-risking case yields
    `risky_outgrowing=False`, and the genuine positive case (`total=5, risky=12`) yields
    `risky_outgrowing=True, stage=PONZI_DRIFT_WARNING`. The fix is sign-safe and the two forms agree
    whenever `total > 0`. The margin (0.2) is read from config, not written as the spec's `1.2`.
  - **Policy-mix sign trap.** `fiscal_deficit_pct_gdp` is declared **positive for a deficit**, the
    opposite of FRED `FYFSGDA188S`. **Measured:** a correct input (`6.0 > avg 4.0`, `3.0 < taylor 5.0`)
    → `MAX_STIMULUS`; a raw-FRED input (`-6.0`) → `MIXED_FISCAL_TIGHT_MONETARY_LOOSE` **plus 3
    warnings**, one of which names the inversion explicitly. The trap is caught at the point of use,
    not trusted to the caller's discipline.
  - **The `mixed` predicate is tested on the booleans** (`fiscal_loose != monetary_loose`), *not* by
    substring-searching the quadrant name for "MIXED" — the code comment says a substring test "breaks
    silently the moment one is renamed". Correct.
  - **Two categoricals are published recomputable** (D-009 cross-field identity): both classifiers
    emit the underlying predicates (`fiscal_loose`/`monetary_loose`; `standards_loosening`/
    `risky_outgrowing`) and the threshold/gap, so the label can be re-derived from the output rather
    than trusted.
  - **The `50.9%` warning claim is TRUE and derived.** Measured from config:
    `0.31579 + 0.19298 = 0.5088 ≈ 50.9%` — the prose states the sum of the two MIXED base rates,
    which the code reads from config, so it cannot drift from the number it describes.
- **(G) CONFIDENCE — PASS (and this file is the *exemplar* of the §22.8 rule Card 7 violates).**
  Three shapes, each correct:
  - Closed-form pure-arithmetic sites (`savings_investment_identity`, `laspeyres_index`,
    `paasche_index`, `fisher_index`, `gdp_deflator`, `openings_to_unemployed_ratio`) → bare
    `compute_confidence(ConfidenceInputs())` = **0.7**. Correct: no uncalibrated leaf, no estimate.
  - `quantity_theory_implied_inflation` → `is_heuristic_not_calibrated=True` = **0.5** (measured).
    Correct: it reads no uncalibrated leaf, but it *is* a model estimate over an unstable term
    (velocity), which §22.8's standard penalises. This is the deliberate call the docstring explains.
  - `policy_mix_classifier` → **0.3** (measured), from `is_heuristic_not_calibrated=not
    _policy_mix_calibrated()` (**False** → True) **AND** `depends_on_unobservable=True` (r* and
    potential GDP, §21.4 item 13) — two distinct weaknesses, both real, so both penalties apply.
    `minsky_composition_drift` → **0.25**, from `is_heuristic_not_calibrated` (margin uncalibrated)
    **+** `data_quality_flags_present=True` (the risky-credit series is a disclosed proxy covering
    only 51 quarters) **+** no source bonus. The docstring explicitly rejects §20.3's hardcoded
    per-stage confidences (0.6/0.45/0.5) *because they are "more confident when it says something is
    wrong"* — a documented refusal of a spec literal, matching §22.8's "never hardcode confidence".
  - **Both calibration flags are measured False** (`_policy_mix_calibrated()`,
    `_minsky_calibrated()`), tracking their `uncalibrated_illustrative` leaves
    (`settings.yaml:3455-3457`, `2155-2157`) — the leaf-derived-penalty pattern, not a literal `True`.
- **(C) INPUT WIRING — PASS.** Every declared field is read. The classifiers' thresholds/base rates
  are read from config (`settings.quadrant_base_rates[quadrant]`, `settings.drift_margin_pct`,
  `settings.fiscal_deficit_avg`), never literals.
- **(D) DATA — PASS (with the disclosed block, Class D).** `MinskyCompositionInputs`'s docstring
  states plainly that two of three inputs are §21.1-**BLOCKED** and that the spec's instruction is a
  substitution **ban** ("Do NOT substitute total credit growth as a proxy") — so the model "cannot be
  run against live data on this build", and a proxy was later adopted under D-043 with the narrower
  holder base named. The output carries `"risky_credit_proxy": "hedge_fund_leveraged_loans"` and a
  warning on **every call**. The block is surfaced, not hidden.
- **(E) INPUT-NOT-TAKEN — PASS.** No field is declared and ignored.
- **(F) INTEGRATION — PASS.** `orchestration.py:1842` calls `_national_accounts_leg(...)` and carries
  its warnings into the thesis (`:1845`); not an orphan.
- **(H) EVIDENCE — PASS.** `pytest tests/models/test_national_accounts.py -q` → **57 passed**; no
  duplicate `test_*` names (`uniq -d` empty). The suite is large enough (57) to cover the two
  classifiers' full quadrant/stage matrices.

**OBSERVATION (disclosed, not a fault):** three warning strings carry prose statistics that are **not**
read from config — "50.9% of the measured history", "3.3% of measured weeks", "7 of 146 quarters".
The **decision-relevant** numbers (base rates, margin, deficit average, observation counts) *are* all
read from config and measured consistent (see above); these three are narrative annotations inside a
warning sentence. Not raised as a DEFECT because they describe the config's own measured values
(50.9% verified = the two MIXED base rates summed) rather than acting as thresholds — but a future
edit to a base rate would not update the prose. Flagged for the operator if prose/config consistency
is wanted.

---


## CARD 10 — `src/macro_engine/models/auctions.py` (292 lines)

**Purpose:** Module 8.2 — `auction_demand_signal`, a three-way verdict on one Treasury auction's
demand (WEAK / STRONG / MIXED) plus a separate foreign-demand-fading flag. The docstring says four
things "had to be measured before the function could be written, and three of them change what the
inputs mean" (D-036).

**STATUS: CLEAN** (no observations; the file's disclosures are all consistent with measurement)

**EVIDENCE:**
- **(A) MATH — PASS.** Two comparisons on five supplied floats; no iteration, no accumulation.
  ```
  $ auction_demand_signal(btc=2.0, btc_avg=2.5, indirect=60, indirect_avg=62, stop=-2.0)
      verdict = WEAK_AUCTION_term_premium_pressure | weak_bid_to_cover=True | tailed=True   PASS
  $ auction_demand_signal(btc=3.0, btc_avg=2.5, indirect=60, indirect_avg=62, stop=+1.0)
      verdict = STRONG_AUCTION | foreign_fading=False                                       PASS
  ```
  The three predicates are the specification's: `weak_bid_to_cover = btc < avg·ratio`;
  `tailed = stop_through_bp < tail_boundary`; `foreign_fading = indirect < avg − fade_pp`.
  The verdict truth-table is exactly `weak ∧ tailed → WEAK`, `¬weak ∧ ¬tailed → STRONG`, else `MIXED`.
- **(B) ECONOMICS/REASONING — PASS, and the one trap is handled in three independent places.**
  The **sign convention** — `stop_through_bp = expected − clearing`, so **negative means a tail** — is
  the D-034 failure mode (a sign-inverted term that is wrong on every observation without raising an
  error). It is (i) stated in the field description, (ii) published in `value` and echoed in a
  warning (`"a value below {boundary}bp is a TAIL"`), and (iii) the `tailed` flag itself is published
  so a reader uses the flag rather than the raw sign. That is the correct treatment of a
  sign-convention trap. The `STRONG + fading` edge case is explicitly warned: the verdict ignores the
  indirect share, so "STRONG_AUCTION" must not be read as "demand composition is healthy" — the
  omission's one misleading case is named (measured: that warning fires, 5 warnings total).
- **(G) CONFIDENCE — PASS.** `is_heuristic_not_calibrated=not _thresholds_calibrated()` — **measured
  False**, because both thresholds (`weak_bid_to_cover_ratio_value`, `indirect_fade_threshold_pp_value`)
  are `uncalibrated_illustrative` — so the flag reads True and confidence = **0.5** (measured). The
  penalty is leaf-derived, not a literal. `source_independence_count=0` is correct and the code
  states why: "All four sourced inputs come from one auction record. One source is one family, not
  four corroborating ones." That is the family-counting rule applied correctly (a single auction is
  one evidence family regardless of how many fields are read from it).
- **(C) INPUT WIRING — PASS.** All five inputs read; thresholds from config
  (`weak_bid_to_cover_ratio=0.95`, `tail_boundary_bp=0.0`, `indirect_fade_threshold_pp=3.0`,
  `trailing_window_auctions=6` — all measured). The `trailing_window_auctions` leaf is **published in
  `value`**, and the docstring records why: it "was previously a config leaf no code path read, which
  a mutation sweep caught: changing it altered nothing observable." A mutant-driven fix, documented.
- **(D) DATA — PASS (with the disclosed manual input, Class D).** `stop_through_bp` is declared
  **MANUAL ENTRY** and the reason is measured, not assumed: no TreasuryDirect route publishes a
  when-issued yield (the three within-auction yields agree to ~0.0005 on all 703 auctions, so none can
  stand in for the pre-auction expectation). The output carries `stop_through_is_manual_entry: True`
  and a warning on every call. The block is surfaced, not hidden.
- **(E) INPUT-NOT-TAKEN — PASS.** No field declared and ignored.
- **(F) INTEGRATION — PASS (measured by execution, O-133).** No direct `thesis_layer`/`api_layer`
  caller — but `scripts/live_labor_check.py:2179` wires it to **real** auction data and
  `scripts/mutation_auction_demand.py` is a registered mutation sweep. `tools/sweep_health.py`
  enumerates sweeps by scanning `scripts/` (`SCRIPTS = REPO / "scripts"`), so the sweep is in the
  census. Coverage is by the live check + the sweep, which is the project's evidence standard for a
  model not yet folded into the thesis path.
- **(H) EVIDENCE — PASS.** `pytest tests/models/test_auctions.py -q` → **27 passed**; no duplicate
  `test_*` names (`uniq -d` empty); dedicated live check and mutation sweep exist.

---


## CARD 11 — `src/macro_engine/models/credit_spread.py` (322 lines)

**Purpose:** Module 8.3 — `credit_spread_attribution`, attributing a credit-spread widening to
**fundamental** (default risk rising; sticky) or **technical** (flight-to-quality; snaps back) cause,
with the durability of each. The module exists because the two have **opposite** forward
implications. Documents four settled issues (D-037).

**STATUS: CLEAN** (no observations; the module's central documented defect — an unreachable branch —
is genuinely fixed and re-verified)

**EVIDENCE:**
- **(A) MATH — PASS.** Comparisons and one subtraction; no accumulation.
  ```
  $ credit_spread_attribution(trend=rising, vol=5, hyc=+20)   → FUNDAMENTAL                 PASS
  $ credit_spread_attribution(trend=stable, vol=30, hyc=+20)  → TECHNICAL_RISK_AVERSION     PASS
  $ credit_spread_attribution(trend=rising, vol=30, hyc=+20)  → BOTH                      PASS
  $ credit_spread_attribution(trend=stable, vol=5, hyc=+20)   → UNCLEAR                    PASS
  $ credit_spread_attribution(trend=rising, vol=30, hyc=-5)   → NO_WIDENING (not_applicable) PASS
  ```
  Thresholds read from config, measured: `equity_vol_spike_threshold_pct=20.0`,
  `differentiation_threshold_bp=5.0`, `change_window_days=5`.
- **(B) ECONOMICS/REASONING — PASS, and the module's headline correction is real.** The specification
  ANDs `technical` with `default_rate_trend != "rising"` while `fundamental` requires it **equal** to
  `"rising"` — making the two predicates **mutually exclusive by construction**, so the `BOTH` branch
  could never execute. The implementation **drops the exclusion**, and I re-verified all four
  attributions are now reachable (above). The docstring's argument is sound: the presence of a
  `BOTH` branch *with its own durability* (`elevated_concern`) shows it was intended, and "credit
  deterioration *with* a volatility spike" is a real state. Two further corrections, both verified:
  - **Widening is checked before it is attributed.** The specification's `hy_spread_change_bp` /
    `ig_spread_change_bp` appear "only in `inputs_used`" — so the spec attributes *widening* without
    ever reading a spread change; a tightening week would still return `FUNDAMENTAL`. The fix adds
    `widening_observed = hy_spread_change_bp > 0` and returns `NO_WIDENING`/`not_applicable`
    otherwise (measured), refusing rather than substituting.
  - **The unit-pairing trap (D-035).** The two spread changes are **percent → bp (×100)** while
    `equity_vol_change_pct` is a **level → percent-change (÷ through)**. Opposite conversions; applying
    one to both is a 100× error producing a plausible wrong attribution. Both conversions are asserted
    in the live check and a unit test.
- **(G) CONFIDENCE — PASS.** `is_heuristic_not_calibrated=not _thresholds_calibrated()` — **measured
  False** (both thresholds `uncalibrated_illustrative`) → confidence = **0.5** (measured). Leaf-derived,
  not literal. `source_independence_count=0` with a stated reason ("One market, one provider for the
  three sourced series") — correct family-counting.
- **(C) INPUT WIRING — PASS, with the anti-inert-input discipline applied.** All five inputs are read;
  the two spread changes feed the **published diagnostic** (`hy_minus_ig_change_bp`,
  `widenings_are_parallel`) and the widening gate, and the code **says** the differentiation "does not
  decide the attribution," with a warning reinforcing it. So the "three inert inputs" the docstring
  flags are consumed *and* disclosed, not silently ignored. `parallel_widening_rate` and
  `change_window_days` are published (the docstring notes the former "was previously a config leaf no
  code path read, which a mutation sweep caught").
- **(D) DATA — PASS (with the disclosed manual input, Class D).** `default_rate_trend` is declared
  MANUAL (no clean free real-time series) and is one of the two deciding predicates — disclosed in
  `value` (`default_rate_trend_is_caller_supplied: True`) and in a warning. Notably, the warning is
  **more informative than the spec**: it records that a free route now exists (FRED `DRALACBS`,
  D-043), while stating honestly that the model "cannot know which was used."
- **(E) INPUT-NOT-TAKEN — PASS.** No field declared and ignored (the two "inert" spec inputs are read
  here — see C).
- **(F) INTEGRATION — PASS (measured by execution, O-133).**
  `scripts/live_labor_check.py:2368` wires it to real data (Module 8.3, D-037) and
  `scripts/mutation_credit_spread.py` is a registered sweep (the file is named in `sweep_health.py`'s
  own docstring as a previously-diagnosed sweep).
- **(H) EVIDENCE — PASS.** `pytest tests/models/test_credit_spread.py -q` → **30 passed**; no duplicate
  `test_*` names (`uniq -d` empty); live check + mutation sweep exist. The 30-test suite covers the
  five-attribution matrix.

---


## CARD 12 — `src/macro_engine/models/financial_conditions.py` (353 lines)

**Purpose:** Module 12 — `compute_fci`, the financial conditions index. §22.7 / Finding #7 governs and
is explicit the **earlier version was wrong**: every component must be **z-score standardized**
before weighting, because percent/bp/index-point units are not comparable as raw deviations. Positive
= tighter-than-average; negative = looser. Documents four settled issues (D-038).

**STATUS: CLEAN** (no observations; the Finding #7 correction is implemented and re-verified)

**EVIDENCE:**
- **(A) MATH — PASS (hand-verified).** One component each, mixed means/stds, equity negated:
  ```
  policy_rate     value=5, mean=3, std=2   → z=1.0
  credit_spread_hy value=4, mean=4, std=1  → z=0.0
  term_premium     value=1, mean=1, std=.5 → z=0.0
  equity_index    value=10, mean=5, std=2.5→ z=2.0  (NEGATED)
  usd_index        value=2, mean=1, std=1  → z=1.0
  weights: pol .25, hy .25, term .20, eq .20, usd .10  (sum = 1.0, measured)
  fci = .25·1 + .25·0 + .20·0 − .20·2 + .10·1 = .25 − .40 + .10 = −0.05
  $ compute_fci(...)  →  fci = -0.05                                               PASS
  ```
  The published `z_scores` and `contributions` match the hand computation exactly. `FCIComponent.z_score`
  is literally `(value - mean) / std` — the standardization Finding #7 requires; **no raw-deviation
  path exists anywhere in the file** (§22.13's "must be deleted … not left alongside" is satisfied by
  construction — nothing raw was ever written).
- **(B) ECONOMICS/REASONING — PASS, and the module's own documented defect is a real fix.**
  - **The `equity_index` negation is the load-bearing sign.** A rising equity market is *looser*
    conditions, so its contribution must push the index **down**. It is named in
    `_NEGATED_COMPONENTS` (a frozenset) rather than inlined, so "a mutation can target it" and "the
    orientation is auditable". Measured: the equity contribution is **−0.40**, not +0.40. This is the
    D-034 failure mode (an inverted sign that leaves every number plausible) deliberately made
    mutable-testable.
  - **The config/item-set mismatch is refused, not silently absorbed.** `configured != modelled` raises
    a `ValueError`: a component in config but not here "would be silently dropped from the composite
    while still carrying weight"; one here but not config "would be silently unweighted". Both
    invisible, both refused. Correct.
  - **The weights are config's, not the spec's**, and the divergence is *recorded* rather than silently
    reconciled: config `0.25/0.25/0.20/0.20/0.10` (measured, sums to 1.0) vs §22.7's illustrative
    `0.25/0.30/0.15/0.15/0.15`. `FCISettings` refuses a set that does not sum to 1.0.
  - **The NFCI cross-check is part of the contract.** §21.1 calls it mandatory; the model accepts an
    optional `nfci_value`, publishes `nfci_divergence`, and — measured — warns **separately when it is
    absent** ("Silence must not read as corroboration"). Calling a cross-check mandatory while
    permitting silence would be the defect; it is not present here.
- **(G) CONFIDENCE — PASS.** `is_heuristic_not_calibrated=not _weights_calibrated()` — **measured
  False** (weights `uncalibrated_illustrative`) → confidence = **0.5** (measured). Leaf-derived.
  `source_independence_count=0` with a stated reason: "Five series, one provider. One family, not
  five corroborating ones." Correct family-counting.
- **(C) INPUT WIRING — PASS.** All five components read via the mapping (a mapping, not dynamic
  attribute access, "so the checker sees every component and a name that drifts out of the input model
  fails here"). Weights, window and cross-check bar from config.
- **(D) DATA — PASS (with the disclosed availability limit, Class D).** The 10-year window §22.7
  suggests is not achievable: `BAMLH0A0HYM2` returns **786 observations (~3.1 years)** and that is a
  **provider limit, not a fetch window** (requesting `start_date=1990-01-01` returns the identical 786
  rows). The model uses the **common** history and states plainly that a per-series maximum "would
  make the z-scores incomparable, the very defect Finding #7 corrects". Config's `standardization_window_years
  = 3` (measured) matches.
- **(E) INPUT-NOT-TAKEN — PASS.** No field declared and ignored. `nfci_value`'s absence is handled
  explicitly (above).
- **(F) INTEGRATION — PASS (measured by execution, O-133).** `scripts/live_labor_check.py` wires it to
  real data and `scripts/mutation_financial_conditions.py` is a registered sweep.
- **(H) EVIDENCE — PASS.** `pytest tests/models/test_financial_conditions.py -q` → **29 passed**; no
  duplicate `test_*` names (`uniq -d` empty). Verified guards: `std=inf` **rejected at schema**
  (`ValidationError`, via `allow_inf_nan=False`), a non-finite **derived z** raises at the point of use
  (the guard checks the derived quantity, not the input — because the composite consumes `z`, not
  `value`), and both the NFCI-absent and window-mismatch warnings fire (measured).

---


## CARD 13 — `src/macro_engine/models/probability.py` (418 lines)

**Purpose:** Module 12.3/12.4 — `bayesian_update` (explicit prior + likelihood ratio) and
`expected_value` (probability-weighted payoff, "necessary but NOT sufficient — survivability of the
tail governs sizing"), plus the §25 `scenario_distribution_status` classifier and the single
definition of `ScenarioOutcome`. Corrects three §20.11 literals/hardcodings (D-042).

**STATUS: CLEAN** (one minor OBSERVATION on export consistency; three documented corrections verified)

**EVIDENCE:**
- **(A) MATH — PASS (hand-verified).**
  ```
  $ bayesian_update(prior=0.5, P(B|A)=0.8, P(B|¬A)=0.2)
      posterior = 0.8   # hand: P(B)=.8·.5+.2·.5=.5; .8·.5/.5 = .8        PASS
      likelihood_ratio = 4.0   # .8/.2                                     PASS
  $ expected_value([good: p=.9, +1.0; bad: p=.1, −100.0])  → ev = −9.1
      # hand: .9·1 + .1·(−100) = .9 − 10 = −9.1                          PASS
  $ expected_value([good: p=.9, +10; bad: p=.1, −50])      → ev = +4.0
      # hand: 9 − 5 = 4; tail_dominates: worst −50 < −2·4 = −8 → True    PASS
  ```
  Bayes is the exact conditional formula; `p_evidence` (the denominator) is **published** so the
  posterior is recomputable from the output (D-009 identity).
- **(B) ECONOMICS/REASONING — PASS; all three documented corrections are real and verified.**
  - **Hardcoded confidence removed.** §20.11 wrote literal `0.8`/`0.6`. Both are now
    `compute_confidence()` with `is_heuristic_not_calibrated=True` (the likelihoods / scenario
    probabilities are caller judgements with no calibration) → **0.5 measured** for both. The
    docstring's argument is correct: "a prior of 0.5 with an uninformative likelihood ratio is not the
    same claim as a prior of 0.9 with a decisive one", so a constant cannot represent the reliability.
  - **The likelihood-ratio band is now symmetric.** §20.11's `0.8 < lr < 1.25` treats 0.8 and 1.25 as
    different distances from uninformative when they are the same in log-space. The fix is
    `|lr − 1| < band` with `band = 0.25` (measured). **Boundary verified:** `lr = 1.25` gives
    `abs(0.25) < 0.25 = False` → treated as *informative*, a symmetric, well-defined edge.
  - **The P(B|¬A) = 0 case is handled as `None`, not `inf`** — "reported as None rather than `inf`,
    which would not survive serialisation and reads as a number." Correct.
  - **The uninformative-evidence warning says the shift is noise**, not an update: "Do not report the
    posterior as a finding." A prior of exactly 0 or 1 warns that no evidence can move it.
  - **The §25 sizing contract is honored.** `scenario_distribution_status` returns three values
    (measured: `empty_no_trade` / `calibrated` / `SCENARIO_DISTRIBUTION_UNAVAILABLE`), driven by a
    **caller-supplied calibration fact** rather than by inspecting the numbers — because "four
    probabilities of 0.55/0.225/0.175/0.05 look exactly as authoritative whether they were fitted …
    or copied from a specification's illustrative literal." Empty short-circuits first. This is the
    economic-integrity directive implemented literally: a placeholder distribution is published so a
    human can see the reasoning, and is **explicitly not sizing-grade**.
- **(G) CONFIDENCE — PASS.** Both functions use `is_heuristic_not_calibrated=True` (measured → 0.5) —
  correct: the likelihoods and scenario probabilities are uncalibrated caller judgements. Leaf-free
  here (the flag is a genuine fact, not a literal `True` for an arbitrary reason), matching §22.8.
- **(C) INPUT WIRING — PASS (validation is the correction here).** `BayesInputs` bounds all three
  fields to `[0,1]`; §20.11's sample applies "no bounds at all", so a prior of 1.5 or a likelihood of
  −0.2 would flow through silently. `ScenarioOutcome.probability` is bounded per-value to `[0,1]` —
  the crucial fix, because a **negative** probability passes a sum-to-one check whenever another
  scenario exceeds one (`1.5 + (−0.5) = 1.0`). **Measured:** a negative probability raises
  `ValidationError` at schema construction. Thresholds (`uninformative_lr_band=0.25`,
  `probability_sum_tolerance=0.01`, `tail_loss_multiple=2.0`) are all from config.
- **(D) DATA — PASS (N/A).** Pure arithmetic over supplied inputs.
- **(E) INPUT-NOT-TAKEN — PASS.** No field declared and ignored.
- **(F) INTEGRATION — PASS (measured by execution, O-133).** `scripts/live_labor_check.py` wires both,
  and `scripts/mutation_probability.py` is a registered sweep. The `ScenarioOutcome` class is the
  **single** definition in the tree (D-064 closed O-51) and the thesis layer **re-exports** it — the
  same pattern `EvidenceSourceFamily` uses — so a silent import typo cannot resolve to a second,
  structurally different class.
- **(H) EVIDENCE — PASS.** `pytest tests/models/test_probability.py -q` → **28 passed**; no duplicate
  `test_*` names (`uniq -d` empty). Verified guards: negative probability rejected at schema, sum ≠ 1
  rejected with `ValueError`, empty set rejected with a message explaining why the emptiness (not the
  sum) is the error.

**OBSERVATION (minor, Class C — export consistency):** `scenario_distribution_status` is a **public**
function (no leading underscore) that is **not listed in `__all__`** (:51-58 lists only the classes and
the two model functions). It is reachable by explicit import (verified) and is therefore not broken —
but `__all__` is the module's declared public surface, and a public name omitted from it is a small
inconsistency. Not raised as a DEFECT: `__all__` here correctly lists the *model* functions that the
registry/consumer path uses, and the classifier is called from the thesis layer by explicit import.
Flagged for the operator if `__all__` is intended to be exhaustive.

---


## CARD 14 — `src/macro_engine/models/production_function.py` (434 lines)

**Purpose:** Module 3.5 / 7.2 — `potential_gdp_cobb_douglas` (`Y = A · K^α · L^(1−α)`) and
`growth_accounting_decomposition` (potential growth ≈ labor growth + productivity growth). The module
docstring's thesis: three of the four symbols are unobservable, so the specification's golden test
"is a test of the *arithmetic*, not of the estimate."

**STATUS: CLEAN** (no observations; the golden cases are exactly reproduced and the confidence is the
suite's lowest, as the module claims)

**EVIDENCE:**
- **(A) MATH — PASS (both docstring golden cases reproduced exactly).**
  ```
  $ potential_gdp_cobb_douglas(A=1, K=100, L=100)   → 100.0
      # hand: 100^0.3 · 100^0.7 = 100^1 = 100.0                                PASS
  $ potential_gdp_cobb_douglas(A=20, K=40000, L=160000)  → 2111212.66
      # hand: 20 · 40000^0.3 · 160000^0.7 = 20 · 24.02249 · 4394.24217 = 2111212.66  PASS
  $ growth_accounting_decomposition(0.5, 1.5)  → potential 2.0, share 0.75    PASS
  ```
  The docstring even records that its **first draft** of the second case was miscomputed (3,252,491.2
  instead of 2,111,212.7) "because it was written from recollection rather than computed", and the
  test caught it. That is the project's hand-verify-don't-hand-assert discipline, documented.
  `alpha` is read from config (`0.3` measured) and is **deliberately not a field** on
  `PotentialGDPInputs` — the docstring's reason is exact: "a signature default is a *second source of
  truth* with priority over the configured one whenever a caller omits the argument. A recalibration
  in config would then move nothing for those callers, silently." Correct.
- **(B) ECONOMICS/REASONING — PASS.** The `alpha` interior check (`0 < α < 1`) warns when the model
  degenerates to a single-factor function; the CRS check names that "Constant returns to scale is
  ASSUMED by this functional form, not estimated — the exponents sum to 1 by construction, so this
  function can never report a scale elasticity other than 1." Naming a built-in as an assumption (not
  a finding) is exactly the §21.0 discipline. The growth-accounting warning matrix is complete and
  **verified across all four sign combinations**, including the case the code comment credits a test
  with finding: "BOTH terms negative is a different situation from either offsetting pattern … A guard
  written as a bare `labor_force_growth_pct < 0` would fire here and report that positive growth
  'rests entirely on productivity' — in a case where productivity is negative too."
  `productivity_share` is `None`, **never `0.0`**, when the terms sum to zero (measured: `None`) —
  "a zero total is not a finding that labor explains everything; it is an undefined ratio." A
  shrinking-labor-force offset case is warned explicitly.
- **(G) CONFIDENCE — PASS, and correctly the lowest in the audit so far.** `potential_gdp_cobb_douglas`
  applies **three** penalties — `depends_on_unobservable=True` (A, K, L per §21.4 item 13),
  `is_heuristic_not_calibrated=True` (no calibration of the equation exists) and
  `source_independence_count=0` (A, K, L all descend from the same national-accounts framework) →
  **0.3 measured** (0.7 − 0.2 − 0.2, no bonus). §20.3 wrote a literal `0.3`; the docstring notes the
  computed value "lands at or below that, which is the correct direction". `growth_accounting_decomposition`
  makes the heuristic flag **conditional** on the config's own dominance threshold:
  `is_heuristic_not_calibrated = (share is not None and share > productivity_dominance)` —
  measured `productivity_dominance = 0.6`; a share of 0.75 > 0.6 → penalised. This is the spec's own
  "confidence scales inversely with productivity's share" turned into arithmetic rather than rhetoric.
- **(C) INPUT WIRING — PASS.** All three fields read; `alpha` and the dominance threshold from config.
  Every remaining field is `gt=0` — "a negative base with a fractional exponent raises inside
  `math.pow` with a traceback that names neither the field nor the caller."
- **(D) DATA — PASS (with the disclosed estimate status, Class D).** The module states plainly that
  `GDPPOT` (CBO) is the §21.1 **preferred** source and this function "is not a competitor to it"; it
  exists for cross-check and factor decomposition. Every branch reporting the output says it is
  estimated.
- **(E) INPUT-NOT-TAKEN — PASS.** No field declared and ignored. `alpha`'s **absence** is a deliberate
  design choice (two-sources-of-truth avoidance), not an omission.
- **(F) INTEGRATION — PASS (measured by execution, O-133).** `scripts/live_labor_check.py` wires it,
  and `scripts/mutation_production_function.py` is a registered sweep.
- **(H) EVIDENCE — PASS.** `pytest tests/models/test_production_function.py -q` → **41 passed**; no
  duplicate `test_*` names (`uniq -d` empty).

---


## CARD 15 — `src/macro_engine/models/convergence.py` (556 lines)

**Purpose:** Module 12 — `classify_convergence`, the **general** convergence classifier over an
arbitrary list of produced `ModelResult`s (distinct from `inflation_convergence_classifier`, a fixed
narrow set, and `four_pillar_scorecard`, a fixed four-wide set). §22.10 / Finding #10 + §15.19-D +
D-050 + D-077. **The most defect-dense module in this audit: 7 documented defects across four groups.**

**STATUS: CLEAN** (no observations; all seven repairs independently re-verified — this is the audit's
strongest evidence card)

**EVIDENCE — every documented defect re-measured, not accepted:**
- **(A/B) MATH & REASONING — PASS. Verdicts, permutation-invariance and the padding-guard all verified.**
  - **All five verdicts reachable** (§D-045a "a `Literal` is a promise with two halves"):
    ```
    NO_SIGNAL  ← [0, 0]                                        (Defect 4's branch)
    CONFLICTED ← [+1 across BLS_CPI, −1 across BEA_PCE]
    HIGH       ← 3 agree, 3 families
    MEDIUM     ← 2 agree, 2 families (unanimous, family floor)
    LOW        ← 2 agree, 1 family
    ```
  - **Defect 1 (supplier returns `ModelResult`, spec compares to `int`)** — the spec's
    `independent_family_count >= 3` raised `TypeError` on every call reaching the family gate. Here the
    census is **called and read**: `census.value["distinct_families"]`, with explicit `TypeError`
    contract guards if the shape is wrong. Fixed.
  - **Defect 2 (order-dependence) — DECISIVELY FIXED.** The spec used `directions[0]` as reference,
    making the verdict order-dependent (132/1800 multisets differ under permutation). I re-enumerated
    all multisets of `{−1,0,+1}^n` for `n ≤ 5` across 5 families under **every permutation**:
    ```
    order-dependent multisets: 0 / 1023        # spec measured 132 / 1800
    ```
    `_direction(value)` reads position-independently from each signal's `value`; a non-numeric value
    is neutral (a dict-valued `ModelResult` is valid upstream — `four_pillar_scorecard` returns a dict
    — and treating it as directional would be worse than ignoring it); `bool` is explicitly neutral
    ("`bool` is an `int` subclass; a flag is not a level").
  - **Defect 7 (introduced by the repair, found by its own test) — VERIFIED FIXED.** Padding a read
    with neutral signals from new families must not promote it. I reproduced the exploit precisely:
    ```
    base   = 2 directional, 2 families            → MEDIUM, confidence 0.60
    padded = base + 3 NEUTRAL, 3 new families      → MEDIUM, confidence 0.60   NOT promoted
    families_excluded_as_neutral = ['bls_jolts','bls_ppi','market_fx']         published, not silent
    ```
    The spec's exploit ("the same two + 3 NEUTRAL → HIGH, 0.75") is closed. The census now runs over
    `directional` signals only (`zip(signals, directions, strict=True) if d != 0`), and the excluded
    families are named in the output and in a warning. The docstring credits the test
    `test_neutral_signals_cannot_promote_a_read_by_padding`, written to assert the *opposite*, which
    failed — the correct way to discover a defect.
  - **Defect 3 (denominator)** — `agree_frac = max(up, down) / n` where `n = len(non_neutral)`, not the
    whole list. A neutral signal is not evidence for either direction, so including it dilutes
    agreement. Verified via the exhausted enumeration above.
  - **Defect 4 (`NO_SIGNAL` unreachable)** — now a real first branch, with its own verdict, reason and
    warning ("This is NOT LOW: no directional read exists"); verified reachable.
  - **Defect 5 (`LOW` conflates three situations)** — the family floor is tested as its **own**
    `elif distinct < medium_family_floor` branch, so "unanimous but single-source" gets its own reason
    and warning. Verified: `[+1,+1]` one family → LOW with the "they span only 1 source family" warning,
    which the spec could never emit.
  - **Defect 6 (§D-050's inert thresholds)** — the gate order is `NO_SIGNAL → CONFLICTED → agreement
    gates`, and the repaired form expresses the gates as what they can actually be ("is there
    agreement at all, and is it backed by independent sources") while **publishing the fraction** so
    the thresholds stay auditable. Floors read from config and measured: `high=0 dissent/3 families`,
    `medium=1 dissent/2 families`.
- **(G) CONFIDENCE — PASS.** `compute_confidence(ConfidenceInputs(data_quality_flags_present=<any
  signal's>, is_heuristic_not_calibrated=True, depends_on_unobservable=False,
  source_independence_count=distinct))`. The confidence moves with the **measured** family count
  (HIGH/3 families → 0.65 measured; MEDIUM/2 → 0.60) — which the docstring defends correctly: "the
  verdict is a fact about the world, the confidence is a fact about how well the signals were
  measured. It does move with the measured family count, because that *is* a measurement-quality
  fact." `is_heuristic_not_calibrated=True` reflects the illustrative thresholds. The confidence is
  correctly **flat across verdicts** (it does not rise because the news is good). `data_quality_flags_present`
  propagates from the constituent signals — correct.
- **(C) INPUT WIRING — PASS.** `min_length=1` on signals; `inputs_used` = the signals' `model_name`s.
  The D-077 disclosure (`untagged_count`) counts over the **whole** list, not the census's structurally-0
  `untagged` — because a neutral signal is the only kind that can lack a family. Documented and correct.
- **(D) DATA — PASS (N/A).** Classifies supplied results; fetches nothing.
- **(E) INPUT-NOT-TAKEN — PASS.** Every signal contributes via `_direction`; neutrals are excluded from
  the verdict *and* reported (`non_neutral_signals` beside `total_signals`).
- **(F) INTEGRATION — PASS (measured by execution, O-133).** The docstring names the call site
  (`build_us_macro_thesis` Q7 with `[growth, inflation, labor, gap]`); dedicated
  `scripts/live_convergence_check.py` and `scripts/mutation_convergence.py` exist. The vocabulary is
  asserted equal to `thesis_layer.schemas.ConvergenceClassification` by a test (a forked vocabulary is
  the D-046 defect).
- **(H) EVIDENCE — PASS.** `pytest tests/models/test_convergence.py -q` → **56 passed**; no duplicate
  `test_*` names (`uniq -d` empty). The suite covers the permutation group, every verdict, and the
  padding exploit.

---


## CARD 16 — `src/macro_engine/models/inflation_trajectory.py` (449 lines)

**Purpose:** Module 3.6 — `project_inflation_trajectory` (D-053), the Phillips-relation direction
classifier: given a labor-tightness score, which way is inflation pressure pointing. The module
docstring's claim is strong — the specification's version is "seven lines, and **every one of the seven
produces a defect**."

**STATUS: CLEAN** (no observations; all seven documented spec defects are corrected and re-verified,
including the subtle double-negation sign trap)

**EVIDENCE:**
- **(A) MATH — PASS, including the sign trap.** §16.2 writes the negation **twice**
  (`slack = −labor.value/100`, then `pc = −beta·slack`) and they cancel:
  `pc = −beta·(−s/100) = +beta·s/100`. So a **tight** market (positive score) must produce a **positive**
  projected change. Measured across the whole declared range [−100, +100]:
  ```
  score +100 → change +0.6000 → reaccelerating
  score  +50 → change +0.3000 → reaccelerating
  score    0 → change  0.0000 → stable          (boundary falls to stable)
  score  −50 → change −0.3000 → decelerating
  score −100 → change −0.6000 → decelerating
  ```
  The sign is monotone increasing in the score — correct Phillips direction. The docstring's warning
  that "writing `beta * (−s)` here would invert it — and would look right, because the comment beside
  the specification's first negation says 'negative score (loose) → positive slack', which is true of
  the *slack* variable and false of the *final* expression" is a precise description of a real trap, and
  a dedicated test (`test_sign_is_monotone_in_the_score`) pins it.
- **(B) ECONOMICS/REASONING — PASS, with the D-047 base-state failure actively prevented.**
  - **The D-047 failure is guarded by test, not hope.** The spec paired `beta=0.3` against a bare `0.05`
    on the wrong (score-fraction) scale, leaving `stable` as **79.1%** of real months (n=296) — "the
    confident label is the base state, arrived at by accident." This implementation uses
    `beta=0.006 pp/point` (measured) against bands `[−0.05, +0.05] pp` (measured), and I verified **all
    three labels are reachable** across the declared range. The test suite contains
    `test_the_configured_band_is_not_a_base_state_on_the_declared_range`,
    `test_every_direction_is_reachable_over_the_declared_range` and
    `test_both_directional_labels_are_reachable_within_a_realistic_score` — so a future config edit
    that re-creates the failure fails a test rather than silently producing an uninformative label.
  - **Defect 3/4 (declared-but-unread inputs) — fixed.** The spec declared `growth` and listed
    `"inflation.value"` in `inputs_used` while reading neither. Here `growth.value` is genuinely consumed
    as **demand-side corroboration** (`_growth_corroboration`), with five reachable states
    (`agrees_expansion`/`agrees_contraction`/`disagrees_tight_labor_weak_growth`/
    `disagrees_loose_labor_strong_growth`/`not_directional`), and `inflation.value` is consumed as the
    **starting level** and reported. An `inputs_used` list that "overstates its inputs is worse than a
    short one: it is a claim about provenance that is false" — corrected.
  - **Defect 5 (§18.6 fiscal flag absent) — fixed.** `fiscal_response_active` is consumed as a
    **multiplier on the projected change** ("not as a second set of bands, so the direction of the
    adjustment is a single auditable number"), and a test (`test_fiscal_flag_never_changes_the_sign`)
    pins that it changes magnitude but never sign.
  - **Defect 6 (no unit) — fixed.** The output key is `projected_change_pp`, the docstring names the
    estimand ("change in ANNUAL CORE INFLATION, in percentage points"), and `beta` is named
    `beta_pp_per_score_point` "with its unit in the key name". The unit is in the identifier, which is
    the strongest form.
  - The band partition is **strict on both sides** so it is exhaustive and non-overlapping
    (`test_band_partition_is_exhaustive_and_non_overlapping`), and the three honest limits (3–9 month
    horizon that REVERSES after 12; R²=0.047; the score is not centred on zero at +1.52 mean/+4.95
    median) are carried in the output warnings on every call.
- **(G) CONFIDENCE — PASS.** §16.2's hardcoded `0.35` (defect 2) is replaced by `compute_confidence()`
  with three stated facts: `data_quality_flags_present=bool(labor.warnings)`,
  `is_heuristic_not_calibrated=True` (beta measured but not fitted), `depends_on_unobservable=True`
  (the Phillips relation is *in u-star*, §21.4 item 13), and
  `source_independence_count = 0 if disagrees/unavailable else 1` — the growth reading is credited as an
  independent second family **only** when it corroborates. That is the family-counting rule applied
  correctly (a disagreement is not corroboration).
- **(C) INPUT WIRING — PASS.** All four declared inputs read; `_validate_score` **rejects a bool
  explicitly** ("`isinstance(True, int)` is true in Python, so a caller passing `True` for a score
  would otherwise be silently accepted as `1.0`") and range-checks against the declared scale — a
  Type-1 defect guard rather than a comparison.
- **(D) DATA — PASS (N/A).** Pure; inputs are upstream `ModelResult`s.
- **(E) INPUT-NOT-TAKEN — PASS.** No declared input ignored (this is precisely what the docs fix).
- **(F) INTEGRATION — PASS (measured by execution, O-133).** The docstring names the cross-check
  (`cross_asset_transmission`, Module 5.6/D-052) and the live check
  `scripts/live_projection_check.py`; `scripts/mutation_inflation_trajectory.py` is a registered sweep.
- **(H) EVIDENCE — PASS.** `pytest tests/models/test_inflation_trajectory.py -q` → **47 passed**; no
  duplicate `test_*` names. The suite names its own reachability/sign/partition guarantees explicitly.

---


## CARD 17 — `src/macro_engine/models/scorecard.py` (473 lines)

**Purpose:** Module 12.2 — `four_pillar_scorecard`: four directional pillar reads (growth, inflation,
financial conditions, policy gap) in, one convergence verdict out. The capstone of Module 12. Corrects
four §20.11 defects (the first two in the spec's own arithmetic).

**STATUS: CLEAN** (no observations; Defect 1 — a 64%-miss CONFLICTED gate — is decisively re-verified)

**EVIDENCE:**
- **(A/B) MATH & REASONING — PASS; Defect 1 verified by full enumeration.**
  - **Defect 1 (the CONFLICTED gate misses most conflicts) — DECISIVELY FIXED.** The spec computes
    `has_up and has_down` (genuine opposition) but then also requires the **narrower**
    `growth_signal * inflation_signal < 0` before returning `CONFLICTED`. I enumerated all `3⁴ = 81`
    pillar combinations:
    ```
    opposed configurations (≥1 each way):        50
    spec's narrower gate catches:                18      # misses 32
    this implementation's CONFLICTED:            50      # catches all
    ```
    The 32 misses include every configuration where growth and inflation agree while financial
    conditions and policy oppose — the "bad news is good news" split. Verified: `[1,1,−1,−1]` (a spec
    miss) → `CONFLICTED` here. Since the spec's own warning calls CONFLICTED a mandatory block, each
    miss "is a false green light". The repair is "the smallest possible one: **the gate is the guard**."
  - **Defect 2 (`0.9` vs `0.75` are not two thresholds) — fixed.** With `agree_frac` dividing by the
    non-neutral count, `n ≤ 4`, the reachable ratios are forced and **no ratio lands in `[0.9, 1.0)`**
    — so `>= 0.9` and `>= 1.0` are the same test. The repair expresses the gates as **dissent counts**
    (HIGH = unanimity, MEDIUM ≤ 1 dissenter), which has no granularity cliff, while still publishing the
    fraction, the dissent count and an agreement margin. Floors measured: `high=0 dissent/3 families`,
    `medium=1 dissent/2 families`.
  - **Defect 3 (§15.19-D not discharged) — fixed by changing what the function asks for.**
    The spec took `independent_source_families: int` — a raw caller-supplied count it cannot verify, so
    "a caller passing `4` (the raw signal count) on a unanimous input gets `HIGH` with no complaint".
    This version accepts the **tagged reads** and calls `count_independent_families` itself. **Verified
    the neutral-padding exploit is closed:** one directional pillar + three neutral pillars spanning
    four families now returns **LOW with `independent_families = 1`** (it previously returned HIGH —
    "the three neutral pillars contributed three families to a verdict none of them pointed at"). The
    docstring records the defect was found by `live_convergence_check.py`'s cross-check against
    `classify_convergence` (D-051) — **"one classifier's repair is a defect report against every
    classifier that shares the pattern."** Excellent cross-check discipline.
  - **Defect 4 (four hardcoded confidences `0.2/0.75/0.5/0.3`) — fixed.** Now `compute_confidence()`,
    **flat across verdicts** ("the verdict is a fact about the world and the confidence is a fact about
    how well it was measured"). Measured: HIGH → 0.7 (no penalties, 4 families credited).
  - **The base-state disclosure is measured, not asserted.** `conflicted_base_share = 0.617` (measured;
    the docstring says "62%") and travels on every CONFLICTED output: "the verdict alone does not
    identify this read as unusual." The module also correctly distinguishes the **input-space** share
    (62%) from the **historical** share (lower, because real pillars are correlated) — "a blocking
    verdict that occupies 62% of the abstract space need not occupy 62% of real time."
- **(G) CONFIDENCE — PASS.** `is_heuristic_not_calibrated=True` (illustrative thresholds),
  `source_independence_count=independent_families` (the **measured** count), `depends_on_unobservable=False`.
  Flat across verdicts, as documented.
- **(C) INPUT WIRING — PASS, with a real guard.** `PillarRead.direction` is `Literal[-1, 0, 1]`
  ("a magnitude here is a category error, not a data point"); `family: EvidenceSourceFamily` and
  `source` travel with the direction so the count is measurable. The all-neutral guard
  (`model_validator`) **refuses all-neutral by default but allows it on purpose** via
  `allow_all_neutral=True` — because "over 761 months of FRED history, 6 readings (0.8%) have all four
  pillars neutral", so refusing outright would "make a state that REAL DATA PRODUCES unrepresentable."
  That is a subtly correct distinction (guard the accident, permit the intent) and I confirmed it fires.
- **(D) DATA — PASS (N/A).** Classifies supplied pillar reads.
- **(E) INPUT-NOT-TAKEN — PASS.** All four pillars read; the neutral count is reported (`non_neutral_pillars`).
- **(F) INTEGRATION — PASS (measured by execution, O-133).** Dedicated `scripts/live_scorecard_check.py`
  and `scripts/mutation_scorecard.py` exist; `live_convergence_check.py` cross-checks it against
  `classify_convergence`.
- **(H) EVIDENCE — PASS.** `pytest tests/models/test_scorecard.py -q` → **53 passed**; no duplicate
  `test_*` names (`uniq -d` empty).

---

## CARD 18 — `src/macro_engine/models/lei_proxy.py` (509 lines)

**Purpose:** Module 7.3 — `leading_indicator_proxy`: a breadth-weighted composite of leading components,
offered *in place of* the licensed Conference Board LEI. The module's central claim is a **naming**
claim — the in-house composite must never be called "LEI" (§21.0 rule 4 / §20.7), and every output
string repeats that. Two §20.7 corrections: the model's self-asserted `confidence=0.5/0.3` is replaced
by `compute_confidence()`, and the bare `breadth >= 0.6` literal becomes a config leaf that travels with
its measured base rate (D-029).

**STATUS: CLEAN** (two documented OBSERVATIONS; all four hand cases and the exact binomial reproduce;
the O-156 false-survivor trap fired twice during this card's collection and was resolved both times)

**EVIDENCE:**
- **(A/B) MATH & REASONING — PASS; all four docstring hand cases reproduced exactly.**
  ```
  C1 four falling, equal weights   composite -7.50  breadth 1.00  broad True   "broad_based_decline"
  C2 one dominating fall -20       composite -4.12  breadth 0.25  broad False  "mixed"
  C3 three rising, sum negative    composite -6.62  breadth 0.25              "mixed"
  C4 all four rising               composite +2.50                            "broad_based_advance"
  ```
  - **C2's arithmetic is the point of the file and it holds.** `0.25·(-20.0+1.0+0.5+2.0) = -4.125` → the
    composite is *more negative* than a broad two-component decline of the same breadth, while breadth
    correctly reports 1-of-4. That is the spec's own stated intent ("a decline concentrated in one or two
    components is much weaker evidence") working as designed — and it is why breadth is first-class.
  - **The advance-side guard is real, not decorative.** C3 has advance_breadth `0.75 >= 0.6` but composite
    `-6.62 < 0`; a breadth-only test would have labelled it `"broad_based_advance"` and printed a
    direction the headline number contradicts. The `and composite > 0` conjunct (line 392) is what makes
    the tri-state strictly-more-informative-than-the-boolean claim true rather than aspirational.
  - **C1 is the anti-D-047 disclosure.** With 4 components, `5/16 = 0.3125` of the null space is
    "broad-based": the confident label is **not** a base state, but it is a *third*, and the module says
    so in a warning (`n=1..6` → 0.5000 / 0.2500 / 0.5000 / **0.3125** / 0.5000 / 0.3438).
- **(A) the null rate is exact integer arithmetic, and I re-derived it.** `_breadth_null_rate(4, 0.6)`:
  `ceil(0.6·4)=3`, `favourable = C(4,3)+C(4,4) = 5`, `5 / float(2**4) = 0.3125` — matches `5/16`. The
  Pascal's-triangle construction (line 267–269) avoids `math.comb`'s typeshed `Any` and is correct:
  each row sums to `2**n`, which is exactly the denominator. Boundary branches verified: `required <= 0
  → 1.0` (threshold 0) and `required > n → 0.0` (threshold 1.0) are both reachable and both correct.
- **(G) CONFIDENCE — PASS.** Measured `0.3` = base 0.7 − 0.2 (heuristic) − 0.2 (unobservable), with
  `source_independence_count=0`. Both penalties are **earned**: `is_heuristic_not_calibrated=True` because
  `breadth_threshold` is `uncalibrated_illustrative` in `settings.yaml:3553` (verified) and no weighting
  has been fitted; `depends_on_unobservable=True` because a leading indicator's link to *future* activity
  is unobservable at read time — the §21.4 item-13 class. **Not** a self-asserted literal.
- **(C) INPUT WIRING — PASS, with four genuine refusals I fired.** `_weights_must_cover_components`
  ✓ partial map (silent `w.get(k,0)` zero-weight) ✓ extra name (half-applied rename) ✓ negative weight
  (a second place to encode direction — same sum as swapping signs, different meaning) ✓ all-zero
  (a constant presented as a measurement). Non-finite component guard fires on both `nan` and `inf`
  (line 359–367) — and its justification is precise: `nan < 0` is `False`, so a missing observation would
  be counted as a component that did **not** decline, i.e. it would suppress the model's own signal.
- **(D) DATA — PASS, and the window limitation is checked, not asserted.** The licensed `USLEI` is
  unreachable (empty frame, three attempts each path); all four named components resolve live. The
  SP500 rolling-~10-year window is disclosed in the docstring, the registry
  (`component_series.known_limitations`) **and** asserted in `live_labor_check.py:2046` (`span_days > 200`).
- **(E) INPUT-NOT-TAKEN — PASS.** Every component is read in both the composite and the breadth count;
  `n_components`/`n_declining` are published so no denominator has to be guessed. `equal_weighted`
  (line 485) surfaces whether the spec's default was used, because the two composites differ.
- **(F) INTEGRATION — PASS (measured by execution, O-133).** `live_labor_check.py:1980` `_check_leading_indicator`
  computes each component's 6-month change independently and **asserts the ICSA inversion**
  (`abs(computed - -raw) < 1e-9`, line 2033) — a build that dropped the inversion shows up as a sign flip
  on an independently-checkable series. `scripts/mutation_lei_proxy.py` = **37 mutants**, including the
  orientation, boundary (`>=` vs `>`), flat-component (`<= 0`), and null-rate families.
- **(H) EVIDENCE — PASS.** `pytest tests/models/test_lei_proxy.py -q` → **55 passed**; no duplicate
  `test_*` names (`uniq -d` empty).

**⚠️ (H) — THE O-156 FALSE-SURVIVOR TRAP FIRED TWICE WHILE COLLECTING THIS CARD.** `mutation_lei_proxy.py`
was SIGTERM'd mid-loop on **both** attempts (the harness is slower than the tool's default window). Each
time it left a **live mutant in the working tree plus a `.sweepbackup`**:
```
kill #1  ->  M3b live:  n_declining = ... if change > 0     (breadth inverted)
kill #2  ->  M3a live:  broad_based = breadth > threshold   (inclusive -> strict)
```
Both were **byte-verified against HEAD and against the backup before any write** (D-123/D-124), confirmed
live by `git diff`, and **only then** killed by the suite (M3b → 10 failed; M3a → 1 failed,
`test_the_boundary_is_inclusive_as_the_specification_writes_it`) and **then** restored from the verified
backup. Final state: `sha256` of `lei_proxy.py` == `sha256` of `git show HEAD:src/.../lei_proxy.py` ==
`e2b895638abc6f6356932ca539ffc538e96bb2b61e32f0bd9b7f312121c8cf27`; `git status --short src/` clean.
**Had the sweep's own output been trusted without this, the record would have read "M3a/M3b survive" —
two false defects against a correct module.** The `.sweepbackup` is the only win32 defence (O-131).

**OBSERVATIONS (non-defects):**
1. **A supplied weight vector is not normalised, and `equal_weighted=False` is the only signal.**
   `weights={"a":1.0,"b":1.0}` yields composite `-2.0` for components `-1.0,-1.0` where the equal-weight
   path would yield `-1.0`. This is **not** a defect — `weights` is documented as "a split of influence"
   and a caller supplying `1.0/1.0` on two components is asking for that sum — but the output publishes
   no `weights_used` echo, so a reader cannot tell a normalised split from an unnormalised one. Adding
   the realised weight dict to `value` (or a warning when `sum(weights) != 1`) would close it cheaply.
2. **`LeadDirection`'s three states are all reachable** — verified `"broad_based_decline"` (C1),
   `"mixed"` (C2/C3), `"broad_based_advance"` (C4), so D-045a's two-halves rule is satisfied. The
   `"mixed"` branch additionally warns that the spec has no branch for a split, which is the correct
   framing: the spec's `False` reads as "no decline" when the truth is "no consensus".

---
## CARD 19 — `src/macro_engine/models/inflation_convergence.py` (596 lines)

**Purpose:** Module 5.3 — `inflation_convergence_classifier` (§15.19-C, corrected by D-047, integrated
with §15.19-D by D-046). Grades *how strongly* the inflation sub-measures converge on a
HIGH/MEDIUM/LOW/CONFLICTED scale, while asking the prior question §15.19-D imposes: **is the agreement
real, or manufactured by counting one release several times?** Headline CPI, core CPI, Cleveland-Fed
median CPI and Atlanta-Fed sticky-price CPI are all built from the BLS CPI survey; five agreeing is one
observation reported five times. **This is the first caller of `count_independent_families`** — the
obligation §15.19-D places on every convergence classifier in the system.

**STATUS: ⚠️ DEFECT (Class G — a bare-literal gate on a published disclosure), plus one Class-A
design note.** Both corrections §15.19-C needs are genuinely implemented and the D-046 integration is
real; the defect is a *disclosure* constant, not the classifier's arithmetic.

**EVIDENCE:**

### (A/B) MATH & REASONING — PASS; the two gates both behave as documented
- **The corrected whole-set conflict gate fires where the spec's pair gate misses.** I enumerated all
  `3³ = 27` three-measure sign combinations and compared the spec's gate against `_classify`:
  ```
  differ: 6/27
    (-1,-1, 1): spec=MEDIUM      ours=CONFLICTED
    (-1, 0, 1): spec=LOW         ours=CONFLICTED
    ( 0,-1, 1): spec=LOW         ours=CONFLICTED
    ( 0, 1,-1): spec=LOW         ours=CONFLICTED
    ( 1, 0,-1): spec=LOW         ours=CONFLICTED
    ( 1, 1,-1): spec=MEDIUM      ours=CONFLICTED
  ```
  All six are cases where headline and core agree (or one is flat) while the third measure opposes and
  the losing side carries `1 >= 0.25·3 = 0.75` — exactly the class of month the docstring claims is
  misreported, and the corrected gate catches every one.
- **The all-flat case is safe without a special case, and the comment explains why correctly.**
  `losing = min(agreeing, opposing) = 0` when nothing moves, and `0 >= share*total` is False for every
  `total > 0` because `share` is positive (0.25). Verified: `3 all flat → LOW`, i.e. absence of evidence,
  not conflict.
- **The `agreeing + opposing > 0` term was removed by the sweep, and the removal is honest.** The comment
  (lines 363–368) records that an earlier revision carried that term as a "degenerate guard" whose
  comment *claimed it was load-bearing*, and that `mutation_inflation_convergence.py` D2 proved it inert.
  The comment left in its place says so explicitly. **That is the correct response to a surviving
  mutant** — the code changed, not the test.
- **Reachability of all four classes confirmed** over the full `3⁶ = 729` input space:
  `{'HIGH': 22, 'MEDIUM': 74, 'CONFLICTED': 322, 'LOW': 311}` — so D-045a's two-halves rule holds for
  `CONVERGENCE_CLASSES`, and the module-scope `assert set(get_args(ConvergenceClass)) ==
  set(CONVERGENCE_CLASSES)` (line 596) pins it at import time.
- **`_attainable_fracs` is correct.** `n=3 → [0.0, 1/3, 2/3, 1.0]`, `n=6 → [0.0, 1/6, …, 1.0]`. This is
  what makes correction 3's degeneracy claim true: at `n=3` the fractions are `{0, 0.333, 0.667, 1.0}`,
  so `high=0.8` requires unanimity and `medium=0.6` selects exactly `2/3` — a knife edge, exactly as
  documented.

### ☠ (G) CONFIDENCE / PROVENANCE — **DEFECT: the base-state warning is gated on a bare literal `0.75`**
`inflation_convergence.py:487` reads:
```python
if classification == "HIGH" and current_rate > 0.75:
```
`current_rate` is a **config leaf** (`settings.measured_base_rates.{three,six}_measure_high` → 0.866 /
0.895). The `0.75` it is compared against is **hardcoded in the source**. This project has a named,
established pattern for exactly this quantity — `regime.markov.modal_share_warning_threshold_value`
(`settings.yaml:3223`, `calibration_status: uncalibrated_illustrative`, whose own note says *"this leaf
only decides when the output also says so in words"*). **11 of 11** comparable warning gates in sibling
models read their boundary from config:
```
credit_spread.py:180            equity_vol_spike_threshold_pct
financial_conditions.py:282     nfci_divergence_threshold
fx_carry.py:1187                vix_threshold
gdp_nowcast.py:1335             persistence_improvement_threshold
inflation_dynamics.py:455-456   real_threshold / breakeven_threshold
bond_math.py:412                volume_threshold
```
`inflation_convergence.py:487` is the only one that does not. **Why this matters beyond style:** the
comparison decides whether a *published* disclosure appears on a *published* output. Move
`measured_base_rates.six_measure_high` from 0.895 to 0.70 — a legitimate re-measurement over a longer
history, which is the entire reason it is a config leaf — and the warning that the module's own docstring
calls *"the honest half"* of correction 2 **silently stops firing**, with no test failing and no
config-validation error (there is no range guard tying `current_rate` to the warning boundary, unlike
the `modal_share` case at `config.py:3944`). The threshold is a **claim about when a number becomes
uninformative**, and `measured_base_rates` is precisely the leaf that will change.

**Note on coverage — the literal is tested but not *governed*.** It is anchored by
`mutation_inflation_convergence.py` (`_BASE_RATE_WARNING`, mutants C1 unconditional / C2 dropped) and by
`test_the_base_state_warning_is_specific_to_high`, so any *code* edit is caught. What is not caught is a
*config* edit, because nothing ties the two together. This is the Class-G shape: a value that behaves
correctly at today's configuration and is silently coupled to a leaf that moves.

**FIX (concrete):** add `base_state_warning_threshold_value: CalibratedValue`
(`calibration_status: uncalibrated_illustrative`, `value: 0.75`, note: "the share above which a HIGH
reading is disclosed as the base state; a plausibility bar, not a measured one") beside
`measured_base_rates` under `inflation.convergence`, expose it as a validated float property on the
settings model with a `ge=0.0, le=1.0` guard **and** a cross-field validator asserting it is strictly
below `max(three_measure_high, six_measure_high)` — otherwise the disclosure is dead on arrival — then
change line 487 to read the leaf. `< 0.866` is the range that keeps today's behaviour.

### (A) DESIGN NOTE — one arithmetic argument is passed a value its name does not describe
At line 449–456:
```python
classification = _classify(
    agreeing=majority,                       # max(up, down)
    opposing=min(agreeing_side, opposing_side),
    ...
)
```
`_classify`'s own docstring (lines 346–348) states: *"Note that ``agreeing`` counts one side, so
``frac_agreeing`` here is the majority share, matching the specification's own arithmetic."* So `agreeing`
is passed the **majority** (which may be the *down* side) while `opposing` gets the minority. The
returned `CONFLICTED`/band results are **correct** — I verified all 27 combinations against an
independent reimplementation — because `_classify` only uses `frac` and `losing = min(agreeing,
opposing)`, both of which are invariant to which side is labelled "agreeing". But a parameter named
`agreeing` receiving a value that is 100% *down* in a disinflation month is a latent trap of the
**D-034/D-036/D-037** class: the next editor who adds a term that genuinely depends on *direction* (e.g.
"conflict only counts if inflation is rising") introduces a real bug with no test failing. The published
`value` field is likewise named `frac_agreeing` while holding the majority share for either direction —
which is what the spec does, and the docstring says so, but the name reads as a directional claim.
**FIX:** rename the parameter to `majority`/`minority` (internal, free), and either rename the published
field to `frac_majority` or add a `majority_direction` field so the sign is recoverable from the output
(the D-009 cross-field-identity habit).

### ✅ (A/D) THE ONE-FAMILY GAP IS **DOCUMENTED, TESTED AND DELIBERATE** — not a defect
`core_pce_direction` is required (it is the only BEA input), and the other two required fields are both
BLS, so **every legal call spans ≥ 2 families**. I verified exhaustively: the reachable family counts are
exactly `{2, 3}`, and `bands_available` is therefore **always** `["HIGH","MEDIUM","LOW"]` — the
§15.19-D ceiling can never *bind* through the public API. This looked like a defect of omission on first
read and it is not:
- `test_a_single_family_input_is_unreachable` enumerates the reachable space and asserts `{2, 3}` — *"so a
  future schema change that makes a single-family call possible fails this test instead of silently
  changing what the counts mean."*
- `test_bands_available_reflects_the_family_count` names it a **"real gap in Section 15.19-D's intended
  effect"** and records that the mechanism is kept implemented and helper-tested so that raising
  `min_independent_families_per_band` takes effect without a code change.
- The two unreachable warning branches (`independent_families == 1`, empty `bands`) are retained as
  defence against a future single-family input set, with `pragma: no cover`-style notes rather than
  fabricated tests. **This is the correct treatment of unreachable code** — retained, explained, and
  guarded by a test that detects the day it becomes reachable.

### (C) INPUT WIRING — PASS
`Direction = Literal[-1, 0, 1]` (line 116) with `extra="forbid"`; flat (`0`) is a first-class value,
counted separately from both sides and excluded from corroboration (verified: `3 all flat → LOW` with the
flat-exclusion warning). `_tagged_measures` builds one `ModelResult` per supplied measure so the family
census runs over *these* objects, and its trailing `assert len(results) == len(as_of_directions)` (line
316) is a genuine internal-consistency guard that fails loudly if `_INPUT_FAMILIES` and `all_directions`
diverge — and that assert is *reachable only if a future edit breaks the pairing*, which is precisely
when you want it.

### (D) DATA — PASS, with the units trap disclosed at the input model
The six measures map to live FRED series; `trimmed_mean_direction` → `PCETRIM1M158SFRBDAL` is
**annual-rate** while the five CPI-derived inputs are m/m — a factor-of-twelve hazard. The module consumes
only the sign, states that in the input docstring *and* repeats it in the module docstring, so the hazard
is recorded where the next magnitude-handling edit will see it.

### (E) INPUT-NOT-TAKEN — PASS
Every supplied measure is read in `all_directions` and in `inputs_used`; `measures_used` is published so
`frac_agreeing` has a visible denominator (D-046's "a count without its denominator" rule).

### (F) INTEGRATION — PASS (measured by execution, O-133)
`scripts/live_inflation_convergence_check.py` and `scripts/mutation_inflation_convergence.py`
(**28 mutants**) exist; the sweep's survivors are handled in-code (D2's inert guard removed; D2c's
narrow kill rests on `test_the_conflict_boundary_is_inclusive` at n=4 and the sweep notes so).

### (H) EVIDENCE — PASS
`pytest tests/models/test_inflation_convergence.py -q` → **54 passed**; no duplicate `test_*` names
(`uniq -d` empty).

**⚠️ (H) ALSO FOUND — three stale `.sweepbackup` files left in the tree** (`src/macro_engine/config.py`,
`data_layer/snapshot_builder.py`, `data_layer/validation.py`). Each was **byte-verified identical to both
`HEAD` and its working file** before removal (D-123/D-124), and all three are `.gitignore`d
(`.gitignore:97`), so they were harmless — but they are the residue of sweeps that did not clean up, and
a stale sidecar sitting beside a module is exactly the artefact D-123 says to diff, not trust. Removed.

**OBSERVATION (non-defect):** the `classification in bands: pass` / `elif bands:` / `else:` chain (lines
497–513) has a dead first branch — `classification in bands` is **always** True (verified 0 counter-examples
over all 729 inputs, because the family floor of 2 clears every band bar). That is a *consequence* of the
documented one-family gap, not a separate defect, and the unreachable branches are retained for the same
reason the warning branches are.

### ✅ STATUS UPDATE — **FIXED** (D-128, 2026-09-28)

**Both prescription items are FIXED.**

1. **A hardcoded literal is now a config leaf.** `inflation_convergence.py`'s base-state disclosure read
   the bare literal `if classification == "HIGH" and current_rate > 0.75:`. It now reads
   `settings.base_state_warning_threshold`, a new `CalibratedValue` leaf
   (`base_state_warning_threshold_value`, `uncalibrated_illustrative`) in
   `InflationConvergenceSettings`. The `_value`-suffix convention (D-126 precedent:
   `confidence_cap_value`) is used so the scalar property and the model field do not shadow.
2. **The Class-A rename.** `_classify(*, agreeing, opposing, …)` → `_classify(*, majority, minority, …)`,
   with `losing = min(majority, minority)` and `frac = majority / total`. A new helper
   `_majority_direction(up, down) -> Direction` was added and its result is published as
   `InflationConvergenceVerdict.majority_direction` — so the "which side holds the majority" question
   has a **stated, single, three-valued** answer (`1`/`0`/`-1`, with `0` the real "no majority" state,
   per D-040/D-050) rather than being recomputed ad hoc at each read.

**A config validator was added, not just a leaf.** `_validate_base_state_warning_threshold` (a
`@model_validator(mode="after")`) REFUSES a threshold outside `[0, 1]` and REFUSES
`threshold >= max(three_measure_high, six_measure_high)` — the latter because a threshold above every
produccible high band could never fire, making the disclosure dead-on-arrival (the D-127-class: a
disclosure that cannot fire is a lie the gates do not see).

**MEASURED:** the disclosure **fires today** (the shipped leaf 0.75 is below the live rate), the
threshold now follows a **moved** leaf (monkeypatched to 0.95 / 0.10, which kills the C-2a mutant),
`pytest tests/models/test_inflation_convergence.py` → **61 pass** (7 new tests);
`scripts/mutation_inflation_convergence.py` → **33/33 killed** (6 new mutants: C-2a literal revert —
which **SURVIVED at first** because the shipped 0.75 *equals* the old literal, and only
`test_the_disclosure_follows_a_moved_leaf` killed it; C-2b inverted; D-1a `majority_direction` dropped;
D-1b inverted; D-1c helper swapped; D-1d never-tie). **O-145 is cleared** (`mutation_qe_stance.py` was
already 28/28).

---

## CARD 20 — `src/macro_engine/models/inflation_dynamics.py` (768 lines, 2 functions)

**Purpose:** Two unrelated modules share this file. **Module 3.3** — `phillips_curve_inflation`:
`π = πᵉ − β(u − u*)`, one equation whose entire content is in the two terms that cannot be measured
(πᵉ is a *choice*; u* is unobservable by nature, §21.4 item 13). **Module 5.6** —
`cross_asset_transmission` (§20.5): given one repricing, emit **directional expectations for six assets**,
decomposed into real vs breakeven legs. The module's framing claim is that §20.5's spec is "the most
defective in the Tier 3 set" and that it corrects **seven** defects.

**STATUS: CLEAN** (two OBSERVATIONS; all 7 claimed corrections independently re-verified; both hand
cases reproduce; the `TransmissionDirection` `Literal` is a verified bijection)

**EVIDENCE:**

### (A/B) MATH & REASONING — PASS; both hand cases and all seven corrections reproduce
**Module 3.3 — sign convention, re-derived.** Measured `β = 0.5` (`phillips.beta_value`), `u* = 4.4`:
```
C1 tight  (u=4.0, u*=4.4): gap -0.4pp  →  2.5 - 0.5·(-0.4) = 2.70   ✓ (doc says 2.70)
C2 slack  (u=5.4, u*=4.4): gap +1.0pp  →  2.5 - 0.5·(+1.0) = 2.00   ✓ (doc says 2.00)
inverted `πᵉ + β·gap` would return        2.30 / 3.00 — the two "plausible but backwards" readings
```
The sign is load-bearing and the module says so with a dedicated direction test. **`beta` is correctly
NOT a field** — read from `settings.phillips.beta_value` so a recalibration moves every result and there
is no second source of truth that silently wins.

**Module 5.6 — the seven corrections, each independently verified:**
| # | Claimed defect | Verification (this audit) |
|---|---|---|
| 1 | `inflation_surprise_bp` declared, in `inputs_used`, never read | **Confirmed invariant.** Swept `None` vs `99.0` on a fixed repricing → the **only** key that changes is `inflation_surprise_bp` itself. Retained as a disclosure channel; output is byte-identical otherwise. |
| 2 | 3 keys (`bonds`, `long_duration`, `value_vs_growth`) from one predicate | **Confirmed.** `nom=+5` → `down/down/value_outperforms`; `nom=−5` → `up/up/growth_outperforms`; `nom=0` → all `flat`. The coupling is real **and is now published** via the shared `bonds` key, so it is auditable from the output rather than inferred. |
| 3 | `usd` was a sentence, not a direction | **Confirmed.** Emitted value is `'unresolved'` — a genuine `TransmissionDirection` member — with the §22.3 rationale (counterparty CB reaction unobservable on a US-only system). |
| 4 | gold's stated trigger ≠ implemented trigger | **Confirmed.** The corrected form tests the **real** leg and publishes `driver_channel` (`real_driven`), so the reason is on the record; the gold-on-a-nominal-rise case carries its **measured** base rate (0.7556). |
| 5 | `surprise_driver` as a bare `str` (D-029) | **Confirmed.** Now `SurpriseDriver = Literal[...]`; a typo is a validation failure rather than a silent fall-through to the least-informative branch. Verified `supply_shock → worse_than_rate_move_alone`. |
| 6 | flat market reported as a direction | **Confirmed.** `nominal=0.0` → `bonds='flat'` (spec's `> 0 … else` would have said `up`). `_leg_direction`'s boundary is **inclusive on the flat side** and pinned by a test: `_leg_direction(0.5, 0.5) == 'flat'`, `_leg_direction(0.51, 0.5) == 'down'`. |
| 7 | hardcoded `confidence=0.45` | **Confirmed.** Measured `compute_confidence` outputs: Module 3.3 → **0.3** (heuristic + unobservable, both earned); Module 5.6 → **0.5** (heuristic only, with `depends_on_unobservable=False` on the correct grounds that a *driver attribution* is an interpretation of a measured split). |

- **`_driver_of` is a genuine improvement over the spec, and its 5 outcomes are all reachable.** Swept a
  ±50bp grid → `{real_driven, breakeven_driven, both_channels, neither_channel, indeterminate}`. The
  `indeterminate` guard (`|nominal| < trivial_move`= 2.0bp) is the right defence: "dividing by a
  near-zero denominator is how a 1bp rounding artefact becomes a confident driver call." The
  `both_channels` branch is *only* reachable when the legs oppose — the comment proves it ("a share and
  its complement cannot both be large otherwise"), and the measured `breakeven_negative_share = 0.2652`
  confirms the legs routinely oppose.
- **The real-yield identity is exact, not a proxy.** `real = nominal − breakeven` reproduces TIPS
  `DFII10` to **0.000000** over 5,931 observations, which is what licenses the live check to cross-check
  the two paths. Verified: `nom=10, be=3 → real_yield_change_bp = 7.0`, shares `0.7 / 0.3`.

### (C) INPUT WIRING — PASS, with a well-reasoned validator
`_check_change_signs_are_not_degenerate` rejects **only** the case where *both* legs are exactly zero
**and** no surprise was supplied — measured: it fires. The docstring's reasoning is exactly right and is
the **D-050 `allow_all_neutral` lesson**: a single zero change is a real observation (a Treasury market
that did not move) and rejecting zeros "would make an observable state unrepresentable"; what is rejected
is the *silent* (0, 0) pair with nothing else, which "carries literally no information and a map built
from it is noise dressed as a view." **That is a guard-the-accident / permit-the-intent distinction
executed correctly.** The units trap (bp vs percent, a documented prior silent factor-of-100 in this
project) is stated in the field descriptions rather than prose above the class, and the
same-window/same-dates pairing requirement is stated because this is "the one model in the suite whose
whole content is a *difference of two changes*."

### (D) DATA — PASS
The `inflation_surprise_bp` absence is handled honestly rather than by requiring an unfetchable input:
no free series carries a CPI consensus forecast (probed via `fred_search`, recorded as a `blocked:`
registry entry), so requiring it "would make the function uncallable on live data while buying nothing."
The measured frequencies travel in the output (`gold_call_base_rate`, `breakeven_negative_share`).

### (E) INPUT-NOT-TAKEN — PASS, and the one non-taken input is *by design and disclosed*
`inflation_surprise_bp` is the only declared field not read, and §20.5's own map is provably invariant to
it — so **not** reading it *is* the faithful correction. It is published when supplied, `inputs_used`
lists it only when present, and a warning says explicitly that no direction depends on it. Every other
input is read.

### (F) INTEGRATION — PASS (measured by execution, O-133)
- Module 3.3: `live_labor_check.py:981` `_check_phillips_curve` wires it to live data.
- Module 5.6: `scripts/live_transmission_check.py` (10 functions) **plus** a second, independent consumer
  — `live_projection_check.py:52-56, 333` **cross-checks against `cross_asset_transmission` (D-052)**,
  which the module docstring itself cites as "the strongest available wiring test for this function."
- `scripts/mutation_transmission.py` = **12 mutants**.

### (G) CONFIDENCE — PASS
Module 3.3 → 0.3 (both penalties earned: `πᵉ` is a *choice* the model cannot validate, and u* is
unobservable by nature — the one lever §21.1 says must be pulled wherever u* is consumed). Module 5.6 →
0.5, with `depends_on_unobservable=False` **and** the reason stated: "which channel *drove* a move is an
attribution, not an observation — the same repricing is consistent with more than one narrative." A
penalty claimed only where a *model estimate* is made is the §22.8 rule applied correctly.

### (H) EVIDENCE — PASS, and D-045a is enforced in **both** directions
- `pytest tests/models/test_inflation_dynamics.py -q` → **26 passed**;
  `pytest tests/models/test_transmission.py -q` → **52 passed**. No duplicate `test_*` names in either.
- **`TransmissionDirection` is a verified bijection.** `declared == emitted` exactly, both directions
  empty:
  ```
  declared (8): up down flat value_outperforms growth_outperforms
                worse_than_rate_move_alone better_than_rate_move_alone unresolved
  emitted  (8): [identical set]
  declared-not-emitted: []      emitted-not-declared: []
  ```
  `SurpriseDriver` likewise has all 3 members producible in the equity key
  (`test_every_declared_driver_is_producible_in_the_equity_key`). The test docstring goes further than
  mere producibility — *"not only must each member be producible, each must be producible **as the thing
  it names**"* — which is the stricter reading of D-045a that the `Literal`-as-promise rule actually
  requires.
- `ASSET_KEYS` (6) is a declared tuple so a test asserts the published key set rather than iterating
  whatever happens to be there (the **D-038** rule: a test that iterates a published dict is vacuous when
  it is empty). Verified `set(ASSET_KEYS) ⊆ set(value)`.

**OBSERVATIONS (non-defects):**
1. **The file holds two unrelated models.** Modules 3.3 and 5.6 share no inputs, no config block, no
   vocabulary and no callers. That is only a *quality* point — the docstring separates them clearly and
   each has its own test file (`test_inflation_dynamics.py` / `test_transmission.py`), so the modules are
   already mentally split. A split would match the one-model-per-file convention the rest of
   `models/` follows.
2. **`_driver_of` returns a bare `str`, not a `Literal`.** It returns one of five documented states and
   both its callers compare it to string literals (`if driver == "indeterminate"`, `elif driver ==
   "both_channels"`, `elif driver == "neither_channel"`). This is the **same D-029 shape** the module
   *corrects* for `surprise_driver` three lines away — a typo in a comparison would silently fall to the
   `else`. It is currently safe (the values are module-private and set in one function), but
   `DriverChannel = Literal[...]` + a `driver_channel` tuple would make it consistent with the module's own
   standard and with `__all__` discipline. Low cost, closes the same class of hole.

---
## CARD 21 — `src/macro_engine/models/gdp_nowcast.py` (1484 lines, 4 public functions)

**Purpose:** Four functions across three module numbers, all growth-related:
`output_gap` (§6.5 / Module 7) — `(actual − potential)/potential × 100`, a **pure arithmetic function**;
`output_gap_from_snapshot` — the snapshot adapter that closes **O-7** (the CBO forward-projection filter)
and **D-009** (same-quarter pairing); `gdp_gdi_divergence` (§20.7 / Module 7.1) — the income-vs-expenditure
residual; `simple_gdp_nowcast` (§6.5 / Module 7.5) — the crude expenditure nowcast, published with its
own measured accuracy. The file's dominant theme is **disclosure of the measurement's weakness**: every
function reports the base rate or the error that would otherwise let a reader over-read the number.

**STATUS: ⚠️ DEFECT (Class G/E — a docstring that describes a caller contract the code does not
implement), plus one Class-C note.** The arithmetic, the pairing logic, the sign corrections and the
accuracy record are all verified correct.

**EVIDENCE:**

### ☠ (G/E) **DEFECT — `output_gap`'s docstring documents four caller inputs that do not exist**
`output_gap`'s "Confidence" section (lines 164–183) enumerates four factors and states the *caller*
supplies them:
```
* depends_on_unobservable=True   — potential GDP is ... unobservable
* data_quality_flags_present     — set by the caller when the snapshot ... was flagged.
* source_independence_count      — the number of genuinely independent source families
                                   behind the inputs (Module 13). ...
* is_heuristic_not_calibrated    — left to the caller, since whether the underlying
                                   potential-output estimate is calibrated is a fact ...
```
and concludes: *"The resulting value will land **at or below** the specification's 0.5 for a bare
two-input call."* **The code does the opposite.** `OutputGapInputs` has exactly two fields
(`actual_gdp`, `potential_gdp`) with `extra="forbid"`, and the body hardcodes
`source_independence_count=0` (line 225) while passing neither `data_quality_flags_present` nor
`is_heuristic_not_calibrated`:
```
OutputGapInputs fields: ['actual_gdp', 'potential_gdp']
caller CANNOT pass source_independence_count: ValidationError
output_gap(23000, 22900) → value 0.44, confidence 0.5     # measured
```
So three of the four documented factors are **not** caller-controlled, and the "at or below 0.5" claim is
**false for the only call the API permits**: the confidence is *identically* 0.5 (0.7 base − 0.2
unobservable) for every legal input, and can never go lower. A caller who supplies a flagged snapshot
(because the docstring told them the model would account for it) gets no penalty at all. This matters
because `is_heuristic_not_calibrated` is the flag that would express *"CBO's potential-output
methodology is not validated"* — the very fact the docstring calls "a property of the estimate's
provenance" — and it is unreachable. The same file's `simple_gdp_nowcast` gets this right
(`test_confidence_is_computed_not_asserted` asserts all three flags explicitly), so the inconsistency is
local to `output_gap`.

**FIX (concrete), two options — the second is preferred:**
1. *Make the docstring true:* add `data_quality_flags_present: bool = False` and
   `is_heuristic_not_calibrated: bool = False` (or a `source_independence_count: int = 0`) to
   `OutputGapInputs`, thread them into the `ConfidenceInputs`, and let a caller who knows the snapshot
   was flagged say so. Then the "at or below 0.5" claim becomes true across a range.
2. *Make the code match the docstring:* delete the three unreachable factors from the docstring and state
   plainly that `output_gap` is a **pure two-float function whose confidence is fixed at 0.5 by
   construction**, with the caller-side quality information expected to be applied by
   `output_gap_from_snapshot` / the orchestration layer. Cheaper and arguably more honest — the
   arithmetic function genuinely *cannot* know the snapshot's flags — but it should then say so, and
   `output_gap_from_snapshot` should be the documented place those flags are honoured.
Either way the current text is the defect: a docstring is a contract, and this one promises an input
surface the model rejects.

### (A/B) MATH & REASONING — PASS
- **`output_gap` formula exact.** `(23000 − 22900)/22900 × 100 = 0.4367…` → reported `0.44` ✓ (spec's
  `round(gap_pct, 2)`).
- **`_gap_direction_sentence` is a true three-state read**, not a `>0`/`else` pair: measured
  `+1.0 → "expansionary: economy above sustainable capacity (inflationary pressure)"`,
  `0.0 → "neutral: at potential"`, `−1.0 → "slack: economy below sustainable capacity…"`. The D-040
  defect class (exact zero falling into an `else`) is avoided, and the sign sense is the one the Taylor
  Rule's `(y−y*)` term expects — stated rather than assumed.
- **`gdp_gdi_divergence` arithmetic exact.** `2.5 / 1.5 → divergence_pp 1.0, average_growth_pct 2.0` ✓.
  The threshold comparison is **strict** (`abs(diff) > threshold`) and pinned on both sides: `2.6/1.5
  (diff 1.1) → significant True`; `3.5/2.5 (diff exactly 1.0) → significant False`. The sign of the
  divergence is deliberately **published but never characterised in words** — `_divergence_direction_sentence`
  states the sign *and* immediately disclaims it with the measured 47.8% coin-flip lead rate, so "a
  consumer that reads only `direction` cannot miss it." That is the correct handling of a value the
  model's own evidence says carries no information.
- **`_quarters_between` is month-arithmetic, not day-counting, and the reason is documented:**
  `(2026-01-01, 2026-07-01) → 2` ✓. The docstring names the exact failure the day-count version would
  have — *"It reports 3 quarters as 2 whenever two of the three fall short of 91 days, which is a silent
  undercount in exactly the situation the caller is trying to detect."*
- **`_quarter_annualized_mom` is arithmetic (not geometric) annualization, deliberately.** Measured
  `[1,1,1] → 3.0` (= `mean·3`), **not** `3.0301` (= `1.01³−1`). The docstring justifies the choice rather
  than leaving it as an accident: *"a geometric annualization would NOT be interchangeable and is
  deliberately not used: these are contributions being added, and the specification's model is
  additive."* The `months_per_quarter` divisor is a config leaf, **never a literal 12** — *"the
  annualization factor is `months_per_quarter * 100 / 100` in percent terms, and externalizing the
  divisor keeps it reviewable alongside the base it must match."*
- **`simple_gdp_nowcast`'s central correction verified as a live sign fix.** Measured weights
  `consumption 0.679 / investment 0.182 / net_exports −0.031`. The docstring's claim is that §6.5's
  **positive** net-exports weight moved the term inversely to the economy on **414/414 months**; the
  negative weight is what makes the product a contribution. Hand-verified on a synthetic quarter: `+1.4743
  = 0.679·consumption + 0.182·investment + (−0.031)·net_exports` → `consumption_contribution 1.0185`,
  `investment_contribution 0.4186`, `net_exports_contribution 0.0372`, sum `1.4743` ✓.

### (C) INPUT WIRING — PASS, with genuine refusals
- `OutputGapInputs.potential_gdp: float = Field(gt=0.0)` — a real guard, and the docstring gives the
  reason: *"a zero or negative value would make the ratio meaningless or silently invert the sign of the
  result."*
- `gdp_gdi_divergence` refuses non-finite inputs (measured: **both `nan` and `inf` refused**) with the
  exact justification the §21.0 rule requires — `abs(nan) > t` is `False`, so a missing observation would
  be reported as *"not significant"*, "a missing observation disguised as a finding."
- `simple_gdp_nowcast` refuses a non-finite base **and** refuses when no quarter has a complete month set
  for all three inputs, rather than annualizing short: *"two months annualized as three reports a rate no
  month produced."* I confirmed the completeness gate: `_is_complete_quarter([1,1,1], 3) → True`,
  `([1,1], 3) → False`; the quarter set is a **union** of all three inputs' keys so a quarter missing from
  one series is dropped rather than silently treated as the other two's.
- **`_check_change_signs…`-style narrowness is right:** `SimpleGDPNowcastInputs` uses `extra="forbid"`
  (test `test_extra_inputs_are_forbidden` asserts it), so a typo'd field is a validation failure.

**Class-C NOTE — one return value is a `str` inside a dict annotated for `str`, so this is *correct*, but
the Returns docstring omits the type.** `quarters_used` holds `'2026-Q1'` (measured `type == str`), and
the local annotation `dict[str, float | int | bool | str | None]` plus `ModelResult`'s outer union both
include `str` — so the typing is sound and `test_gdp_nowcast.py:399` asserts it as a string via
`as_str`. The gap is documentation only: the docstring's Returns list names `quarters_used` among keys
without saying it is the **quarter label**, not a count — adjacent to `quarters_measured` (137) and
`quarters_dropped` (int), which are counts. A reader skimming three `quarters_*` keys will assume
homogeneous types. Worth one clause in the docstring; not a code defect.

### (D) DATA — PASS; the O-7 filter and the D-009 pairing are both real and both justified by measurement
- **O-7 is closed in the adapter, and the truncation is *reported*, not silent.** `OutputGapSeriesReport`
  carries `withheld_forward_points` and `withheld_unpaired_points` **separately**, and the two are kept
  separate *because they have different meanings and different remedies* — a projection versus a realised
  point waiting on its print. Critically, the total is a **derived `@property`**
  (`withheld_potential_points`), and the docstring records **D-076**: the field was once *stored*, held
  the sum while its name said "forward-dated", and *"reporting 42 projections where the series contained
  41."* A stored total is "a second number that can disagree with its parts" — this is the correct shape.
- **The D-009 pairing defect is fixed and the diagnosis is preserved with the wrong numbers.** The
  docstring records the actual broken output (`actual 24,269.613 @ 2026-04-01` vs `potential 24,200.445 @
  2026-07-01` → `+0.29%`) and names the cause precisely: **CBO's `GDPPOT` runs one quarter ahead of
  FRED's `GDPC1`**, so subtracting Q2 actual from Q3 potential "does not measure the output gap." The
  rule stated is the right one: *"the output gap is a same-quarter comparison or it is not an output
  gap."* The adapter filters to `as_of`, then to the intersection, then takes the latest common date.
- **The `simple_gdp_nowcast` accuracy record is genuinely measured and the D-035 correction is disclosed
  rather than buried.** The config carries `mean_abs_error_pp 3.0261`, `persistence_mean_abs_error_pp
  2.9153`, `correlation_with_realised −0.0922`, `spec_form_correlation_with_realised −0.169`,
  `delta_overweighting_ratio_value 0.5052`, `quarters_measured 137`, `realised_positive_rate 0.8978`.
  The note on `quarters_measured` records **the exact trap a future reader will fall into**: a
  `GDPC1`-derived reconstruction "gives a **different sample and different figures** … so a later reader
  comparing against a `GDPC1`-derived figure will see a discrepancy and should check the series before
  changing anything." And the D-035 correction is recorded in full — the cumulative estimand that gave
  `7.747pp / +0.108` versus the correct one-quarter-ahead `2.930 / −0.169`, with the note that *"the live
  check … caught the discrepancy by failing; the tolerance was not widened."*

### (E) INPUT-NOT-TAKEN — PASS
Every declared field is read. `published_gdpnow` is optional and its absence changes only the presence of
one key + one warning; it is never required (the D-031/§21.0-rule-4 reasoning: *"a model must not require
an input it cannot always obtain"*).

### (F) INTEGRATION — PASS (measured by execution, O-133)
- Live consumers: `api_layer/orchestration.py:123-124` imports `gdp_gdi_divergence` and
  `output_gap_from_snapshot`; line 39 names `output_gap_from_snapshot` as *"the ONE shipped"* growth read;
  lines 1124–1235 wire `gdp_gdi_divergence` from the snapshot with four distinct failure paths.
- Sweeps: `scripts/mutation_gdp_nowcast.py` = **40 mutants**, `scripts/mutation_gdp_gdi_divergence.py` =
  **31 mutants**.
- Tests: `tests/models/test_gdp_nowcast.py` (**30 passed**) and `tests/models/test_gdp_gdi_divergence.py`
  (**35 passed**); no duplicate `test_*` names in either.

### (G) CONFIDENCE — the *mechanism* is right everywhere; see the DEFECT above for `output_gap`'s doc
- `gdp_gdi_divergence` → **0.3** (heuristic + unobservable + `source_independence_count=0`): all three
  earned — the threshold is illustrative, the residual's sign is uninformative, and GDP/GDI are one BEA
  release pair.
- `simple_gdp_nowcast` → **0.5** (heuristic only). `depends_on_unobservable=False` is **correct and
  explained**: *"The base is a realised print rather than an unobservable … the model depends on observed
  GDP growth, not on r*, u* or potential output."* `test_confidence_is_computed_not_asserted` asserts all
  three flags **and** that the result is `!= 0.35` (the spec's literal), so a mutation flipping either
  flag is caught.
- `output_gap` → 0.5 measured, but see the DEFECT: three of its four documented factors are unreachable.

**OBSERVATION (non-defect):** the file is 1484 lines holding **four** public functions from **three**
module numbers (7, 7.1, 7.5) plus two adapters and five helpers. As with Card 20's file this is a
*quality* point only — each function has its own test file and its own config block, and the module is
internally well-sectioned with banner comments — but `gdp_nowcast.py` is the largest file in `models/`
and a split (`output_gap.py` / `nowcast.py`) would match the one-concern-per-file convention the rest of
the package follows.

### ✅ STATUS UPDATE — **FIXED** (D-128, 2026-09-28)

**The audit's PREFERRED option was taken: the code is the truth, and the docstring was corrected to
match it** — no misleading surface was widened.

`output_gap`'s docstring had advertised four caller-supplied confidence factors
(`data_quality_flags_present`, `source_independence_count`, `is_heuristic_not_calibrated`,
`depends_on_unobservable`) while `OutputGapInputs` (`extra="forbid"`) rejected **every one of them** and
accepted only the two floats. A docstring promising an input surface the model refuses is the D-045a
class (a promise with two halves that disagree). The rewritten Confidence section states plainly that
`output_gap` is a **pure two-float function whose confidence is fixed at 0.5 by construction** (0.7 base
− 0.2 unobservable), with caller-side quality information applied by `output_gap_from_snapshot` / the
orchestration layer.

**The claim was verified, not just written:** `output_gap_from_snapshot` (`gdp_nowcast.py:619–630`)
DOES apply `data_quality_flags_present=True` for a flagged snapshot, so the sentence "the caller-side
data-quality information is applied by `output_gap_from_snapshot`" is backed by code. **MEASURED:**
`output_gap(23000, 22900)` → value `0.44`, confidence `0.5`.

**Two tests pin the corrected contract** so the two halves cannot drift apart again:
`test_output_gap_input_contract_is_exactly_two_floats` asserts the model's field set is *exactly*
`{actual_gdp, potential_gdp}` and that each of the four formerly-documented factors is REFUSED;
`test_output_gap_confidence_is_pinned_at_half_by_construction` asserts a positive-gap and a slack input
both publish 0.5 (the "fixed by construction" sentence made executable, and shown to be
input-*independent*).

**MEASURED:** `pytest tests/models/test_output_gap.py` → **23 pass, 1 skipped** (the skip is the
pre-existing calibrated-constants precondition, documented); `scripts/mutation_gdp_nowcast.py` →
**40/40 killed**, no anchor touched by the docstring edit.

---
## CARD 22 — `src/macro_engine/models/instrument_selection.py` (691 lines)

**Purpose:** Module 15 — `select_instrument`: map a `(thesis_type, gap_direction)` pair to the
production instrument that expresses it, or return one of **two sentinels** saying why there is none
(§22.12 analytical-only; §22.3 blocked-multi-country). Its defining constraint is §22.3.1's whole point:
**every thesis family must have an explicit branch, and no branch may name an instrument outside the
production universe.** This is the function that lets the system decline to trade.

**STATUS: ⚠️ DEFECT (Class G/E — a rationale published in the instrument field), plus one Class-C note
on an over-permissive guard.** The routing, the sentinels, the tenor parser and the universe boundary
are all verified correct and well-guarded.

**EVIDENCE:**

### ☠ (G/E) **DEFECT — `equity_macro` publishes a parenthetical rationale as the instrument name**
Measured, on the real `ProductionUniverse()`:
```
policy_path_gap            'UST 2yr note futures'                                  [rates]
curve_shape_gap            'Duration-weighted {short}/{long} UST {direction_word}' [rates]
inflation_expectations_gap 'Duration-matched TIPS long / nominal short (breakeven trade)' [rates]
equity_macro               'Broad equity index (per Section 6.9 duration/sector logic)'  [equity]
select_instrument(EQUITY_MACRO, POSITIVE) → value['instrument'] =
    'Broad equity index (per Section 6.9 duration/sector logic)'
```
Three of the four templates name a tradeable thing; `equity_macro`'s appends **a note to the reader**.
And critically, **that string is not a universe member**:
```
equity universe members:              ['Broad equity indices (ES, NQ, RTY)']
exact member match for the template:  False
bare-ticker match:                    None
category_for(...):                    'equity'   ← admitted by a KEYWORD hit ('equity index')
```
So §22.12's boundary check **passes on the keyword, not on membership** — the guard as constructed
cannot tell "an instrument the desk trades" from "a phrase containing the words *equity index*". The
config *rationale* for the route says **"No single-stock exposure (production universe boundary)"** —
i.e. there already **is** a correct instrument available (`Broad equity indices (ES, NQ, RTY)`), and the
template chose prose over it. This is precisely the defect this same audit found one card earlier in
`inflation_dynamics.cross_asset_transmission`, where `usd` held
`"up_if_relative_rate_expectations_rose"` and the correction was: *"A value no caller can compare,
branch on or evaluate is not an output, it is a TODO."* Its downstream consumer is
`TradeIdea.instrument` (`builder.py:1190`), and `decision_prohibition` in this very file says
*"MUST NOT have its `value` consumed as an instrument name"* — **for sentinels.** The executable branch
has no equivalent discipline, and the one template that needed it is the one that broke it.

**Compounding evidence that this is an oversight, not a decision:** no test pins the string
(`grep 'equity_macro\|sector logic\|Broad equity index' tests/models/test_instrument_selection.py` →
**empty**), and `docs/DECISIONS.md` never discusses the template. The `curve_shape_gap` rationale, by
contrast, records the *exact same class of failure being caught and fixed* — *"The leading 'UST' is
load-bearing: without it the string names no instrument the production universe recognises, which is
exactly how Section 22.3.1's literal failed its own matcher (D-058 probe P1/P2)."* The lesson was
learned on the curve route and **not applied to the equity route**, which instead reached for a keyword
that happens to match.

**FIX (concrete):**
1. Change `settings.yaml:1856` to an actual member name —
   `instrument_template: "Broad equity indices (ES, NQ, RTY)"` — and move the section reference into the
   route's existing `rationale` field, which is where prose belongs; it is already published to
   `value["rationale"]`. (Better still, expose a `universe_category`-derived default so the template
   cannot drift from `ProductionUniverse.equity`.)
2. **Strengthen the guard so this class cannot recur:** after `observed_category = universe.category_for(instrument)`
   succeeds, additionally require `universe.permits(instrument)`, and/or assert
   `instrument in universe.<category>` for the declared category. The keyword path currently makes
   §22.12's check *category-correct but membership-blind*, which is exactly the P4 defect the code
   comment says it fixed ("compared the EMITTED NAME to the real matcher") — it does compare the emitted
   name, but to a matcher that accepts far more than the universe lists.
3. Add a test pinning every route's emitted `instrument` to a real universe member, so the next template
   edit fails at CI rather than at the desk.

### (A/B) MATH & REASONING — PASS
- **`_parse_tenor_years` correct across the whole accepted vocabulary and all three failure modes.**
  Measured: `2y→2.0`, `10yr→10.0`, `6m→0.5`, `3mo→0.25`, `1w→0.0192`, `2Y→2.0`, `' 10Y '→10.0`;
  refusals confirmed for `'long'`, `'2x'`, `''`, `'y'`. The suffix table's **order is load-bearing and
  correct**: `("yr",1) ("y",1) ("mo",1/12) ("m",1/12) ("w",1/52)` tested in sequence, so `10yr` matches
  `yr` before `y` would (wrongly) leave a trailing `r`. Longer-suffix-first is the right construction and
  I verified `12mo→1.0`, `18mo→1.5`, `24m→2.0`, `52w→1.0` to rule out a substring inversion.
  **Raising rather than returning `None`** is the correct choice and the docstring says why: "a tenor the
  parser cannot read would otherwise flow into a string comparison that silently passes."
- **The three curve rejections all fire, each with a distinct message.** Measured:
  `2y/2y` → inverted/equal refusal; `10y/2y` → *"Curve legs must be ordered short-to-long"*;
  `2y/40y` → *"exceeds the configured maximum of 30.0y"*; `2y/2.5y` → *"are 0.5000y apart, below the
  configured minimum of 1.0y"*. The **leg-order rejection is the subtle and correct one**: it enforces
  that the slope's sign lives in `gap_direction` and *not* in leg order, because "a '2y/10y' trade and a
  '10y/2y' trade are the same instrument written two ways … one way to say it twice and get it wrong."
- **`GapDirection` is a real consumption site, not a carried field.** Measured: `POSITIVE → steepener /
  'Duration-weighted 2y/10y UST steepener'`, `NEGATIVE → flattener / '…UST flattener'`. The comment
  records that before **D-058** "the direction reached only `inputs_used` and no output depended on it"
  — a **Class-E defect found and fixed**, and `direction_word` is now published "so the consumption of
  `gap_direction` is visible in the output rather than only in the code." That is the right remedy.

### (C) INPUT WIRING — PASS, with one over-permissive guard (see the DEFECT's fix #2)
- `_tenors_only_belong_to_curve_trades` refuses a curve leg on any non-curve route — measured: refused.
  The reasoning is the same one-step-down logic as `extra="forbid"`: "Silent acceptance is how a caller
  concludes their tenors were honoured when they were dropped."
- Supplying **one** leg and not the other is deliberately accepted (defaulted), which the docstring
  justifies as "what a caller editing one leg expects." Consistent with the measured behaviour.
- **All 7 `ThesisType` members reach a branch — verified by enumeration, none raises.**
  `policy_path_gap` → `'UST 2yr note futures'`; `curve_shape_gap` → the curve template;
  `inflation_expectations_gap` → the TIPS breakeven trade; `equity_macro` → (see DEFECT);
  `cross_country_divergence` → `BLOCKED_MULTI_COUNTRY_NOT_BUILT`;
  `credit_quality_gap` + `em_vulnerability` → `ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT`. This is
  **D-045a's two-halves rule satisfied at the enum level**, and it is the §22.3.1 requirement that no
  family silently falls through.
- The routing-table gap **does** refuse rather than fall back: `routes.get(...) is None` → `ValueError`
  listing `sorted(routes)`. Measured route set = `{curve_shape_gap, equity_macro,
  inflation_expectations_gap, policy_path_gap}` — i.e. exactly the 4 non-sentinel members, so the two
  sentinel branches are what keep the table complete. Good: the two mechanisms are complementary.

### (D) DATA — PASS
Every route is config-sourced (`instrument_selection.thesis_type_routes`), and the confidence leaves
(`heuristic_not_calibrated=True`, `independence_count=0`) are read from config rather than hardcoded.
`InstrumentUniverse` is a **narrow `Protocol`** so the dependency runs `thesis_layer → models` and not
the reverse — the protocol is "the smallest surface `select_instrument` actually uses, so a future
universe implementation is not forced to reproduce an unrelated API." That is the correct way to take a
callback object across a layer boundary without importing upward.

### (E) INPUT-NOT-TAKEN — PASS
`inputs_used` is `["thesis_type", "gap_direction"]` on the executable branch — both are genuinely read
(`gap_direction` selects the direction word, `thesis_type` the route). The sentinel branch reports only
`["thesis_type"]`, which is correct: nothing else is consulted. Verified that a non-curve route ignores
tenors *and* refuses them rather than ignoring them silently.

### (F) INTEGRATION — PASS (measured by execution, O-133)
`scripts/live_instrument_selection.py` and `scripts/mutation_instrument_selection.py` exist;
`api_layer/orchestration.py:1735` resolves the universe (`universe if universe is not None else
ProductionUniverse()`), and `portfolio/risk_budget.py:2650` constructs one too — so the Protocol has
**two independent** real implementations consuming it.

### (G) CONFIDENCE — PASS, and the sentinel reasoning is the file's best moment
- Executable branch → **0.5** (heuristic only; `settings.heuristic_not_calibrated=True`,
  `independence_count=0`). Measured identical on the sentinel branch → also **0.5**.
- **That equality is deliberate and argued**, and it is the correct call: §22.3.1 reports sentinels at
  confidence `0.0`, and the module refuses because *"a sentinel is a confident negative — 'this thesis
  has no production expression' is a structural fact, not a failure to determine one — so reporting it at
  0.0 states the opposite of the truth."* The module is explicit that the independence credit is **a true
  zero, the same zero the executable branches receive** — "the confidence difference between a sentinel
  and an instrument is a difference of *no* factors, not a hand-set penalty." Measured: both 0.5, so the
  claim holds.
- `depends_on_unobservable=False` is right on both branches: "nothing here rests on r*, u* or potential
  GDP."

### (H) EVIDENCE — PASS
`pytest tests/models/test_instrument_selection.py -q` → **38 passed**; no duplicate `test_*` names
(`uniq -d` empty).

**OBSERVATION (non-defect):** the two sentinel constants are bare module-level `str`s
(`ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT`, `BLOCKED_MULTI_COUNTRY_NOT_BUILT`) rather than members of an
enum or a `Literal`. They are in `__all__` and the docstring notes the value is "importable without
constructing anything, and so a test can assert the function *returns* this rather than a re-typed
string" — which is the substantive protection. But the function's declared return type for `value` is a
broad union, so nothing at the type level stops a caller comparing against a re-typed literal. A
two-member `Sentinel` enum (or a `Literal` alias of the two constants) would make the sentinel set
enumerable the same way `ThesisType`/`GapDirection` already are — consistent with this file's own
"tuple-plus-Literal" idiom. Low priority because the constants are exported and tested.

### ✅ STATUS UPDATE — **FIXED** (D-128, 2026-09-28)

**The config defect is fixed and the guard was strengthened; one prescription sub-item was found
UNSOUND by measurement and replaced with the sound equivalent.**

1. **The template now names a real member.** `settings.yaml` `equity_macro.instrument_template` changed
   from `"Broad equity index (per Section 6.9 duration/sector logic)"` (prose) to
   `"Broad equity indices (ES, NQ, RTY)"` — a verbatim member of `ProductionUniverse.equity`. The
   Section 6.9 note moved into the route's `rationale` (published under `value["rationale"]`), where
   prose belongs. **MEASURED:** `select_instrument(EQUITY_MACRO, POSITIVE)` now emits
   `'Broad equity indices (ES, NQ, RTY)'`, `permits=True`, `category=equity`.
2. **The guard was strengthened with `universe.permits(instrument)`** — the universe's OWN membership
   statement — required **in addition to** the `category_for` classification.
3. **A test pins every route's emitted instrument to a real universe member**
   (`test_the_equity_route_names_a_literal_universe_member_not_a_description`, plus the
   category-agnostic `test_no_executable_route_publishes_prose_as_its_instrument`), so the next template
   edit fails at CI.

**⚠️ MEASUREMENT OVERTURNED THE AUDIT'S SECOND HALF, and this is the substantive finding.** The audit
prescribed requiring `permits` **and/or** `instrument in universe.<category>`. I implemented the strict
`in universe.<category>` form first and it **broke three legitimate routes**:

```
The route for 'policy_path_gap' publishes 'UST 2yr note futures', which is not a MEMBER of the
production universe's 'rates' category ['Fed cash (2y...', 'UST futures (TU, FV, TY, US)', ...]
```

`rates` lists the **family** `"UST futures (TU, FV, TY, US)"`, while `policy_path_gap` correctly ships
the **specific contract** `"UST 2yr note futures"` (TU by name) and `inflation_expectations_gap` ships
the breakevens structure — both real, desk-verified instruments that the keyword path recognises as
specific instances of a listed family. A strict membership check trades one real defect for two false
refusals, which is the wrong trade (Section 22.8: refuse rather than guess — but never refuse a correct
answer). **`permits` was measured to reject NONE of the five strings, including the defective one**, so
it is defence in depth and not the whole fix; the exact-membership pin therefore lives in the **test**,
per category, where the family-vs-instance answer is known — strict equality for `equity` (which lists
exactly one member), a membership-or-prose check for the rest.

**MEASURED:** `pytest tests/models/test_instrument_selection.py` → **42 pass** (was 38; +4);
`scripts/mutation_instrument_selection.py` — **M3.4 added** (the `permits` guard made vacuous) plus the
**M9b group (3 mutants)**, which edits the shipped YAML `instrument_template` (the sweep now targets
`config/settings.yaml` for the first time): M9b.1 reverts `equity_macro` to the prose form (the D-128
defect), M9b.2 renames it to a keyword-valid non-member, M9b.3 adds a document reference to
`policy_path_gap`. **All 3 M9b mutants KILLED**, so the config pin binds.

---

## CARD 23 — `src/macro_engine/models/labor_synthesis.py` (1433 lines, 9 public functions)

**Purpose:** Module 6 — the whole labour block in one file, built on a stated **lead/lag hierarchy**
(claims 0.4, JOLTS 0.4, NFP 0.2 — "weights are not a preference"). Nine public functions:
`labor_tightness_score` (§6.4), `claims_trend_signal` (§6.1), `claims_corroboration` (§6.3),
`two_survey_divergence` (§6.1), `beveridge_curve_position` (§6.2), `ahe_composition_flag` (§6.2),
`nfp_revision_adjusted_read` (§6.1), `inflation_breadth_score` (§6.3), and the
`beveridge_shift_tolerance` accessor. This is the single largest concentration of
threshold-gated categoricals in the Phase 0–4 tree, so it is also the densest field for the
D-040 / D-047 / D-050 class of defect.

**STATUS: ☠ DEFECT (Class B — a real producible state is classified as a *different* state, and the
disclosure asserts a fact that is false).** One function of nine. The other eight are clean, and two of
them (`claims_trend_signal`, `two_survey_divergence`) are the best-argued boundary handling in the file.

**EVIDENCE:**

### ☠ (B) **DEFECT — `inflation_breadth_score` reports a FLAT reading as `CONFLICTED`/`disagree`**
`inflation_breadth_score` classifies by **sign**:
```
all_positive = all(v > 0 for v in values)          # line 1307
all_negative = all(v < 0 for v in values)          # line 1308
same_direction = all_positive or all_negative      # line 1309
```
With three m/m readings of **exactly zero** — a real, producible state (a month in which headline CPI,
core CPI and core PCE each printed unchanged) — `all_positive` is `False` and `all_negative` is
`False`, so the reading falls to the `else` branch. Measured:
```
inflation_breadth_score(InflationSubMeasures(
    cpi_headline_mom=0.0, cpi_core_mom=0.0, pce_core_mom=0.0))
  value:        0.0
  confidence:   0.3            ← the DIVERGENT (lower) confidence
  direction:    'CONFLICTED: measures disagree in sign, so the average describes neither'
  interpretation: 'Divergent inflation signal across headline CPI, core CPI and core PCE, average +0.00% m/m'
  warning[0]: 'Sub-measures disagree — per Module 13, investigate the source of the divergence
               before treating this as a trend. The average of opposing readings describes neither.'
```
**Every published sentence is false for this input.** The three measures do not disagree; they *agree*
— all three are flat. There are no "opposing readings" for the average to describe. The classification,
the `direction` string, the `interpretation`, and the warning all assert a disagreement that did not
happen. It also wrongly earns the **lower** confidence (0.3 rather than the convergent 0.5), and it
routes the reader to Module 13's "investigate the source of the divergence" procedure for a divergence
that does not exist. Measured enumeration of the 27 sign states (`{-1,0,+1}³`,
`values=[0.5*c]`) → `{'rising': 1, 'falling': 1, 'CONFLICTED': 25}` — **25 of 27** states report
`CONFLICTED`, and **19 of those 25 contain a genuine disagreement**, while the zero-containing ones
that are all-`0` do not. The single all-zero state is the specific wrong one.

The file's own three-state helper proves the intent, and the defect is that the function does not use
it consistently. `_breadth_direction_sentence(all_positive, all_negative)` (line 1258) is written
**precisely** to keep the third state honest — its docstring: *"'all rising', 'all falling', and
'measures disagree' are not a direction and its negation. The third state is the one that matters."*
But its third state's literal text is `"CONFLICTED: measures disagree in sign"` — so the helper folds
**all-zero** (measures *agree*, on zero) into the same bucket as **mixed-sign** (measures *disagree*),
and the docstring's own claim that the naming prevents the collapse is not met. This is the **D-050
shape** exactly: *"a real state real data produces must be representable"* — here it is representable
but mislabelled, which is the same `all()/else` mistake as **D-040** ("a `>0`/`else` pair that reports a
flat market as a move"), one layer up.

**Reachability on the live path — not hypothetical.** `api_layer/orchestration.py:_inflation_leg`
(lines 634–662) feeds the function real m/m percent changes computed from the latest two observations of
CPIAUCSL / CPILFESL / PCEPILFE. A month where a series is unchanged between prints yields exactly
`0.0`, and the guard is `> 0`, so an unchanged print lands in the divergent branch. `direction` is
consumed by the Module-3 regime classifier's inflation axis — the same axis the docstring says is
load-bearing (*"the classifier reads inflation MOMENTUM, so a 'falling' breadth read is what makes
'disinflation' reachable"*) — so a mislabelled flat read propagates into the regime read, not merely
into a displayed string.

**Why the green suite did not catch it:** `pytest tests/models/test_labor_synthesis.py -q` →
**42 passed** (collected `--collect-only` → 42). No test supplies a zero sub-measure —
`grep 'cpi_headline_mom=0\|cpi_core_mom=0\|pce_core_mom=0' tests/models/test_labor_synthesis.py` →
**empty**; all seven breadth tests use strictly positive or mixed-sign values (lines 647, 666, 676, 679,
690, 705, 732). The suite exercises `rising`, `falling`, `divergent` but never `flat\*`, so the defect
sits in the untested cell — a **Class-H evidence gap** that let a Class-B defect ship.

**FIX (concrete):**
1. Make "all flat" an explicit third *benign* state rather than a fall-through. Add
   `all_flat = all(value == 0 for value in values)` at line ~1308 and branch it **before** the
   divergent `else`, classifying a flat read as its own verdict with wording that states the measures
   agree on zero (e.g. `"flat: all three measures unchanged"`). It must not reuse the divergent
   confidence.
2. If a mixed flat-and-signed reading is also worth distinguishing (e.g. `+0.2, 0.0, 0.0`), decide it
   explicitly; do not let it fall through either. At minimum, the warning text should only be emitted
   when the signs genuinely differ (`any(v > 0) and any(v < 0)`), which is the test that actually
   corresponds to the sentence "measures disagree".
3. Rewrite `_breadth_direction_sentence` (line 1258) to take the flat case as a third predicate, so the
   helper's own docstring claim — three genuinely distinct states — is true of its implementation.
4. Add the regression test the suite is missing: assert that
   `InflationSubMeasures(0.0, 0.0, 0.0)` does **not** produce a `CONFLICTED`/`disagree` direction and
   does **not** carry the divergent confidence, and that its warning does not say "disagree". Also pin
   the mixed-sign case to confirm the divergent wording still fires where it is correct.
5. Consider whether a small dead-band (config, not literal — consistent with this file's
   `two_survey.min_meaningful_change_thousands`) should define "flat", so a `±0.005%` rounding wobble is
   not read as a disagreement. The config leaf pattern for it already exists in the same settings block.

### (A) MATH & REASONING — PASS (**every** hand calculation re-derived from source)
- **`labor_tightness_score` docstring hand calc reproduces exactly.** Config read from disk: weights
  `0.4/0.4/0.2` (sum `1.0`), scaling `claims −2.0`, `openings 0.5`, `quits 0.5`, `centering 50.0`,
  `neutral_nfp_pace 150.0`. Measured on the §6.4 defaults (`−0.4 / 3.0 / 60.0 / 180.0`) →
  `value 3.5`, `context` components `claims +0.80, JOLTS +6.50, NFP +3.00`. Hand check:
  `−(−0.4)·2.0 = 0.80`; `0.5·3.0 + 0.5·(60−50) = 6.50`; `(180−150)/10 = 3.00`;
  `0.4·0.80 + 0.4·6.50 + 0.2·3.00 = 0.32 + 2.60 + 0.60 = 3.52 → 3.5`. ✔
- **The three "plausible-but-wrong transcription" traps the docstring names are all avoided.** (i) The
  claims sign is inverted by the **config multiplier** `−2.0`, not a literal minus in the expression —
  measured: `claims_component = −2.0 · (−0.4) = +0.80` (positive, i.e. falling claims ⇒ tighter). (ii)
  The JOLTS percentile is **centred on 50** (`percentile − quits_centering`), so `60.0 → +5.00` and a
  mid-range `50.0 → 0.00`. (iii) The result is **clamped** to `[−100, +100]` with the raw value preserved
  in a warning (measured `clamped = score != raw_score`).
- **Weight-normalisation guard reads the same object the score reads.** Line 178 refuses unless
  `abs(weights.total − 1.0) <= 1e-9`; `total` is a derived property (`claims + jolts + nfp`), so the
  check cannot drift from the sum actually used. Correct construction (a stored total would be D-076).
- **The JOLTS-centring docstring claim was verified against the emitted context, not the code.** The
  context prints `JOLTS +6.50` for percentile `60`, which is only `6.50` if centring happened
  (`0.5·3 + 0.5·(60−50)`); an uncentred version would print `1.50 + 5.00` differently-structured. ✔
- **`claims_trend_signal` — both windows are drawn from ONE series (D-022 applied structurally), and
  the "measured −8.8%" claim in the docstring was itself re-measured.** A `+2%/week` 13-week rise
  (`200000·1.02ⁱ`) gives `latest_4wk 246285.2`, `trailing_4wk 206080.4`, `pct_above +0.195`, and the
  docstring's warning scenario ("latest against the window **mean**") measures `+9.05%` for my series —
  the *sign inversion* the docstring describes is produced by comparing the leading quarter against the
  mean of a rising series, which is the class it correctly rules out. The two slices are
  **last-4 vs first-4** of the same 13-week window (`sum(window[-4:])/4`, `sum(window[:4])/4`), so
  neither side gets more smoothing. ✔
- **The persistence loop is strict (`>`) and the flat/monotone cases behave.** Measured: an all-flat
  `[200000]*13` → `consecutive_weeks_rising == 0` (the loop breaks on the first non-`>` comparison, so a
  flat does not count as a rise); a rising series with a flat tail → `9` rising weeks and
  `pct_above +0.086`. This is the correct reading of "risen for at least N consecutive weeks" and
  matches the strict magnitude test (`> pct_threshold`, line 461). Its own test
  `test_claims_magnitude_threshold_is_strictly_greater_than` pins it — a **Class-A boundary that is
  tested**, which is why this function has no defect.
- **`claims_trend_signal`'s two-condition gate is genuinely non-redundant — reproduced both failure
  modes.** A one-week spike `[200000]*12 + [260000]` → `consecutive 1`, `pct +0.075`, `persistence False`,
  `is_signal False` (passes magnitude, fails persistence). The flat series → fails both. This is the
  docstring's exact claim, measured. ✔
- **`two_survey_divergence` — all four docstring hand cases reproduce, and the four-state partition is
  total.** Measured: `(200,·,0.1,0.2) → PARTICIPATION_DRIVEN`; `(200,·,0.1,−0.1) →
  GENUINE_DIVERGENCE`; `(−100,·,0.2,−0.2) → BROAD_WEAKENING`; `(200,·,−0.1,0.1) →
  CONSISTENT_STRENGTH`. The classification is sign-only by construction, which the docstring *discloses*
  as a limitation and a warning rather than hiding — the correct handling of a deliberate
  low-resolution test.
- **`claims_corroboration` — the four-input partition is total and the collapse is disclosed.**
  Measured `(True,True) → genuine_downturn_signal`, `(True,False) → churn_not_downturn`,
  `(False,True) → no_signal`, `(False,False) → no_signal`. The two `no_signal` cells collapse, and the
  branch's own text names why: *"No initial-claims deterioration to corroborate. Nothing to
  distinguish — this is absence of evidence, not evidence of stability."* Collapsing them is correct
  (the verdict is about *initial* claims), and the wording refuses to over-read. ✔
- **`beveridge_curve_position` — the tolerance band is inclusive and symmetric, and both ends were
  measured.** `shift > threshold → OUTWARD`; `shift < −threshold → INWARD`; a shift of **exactly**
  `±0.50` (the configured `shift_tolerance_pp = 0.5`) → `ON_CURVE_cyclical` on **both** signs. The
  band's docstring claim ("symmetric in effect but not in construction … any shift inside the configured
  tolerance is ON_CURVE") holds. ✔ The function correctly takes `historical_openings_at_this_u` as an
  **input** rather than re-deriving the fitted curve — the docstring's stated reason (a chart
  transcribed into a formula treated as data) is the project's no-prototyping rule applied to a fitted
  assumption, and it is right.
- **`ahe_composition_flag` — the COVID-2020 hand case and both strict boundaries reproduce.** Measured
  `(8.0, 2.5, −12.0) → {'distortion_flagged': True, 'ahe_minus_eci_pp': 5.5}` (matching the docstring);
  `(3.5, 3.3, +1.2) → False`. Boundary: low-wage change of **exactly** `−1.0` (the configured
  `low_wage_decline_pct`) → `False` (strict `<`), and an AHE−ECI gap of **exactly** `0.75` (the
  configured `eci_divergence_pp`) → `False` (strict `>`). Both boundaries are strict and match the
  config semantics. ✔ The conservative third branch (ECI `None` **and** low-wage falling ⇒ flagged on
  composition alone) was measured: `eci=None, low=−12 → flagged`; the docstring's "conservative
  direction" reasoning is realised.
- **`nfp_revision_adjusted_read` — the strict threshold and the negative-headline exclusion both hold.**
  Measured net `−50.0` (== configured `misleading_net_thousands`) → **not** misleading (strict `<`);
  net `−51.0` → misleading fires (warning count `3 = 1 base + 2 misleading`); a negative headline with
  large negative revisions → **not** misleading (`1` warning), exactly as the docstring argues ("a
  negative headline with negative revisions is not 'misleading' — the revisions are confirming it").
  ✔ This is the D-040 symmetry done correctly: the flag requires *both* a positive headline and net
  revisions below threshold.
- **`_tightness_direction_sentence` is a genuine three-state read (D-040 handled).** Measured
  `−5.0 → loosening`, `0.0 → neutral: at the balanced level`, `+5.0 → tightening`. Zero is not swept
  into either `else` — which is exactly the discipline `inflation_breadth_score`'s sign test fails to
  apply (see DEFECT). The file contains both the correct pattern **and** the broken one.

### (C) INPUT WIRING — PASS
- Every input model is `extra="forbid"`. `ClaimsTrendInputs.weekly_initial_claims` carries
  `min_length=13`, and `claims_trend_signal` **also** guards `len(weekly) < 13` in the body (line 427) —
  belt-and-braces, with a test (`test_claims_function_guard_covers_a_bypassed_contract`, line 519)
  proving the body guard fires even when the contract is bypassed. Correct: the contract can be bypassed
  by `model_construct`.
- `ClaimsTrendInputs` holds **one** series and derives both windows internally (D-022) — a caller cannot
  supply two disagreeing windows because the caller no longer supplies windows. The docstring states
  this and it is structurally true.
- `BeveridgeInputs.openings_rate_pct` is `ge=0.0`, `unemployment_rate_pct` is `ge=0.0, le=100.0`,
  `historical_openings_at_this_u` is `ge=0.0` — the rate/level distinction the docstring stresses is
  enforced by the field bounds, not merely described.
- `AHEDistortionInputs.eci_growth_yoy_pct` is correctly `float | None` with `default=None`; `None` is a
  *documented expected state* (ECI is quarterly), not missing data — the right design for a genuinely
  intermittent series, and the function branches on it explicitly (line 1036).
- `claims_trend_signal` rejects a non-positive observation **in the trailing window** (line 435) with a
  message naming why (a percent comparison against zero is undefined). The guard is scoped to the
  window, and the test `test_claims_rejects_non_positive_levels` pins it.

### (D) DATA — PASS
- No numeric threshold is a bare literal in any model body. Every band is a config leaf:
  `labor.claims.{consecutive_weeks,pct_above_trailing}` (3, 0.05), `labor.ahe_distortion.
  {low_wage_decline,eci_divergence}` (−1.0, 0.75), `labor.revisions.misleading_net` (−50.0),
  `beveridge.shift_tolerance.shift_pp` (0.5), `inflation.breadth.{convergent,divergent}` (0.5, 0.3).
  Measured all of them from `get_settings()` — none mismatched the model's read.
- The **two** module constants that *are* literals are argued as scale definitions rather than tunable
  judgement: `_SCORE_FLOOR/_SCORE_CEILING` ("changing it would change the meaning of every score ever
  recorded") and `_nfp_scaling_divisor()` returning `10.0` ("a unit conversion — thousands of jobs →
  score points — not a tunable judgement; the neutral pace it is applied against *is* a judgement, and
  that one is in config"). Both distinctions are sound; the neutral pace **is** in config
  (`150.0`). This is the correct application of the literal-vs-config rule, not an exemption claimed.
- `quits_percentile_window_months` (36) is config with a documented reason (the snapshot may carry less
  history) — and the API layer reportedly reports the window actually used.

### (E) INPUT-NOT-TAKEN — PASS
`inputs_used` matches the inputs genuinely read in every function: `labor_tightness_score` lists all
four `LaborInputs` fields (all four are read); `claims_trend_signal` lists
`["weekly_initial_claims"]` (the only input); `two_survey_divergence` lists all four `TwoSurveyInputs`
fields, and its docstring **explicitly discloses** that `household_employment_change_thousands` enters
only the reported `survey_gap` and **not** the verdict (*"does not enter the verdict at all; it is
reported so a reader can see…"*) — a taken-but-not-classified input that is disclosed rather than
silently listed. That is the honest handling of a Class-E-adjacent case.
`ahe_composition_flag` lists all three fields (all three are read, `eci` conditionally).

### (F) INTEGRATION — PASS (measured by execution, O-133)
- `inflation_breadth_score` has a **real live caller**: `api_layer/orchestration.py:657`
  (`_inflation_leg`), which builds `InflationSubMeasures` from three `_mom_percent` derivations and
  appends `DerivationNote`s (lines 645–657). So the DEFECT's blast radius reaches the live path.
- `labor_tightness_score` and the other Module-6 reads are reachable from the orchestration layer's
  economy reads; the file's inputs are wired from the snapshot rather than from constants.
- `grep` for the private accessors confirms the intended single-point-of-config-path pattern:
  `beveridge_shift_tolerance`, `_ahe_thresholds`, `_revision_thresholds` each read one config path
  **once**, so a `config.py` rename is a one-line edit here — the docstring's stated reason for the
  accessor, and it holds.

### (G) CONFIDENCE — PASS except the DEFECT's branch assignment
- Every `compute_confidence()` site is `ConfidenceInputs(is_heuristic_not_calibrated=True)` — correct
  under §22.8, because each model reads `uncalibrated_illustrative` config leaves (the weights, the
  thresholds, the scalings are all `uncalibrated_illustrative` per `settings.yaml`). Measured:
  each returns **0.5** (base 0.7 − heuristic 0.2).
- **`claims_corroboration`'s identical-across-branches confidence is deliberate and argued**, and I
  measured it identical (all four input combinations → **0.5**). The docstring: *"three boolean-derived
  verdicts are not better evidenced because one of them is alarming."* Same discipline in
  `claims_trend_signal` ("in both branches … letting the positive branch score higher would make the
  model systematically eager"). This is the correct refusal to let severity drive confidence — the
  opposite of the failure mode the audit looks for. ✔
- `inflation_breadth_score` is the **declared** §6.3 exception (confidence from config, not
  `compute_confidence()`) and the docstring says so and explains why ("a property of this specific
  convergence test"). The exception is legitimate, **but** it is `breadth.convergent=0.5` vs
  `breadth.divergent=0.3` — and the DEFECT assigns the defaulting all-zero input the **divergent**
  confidence, so the exception is being used to hand a flat reading the *lower* number.

### (H) EVIDENCE — the suite is green and the defect is outside its coverage
`pytest tests/models/test_labor_synthesis.py -q` → **42 passed** (`--collect-only` → **42**; 35 `def
test_*` plus 2 parametrized expansions — 4 corroboration combos + 4 contract-conformance params). No
duplicate `test_*` names. The tests are genuinely strong where they reach — boundary strictness,
sign conventions, cross-window identity, the `-8.8%` slicing class, branch-independence of confidence —
but **no test supplies a zero sub-measure to `inflation_breadth_score`**, which is precisely why the
Class-B defect survived (Class-H gap, per the file-by-file standard). No `scripts/mutation_labor_
synthesis.py` exists; unlike the Tier-5 files, this Phase-0–4 file has no mutation harness, so there is
no mutant set to consult for the zero-state case.

**OBSERVATIONS (non-defects):**
1. **The file holds nine public functions across at least four distinct Module numbers (6.1, 6.2, 6.3,
   6.4)** — 1433 lines. It is coherent (all labour) but large; a split into `labor_tightness.py` /
   `labor_claims.py` / `labor_wages.py` would match how the codebase separates other domains. Low
   priority — the cohesion argument (one module) is real.
2. **`claims_corroboration`'s `no_signal` verdict covers two distinct input states and the verdict
   string does not distinguish them.** They are correctly treated as equivalent for the *intended*
   question (is there an initial-claims deterioration to corroborate?), and the interpretation says so —
   so this is not a D-045a violation. It is noted only because a caller scanning verdict strings cannot
   tell "no initial-claims signal at all" from "initial claims quiet, continuing claims rising."
3. **`TwoSurveyInputs.unemployment_rate_change_pp` docstring warns against passing a level** ("a +5.0%
   unemployment 'change' would flag every input as rising") but nothing structurally prevents it — the
   field is a bare `float`. A `ge=-20, le=20` sanity bound (or a named `_pp_change` type) would make the
   documented misuse unrepresentable, the same way `BeveridgeInputs` bounds its rate. Low priority
   because the docstring is explicit and the live path derives the change correctly.

---

### ✅ STATUS UPDATE — **FIXED** (D-127, 2026-09-28)

**Defect #5 is FIXED to production grade.** The `by-sign-only` classifier was replaced with an
explicit opposition predicate plus a real `flat` state, per the canonical **`AGENTS.md` §22
Resolution Finding #10** rule (*a neutral signal is not evidence for either direction; CONFLICTED
only on genuine opposition among NON-neutral signals*):

```python
    all_flat = all(value == 0 for value in values)
    divergent = any(value > 0 for value in values) and any(value < 0 for value in values)
    confidence = breadth.divergent if divergent else breadth.convergent
```

`_breadth_direction_sentence` grew from 3 → **4 arguments** (`all_positive, all_negative, all_flat,
divergent`) and now returns `"flat: all three measures at zero…"` on the flat path and
`"convergent: measures agree on the sign of the readings that moved"` on the partial path. The
docstring/`assumptions`/`limitations`/`decision_prohibition` were updated to **forbid reading flat as
a conflict**. **MEASURED:** `(0,0,0)` → `flat`, conf **0.5** (was `CONFLICTED`, 0.3);
`(0,0,−0.3)` and `(0,0.2,0.3)` → convergent-partial, **0.5**; `(0.4,−0.2,0.3)` → still `CONFLICTED`,
**0.3**. The file had **NO mutation sweep**; a new one (`scripts/mutation_labor_breadth.py`, **19
mutants, 19/19 killed**) was created, and **5 new tests** were added in
`tests/models/test_labor_synthesis.py` (**48 pass**).

---

## CARD 24 — `src/macro_engine/models/ppi_pipeline.py` (352 lines, 1 public function)

**Purpose:** Module 5.4 — `ppi_pipeline_signal`: read the PPI **stage-of-processing** gradient
(crude → intermediate → final demand) and report whether cost pressure is *queued upstream* or
*already passing through*, plus the expected pass-through. Its defining habit is honesty about a weak
test: the module's own docstring opens by **measuring the specification's rule and reporting that it is
worse than a coin flip** (57/190 = 30.0% strict, 84/190 = 44.2% loose), then keeps the flag while
attaching its base rate (D-029). It is the file where the "flag, don't fix" discipline is most visibly
exercised.

**STATUS: ⚠️ DEFECT (Class C/F — two published fields contradict each other in a real input region,
against an invariant the module's own docstring states and its own test claims to enforce).** The
base-rate honesty, the `Literal` conversions, the five-state gradient and the confidence are all
verified correct.

**EVIDENCE:**

### ⚠️ (C/F) **DEFECT — `upstream_pressure_building=True` alongside `gradient_direction="no_clear_gradient"`**
The docstring, under `value["gradient_direction"]`, states a hard invariant:
> *"Strictly more informative than the boolean, and **never contradicts it: a `True` here implies
> `upstream_pressure_building` is `True`.**"*

Measured — an input region in which the two fields flatly contradict each other:
```
ppi_pipeline_signal(_inputs(crude=2.06, intermediate=2.05, final=2.04))
  upstream_pressure_building: True
  gradient_direction:         'no_clear_gradient'
```
The stages are **strictly descending** (2.06 > 2.05 > 2.04 — the specification's exact test, so the
boolean is correctly `True`), but every adjacent gap (`0.01`) is inside the configured
`inflation.pipeline_gradient_tolerance_pp = 0.1`, so the **dead-band branch runs first** (line 228) and
reports `no_clear_gradient`. The measured contradiction set is
`{strictly descending AND |c−i| ≤ tol AND |i−f| ≤ tol}`; a fine sweep over that region found **9 of 25
candidate points** producing the contradiction (all points with both gaps ≤ 0.1).

**Why this is a defect and not a disclosed design choice.** The two fields are *not* in a
parent/child relationship — the caller cannot resolve them. `upstream_pressure_building=True` says a
gradient exists; `gradient_direction="no_clear_gradient"` says none does. And unlike every other
tension in this file, **no warning is emitted for this pair**: measured, the warnings on the
`(2.06, 2.05, 2.04)` call are the four standing disclosures plus the `stage_spread` note — nothing
names the disagreement between the two published fields. The module warns when the margin assessment
contradicts the gradient (line 274), so the omission is inconsistent with the file's own standard,
not a deliberate silence. `docs/DECISIONS.md` (line 1568) confirms the *intent* was coexistence, not
contradiction — *"without altering the specification's boolean, which is still computed and still
reported verbatim"* — but coexistence was never supposed to mean mutual contradiction.

**The test that claims to enforce the invariant does not reach the violating region.** There **is** a
test, `test_gradient_direction_never_contradicts_the_boolean` (`tests/models/test_ppi_pipeline.py:94`),
whose docstring says *"`building_upstream` implies the boolean is `True` — checked both ways"* and whose
body asserts the **biconditional** `(direction == "building_upstream") == building`. But its five cases
are `(5,3,1) (1,2,3) (3,1,2) (1,3,2) (2,2,2)` — **every adjacent gap is ≥ 1.0pp**, i.e. ≥ 10× the
tolerance. Not one case lands inside the dead band, which is the *only* region where the biconditional
fails. So the test passes while the defect stands: a **Class-H coverage gap** masked by a
**Class-C assertion gap** (the invariant is asserted over a sample that cannot falsify it). The
`non_monotonic`/`no_clear_gradient` fixtures that *do* exist (`test_exact_tie_is_no_clear_gradient`
line 362, `test_separation_exactly_at_the_tolerance_is_no_clear_gradient` line 369) only assert
`upstream_pressure_building is False`, so they never confront the `True`/`no_clear_gradient` pair.

**FIX (concrete):**
1. Pick one of two honest resolutions and make the output say it:
   - **(preferred) Keep both fields but make the dead band not contradict the boolean**: when the
     ordering *is* strictly monotonic, report the ordering (e.g. a fourth state `building_within_tolerance`
     or `building_upstream_below_tolerance`) instead of `no_clear_gradient`, so the direction states the
     measured sign and the tolerance is expressed as a *confidence qualifier*, not as a denial that an
     ordering exists. This preserves the specification's boolean and the docstring's invariant together.
   - **Or, if `no_clear_gradient` must win**, then `upstream_pressure_building` must be reported as
     `False` in that region (or renamed/qualified, e.g. a third field `strict_ordering_holds`), and the
     docstring's "never contradicts" sentence must be deleted and replaced with the actual rule.
2. **Add the contradiction warning unconditionally**, mirroring the margin-vs-gradient warning at line
   274, so any residual tension between the two fields is named in the output rather than left for the
   reader to spot.
3. **Close the test gap**: extend `test_gradient_direction_never_contradicts_the_boolean` with cases
   *inside* the dead band — at minimum `(2.06, 2.05, 2.04)` and a both-gaps-at-exactly-`tol` case — so
   the asserted biconditional is exercised over the region that can falsify it. The existing
   `test_float_subtraction_cannot_build_a_boundary_fixture` already documents *why* such a fixture must
   be built by addition from zero, so the pattern to follow is in the file.
4. Add a mutation for this exact pair (a mutant that forces `no_clear_gradient` whenever the ordering is
   monotone) — the sweep has `M4e`/`M5b` for adjacent gaps and the warning, but nothing that would kill
   a mutant collapsing the tolerance region into a contradiction.

### (A) MATH & REASONING — PASS (every docstring claim re-measured)
- **Both hand calculations reproduce exactly.** `(13.06, 11.53, 5.41)` →
  `upstream_pressure_building True`, `stage_spread_pp +7.65`, `expected_pass_through "fuller"`,
  `gradient_direction 'building_upstream'` — matching the docstring's `+7.65pp` / `"fuller"` line for
  line. `(1.00, 2.00, 3.00)` → `False`, `spread −2.00`, `'passing_through_downstream'` — matching the
  reversed case's stated result, including the docstring's insistence that pass-through "depends only on
  the two assessments, NOT on the gradient". ✔
- **The base rates match their config leaves and the divisors are self-consistent.**
  `strict_descending_rate = 0.3` (`57/190 = 0.3`) and `crude_above_final_rate = 0.442`
  (`84/190 = 0.44210…` → `0.442`) — the docstring's `30.0%` / `44.2%` and the per-190-month window are
  both reproduced from `settings.inflation.pipeline_base_rate`. Both leaves carry
  `calibration_status='fitted_assumption'` with a note explaining *why* ("a property of THESE three
  series over THIS window, not a constant of the economy") — the correct provenance for a measured
  base rate, and the direct D-029 remedy. ✔
- **Pass-through is genuinely binary and independent of the gradient — measured over the full 3×3
  assessment grid.** All nine `(margin, demand)` combinations match the `muted`-iff-(weak OR
  compressing) rule (and the parametrized test at line 129 pins all nine). The docstring's claim that a
  rising gradient with weak demand still reports `muted` is a **real regression test**
  (`test_pass_through_ignores_a_building_gradient`, line 152) using the live readings — the mechanism
  (margin absorption breaks the PPI→CPI link) is protected, not merely described. ✔
- **The dead-band wording is right even where the boolean interplay is not.** "the sum of absolute
  adjacent gaps is the right width to compare against" is implemented as
  `abs(crude−intermediate) <= tol and abs(intermediate−final) <= tol` (line 228) — a conjunction of the
  two adjacent gaps, so a gradient exists only if both separations clear the band. That is the correct
  predicate for "no ordering to speak of"; the defect is the *label* it produces, not the test.
- **`non_monotonic` is correctly identified as the most common real outcome** and warned as such
  (line 294), with the right instruction ("treat as 'no signal' rather than resolving it by ignoring
  whichever stage disagrees"). Consistent with the module's whole posture.

### (C) INPUT WIRING — PASS (the file's best engineering)
- **The two free-`str` fields were converted to `Literal`, and this is a real Class-C fix, correctly
  diagnosed.** `MarginTrend = Literal["expanding","stable","compressing"]`,
  `DemandCondition = Literal["strong","neutral","weak"]` (lines 108–109). The module docstring states
  the exact failure it prevents: a caller passing `"Compressing"`/`"compress"`/`"tight"` "falls through
  every equality test and lands in the `else` branch as `"fuller"` pass-through — an optimistic answer
  manufactured by a typo." Measured: `pass_through` reads `inputs.demand_condition == "weak" or
  inputs.corporate_margin_trend == "compressing"` (line 238), so an unconstrained misspelling would
  indeed default to the *optimistic* `fuller`. The `Literal` makes it a construction error. This is the
  **D-045a "a `Literal` is a promise with two halves"** discipline applied where `extra="forbid"`
  structurally cannot reach (the field *is* provided, *is* a string). ✔
- `PipelinePassThrough = Literal["muted","fuller"]` — and the module **argues against** inventing a
  third state ("inventing a middle state would imply a precision the margin input cannot support"). The
  declared set equals the emitted set (both branches assign one of exactly these two), so D-045a's
  second half holds. ✔
- `extra="forbid"` on `PPIPipelineInputs`; all five inputs are required with no defaults, so a missing
  stage is a construction error rather than a silently-zeroed gradient.
- **The D-009 pairing hazard is documented at the input, where it belongs**: the docstring warns that
  passing "each stage's own latest reading" pairs non-contemporaneous stages because `PPIFIS` begins
  2009-11 while `WPSID*` reach back to 1947. The three fields are "at the same observation date" — the
  alignment obligation is stated on the input contract. (Whether a caller *can* violate it is a real
  residual: the three fields are independent floats with no shared as_of, so alignment is enforced by
  convention, not structure. See OBSERVATION 2.)

### (D) DATA — PASS
- No numeric threshold is a bare literal in the model body: tolerance
  (`inflation.pipeline_gradient_tolerance_pp = 0.1`), both base rates, and the staleness horizon all
  live in config with `calibration_status`. The **only** literals are the `Literal` type aliases
  (permitted-value sets, not thresholds) and the `190`-month window, which appears **inside the
  config notes** describing the measurement, not as a model constant. ✔
- **The stage→series mapping is documented, justified, and records a dead end.** `PPICRM`
  ("crude materials for further processing", the obvious choice) was **discontinued by BLS after
  2015-12**; `WPSID62` is the live crude-stage equivalent. The mapping is in
  `config/series_registry.yaml` and exercised in `scripts/live_labor_check.py`. This is provenance done
  properly — a non-obvious substitution that is *named as a this-build choice* in a standing warning
  (line 262) rather than presented as a BLS identity. ✔
- **The base-year note is correct and load-bearing.** `WPSID*` are 1982=100, `PPIFIS` is Nov-2009=100;
  the module states that a base-year convention cancels in a same-series YoY ratio and that levels are
  **never combined** across stages. Verified: every input is used only in differences and comparisons
  (`crude − final`, `crude > intermediate`), never as a level sum or cross-stage ratio. ✔

### (E) INPUT-NOT-TAKEN — PASS
`inputs_used` lists all five fields, and all five are genuinely read: the three stages drive the boolean,
the spread and the gradient; `corporate_margin_trend` and `demand_condition` drive `pass_through` and
the contradiction warning. The `context` string names which two decide pass-through ("driven by
demand_condition=... and corporate_margin_trend=... alone, not by the gradient") — a taken-input
relationship made visible in the output. ✔

### (F) INTEGRATION — PASS (with the DEFECT's caveat)
- **No live caller yet within `src/`** — `grep` finds only a config-docstring reference
  (`config.py:1937`) and the module itself. So the DEFECT's blast radius today is bounded to any reader
  of the `value` dict; it is **not** currently propagated into the thesis. That lower severity is why
  this is ⚠️ rather than ☠, but the docstring promises an invariant a future consumer would rely on.
- `docs/DECISIONS.md` records a **32/32 mutation sweep** (`scripts/mutation_ppi_pipeline.py`) — I
  counted 35 mutant markers in the script (the record's 32 refers to the killed set; two first-sweep
  survivors became tests). The record names two survivors that were **real test gaps** (`M4e` dead band
  on one adjacent pair; `M5b` warning ignoring margin trend) and says both are now covered — accurate
  as far as it goes, but **neither survivor probes the boolean/direction contradiction**, which is why
  the DEFECT survived a 32/32 sweep. ✔ (sweep integrity) / ✗ (sweep coverage of this region)

### (G) CONFIDENCE — PASS
- `confidence = compute_confidence(ConfidenceInputs(is_heuristic_not_calibrated=True,
  depends_on_unobservable=True))` — measured **0.3** (base 0.7 − heuristic 0.2 − unobservable 0.2). Both
  penalties are correct under §22.8: `is_heuristic_not_calibrated` because the ordering test is
  uncalibrated and the two assessment fields are judgements; `depends_on_unobservable` because the
  margin trend "is not directly observed by this system at all (Section 21.4 item 10)". ✔
- The module docstring **explicitly replaces the specification's `confidence=0.4`** with the
  Ø22.8-compliant producer — a bare literal confidence eliminated, which is the class of fix this audit
  exists to catch. ✔
- **The judgement-vs-observation distinction is carried as a standing warning** (line 256) rather than
  left in the confidence number: one of five inputs "carries judgement reliability rather than series
  reliability … the two are not interchangeable." That is the §21.0 rule-4 substitution refusal, stated
  in the output. ✔

### (H) EVIDENCE — green suite, and one asserted invariant the suite cannot falsify
`pytest tests/models/test_ppi_pipeline.py -q` → **55 passed** (`--collect-only` → 55). Tests are strong
on boundary construction (the float-subtraction hazard is documented executably), pass-through
independence, `Literal` negative tests, and warning polarity. But
`test_gradient_direction_never_contradicts_the_boolean` asserts a biconditional its sample cannot
violate (all cases ≥1.0pp apart vs a 0.1pp band) — the single most important invariant in the file is
the one the suite tests vacuously. **This is the Class-H instance that let the Class-C DEFECT ship.**

**OBSERVATIONS (non-defects):**
1. **The `190`-month / `2010-11..2026-08` window is stated in prose in three places** (module docstring,
   base-rate warning, config note) but is not itself a config leaf or a computed value. If the series
   are re-pulled the window changes and the three statements must be updated by hand. Low priority (the
   *rates* are config-sourced; only the descriptive window is prose), but a `measured_window` leaf
   alongside the rates would make the disclosure un-driftable.
2. **D-009 alignment is documented rather than structural.** The three stage fields have no shared
   `as_of`, so a caller can still pair stages from different dates — the exact defect the docstring
   warns against. A composite input (`list[StageReading]` with per-reading dates, or a required
   `as_of`) would make it unrepresentable, as `ClaimsTrendInputs` did for the claims two-window hazard
   in Card 23. Worth considering when a live caller is wired.
3. **`gradient_direction` is a bare `str` in the dict**, not a `Literal`-typed value, even though the
   module already defines `PipelinePassThrough` as one. The four emitted states
   (`no_clear_gradient`/`building_upstream`/`passing_through_downstream`/`non_monotonic`) would be safer
   as a named `Literal` alias, consistent with this file's own idiom and with Card 22's observation.

---

### ✅ STATUS UPDATE — **FIXED** (D-127, 2026-09-28)

**Defect #6 is FIXED to production grade.** The dead-band guard no longer returns a bare
`"no_clear_gradient"`; it reports **which ordering the band contains**, so a `True`
`upstream_pressure_building` can no longer coexist with a direction that denies it (D-009 class F,
cross-field identity):

```python
    within_band = (
        abs(crude - intermediate) <= tolerance and abs(intermediate - final) <= tolerance
    )
    if within_band:
        gradient_direction = (
            "building_within_tolerance" if upstream_building else "flat_within_tolerance"
        )
    elif upstream_building:
        gradient_direction = "building_upstream"
    elif crude < intermediate < final:
        gradient_direction = "passing_through_downstream"
    else:
        gradient_direction = "non_monotonic"
```

The corrected invariant is **one-directional** (the biconditional is WRONG once a dead band exists):
`upstream_pressure_building is True` ⟹ `gradient_direction ∈ {building_upstream,
building_within_tolerance}`. Three warnings were added (general band resolution + one per band
resolution). **MEASURED:** `(2.06, 2.05, 2.04)` at `tol=0.02` → `building_within_tolerance` with the
boolean `True` (was `True` + `no_clear_gradient`). See also observation 3 above: the four old states
plus the two new in-band states remain bare `str` (a pre-existing idiom note, not part of this fix).
`tests/models/test_ppi_pipeline.py` rewritten/added (**57 pass**); `scripts/mutation_ppi_pipeline.py`
retargeted + 5 new mutants (**38/38 killed**).

---

## CARD 25 — `src/macro_engine/models/policy_rules.py` (1380 lines, 8 public functions)

**Purpose:** Module 4 — the Taylor-rule family (`taylor_rule`, `balanced_approach_rule`,
`first_difference_rule`), the ensemble (`policy_rule_ensemble`), the **single canonical model-vs-market
gap** (`canonical_policy_gap` + the `MarketPricingGap` class), the market-implied path proxy
(`derive_market_implied_policy_path`), the balance-sheet stance (`qe_qt_stance`, Module 4.1) and the
forward-guidance text diff (`statement_text_diff`, Module 4.3 — the D-125 function). It is the file
whose output decides whether the thesis sees a tradable policy gap at all, and it holds the tree's
**only** definition of that gap.

**STATUS: ⚠️ DEFECT (Class B/C — a published direction state names a movement that did not occur, in the
`statement_text_diff` code path that D-125 itself rewrote).** Everything else is verified correct: all
three rules' hand calculations, the ensemble bands, the canonical median/dispersion/significance test,
the `qe_qt` base rates and neutral-band correction, the D-078 non-finite guards, and the D-118
CAP-PRODUCT confidence.

**EVIDENCE:**

### ⚠️ (B/C) **DEFECT — `HAWKISH_TILT_WITH_DOVISH_REMOVALS` fires when dovish language was ADDED**
`statement_text_diff`'s direction naming is over **direction of movement**, and the two `_TILT_*` states
are documented to name *which side produced the tilt* — the docstring (lines 1278–1282) says the label
distinguishes *"a hawkish net built by dropping dovish phrases"* from *"one built by adding hawkish
ones"*. Measured, that distinction is **not** made:
```
prior   = '<pad>'                                                    # 0 dovish markers
current = '<pad> additional policy firming further tightening not expected to be appropriate'
          #  -> adds 2 hawkish, adds 1 dovish; provably NOTHING was removed (prior had none)

  hawkish_net:      +2
  dovish_net:       +1          <- dovish language ENTERED
  dovish_entered:   ['not expected to be appropriate']
  dovish_left:      []          <- EMPTY. No dovish phrase was removed.
  net_tilt:         +0.3333
  direction:        'HAWKISH_TILT_WITH_DOVISH_REMOVALS'   <-- asserts a removal that did not happen
```
The label says **DOVISH_REMOVALS** while the value dict on the same result says `dovish_entered=[…]` and
`dovish_left=[]`. A consumer reading `direction` is told the tilt came from *dropping* dovish phrases; a
consumer reading `dovish_left` is told nothing was dropped. The two published fields contradict each
other, and the `direction` state is the one the docstring says is the desk signal.

**Root cause.** The `tilt > 0` branch (line 1277) is reached whenever **both** wards are true and the net
is hawkish — i.e. for `(hk>0, dv>0)` *and* `(hk>0, dv<0)` *and* `(hk<0, dv<0 with |dv|>|hk|)`. It does
**not** check the sign of `dovish_net`, which is the only quantity that says whether dovish language was
added or removed. Measured, both of these produce the same label:
```
hk=+2, dv=+1  (dovish ADDED)   -> HAWKISH_TILT_WITH_DOVISH_REMOVALS   [dovish_entered non-empty]
hk=-1, dv=-2  (dovish REMOVED) -> HAWKISH_TILT_WITH_DOVISH_REMOVALS   [dovish_left  non-empty]
```
The mirror pair shows the same conflation for `DOVISH_TILT_WITH_HAWKISH_REMOVALS` (`hk=+1,dv=+2` →
labeled, hawkish **added**; `hk=-2,dv=-1` → labeled, hawkish **removed**). So **the two `_TILT_*` states
each cover two opposite movement patterns**, and the `_REMOVALS` half of the name is only true for one of
them. This is **D-045a's "a `Literal` is a promise with two halves"** violated on the *meaning* half: the
member is declared and producible, but the name it carries does not mean what it says for every input
that produces it. It is also the **exact failure mode D-125 corrected one level up** — D-125 fixed a
*reduction keyed on the wrong predicate* that "read a hawkish REMOVAL as MORE_HAWKISH" (the comment at
lines 1264–1266 records it); the `_TILT_*` labels retain the same class of error, keyed on `tilt` sign
instead of on which side was removed.

**Why the green suite and the 30/30 sweep did not catch it (Class-H).** Every existing fixture that
produces a `_TILT_*` state puts the *named* side in the **removal** direction, so the label is literally
true for all of them:
- `test_opposing_moves_with_a_hawkish_net_name_the_removal` (line 1173) uses `dovish_net == -2` — dovish
  **removed**. ✔ true for that fixture.
- `test_every_direction_is_reachable` (line 1213) builds both `_TILT_*` cases from "prior has markers →
  current has none" — i.e. removals on both sides. ✔ true for those fixtures.
`grep` for a fixture with `dovish_net > 0` **while** `hawkish_net > 0` (the addition mirror) → **none**.
So the suite proves every state is *reachable* but never proves each state *means* what it names. The
`scripts/mutation_statement_text.py` sweep (30/30) mutates the tilt formula, the ward booleans, the tie
branch and the counts — but **no mutant targets the label-selection predicate** (swapping the label for
"dovish added" vs "dovish removed"), because no test would kill one: the surviving distinction is
unobserved by the suite.

**FIX (concrete):**
1. **Split each `_TILT_*` state by the sign of the opposite side's net, or reword the states** so the name
   is true for every input that reaches it. Two options, both honest:
   - **Two more states** (preferred, preserving the movement information): `HAWKISH_TILT_FROM_DOVISH_REMOVALS`
     / `HAWKISH_TILT_FROM_HAWKISH_ADDITIONS` (and the dovish mirror), selected by `dovish_net < 0` vs
     `dovish_net > 0` inside the `tilt > 0` branch. This keeps the "phrase that MOVED is the signal"
     distinction the docstring promises.
   - **Or reword to a direction-neutral pair**: `HAWKISH_TILT_BOTH_DIRECTIONS_MOVED` /
     `DOVISH_TILT_BOTH_DIRECTIONS_MOVED`, dropping the `_REMOVALS` claim entirely. Cheaper, but loses the
     addition/removal distinction the module says it wants.
2. Whichever is chosen, drive the choice from the **sign of the opposite side's net** (the quantity that
   already exists on the value dict), not from `tilt` alone.
3. **Add the missing mirror fixtures**: a case with `hawkish_net > 0` **and** `dovish_net > 0` (both
   added) asserting the new/reworded direction, and its four-cell partner. At minimum, add an assertion
   that the state naming `_REMOVALS` is only ever emitted when the corresponding
   `dovish_left`/`hawkish_left` list is non-empty — the invariant the current name silently breaks.
4. Add a mutant to `scripts/mutation_statement_text.py` that flips the label-selection predicate (emit
   the `_REMOVALS` state regardless of which side moved), which the new fixtures must kill.

### (A) MATH & REASONING — PASS (all three rules hand-verified; §11.1's mandated test reproduced)
- **§11.1's mandated hand calculation reproduces exactly**: `taylor_rule(r*=0.5, pi=3.0, target=2.0,
  output_gap=+1.0)` → **4.5** (`0.5 + 3 + 0.5·1 + 0.5·1 = 4.5`). Config read from disk: `pi_target 2.0`,
  `inflation_gap_coefficient 0.5`, `taylor_output_gap_coefficient 0.5`. ✔
- **`balanced_approach_rule` differs only in the output-gap coefficient** (config
  `balanced_approach_output_gap_coefficient = 1.0`), and its stated divergence is **derived, not
  described**: measured context `"Weights the output gap 1x rather than 0.5x, so it diverges from Taylor
  by 0.5 x output_gap = +0.50pp"` for the same inputs (`5.0` vs `4.5` = +0.50). A config change to either
  coefficient moves the stated divergence, which is the right construction (no hardcoded 0.5·gap). ✔
- **`first_difference_rule` is arithmetically correct and `r*` genuinely cancels**:
  `i_prev=4.0, pi=3.0, target=2.0, Δgap=0.5, α=β=0.5` → `4.0 + 0.5·1 + 0.5·0.5 = 4.75`. ✔ The docstring's
  claim that this rule "needs only the previous policy rate … and the *change* in the output gap" is
  true of the signature (`FirstDifferenceInputs` has no `r_star` field), so the structural claim is
  enforced by types, not asserted.
- **The structural confidence gradient is real, not rhetorical.** Measured: `taylor_rule` **0.5**,
  `balanced_approach_rule` **0.5**, `first_difference_rule` **0.7**. The first two carry
  `depends_on_unobservable=True` (r*), the third `False` (r* cancels) — so "the higher number is earned
  by the construction, not asserted" (docstring) is measured exactly. ✔
- **Ensemble dispersion and the median are correct, and the median-vs-mean argument is realised.**
  `{4.5, 5.0, 4.75}` → `range [4.5, 5.0]`, `dispersion_pp 0.5` → `dispersion_bp 50.0` (the `_BP_PER_PP`
  conversion applied), `agreement "MIXED"`. Band check: `convergence_bp = 50.0`, `uncertainty_bp = 100.0`;
  a 50bp dispersion is **not** `< 50` and **not** `> 100`, so `MIXED` is correct at the exact boundary
  (strict comparisons, the right end behaviour). ✔
- **`canonical_policy_gap` computes the median correctly and the significance test is the real
  contribution.** Measured: `sorted {4.5, 5.0, 4.75} → median values[1] = 4.75`, `dispersion = values[2] −
  values[0] = 0.5`. With `market_implied = 4.0` → `raw_gap 0.75 > 0.5` → `is_meaningful True`,
  `direction "model_above_market"`. With `market_implied = 4.6` → `raw_gap 0.15 ≤ 0.5` →
  `is_meaningful False` while `direction` still reports `model_above_market` — correct: the *direction* of
  a sub-noise gap is still a fact, it is the *significance* that the dispersion gates. The median is
  robust to one outlier by construction (`values[1]`), which is the docstring's stated reason for
  preferring it over Taylor-alone or a mean. ✔
- **The `MarketPricingGap.direction` finite-fallthrough is correct and its history is recorded.** It is a
  `property` (not a stored field) precisely so it cannot disagree with `raw_gap` (D-076 shape), and the
  docstring records the pre-D-078 defect — a `nan` gap "satisfies neither `> 0` nor `< 0`" → fell to
  `aligned`, "a silent NO-TRADE manufactured from absent data". Measured: the field constraints
  (`allow_inf_nan=False`) plus the D-078 guards make `nan` unreachable, so the fallthrough is safe. ✔
- **`qe_qt_stance`'s neutral-band correction is correct and its base rates are measured.**
  `change_pct = change_3mo / level × 100` compared against `±neutral_band_pct`. Measured: `+2% → QE_EXPANDING`,
  `−2% → QT_CONTRACTING`, a tiny change → `NEUTRAL_HOLD`. The three stances are all reachable, which is
  the fix §20.4's `== 0` test failed (docstring: "over 1226 weeks … happened zero times"). Base rates
  measured `{QE_EXPANDING 0.4869, QT_CONTRACTING 0.3124, NEUTRAL_HOLD 0.2007}` over
  `observations_measured = 1226` — matching the docstring's **48.7% / 31.2% / 20.1%** to the stated
  precision. ✔
- **The relative band's reason is load-bearing and correct**: an absolute tolerance "would mean different
  things" across a `$0.7T`–`$9.0T` range, so `change_pct` normalises by the level. Verified the level is
  `gt=0.0` (it is the denominator), so the division cannot be by zero. ✔

### (C) INPUT WIRING — PASS (the guards are the file's strongest feature)
- **D-078's non-finite guards are uniformly present and correctly placed on the INPUT, not the output.**
  Measured: `taylor_rule(r_star=nan, …)` → `ValidationError` *"non-finite policy-rule input(s):
  r_star=…"* — naming the field. The `_FiniteInputs` base runs a `model_validator(mode="after")` over
  `model_fields`, so it covers every float on every subclass without repetition. The module's
  `_NON_FINITE_REMEDY` text explains *why input-side*: "a prescription of `nan` is the symptom … the
  rule's arithmetic has no way to distinguish 'the arithmetic went wrong' from 'the input was never a
  number'." Correct diagnosis and correct placement. ✔
- **`derive_market_implied_policy_path` guards both inputs and states the subtraction-specific hazard**:
  the docstring and the raise message both note that `short_tenor_term_premium=inf` "can **flip the
  sign**" of the adjusted path (measured pre-fix `→ -inf`). This is the more dangerous non-finite case
  (propagation that inverts), and it is guarded explicitly rather than relying on the generic base. ✔
- **`StatementTextInputs._reject_blank_text` refuses a blank statement (D-054)** with the right reasoning
  — "an empty statement is not a statement that says nothing — it is one that was not retrieved, and
  diffing against it would report every marker as newly entered". Measured: a blank raises. Plus the
  `min_tokens` floor (config = 1; the mechanism is present and config-driven) guards a truncated
  retrieval. ✔
- **The `Literal` vocabularies are closed**: `QEStance` (3 members) and `StatementDiffDirection`
  (6 members) are `Literal` aliases, and all members are reachable (measured: 3/3 stances, 6/6
  directions). D-045a's first half satisfied. **The second half is the DEFECT above for two of the six.**
- **`resolved_*` properties centralise the config fallback** (`pi_target`, `alpha`, `beta`) so a `None`
  means "use config" in exactly one place. `r_star` has no fallback and none is wanted (it is an
  unobservable input the caller must supply), which is consistent.

### (D) DATA — PASS
- Every coefficient, band, base rate and threshold is a config leaf: `policy.pi_target_value`,
  `policy.rules.{inflation_gap_coefficient,taylor_output_gap_coefficient,first_difference_alpha,
  first_difference_beta}`, `policy.balanced_approach_output_gap_coefficient`,
  `policy.ensemble.{convergence_threshold_bp,uncertainty_threshold_bp}`, `qe_qt.{neutral_band_pct,
  rrp_drained_threshold_bn,base_rates}`, `statement_text.{min_tokens,confidence_cap,hawkish_markers,
  dovish_markers,vocabularies_are_calibrated}`. Measured all of them; none mismatched.
- The two module constants are argued as **unit conversions, not judgements**: `_BP_PER_PP = 100.0`
  ("making the conversion a named constant means the comparison cannot be made between mismatched units,
  which would be a silent factor-of-100 error in the one place the system judges whether policy rules
  agree") — a real risk, correctly closed. The `MarketPricingGap.unit` default `"%"` is a unit label.
- **Provenance is explicit about the unobservable**: `data_provenance` states "r_star is config-sourced
  … and is itself UNOBSERVABLE; both rules inherit that", and that the market leg is *not* part of this
  result but combined in `canonical_policy_gap`. The pipeline's seam is documented on the value.
- `qe_qt_stance` publishes `observations_measured` (1226) alongside `stance_base_rate`, so the base rate
  is auditable from the output (D-029).

### (E) INPUT-NOT-TAKEN — PASS (and this is where the file fixes a prior Class-E defect)
- **The D-037 defect §20.4's sample shipped is corrected here, and the correction is documented.**
  `BalanceSheetInputs`' docstring records that the specification "declares `balance_sheet_level` and
  `reserve_balances` as inputs, lists them in `inputs_used`, and then reads **neither** — the stance is
  decided by one number while the output claims three." Measured: the corrected function **does** read
  both — `balance_sheet_level` is the denominator of `change_pct`, and `reserve_balances` drives
  `reserves_draining = reserve_balances_change_3mo < 0` and the scarcity warning. `inputs_used` lists all
  five and all five are genuinely consumed. ✔ This is a Class-E defect found and fixed, exactly the
  audit's target class.
- The consumer-facing prohibition list on the ensemble ("MUST NOT be read as a single 'model view' with
  the dispersion as noise") and on the market path ("MUST NOT be compared against a value produced by the
  OTHER branch without checking which branch ran") are the §21 "cannot say I don't know → will fabricate"
  discipline applied to consumption.

### (F) INTEGRATION — PASS
- `MarketPricingGap` is the **single** definition, and the class docstring records the D-064 collapse of a
  duplicate in `thesis_layer/schemas.py` (same fields, different noise-floor field name
  `rule_dispersion` vs `dispersion`) that had made the canonical producer unable to feed
  `build_scenario_distribution` — the same O-51 shape as `ScenarioOutcome`. The thesis layer now
  re-exports this class ("the `EvidenceSourceFamily` pattern"). So the canonical gap and the thesis
  consumer are structurally one object. ✔
- `policy_rule_ensemble.confidence = min(taylor, balanced, first_diff)` — measured **0.5** for a
  `{0.5, 0.5, 0.7}` input set, i.e. the minimum. `min()` here is *correct* (a summary cannot exceed its
  weakest part) and is explicitly distinguished from the `compute_confidence` producer in a comment — the
  right call, and **not** the D-118 `min()` error (that error is about replacing the computed half with a
  cap in a *product*, a different construction). ✔
- The ensemble and canonical gap both **refuse a non-numeric rule value** with a `TypeError` naming the
  variant — measured branch present. This prevents a `PolicyRuleResult` whose `value` was mutated to a
  string from silently entering `min()/max()`. Defensive and correct (the comment explains why it is
  narrowed per-value rather than in a bulk `all()` — for mypy).

### (G) CONFIDENCE — PASS (the D-118 CAP-PRODUCT rule is applied correctly here)
- **`statement_text_diff` is the D-118/D-125 CAP-PRODUCT site and it is correct.** Measured:
  `confidence = round(computed * cap, 3)` with `computed = 0.5`, `cap = 0.35` → **0.175**. Both halves are
  published on the value dict (`confidence_computed`, `confidence_cap`), so the number is recomputable
  from the output (D-009) — the docstring states publishing the cap alone "would leave the reader unable
  to tell a dead computed half from a live one". The comment explicitly rejects `min()` because "the
  computed value sits above it — which it does here (0.50 against a 0.35 cap), making the whole
  `compute_confidence()` half DEAD CODE" — the exact D-118 diagnosis, measured true. ✔
- `is_heuristic_not_calibrated = not settings.vocabularies_are_calibrated` reads the config leaf rather
  than asserting the flag (measured `vocabularies_are_calibrated = False` → penalty applied), and
  `source_independence_count = 0` ("one institution's own text, diffed against its own prior text") —
  correct on both.
- `qe_qt_stance`'s confidence is `compute_confidence(...)` with `is_heuristic_not_calibrated =
  not _qe_stance_calibrated()` reading `settings.is_calibrated("qe_qt.neutral_band_pct_value")`, and
  `source_independence_count = 0` ("one provider, one institution's own reporting") — measured **0.5**.
  The `_qe_stance_calibrated()` accessor centralises the config path, consistent with the file's pattern.
- No bare-literal confidence anywhere; §22.8's "`compute_confidence()` is the only legal producer"
  holds except the two **declared** exceptions (`derive_market_implied_policy_path`'s two config-read
  branch confidences, and `policy_rule_ensemble`'s `min()` of already-computed values) — both argued in
  comments as properties of the specific construction, not two settings of one factor.

### (H) EVIDENCE — green suite, and the DEFECT's fixtures are all one-sided
`pytest tests/models/test_policy_rules.py -q` → **81 passed** (`--collect-only` → 81). Coverage is
genuinely strong — the §11.1 hand calc, the six-direction reachability enumeration, the exact-cancellation
tie branch (mutation D4a), the D-078 non-finite rejections, the CAP-PRODUCT confidence and its
load-bearing-cap test (D-050), and the `qe_qt` three-stance reachability. **But every `_TILT_*` fixture
produces the state via the named side's *removal*, so no test confronts the addition mirror** — the
Class-H gap that let the DEFECT ship. `scripts/mutation_statement_text.py` (30/30) mutates the tilt
formula, wards, tie branch and counts, but **no mutant targets label-selection by which side moved**, so
the sweep cannot see it either.

**OBSERVATIONS (non-defects):**
1. **`PolicyRuleResult.rule_variant` is a bare `str`** with the permitted set (`"taylor_1993"` |
   `"balanced_approach"` | `"first_difference"`) in the description, not a `Literal`. Unlike
   `StatementDiffDirection`/`QEStance` in the same file, a typo here would not be a construction error.
   The docstring's point (carrying the variant so consumers need not string-match `model_name`) is well
   taken; a `Literal` alias would complete it, consistent with the file's own idiom.
2. **`derive_market_implied_policy_path`'s confidence is read from config, not `compute_confidence()`**
   — a declared §22.5 exception, correctly disclosed, but it means the two branches' confidences are not
   comparable to any `compute_confidence()` value. The `data_provenance` says exactly this ("the two
   branches are deliberately different qualities, not two settings of one factor"), so it is disclosed
   rather than hidden — noted only because it is the kind of divergence a reader must be told about.
3. **The live-path disclosure is carried only in warnings, not a field** — the no-term-premium branch's
   `value` is identical in shape to the adjusted branch's, so a consumer reading only `value` cannot tell
   which ran (the docstring admits this and calls it "by design"). The mitigation is that the *prose
   limitations* and the confidence differ. A boolean `term_premium_applied` on the value dict (the same
   D-009 "recomputable from the output" habit used for `statement_text_diff`'s confidence halves) would
   make it structurally visible; worth considering, low priority as the disclosure is explicit.

---

### ✅ STATUS UPDATE — **FIXED** (D-127, 2026-09-28)

**Defect #7 is FIXED to production grade.** The `elif tilt > 0:` / `elif tilt < 0:` guards read only
the **net**; the label asserted which way the OTHER side moved without reading that side's own net
sign (the **D-125 class**). Each tilt state is now split by the sign of the opposite side's net:

```python
    elif tilt > 0:
        direction = (
            "HAWKISH_TILT_WITH_DOVISH_REMOVALS"
            if dovish_net < 0
            else "HAWKISH_TILT_WITH_DOVISH_ADDITIONS"
        )
    elif tilt < 0:
        direction = (
            "DOVISH_TILT_WITH_HAWKISH_REMOVALS"
            if hawkish_net < 0
            else "DOVISH_TILT_WITH_HAWKISH_ADDITIONS"
        )
```

`StatementDiffDirection` grew **6 → 8 members** (both `..._ADDITIONS` states added), satisfying
**D-045a** ("a `Literal` is a promise with two halves" — the new members are PRODUCIBLE per the live
check and now MEAN what they name). **MEASURED:** the exact reproduced fixture
(`hk+2, dv+1, tilt +0.3333`, `dovish_left=[]`, `dovish_entered=['has eased']`) now reads
`HAWKISH_TILT_WITH_DOVISH_ADDITIONS` (was `..._REMOVALS`). The Class-H gap is closed: the *addition
mirror* is now fixture-covered (`test_opposing_moves_with_a_dovish_addition_say_additions_not_removals`,
`..._with_a_hawkish_addition_...`), `test_every_direction_is_reachable` asserts against
`set(get_args(StatementDiffDirection))` (**all 8**), the live check covers all 8, and the sweep gained
**D4c/D4d/D4e/D4f** — label-selection-by-which-side-moved mutants the old 30 could not see
(**34/34 killed**; `tests/models/test_policy_rules.py` **83 pass**).

---

## CARD 26 — `src/macro_engine/models/__init__.py` (53 lines, 0 functions)

**Purpose:** Package marker for the models layer. Its only content is a module docstring that states the
layer's **single structural rule** — *"models do not fetch data"* — and carries the Module→File map.

**STATUS: CLEAN.** No code, no imports, no `__all__`, no side effects.

**EVIDENCE:**

### (A–H) ALL CLASSES — PASS, vacuously for A/B/E/G and meaningfully for C/D/F
- **No executable code at all.** Measured: `grep -n "^import\|^from"` → **empty**; the file is a
  docstring and nothing else. So there is no arithmetic (A), no reasoning (B), no input wiring (C), no
  confidence (G), and no input-not-taken surface (E).
- **The stated rule is the one worth stating, and it is enforced elsewhere.** "Nothing here holds a
  provider URL, a symbol, or an HTTP client" is the property that makes §21.2 Step 6 (real-data
  execution) meaningful, and it is enforced by the model files rather than by this docstring — every
  input model is a `BaseModel` with typed fields and no client. The docstring is a correct statement of a
  real invariant, not an aspiration.
- **The two-tier STUB/IMPLEMENTED description is accurate against the tree.** Verified in this audit:
  `grep` for live `NotImplementedError` in `src/` finds only **refusals** (the X-A cross-cutting finding),
  so no path is still a STUB — the docstring describes a status system that has since been fully
  discharged. Consistent, not stale.
- **The Module→File map matches reality for every row it lists.** Spot-checked the rows that matter:
  `bond_math.py` (Module 2), `national_accounts.py` (3), `inflation_dynamics.py` (3.3 *and* 5.6 — the
  map lists it twice, correctly), `production_function.py` (3.5), `policy_rules.py` (4),
  `inflation_nowcast.py` (5.1), `ppi_pipeline.py` (5.4), `labor_synthesis.py` (6), `gdp_nowcast.py`
  (7 *and* 7.1 — listed together, correct), `yield_curve.py` (8), `risk.py` (17–18), plus the two
  cross-cutting modules `as_of.py` and `contracts.py`. Every listed path exists; every module number I
  verified in this audit matches the file the map names. ✔
- **The map is deliberately partial, and that is correct.** It omits the Tier-5-only modules
  (`commodities.py`, `fx_carry.py`, `econometrics.py`, `regime.py`, `em_vulnerability.py`,
  `intervention.py`, `equity_macro.py`) and the Phase-0–4 files whose module number is a sub-module of a
  listed file (`convergence.py`, `credit_spread.py`, `auctions.py`, `real_policy_rate.py`,
  `probability.py`, `scorecard.py`, `evidence.py`, `evidence_family.py`, `financial_conditions.py`,
  `lei_proxy.py`, `inflation_convergence.py`, `inflation_trajectory.py`, `instrument_selection.py`). It
  is labelled "Module map, as implemented" and reads as a router, not an exhaustive index — the
  fine-grained index lives in `AGENTS.md` §21.3, which is the authority. No drift claim is made by the
  header that the body does not support.

### OBSERVATIONS (non-defects)
1. The map's partiality means a reader cannot use `models/__init__.py` alone to find, e.g.,
   `real_policy_rate` or `scorecard`. That is by design (the layer map routes to the *big* modules), and
   the docstring does not overclaim — noted only so a future reader is not surprised. Adding a final
   line pointing at `AGENTS.md` §21.3 as the complete index would cost nothing.
2. `models/__init__.py` exporting nothing means every import is deep
   (`from macro_engine.models.policy_rules import …`) rather than
   `from macro_engine.models import …`. This is the same "no re-export facade" choice the layering
   expects (it keeps import cycles impossible by construction) and is consistent across the tree.

---
