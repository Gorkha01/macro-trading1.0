# Global Macro Reasoning Engine

A **reasoning layer**, not a trading system.

This service ingests macro and market data via OpenBB, runs a suite of
quantitative macro models (policy rules, regime detection, inflation and GDP
nowcasting, yield-curve decomposition, FX parity/carry, commodity and equity
macro frameworks, volatility models), and synthesizes their outputs into a
structured, machine-readable **`MacroThesis`** — the codified form of the
institutional trade-construction discipline:

> *"I think [policy variable] will move by more than the market has priced, on
> this timeframe, expressed through this instrument, sized according to my
> conviction and the asymmetry of the payoff, with this stop and this catalyst
> calendar."*

It does **not** place orders. It does **not** manage live positions. Execution
remains a human (or a separate, deliberately-scoped system) reading its output.

The authoritative specification is [`AGENTS.md`](./AGENTS.md).

---

## Scope, stated honestly

**Phases 0–4 build a US-only system.** `country: str = "us"` is not a
generalization — it is a label on a system that currently works for exactly one
value of it. Multi-country support (`de`, `jp`, `gb`) is Phase 5+, and requires
for *each* new country:

- its own verified data sources,
- its own central-bank reaction function (the ECB's 20-country compromise
  dynamic, the BoJ's deflation-scar-tissue bias, and the PBoC's non-Western
  reaction function each need genuinely distinct logic — none is "the Fed's
  Taylor Rule with a different country label"),
- its own instrument set.

No function may claim country-genericity it has not earned.

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 0 | Repo skeleton, `uv`, config, quality gates | **complete** — 8/8; 21/21 routes verified |
| 1 | Data layer, `MacroDataSnapshot`, snapshot builder, thesis schema | **complete** — 9/9, live-validated |
| 2 | Core models (policy rules, regime, inflation, labor, GDP, curve) | **95/101** — Tiers 1–4 complete (23/23 · 29/29 · 15/15 · 11/11) plus **Tier 5 = 17/23**; the **6** outstanding are all Tier 5 — **not a backlog** |
| 3 | Thesis builder + API layer | **complete** — 2/2; `build_us_macro_thesis` runs end to end; the service exposes five surfaces |
| 4 | Risk basics (VaR) + risk-budget hook | **complete** — 4/4 (closed at D-073) |
| 5+ | Tier-5 upgrades: Markov regime, GARCH volatility, joint-draw VaR, econometric tooling, FX carry/parity, commodities, multi-country | **under way** — **Tier 5 = 17/23** (D-092 … D-120), one function per increment, each with tests, a mutation sweep and a live check. **Not a tier of new work: an UPGRADE PASS (D-096)** — Phases 0–4 built the simple version of each deferred item and Phase 5+ builds the sophisticated one, **deleting nothing**. Multi-country still needs, per country, its *own* data registry, reaction function and instrument set |

> **The `98` this row used to carry implied a 20-name Tier 5, and §21.3's list has 23.**
> Resolved 2026-09-26 against the authority: **23** is the work list (the project has recorded
> three disagreeing tier-5 counts; §21.3's table, *and only that table*, governs — §22.1).
> `95/101` is **derived, not recalled**: 78 Tier-1–4 names + **17** implemented Tier-5 names,
> measured 2026-09-27 against `src/` (**O-147** — a carried `15/23` was an off-by-one). The
> **6** remaining are `gold_driver_attribution` ·
> `metals_complex_divergence` · `sector_rotation_prior` · `duration_sensitivity` ·
> `factor_tilt_prior` · `statement_text_diff`.
>
> **Phase 5 is under way by explicit operator instruction**, one function per increment, each
> to production standard and each independently verified. The 7 outstanding Tier-5 items are
> the *entry point* for the rest, not a backlog. See `docs/PROGRESS.md` for the live state and
> `docs/DECISIONS.md` for the per-increment evidence.

**Run the API:**
```bash
uv run uvicorn macro_engine.api_layer.app:app --host 127.0.0.1 --port 8000
# /health · /thesis/us · /dashboard_data · /query · /thesis/us/stream (SSE)
```

### Quality gates (measured 2026-09-27, after D-120)

```bash
uv run ruff check src tests tools scripts    # All checks passed!
uv run ruff format --check .                 # 281 files already formatted
uv run mypy --strict src tests tools scripts # Success: no issues found in 281 source files
uv run pytest -q --junitxml=build/full.xml   # 3769 passed / 0 failed / 0 errors / 1 skipped
uv run pytest -m live                        # gated on tools/openbb_reachability.py; scheduled CI only
uv run python tools/sweep_health.py          # run LAST: 48 sweeps, 0 leftovers, OK
```

`pytest` runs the **default marker set** (`not live and not slow`) — `slow` tests exist and are
run explicitly when they are the thing you changed (e.g. the ~560 s two-copies-agree test over
the real sweep catalogue).

Three notes that are easy to get wrong:

- **All four roots are required** in the `mypy` argument list (`src tests tools scripts`). It is
  the only gate that sees a `src/` rename break a `scripts/` consumer.
- **Read the suite verdict from `--junitxml`, not the exit code.** On this host the sandbox's
  safe-delete hook refuses `pytest`'s own bulk temp-dir cleanup and leaks **`exit=1` on a green
  run**; the XML is the artefact the run itself produced.
- **`sweep_health.py` runs LAST.** It is a photograph of the working tree: run it before a sweep
  and it reports on a state that a later sweep can invalidate. It also gates the `quality` CI job
  *before* the suite.

## Setup

This project uses **`uv` exclusively**. Do not use pip, poetry, or conda.

```bash
uv sync --extra dev        # create .venv, install locked dependencies
uv run pytest              # offline suite (3769 passed / 1 skipped; no network)
uv run pytest -m live      # live suite (real OpenBB/FRED calls, scheduled CI)
uv run ruff check .        # lint
uv run ruff format --check .
uv run mypy --strict src tests tools scripts
```

### Why two test suites

Unit tests prove the **arithmetic**; live execution proves the **wiring** — the
units, the nulls, the frequency, the sign conventions. They are not substitutes
(Section 21.0 rule 1). The recurring failure mode this project has actually
suffered is a **plausible-looking wrong value**: a unit error, a wrong sign, a
null read as zero — each of which passes a synthetic test written against the
same misreading. In the first audit round, **the majority of defects found were
invisible to synthetic tests**, and several returned a plausible number rather
than an error.

The `live` marker is therefore excluded from the default run (a network
dependency in the default suite is how a suite becomes something people ignore)
and runs explicitly, gated on `tools/openbb_reachability.py` and on a CI
schedule. The running tally lives in `docs/OPEN_ISSUES.md` (the Loophole
Ledger) — **not here**, where a count goes stale silently.

## Configuration

- `config/settings.yaml` — model parameters and thresholds. Every parameter
  carries an explicit `calibration_status`, and that status feeds
  `compute_confidence()`, so marking a parameter uncalibrated mechanically
  lowers the confidence of every model that uses it.
- `config/series_registry.yaml` — internal field name → provider route. Every
  LIVE input resolves through this file, and **no provider, symbol or endpoint
  literal appears in application code**. An entry cannot be marked `verified`
  without recording the observed value and retrieval date; an unverified entry
  cannot reach a model.
- `.env` — secrets only. Never committed.

## Governing principles

1. **Flag, don't fix.** Anomalies are recorded in
   `MacroDataSnapshot.data_quality_flags`, never silently dropped and never
   silently corrected. Build-report flags (`FETCH_FAILED`, `EMPTY_SERIES`,
   `UNVERIFIED_SERIES_SKIPPED`) are kept distinct from validation findings,
   because "bad number" and "no number" are different problems.
2. **No model returns a bare number.** Every output is a `ModelResult` carrying
   its interpretation, context, inputs, and warnings.
3. **Confidence is computed, never asserted.** `compute_confidence()` derives it
   from stated factors. No hardcoded `confidence=0.X` literals.
4. **Nothing is guessed.** An input whose source is not defined is `BLOCKED`
   and raises — it is never filled with a "reasonable default". Blocked items
   are tracked in the Loophole Ledger and surfaced in every affected thesis's
   `warnings`.
5. **Aggregation discards information.** The three policy rules are never
   averaged; their divergence *is* the signal. Source families are counted for
   genuine independence, so five sub-measures of one release are one vote.
6. **A partial snapshot is visibly partial.** One failed series does not abort
   the build, but every omission is reported and flagged. `build_snapshot()`
   returns a report that is not optional to read.

## Documentation

| Document | Contents |
|---|---|
| [`AGENTS.md`](./AGENTS.md) | The single authoritative specification |
| [`docs/PROGRESS.md`](./docs/PROGRESS.md) | The live tracker — **start here for current status** |
| [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) | How the layers fit, the four contracts, where boundaries are enforced |
| [`docs/BUILD_STATE.md`](./docs/BUILD_STATE.md) | Per-function completion and real-data validation records |
| [`docs/DECISIONS.md`](./docs/DECISIONS.md) | Every deviation from the spec, with its evidence |
| [`docs/OPEN_ISSUES.md`](./docs/OPEN_ISSUES.md) | The Loophole Ledger: blocked inputs, inherent limits, deferred work |
| [`docs/SERIES_VERIFICATION.md`](./docs/SERIES_VERIFICATION.md) | Phase 0 evidence — all 21 verified routes and their values |
| [`docs/CHANGELOG.md`](./docs/CHANGELOG.md) | What changed |

`docs/PHASE4_HANDOFF.md` is **history**, not a live to-do list — it was
purpose-built for Phase 4, which closed at D-073.

## Layout

```
config/                 settings.yaml, series_registry.yaml, logging.yaml
src/macro_engine/
  config.py             typed settings loader + registry enforcement
  settings_store.py     read/write access to persisted settings
  audit.py              audit-event plumbing
  deployment.py         deployment/runtime surface
  data_layer/           openbb_client, alfred_client, schemas, validation,
                        snapshot_builder, persistence
  models/               contracts (ModelResult, compute_confidence) + Modules 4-11, 17
  thesis_layer/         MacroThesis schema + build_us_macro_thesis()
  portfolio/            risk budgeting (Riskfolio-Lib hook)
  api_layer/            FastAPI service
  extensions/           Phase 5+ stubs, signatures only
tests/                  mirrors src/ (api_layer, data_layer, models, portfolio, thesis_layer)
tools/                  gates and probes — sweep_health, reachability_audit,
                        openbb_reachability, integrity_audit, record_verification,
                        manual_series_check, and the live_*_probe / diagnosis scripts
scripts/                the mutation-sweep drivers and their shared gate module
docs/                   architecture, progress, decisions, open issues, build state
```

## Contributing

Implementation follows the Section 21.2 process, one function at a time, never
in batch — read the spec, confirm every input's source, implement, unit-test with
hand-verified values, test the warning paths, execute against real data, assess
plausibility, run the gates, record it, then **report and wait for approval**
before starting the next function.

# macro
