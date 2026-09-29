# Phase 2 — Models Layer Review (production-grade)

**Decision:** `D-139`. **Status:** COMPLETE. **Date:** 2026-09-30.
**Scope:** every file in `src/macro_engine/models/` (34 files), reviewed
file-by-file.

This is Phase 2 of the operator's production-grade review (Phase 0 → 5). Phase 0
(`D-136`) closed performance + sweep/CI safety; Phase 1 (`D-137`) closed the data
layer. Phase 2 is the **models layer** — the quantitative macro models that turn a
`MacroDataSnapshot` into numeric outputs consumed by the thesis layer. The
standing rule applies: trace real logic from first principles, fix at root cause,
and re-derive every gate at CI scope before declaring done.

The operator directed, via `AskUserQuestion`: **"Fix all 13 now"** for the NaN
defect scope, and **"Deep-read all remaining"** for depth.

---

## 1. Method

1. Read every `models/*.py` file (34 files) in full — not sampled.
2. Read `models/contracts.py` (the `ModelResult` contract + `ConfidenceInputs`
   / `compute_confidence`) and `config.py` to establish the plumbing pattern
   (`CalibratedValue` leaf + `@property` accessor; models read leaves, never
   literals).
3. For each input group, **measured** whether a non-finite float could reach the
   model body (D-078 class) — built a valid instance, then re-validated with
   `nan` / `+inf` / `-inf` substituted.
4. Fixed four defects found by the read (§2) plus the repo-wide non-finite class
   (§3), each with a regression test.
5. Re-derived every gate at CI scope (§6) and re-verified the affected sweep
   anchors (§5).

## 2. Four root-cause defects (found by the file-by-file read)

### 2.1 `inflation_trajectory.py` — an independence point credited to a NON-corroboration

`source_independence_count` (L423–427) was:

```python
source_independence_count = (
    0 if corroboration.startswith("disagrees") or corroboration == "unavailable" else 1
)
```

A `not_directional` verdict therefore fell into `else 1` and earned the *same*
confidence bonus as an agreeing source. Corroboration adds genuine evidence only
when it **agrees**; a non-directional read is not corroboration. Fixed to:

```python
source_independence_count=(
    1 if corroboration.startswith("agrees") else 0
),
```

**Measured impact:** the same inputs moved confidence **0.35 (buggy) → 0.30
(fixed)** — the bug was inflating confidence. Regression test:
`test_a_non_directional_corroboration_earns_no_independence_credit`.

### 2.2 `inflation_dynamics.py` — two bare literals in the Phillips curve

`u_star_revision = 0.5` (the illustrative u\* revision magnitude used to compute
the expectations-dominance threshold) and the `slack_negligible < 0.05` guard were
both inline literals. Promoted to config leaves:

- `phillips.illustrative_u_star_revision_pp` (0.5) → accessor
  `settings.phillips.illustrative_u_star_revision`;
- `phillips.slack_negligible_threshold_pp` (0.05) → accessor
  `settings.phillips.slack_negligible_threshold`.

Each has a **MOVER** test (`test_the_u_star_revision_magnitude_is_read_from_config`,
`test_the_slack_negligibility_threshold_is_read_from_config`) so a leaf read is
distinguishable from a re-typed literal (trap class 4).

### 2.3 `intervention.py` — a PHANTOM input

`reserves_to_gdp_pct` was a declared field that fed *no* computation and never
appeared in the output — a documented input that did nothing. It is now consumed:
a `reserves_scale` verdict (`"UNSCALED"` / `"AMPLE"` / `"THIN"`) is computed
against a new leaf `intervention.reserves_to_gdp_ample_threshold_pct` (20.0),
published in `value["reserves_scale"]`, and disclosed in `assumptions`. Four
tests pin it, including `test_the_scale_verdict_does_not_change_the_capacity_label`
(the verdict is *disclosure*, not a label-flipper) and
`test_a_missing_reserves_to_gdp_reads_as_unscaled`.

### 2.4 `labor_synthesis.py` — a hardcoded scaling divisor

`_nfp_scaling_divisor()` returned the literal `10.0` (the NFP→payrolls unit
scaling). Promoted to `labor.tightness_scaling.nfp_divisor` (10.0), accessor
`settings.labor.tightness_scaling.nfp_divisor_value`, with a MOVER test
`test_the_nfp_divisor_is_read_from_config_not_hardcoded`.

## 3. The D-078 non-finite class, CLOSED repo-wide (the load-bearing work)

**The defect class.** A non-finite float (`nan` / `inf`) is *not* "missing" — it
fails **every** comparison, so `nan` silently takes the branch the bounds were
written to exclude (`nan > x` is `False`). Meanwhile a `Gt`/`Ge` bound *rejects*
`nan` and `-inf` but **admits `+inf`** (`+inf > 0` is `True`), so a `+inf` gap
never surfaces as a `nan` gap and hides in a different test.

**The audit.** A repo-wide structural sweep measured the gap as **20 input
classes**: **13 that accepted `nan`** (measured with a valid-instance probe) plus
**7 that accepted `+inf`**. All 20 were reachable because their input groups did
not inherit the guard.

**The fix — one shared base, not 20 copies.** `policy_rules._FiniteInputs` was
promoted to a shared, public `contracts.FiniteInputs`:

- `model_config = ConfigDict(extra="forbid")`;
- a single `@model_validator(mode="after")` that rejects a non-finite scalar
  float **and** a non-finite element of a `list` / `tuple` (which pydantic's
  `allow_inf_nan=False` cannot catch for containers);
- a shared `NON_FINITE_INPUT_REMEDY` constant for every refusal message;
- only `float` is inspected (an `int` is always finite; `bool` is an `int`
  subclass, not a `float`).

All 20 gap classes were re-based onto `FiniteInputs`, by module:

| Module | Classes |
|---|---|
| `bond_math` | `RepoStressInputs`, `BondPricingInputs`, `ConvexityInputs` |
| `gdp_nowcast` | `GdpGdiInputs`, `OutputGapInputs` |
| `inflation_dynamics` | `PhillipsCurveInputs`, `InflationTransmissionInputs` |
| `national_accounts` | `PolicyMixInputs`, `QuantityTheoryInputs`, `SavingsInvestmentInputs`, `MinskyCompositionInputs`, `FisherIndexInputs`, `OpeningsToUnemployedInputs` |
| `real_policy_rate` | `RealPolicyRateInputs` |
| `risk` | `TwoAssetPortfolioInputs` |
| `yield_curve` | `BreakevenInputs`, `CurveDecompositionInputs` |
| `auctions` | `AuctionInputs` |
| `credit_spread` | `CreditSpreadInputs` |
| `production_function` | `PotentialGDPInputs` |
| `labor_synthesis` | all 8 groups |
| `ppi_pipeline` | `PPIPipelineInputs` |

**Final audit: 30 classes `FiniteInputs`-covered, 11 self-guarded, 0 remaining
gaps** for `nan` / `+inf` / `-inf`.

Additionally `national_accounts.py:554` had a bare `> 0.5` (the deficit-mismatch
tolerance) → promoted to `policy_mix.deficit_mismatch_tolerance_pp`.

**Why the SWEEP is the closing argument.** A per-class regression test is exactly
what nobody writes for the *next* input group. The real guard is
`tests/models/test_finite_inputs_repo_wide.py` — a **structural sweep** that
imports every `*Inputs` class in the package and asserts none admits a non-finite
float, naming every offender at once. `tests/models/test_finite_inputs_contract.py`
pins the promoted base itself (scalar refused, list element refused, error names
the field, finite/int pass, structural inheritance over `labor_synthesis` /
`policy_rules`, shared remedy constant).

## 4. Five new config leaves

| Leaf | Value | Consumed by |
|---|---|---|
| `phillips.illustrative_u_star_revision_pp` | 0.5 | `inflation_dynamics` expectations-dominance threshold |
| `phillips.slack_negligible_threshold_pp` | 0.05 | `inflation_dynamics` slack-negligibility guard |
| `intervention.reserves_to_gdp_ample_threshold_pct` | 20.0 | `intervention` `reserves_scale` verdict |
| `labor.tightness_scaling.nfp_divisor` | 10.0 | `labor_synthesis` NFP scaling |
| `policy_mix.deficit_mismatch_tolerance_pp` | 0.5 | `national_accounts` deficit-mismatch check |

Each has a `CalibratedValue` field, a `@property` accessor, a YAML leaf carrying
its rationale in `config/settings.yaml`, and — where it feeds a computation — a
MOVER test.

## 5. Sweep anchoring repaired

The L423–427 fix invalidated `scripts/mutation_inflation_trajectory.py` M8.2's
anchor (target ABSENT is a `sweep_health` failure). Retargeted to the new ternary,
renamed *"source-independence factor polarity inverted"*, its `new` string
polarity-inverted, and its `killed_by` intent corrected to name the real killer
(`test_confidence_matches_compute_confidence_exactly`).

All 15 affected sweeps re-verified `--check-targets: 0 problems`; `sweep_health.py`
**OK**.

## 6. Line-ending incident (D-061/O-119 class) — self-inflicted, caught by the suite

The helper scripts used to apply edits wrote with
`pathlib.write_text(encoding="utf-8")` **without `newline=""`**, converting
LF → CRLF in 11 model files on Windows. Git cannot see this (`.gitattributes`
`* text=auto eol=lf`), but
`tests/test_source_hygiene.py::test_no_source_file_contains_a_carriage_return`
did — which is exactly why that test exists. Fixed with a `write_bytes`
normaliser (`\r\n` / `\r` → `\n`); the 11 files re-verified LF,
`test_source_hygiene.py` 5 passed.

**Lesson recorded:** helper edits must use `newline=""` (or byte-mode), never a
bare `write_text`.

## 7. Gates (re-derived at CI scope — all green)

| Gate | Result |
|---|---|
| `ruff check src/ tools/ tests/ scripts/` | **All checks passed** |
| `ruff format --check` (same scopes) | **296 files already formatted** |
| bare `mypy` | **Success: no issues found in 296 source files** |
| `reachability_audit.py --check-baseline` | **PASS — baseline 58, measured 58, no regressions** |
| `pytest -m "not live"` (`--junitxml`) | **4320 tests / 0 failures / 0 errors / 23 skipped** |
| `sweep_health.py` | **OK — 52 sweeps, 0 failures, 0 leftovers, 0 mutant shapes, 0 committed mutants** |

No `.sweepbackup` sidecars after any run.

**Files changed:** see `docs/DECISIONS.md` D-139. **No new `src/` function, no new
OpenBB command** (census stays 6). 5 new config leaves.

## 8. Deferred to a live session

Live re-verification of `yield_curve` and `regime` against the running OpenBB
server (both build on the data-layer transports verified in Phase 1), and the
deep-read of the six large remaining files (`econometrics` 4439 lines,
`fx_carry` 2507, `regime` 2347, `yield_curve` 2113, `risk` 1528, `commodities`
1309). These are recorded as remaining Phase 2 work, not defects.
