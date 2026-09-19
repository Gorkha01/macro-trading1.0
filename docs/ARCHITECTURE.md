# Architecture

How the layers fit together, what each one is allowed to do, and where the
boundaries are enforced. This document describes the system as **built**, not
as planned — Phase status is in `BUILD_STATE.md`.

---

## The shape of the system

```
┌───────────────────────────────────────────────────────────────────────┐
│  OpenBB Workspace / HTTP clients                          (Phase 4+)  │
└──────────────────────────────┬────────────────────────────────────────┘
                               │  JSON + SSE reasoning stream
┌──────────────────────────────▼────────────────────────────────────────┐
│  API LAYER — FastAPI                                       (Phase 2+) │
│  /health   /thesis/{country}   /query   /dashboard_data               │
│  Pydantic request/response schemas · reasoning_step SSE               │
│  DOES NOT: compute anything. It is transport.                          │
└──────────────────────────────┬────────────────────────────────────────┘
                               │
┌──────────────────────────────▼────────────────────────────────────────┐
│  THESIS LAYER — build_us_macro_thesis()                    (Phase 3+) │
│  Consumes ALL model outputs → MacroThesis                             │
│  Encodes hypothesis→thesis→evidence→probability→risk→catalyst→        │
│  instrument→sizing as DATA, not prose                                 │
│  DOES NOT: fetch data, or run models.                                  │
└──────────────────────────────┬────────────────────────────────────────┘
                               │
┌──────────────────────────────▼────────────────────────────────────────┐
│  MODELS LAYER — pure functions over a snapshot             (Phase 2+) │
│  Policy rules · regime · inflation nowcast · labour · GDP nowcast ·   │
│  yield curve · FX · commodities · equity · volatility · risk          │
│  Every one returns a ModelResult — never a bare number.               │
│  DOES NOT: fetch data. Models receive a snapshot, full stop.           │
└──────────────────────────────┬────────────────────────────────────────┘
                               │
┌──────────────────────────────▼────────────────────────────────────────┐
│  DATA LAYER                                        ✅ PHASE 1 COMPLETE │
│  openbb_client → validation → snapshot_builder → persistence           │
│  Produces ONE MacroDataSnapshot per point in time.                     │
│  DOES NOT: interpret, model, or decide.                                │
└──────────────────────────────┬────────────────────────────────────────┘
                               │
┌──────────────────────────────▼────────────────────────────────────────┐
│  CONFIG + REGISTRY                        ✅ PHASE 0/1 COMPLETE        │
│  settings.yaml · series_registry.yaml · logging.yaml · .env            │
│  The ONLY place a route, threshold, or calibration note may live.      │
└───────────────────────────────────────────────────────────────────────┘
```

---

## The governing rule: one direction of dependency

Data flows **up**; nothing reaches back **down**. Concretely:

- A model never fetches data. It receives a `MacroDataSnapshot` and returns a
  `ModelResult`. This is what makes every model unit-testable against a
  hand-built snapshot with no network.
- The thesis layer never runs a model inline. It consumes `ModelResult` objects
  that were produced elsewhere.
- The API layer never computes. It calls a builder and serialises the result.

The practical payoff: the entire models layer can be tested, reasoned about and
re-run offline, because its inputs are values rather than live calls.

---

## The four contracts

Everything else in the system is an implementation detail behind these.

### 1. `MacroDataSnapshot` — the single point-in-time input

Every model's input. Assembled once by `snapshot_builder.build_snapshot()`.

Carries, in addition to the data:
- `as_of` — pinned at the start of the build, so a snapshot gathered across
  minutes of sequential HTTP calls is still one point in time.
- `data_quality_flags` — every anomaly, from two distinct sources (below).
- `field_sources` — field → actual route used (`fred:CPIAUCSL`), so a
  completion record can name the real series.

### 2. `ModelResult` — the universal output

**No model ever returns a bare number.** Every model returns a `ModelResult`
carrying `value`, `confidence`, `interpretation`, `context`, `inputs_used` and
`warnings`. The `value` union is `float | int | str | bool | dict | list | None`
— deliberately broad, because `repo_stress_check` returns a dict and
`classify_convergence` could return a string.

### 3. `compute_confidence()` — the single confidence rule

No model may hardcode `confidence=0.7`. Every confidence value is produced by
one function, from four declared inputs:

```
base
  − data_quality_flags_present      penalty
  − is_heuristic_not_calibrated     penalty
  − depends_on_unobservable         penalty
  + min(source_independence_count × bonus, bonus_cap)
  clamped to [floor, ceiling]
```

Two config-level validators make the numbers self-consistent, so a future edit
cannot silently break them:
- the bonus cap must exceed `ceiling − base`, or the ceiling becomes
  unreachable and the clamp is decorative (**this exact bug was caught by test**);
- the floor must sit below the base, or every score would be clamped upward.

### 4. `MacroThesis` — the codified trade-construction discipline

The schema enforces, by validation rather than convention, that:
- a live trade without `stop_or_invalidation` cannot be constructed;
- a `CONFLICTED` convergence cannot carry a live trade;
- scenario probabilities sum to 1.0 within tolerance;
- a no-trade idea cannot carry a direction;
- an instrument outside the production universe cannot be expressed as a trade.

**NO TRADE is a first-class outcome**, not an exception or a null: a full
`MacroThesis` with `status=WATCH` and `instrument="NONE"`.

---

## Configuration is the only source of truth

No provider name, symbol, endpoint, threshold, port or calibration constant
appears in application code. Everything resolves through:

| File | Contains | Committed? |
|---|---|---|
| `config/settings.yaml` | Every parameter, each wrapped in a `{value, calibration_status, note}` envelope | yes |
| `config/series_registry.yaml` | Every LIVE series route, its verification evidence, and blocked items | yes |
| `config/logging.yaml` | Structured logging configuration | yes |
| `.env` | Secrets only (`FRED_API_KEY`, overrides) | **never** |

### Why the `calibration_status` envelope matters

Every parameter states **how well it is known**:

`institutional_fact` · `institutional_convention` · `conventional` ·
`mechanical_rule` · `fitted_assumption` · `judgment_parameters` ·
`uncalibrated_illustrative`

This is not documentation. `is_heuristic_not_calibrated` is derived from it and
**feeds `compute_confidence()`**, so marking a parameter as uncalibrated
mechanically lowers the confidence of every model that uses it. It is
impossible to add a parameter without declaring how much it should be trusted,
because the config loader rejects anything with an unrecognised status.

### Why the registry refuses to lie

`SeriesRegistry.require_verified()` is the enforcement point for Phase 0
discipline:

- field not defined → `KeyError` naming Section 21.0 rule 3
- field in the `blocked:` list → `NotImplementedError` with the reason
- field not `verified` → `NotImplementedError` naming the tool to run
- field marked `verified` but with no `verified_on` / `verified_value`
  → rejected by validation, because an unbacked verification claim is the
  shortcut an agent would take to unblock a downstream model
- `verified_value` outside `plausible_range` → rejected, since the bounds and
  the observation cannot both be right

The consequence: an unverified series **cannot** reach a model. The failure is
loud and occurs at the point of attempt, rather than upstream as a confusing
empty result.

---

## "Flag, don't fix" — two distinct flag streams

`data_quality_flags` merges two things that are deliberately kept distinct:

**Validation findings** — data that *arrived and looked wrong*: out-of-range
values, duplicate dates, non-monotonic ordering, stale series, implausible
inversion. Produced by `validation.py` against registry-declared bounds.

**Build-report flags** — data that *never arrived*: `FETCH_FAILED:<field>`,
`UNVERIFIED_SERIES_SKIPPED:<field>`, `EMPTY_SERIES:<field>`. Produced by the
builder.

Conflating these would hide the difference between "bad number" and "no number",
which are different problems with different responses: a bad number may still
be usable with a confidence penalty, whereas a missing number means the model
cannot run at all.

### One bad series does not kill the snapshot

But a partial snapshot must be **visibly** partial. The builder degrades
gracefully *with an audit trail*, never silently:

```python
snapshot, report = build_snapshot(country="us")
if not report.is_complete:
    # report.failed, report.skipped_unverified tell you exactly what is missing
```

The report is not optional in the return signature, because a caller that
ignores it cannot distinguish a complete snapshot from a half-empty one.

---

## The verification discipline

### Two kinds of tests, and why both are required

**Offline tests** prove the arithmetic: validation rules, schema gates,
persistence round-trips, config enforcement. They run in the default suite
(seconds) and in CI on every push.

**Live tests** prove the wiring: correct route, correct units, nulls, frequency,
sign conventions. They run explicitly and on a schedule, because a network
dependency in the default suite is how a suite becomes something people ignore.

Section 21.0 rule 1 is explicit that these are not substitutes:

> Unit tests prove the arithmetic; live execution proves the wiring, the units,
> the nulls, the frequency, and the sign conventions.

**This project's evidence that the rule is real:** of the defects found so far,
the four most severe — the `fred_series` object-dtype index, the unapplied
registry `defaults:`, the `treasury_curve`/`yield_curve` name mismatch, and the
curve persistence asymmetry — were **all invisible to synthetic tests** and all
found by live execution. Three of them produced a *plausible-looking* result
rather than an error.

### Economic-plausibility assertions, not just shape assertions

The live snapshot test asserts that the data is **mutually coherent**, because
a mis-mapped symbol usually returns a value that is individually plausible:

- **nominal = real + deflator** — three independent FRED symbols must satisfy
  this identity. A mis-mapping breaks it.
- **`on_rrp_rate < iorb`** — the corridor must exist. This is the assertion
  that catches a volume series mapped to a rate field.
- **`sofr` within 100bp of `iorb`** — normal money-market conditions.
- **10yr > 3mo** — the curve must have the right shape.

These are the checks that catch the failure class where the number looks fine
but the series is wrong — which is the dangerous one, because it produces a
thesis rather than an error.

---

## Phase boundaries are enforced in code

### Country genericity (Section 22.3)

`CountrySettings` rejects a country listed in `enabled` but not in
`implemented`, and `build_snapshot` raises for any country outside
`implemented`. A `country` parameter is **not** a generalization:

> `country: str = "us"` is not a generalization — it is a label on a system
> that currently only works for one value of it.

Adding `de`/`jp`/`gb` requires its own data sources, its own central-bank
reaction function, and its own instrument set. None of that is a label change.

### Stubs are correctly signed, never silently empty

`extensions/*.py` contain Phase 4+ components. Each declares its full
signature and raises `NotImplementedError` naming its phase and required
dependency. An empty function that returns a neutral value is a bug; a stub
that raises is a contract.

### `uv` exclusively

`uv init` / `uv add` / `uv run`; `uv.lock` committed. No pip, poetry or conda.

---

## Module map

| Layer | Module | Responsibility |
|---|---|---|
| Config | `config.py` | Typed, validated config load; registry access |
| Data | `data_layer/openbb_client.py` | Two-path fetch, retries, normalization |
| Data | `data_layer/schemas.py` | `MacroDataSnapshot`, `YieldCurveSnapshot`, `ObservationPoint` |
| Data | `data_layer/validation.py` | Range/staleness/inversion checks — flags, never fixes |
| Data | `data_layer/snapshot_builder.py` | The ONE place a snapshot is assembled |
| Data | `data_layer/persistence.py` | Timestamped parquet audit trail |
| Contracts | `models/contracts.py` | `ModelResult`, `compute_confidence()`, `utc_now()` |
| Thesis | `thesis_layer/schemas.py` | `MacroThesis` and its validation gates |
| Extensions | `extensions/*.py` | Phase 4+ stubs, correctly signed |
| API | `api_layer/` | Phase 2+ |
| Tools | `tools/manual_series_check.py` | Phase 0 route verification CLI |
| Tools | `tools/probe_money_market.py` | Money-market route discovery |
| Tools | `tools/record_verification.py` | Records verification evidence into the registry |

---

## Where the two override rules live

The specification contains internal amendments. Two rules govern conflicts:

1. **Section 22 governs.** Where an integrated `22.x Resolves Finding #N`
   amendment conflicts with earlier text, the amendment wins.
2. **One instruction file only.** There is exactly one root instruction file
   (`AGENTS.md`) holding the entire specification. No second file is ever
   created to hold a subset of it.

Both are honoured throughout this codebase: `compute_confidence`, the canonical
policy gap, the corrected `ModelResult` union, the generalized Kelly objective,
and the corrected `select_instrument()` are all implemented in their **amended**
form, with the superseded placeholder versions never having been written at all
(Section 22.13 requires deletion rather than coexistence).
