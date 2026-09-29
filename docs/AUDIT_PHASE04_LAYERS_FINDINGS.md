# AUDIT FINDINGS — Phase 0–4 `src/` LAYERS (the files the models/ pass did NOT cover)

**Audit run:** 2026-09-29, `HEAD = 2f40d27db24a762eb248c8dc3ee911d3704e04ac`.
**Trigger:** `docs/AUDIT_PHASE04_FINDINGS.md` declared a scope of **68** non-Tier-5 `src/**/*.py`
files (63 substantive) but delivered **26 cards, all in `models/` (25) + `extensions/` (Card 5, 6
files)**. The remaining layers were never given the same file-by-file pass. This file is that pass.
**Scope (RE-DERIVED):** the `src/` files neither the Tier-5 audit nor the Phase 0–4 models pass
covered —

| Layer | substantive files | status |
|---|---|---|
| `data_layer/` | 12 (`__init__.py` empty) | **DONE (2026-09-29)** — 4 cards (D-1..D-4) + 2 NEW cards (P-1, P-2) + R-1..R-6 (PART 3) + **D-6/D-7** (PART 7, `schemas.py`/`snapshot_builder.py`, the two files with no card — both CLEAN). **All 12 files CLEAN on re-read; 6+3 defects found and fixed across the layer.** |
| `thesis_layer/` | 8 | **DONE (2026-09-29)** — 8/8 CLEAN; 8 dedicated sweeps already present (149 mutants) |
| `api_layer/` | 8 | **DONE (2026-09-29)** — 8/8 CLEAN on files, **1 NEW DEFECT fixed** (`orchestration.py` re-typed yield ceiling, Class C); X-L1/X-L2 CLOSED; `scripts/mutation_api_layer.py` anchor updated + **M1.3b added** |
| root `src/macro_engine/` | 3 (`audit.py`, `deployment.py`, `settings_store.py`) | **DONE (2026-09-29)** — 3/3 CLEAN (no sweep owns them; heavily covered by `tests/test_infrastructure.py`, 12 audit + 13 settings_store tests) |

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

---

# PART 3 — `data_layer/` COMPLETION (2026-09-29, the layer-by-layer fix pass)

**Scope:** the five `data_layer/` files the Phase 0–4 pass left UNTOUCHED — `release_calendar.py`,
`logging_json.py`, `world_bank_client.py`, `openbb_client.py`, `commodities_client.py` — plus
`reserves_client.py`, whose date helper carried the same defect class the other two clients did.
**Method:** unchanged (8 classes, MEASURED-EVIDENCE, one killer-proven guard per fix).
**Six new defect cards: R-1 … R-6.** Every guard below was proven a KILLER by hand-re-planting the
exact pre-fix text and watching the named test fail.

## CARD R-1 — `data_layer/release_calendar.py` + `config/series_registry.yaml` — FOUR dead joins

**Class C + E. FIXED.** `release_calendar.event_map` maps a provider event NAME to a **registry series
key**; `snapshot_builder` then reads the `ReleaseDateIndex` by that key (`release_index.get(series_id)`
at `snapshot_builder.py:267`, built from `fetch_release_dates` at `:58`). A target key that is **not**
in `registry.series` is a **dead join**: the calendar still matches the event and still writes a date
into the index — but **no observation can ever read it**, silently.

**Measured, pre-fix:** four shipped rows pointed at non-existent series —
`"Core PPI": ppi_core`, `"Nonfarm Payrolls": nfp`, `"GDP Price Index": gdp_deflator`,
`"Industrial Production": industrial_production`. Simulating a provider payload carrying
`"Core PPI"` / `"Nonfarm Payrolls"` / `"CPI"` produced a `ReleaseDateIndex` keyed
`['cpi_headline','nfp','ppi_core']` — of which **only `cpi_headline` could ever be looked up**; the
other two were written and discarded. No gate saw it: every existing test asserted the join in the
OTHER direction (`event NAME → registry`), never `target → registry.series`.

**Fix, two parts:** (1) the four dead rows removed from `config/series_registry.yaml` (event map
**16 → 12**), with a `⚠️` comment naming the class; and (2) a **structural** guard — a
`model_validator(mode="after")` on `SeriesRegistry` (`config.py`, `_release_calendar_joins_real_series`)
that REFUSES, **at config load**, any `event_map` value absent from `self.series`. A validator beats a
test here because a defect reachable only by a test can be reintroduced by the next edit; the validator
protects every consumer regardless.

**Guards proven killers** (`tests/data_layer/test_release_calendar.py`, 3 new tests):
`test_every_shipped_event_map_target_is_a_real_registry_series` (coverage),
`test_the_registry_refuses_an_event_map_join_to_a_missing_series` (plants `"Core PPI": ppi_core` →
`ValueError` naming `ppi_core`), and `test_the_validator_accepts_a_join_to_a_series_that_exists`
(negative control). Re-planting one dead row fails all three.

## CARD R-2 — `data_layer/logging_json.py` — a public helper with zero callers and zero tests

**Class E. CLOSED.** `get_logger` is exported in `__all__` and is a legitimate documented convenience
wrapper, but repo-wide it had **no caller and no test** — the same *shape* as D-5's removed
`isoformat_or_none`, differing in that a namespaced logger getter is a reasonable public affordance
(kept rather than removed, the D-5 distinction applied in the other direction).

**Fix:** three tests added to `tests/test_infrastructure.py` —
`test_get_logger_returns_the_namespaced_stdlib_logger` (pin),
`test_configure_logging_refuses_a_missing_config_file` (`FileNotFoundError`), and
`test_configure_logging_applies_the_shipped_config` (asserts the `macro_engine` logger ends up
non-propagating with a `JsonFormatter` handler; snapshots/restores `logging.root.manager.loggerDict`).
The last was **proven a killer** by breaking the YAML formatter dotted path
(`JsonFormatter` → `NoSuchFormatter`) → `ValueError: Unable to configure formatter 'json'`;
restored → green.

## CARD R-3 — `data_layer/world_bank_client.py` — the registry `symbol` and the client constant are ONE fact, twice

**Class C + E. FIXED.** Each `world_bank` registry entry declares its indicator code in **two** places:
the YAML `symbol`, and a module constant in the client. For a snapshot field that duplication is
harmless (`snapshot_builder` reads `entry.symbol`). But **all five World Bank entries are
`not_a_snapshot_field: true`** — the builder SKIPS them (`validation.py:547`) and the **only** thing
that fetches these series is the client, which uses its **own** constant and never read the registry.
So the registry `symbol` was **dead at runtime**: the fetch path and the auditable declaration could
disagree with nothing to notice until a wrong-series number reached a verdict.

**Measured, pre-fix:** all five pairs happened to MATCH — but only because they were transcribed
carefully, **not because anything enforced it**. `grep` over `tests/` found no test loading the
registry for these entries; the seven client tests that assert the codes compare them against
hardcoded literals (pinning the client to a value, not to the registry).

**Fix:** a **binding** — `_REGISTRY_TO_CLIENT_INDICATOR` in `tests/data_layer/test_world_bank_client.py`
plus two tests: `test_registry_symbols_match_the_client_indicator_constants` (the KILLER) and
`test_every_world_bank_registry_entry_is_bound_here` (coverage, derived from the registry so a sixth
entry with no constant fails). **Killer proven:** drifting the registry `symbol` to
`BN.CAB.XOKA.ZS` fails with `registry symbol='BN.CAB.XOKA.ZS', client constant='BN.CAB.XOKA.GD.ZS'`;
the inverse (client edited alone) trips the same assertion.

## CARD R-4 — `data_layer/openbb_client.py` — `to_observation_date` leaks a `datetime` out of `-> date`

**Class A + B. FIXED.** A **public module-level** helper (`snapshot_builder.py`'s own date coercion gets
this right; this one inverted it). It was already documented, unfixed, as item **3.10** in
`docs/CODE_REVIEW_PHASE0-4.md`.

**Measured, pre-fix** (not assumed):
`to_observation_date(datetime(2026,9,29,13,45))` → `datetime(...)`; and
`to_observation_date(pd.Timestamp("2026-09-29"))` → `Timestamp(...)`.
Both violate the `-> date` annotation, because the guard tested the **broadest** type first
(`isinstance(value, date)` is `True` for `datetime` and `pd.Timestamp`) and returned the value it
matched. `snapshot_builder._points_from_frame` tests `pd.Timestamp` BEFORE `date`; this inverted that
ordering.

**Fix:** test the most-derived type first and collapse via `.date()` (``pd.Timestamp``, then
``datetime``, then ``date``, then a parse), matching `snapshot_builder`. The function had **zero
callers and zero tests** repo-wide, so five tests were added to
`tests/data_layer/test_unit_scale_and_single_call_curve.py`, all asserting `type(out) is date` (not
`isinstance`, which a leaked `datetime` would satisfy). **Killer proven:** re-planting the `date`-first
guard fails 3 of 5, naming `-> datetime (leak)`; the two that still pass (plain `date`, string) are
exactly why the datetime-specific cases were required.

## CARD R-5 — `data_layer/commodities_client.py` — the SAME trap, reachable, in `_parse_date`

**Class A + B + G. FIXED.** The `datetime`-is-a-`date` trap of R-4, transcribed in a sibling module's
date parser. Unlike R-4 this one is **reachable**: `OpenBBClient._coerce_records` converts a
DataFrame-shaped payload with `to_dict(orient="records")`, and a datetime column becomes `pd.Timestamp`
values (measured) — which reach `_parse_date` at the two `fetch_records` call sites (inventories
`:278`, spare capacity `:405`).

**Measured, pre-fix — two live consequences:** (1) `when > as_of` (Timestamp vs `date`) raises
`TypeError: Cannot compare Timestamp with datetime.date`, an **uncaught crash** carrying a pandas
message instead of the module's own `CommodityReadError`; and (2)
`observation_date=when.isoformat()` publishes `'2026-09-18T00:00:00'` instead of `'2026-09-18'` — a
wrong-shape provenance fact (Class G).

**Fix:** the same most-derived-type-first ordering (no pandas/numpy import — the module owns no frame
library, so the check is by capability: collapse `datetime`, then any carrier exposing `.date()`, then
plain `date`, then a string parse). Seven tests added to `tests/data_layer/test_commodities_client.py`,
including an **end-to-end** case (`test_a_timestamp_dated_row_does_not_crash_the_inventory_as_of_clip`)
that reproduces the real fetch path. **Killer proven:** re-planting the `date`-first guard fails 3,
the end-to-end one with the exact measured `TypeError: Cannot compare Timestamp with datetime.date` at
`fetch_crude_inventories:279`.

## CARD R-6 — `data_layer/reserves_client.py` — `_as_iso_date` renders a time-bearing string

**Class B + G. FIXED.** The third transcription of the trap, with a **different** symptom: the function
returns a **string**, and the original guard led with
`if isinstance(index_value, date): return index_value.isoformat()` — so a `pd.Timestamp` took that
branch and `.isoformat()` produced `'2026-09-18T00:00:00'` (measured).

**Why a defect even though not reachable today.** `reserves_client` calls `fetch_series`, whose
normalized `date` column holds real `datetime.date` objects (measured: `sort_values` and `tolist`
preserve them), so the standard path never supplies a `Timestamp` — this is **latent, not live**. It is
fixed anyway because the code **contradicted its own docstring**, which states the function's purpose is
to avoid "a ``str()`` of a Timestamp [that] carries a time and a timezone, which would make two dates
for the same observation compare unequal" — the exact string the first branch emitted. An
intent-vs-code mismatch is a defect at the same standard when the fix is cheap.

**Fix:** collapse a `datetime` first (`datetime ... -> .date().isoformat()`), then any other
`.date()`-bearing carrier that is not already a plain `date`, then the plain `date`, then the
`year`/`month`/`day` fallback. Six tests added to `tests/data_layer/test_reserves_client.py`, including
an invariant sweep asserting no carrier emits a `T`-bearing string. **Killer proven:** re-planting the
`date`-first guard fails 4 of 6, printing the leaked `2026-09-18T23:59:59+00:00`.

## R-1…R-6 — the shared lesson

Three of the six (R-4, R-5, R-6) are **one defect class transcribed three times**: a type dispatch
that tests `date` (the broadest of `date`/`datetime`/`pd.Timestamp`) first, so a derived carrier slips
through a guard written for the base type. R-1, R-3 and R-5's end-to-end case share a second shape:
**a fact declared in two places with one copy dead** (a registry key nothing reads; a `symbol` no
fetch consults), invisible to every gate because each copy is individually valid. Both shapes are
**measured-reachable only by running the path**, which is why the audit's per-function reading missed
them and the killer-proof protocol is what certified the fix.


# PART 4 — the `models/` no-card pass COMPLETE + the `portfolio/` layer + `extensions/` (2026-09-29, D-132)

## CARD M-1 — `models/regime.py` (2347 lines) — TWO dead config leaves (Class E) + a missing reasoning object (Class G)

**Class E.** `late_expansion_output_gap_min` (1.0) and `disinflation_output_gap_max` (0.5) were declared
in `RegimeSettings`, accessor'd, documented as Section-6.2 literals, and consumed by
`_thresholds_calibrated` — but **no classifier branch read them**. **MEASURED:** moving each to a value the
literal does not equal (1.0→5.0, 0.5→0.05) changed **NO** `classify_regime` output; the only effect was
the published confidence via the "all-thresholds-calibrated" flag. This is the **declared-consumed-
unreachable** class, and the two leaves made the confidence flag *look* like it covered four thresholds
when it covered two.

**Fix:** REMOVED both (config field, accessor, YAML leaves, `_thresholds_calibrated` entries, test
fixtures), recording the superseded literals in the module docstring so the specification's intent is not
lost. Removal over making-them-live because a live `late_expansion` gap gate would create an unreachable
hole and contradict the deliberate momentum-band design (`_growth_axis`). `_bands_must_be_ordered`
rewritten to validate only the two thresholds that remain live.

**Class G.** `check_trilemma_tension`'s `ModelResult` published **none** of the seven §3–4 reasoning
fields (`unit`, `direction`, `assumptions`, `data_provenance`, `limitations`, `decision_relevance`,
`decision_prohibition`) while `classify_regime` and `check_trilemma_tension`'s sibling both published all
seven. Every field defaults to an honest "not supplied", so the omission passed every gate.

**Fix:** populated all seven (`unit="categorical (trilemma severity label)"`, a `direction`, four
`assumptions`, three `data_provenance`, four `limitations`, a `decision_relevance`, four
`decision_prohibition`). **Killer guards:** `test_the_reasoning_object_is_populated_d132` and
`test_the_reasoning_object_is_produced_for_every_severity`. **Kill-proved:** blanking `unit` fails; emptying
`decision_prohibition` fails.

## CARD M-2 — `models/fx_carry.py` (2500 lines) — ONE bare literal in a warning gate (Class C)

**Class C.** `ppp_valuation`'s data-sanity warning gate was `if abs(deviation_pct) > 100.0:`, while **every
other boundary in the module is a config leaf** (notable/extreme CIP bands, the carry-vol floor, the VIX
gate, the sign boundary, the tactical horizon). **MEASURED:** the gate fires at 100.1 and not at 99.9, and
`FxCarrySettings` carried **no** leaf for it.

**Fix:** added `ppp_implausible_deviation_pct` (following the `implausible_*` convention established by
`yield_curve.implausible_long_end_inversion_bp`) + a positivity validator + rewired `_ppp_warnings`.
**Killer guards:** `test_the_data_error_bound_is_read_from_the_leaf_not_a_literal` — a **mover** that
monkeypatches the leaf to 10.0 and 250.0 (a **pinner** cannot tell 100.0-from-config from a retyped 100.0,
D-031) — and `test_the_data_error_bound_is_validated_at_load`. Sweep: `_PPP_WARN_DATA` re-pointed, `P4g`
(retype-as-literal) and `C7a`-`C7d` added; **176 mutations, 0 problems** (was 171).

## CARD M-3 — `models/econometrics.py` (4282 lines) — a MODULE-WIDE missing reasoning object (Class G)

**Class G, systematic.** **MEASURED:** `data_provenance` and `decision_relevance` were published by
**NONE** of the five public functions (`run_regression`, `test_stationarity`, `test_cointegration`,
`compute_pca`, `kalman_latent_state`); `unit` was absent on `run_regression` and `test_stationarity`;
`assumptions` was absent on `test_stationarity`. This is the same shape the Tier-5 upgrade closes
(`DECISIONS.md`: "a `unit`, a `direction`, a `source_family` and a full reasoning object **added**") — and
`econometrics.py` IS "Phase 5, Tier 5" (`DECISIONS.md:15818`), so its **partial** object was a genuine
defect, not an un-upgraded state.

**Fix:** all six applicable fields on all five functions. **`direction` DELIBERATELY left unset** on all
five — each result is a coefficient map, a verdict, a lag set, a loading map, or a state path; none has a
single direction, and inventing one would be the `commodities.py` (D-131) label-blinder defect. **Killer
guard:** `test_every_result_populates_the_reasoning_object_d132` (loops all five fixtures; asserts the six
fields populated AND `direction is None`); **kill-proved** by blanking one `data_provenance`.

## CARD P-7 — `portfolio/risk_budget.py` (3075 lines) — ONE bare literal in the sum-to-1 gate (Class C); the missing reasoning object is the Tier-3/Tier-5 UN-UPGRADED STATE

**Not a defect:** all 8 `ModelResult`s publish only `inputs_used` (plus `direction=idea.direction` on the
two translation returns) — **zero** §3–4 reasoning fields. §21.3 places
`evaluate_drawdown_rules`/`check_rebalancing_drift`/`volatility_target_scaling`/`apply_fractional_kelly` in
**Tier 3** and `compute_risk_parity_weights` in **Tier 5**; DECISIONS.md's Tier-5 phrasing ("a full
reasoning object **added**") means the object arrives *with* the upgrade. Its absence here is the
un-upgraded state — contrast `econometrics.py` (an already-upgraded Tier-5 module, CARD M-3).

**Class C (the ONE real defect).** `check_rebalancing_drift`'s sum-to-1.0 warning gate was
`if current_contributions and abs(total_actual - 1.0) > 0.01:`. Every other boundary in the module is a
config leaf or a *named, documented* module constant (`_RISK_BUDGET_SUM_TOLERANCE = 1e-9`,
`_CCD_SIGMA_FLOOR = 1e-12`, `DEFAULT_RISK_PARITY_TOLERANCE = 1e-10`). **MEASURED the kill-gap:**
`mutation_rebalancing.py`'s M9.3 replaced the WHOLE branch (`if False:`), so a mutant that **MOVED** `0.01`
survived every test and the sweep — the D-031 shape, and the number is a *policy* choice (how far off a
STATED invariant is warn-worthy), the same class as `risk.rebalancing_drift` six lines up and
`probability.probability_sum_tolerance` (a leaf in the SAME module).

**Fix:** leaf `risk.rebalancing_contribution_sum_tolerance` + accessor + load-time validator (range
`(0, 1]`; `<= 0` warns on everything, `> 1` never fires — the D-128 dead-threshold class) + YAML + rewired
gate. **Killer guards:** `test_the_sum_warning_bound_is_read_from_the_leaf_not_a_literal` — a **mover**
(0.5 suppresses the warning at a 44%-off input, 1e-9 fires on a 1e-7 deviation) — and
`test_the_sum_tolerance_leaf_is_validated_at_load`. **Both kill-proved by hand** (retyping the literal
fails the mover; `if False:` on the validator fails the load test). Sweep: anchors re-pointed, `M9.6`
(retype-as-literal) and `M9.7` (wrong hardcoded bound) added — **both KILLED**; **66 mutations, 0 problems**
(was 64).

## CARD X-1 — `extensions/` (6 files, 239 lines) — CLEAN BY DESIGN

`backtest_vbt` / `bayesian_updater` / `duckdb_store` / `mlflow_tracking` / `nautilus_adapter` / `scheduler`
are all **Phase 5+ stubs** whose body is `raise NotImplementedError(...)` naming the blocked dependency and
the §12 interface contract. This is the **SANCTIONED** pattern (`DECISIONS.md:11446`: *"Phase 4+ stubs —
`raise NotImplementedError`, never return a neutral value"*) — they refuse rather than guess (§21.1). No
action; recorded so the pass is not re-run.

## O-161 MATERIALIZED — the sidecar hazard fired, and it cost real work

`mutation_rebalancing.py`'s startup HEAL restored a **stale `config.py` sidecar** left by an earlier killed
regime run, **silently reverting the D-132 `config.py` leaf** (`grep -c` = 0) — a half-applied tree (the
YAML leaf survived). The killed sweep also left a live leftover mutation in `risk_budget.py` **and** a
separate live leftover in `regime.py` (the contraction guard deleted) — the **O-157** shape. All healed:
live files restored from sidecars, sidecars deleted, the config edit re-applied by hand, verified.
**New HARD rule:** probe `find src -name '*.sweepbackup'` before every `src` edit and after every sweep
exit; never trust "N/N killed" as proof of a clean tree.


# PART 5 — the `thesis_layer/` layer (8 files) + the `api_layer/` cross-cutting findings (2026-09-29, D-132 cont.)

> **Operator directive in force:** *"fix logics math bugs reasoning inputs values integrations all must be
> worked fully and advanced or production or institutional way … no guessing no ambiguity."* Method is
> unchanged: read each file, measure against the 8 classes, fix what is measurably wrong, and record a card.
> **A CLEAN card is a positive measurement** (every class checked and none fired), not an absence of review.

## LAYER VERDICT — `thesis_layer/` (8 substantive files, 4670 lines) — **CLEAN, 8/8**

Every file was read end to end and measured against all 8 classes. **No defect was found**, and the reason
is measurable rather than a judgement: the layer already carries a dedicated mutation sweep per module —
**149 mutants across 8 sweeps** (`mutation_builder` 26, `mutation_scenario_distribution` 29,
`mutation_catalyst_calendar` 22, `mutation_no_trade` 21, `mutation_warnings` 19, `mutation_invalidation`
18, `mutation_confirmation_signals` 14, `mutation_thesis_position`… the last belongs to `portfolio/`). A
module at this standard has already survived the increment that built it.

### CARD T-1 — `thesis_layer/builder.py` (1549) — CLEAN

The seam function. Measured checks that all passed:

* **Class C (input wiring / hardcoded values):** every quantity is a config leaf or a published object
  field. `risk.thesis_demotion_fraction` (L1506), `SIZING_LOGIC_PHASE_1` (L201) and `THESIS_TIMEFRAME_PHASE_1`
  (L224) are **named module constants** (the audit finding B-1 fix — a bare `"6-12 months"` at the
  `TradeIdea` call site was retyped-string drift two lines from a constant that existed for that reason);
  the timeframe gap is **disclosed** (O-75) rather than invented.
* **Class B (reasoning):** the docstring documents **eight measured divergences** between §16.2's sample and
  the shipped contracts, each with the reason the code wins — e.g. `is_meaningful` is read from the gap
  object, not recomputed (two definitions of one predicate would let `gap.is_meaningful` and its own
  magnitude disagree), and `direction` comes from `select_instrument`'s own output rather than §16.2's
  rates-only `raw_gap < 0` rule.
* **Class A/E (math / input-not-taken):** `_gap_direction` refuses an exactly-zero gap (Q6 guarantees
  `abs(raw_gap) > dispersion >= 0`, so reaching it is a contradiction → raise, not a coin-flip default);
  `_family_count` treats `None` as **not** a family (D-046 over-count), so the honest count on a default
  snapshot is `0`, which is a disclosure rather than a claim.
* **Class F (integration):** `_apply_risk_axis` **calls** `translate_thesis_to_position` and re-derives
  nothing; `None` short-circuits to a **disclosed absence** ("the check did not run"), so "unchecked" and
  "checked and clear" cannot read alike.
* **The `assert isinstance(value, dict)` at L1503 is NOT a defect.** It is the project-wide **mypy-narrowing
  idiom** — 32 bare asserts across `src/`, each after a shape is validated or built above (`regime.py:695`
  "narrowing; measured implies a rate", `econometrics.py:2218` "narrowed for mypy"). It is a different class
  from the **real raise** the layer uses where a failure must survive `-O` (`warnings.py:367/374`'s
  `raise AssertionError(...)` for the census). Measured before "fixing" — a convention is not a defect.

### CARD T-2 — `thesis_layer/schemas.py` (720) — CLEAN

`MacroThesis` carries **four** `@model_validator(mode="after")` gates, all with real raises: the LTCM
invalidation gate (L615), CONFLICTED-blocks-trade (L633, Section 22.10 Finding #10 — a hard error, not
advisory), scenario probabilities sum to 1.0 (L652, tolerance read from `validation.prob_tolerance`, **not**
a literal), and status-matches-distribution (L672, both directions). `scenario_sizing_permitted` (L709) is a
**property** so the Section-25 question cannot be inferred wrong. The two-class-name defects (`MarketPricingGap`,
`ScenarioOutcome`, `PayoffUnit`) were closed in D-064 by re-exporting the models-layer class — one
definition, so a producer can feed its consumer.

### CARD T-3 — `thesis_layer/no_trade.py` (433) — CLEAN

**The D-128 dead-threshold class is ALREADY FIXED HERE.** `NoTradeDecision.is_marginal` compared the
shortfall against a literal `1e-9` **percentage-points** — which is `1e-11` bp, unreachable because
`raw_gap` is rounded to 4 decimals upstream — so every real stand-down reported `is_marginal=False` and the
near-miss distinction could never fire. It now reads `policy.ensemble.near_miss_tolerance_bp_value` and
converts with an explicit `* 100.0`. The five §16.4 sample defects are each repaired with a named field
(`trigger` as a closed `Literal`, `evidence` as a typed union, an empty-`reason` refusal, `stop_or_invalidation=""`
not the truthy `"n/a"`).

### CARD T-4 — `thesis_layer/signals.py` + `invalidation.py` (420 + 364) — CLEAN

The two **twins** (`_signed_scalar`) both apply the narrow-first rule (`bool` excluded first, `nan`/`inf`
excluded), and **`tests/thesis_layer/test_signed_scalar_parity.py` fails if they drift** — the exact
mechanism D-063's note predicted ("the two sit in one layer and must not drift"). `signal`'s three-state
`confirms`/`contradicts`/`neutral` replaces the sample's two-state fall-through that published an unreadable
value as an active **contradiction** (D-056 false-confidence direction).

### CARD T-5 — `thesis_layer/warnings.py` + `scenarios.py` + `catalysts.py` — CLEAN

* `warnings.py`: the census invariants use **`raise AssertionError(...)`** (survives `-O`), not a bare
  assert — the correct real-raise shape, and the contrast that proves L1503's assert is the mypy idiom.
* `scenarios.py`: every probability/multiple is a `CalibratedValue` leaf; `scenario_probabilities_are_calibrated`
  reads them as a **set** (so adding a leaf cannot drift); the direction-blindness is disclosed and pinned.
* `catalysts.py`: `404` is `INFO` (expected absence) while 5xx/transport/malformed stay `WARNING` — the
  "an expected absence reported as a failure is how a real failure gets ignored" lesson; the horizon is
  applied **twice** (request + local filter) for a measured reason; `answered` distinguishes reachable-but-empty.

## CROSS-CUTTING X-L1 and X-L2 — **BOTH CLOSED** (measured this pass)

* **X-L1 (the §10.3 logging mandate unimplemented at runtime)** — **CLOSED.** `api_layer/app.py:51-97` now
  installs a `_lifespan` hook that calls `configure_logging()` when the service starts. The recorded defect
  was *"`configure_logging()` … has ZERO callers anywhere in the repo"*; it now has one, in the correct place
  (lifespan, not `create_app()` — applying a process-global logging config as a construction side effect
  would mutate the test process's root logger).
* **X-L2 (a published disclosure asserts a confidence penalty that is NOT enforced)** — **CLOSED.** Both
  halves of the false claim are corrected with measured evidence: `api_layer/snapshot_provider.py:136-145`
  now says *"these flags are NOT applied as a confidence penalty automatically — compute_confidence() reads
  each model's OWN `data_quality_flags_present` input"*, and `data_layer/validation.py:11-32` carries the
  same correction naming the three models that set the boolean from **their own** inputs
  (`commodities.py` from `fetched_legs < 2`, `equity_macro.py` from `not has_prior`, `convergence.py` from
  its constituent signals) and the `grep` that proves no model reads `snapshot.data_quality_flags` into
  `ConfidenceInputs`.

---

# PART 6 — the `api_layer/` route files (4) + root `src/macro_engine/` (3) — 2026-09-29, D-132 cont.

## LAYER VERDICT — `api_layer/` (8 substantive files, 3843 lines) — **7 CLEAN / 1 NEW DEFECT (fixed)**

`app.py` (125), `snapshot_provider.py` (374), `reasoning_stream.py` (339) were CLEAN in PART 5; the four
route modules below were audited file-by-file this pass, plus a re-read of `orchestration.py` that found
the one new defect.

### CARD A-1 — `api_layer/orchestration.py` (1993) — **DEFECT FIXED (Class C)**

**The defect.** `_short_yield_from_curve` (L734 before the fix) admitted a curve value with a **re-typed
literal**:

```python
if not 0.0 < value < 25.0:
    raise OrchestrationError(
        f"... (Section 5.4's max_plausible_yield_pct is 25.0). ...")
```

`25.0` is the value of the config leaf **`validation.max_plausible_yield_pct`**, whose accessor
`validation.max_yield` (`config.py:4850`) is read by `data_layer/validation.py:450` as *the* plausibility
ceiling. So one bound had **two definitions**: the data-layer validator (leaf) and this guard (literal).
The failure mode is silent and one-directional: move the leaf and the data-layer check tightens while this
check keeps admitting up to the **old** value — and the fault this check exists to be loud about is a
units error (bp read as percent), where the difference between 25 and the moved value is exactly what
decides whether a 100× inflation gets caught. The message also **hardcoded** `"is 25.0"`, so the error
text would lie about the bound it named.

**The fix** (`orchestration.py:736-750`): read the leaf, quote it in the message.

```python
max_yield = get_settings().validation.max_yield
if not 0.0 < value < max_yield:
    raise OrchestrationError(
        f"... (Section 5.4's max_plausible_yield_pct is {max_yield:g}). ...")
```

**Behaviour is unchanged today** (leaf = 25.0, measured); the fix removes the drift risk.

**The killer guard (D-031 mover, `tests/api_layer/test_orchestration.py`).** A *pinner* cannot tell a
leaf-read from a re-typed literal — the fixture's 2yr = 4.25 passes `< 25.0` under BOTH forms, and even a
425.0 value fails under both. So the test is a **mover**: monkeypatch `orchestration.get_settings` to set
the leaf to **4.0**, and assert the SAME 4.25 snapshot now **refuses**. If the code still held `25.0` it
would keep admitting and the test fails:
`test_the_yield_ceiling_is_taken_from_config_not_a_literal`.

**Sweep updated.** `scripts/mutation_api_layer.py`'s anchor `_YIELD_RANGE` was the *old* literal text
(`"    if not 0.0 < value < 25.0:"`) — now **stale**, since `check_targets` verifies every anchor against
shipped source. Updated to the shipped `if not 0.0 < value < max_yield:` and added a new
`_YIELD_CEILING_READ` anchor + **M1.3b** (`max_yield = 25.0  # MUTANT`), the D-031 complement: re-typing
the leaf read as the literal that shipped before D-132. M1.3b is killed **only** by the mover test.

**Everything else in the file re-verified CLEAN:** the refusal matrix (every missing series raises
`OrchestrationError` naming the field), the three unit conversions, the m/m convention, the claims 4-week
pairing, the YoY anniversary tolerance, `pi_target=None` (left to the model's own config target).

### CARD A-2 — `api_layer/routes_dashboard.py` (287) — CLEAN

* Reads the config leaf `api.dashboard_series_limit` (L173), never a literal; reports **`points_withheld`**
  per panel so a truncated chart says it is truncated.
* Publishes **measurements, not claims** — the module docstring is explicit that gaps/verdicts/instruments
  belong to `/thesis`, and this endpoint publishes the readings they were made from plus a provenance pointer.
* The `_declared_but_absent` guard turns a **renamed snapshot field** (a code defect that would otherwise
  surface as `"tips_curve": null`, indistinguishable from a data gap) into a named warning. **Measured
  working:** all 20 family fields + 2 curve fields resolve (`hasattr(snapshot, field)` is `True` on the
  *instance*; the class-level `hasattr` returning `False` is a pydantic-v2 quirk — fields live in
  `model_fields`, not as class attrs — and the code correctly tests the **instance**, so the guard is not
  a false alarm). `_declared_but_absent(minimal)` returns `[]`, measured.

### CARD A-3 — `api_layer/routes_health.py` (168) — CLEAN

* The `status`/`ready` split is honest and distinguishable; `ready` is checked **without building a
  snapshot** (the cost is stated: ~10s in-process / ~220s over the API), with `?deep=true` opting into the
  expensive real build.
* `SERVICE_NAME`/`SERVICE_VERSION` are **module constants** read by `/health` and the app factory, not
  literals in two places.
* `country` is the literal `"us"` in both branches with no query param, and **US is implemented**
  (measured: `country.implemented == ['us']`), so the un-caught `NotImplementedError` path is unreachable
  by construction — this is not a missing handler.

### CARD A-4 — `api_layer/routes_query.py` (311) — CLEAN

* Keyword routing that **says so**: `is_keyword_routing` is a machine-readable field, the `answer` is
  phrased as a routing description, and an unmatched question is a **200 with an explicit "no match" note**,
  never a fabricated answer and never a 404 (the route exists; the request was well-formed).
* Three stages, three handlers, three messages — the mapping lives in `routes_thesis._http_status_for`
  and is **imported, not restated**, so the two endpoints cannot drift.
* The warnings are the **union** of `provenance.warnings()` and `inputs.warnings`, deduplicated in order —
  `/query` was the one endpoint that withheld the orchestration's disclosures.

### CARD A-5 — `api_layer/routes_thesis.py` (246) — CLEAN

* `_http_status_for` maps **501** (not implemented), **502** (provider/orchestration) and **re-raises
  everything else** (L157) — it cannot silently swallow an unexpected exception. This is what makes the
  documented invariant *"a `WATCH` thesis is never a failure response"* hold by construction.
* Three-stage error handling identical to `routes_query.py` (shared mapping); builder failures are a
  **500** (a bug here), not a 502 (blaming the data).

## LAYER VERDICT — root `src/macro_engine/` (3 files, 1534 lines) — **3/3 CLEAN**

No mutation sweep owns these. Coverage is by `tests/test_infrastructure.py` (1322 lines): **12** dedicated
audit tests + **13** settings_store tests + the deployment tests.

### CARD R-1 — `audit.py` (396) — CLEAN

* Append-only by **construction** — no update/delete method on `AuditLedger` (pinned by
  `test_audit_ledger_has_no_update_or_delete_method`).
* `record()` **raises** on failure rather than swallowing (a result with silently-missing provenance is
  worse than a visible failure).
* `record_thesis` **refuses** a thesis missing `thesis_id`/`country`/`status`/`convergence_classification`/
  `regime.state` rather than inventing a default (D-015) — pinned by
  `test_record_thesis_does_not_invent_a_country` / `..._a_thesis_id`. The `assert isinstance(regime, dict)`
  at L261 is the documented mypy-narrowing idiom (the guard above it already raised), **not** a defect.

### CARD R-2 — `deployment.py` (566) — CLEAN

* Every external knob is declared **as data** in `_VARIABLES` (enumerable for a runbook/manifest/review).
* `resolve()` **never invents** a value: env wins → declared default → hard failure (unless
  `optional_when_unset`, where `None` is a real answer). The two-way preflight reports **all** unresolved
  variables at once. `api_key_required` with an absent hash is refused **at construction**.
* `_OPENBB_DEFAULT_BASE_URL` is duplicated (this module imports nothing from `config`) **on purpose**, and
  pinned to `openbb.local_api_base_url` by `test_the_two_openbb_defaults_agree` (O-113).

### CARD R-3 — `settings_store.py` (572) — CLEAN

* `set()` refuses an unknown `value_type`, an empty `actor`, an empty `reason` (L375-388) — an
  unattributed change is refused, not defaulted.
* Monotonic timestamp bump inside the session (L415-424, L508-517) prevents two same-microsecond writes
  collapsing a `value_at` interval to nothing — a subtle correctness fix, pinned by
  `test_consecutive_writes_are_strictly_ordered`.
* `delete()` is retire-as-update (never physically deletes); `SettingSnapshot`'s validator enforces that a
  **database**-sourced snapshot carries `revision` + `changed_at`.

---

# PART 7 — the two `data_layer/` files with NO card (2026-09-29, D-132 cont.)

PART 3's scope named five untouched data_layer files; a `grep` of the CARD headers shows `schemas.py`
(445) and `snapshot_builder.py` (935) were only ever **referenced**, never given their own card. They are
the two largest un-carded files, and `snapshot_builder.py` is the central assembly hub the P-1/P-2 defect
chain runs through, so both are audited here. **Both CLEAN.**

## CARD D-6 — `data_layer/schemas.py` (445) — CLEAN

* `ObservationPoint.value` refuses a non-finite value at **construction** (`allow_inf_nan=False`); the
  docstring states why a `nan` is *poisoned*, not missing (§21.0 rule 2): every downstream guard sees a
  present, testable float, so nothing degrades to INSUFFICIENT_DATA and the model silently computes `nan`.
* `YieldCurveSnapshot._reject_unknown_tenors` refuses **both** an unknown tenor label **and** a non-finite
  yield — the D-074.1 mechanism applied to the curve, since every `validate_yield_curve` comparison is
  False for `nan` (so a poisoned tenor would report the curve CLEAN).
* `iter_scalar_series` / `iter_curves` / `assert_finite` are **schema-derived** (iterate `model_fields`),
  so a new field is covered the moment it is declared — the pluggability contract. `assert_finite` covers
  **both** the list shape and the curve shape; the one-shape hole (a `nan` tenor passing the guard) is
  documented as the reason `iter_curves` exists.
* The X-L2 correction is present on `data_quality_flags` (L344-360): *"this list is NOT what
  compute_confidence() reads"*.

## CARD D-7 — `data_layer/snapshot_builder.py` (935) — CLEAN

* **Registry is the only routing source** — no provider/symbol/endpoint literal appears; a re-point is a
  config edit. `resolve_snapshot_field` + `_assert_field_exists` force registry↔schema agreement **at the
  point of use**, so a registry field the schema lacks raises rather than `setattr`-ing into a Pydantic
  refusal.
* `_points_from_frame` and `fetch_curve` apply `unit_scale` (D-086) at the **single** site where a raw
  provider value becomes a published value — one conversion site, so no second site can drift.
* `fetch_curve` carries the **O-7 forward-dated filter** (the load-bearing guard): every tenor is filtered
  to `observation_date <= as_of` before its latest point is read, and it **refuses** rather than
  interpolates a partial tenor mapping, attributes rows by the provider's `maturity` label (never by
  position), and raises when a tenor's whole history is forward-dated.
* `_resolve_release_index` keeps the `release_calendar_read` flag **tri-state** (True / False / None) with
  the outage-vs-never-asked distinction; the docstring records the exact conflation bug it fixed (the
  primary path only ever set `True`, so a total `publication_dates` outage read as a clean snapshot).
* `build_snapshot` validates `country in implemented` and **raises `NotImplementedError`** (§22.3),
  refuses an empty field list, and `assert_finite()` is the **last chokepoint every path shares** (a
  snapshot can also arrive from a cache or parquet round-trip). Per-field failures are caught
  (`OpenBBFetchError` and a bounded `except Exception`) and recorded, so one series failing never kills
  the snapshot — graceful degradation with an audit trail, never silent.
