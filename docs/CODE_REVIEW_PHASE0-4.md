# Comprehensive Code Review — Phase 0 → Phase 4

**Date:** 2026-09-20
**Scope:** `src/macro_engine/`, `config/`, `scripts/`, tooling — Phase 0 through Phase 4
**Mode:** READ-ONLY. **No file under `src/` was modified for this review.** Verified with
`git diff --stat HEAD -- src/` (empty at time of writing).
**Method:** every finding below was reproduced by reading the cited source and, where a
numeric claim is made, by executing the function under `uv run python` against the real
package. Findings that turned out to be intentional design decisions are listed in
§7 (Rejected / intentional) so they are not re-investigated.

---

## 0. How to read this report

Severity is graded against **this project's own standard**, not a generic one:

| Severity | Meaning in this codebase |
|---|---|
| **CRITICAL** | Produces a *wrong number or wrong verdict* on the thesis path with no warning, or violates a §21.0 / §22.x invariant. Blocks sign-off release. |
| **HIGH** | Produces a wrong number on a path a caller can reach, or a cross-phase contract is broken such that data is silently absent/defaulted. |
| **MEDIUM** | Wrong on an untested/unusual input, or a robustness/consistency gap that degrades a disclosure. |
| **LOW** | Cleanliness, dead code, documentation-scope, or single-instance fragility. |

**Cross-phase data-availability / data-consumption problems are flagged with
`[CROSS-PHASE]`** and collected in §3.

**Headline result:** the review found **3 HIGH** defects with directly executable proofs —
two of which produce a *materially wrong number* from a public, exported function — plus a
**systemic cross-phase finding**: of **76 `ModelResult`-returning functions**, only **17**
are reachable from `api_layer` / `thesis_layer`. The 59 unreachable ones are a mixture of
legitimate Phase-5 deferrals and **genuinely orphaned spec-mandated thesis inputs** (§3).

---

## 1. Findings grouped by CATEGORY

### Category 1 — Math / Reasoning Bugs

| # | Phase | File / Area | Sev | Description |
|---|---|---|---|---|
| **1.1** | 4 | `models/risk.py:182-192` — `z_score_for_confidence` | **HIGH** | **Below-0.90 branch interpolates off the wrong anchor and is discontinuous.** `upper` is bound to `points[-1]` (0.999) but the branch is entered when `confidence < points[0][0]` (0.90). The return is `3.0902 · c / 0.999` — the secant through the origin and the **0.999** point, not the first segment (0.90→0.95) the docstring claims. **Measured:** `z(0.899) = 2.7809` vs correct `1.2789` — **a 2.17× overstatement**, and discontinuous across the tabulated point (`z(0.90)=1.2816`, `z(0.899)=2.7809`). Propagates directly into `parametric_var` (`risk.py:364`) via `var_loss = z·σ·√h`, so any caller with `confidence < 0.90` gets a VaR ~2× too large. **Why it survived:** `tests/models/test_risk.py:166-179` only exercises the tabulated points (0.90/0.95/0.99) and the *upper* boundary (0.9999/1.0); the interior-below-0.90 region is untested. The docstring's stated justification ("below 0.90 the normal quantile is small and well-behaved") is contradicted by the arithmetic. **Fix (description):** replace the tail branch with a true secant through the two lowest tabulated points, or refuse `confidence` below `points[0][0]` exactly as it already refuses values above the maximum. |
| **1.2** | 3 | `thesis_layer/invalidation.py:182-193` — `_signed_scalar` | **HIGH** | **The sibling narrower lost its non-finite guard, so `nan`/`inf` produce a confident falsifier — the exact defect `signals.py` was fixed for (D-078).** `signals._signed_scalar` (`signals.py:255-257`) excludes non-finite values via `isfinite`, and its own docstring states *"the two functions sit in one layer and must not drift"* (D-063). `invalidation._signed_scalar` applies **only** the `bool` guard and returns `float(value)` for any `int`/`float`, including `nan`/`inf`. Downstream in `_condition_for_scalar` (`invalidation.py:221-228`): for `nan` both `value > crossing` and `value < crossing` are `False`, so it returns `None` → the signal is reported **neutral** ("sits exactly on the crossing") from a value that was never computed; for `inf`, `value > crossing` is `True` → it emits a confident **`crosses_back_negative`** falsifier ("crosses back below 0.5") from an unbounded reading. Both are published on `InvalidationAssessment`, which reaches the no-trade decision's `evidence` (`builder.py:872`). **Fix (description):** give `invalidation._signed_scalar` the same `isfinite` guard and route non-finite values to an `unreadable`/absent outcome rather than `neutral`. |
| **1.3** | 3 | `thesis_layer/no_trade.py:283` — `is_marginal` | **MEDIUM** | **`is_marginal` is a no-op predicate and can never be `True`.** It returns `0.0 <= self.elapsed <= 1e-9`, where `elapsed = gap.dispersion - abs(gap.raw_gap)` (`no_trade.py:368`) is measured in **percentage points** and is only computed when `abs(raw_gap) <= dispersion`, i.e. it is the *distance inside* the noise floor. A tolerance of 1e-9 in **pp** is 1e-13 of a basis point — unreachable for gaps rounded to 4 decimals upstream (`policy_rules.py:667`). The property's docstring describes it as *"a gap that missed the significance bar by a hair"*; that hair is ~1e-11 pp. **Every real stand-down reports `is_marginal=False`**, so the near-miss distinction the field exists for cannot ever fire. **Fix (description):** express the tolerance in basis points or in units of `dispersion` (e.g. `elapsed * 100 <= <configured bp tolerance>`) so a genuine near-miss is detectable. |
| **1.4** | 4 | `models/risk.py:250, 264-269` — `effective_tail_observations` | **LOW-MED** | **A fractional expectation is published as an observation count, and the flag is off at exactly its own boundary.** `effective_tail_observations = observations · (1 − confidence)` gives `1.5` for n=30 @ 95% and is formatted as *"Only 1.5 observations lie in the tail"* — an integer fact stated as a real number. It is then compared `< 5` to set `data_quality_flags_present`; at n=100 @ 95% the product is exactly `5.0`, so the flag is `False` while the actual tail membership (`_quantile` at `fraction=0.05` interpolates at position 4.95) is **5**. The guard is off by exactly the boundary case it exists to catch. **Fix (description):** count actual tail membership (`sum(1 for r in sorted_returns if r <= tail_quantile)`) and use that integer for both the warning text and the flag. |
| **1.5** | 4 | `models/risk.py:713` — Euler identity check | **LOW** | **Relative tolerance is scaled by `max(1.0, variance)`, so it degrades to an absolute `1e-9` for small portfolios.** Covariance entries are decimal-squared, so a low-vol book has `variance ~ 1e-4` and the check collapses to ~1e-5 relative. Accumulated summation error over `n²` terms can trip the check on a valid PSD matrix, and it then raises a message asserting a mathematical impossibility ("equal by Euler's theorem for any positive semi-definite matrix") — misattributing a float artefact to the caller's input. **Fix (description):** use a relative tolerance on `variance` alone (`1e-9 * max(abs(variance), tiny)`) so the bound scales with the compared quantity. |
| **1.6** | 3 | `thesis_layer/signals.py:231` vs `invalidation.py:182` | **MEDIUM** | (same root cause as 1.2, listed here for the category view) Two functions documented as *must not drift* have drifted. |

> Verified-correct (NOT defects), recorded so they are not re-opened:
> Taylor rule hand-calc `r*=0.5, π=3%, target=2%, gap=+1% → i=4.5%` reproduces exactly;
> §22.4 canonical gap `median{3 rules}` / `dispersion = values[2]−values[0]` /
> `is_meaningful = |gap| > dispersion` in `policy_rules.canonical_policy_gap` is exact;
> `bond_math` discounting/annuity/Macaulay→modified conversions; `national_accounts`
> Laspeyres/Paasche/Fisher; `probability.expected_value` `[0,1]` bounds;
> `real_policy_rate` `nominal − inflation` sign; `inflation_dynamics` Phillips sign
> (`gap = u − u*` → positive u-gap gives below-expectations inflation).

### Category 2 — Mechanics / Flow Bugs

| # | Phase | File / Area | Sev | Description |
|---|---|---|---|---|
| **2.1** | 3 | `api_layer/reasoning_stream.py:184-190` | **MEDIUM** | **The SSE generator has an unguarded region between its two `try` blocks.** `get_snapshot` (112-121), `snapshot_to_thesis_inputs` (158-167) and `build_us_macro_thesis` (209-222) are each individually guarded and each yields `[DONE]` before returning — so the module's docstring claim *"every failure becomes a final event with `status="error"` followed by `[DONE]`"* holds for those three. But `build_policy_gap` at line 187 is called **outside** any `try`, and it raises by design: `builder.py:379/420` raises `TypeError`, and `_gap_direction` (`builder.py:1148`) raises `ValueError` on a zero gap. The `_event(...)` string-building calls (123-135, 236-253) are likewise unguarded. If any of these raises, the async generator propagates mid-stream, the `[DONE]` at line 256 is never yielded, and the client receives a **truncated SSE body with no terminal event**. Starlette closes the connection, so it is detectably-truncated rather than a hang — but the module's own contract is not met. **Fix (description):** wrap the whole generator body in one outer `try/except Exception` that yields an `error` event plus `[DONE]` and returns, keeping the per-step handlers for specificity. |
| **2.2** | 3 | `api_layer/reasoning_stream.py:100, 260-280` + `snapshot_provider.py:312` | **MEDIUM** | **A multi-minute blocking build runs inside `async def`, blocking the event loop.** `reasoning_step_generator` is `async` but contains **no `await`**; it calls the fully synchronous `get_snapshot` / `build_us_macro_thesis`. With `build_snapshot` measured at **223.6s** over the local OpenBB API (the module's own docstring), a single `/thesis/.../stream` request blocks the loop for the whole build — so a concurrent `/health` (whose entire job is liveness) cannot be answered while a thesis is building. The same pattern is in `routes_thesis.py:190`, `routes_query.py:211`, `routes_dashboard.py:164`. **Fix (description):** declare these handlers `def` (Starlette then runs them in its threadpool) or wrap the blocking calls in `run_in_threadpool` / `asyncio.to_thread`. |
| **2.3** | 3 | `api_layer/reasoning_stream.py` (whole module) | **MEDIUM** | **No heartbeat/keepalive frame exists anywhere.** One `fetch_data/started` frame is emitted *before* the blocking call, then nothing until `done` up to 223.6s later. Intermediaries and browsers commonly drop idle SSE connections well before that, and the client cannot distinguish "still building" from "hung". The blocking call also prevents any flush. **Fix (description):** emit periodic `: keepalive` comment frames and/or move the build off the event loop so the response can flush. |
| **2.4** | 2 | `models/regime.py:478-524` — `_select_state` | **LOW** | **The docstring's cell grid omits the `gap < −band` row of the `above_trend` axis.** The table at lines 419-429 shows `above_trend / gap > band` and `/ −band ≤ gap ≤ band` but not `/ gap < −band`; the code's final branch returns `disinflation` for `gap = −1.2` (measured). The result is off-grid relative to the documented table, though it is directionally defensible for a soft-landing read. The docstring's "three deliberate asymmetries" narrative covers only `gap > band`. **Fix (description):** add the missing row to the table (or fold `gap < −band` into the near-trend branch deliberately) so the documented grid is total. |
| **2.5** | 3 | `thesis_layer/builder.py:1029, 1075-1076` | **LOW** | **`_render(..., selection=...)` is an inert parameter.** It is declared with default `None` and consumed at 1075-1076, but **no call site ever passes it** (Q6 at 836-847, Q7 at 854-867, Q8 at 873-888 all omit it). Consequence: a Q7/Q8 stand-down cannot carry the instrument-selection warnings a live thesis at the same gate would. This is *correct* in outcome (selection has not run at those gates), but the dead parameter conceals it and will mislead the next editor. **Fix (description):** delete the parameter, or run selection before Q7/Q8 if its warnings are meant to travel. |

### Category 3 — Data Validity Issues

| # | Phase | File / Area | Sev | Description |
|---|---|---|---|---|
| **3.1** | 1/4 | `config/series_registry.yaml:447, 597` + `models/policy_rules.py:903, 952-953` | **MEDIUM** `[CROSS-PHASE]` | **`on_rrp_level` and `on_rrp_volume_bn` bind the SAME FRED series (`RRPONTSYD`) but only one is a snapshot field — and the model reads the one that is never populated.** `on_rrp_volume_bn` (line 447) → `RRPONTSYD`, `billions_usd`, is a snapshot field. `on_rrp_level` (line 597) → `RRPONTSYD`, `billions_usd`, **`not_a_snapshot_field: true`**. `qe_qt_stance` reads `inputs.on_rrp_level` (`policy_rules.py:952-953`) as its facility-drain test. Because `on_rrp_level` is excluded from `MacroDataSnapshot` by the guard at `snapshot_builder.py:178-184`, no snapshot ever carries it — so the drain test can only fire when a caller hand-supplies the value. Since `BalanceSheetInputs` is constructed **only in `tests/` and `scripts/`** (§3.2), the production path never supplies it. Two consequences: (a) the same physical series is declared twice under two names with different roles, and the *role* difference is not enforced by the type system; (b) the model input that Section 22.11's escalation depends on is unreachable in production. **Fix (description):** either promote `on_rrp_level` to a snapshot field (it is a distinct *role*, not a distinct series) and thread it through `snapshot_to_thesis_inputs`, or have `qe_qt_stance` read `on_rrp_volume_bn` explicitly and delete the duplicate declaration. |
| **3.2** | 1 | `data_layer/persistence.py:251-253` | **MEDIUM** | **Every persistence failure is converted to `None`, and the caller ignores it — a silent audit-trail hole.** `except Exception as exc: logger.error(...); return None` is the broadest swallow in the reviewed set, and the caller at `snapshot_builder.py:661-662` discards the return value. A failed write is therefore invisible to the snapshot, the report, and every flag list: the build reports success while no audit record exists. The module docstring justifies swallowing ("must not abort the thesis computation") — that is a reasonable *policy* — but there is no compensating disclosure. **Fix (description):** return a status the caller records as a `PERSISTENCE_FAILED` data-quality flag rather than overloading `None` for both "disabled" and "failed". |
| **3.3** | 1 | `data_layer/persistence.py:90-99, 270-295` | **MEDIUM** `[CROSS-PHASE]` | **Persistence round-trip drops `release_datetime`/`vintage_datetime`, so a reloaded snapshot loses exactly the §6 fact it was built to carry.** `long_frame_from_snapshot` writes only the seven `_LONG_COLUMNS` (`country, snapshot_as_of, field, series_id, observation_date, value, source, retrieved_at`); `release_datetime` is absent, and `points_for` reconstructs `ObservationPoint(...)` without it. `has_known_release_timing` (`schemas.py:131-141`) therefore flips **True → False for every point** across a round-trip, silently discarding the primary source's 42/42 release coverage. The docstring explicitly justifies *not* round-tripping `data_quality_flags` (they are re-derived), but `release_datetime` is a property of the **observation**, not of the validation run, and it is not re-derived either. `field_sources` (populated at `snapshot_builder.py:638`) has the same problem. **Fix (description):** add `release_datetime` to `_LONG_COLUMNS` and restore it, or document explicitly that reloaded snapshots are release-timing-blind. |
| **3.4** | 1 | `data_layer/publication_dates.py:270-274` + `schemas.py:132-141` | **MEDIUM** | **A total outage of the release-date source is indistinguishable from "no series has metadata", and is flagged data-clean.** `route_read = bool(dates)` is the only status returned. When *every* series exhausts its retry budget, `dates` is empty → `route_read=False` → `snapshot_builder._resolve_release_index` (484-487) leaves `release_source=None` and `release_calendar_read=None`; `as_flags()` then emits **no flag**, because its only branch is `release_calendar_read is False` and its comment states `None` means "never attempted… NOT a data-quality defect". So a configured, enabled, attempted, 100%-dead primary source yields a snapshot whose release timing is entirely unknown **and which is flagged clean**. Partial failures are reported to the logger only. **Fix (description):** return an explicit route-health signal so a total outage maps to `release_calendar_read=False` and raises `RELEASE_TIMING_UNKNOWN`. |
| **3.5** | 1 | `data_layer/snapshot_builder.py:416-439` vs `validation.py:574-601` | **MEDIUM** | **The same series gets two different verdicts: build-time bounds vs re-validation honours `signed_series`.** `_apply_validation` passes both bounds unconditionally; `validate_snapshot` suppresses the lower bound when `entry.signed_series` is set (`credit_spread_hy`/`credit_spread_ig`, registry lines 478/494). Both are in `SCALAR_SERIES_FIELDS`, so both are reachable by `validate_snapshot` via `_validated_scalar_series`. A legitimate negative spread *change* is an ERROR at build time and clean on re-validation — this is the AUDIT-001 defect class surviving in the mirror direction. **Fix (description):** reuse one shared bound-derivation helper so `signed_series` is honoured identically on both paths. |
| **3.6** | 1 | `data_layer/snapshot_builder.py:359-380` — `fetch_curve` | **MEDIUM** | **The O-7 filter runs before de-duplication and compares a calendar date against an instant.** `realised_positions` is computed from the frame as delivered; `_normalize` sorts but never de-duplicates, and `validation.py:227` documents that providers emit revised **and** original rows for the same date. `max(..., key=...)` picks the **highest index** among equal maxima (the last duplicate delivered, arbitrary) — while a scalar series over the same date yields *both* rows, so a curve tenor and a scalar can disagree. Separately, `cutoff = (as_of or utc_now()).date()` discards the time component, so a projection dated the same calendar day as `as_of` is admitted as a *realised* yield — precisely the O-7 outcome the docstring says the filter prevents. **Fix (description):** de-duplicate by date (deterministically) before selecting the latest, and compare on the full instant. |
| **3.7** | 1 | `data_layer/snapshot_builder.py:335-336` + `schemas.py:35-47` | **LOW-MED** | **A partially-populated curve is silently accepted.** `fetch_curve` only raises on **zero** tenors; `CANONICAL_TENORS` declares **eleven** required tenors and neither the builder nor `validate_yield_curve` checks that all eleven are present. `as_flags` reports `EMPTY_SERIES` for a curve missing one tenor only if the count is zero. Per the module's own standard ("a series that cannot be fetched is recorded as an explicit absence"), a missing tenor is unremarked. **Fix (description):** compare each curve's tenor set against `CANONICAL_TENORS` and flag the difference. |
| **3.8** | 1 | `data_layer/snapshot_builder.py:288, 348` → `openbb_client.py:267-268, 283-290` | **MEDIUM** | **`start_date=None` is forwarded as a literal, and the lookback window may be honoured on one transport and not the other.** `fetch_field`/`fetch_curve` build `params={"symbol": ..., "start_date": start}` where `start: str | None = None`. The local-API path forwards the dict as a query string (a `None` becomes the literal `"None"` — UNCONFIRMED whether OpenBB rejects or ignores it), while the package path calls `target(**params)`, i.e. `start_date=None` — a different call shape from omission. No code in `openbb_client.py` normalises or validates this parameter, so the fetched history can differ depending on which transport served the request. **Fix (description):** drop `None` keys from `params` before dispatch and normalise the date-window parameter name per transport. |
| **3.9** | 3 | `thesis_layer/invalidation.py:337` | **LOW** | **`InvalidationAssessment.as_of` is wall-clock, not the thesis stamp.** `derive_invalidation_conditions` takes no `as_of` and stamps `utc_now()`, while every other object in the build is stamped from the builder's `stamp = as_of or utc_now()` (`builder.py:820`) — the snapshot's timestamp. On a snapshot replay (`build_us_macro_thesis(..., as_of=<past>)`) the assessment claims to be *newer* than the thesis it belongs to. **Fix (description):** thread the builder's `stamp` through as an `as_of` parameter and use it. |
| **3.10** | 1 | `data_layer/openbb_client.py:469-473` | **LOW** | **`to_observation_date` is dead code with the classic `datetime`-is-a-`date` trap.** `isinstance(value, date)` is `True` for a `datetime`, which then leaks a `datetime` out of a function annotated `-> date`. Exported in no `__all__` and called nowhere in `src/`. The correct pattern (test `pd.Timestamp` **before** `date`) is used at `snapshot_builder.py:240-245`, so this inverts it. **Fix (description):** delete it, or narrow the guard to `type(value) is date`. |

### Category 4 — Integration Issues

| # | Phase | File / Area | Sev | Description |
|---|---|---|---|---|
| **4.1** | 3→4 | `thesis_layer/invalidation.py:14, 81` + `signals.py:27-53, 133` | **MEDIUM** `[CROSS-PHASE]` | **The convergence verdict travels as a `dict`-valued `ModelResult`, and two consumers read it with different vocabularies.** `invalidation.py` imports `CONVERGENCE_CLASSES` and reads the verdict dict; `signals.py` (133) documents that it reads the same classifier's verdict for `("inflation_convergence", "contradicts")`. The three call sites (`signals`, `invalidation`, `scorecard`) each re-derive the membership test rather than sharing one accessor, which is the drift surface that produced 1.2. **Fix (description):** publish one typed accessor (e.g. `convergence_verdict(result) -> ConvergenceClass | None`) and have all three consumers call it. |
| **4.2** | 2 | `models/scorecard.py:369-377` vs `models/convergence.py:351-366` | **LOW-MED** | **Two sibling classifiers documented as kept-in-agreement disagree on the `LOW` reason.** In `scorecard.py` the `else` branch selects its reason by re-testing `independent_families < medium_family_floor`; because the MEDIUM gate requires **both** that and `dissent <= medium_dissent_ceiling`, falling through can mean either failed. When `dissent` was the cause but families are also low, the emitted reason claims *"agreement exists but is under-corroborated"* — false. `convergence.py` orders the tests correctly (family test as its own `elif`). Both docstrings say the two are deliberately symmetric. **Fix (description):** give `scorecard.py` the same three-way `elif` structure as `convergence.py`. |
| **4.3** | 3 | `api_layer/routes_query.py:222-231` vs `routes_thesis.py:209-221` | **MEDIUM** | **The same builder failure is reported in two different shapes across endpoints.** `/thesis/{country}` catches the builder and returns **500** with a diagnostic `detail`. `/query` wraps `build_us_macro_thesis` in the same `try` as the snapshot/orchestration calls and only catches `NotImplementedError`/`SnapshotUnavailableError`/`OrchestrationError` — a builder raise falls through entirely and escapes as an unhandled 500 with a stack trace and **no `detail`**. Two endpoints calling one builder report one failure two ways, and one leaks a traceback. **Fix (description):** add an explicit builder `except` branch in `/query` mirroring `/thesis`'s 500-with-detail. |
| **4.4** | 3 | `api_layer/routes_query.py:210-221, 254-256` | **MEDIUM** | **`/query` conflates three stages into one 502 and publishes a truncated warning set.** One `try` spans `get_snapshot`, `snapshot_to_thesis_inputs` and `build_us_macro_thesis`; the `except (SnapshotUnavailableError, OrchestrationError)` produces one message either way, though the two classes are deliberately distinct (`snapshot_provider.py:53-65`: source did not answer vs data unusable) and `/thesis` preserves the distinction. The `snapshot` binding at line 211 is never used — the only visible trace that the stages were conflated. `/query` also publishes `warnings=list(provenance.warnings())` only, while `/thesis` publishes `provenance.warnings() + inputs.warnings`; the orchestration's disclosures (curve-legs-ignored, unit traps; `orchestration.py:1692-1698`) are silently absent. **Fix (description):** split into per-stage `try` blocks with stage-naming messages, and publish the same warning union `/thesis` builds. |
| **4.5** | 3 | `api_layer/routes_dashboard.py:222-226, 96` | **MEDIUM** | **A renamed snapshot field degrades to a null panel with no warning, and `CurvePanel.units` is a literal.** `_curve_panel`/`_points_for` use `getattr(..., None)` with a silent `[]`/`None` fallback, so a snapshot field rename (D-005 records exactly this class of `treasury_curve`→`yield_curve` alias drift) yields `"tips_curve": null` with **nothing** in `DashboardData.warnings` naming the missing field — the client renders an absent panel as a data-free chart. `CurvePanel.units` defaults to the literal `"percent"` (line 96) and is never read from the snapshot, so the units claim is an assumption rather than a measurement. **Fix (description):** collect not-found field names into an explicit `DASHBOARD FIELD MISSING` warning, and source `units` from the snapshot. |
| **4.6** | 3 | `api_layer/routes_dashboard.py:99-113` | **LOW** | **The dashboard declares no pointer to the thesis it came from.** The module docstring says it "publishes the measurements… plus a pointer to the thesis", but `DashboardData` has no such field (`country, as_of, provenance, series, yield_curve, tips_curve, series_limit, warnings`). `/query` does expose `supporting_thesis_id`; the dashboard has no equivalent, so a widget cannot link its panel to the thesis. **Fix (description):** add `thesis_id: str \| None` (or a `/thesis` URL) to `DashboardData`. |
| **4.7** | 3 | `api_layer/routes_thesis.py:122-157` | **LOW** | **`_http_status_for` re-raises for unmapped types, bypassing FastAPI's 500.** It handles `NotImplementedError`/`SnapshotUnavailableError`/`OrchestrationError` then does `raise exc` for anything else. Because it is called inside `except Exception as exc:`, an unexpected type (`ValueError` from `build_snapshot`, `AttributeError` from a schema drift) escapes as a bare re-raise rather than a 500 with the handler's diagnostic detail. **Fix (description):** return a 500 `HTTPException` for the fall-through case instead of re-raising. |

### Category 5 — Client-Side Defects

| # | Phase | File / Area | Sev | Description |
|---|---|---|---|---|
| **5.1** | 3 | `api_layer/routes_query.py:254-256` | **LOW** | **The STALE disclosure is signalled in two incompatible forms.** It is appended as prose inside `answer` (line 256, conditional on a substring match) **and** emitted as a provenance warning. A client has to parse the answer string for one form and read `warnings` for the other; the two can disagree if the substring match misses. **Fix (description):** drop the redundant prose sentence and rely on the structured warning. |
| **5.2** | 3 | `api_layer/routes_dashboard.py:205-226` | **MEDIUM** | (same as 4.5 from the client view) A missing declared family or curve is invisible to the client: `warnings` is empty and the panel is `null`/`[]`, so the UI cannot distinguish "no data configured" from "field renamed". **Fix (description):** as 4.5. |
| **5.3** | 3 | `api_layer/app.py:67-74` | **LOW** | **CORS middleware is attached only when `cors_origins` is non-empty, with no startup warning.** With an empty origin list and `allow_headers=["*"]`, a browser client served from a different origin/port receives no CORS headers and sees the `POST /query` request fail as an opaque network error — indistinguishable from a server outage. **Fix (description):** emit an explicit startup warning when `cors_origins` is empty, or document the precondition in the OpenAPI description. |
| **5.4** | 3 | `api_layer/reasoning_stream.py` (whole module) | **MEDIUM** | (same as 2.3 from the client view) The client can see a dead stream for the entire multi-minute build, with no heartbeat to distinguish "working" from "hung". **Fix (description):** as 2.3. |

### Category 6 — Interruptions / Edge Cases

| # | Phase | File / Area | Sev | Description |
|---|---|---|---|---|
| **6.1** | 4 | `api_layer/snapshot_provider.py:294-314` | **MEDIUM** | **The snapshot cache has no single-flight guard, so a cold cache stampedes and the last writer wins — including an older snapshot over a newer one.** `get_snapshot` reads `_CACHE`, and on a miss calls `_build` (a 9.5–223.6s blocking build) **outside any lock**, then writes `_CACHE[country]` unconditionally. Two concurrent requests for a cold cache both miss, both run the full build (doubling load on the 223.6s provider), and both overwrite — the second entry wins **even if built from an older `as_of`**, so the cache can regress in age. No `asyncio.Lock`/`threading.Lock`, no in-flight marker exists in the module. (The returned tuples are internally consistent per call, so this is a cache-age regression and an unbounded stampede, not data corruption.) **Fix (description):** guard the miss-and-build in a per-country lock (or single-flight future), and refuse to overwrite an entry whose `as_of` is newer than the one being written. |
| **6.2** | 4 | `api_layer/snapshot_provider.py:294` + `routes_health.py:137` | **MEDIUM** | **`force_refresh=True` rebuilds a 223.6s operation on every call, with no timeout, no retry and no in-flight dedup.** `/health?deep=true` and `/thesis?fresh=true` both enter `_build` unconditionally; `_build` maps **any** exception (including a provider timeout) to `SnapshotUnavailableError` (341-346) but there is no deadline or retry policy anywhere on this path. A supervisor with a normal probe timeout will mark the service dead while it is working correctly, and two concurrent `?deep=true` calls run two full builds against one provider. **Fix (description):** bound the deep check with a timeout shorter than a typical probe interval (returning `status="degraded"` with a detail naming the deadline), and share/skip a build already in flight. |
| **6.3** | 1 | `data_layer/openbb_client.py:249-253` | **MEDIUM** | **`is_local_api_available` swallows the very errors the health endpoint exists to surface.** The `except httpx.HTTPError` catches `httpx.TimeoutException` into a bare `False` with **no log line**, and a non-`httpx` exception (SSL error, malformed `base_url`) propagates out of a method whose docstring says it is used by `/health` — so a health endpoint can return 500 instead of a boolean. This is the one exception-to-boolean conversion in the reviewed set with no accompanying log. **Fix (description):** catch broadly, log the reason, and return `False`. |
| **6.4** | 1 | `data_layer/release_calendar.py:230, 253-282` | **MEDIUM** | **The calendar fallback stamps a FUTURE release datetime onto historical points, and its retry budget blocks the request path.** `_resolve_release_index` never threads `as_of`, so `fetch_release_dates` anchors its window to `datetime.now().astimezone().date()`; with `window_days_forward: 45`, `dates` can contain a release datetime **up to 45 days in the future** of the wall clock, and `_points_from_frame` (235, 253) stamps that value onto every historical point of the series — so an observation months old carries a `release_datetime` in the future, a physically impossible combination. The module docstring only defends the *direction* that protects the `as_of` filter ("cannot be fooled into admitting a value earlier than the true release"); the reverse was never checked. Separately, the retry loop sleeps `backoff_seconds · attempt` = 1.5/3.0/4.5/6.0s for `max_attempts: 5` — 15s of blocking `time.sleep` in a synchronous request path, with no total-elapsed cap and no jitter. (The retry budget is documented as an intentional "dead cost" while the route is edge-blocked, so only the missing cap is a defect.) **Fix (description):** thread the snapshot's `as_of` into the calendar query and clamp every applied release datetime to `<= as_of`; add a total-elapsed budget to the retry loop. |
| **6.5** | 1 | `data_layer/release_calendar.py:157-164` + `snapshot_builder.py:601` | **LOW** | **The calendar window is anchored to local date while `snapshot.as_of` is UTC.** On any host with a non-UTC offset the two disagree by up to a day at the boundary — extended 45 days forward by `window_days_forward`. Related to 6.4. **Fix (description):** anchor both to the same clock. |
| **6.6** | 1 | `data_layer/openbb_client.py:411-440, 449-466` | **LOW-MED** | **Index/date inference samples one element and can leak a raw `ValueError`.** `_index_looks_like_dates` tests `df.index[0]` only, so a mixed-type index is classified on one sample; if the reset produces a non-parseable column, `pd.to_datetime(out["date"])` (395) raises a raw `ValueError` — violating the module's stated contract that callers "handle **one** exception type and never see a raw provider exception". `_pick_value_column` (463-465) returns the sole remaining column unconditionally, so a date-like field can be paired with a date. **Fix (description):** wrap the `to_datetime` cast and the `float(row["value"])` cast (`_points_from_frame:249`) so parse failures raise `OpenBBFetchError`. |
| **6.7** | 1 | `data_layer/snapshot_builder.py:504-514` | **LOW-MED** | **The public-date merge can resurrect a series the primary source deliberately omitted, under one global provenance label.** The merge `{**fallback.dates, **primary.dates}` is correct per-series, but `report.release_source` is already `"publication_dates"` and `report.release_calendar_series` counts only the primary — so a series served by the **fallback** is attributed to the primary and under-counted. The registry explicitly holds the two sources to be different in kind, so mixing them under one label erases a provenance distinction the module deliberately created. **Fix (description):** record per-series provenance in the index, or emit a `mixed` `release_source`. |
| **6.8** | 3 | `api_layer/reasoning_stream.py:100-256` | **LOW** | **No `finally` block on the SSE generator.** A client disconnect mid-build relies entirely on Starlette calling `aclose()`; anything held during the 223.6s `get_snapshot` is released only by GC. (UNCONFIRMED without runtime access.) **Fix (description):** add a `finally` that releases/records state on cancellation. |
| **6.9** | 1 | `data_layer/publication_dates.py:191-252` | **MEDIUM** | **A transient empty response permanently drops a series' publication date, and retryable vs permanent outcomes are collapsed.** The empty-result path `continue`s correctly, but the loop's `break` on non-empty-without-exact-match consumes the budget once, and the `for...else` fires only on exhaustion — so an empty-then-non-empty sequence lands on the `break` and the series is silently absent. `_extract_exact` returning `None` for a malformed `last_updated` (134-135) is likewise indistinguishable from a prefix-sibling miss. Downstream both become `has_known_release_timing == False` with **no flag** (`schemas.py:130-141`). **Fix (description):** distinguish "empty after retries" from "well-formed answer lacking the symbol" and surface both as a per-series gap flag. |

---

## 2. Findings grouped by PHASE

### Phase 0 — Repo skeleton / tooling
No defect found. `pyproject.toml` pins `ruff`/`mypy`/`pytest`; the D-035 rule that lint
paths and the close-out gate must agree is explicitly encoded (lines 85-92, 145-147).
Nothing to report.

### Phase 1 — Data layer + `MacroDataSnapshot` + thesis schema
**3.2 · 3.3 · 3.4 · 3.5 · 3.6 · 3.7 · 3.8 · 3.9 · 3.10 · 6.3 · 6.4 · 6.5 · 6.6 · 6.7 · 6.9**
The data layer carries the largest cluster of findings, mostly in the "a failure or an
absence must be *recorded*, not absorbed" family (3.2, 3.4, 3.9), plus two genuine
correctness bugs in time handling (3.6, 6.4) and a silent round-trip data loss (3.3).

### Phase 2 — Core models
**1.4 (risk, technically 4) · 2.4 · 4.2** · and the `regime` / `inflation_convergence` grid
findings in §7.
The Phase-2 model math is strong: Taylor rule, canonical gap, bond math, national accounts,
Phillips sign and the probability bounds all reproduce the spec by hand. The defects found
are at the *edges* (a boundary flag, a `LOW`-reason branch) rather than in the core formulas.

### Phase 3 — Thesis builder + API layer
**1.2 · 1.6 · 2.1 · 2.2 · 2.3 · 2.5 · 4.1 · 4.3 · 4.4 · 4.5 · 4.6 · 4.7 · 5.1 · 5.2 · 5.3 · 5.4 · 6.8**
The single most consequential Phase-3 defect is **1.2** (the drifted `_signed_scalar`), because
it publishes a *directional falsifier* from an unreadable value. The SSE and API findings
(2.1, 2.2, 2.3, 4.3, 4.4) are a consistent pattern: the API layer was written for a fast
in-process build and not re-hardened for the 223.6s local-API reality.

### Phase 4 — Risk basics + risk-budget hook
**1.1 · 1.5 · 6.1 · 6.2**
**1.1 is the highest-impact finding in the entire review**: a public, exported, tested
function returns a 2.17×-wrong z-score for any confidence below 0.90, feeding `parametric_var`.

---

## 3. `[CROSS-PHASE]` — Data availability & consumption

### 3.A The orphan census — 76 `ModelResult` functions, only 17 reachable
An AST analysis of every `ModelResult`-returning function across `src/macro_engine/models/`
found **76** such functions; only **17** are reachable from `api_layer` or `thesis_layer`.
The 59 unreachable ones split into three tiers:

| Tier | Examples | Verdict |
|---|---|---|
| Legitimate Phase-5 / library | `compute_fci`, `bayesian_update`, `historical_var`, `parametric_var`, `expected_shortfall`, `apply_fractional_kelly` | **Not a defect** — deliberate deferral, exported for the Phase-5 layers. |
| **Spec-mandated thesis input, genuinely orphaned** | **`project_inflation_trajectory`** (§16.2 **Q2**, Module 3.6, D-053 "Implemented", 47 tests) | **DEFECT (MEDIUM)** — §16.2 names it a thesis input (Q2), yet no module references it except itself, `config.py` comments, tests and `scripts/`. The spec-mandated inflation-trajectory question is not answered on the thesis path. |
| **Declared, consumed, unreachable** | **`qe_qt_stance`**, **`repo_stress_check`** | **DEFECT (MEDIUM, `[CROSS-PHASE]`)** — see 3.B below. |

### 3.B `BalanceSheetInputs` is never constructed in production — `[CROSS-PHASE]`
`BalanceSheetInputs` (`policy_rules.py:863`) is the input to both `qe_qt_stance`
(`policy_rules.py:916`) and `repo_stress_check` (`bond_math.py:351`). It is constructed
**nowhere in `src/`** — only in `tests/models/test_policy_rules.py` and
`scripts/live_labor_check.py`. Consequently:
- `qe_qt_stance` is called only from tests; no thesis ever carries a QT-stance reading.
- `repo_stress_check`'s only `src/` reference is a **comment** (`policy_rules.py:974`:
  *"QT active — monitor repo_stress_check()"*).

This matters because Section 22.11 requires `repo_stress_check` to consume the
`repo_volume_change_pct` corroboration before escalating to `ACUTE_REPO_STRESS` — and
`on_rrp_volume_bn` (the series added *specifically* to supply it, registry lines 455-462)
is a snapshot field that **nothing reads**. The chain
`snapshot field → BalanceSheetInputs → repo_stress_check` is broken at the second link.
The same pattern is D-073's headline: *declared, consumed, unreachable.*

### 3.C `on_rrp_level` vs `on_rrp_volume_bn` — duplicate series, split roles — `[CROSS-PHASE]`
See **3.1**. Two registry entries bind FRED `RRPONTSYD`; the one the model reads
(`on_rrp_level`) is `not_a_snapshot_field: true` and therefore never populated by any
snapshot, while the one that *is* populated (`on_rrp_volume_bn`) is read by nobody.

### 3.D `release_datetime` does not survive persistence — `[CROSS-PHASE]`
See **3.3**. A snapshot reloaded from the store loses every `release_datetime`, flipping
`has_known_release_timing` from True to False across the round-trip with no flag.

### 3.E `project_inflation_trajectory` (§16.2 Q2) is not on the thesis path — `[CROSS-PHASE]`
See 3.A. Q2 is one of the fifteen core questions the thesis is defined to answer.

---

## 4. Prioritised remediation order (description only — no code)

1. **1.1** `z_score_for_confidence` below-0.90 branch — wrong anchor, 2.17× error, feeds VaR.
2. **1.2 / 1.6** `invalidation._signed_scalar` — restore the `isfinite` guard; non-finite
   values must not produce a directional falsifier.
3. **3.1 / 3.B** RRP duplicate + never-constructed `BalanceSheetInputs` — restore the
   `snapshot → BalanceSheetInputs → repo_stress_check` chain, or delete the dead model paths.
4. **3.3** persist `release_datetime` (and `field_sources`) across the round-trip.
5. **3.4 / 6.9** distinguish "asked and failed" from "never asked" in the release-date source.
6. **2.1 / 2.2 / 2.3** SSE: outer `try` yielding `[DONE]`, off-loop build, heartbeat.
7. **1.3** `is_marginal` tolerance in bp, not pp.
8. **3.5 / 3.6 / 3.7** collapse the two bound-derivation paths; de-dup curves before the
   O-7 filter; validate curves against `CANONICAL_TENORS`.
9. **6.1 / 6.2** cache single-flight + a bounded deep-health check.
10. **4.3 / 4.4 / 4.5** unify API error shapes and surface missing dashboard fields.
11. **3.A / 3.E** decide `project_inflation_trajectory`'s fate (wire it into the thesis path
    or record it as a deliberate deferral in `OPEN_ISSUES.md`).
12. Remaining LOW items (1.5, 2.4, 2.5, 4.2, 4.6, 4.7, 5.1, 5.3, 6.6, 6.7, 6.8, 3.9, 3.10).

---

## 5. Coverage & method notes

- **Read in full:** all of `data_layer/` (8 files), all of `api_layer/` (9 files), all of
  `thesis_layer/` (9 files), 16 of the 28 `models/` files, plus `config/series_registry.yaml`
  (1334 lines) and the tooling config.
- **Verified by execution** (`uv run python`, real package): `_select_state` across all
  growth×inflation×gap cells; `z_score_for_confidence` at 0.80/0.85/0.899/0.90/0.95;
  `_classify` across all 27 three-measure direction combinations; the Taylor-rule and
  canonical-gap hand calculations.
- **Every finding was independently confirmed against the source by the lead reviewer.**
  Where a subordinate analysis asserted something the source contradicted, the assertion was
  discarded — see §7 for the two significant examples.
- **No file under `src/` was modified.** The only files written by this review are this
  report and the memory/HANDOFF notes.

---

## 6. `[CROSS-PHASE]` summary table

| ID | From phase | To phase | Availability | Consumption |
|---|---|---|---|---|
| 3.1 | 1 (snapshot) | 4 (`qe_qt_stance`) | `on_rrp_level` **never in snapshot** (`not_a_snapshot_field`) | model reads the unpopulated one |
| 3.B | 1 (snapshot) | 4 (`repo_stress_check`) | `on_rrp_volume_bn` **is** in snapshot | **read by nobody**; `BalanceSheetInputs` built only in tests |
| 3.3 | 1 (build) | 1 (reload) | `release_datetime` present at build | **lost on round-trip**, no flag |
| 3.D | 1 (`publication_dates`) | 1 (`as_flags`) | source can be 100% dead | outage ≡ "never attempted" → **flagged clean** |
| 3.E | 2 (`project_inflation_trajectory`) | 3 (thesis) | series available | **function orphaned**; §16.2 Q2 unanswered |
| 4.4 | 3 (`orchestration`) | 3 (`/query`) | warnings produced | **not published** by `/query` |
| 4.5 | 1 (snapshot field) | 3 (dashboard) | field may be renamed | silent `null` panel, **no warning** |

---

## 7. Rejected / intentional — do NOT re-investigate

The following were raised during the review and **confirmed to be deliberate design
decisions**, documented in the source. They are recorded so a future reviewer does not
re-file them.

1. **`regime._select_state` one-dissenter grid.** The docstring table (regime.py:419-429)
   is not contradicted by the code. The table's `above_trend, gap < −band` row is simply
   **absent** from the docstring (finding 2.4 is about that omission only). The `falling`
   and `flat` columns inside the near-trend band producing the same state is **by design**:
   the code's stated split is on `sign(gap)`, not on `falling` vs `flat`. Verified by
   execution across the whole grid.
2. **`inflation_convergence._classify` treats a lone dissenter at n=3 as `CONFLICTED`.**
   Confirmed deliberate: `tests/models/test_inflation_convergence.py:291` states *"at n=3 a
   lone dissenter is a whole third of the set"*. The side-effect — `HIGH` via band is
   unreachable at n=3, and `MEDIUM` requires *no* opposing direction — is a real **design
   consequence** worth a note, but it is not a bug. (Recommend documenting the consequence;
   do not change the threshold without a decision record.)
3. **`MacroThesis.warnings` reassigned post-construction** (`builder.py:1110`,
   `_apply_risk_axis` 1468-1520). `warnings` is `list[str]` and `MacroThesis` has
   `extra="forbid"` but no `validate_assignment`, so the assignment is type-safe. Style
   concern at most.
4. **`_render`'s Q6 path omitting `regime`.** A preliminary analysis claimed the Q6 `_render`
   call drops `regime` while Q7/Q8 pass it. **Falsified** — `builder.py:838-850` passes
   `regime=regime` on the Q6 path. Not a defect.
5. **`release_calendar: enabled: false`** in the registry is intentional, and the
   consequence ("no `RELEASE_TIMING_UNKNOWN` flag when we did not ask") is explicit in the
   registry comments. Finding 3.4 is about the *primary* source inheriting that same silence
   when it *is* enabled and fails — a different case.
6. **`snapshot_provider`'s module-level `_CACHE`** with the "single process by design"
   rationale is intentional; the multi-worker consequence is a documented performance
   difference. Finding 6.1 is about the missing single-flight guard *within* one process, not
   about multi-process behaviour.
7. **`compute_confidence`'s penalty fields defaulting to the no-penalty state** is
   deliberate and mitigated by `extra="forbid"` turning a misspelling into an error
   (`contracts.py:70-91`).
8. **`convergence.py:300` `untagged_count` measured over `signals` while the census runs
   over `directional`** is a documented correction (D-077) — the alternative made the
   disclosure unfireable.
9. **`_quarter_annualized_mom` not asserting a complete quarter** is a documented caller
   contract (`gdp_nowcast.py:990-992`), enforced at the public entry point.
10. **`gdp_nowcast`'s `[0.1, 10.0]` ratio guard** covers index-vs-level mis-mapping only;
    the SAAR/NSA and nominal/real wedges are too small for it to see. Documented limitation.

---

*End of report. No fixes applied. Awaiting explicit permission before any code change.*
