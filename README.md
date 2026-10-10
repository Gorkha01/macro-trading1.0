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

**Phases 0–4 build a US-only system; the four post-US multi-country increments (`gb`, then the euro area `eu`, then `de` and `jp`) all landed 2026-10-10.**
`country: str = "us"` is not a generalization — it is a label on a system that, through Phase 4,
worked for exactly one value of it. Multi-country support is Phase 5+, and requires
for *each* new country:

- its own verified data sources,
- its own central-bank reaction function (the ECB's 20-country compromise
  dynamic, the BoJ's deflation-scar + Yield Curve Control, and — for Germany, which
  has no policy rate of its own — a member-state *appropriateness* rule, each need
  genuinely distinct logic — none is "the Fed's
  Taylor Rule with a different country label"),
- its own instrument set.

**`gb` has now earned all three:** seven verified `gb_*`
series, the Bank of England's three *published* rules (contemporaneous, forward-looking,
first-difference — genuinely distinct, not a relabelled Fed rule), and a UK `ProductionUniverse`
(gilts, index-linked gilts, short-sterling, SONIA OIS, FTSE 100). `snapshot_to_thesis_inputs`
dispatches on country, so `/thesis/gb` runs end to end and selects UK instruments. The gb derivation
carries three **disclosed stand-ins** (no published UK output-gap series, no JOLTS/claims/payrolls, no
BoE projection path) — disclosed rather than passed off as measurements.

**`eu` (the euro area) has now earned all three** (landed
2026-10-10): its own verified `eu_*` series (HICP index, main-refi and deposit rates, ESTR,
unemployment, real-GDP level, 3-month and 10-year yields); the **ECB's three published rules** from
ECB Working Paper No 258 — a level rule carrying the euro area's OWN coefficients (2.733 / 1.443,
which the paper's joint Wald test rejects Taylor's 1.5 / 0.5 at p = 0.04 against), and TWO
cointegration rules that read the **long rate** as a structural regressor (the public's long-run
inflation perception) in an **error-correction (change) form** (the level specification is unstable);
and a euro-area `ProductionUniverse` (Bunds/BTPs/OATs, Bund futures, BTP-Bund/OAT-Bund spreads, ESTR
futures, Euro-area OIS, Euro Stoxx 50). The country-aware instrument route table names `ESTR futures`
for the euro policy-path leg — an instrument the US and UK universes both refuse. `eu` is enabled as
the **20-country AGGREGATE**, not per member state. The eu derivation carries disclosed stand-ins
(an ESTIMATED output gap from the real-GDP level; no JOLTS/claims/payrolls; no HICP core split).

**Two real unit defects were found and fixed in the eu increment** (both by reading the LIVE output,
not by any unit test — Lesson 2): `output_gap_change` was fed the raw change in the GDP *level*
(order 10^4, a national-accounts index) rather than the change in the *gap* (percentage points),
and `pi_change` was fed the raw change in the HICP *index* (~+0.44) rather than the change in the
YoY *rate*; the first blew the error-correction prescription to ~4885% and the dispersion to ~4882pp.
Both are now derived from the canonical YoY/growth quantities and pinned by tests with a realistic
GDP magnitude.

**`de` and `jp` have now earned all three too** (both landed 2026-10-10; `country.implemented:
["us", "gb", "eu", "de", "jp"]`). **`de` (Germany)** reads its own verified `de_*` series against the
single ECB stance the ECB actually sets — Germany has **no policy rate of its own**, so a "German
Taylor rule" would be a relabelled ECB rule. The `de` arm is therefore a **member-state
appropriateness** trio (`de_member_appropriateness_rule`, `de_bund_spread_rule`, `de_real_rate_rule`)
that measures the *divergence* of German inflation/output/unemployment/growth and its own Bund curve
from the euro-area aggregate the ECB reacts to, with a German `ProductionUniverse` (Bunds/Bobl/Schatz,
Bund futures, DAX). **`jp` (Japan)** runs a genuinely distinct central-bank framework: the
**Reifschneider–Williams shadow-rate rule** with the `max[0, ·]` ZLB floor and a cumulative-shortfall
term no plain Taylor rule reproduces, plus `jp_ycc_reference_rule` (Yield Curve Control, the 10-year
JGB as the instrument) and `jp_overshoot_commitment_rule` (the BoJ's inflation-**overshooting**
commitment), with a Japanese `ProductionUniverse` (JGBs, JGB futures, Nikkei 225 / Topix futures).
`/thesis/de` and `/thesis/jp` both run end to end. **With this, all five modelled countries are
complete**; the increment proves the *pattern* (three workstreams per country, wired and
mutation-proved) across four structurally different reaction functions.

**The cross-country reasoning layer (layer 4) landed 2026-10-10 (D-150)** — the fourth and last
capability of the multi-country bar. `models/cross_country.py`'s `cross_country_divergence` measures
the **signed real-rate differential** between two complete country systems (same instrument, same
horizon, FX-reconciled — each an input validator), and `select_instrument`'s `CROSS_COUNTRY_DIVERGENCE`
branch names a **duration-neutral cross-market RV pair** (long the higher-real-rate country, short the
other) from config `leg_labels`/`instrument_template`, or refuses with a sentinel inside the noise
band. `build_us_macro_thesis(cross_country=...)` computes the divergence once and threads it. The
`BLOCKED_MULTI_COUNTRY_NOT_BUILT` sentinel is retained but **narrowed** to "malformed divergence
record". The remaining boundary is documented honestly: the two-snapshot **orchestration** (fetching
both countries' data from one request) is an API-layer increment not yet wired
(`docs/PHASE5_DEFERRED.md` §2.4.2).

No function may claim country-genericity it has not earned.

**The FX layer landed 2026-10-10** — the bridge between two countries' rates systems. `fx_spot` had
been declared on the schema and empty in every build since Phase 1; it was recorded as a *data*
block and re-measured as a *wiring* gap (the sixth FALSE BLOCK). Now `data_layer/fx_client.py`
fetches the configured G10 pairs, `build_snapshot` fills `snapshot.fx_spot`, and
`models/fx_conversion.py` converts between currencies with the direction derived from the codes
rather than assumed. **Spot only:** FX forwards remain unavailable on this installation (no
`forward`/`swap`/`basis` route; D-108), so `cip_check`'s live check stays unavailable and no forward
is ever synthesised from a spot value.

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 0 | Repo skeleton, `uv`, config, quality gates | **complete** — 8/8; 21/21 routes verified |
| 1 | Data layer, `MacroDataSnapshot`, snapshot builder, thesis schema | **complete** — 9/9, live-validated |
| 2 | Core models (policy rules, regime, inflation, labor, GDP, curve) | **101/101** — Tiers 1–4 complete (23/23 · 29/29 · 15/15 · 11/11) plus **Tier 5 = 23/23** |
| 3 | Thesis builder + API layer | **complete** — 2/2; `build_us_macro_thesis` runs end to end; the service exposes five surfaces |
| 4 | Risk basics (VaR) + risk-budget hook | **complete** — 4/4 (closed at D-073) |
| 5+ | Tier-5 upgrades: Markov regime, GARCH volatility, joint-draw VaR, econometric tooling, FX carry/parity, commodities, multi-country | **Tier 5 = 23/23 COMPLETE (D-092 … D-125)** — every §21.3 name has a `def`, one function per increment, each with tests, a mutation sweep and a live check. **Not a tier of new work: an UPGRADE PASS (D-096)** — Phases 0–4 built the simple version of each deferred item and Phase 5+ builds the sophisticated one, **deleting nothing**. **Remaining Phase-5 work: the two-snapshot cross-country orchestration** (the cross-country *reasoning* layer itself shipped 2026-10-10, D-150 — per-country coverage is complete for all five modelled countries — `us`, `gb`, the euro area `eu`, `de` and `jp` — each with its *own* data registry, reaction function and instrument set, and the reasoning layer now measures the divergence between any two of them) **and FX-forward data coverage** (spot shipped 2026-10-10; the forward is still a hard data block). GARCH and the whole crisis-shock engine — factor set, engine, simulation half and the four-scenario library — closed 2026-10-09 (`docs/PHASE5_DEFERRED.md` §2.2/§2.3) |

> **The `98` this row used to carry implied a 20-name Tier 5, and §21.3's list has 23.**
> Resolved 2026-09-26 against the authority: **23** is the work list (the project has recorded
> three disagreeing tier-5 counts; §21.3's table, *and only that table*, governs — §22.1).
> `101/101` is **derived, not recalled**: 78 Tier-1–4 names + **23** implemented Tier-5 names,
> measured 2026-09-28 against `src/` (**O-147** — a carried `15/23` was an off-by-one). **No
> Tier-5 name remains**; the last, `statement_text_diff`, shipped at **D-125**.
>
> **Phase 5 is under way by explicit operator instruction**, one function per increment, each
> to production standard and each independently verified. With the §21.3 list complete, the
> standing obligations are the **multi-country theses** (all four post-US countries — `gb`, the euro
> area `eu`, `de` and `jp` — landed 2026-10-10, so only the cross-country *reasoning* layer remains)
> — and the **22 Tier-5 functions wired but
> not yet called from the thesis pipeline**. See
> `docs/PROGRESS.md` for the live state and `docs/DECISIONS.md` for the per-increment evidence.

**Run the API:**
```bash
uv run uvicorn macro_engine.api_layer.app:app --host 127.0.0.1 --port 8000
# /health · /thesis/us · /dashboard_data · /query · /thesis/us/stream (SSE)
```

### Quality gates (measured 2026-09-28, after D-125)

```bash
uv run ruff check src tests tools scripts    # All checks passed!
uv run ruff format --check .                 # 289 files already formatted
uv run mypy --strict src tests tools scripts # Success: no issues found in 289 source files
uv run pytest -q --junitxml=build/full.xml   # 4054 tests / 0 failed / 0 errors / 1 skipped
uv run pytest -m live                        # gated on tools/openbb_reachability.py; scheduled CI only
uv run python tools/sweep_health.py          # run LAST: 50 sweeps, 0 leftovers, OK
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
uv run pytest              # offline suite (4054 passed / 1 skipped; no network)
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
  extensions/           Phase 5+ stubs (6, dependency-gated) + scenario_engine.py (real)
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
