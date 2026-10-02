# Production Review — Global Macro Reasoning Engine

**VERDICT: FAIL**

The verdict is produced by `tools/selfaudit.py`, not asserted here. Run it with
`uv run python tools/selfaudit.py`; it exits 0 only when every check passes and
writes its own outcome to `.review-evidence/selfaudit.json`.

---

## Why this is FAIL

One unfixed defect of any severity fails the review (section 1C). Three
conditions hold, any one of which is sufficient:

1. **Four defects are open.** Two are fixed and mutation-proved (F-VAL-001,
   F-RB-001). Four remain open: F-VAL-002, F-LAW1-001, F-LAW1-002, F-SCOPE-001.
2. **97.48% of source lines were not reviewed line-by-line.** Section 4 requires
   every non-trivial line to be explainable. 1,426 of 56,481 lines were read
   at that depth. The remaining 55,055 lines are recorded as NOT REACHED, not
   as reviewed.
3. **The live gate (`uv run pytest -m live`) never ran.** Section 7 requires it.
   It needs the OpenBB Platform API at `127.0.0.1:6900`; that service was not
   confirmed running, and section 21.1 forbids substituting a synthetic fetch
   for a real one.

---

## Measured numbers (machine-checked by the harness)

**Files in scope**: 79
**Share of lines reviewed**: 2.52
**ORPHAN**: 1054

| Key | Value | Reproducing command |
|---|---|---|
| Files in scope | 79 | `find src -name "*.py" \| wc -l` |
| Source lines | 56,481 | `find src -name "*.py" -print0 \| xargs -0 wc -l` |
| Lines reviewed line-by-line | 1,426 | `.review-evidence/manifest.json` (re-hashed each audit) |
| Files fully reviewed | 6 | `.review-evidence/manifest.json` |
| Files not reached | 68 | `.review-evidence/manifest.json` |
| Functions measured | 1433 | `uv run python tools/callgraph.py` |
| **WIRED** | 173 | `uv run python tools/callgraph.py` |
| **REACHABLE-ONLY** | 206 | `uv run python tools/callgraph.py` |
| **ORPHAN** | 1054 | `uv run python tools/callgraph.py` |
| **WIRED-BUT-DEAD** | 0 | `uv run python tools/callgraph.py` |
| Public ORPHAN functions | 851 of 946 | `uv run python tools/callgraph.py` |
| Entry points (HTTP routes) | 5 | `uv run python tools/callgraph.py` |
| Tests passing | 377 (5 deselected) | `uv run pytest -m "not live and not slow" -q` |

---

## Gate results

| Gate | Command | Exit | State |
|---|---|---|---|
| ruff check | `uv run ruff check src/` | 0 | PASS |
| ruff format | `uv run ruff format --check src/` | 0 | PASS |
| mypy (bare) | `uv run mypy` | 0 | PASS (99 source files) |
| import smoke | `uv run python tools/import_smoke.py` | 0 | PASS (79 modules) |
| pytest default | `uv run pytest -m "not live and not slow" -q` | 0 | PASS (377) |
| pytest live | `uv run pytest -m live -q` | not run | **NOT REACHED** |

**The committed tree was red before this review touched anything.** This is
finding F-BASE-001 and it is recorded with both failing exit codes in
`.review-evidence/baseline.json` under `untouched_tree`:

* `uv run mypy` exited **2** — `There are no .py[i] files in directory 'tools'`,
  then the same for `'scripts'`. `pyproject.toml` sets
  `files = ["src", "tests", "tools", "scripts"]`, and the committed tree left
  `tools/` and `scripts/` empty, so the configured gate could never pass.
* `uv run pytest -m "not live and not slow" -q` exited **2** —
  `ModuleNotFoundError: No module named 'tests'` from
  `tests/data_layer/test_phase1_data_layer.py:56`. The committed suite imports
  `tests.conftest`, but neither `tests/__init__.py` nor `tests/conftest.py` was
  ever committed, so collection was interrupted and zero tests ran.

Both were repaired by adding what the tree already declared, not by narrowing a
gate: `tools/` and `scripts/` now hold tooling this review requires, and the
missing `conftest` is built over the real production schema types
(`ObservationPoint`, `YieldCurveSnapshot`, `MacroDataSnapshot`) rather than over
stand-in structures. mypy's configured scope was not reduced.

---

## SPEC_CHALLENGES

Five places where `AGENTS.md` contradicts itself or where the spec's own sample
cannot work. Each is recorded with its line range in
`.review-evidence/agents_read.json` under `spec_challenge_candidates`.

| # | Challenge | Evidence |
|---|---|---|
| S1 | Section 6 and 22.8 mandate `compute_confidence()`, yet most section-6/15/20 samples still write literal `confidence=` values (`taylor_rule confidence=0.6` at AGENTS.md:731). 22.8 governs; the samples are stale. | `agents_read.json` |
| S2 | Section 16.2 (AGENTS.md:3244) uses `ensemble['rules']['taylor']` as `model_implied_value`, while 22.4 (AGENTS.md:655) makes the **median** canonical. 22.4 governs; 16.2's sample would emit a non-canonical gap. | `agents_read.json` |
| S3 | Section 20.2's convexity sample passes `inputs.n_periods` / `inputs.coupon`, while `BondPricingInputs` at 20.5/16.4 declares `periods` / `coupon_rate`. The spec's two halves disagree on a signature. Measured: `bond_math.py` uses `periods` and `coupon_rate`. | `agents_read.json`; `bond_math.py:185-206` |
| S4 | 21.1 renames intervention capacity to `MECHANICALLY_UNCONSTRAINED_COST_BOUNDED` (22.11), but the 20.9 sample still emits `UNLIMITED_AMMUNITION_but_costly` (AGENTS.md:4916). | `agents_read.json` |
| S5 | 22.3 retracts multi-country generality and calls `country: str = "us"` "a label, not a generalization", while REVIEW_PROMPT LAW 1 requires `us` to be a config value with no country literal in `src/`. The two cannot both hold. Measured: no `country` key exists anywhere in `config/settings.yaml`. | F-LAW1-002 |

---

## Per-file findings

Severity per section 1C. "Disposition" is FIXED only where a test exists and a
mutation proof is recorded in `.review-evidence/mutations.json`.

| ID | File:line | Sev | Finding | Disposition |
|---|---|---|---|---|
| F-BASE-001 | `tools/`, `scripts/`, `tests/` | SEV-1 | Committed tree fails two of its own configured gates (mypy exit 2, pytest collection exit 2). Zero tests ran. | **FIXED** — scaffolding added; 377 tests now run; both exit codes recorded in `baseline.json` |
| F-VAL-001 | `data_layer/validation.py:439` (pre-fix) | SEV-2 | `yld <= 0.0` flagged as ERROR "a data fault, not a market state" for every tenor. The U.S. Treasury par yield curve printed **1 Mo = 0.00 and 3 Mo = 0.00 on 2020-03-25**, so the check emitted false corruption flags on real published history. | **FIXED + mutation-proved** |
| F-VAL-002 | `data_layer/validation.py:383`, `:52` | SEV-3 | `validate_positive_index_level` is exported in `__all__` and never called anywhere in `src/` or `tests/`; the same rule runs only via `plausible_range`, so there are two implementations of one rule. **Reconciled against D-142**, which triaged this name as deliberate public API surface and cleared it as not-a-defect — see the note below the table. | OPEN |
| F-LAW1-001 | `config/settings.yaml`, 51 leaves | SEV-3 | 51 config leaves carry no complete `{value, calibration_status, note}` envelope — e.g. `openbb.max_retries` and `openbb.timeout_seconds` have a status but no note; `inflation.convergence.min_independent_families_per_band.{high,medium,low}` are bare integers. LAW 1 requires unit and provenance per leaf. | OPEN |
| F-LAW1-002 | 137 sites across `src/` | SEV-3 | `us` is hardcoded at 137 sites with no config entry. Measured mitigation: of the 96 functions that emit `country="us"`, **0** take a snapshot parameter, so no model mislabels a snapshot's country; `gdp_nowcast.py:557` actively refuses non-`us`. | OPEN |
| F-RB-001 | `portfolio/risk_budget.py:2914` | SEV-3 | `outcome: PositionTranslationOutcome = kelly_outcome  # type: ignore[assignment]`. `PositionTranslationOutcome` is a `Literal` of six strings; `kelly_outcome` is `str(kelly_value["outcome"])`, a plain `str`, so the declaration was a lie the checker was told not to look at. | **FIXED + mutation-proved** |
| F-SCOPE-001 | whole tree | SEV-1 | 55,055 of 56,481 source lines not reviewed line-by-line; 68 of 79 files not reached. | OPEN |

### Note on F-VAL-002, recorded against a prior decision

`docs/DECISIONS.md` D-142 already triaged this name and cleared it, on the
grounds that "`__all__` exports ... Deliberate public API surface; unreferenced
in-tree is the *point* of an exported name". That reasoning holds for the class
of names it was written about, and I am not overturning it: `AGENTS.md` does not
name `validate_positive_index_level` anywhere, so no spec text is violated by
its being unwired.

What D-142 did not address is the asymmetry this review measured: of the three
sibling validators it lists together, `validate_unemployment_rate` **is** called
(`validation.py:588`) and `validate_equity_index` **is** called
(`validation.py:626`), while `validate_positive_index_level` is not. Its rule —
a price-index level cannot be negative — runs only as a side effect of
`plausible_range`, so the same invariant has two implementations and the one
with the explicit name is the one that never executes (LAW 2). The existing
test `test_negative_cpi_index_level_is_flagged` passes through the range path,
not through this function.

Left OPEN rather than deleted, because deleting a public export on my own
authority is a larger change than the defect, and D-142's position deserves an
explicit decision to reverse it.

### Attacks that found no defect (recorded because an unrecorded attack did not happen)

| Target | Attack | Result |
|---|---|---|
| `datetime.utcnow()` (22.10) | AST scan of all 79 modules excluding docstrings | **0 live call sites.** All 4 `utcnow` occurrences are inside docstrings quoting the spec's samples, including `thesis_layer/no_trade.py:31`. No defect. |
| `country` mislabelling | AST: find functions emitting `country="us"` that also receive a snapshot | **0 of 96.** No model can mislabel a snapshot's country. |
| Negative-yield hypothesis | Primary-source check of the Treasury par yield curve | **Refuted.** No tenor printed below 0.00 on any 2020 date. The defect is the zero boundary, not the sign. Downgraded from a hypothesised SEV-1 to the confirmed SEV-2 F-VAL-001. |
| Config property aliases | `ValidationSettings.unemployment_bounds`, `stale_days`, `max_yield`, `long_end_inversion_floor` | All four resolve correctly to the YAML leaves. No defect. |
| 2s10s slope units | Hand-derivation: yields are percent, difference is percentage points, x100 gives bp; inversion is `2yr > 10yr` = negative | Correct on both direction and scale. |
| Suppression inventory | 7 `# noqa` / `# type: ignore` sites | 4 are narrow with a stated reason; 2 are narrow argument/return coercions; 1 (`no_trade.py:432`) is a `**kwargs` unpack. F-RB-001 was the one that hid an invariant and is now fixed; the other 6 are recorded and left alone. |

---

## SEV-0 list

**None confirmed.**

One candidate was investigated and refuted, and the refutation is recorded
because the hypothesis was wrong in a way worth knowing: I expected the short end
to have printed negative yields in March 2020, which would have made
`validation.py`'s non-positive check a sign error on live data. The primary
source shows the official par yield curve bottomed at exactly **0.00**, never
below. The real defect is narrower — the boundary at zero — and is F-VAL-001.

---

## Call-flow map

Five HTTP entry points, measured by AST (not grep) in
`uv run python tools/callgraph.py`:

```
macro_engine.api_layer.routes_health.health
macro_engine.api_layer.routes_query.query
macro_engine.api_layer.routes_thesis.get_thesis
macro_engine.api_layer.routes_dashboard.dashboard_data
macro_engine.api_layer.reasoning_stream.stream_thesis_reasoning
        |
        v  (173 functions reachable)
   thesis_layer  ->  models  ->  data_layer  ->  OpenBB
        |
        +-- portfolio/risk_budget.py  (sizing; reachable from the thesis route)
```

Reachability, all functions: **WIRED 173**, **REACHABLE-ONLY 206**,
**ORPHAN 1054**, **WIRED-BUT-DEAD 0**.
Restricted to public functions: **WIRED 64**, **REACHABLE-ONLY 31**,
**ORPHAN 851**.

851 of 946 public functions have no caller anywhere in the tree. Many are
Tier-5 stubs and spec-named helpers, so a large orphan count is expected; what
it means is that **no test can reach them through the request path**, and the
default suite exercises only the 173 wired functions.

`WIRED-BUT-DEAD` is 0: every route module that declares a handler is referenced
by `api_layer/app.py`, so no handler is unreachable by HTTP.

---

## Data-coverage table

Generated by `uv run python tools/layer_table.py` from `manifest.json` and
`callgraph.json`; the rows below are not typed by hand.

| Layer | Files | Lines | Lines reviewed | WIRED | ORPHAN |
|---|---|---|---|---|---|
| `data_layer/` | 13 | 6,491 | 891 | 24 | 92 |
| `models/` | 34 | 29,555 | 30 | 44 | 170 |
| `portfolio/` | 2 | 3,113 | 170 | 7 | 21 |
| `thesis_layer/` | 9 | 4,685 | 75 | 43 | 36 |
| `api_layer/` (reviewed last) | 9 | 3,843 | 0 | 51 | 8 |
| `top level + extensions/` | 12 | 8,794 | 260 | 4 | 727 |
| **Total** | **79** | **56,481** | **1,426** | **173** | **1054** |

Per-file WIRED/ORPHAN is in `.review-evidence/callgraph.json` under `nodes`
(keyed by dotted qualified name, with a `module` field).
Per-file hashes and review depth are in `.review-evidence/manifest.json`; the
harness re-hashes all 79 files on every run and fails on drift.

No test asserts a value fetched from a live provider: the 377 passing tests are
offline or golden-value tests. Section 7's real-data E2E requirement is
**NOT REACHED** because it depends on the live gate.

---

## Fixes made in this session

**F-VAL-001 — the zero-yield boundary.** The check is now split: a strictly
negative yield is an ERROR at every tenor (no tenor in the official series
printed below zero); a yield of exactly 0.00 is an ERROR only at tenors the
official series never reached zero on, and an INFO (`ZERO_SHORT_END_YIELD`)
elsewhere. The permitted-tenor set is a **config value** with a provenance note
quoting the Treasury data —
`validation.zero_yield_permitted_tenors` in `config/settings.yaml` — rather than
a literal in the validator, so the measured claim is reviewable and re-pointable.

Test: `tests/data_layer/test_yield_zero_boundary.py`, 6 tests, expected values
taken from the Treasury row `03/25/2020,0.00,0.00,0.00,0.07,...` rather than
chosen for convenience. The existing assertion that a 10yr at 0.00 is an ERROR
still holds.

**F-RB-001 — the suppressed Literal assignment.** `outcome:
PositionTranslationOutcome = kelly_outcome  # type: ignore[assignment]` declared
a plain `str` to be a `Literal` and told the checker not to look. It now narrows
through `_as_translation_outcome`, which enforces `Literal` membership at
runtime and raises naming the offending value, so an unknown Kelly verdict fails
at its cause instead of being rejected later by Pydantic at a distance from it.
The runtime values are provably inside the `Literal` today — the `no_edge`
branch returns early, so only `sized_by_kelly` and `clipped_by_position_limit`
arrive — which is exactly why the suppression survived review before: it was
never wrong, only unchecked.

Test: `tests/portfolio/test_translation_outcome_narrowing.py`, 4 tests. The
rejection case asserts the message names the offending value, per section 7's
requirement that a refusal name what it refuses.

Mutation proof: removing the membership check makes 2 of the 4 tests fail
(exit **1**); restoring makes all 4 pass (exit **0**). Both exit codes recorded.

Mutation proof (`.review-evidence/mutations.json`): reverting the single
comparison `if yld < 0.0:` back to `if yld <= 0.0:` makes 3 of the 6 tests fail
(exit **1**); restoring makes all 6 pass (exit **0**). Both exit codes are
recorded. The mutation changes which finding code is emitted, so it is a
behaviour change, not a text change.

---

## Blocked on me

| Item | What is needed | Why I cannot proceed |
|---|---|---|
| Live gate | The OpenBB Platform API listening on `127.0.0.1:6900` (or `OPENBB_API_URL` set to wherever it runs) | Section 7 requires `uv run pytest -m live` to run at least once with recorded output. Section 21.1 forbids inventing input or substituting a synthetic series, so I cannot stand in for the provider. |

Nothing else blocks. The four open defects are fixable by me and are open
because the review order (section 18: review first, fixing second) puts every
fix behind its findings — not because of an external dependency.

---

## Not reached

Recorded rather than glossed. Each item is work the instruction requires that
this session did not complete.

1. **68 of 79 source files were not opened.** Among them the four largest:
   `models/econometrics.py` (4,448 lines, 0 read), `config.py` (7,005 — 260 read),
   `portfolio/risk_budget.py` (3,113 — 170 read), `models/fx_carry.py` (2,463 —
   0 read). Formulas in those files were not hand-derived against a primary
   source.
2. **`api_layer/` was not reviewed at all.** Section 3 puts it last, after the
   backend is clean; the backend is not clean.
3. **No per-request OpenBB call audit** (section 4, check 7). Requires the
   request path exercised against the live service.
4. **No individual per-field fuzzing** (section 1B) beyond the curve and range
   boundaries touched by F-VAL-001. The NaN/inf/zero/negative/empty/None matrix
   per field is unstarted.
5. **OpenBB endpoint verification** (section 5): zero endpoints checked against
   the official OpenBB docs for exact endpoint string, parameter names, response
   schema, units and provider. `docs/OPENBB_ENDPOINT_RECONCILIATION.md` exists
   in the repository and was not read.
6. **One citation has no external quote.** `C-002` (the 2s10s slope convention)
   was verified by hand-derivation only; the FRED `T10Y2Y` definition page was
   not retrieved. It is listed under `pending_external_quote_ids` in
   `citations.json` and is not counted as a citation.
7. **Statement coverage was not measured.** `coverage.json` records collected
   and passing tests plus call-graph reachability, not line coverage per module.
8. **The config-leaf defects are enumerated, not fixed.** All 51 leaves are
   listed in `.review-evidence/config_leaf_audit.txt`.
9. **`compute_confidence()` was not verified against 22.8's formula.** The
   spec's constants are in `ConfidenceSettings` and were not checked line by
   line against the section.
10. **No git commits were made.** Work is in the working tree only.

---

## Reproducing commands

```bash
uv run python tools/selfaudit.py          # the verdict; exit 0 only on PASS
uv run python tools/gates.py              # all six gates, real exit codes
uv run python tools/callgraph.py          # AST call graph + classification
uv run python tools/import_smoke.py       # every module imports
uv run python scripts/check_config_leaves.py   # LAW-1 config provenance audit
uv run pytest -m "not live and not slow" -q    # 377 tests
uv run pytest -m live -q                  # NOT RUN -- needs the OpenBB API
```

Evidence directory: `.review-evidence/` — `baseline.json`, `agents_read.json`,
`citations.json`, `manifest.json`, `gates.json`, `callgraph.json`,
`mutations.json`, `coverage.json`, `skills_read.json`, `selfaudit.json`,
`config_leaf_audit.txt`.
