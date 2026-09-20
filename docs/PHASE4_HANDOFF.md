# PHASE 4 HANDOFF — read this first in the new session

**Written:** 2026-09-20, at the end of the session that produced
`docs/FINDINGS_value_provenance.md` and the §6 publication-date work.
**Purpose:** start Phase 4 in a fresh session with zero re-derivation.
**Status of this document:** a *handoff index*, not an authority. `AGENTS.md` remains
the single authority; if this file and `AGENTS.md` disagree, `AGENTS.md` wins.

---

## 1. Where we are

| Phase | Status |
|---|---|
| 0 | 8/8 ✅ |
| 1 | 9/9 ✅ |
| 2 | 85/98 — 13 outstanding, **all Tier 5 by §22.3 design** |
| 3 | 2/2 ✅ (last increment **D-070**, the §8 API layer) |
| **4** | **NOT STARTED ← the front of the runway** |

Tiers 1/2/3/4 = 23/23 · 29/29 · 15/15 · 11/11 — all complete.
Tier 5 = 0/20 **by design** (not a gap).

**Do not re-open D-070.** It is closed: 8 modules in `src/macro_engine/api_layer/`,
five surfaces, sweep 42/39/3 CERTIFIES, live check PASSED exit 0.

---

## 2. STEP 0 — before touching anything

```bash
uv run python tools/sweep_health.py          # inherit a clean tree
grep -rn "if False:\|if True:" src/macro_engine/   # must print NOTHING
```

Then read, in order: `AGENTS.md` → `docs/PROGRESS.md` → `REFERENCE.md`.

**Never run the test suite while a mutation sweep is in flight** (lesson **5bi**).
The sweep mutates `src/` per mutant, so any failure you see mid-sweep is a phantom.

---

## 3. Phase 4 scope — the concrete deliverable

Phase 4 = **risk basics (VaR) + the risk-budget hook.** Per `AGENTS.md` line 1787's
Module-to-Phase table, these functions carry the endpoint marker **"(Phase 4+)"**:

- `historical_var`, `expected_shortfall`, `parametric_var`, `realized_vol_simple`
- `portfolio_volatility_*`, `marginal_risk_contributions`
- `compute_risk_parity_weights` (§9.2)
- `translate_thesis_to_position` (§9.3)

### 3a. What ALREADY EXISTS — do not rebuild it

This is the most important paragraph in this document. Substantial Phase 4 material
has already shipped; the gap is **integration**, not implementation.

**`src/macro_engine/models/risk.py` (32 KB) — COMPLETE.**
`historical_var`, `expected_shortfall`, `parametric_var`, `realized_vol_simple`
are all implemented, with the loss-sign convention documented (losses are returned
**positive**: a VaR of `3.25` means "a 3.25% loss"), and with the three-method
rationale written out (historical = no distributional assumption; parametric =
understates tails; ES = severity given the tail).

**`src/macro_engine/portfolio/risk_budget.py` (66 KB) — MOSTLY COMPLETE.**
Present and implemented:
- `evaluate_drawdown_rules` (D-058) + `resolve_drawdown_rule` + `_tiers`
- `check_rebalancing_drift` (D-060) + `RiskBudgetTarget`
- `volatility_target_scaling` (D-061) + `VolTargetInputs`
- `apply_fractional_kelly` (D-062) + `KellyInputs` + `SizingOutcome`
- `generalized_kelly_fraction` + `_expected_log_growth`
- `RiskLimits` (the hard-constraint envelope)
- `DrawdownState`, `DrawdownRule`

### 3b. What is GENUINELY MISSING — the actual Phase 4 work

1. **`compute_risk_parity_weights(inputs: RiskBudgetInputs)`** — §9.2. Currently a
   stub: `raise NotImplementedError("Phase 4 — see docs/DECISIONS.md")`. Spec
   signature is fixed in `AGENTS.md` ~line 1515:
   ```python
   class RiskBudgetInputs(BaseModel):
       instrument_returns: pd.DataFrame              # cols = instruments, index = dates
       target_risk_contribution: dict[str, float]    # instrument -> target % of total vol
   ```
   Full implementation = covariance estimation + optimizer call + the Module 17.1
   **correlation stress test** (LTCM caveat). `riskfolio-lib` is the intended backend
   (optional dep; `pyportfolioopt` only if riskfolio lacks a needed optimizer).

2. **`translate_thesis_to_position()`** — §9.3. Takes a `MacroThesis` + portfolio
   risk-budget config, emits a **proposed** notional size. Still requires human
   sign-off — execution stays a deliberate separate decision, never an automatic
   consequence of a thesis existing.

3. **`portfolio_volatility_two_asset` / `marginal_risk_contributions`** — §20.12
   part C (Module 17.1 "the core correlation math"). The reference implementation is
   given *verbatim* in `AGENTS.md` ~line 2979. Note the mandated warning text about
   correlation rising toward 1 in crisis, and the instruction to stress-test at
   `rho=0.6` and `rho=0.9` before sizing.

4. **The risk-budget HOOK itself** — wiring the risk axis into the thesis builder.
   `src/macro_engine/thesis_layer/builder.py` ~line 278 currently documents that the
   risk axis is **deliberately not wired**: `reachability_audit.py` measures **59 of
   77** `models/` functions with no pipeline caller (34 live-checked in `scripts/`,
   25 with no caller at all). The file explicitly says wiring the risk axis "would
   build a Phase 4 layer early". **Phase 4 is when that stops being early.**

### 3c. Config already present for this

`src/macro_engine/config.py` already carries
`historical_var_lookback_days: CalibratedValue` (line 611) with an accessor at 695.
Remember the envelope convention: **every `settings.yaml` leaf is a
`{value, calibration_status, note}` envelope** with `extra="forbid"`, so keys are
`*_value`-suffixed and read via `@property`. Do not add a bare scalar key.

---

## 4. Phase 4 tests the spec DEMANDS

From `AGENTS.md` ~line 1681, verbatim requirements:

- **`test_historical_var_matches_hand_calculation()`** — a small synthetic return
  series with a **known quantile**.
- **`test_fractional_kelly_never_exceeds_hard_limits()`** — feed a scenario
  distribution engineered to produce a **large raw-Kelly output**, then assert the
  final sized position never exceeds `RiskLimits.max_position_pct_of_portfolio`
  **regardless of how large the unclipped Kelly fraction would have been**.

That second test is the load-bearing one: it is the LTCM lesson encoded as an
assertion. Hard limits must override, always.

---

## 5. Gates you inherit — these exact numbers are the baseline

Any deviation is either your change or a defect. **Do not assume drift.**

```bash
ruff check src tests tools scripts          ->  All checks passed
ruff format --check src tests tools scripts ->  210 files already formatted
mypy --strict src tests tools scripts       ->  no issues in 210 source files
pytest -q                                   ->  2217 passed, 0 failed
tests/data_layer/ (live)                    ->  16 passed
baseline gate                               ->  PASS (59 = 59)
```

`ruff format`'s file count **must equal** `mypy`'s (D-035) — currently **210**.
That number moved from 196 → 210 during the §6 work (two new modules + their tests),
so **re-measure it, do not carry 210 forward blindly.** A gate row is a CLAIM, not a
receipt (O-88) — re-run it.

---

## 6. Inherited open issues — recorded, NOT fixed

Full text in `docs/OPEN_ISSUES.md`. Carry these; do not silently repair them.

| ID | Issue | Why not already fixed |
|---|---|---|
| **O-92** | Two **production** HTTP clients default `trust_env=True` (`openbb_client.py:91`, `catalysts.py:213`); OpenBB loopback mounts are `{http://: HTTPProxy}`. Every loopback request is proxied — works here only because this env's proxy transparently forwards loopback (**luck, not design**). | Patching would invalidate the provider mutants that certify current behaviour. |
| **O-90** | Memoized snapshot is **process-global**; `--workers N` silently multiplies the measured **223.6 s** build while still disclosing a correct age. | Needs a `workers=1` contract or a shared store. |
| **O-91** | Async SSE generator **awaits a synchronous build**, blocking the event loop so `/health` goes unanswered during a slow build. | Needs `to_thread`. |
| **O-87** | `select_instrument`'s two value shapes. | |
| **O-86** | `WATCH` cannot distinguish "no edge" from "waiting". | |
| **O-84** | Data-layer `iorb` tolerance decision — published 2–3 days ahead of calendar against a declared tolerance of 1. Was the **only failing test** at D-070's close. | Pre-existing data-layer decision. |

---

## 7. Lessons that will cost you the most time if unknown

**5bg — a ROUTING-shaped symptom can have a TRANSPORT-shaped cause. Print the
request line.** `httpx.Client` defaults to `trust_env=True`, honours `HTTP_PROXY`,
and a forward proxy takes the **absolute-URI form** (RFC 7230 §5.3.2), which uvicorn
unquotes into `scope["path"]`. **The intermittency is what costs the day: the first
request on a FRESH connection survives; a request on a REUSED keep-alive 404s.**
Rule: for a loopback service, always pass `trust_env=False`, and guard it with an
`ast` test. (This is the mechanism behind O-92.)

**5bh — lesson 5bf applies to CHECKS, not only tests: pin the VALUE, never a
rendering.** A check asserted `"gap = +26.0bp"` while the service correctly emits
`"gap = +0.2600pp (+26.0bp)"` — a string the format never produces. Derive what you
expect from the value you measured. And the check must **supply the input the config
declares** (a hardcoded CORS origin of `localhost:3000` against an allow-list of
`:8000` produced a correct `400`, i.e. the middleware was right and the check wrong).

**5bi — NEVER run the suite while a mutation sweep is in flight.** (See §2.)

---

## 8. §6 provenance — the state you inherit

Populated and verified in this session's predecessor:

- **`release_datetime` — OBTAINED.** Primary source is `last_updated` via
  `GET /api/v1/economy/fred_search?search_type=series_id&query=<SYMBOL>`. Coverage
  **42/42** registry symbols, **0** transport errors. Implemented in
  `src/macro_engine/data_layer/publication_dates.py`. Fallback
  `release_calendar.py` is retained but `enabled: false`.
- **`vintage_datetime` — NOT OBTAINED, and now established by test** rather than
  assumed. `realtime_start`/`realtime_end` exist but **always equal today**; passing
  `realtime_start` as a param is **silently ignored**. Requires a credentialed
  FRED/ALFRED key → an **entitlement** question, not a routing one.
- Live build reports `release_source: publication_dates`, `has_known_release_timing`
  **True on 59/59** points, **no** `RELEASE_TIMING_UNKNOWN` flags.

**Full detail: `docs/FINDINGS_value_provenance.md`.** Read it before touching
anything in `data_layer/`. It lists every value field with an explicit
obtainable / not-obtainable verdict.

**Unbuilt lead recorded there:** `GET /api/v1/economy/fred_release_table` with its
`date` param yields a **204↔200 publication-boundary oracle** (204 = before first
publication or in the future). Stronger `release_datetime`, **no API key needed**,
but needs caching (~1 request per candidate day per series). It does **not** move
`vintage_datetime` off `None`.

---

## 9. Repository state at handoff

- Branch `main`, HEAD **`13467a4 "fixes2"`** (the user's own commit, 2026-09-20 10:11),
  parent `9f868e2 "others"`.
- **`.git` is effectively user-managed — the user pushes to GitLab themselves.**
  Do not do git work; report state and let them push.

### Already committed — `13467a4 "fixes2"` (+1051 / −94, 8 files)

The entire §6 publication-date work is **committed**:

| File | Change |
|---|---|
| `src/macro_engine/data_layer/publication_dates.py` | **NEW** — 274 lines |
| `tests/data_layer/test_publication_dates.py` | **NEW** — 411 lines, 18 tests |
| `config/series_registry.yaml` | `publication_dates` block; calendar disabled |
| `src/macro_engine/config.py` | `PublicationDates` model + wiring |
| `src/macro_engine/data_layer/schemas.py` | `ObservationPoint` docstrings |
| `src/macro_engine/data_layer/snapshot_builder.py` | `_resolve_release_index`, `release_source` |
| `tests/data_layer/test_phase1_data_layer.py` | tightened live coherence test |
| `docs/INTEGRITY_2026-09-19.md` | §K + recommendation #2 corrected |

### Uncommitted at handoff — docs written after that commit

| File | Status |
|---|---|
| `docs/PHASE4_HANDOFF.md` | **NEW** (this file) |
| `docs/FINDINGS_value_provenance.md` | **NEW** — the value-provenance findings |
| `docs/PROGRESS.md` | **MODIFIED** — header bumped to 2026-09-20 + pointer to this file |

**Only these three docs are pending.** They are `docs/` only — no source, config, or
test file is uncommitted, so the code baseline is fully captured in `13467a4`.
**Phase 4 starts on top of `13467a4` plus these three doc edits.**

---

## 10. Standing obligations at every close

1. Run the full gate set **sequentially** — never alongside a sweep (5bi).
2. Run `tools/sweep_health.py`.
3. Quote the **measured** file count; check ruff-format's equals mypy's (D-035).
4. Write the record set in this order:
   **DECISIONS → PROGRESS → OPEN_ISSUES → BUILD_STATE → MODULE_MAPPING → CHANGELOG
   → memory → skill.**
5. A mutation survivor is a claim about your **tests** until proven otherwise. First
   question: *"is its killer in my selection?"* **Never exempt a mutant to make a
   sweep go green — add the test.**
6. `uv` exclusively.

---

## 11. One-line summary for the new session

> Phase 4 = risk basics (VaR) + the risk-budget hook. The VaR functions
> (`models/risk.py`) and most risk-budget primitives (`portfolio/risk_budget.py`)
> **already exist** — what is missing is `compute_risk_parity_weights` (§9.2),
> `translate_thesis_to_position` (§9.3), `portfolio_volatility_two_asset` /
> `marginal_risk_contributions` (§20.12C, reference impl given verbatim), and the
> **wiring** of the risk axis into the thesis builder. Two tests are mandated:
> `test_historical_var_matches_hand_calculation` and
> `test_fractional_kelly_never_exceeds_hard_limits`.
