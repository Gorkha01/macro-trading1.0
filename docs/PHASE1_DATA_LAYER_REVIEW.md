# Phase 1 — Data Layer Review (production-grade)

**Decision:** `D-137`. **Status:** COMPLETE. **Date:** 2026-09-29.
**Scope:** every file in `src/macro_engine/data_layer/` (14 files, ~6 441 lines),
reviewed file-by-file, against the live OpenBB stack on both transports.

This is Phase 1 of the operator's production-grade review (Phase 0 → 5). Phase 0
(`D-136`) closed performance + sweep/CI safety. Phase 1 is the **data layer** —
the seam between OpenBB and the models (`AGENTS.md` §5). The standing rule
applies: trace real logic from first principles, fix at root cause, verify against
**live** data (no placeholders), and re-derive every gate at CI scope before
declaring done.

---

## 1. Method

1. Read all 14 data-layer source files in full (not sampled).
2. Read `AGENTS.md` §5 (data-layer spec) and `config/series_registry.yaml`
   (59 series keys) to establish the contract.
3. Resolved the open question from the Phase 0 handoff — are the
   `fx_spot` / `commodity_spot` / `equity_index` dict fields reachable from the
   build path? (§4 below.)
4. Built a live snapshot end-to-end against the real OpenBB service, exercising
   **both** transports: the `openbb` **package** path and the **local API**
   (`http://127.0.0.1:6900`) path.
5. Re-derived every gate at CI scope (§5).

## 2. Files reviewed

| File | Lines | Role |
|---|---|---|
| `schemas.py` | 446 | `ObservationPoint`, `YieldCurveSnapshot`, `MacroDataSnapshot`; finiteness + point-in-time provenance |
| `openbb_client.py` | 717 | Two-path `OpenBBClient` (local API / package), normalize, provenance |
| `alfred_client.py` | 456 | Direct FRED ALFRED vintage fetch (no OpenBB, deliberately) |
| `snapshot_builder.py` | 935 | The one place a `MacroDataSnapshot` is assembled from registry-verified series |
| `validation.py` | 647 | Flag-don't-fix checks (finiteness, future-dating, range, staleness, curves) |
| `persistence.py` | 445 | Parquet long-format write/read, snapshot round-trip |
| `commodities_client.py` | 1024 | Oil / gold / metals observables via OpenBB `economy`/`commodity` routes |
| `world_bank_client.py` | 580 | PPP factor, current-account, reserves/debt — direct World Bank REST |
| `reserves_client.py` | 315 | BIS/IMF FX-reserve stocks (millions→billions in the model) |
| `release_calendar.py` | 328 | Section 6 release-timing fallback (events join) |
| `publication_dates.py` | 298 | Section 6 release-timing **primary** (`last_updated` per series) |
| `logging_json.py` | 251 | Structured JSON audit logging, credential redaction |

(`__init__.py` is empty.) Every file is heavily documented and the logic is sound;
the one genuine defect found is in §3.

## 3. Defect found and fixed — `publication_dates` resolves non-FRED symbols

**Symptom (live):** every `build_snapshot` emitted 7 warnings of the form
`publication date for <X> attempt N/3 failed: Expecting value: line 1 column 1
(char 0)` — i.e. 21 failing HTTP calls per build (7 series × 3 retries).

**Root cause:** `publication_dates._resolve_series_symbols()` resolved *every*
registry entry that had a `symbol` and was not a `tenors` curve — **regardless
of provider**. But the route it feeds is the FRED-only `economy.fred_search`
endpoint. The 7 symbols that are not FRED series — `WCESTUS1` (EIA),
`COPS_OPEC` (EIA), `PA.NUS.PPP` (World Bank, ×2), `BN.CAB.XOKA.GD.ZS`,
`FI.RES.TOTL.CD`, `DT.DOD.DSTC.CD` (World Bank) — are all `provider != "fred"`
and `not_a_snapshot_field: true`. The lookup against them returns a non-JSON
body that cannot be parsed, so every attempt fails with a `JSONDecodeError`.

**Why it is a real defect, not noise:** 21 wasted failing calls per build, plus
misleading warnings that look like a data-source outage when the only truth is
"no FRED `last_updated` exists for this symbol" (which is correct, and the
release timing already degrades to UNKNOWN by design).

**Fix:** `_resolve_series_symbols()` now also requires `entry.provider == "fred"`
(the route is FRED-specific). The 7 non-FRED symbols are excluded at the source,
so the wasted calls and warnings disappear; their release timing still correctly
stays UNKNOWN.

**Verification:** re-ran the live probe after the fix — the 7 warnings are gone,
and FRED series still resolve and attach `release_datetime`. Added regression
test `test_resolve_series_symbols_only_keeps_fred_provider_entries` (asserts a
FRED series is kept, the 4 non-FRED symbols are excluded, and every resolved
entry is `provider == "fred"` and non-tenor).

## 4. Open question resolved — the three dict fields are schema placeholders

The Phase 0 handoff flagged that `fx_spot` / `commodity_spot` / `equity_index`
appear in `MAPPING_SERIES_FIELDS` / validation but **no registry key routes to
them** (the only `snapshot_field` alias in the registry is `treasury_curve →
yield_curve`).

**Finding:** these three are `dict[str, list[ObservationPoint]]` fields on
`MacroDataSnapshot`, validated defensively by `validate_snapshot` **if present**,
but they are **never populated by `build_snapshot`** — that function only fills
scalar + curve fields. Their values come from the dedicated provider clients
(`commodities_client`, `world_bank_client`, `reserves_client`), which return
dataclass *readings* (not `ObservationPoint` lists) and are `not_a_snapshot_field:
true`. They are future multi-asset fields for the post-Phase-4 (Tier 5)
programme; for a US-only Phase 0–4 thesis they are legitimately empty.

**Action:** documented as such. No code change — the gap is by design, not a
defect. A reader must not mistake an always-empty dict for missing data. (Note:
`assert_finite` / `iter_scalar_series` deliberately does not iterate these dict
fields, so a non-finite value placed there by future code would evade the
guard — recorded as a known limitation, not patched, because nothing populates
them today.)

## 5. Live verification — both transports return correct, identical data

Built `MacroDataSnapshot` for `cpi_headline`, `unemployment_rate`,
`fed_funds_rate`, `treasury_curve` against the live service.

| Field | Value | Date | Package source | Local-API source |
|---|---|---|---|---|
| `cpi_headline` | 334.131 | 2026-08-01 | `openbb:package` | `openbb:http://127.0.0.1:6900` |
| `unemployment_rate` | 4.1 | 2026-08-01 | `openbb:package` | `openbb:http://127.0.0.1:6900` |
| `fed_funds_rate` | 3.63 | 2026-08-01 | `openbb:package` | `openbb:http://127.0.0.1:6900` |
| `treasury_curve` | 11 tenors (1mo…30yr) | as_of 2026-09-25 | `openbb:package` | `openbb:http://127.0.0.1:6900` |

Both transports returned **identical** values and populated `yield_curve`
correctly (the `treasury_curve` registry key resolves to the `yield_curve`
schema field via `snapshot_field`). `validate_snapshot` reported `has_errors =
False`, `0` findings, on both. Provenance is correctly tagged per transport
(`openbb:package` vs `openbb:http://127.0.0.1:6900`), satisfying the
"every number carries provenance" rule.

## 6. Gates (re-derived at CI scope — all green)

| Gate | Result |
|---|---|
| `ruff check src/ tools/ tests/ scripts/` | PASS |
| `ruff format --check src/ tools/ tests/ scripts/` | 295 files clean |
| bare `mypy` (CI scope, `--strict`) | Success: no issues in 294 files |
| `reachability_audit.py --check-baseline` | PASS 58/58 |
| full suite `pytest -m "not live"` | **4243 passed / 23 skipped / 16 deselected / 0 failures** |
| `sweep_health.py` | OK — 52 sweeps, 0 leftovers, 0 mutant shapes, 0 committed mutants, 0 failures |

`src/` modified only in `publication_dates.py`; no `.sweepbackup` sidecars after
any run; the source tree was clean before and after the sweep census.

## 7. Residual risk / next phase

- The three dict fields (§4) remain placeholder; their `assert_finite` gap is a
  known limitation, surfaced for when they are wired in (Tier 5).
- The Phase 0 performance finding (per-mutation process spawn) is unchanged and
  deferred to a Phase 1+ structural refactor — documented, not masked.
- **Phase 2** (next): review the `models/` layer file-by-file under the same
  standard, with live-data verification of each model's inputs.
