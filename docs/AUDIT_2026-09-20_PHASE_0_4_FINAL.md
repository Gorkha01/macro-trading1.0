# PHASE 0 → PHASE 4 FINAL AUDIT — REPORT

**Repository:** `C:\Users\Hp\Documents\macro` — Global Macro Reasoning Engine
**Date:** 2026-09-20 · **Decision record:** `docs/DECISIONS.md` **D-074**
**Live service:** `http://127.0.0.1:6901` (never `:6900`)

**Constraints honoured:** no architecture rewrite · `AGENTS.md` unchanged · no
Phase 5+ implementation · no new features · no duplicate `FRED_API_KEY`
requirement · validation standards never lowered · no unavailable data replaced
with plausible numbers · no economic reasoning changed to produce more trades.

---

## 1. Defects found

Four defects. Every one was **invisible to the existing gates**, and every one
was a **missing-data conversion** — the exact class the directive forbids.

| # | Defect | Class | Severity |
|---|---|---|---|
| 1 | Non-finite (`nan`/`±inf`) values passed **every** gate and reported **CLEAN** | missing-data | **CRITICAL** |
| 2 | One `nan` FCI component silently inverted the composite verdict | missing-data | **CRITICAL** |
| 3 | Provenance recorded the **configured preference** instead of the **serving path** | source identity | HIGH |
| 4 | Config pointed at `:6900` against an explicit "do not use `6900`" | deployment | MEDIUM |

### 1.1 Non-finite values passed every gate (CRITICAL)

Three library defaults conspired:

- `pandas.dropna()` removes **nulls**, not `±inf`.
- Pydantic's `float` annotation accepts `nan` and `inf` **by default**
  (`allow_inf_nan=True`).
- The plausibility check is **made of comparisons** — and `nan < min`,
  `nan > max`, `nan == x` are **all `False`**. **A `NaN` passes a bounds check by
  failing to fail it.**

Measured consequence: a poisoned series was reported **CLEAN**. `+inf`/`-inf`
were caught only when the series carried a `plausible_range`, and **2 of the 45
registered series carry none** — in those two, a poisoned value was entirely
invisible.

**Reachability proved end-to-end:** provider response → normalisation → 
`ObservationPoint` → `MacroDataSnapshot` → a transform formatting `inf` into a
result.

### 1.2 One `nan` component inverted the FCI (CRITICAL)

`compute_fci` computes `fci = sum(contributions.values())`. `sum()` **propagates
`NaN`** without raising. The next line, `tighter_than_average = fci > 0.0`,
evaluates `NaN > 0.0` → **`False`** — so the model reported *"financial
conditions are looser than average"* **invented from absent data**. This is
precisely the forbidden `missing → False` conversion, and it is undetectable by
inspection because both branches are valid-looking booleans.

Separately, `FCIComponent.std = inf` was accepted, and `z = (x - mean)/inf` →
**`0.0`** — an invented "exactly average" observation.

### 1.3 Provenance recorded the preference, not the path (HIGH)

`_normalize` derived `source` from `self.config.use_local_api_first`. On a
cross-path fallback (preferred `:6901` fails, in-process package answers), the
frame was still labelled `openbb:http://127.0.0.1:6901` — **a fabricated
transport fact**. Provenance is evidence; a wrong provenance label is a
fabricated one.

### 1.4 Config pointed at `:6900` (MEDIUM)

Measured: **both `:6900` and `:6901` served identical live instances** — an
ambiguity, not an outage, which is why nothing had failed visibly.

---

## 2. Defects fixed

Each fix carries a **RED → GREEN regression test**.

### Fix 1 — four layers of defence (any one can be bypassed by another route)

1. **Normalisation** (`data_layer/openbb_client.py`) — `_is_non_finite()` drops
   non-finite rows with a logged warning **before** the empty-frame raise. An
   entirely-non-finite series now correctly becomes `EMPTY_SERIES` /
   `FETCH_FAILED` rather than a successful snapshot.
2. **Schema** (`data_layer/schemas.py`) — `ObservationPoint.value` is now
   `Field(allow_inf_nan=False)`. This is the load-bearing guard: it also covers
   the **rehydration** path (`snapshot_from_long_frame`) which never passes
   through normalisation.
3. **Snapshot** (`data_layer/snapshot_builder.py`) —
   `snapshot.assert_finite()` runs after validation and **before** persistence,
   raising a `ValueError` naming every offending `field[index]=value (series_id)`.
4. **Validation** (`data_layer/validation.py`) — a `NON_FINITE_VALUE`
   `Severity.ERROR` finding is emitted as the **first** check in the point loop,
   with a detail string stating *why* it must be first: every subsequent check
   is a comparison, and `NaN` compares `False` to all of them. An auditor now
   sees the poison **named**, not a clean tick.

### Fix 2 — schema + point of use

- `FCIComponent.value` / `.mean` gained `allow_inf_nan=False`.
- `.std` gained **both** `gt=0.0` and `allow_inf_nan=False` — a zero or negative
  standard deviation is not a small dispersion, it is an undefined z-score.
- `compute_fci` now checks `isfinite(z)` **per component at the point of use**,
  necessary because a component may arrive via `model_construct()` or a cache
  and therefore never face field validation.

### Fix 3 — mandatory keyword-only parameter

`_normalize(raw, series_label, *, served_by: str)`. `served_by` names the path
that **actually answered**; `_fetch_via_local_api` passes `_PATH_LOCAL_API`,
`_fetch_via_package` passes `_PATH_PACKAGE`. The parameter has **no default**,
deliberately: a silent default would reintroduce exactly the bug, so the type
system now refuses the call without it. Mutation-verified — reverting the fix
kills 3 tests.

### Fix 4 — repinned to `:6901`

`config/settings.yaml`, `src/macro_engine/deployment.py`, and the client
docstring. The 2026-09-20 measurement is recorded in the config note so a later
reader does not "restore" the old value.

---

## 3. Reasoning / logic corrections

Three **reasoning** corrections, all of the same shape: *a computed float was
reduced to a boolean without first proving the float existed.*

1. **`fci > 0.0` is not a two-valued function when the input can be `nan`.**
   The comparison returns a valid-looking `False`, so *"the composite is missing"*
   and *"conditions are tighter"* were **indistinguishable in the output**. The
   correction is to prove finiteness **before** reducing to a boolean.

2. **A range check must test finiteness, not magnitude.** The original check
   asked *"is this value inside the bounds?"* — a question `NaN` answers `False`
   to. The corrected check asks *"is this value a number at all?"* **first**, and
   only then asks about its magnitude.

3. **Provenance is a receipt about the past, not a statement of intent.** The
   label must be written by the code that **observed** the transport, never
   reconstructed from the configuration that **requested** it. The two coincide
   only when nothing falls back — i.e. exactly when the label is least needed.

**Economic-reasoning audit:** all ten directive questions were applied to the
implemented calculations. The live run confirmed the reasoning is sound — see
§6. Notably, the FCI defect was an *economic-reasoning* defect as much as a code
defect: it published a **direction of financial conditions** derived from no
observation at all.

---

## 4. Missing-data corrections

The directive's binding rule: *never convert missing data into `0`, `False`,
neutral, unchanged, empty-but-successful or an invented default.*

| Site | Before | After |
|---|---|---|
| `ObservationPoint.value` | `nan`/`inf` accepted as a value | rejected (`allow_inf_nan=False`) |
| Snapshot build | poisoned snapshot persisted | `assert_finite()` raises before persistence |
| Validation report | poisoned series reported **CLEAN** | `NON_FINITE_VALUE` **ERROR** |
| Normalisation | `inf` survived `dropna` | dropped with a warning; all-poisoned → `EMPTY_SERIES` |
| `FCIComponent.mean` | `nan` accepted | rejected |
| `FCIComponent.std` | `inf` accepted → `z = 0.0` (invented neutral) | rejected (`gt=0.0`, finite) |
| FCI composite | `nan` → `False` ("looser than average") | `ValueError` naming the component |
| `_normalize` `source` | wrong transport on fallback | names the serving path |

**No missing value is now converted to a default anywhere on these paths.** The
honest outcomes `BLOCKED` / `INSUFFICIENT_DATA` / `NO TRADE` remain available and
are exercised.

---

## 5. Tests added

**+29 tests, across three new files, zero regressions** (2329 → 2358 passed).

| File | Tests | Covers |
|---|---|---|
| `tests/data_layer/test_non_finite_values.py` | 14 | `ObservationPoint` non-finite rejection; `assert_finite` via `model_construct`; `NON_FINITE_VALUE` flag with and without bounds; **`dropna` does not remove `inf`** (pinned); normalisation drops poisoned rows; all-poisoned → empty frame |
| `tests/models/test_fci_non_finite.py` | 9 | `FCIComponent.value`/`.std` non-finite rejection; z-score always finite; documents that **`sum` propagates `NaN`** and **`nan > 0` is `False`** |
| `tests/data_layer/test_provenance_path.py` | 6 | `source` labels the **serving** path; two paths distinguishable; label independent of the preference flag; `served_by` is **keyword-only with no default** |

One existing file updated: `tests/data_layer/test_phase1_data_layer.py` (two
`_normalize` call sites now pass `served_by`).

**Test-audit findings:** no test passes only because another test populated a
cache first; an empty/unavailable dataset fails explicitly; the one skip is
**pre-existing** and Phase-5-gated (`tests/models/test_output_gap.py:255`),
documented, not introduced here.

---

## 6. Live-data evidence — `http://127.0.0.1:6901`

### Snapshot

```
fields populated : 22
fields failed    : 0
is_complete      : True
assert_finite()  : PASS
validation       : 2 INFO, 0 WARNING, 0 ERROR
```

| Series | Value | Observation date | Release |
|---|---|---|---|
| `cpi_headline` | 334.131 | 2026-08-01 | 2026-09-11 |
| `cpi_core` | 337.765 | 2026-08-01 | — |
| `pce_core` | 130.658 | — | — |
| `unemployment_rate` | 4.1 | — | — |
| `fed_funds_rate` | 3.63 | — | — |
| `gdp_real` | 24269.613 | — | — |
| `gdp_potential` | projected to 2036-10-01 | forward-dated CBO | withheld + flagged |
| `sofr` / `iorb` | 3.85 / 3.90 | — | corridor intact |
| `credit_spread_hy` / `ig` | 2.70 / 0.78 | — | ordering intact |

Two INFO findings, both correct-and-declared: `FORWARD_LOOKING_HORIZON` (CBO
projections) and `SAME_DAY_PUBLICATION_AHEAD_OF_CLOCK`.

### Yield curve

```
10YR-2YR slope     : +27.0 bp   (positive — normal)
5yr  breakeven     :  2.32%
7yr  breakeven     :  2.34%
10yr breakeven     :  2.33%
20yr breakeven     :  2.45%
30yr breakeven     :  2.25%
```

### Thesis — the headline result

```
status      : WATCH
convergence : NO_SIGNAL
instrument  : NONE
direction   : n/a
warnings    : 11
gap         : 0.26    dispersion : 0.86
Q6          : No trade [gap_below_dispersion]
```

**This is a correct `NO TRADE`.** The gap (0.26) sits **inside** the policy
rules' own dispersion (0.86), so Q6 stands the trade down — the system declined
to manufacture a view from a gap it cannot distinguish from its own noise.

That is the audit's intended result:

> **real data → correct calculation → correct economic interpretation →
> traceable reasoning → honest uncertainty** — *including when the honest answer
> is to do nothing.*

### Vintage — the prescribed route does not exist (negative finding)

The directive prescribed:
`economy/fred/series_vintages` → `economy/fred/series?realtime_start=…&realtime_end=…`
→ manual `df["vintage_date"]`. **Measured against this deployment:**

| Probe | Result |
|---|---|
| OpenAPI paths on `:6901` | 278 operations; **zero** contain `vintage` |
| The two prescribed HTTP paths | **HTTP 404** (`/economy/fred/series_vintages`, `/economy/fred/series`) |
| The real path | `/economy/fred_series` — accepts `provider, symbol, start_date, end_date, limit, frequency, aggregation_method, transform, all_pages, sleep, chart` |
| In-process SDK | **no `obb.economy.fred` namespace** — `AttributeError`; the FRED surface is exactly `fred_regional`, `fred_release_table`, `fred_search`, `fred_series` |

**Correction to an earlier overstatement in this report:** I first wrote *"zero
operations expose any `realtime*` parameter."* Reading the provider source
(`openbb_fred/models/series.py`, `search.py`) showed that was **too strong** —
`realtime_start`/`realtime_end` **do** exist, but only as `order_by` **sort keys**
on `fred_search`, never as filters; and `fred_series` explicitly **pops them out
of the upstream response** (`series.py:156-157`) with no realtime field in its
query model.

**The absorption proof — the part that actually matters.** Passing the
parameters through the SDK does not raise; it swallows them:

```
fred_series('CPIAUCSL', 2024-01-01..2024-06-01)
  -> Jan 309.698, Feb 310.967, Mar 312.345
fred_series('CPIAUCSL', …, realtime_start='2024-01-01', realtime_end='2024-01-01')
  -> Jan 309.698, Feb 310.967, Mar 312.345
  .equals() == True          # byte-identical
```

**And the identical output is absorption, not a genuine "no revision" result.**
Calling FRED/ALFRED directly (key read from OpenBB's own credential store):

```
CPIAUCSL observations 2024-01..03, at three vintages:
  2024-06-01 -> {309.685, 311.054, 312.230}
  2024-12-01 -> {309.685, 311.054, 312.230}
  2026-09-20 -> {309.698, 310.967, 312.345}
```

**The same observation dates carry different values per vintage** (Δ ≈ 0.013 /
0.087 / 0.115 index points). Revision history is real; OpenBB returned the latest
revision while a caller asking for `2024-01-01` had no signal. **A silently
absorbed parameter is indistinguishable from a respected one unless you compare
payloads — the status code is 200 either way.**

**What IS reachable, and why the engine still does not use it.**
`api.stlouisfed.org/fred/series/observations` *with* `realtime_*` **does** return
true vintage data. So the capability is absent from **the OpenBB route this
engine is specified to use**, not from FRED. Reaching it would require the engine
to hold its own FRED key and bypass OpenBB — exactly the architecture and
credential duplication §22.2/§22.3 and the directive forbid. **Recorded, not
implemented.**

**No code change was made**, because the codebase already handles this
correctly — `config.py`, `publication_dates.py` and `schemas.py` each already
state that the provider returns no vintage field. The directive's framing
(*"vintage is a parameter, not a column"*) is exactly right; the reason it cannot
be applied here is that **the parameter cannot be transmitted by the provider**.
Evidence recorded under **O-6**.

### Alpha Vantage — separately verified

| Probe | Result |
|---|---|
| `grep -rni "alpha.?vantage"` across `src/ config/ tests/ tools/ scripts/ .env.example pyproject.toml` | **0 references** |
| `openbb_alphavantage` provider installed? | **No** |
| Live `:6901` paths containing `"alpha"` | **0 of 278** |
| Registry providers | **47 × `fred`**; 1 × `nasdaq` on `release_calendar:` which is **`enabled: false`** |
| OpenBB credential store | contains `alpha_vantage_api_key`, but **nothing installed consumes it** |

**`FRED_API_KEY`:** confirmed the engine requires **no** key of its own — the
working key (`fred_api_key`, 32 chars) lives in
`~/.openbb_platform/user_settings.json`, i.e. **OpenBB's own store**, exactly as
the directive requires. The engine declares no FRED key; the `.env.example` line
is a commented-out documentation record and says so.

---

## 7. Remaining limitations

**Investigated and confirmed already correct (deliberately NOT changed):**

- `datetime.utcnow()` — appears **only inside docstrings** quoting the spec.
  Production uses the timezone-aware `utc_now()`. An automated grep flags it; the
  flag is a **false positive**.
- `raw_kelly = ev / 100` — **not implemented anywhere**. The shipped
  `generalized_kelly_fraction` is a genuine `argmax` of expected log growth, and
  a test enforces that the placeholder cannot return.
- `SnapshotStoreEmptyError` — an **absent** store raises; an empty snapshot and a
  missing store are distinguished, not conflated.
- `validate_snapshot` — genuinely registry-driven; no hardcoded series subset.
- `marginal_risk_contributions` — refuses on `variance <= 0`.
- Phase 4+ stubs — `raise NotImplementedError`, never return a neutral value.
- No hidden numeric defaults in model signatures; no hardcoded scenario
  probabilities or payoffs; no placeholder arithmetic in production paths.

**Carried forward (unchanged, pre-existing, documented):**

- **O-6** — no vintage/PIT-revision storage is possible against this provider.
  Forward-only mitigation. Now carries the five-way re-probe evidence.
- **O-21, O-25, O-29, O-30–O-42, O-56–O-68, O-71–O-78, O-80, O-82, O-84–O-87,
  O-89–O-97** — the standing open-issue ledger.
- **O-92** — production HTTP clients honour `HTTP_PROXY` (loopback traffic in
  this environment is *luckily* forwarded). Filed, not fixed: it changes
  data-layer network behaviour and would invalidate a certifying sweep.
- **O-96** — §17.4's literal `CANDIDATE → WATCH` transition names a state with no
  producer; the demotion target is `WATCH`. Recorded, not silently reconciled.
- Two **INHERITED** `sweep_health.py` failures (`mutation_regime.py` `M8d`,
  `mutation_lei_proxy.py` `M8e`) — targets absent by design. **Do not fix.**
- **The single pytest skip** (`test_output_gap.py:255`) is Phase-5-gated.
- **Phase 5 is not started**, by explicit user instruction. Its entry point is
  the 13 Tier-5 deferrals, each requiring its own registry, its own
  central-bank reaction function, and its own instruments.

---

## 8. Final Phase 0–4 status

```
Phase 0 = 8/8 ✅   Phase 1 =  9/9 ✅   Phase 2 = 85/98 (13 out = ALL Tier 5, by §22.3)
Phase 3 = 2/2 ✅   Phase 4 = 4/4 ✅   Phase 5 = NOT STARTED (deliberate)
Tier 1 = 23/23 ✅  Tier 2 = 29/29 ✅  Tier 3 = 15/15 ✅  Tier 4 = 11/11 ✅  Tier 5 = 0/20
```

**"85/98" is not a backlog** — 85 = 23+29+15+11, i.e. every Tier 1–4 function. The
13 outstanding are all Tier 5, the specification's own deferral list.

### Final quality gates — measured by execution, never carried forward

| Gate | Result |
|---|---|
| `ruff check src tests tools scripts` | **All checks passed!** |
| `ruff format --check src tests tools scripts` | **221 files already formatted** |
| `mypy --strict src tests tools scripts` | **no issues in 221 source files** |
| Count parity (D-035) | **221 = 221 ✅** |
| `pytest -q` | **2358 passed, 1 skipped, 0 failed** (exit 0) |
| `tools/sweep_health.py` | 40 sweeps, **0 leftovers**, 2 INHERITED failures (unchanged) |
| `tools/reachability_audit.py --check-baseline` | **PASS — 59 = 59, no regressions** |
| `grep "if False:\|if True:"` (Step 0) | **clean** |
| Live OpenBB `:6901` validation | **clean** |
| Unresolved critical defect | **none** |
| Discovered bugs documented | **D-074 + O-6** |
| Intentional limitations documented | **§7 above + OPEN_ISSUES.md** |
| Phase 5+ implementation introduced | **none** |

### Verdict

**Phase 0–4: AUDITED, FOUR DEFECTS FIXED, ALL GATES GREEN, SIGNED OFF.**

Four defects that the existing gates could not see were found and fixed; the
fixes are pinned by 29 new regression tests; the live system was validated
end-to-end against real `:6901` data; the one prescribed procedure that cannot
execute here was **measured five ways, refused, and documented** rather than
faked; and the system's own output on live data was an honest **`NO TRADE`**.
