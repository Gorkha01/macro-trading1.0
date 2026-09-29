# AUDIT FINDINGS — Phase 0–4 `src/` LAYERS (the files the models/ pass did NOT cover)

**Audit run:** 2026-09-29, `HEAD = 2f40d27db24a762eb248c8dc3ee911d3704e04ac`.
**Trigger:** `docs/AUDIT_PHASE04_FINDINGS.md` declared a scope of **68** non-Tier-5 `src/**/*.py`
files (63 substantive) but delivered **26 cards, all in `models/` (25) + `extensions/` (Card 5, 6
files)**. The remaining layers were never given the same file-by-file pass. This file is that pass.
**Scope (RE-DERIVED):** the `src/` files neither the Tier-5 audit nor the Phase 0–4 models pass
covered —

| Layer | substantive files | status |
|---|---|---|
| `data_layer/` | 12 (`__init__.py` empty) | **IN PROGRESS** — 4 cards + 2 NEW cards (P-1, P-2) |
| `thesis_layer/` | 8 | pending |
| `api_layer/` | 8 | pending |
| root `src/macro_engine/` | 3 (`audit.py`, `deployment.py`, `settings_store.py`) | pending |

**Method:** the same 8 classes (A=MATH, B=ECONOMICS/REASONING, C=INPUT WIRING, D=DATA AVAILABILITY,
E=INPUT-NOT-TAKEN, F=INTEGRATION, G=CONFIDENCE/PROVENANCE, H=EVIDENCE INTEGRITY) and the same
**MEASURED-EVIDENCE** standard as the Tier-5 and Phase 0–4 audits. One file at a time.
**Status legend:** `CLEAN` (positive measurement) | `DEFECT` (measured fault) | `OBSERVATION`
(disclosed, not a fault) | `UNMEASURED` (no measurement).

> **PART 2 (below) FIXES every finding in this file** and adds two NEW defect cards (**P-1**, **P-2**)
> that the fix pass exposed. Part 1 was audit-only; the "Not fixed here" lines under each card are
> superseded by Part 2. See **PART 2 — THE FIX PASS** at the bottom.

---

## CROSS-CUTTING X-L1 — the §10.3 logging mandate is DECLARED but not in effect at runtime

**AGENTS.md §10.3** mandates: *"Structured JSON logging (`logging` + a JSON formatter) — every model
call logs `model_name`, `country`, `duration_ms`, `confidence`; every data fetch logs
success/failure/retry count; every thesis build logs the final `convergence_classification` and
`thesis_id`. Log level `WARNING` for any `ModelResult.warnings` being non-empty."*

**Measured against the tree:**

* The formatter exists (`data_layer/logging_json.py`), is referenced by `config/logging.yaml:12`, and
  is well-tested. **But `configure_logging()` — the only function that applies the YAML — has ZERO
  callers anywhere in the repo** (`grep -rn configure_logging . --include=*.py` → its definition +
  `__all__` only). The README's run command
  (`uv run uvicorn macro_engine.api_layer.app:app --host 127.0.0.1 --port 8000`) carries **no
  `--log-config`**, and `api_layer/app.py` has **no lifespan/startup hook**. So the JSON formatter
  **never runs at runtime**.
* No log call anywhere passes `model_name`, `country`, `duration_ms`, or `confidence`
  (`grep -rn "duration_ms\|model_name" src/ | grep -i "log\|extra"` → only the formatter's own
  `_AUDIT_FIELDS` and `audit.py`'s docstring).
* No `WARNING` is emitted when `ModelResult.warnings` is non-empty.
* `api_layer/` has **0** `logger.*` calls.

**Verdict: the mandate is substantially unimplemented at runtime.** The pieces exist in isolation
(config + formatter + `audit.py` store) but nothing composes them. See Card D-1 and Card R-1
(`audit.py`, pending) for the per-file view. **Recorded as a cross-cutting finding; not fixed here**
(it spans layers and needs a decision about *where* logging is configured).

---

## CROSS-CUTTING X-L2 — a published disclosure asserts a confidence penalty that is NOT enforced

`api_layer/snapshot_provider.py:136-140` publishes, whenever the snapshot carries any data-quality
flag:

> *"SNAPSHOT FLAGGED: {N} data-quality flag(s) on the snapshot; **every model derived from it carries
> a reduced confidence** (Section 5.4 / 22.8)."*

`data_layer/validation.py:11-12` repeats the claim: *"The flag list is also what
`compute_confidence()` reads — so a flagged snapshot **cannot** report high confidence downstream."*

**Measured — both are FALSE.** `compute_confidence(inputs: ConfidenceInputs)`
(`models/contracts.py:121`) reads a **per-model** boolean `data_quality_flags_present`
(`contracts.py:81`), which each model sets from **its own** inputs — e.g. `commodities.py:288`
(`fetched_legs < 2`), `equity_macro.py:275` (`not has_prior`), `convergence.py:370`
(`any(s.data_quality_flags_present for s in signals)`). **No model reads
`snapshot.data_quality_flags` into `ConfidenceInputs`** (`grep -rn data_quality_flags
src/macro_engine/models/*.py src/macro_engine/thesis_layer/*.py` → only the per-model boolean).
The snapshot's flag list flows **only** to `snapshot_provider` as `data_quality_flag_count`
(a disclosure), never into any confidence.

**Consequence:** a snapshot can carry N flags while every model reports full confidence — the
published message asserts the opposite. **Class G (false disclosure about confidence).** The honest
fix is to correct the two texts to describe what is actually enforced (the per-model
`data_quality_flags_present` factor), or to actually wire the snapshot flags into confidence — a
model-behaviour decision for the operator.

---

## CARD D-1 — `src/macro_engine/data_layer/logging_json.py` (251 lines)

**Purpose:** the JSON log formatter + redaction (AGENTS.md §10.3).

| # | Check | Result |
|---|---|---|
| A | MATH | PASS (vacuous — no arithmetic) |
| B | ECONOMICS/REASONING | PASS (vacuous — no domain logic) |
| C | INPUT WIRING | PASS — `config/logging.yaml` exists and references the class (`:12`, verified) |
| D | DATA | PASS (the config file is present) |
| E | INPUT-NOT-TAKEN | **OBSERVATION (minor)** — `get_logger()` has zero callers; all 14 modules use `logging.getLogger(__name__)` directly |
| F | INTEGRATION | **DEFECT** — `configure_logging()` has zero callers; the YAML is never applied |
| G | CONFIDENCE/PROVENANCE | PASS (vacuous) |
| H | EVIDENCE | PASS — `tests/test_infrastructure.py` covers key redaction, case-insensitivity, nesting, depth-limit, truncation, location-at-WARNING, exception, stack, `default=str` |

**STATUS: DEFECT (Class F).** `configure_logging()` is the only function that applies
`config/logging.yaml` to the stdlib tree, and **nothing calls it** — verified repo-wide
(`grep -rn configure_logging . --include=*.py` → the definition and `__all__` only). So the JSON
formatter is never active; the §10.3 structured-logging mandate is declared but not wired
(cross-cutting X-L1). The formatter itself is correct and well-tested. **Not fixed here.**

---

## CARD D-2 — `src/macro_engine/data_layer/publication_dates.py` (282 lines)

**Purpose:** read each registry series' `last_updated` from FRED metadata (Section 6).

| # | Check | Result |
|---|---|---|
| A | MATH | PASS — linear backoff `backoff_seconds * attempt`; the exact-match rule is correct |
| B | ECONOMICS/REASONING | PASS — publication-vs-vintage distinction is correct and evidenced |
| C | INPUT WIRING | PASS — config-driven (`provider`, `endpoint`, `search_type`, `limit`, `max_attempts`, `backoff_seconds`, `enabled`) |
| D | DATA | PASS — measured live (42/42 symbols) |
| E | INPUT-NOT-TAKEN | PASS — every declared input is used |
| F | INTEGRATION | PASS — called by `snapshot_builder.py:726` |
| G | CONFIDENCE/PROVENANCE | PASS |
| H | EVIDENCE | **OBSERVATION (minor)** — the docstring overstates the filter |

**STATUS: CLEAN, with one minor Class-H observation.** `_resolve_series_symbols`'s docstring claims
*"``blocked``/``unverified`` entries are skipped too"*, but the code filters **only** on
`entry.symbol and not entry.tenors` — it never reads `entry.status`. Measured: `blocked` is a
**separate registry section** (`series_registry.yaml` → `blocked: [5 entries]`), so those entries are
never in `.series` and are "skipped" only by construction; `unverified` is the `RegistrySeries`
default but **all 59 series are `status: verified`**, so there is nothing to skip today. **Zero
current impact**; the sentence is inaccurate as a general statement about `unverified`. Fix = correct
the docstring (or implement the status filter).

---

## CARD D-3 — `src/macro_engine/data_layer/validation.py` (630 lines)

**Purpose:** range / date / future-dating / curve checks; flags, never fixes (Section 5.4).

| # | Check | Result |
|---|---|---|
| A | MATH | PASS — bp conversions, staleness, tolerance comparisons all correct |
| B | ECONOMICS/REASONING | PASS — finiteness-first, forward-looking vs tolerance, signed-series lower-bound suppression, 2s10s INFO vs 30yr-below-10yr ERROR |
| C | INPUT WIRING | PASS — all bounds from config + registry |
| D | DATA | PASS (operates on already-fetched data) |
| E | INPUT-NOT-TAKEN | **DEFECT (minor)** — `out_of_range` is a dead counter |
| F | INTEGRATION | PASS — called by the snapshot build path |
| G | CONFIDENCE/PROVENANCE | **DEFECT** — the module docstring's confidence claim is false (X-L2) |
| H | EVIDENCE | PASS — validated by the snapshot build + re-validation agreement (AUDIT-001) |

**STATUS: DEFECT (Class E + G).** Two findings:

1. **`out_of_range` is computed and never read** — initialised at `:162`, incremented at `:249` and
   `:260`, and **never used again** (measured: `grep -n out_of_range` → those three lines only). A
   dead counter; presumably intended for an aggregate finding that was never written. Class E.
2. **The docstring's confidence claim is false** (`:11-12`, *"the flag list is also what
   `compute_confidence()` reads — so a flagged snapshot cannot report high confidence downstream"*).
   Measured false — see cross-cutting **X-L2**. Class G.

**Not fixed here.**

---

## CARD D-4 — `src/macro_engine/data_layer/reserves_client.py` (277 lines)

**Purpose:** fetch FX reserve stocks (USD millions) for `intervention_capacity` (Section 20.9).

| # | Check | Result |
|---|---|---|
| A | MATH | PASS — 12-month lag indexing (`values[-13]`), `(last-prior)/prior*100`, `MILLIONS_PER_BILLION = 1000.0` |
| B | ECONOMICS/REASONING | PASS — `None` (never `0.0`) for an unknown change; zero prior → unknown, not infinite |
| C | INPUT WIRING | PASS — routes through `OpenBBClient.fetch_series` |
| D | DATA | PASS — series measured reachable |
| E | INPUT-NOT-TAKEN | **DEFECT (minor)** — `OUTPUT_UNIT` is dead |
| F | INTEGRATION | PASS — used by `intervention_capacity` |
| G | CONFIDENCE/PROVENANCE | PASS — `source_unit` carried on the reading |
| H | EVIDENCE | **DEFECT** — the module docstring states the opposite of the code |

**STATUS: DEFECT (Class H + E).** Two findings:

1. **The module docstring contradicts the code AND the dataclass docstring.** The module docstring
   (`:30-35`) says *"The model's contract is **billions**, so the conversion happens **here**, once …
   **this module performs the equivalent conversion** rather than delegating it to a reader."* The
   `ReservesReading` docstring (`:131-136`) says the opposite: *"``reserves_usd_mn`` is in the
   **source's own unit** (millions). **The model converts.** Deliberately *not* pre-converted
   here."* **Measured:** the code returns `reserves_usd_mn=last_value` (raw millions, no division),
   and `models/intervention.py:520` does `reading.reserves_usd_mn / MILLIONS_PER_BILLION`. So the
   **dataclass docstring is TRUE and the module docstring is FALSE**. Class H.
2. **`OUTPUT_UNIT = "billions of USD"` (`:101`) is dead** — defined, never referenced in this file or
   anywhere else (`grep -rn OUTPUT_UNIT` → the definition only). Class E.

**Not fixed here.**

---

## REMAINING (this audit, not yet done)

`data_layer/`: `alfred_client.py`, `commodities_client.py`, `openbb_client.py`, `persistence.py`,
`release_calendar.py`, `schemas.py`, `snapshot_builder.py`, `world_bank_client.py` (8 files).
Then `thesis_layer/` (8), `api_layer/` (8), root (3).

---

## CARD B-1 — `thesis_layer/builder.py` — the horizon literal vs its named neighbour

**Class E + H (bare re-typed literal; documented standard not applied to its own
neighbour). Fix pass, Part 2.**

**Measured.** In the same `TradeIdea(...)` construction inside
`build_us_macro_thesis`, two adjacent fields with two different standards:

```python
            timeframe="6-12 months",               # bare literal, line 996
            sizing_logic=SIZING_LOGIC_PHASE_1,     # named constant, line 997
```

The comment directly above `SIZING_LOGIC_PHASE_1` (`builder.py:199-201`) states the standard that is
being violated: *"A module constant because a test asserts the thesis carries it and **a re-typed
string at a call site is the drift this project has measured repeatedly**."* A dedicated guard test
exists for the sizing sentence (`test_the_sizing_sentence_is_used_not_re_typed`) and
**none** for the horizon — measured: `grep -n "6-12 months" tests/thesis_layer/test_builder_strictness.py`
→ 0 hits.

**Fix:** promoted the literal to a named module constant `THESIS_TIMEFRAME_PHASE_1` with a provenance
comment, bound the call site to the name, and added two guard tests
(`test_the_horizon_is_used_not_re_typed`, `test_the_horizon_constant_is_a_single_definition`) plus the
name in the public-surface set. **Guard proven a killer:** re-typing the literal at the call site fails
the named test with the exact message.

**⚠️ The structurally important part, which the constant does NOT fix — and must not be read as
fixing.** The horizon is a **disclosure-bearing free-text string, not a structured value**, so it
cannot serve the backtest / sizing path this project is building toward:

* `TradeIdea.timeframe` is a bare `str`, default `"n/a"` (`schemas.py:488`).
* The only consumers are `portfolio/risk_budget.py:2932` / `:2938`, which **interpolate it into prose**
  and copy it onto `PositionSize.timeframe` (`:2974`, `:3039`) — whose docstring calls it "The thesis's
  stated horizon" while nothing parses it.
* Nothing derives a **numeric holding period** from it. A backtest or Kelly sizer that needs a horizon
  in days has no machine-readable value to read.

This is the gap **O-75 already records**: *"Calibrating it needs a stated thesis-timeframe convention
first, which does not exist yet."* Promoting the literal to a constant removes the **drift** defect and
single-sources the value; it does **not** invent the convention. Turning `timeframe` into a structured
horizon (a `Literal`/`timedelta` field plus a convention) is a **schema + decision** change, recorded
here rather than improvised — consistent with the user's explicit instruction to fix defects but not to
invent unspecified design.

---

## CARD D-5 — `data_layer/alfred_client.py` — a dead public helper with a false activity claim

**Class E + H. Fix pass, Part 2.**

**Measured.** `isoformat_or_none(value: datetime | None) -> str | None` was defined at `:459` with the
docstring *"Small helper **used by callers building log lines**… Exists so a caller never reaches for
`str(vintage_datetime)`…"*. Repo-wide caller census:
`grep -rn isoformat_or_none src/ scripts/ tests/ --include=*.py` → **the definition only** (not in
`src/`, not in `scripts/`, not in `tests/`). It is also absent from the module's `__all__`. So the
docstring's central claim ("used by callers") is false — the helper has never had a caller.

This is the **same shape** as the two Class E+H findings already fixed in this pass (`OUTPUT_UNIT` in
`reserves_client.py`, `out_of_range` in `validation.py`): dead code carrying a claim of activity.
Unlike `out_of_range` (an internal counter), this one is a **public, named helper**, so its presence
reads to an author as "the supported way to format a datetime for a log line" — an invitation to
adopt it rather than a no-op.

**Fix:** removed the function and the now-unused `datetime` import (ruff caught the import the moment
the only user disappeared — a good demonstration that the removal is complete). Behaviour-preserving:
zero callers, not in `__all__`, not referenced in any doc.

**No guard test added** — a test asserting "this function does not exist" is not a useful guard, and
the general principle (dead code carrying an activity claim) is already covered by the removal
itself. `describe_route()`, by contrast, was **kept and verified live**: its docstring's stated purpose
is the distinctness assertion, which `tests/data_layer/test_alfred_client.py:229` genuinely performs
(`assert ROUTE_NAME not in {_PATH_LOCAL_API, _PATH_PACKAGE}`), so it is a live guard helper rather than
dead code — the distinction that separates D-5 from the two removals before it.

**Not addressed here (kept intentionally):** `describe_route` and `isoformat_or_none` are both public
by name but absent from `__all__`. With `isoformat_or_none` removed, `describe_route`'s absence from
`__all__` is a minor export-hygiene question, not a defect — the test imports the module and calls the
attribute, which works regardless.

---

# PART 2 — THE FIX PASS (2026-09-29, same session)

**Mode change:** Part 1 was audit-only. Part 2 **fixes** every finding above, to production grade, and
records two NEW defects the fixes exposed. Every claim below is MEASURED on the tree, and every guard
was proven a KILLER by hand-reverting the fix and watching the named test fail.

## CARD P-1 — `data_layer/persistence.py` — FOUR series SILENTLY ERASED from every snapshot

**Class C/F. Found by the fix pass, not the audit.** The audit's method was per-function reading; this
defect is only visible by **running** the round-trip.

**The mechanism.** `long_frame_from_snapshot` iterates `SCALAR_SERIES_FIELDS` /
`CURVE_SERIES_FIELDS` / `MAPPING_SERIES_FIELDS` and **nothing else**. A `MacroDataSnapshot` field that
is absent from these tuples is therefore written by no path and — because the read path mirrors the
tuples — **silently erased from every persisted snapshot, with no error.**

**Measured, pre-fix:** `SCALAR_SERIES_FIELDS` held 20 names while the schema declared 24 scalar series.
Missing: `fed_total_assets`, `reserve_balances`, `ppi_stage_crude`, `ppi_stage_intermediate`. A
snapshot with all four populated round-tripped through `long_frame_from_snapshot` /
`snapshot_from_long_frame` to **ZERO rows**. No gate noticed: the existing coverage test asserted only
`declared ⊆ schema` (the direction that catches a *typo*), never `schema_series_fields ⊆ declared`
(the direction that catches *data loss*).

**Fix:** added all four to `SCALAR_SERIES_FIELDS` (now 24) with a `⚠️` provenance comment. Rewrote
`test_persistence_field_lists_match_schema` to assert **BOTH** directions (with a named
`non_series_fields` exclusion set, because `country` / `as_of` / `decision_cutoff` /
`data_quality_flags` / `field_sources` are snapshot-level metadata, not observations). Added
`test_every_scalar_series_field_survives_a_persistence_round_trip` — an **effect** check, because a
name check can be satisfied by a wrong list.

**Guard proven a killer:** reverting the four names fails the rewritten coverage test, naming all
four.

## CARD P-2 — `config/settings.yaml` — the P-1 fix EXPOSED a second, deeper defect in the same chain

**Class C/F (input wiring) — the exact `gdi` defect class, verbatim.**

**How it surfaced.** With the P-1 fix in place, `test_every_scalar_snapshot_field_is_in_the_bootstrap_fetch_list`
— the guard written for the historical `gdi` defect — **failed**, naming `ppi_stage_crude` and
`ppi_stage_intermediate`. The P-1 fix is what made that guard able to see them: the guard iterates
`SCALAR_SERIES_FIELDS`, and the two fields were absent from *both* the tuple and the fetch list, so
they had been outside its iteration set since the day they were introduced.

**Measured state of both fields before the fix:**

| property | value |
|---|---|
| registry entry | `verified`, `verified_on: 2026-09-17`, resolvable |
| `not_a_snapshot_field` | **False** (i.e. declared as a real snapshot field) |
| `MacroDataSnapshot` field | **present** |
| `persistence.SCALAR_SERIES_FIELDS` | absent (P-1) — then present (P-1 fixed) |
| `settings.snapshot_fields.us` | **absent** ← the killer |

`build_snapshot` does `for field_name in requested:` where `requested =
settings.snapshot_fields[country]` — **that list is the only iteration source**, so `setattr` is never
reached for an unlisted series. Consequence: every snapshot carried two permanently empty stage
series, and `ppi_pipeline_signal` (implemented, tested, `mutation_ppi_pipeline.py` 38/38) had **no data
path from a snapshot at all** — the same "declared in five places, fetched in none" shape the
`gdi` and `fed_total_assets` comments in `settings.yaml` already record.

**Fix:** added `ppi_stage_crude` and `ppi_stage_intermediate` to `snapshot_fields.us`, with a comment
naming the class and the measurement.

**Scope honesty — what the fix does and does NOT do.** `ppi_pipeline_signal` is **not** yet wired into
`build_us_macro_thesis`: `orchestration.py` imports and consumes exactly six models (`gdp_nowcast` /
`labor_synthesis` / `policy_rules` / `regime` / `yield_curve` / `instrument_selection`), and the PPI
pipeline signal is not among them — a **known Phase-5 integration boundary** (D-096: Phase 5+ is an
upgrade pass), and one `orchestration.py`'s docstring states explicitly ("What is derived, and what is
deliberately NOT"). So this fix does **not** add a thesis-build data path. What it does:

1. the snapshot now **carries** the two stage series, so any consumer that reads them (the standalone
   `scripts/live_labor_check.py` path, or a future `orchestration` wiring) gets real data instead of
   two permanently empty fields;
2. it removes the internal contradiction where the registry declared these as real snapshot fields and
   the fetch list disagreed — the state the `gdi` guard exists to forbid.

It is a **necessary precondition** for wiring the pipeline signal, not the wiring itself.

**Guard:** added `test_every_snapshot_field_registry_entry_is_actually_fetched` — a **registry-driven**
check that closes the *class*, not the instance. It enumerates `get_registry().series` — the only
complete list — and requires every entry that is `verified`, resolves into a real
`MacroDataSnapshot` field, and is not `not_a_snapshot_field` to appear in the fetch list (by registry
KEY, since that is what the list holds; a target-based comparison was measured to false-positive on
`treasury_curve` → `yield_curve`).

**Guard proven a killer, and non-redundant** (this is the decisive measurement):

| tree state | old `bootstrap_fetch_list` guard | new registry-driven guard |
|---|---|---|
| both P-1 and P-2 reverted (**the true pre-fix repo**) | **PASSES (blind)** | **FAILS**, names both |
| P-2 reverted, P-1 fixed | FAILS | FAILS |
| fixed | passes | passes |

The old guard **passed on the real pre-fix tree.** That is why the defect survived every gate for the
life of the module.

## O-157 RECURRENCE — a killed sweep left a LIVE MUTATION with NO marker

**Evidence-integrity (Class H), recorded because it recurred in THIS session.** The background
`mutation_api_layer.py` run was stopped after ~13 min. The tree then showed `routes_query.py` as
modified — a file this session never edited — with **no `# MUTANT` marker anywhere**
(`grep -rn MUTANT src/` → 0 hits). The diff was a real mutation:

```
-        default=True,
+        default=False,      # QueryResponse.is_keyword_routing
```

This is the **O-157 shape exactly**: a sweep can leave a live mutation that no marker-grep and no
`git status`-vs-intent comparison reveals, because the only signal is "this file changed and I did not
change it." Repaired with `git checkout HEAD -- src/macro_engine/api_layer/routes_query.py` +
`find src -name '*.sweepbackup' -delete`; verified 0 sidecars, 0 markers, tree == intent (10 modified
files, 1 new doc).

**Operational rule reaffirmed:** never edit `src/` while a sweep is in flight, and after ANY
interrupted sweep verify **both** sidecars AND an explicit `git diff` review of every modified `src/`
file — the marker grep is not sufficient.

