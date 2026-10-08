## CANONICAL MERGE RULE

This AGENTS.md is the single authoritative instruction file. The external-review resolutions have been integrated beside the sections and phases they govern rather than relying only on a late override. Where an integrated canonical amendment conflicts with earlier text, the amendment governs. Original review wording is preserved verbatim at its integrated location.

### ORIGINAL REVIEW RESOLUTION HEADER — PRESERVED VERBATIM

## 22. Resolution of External Review Findings

An external review found 12 real architectural/logic contradictions and one
genuine implementation blocker. Each is resolved below, in the order
raised, with a single canonical rule replacing every prior ambiguous or
contradictory statement. **Where this section conflicts with anything
earlier in this document, this section governs.**

---

# Global Macro Reasoning Engine — Design & Implementation Specification

**Version 1.0 | Production Specification | OpenBB-Backed Macro Thesis System**

---

## 1. Executive Summary

### 22.2 Resolves Finding #2 — Single Instruction File

The project uses **exactly one instruction file at the repository root.**
Wherever this document says "AGENTS.md," that is a placeholder for
**whatever filename the coding tool in use actually reads automatically**
(e.g. `AGENTS.md`, `CLAUDE.md`) — there is one such file, containing this
entire specification, and no second file is ever created to hold a subset
of it. Every prior "append this to AGENTS.md" instruction means: this
content becomes part of the single instruction file, in place, not a new
file.

---


**Package management: this project uses `uv` exclusively** — `uv init`,
`uv add <package>`, `uv run`. Do not use pip, poetry, or conda. Commit
`uv.lock`. This matches the companion standalone data-pipeline project's
convention; there is no reason to use a different tool between the two.

This document specifies a production-grade **macro reasoning engine** — a Python
backend service that ingests macro and market data via OpenBB, runs a suite of
quantitative macro models (policy rules, regime detection, inflation/GDP
nowcasting, yield curve decomposition, FX parity/carry, commodity and equity
macro frameworks, volatility models), and synthesizes their outputs into a
structured, machine-readable **MacroThesis** object — the codified form of the
institutional trade-construction discipline: *"I think [policy variable] will
move by more than the market has priced, on this timeframe, expressed through
this instrument, sized according to my conviction and the asymmetry of the
payoff, with this stop and this catalyst calendar."*

The system exposes this logic through a FastAPI service designed from day one
to be registrable as a custom agent/backend in OpenBB Workspace, including
support for streaming step-by-step reasoning events compatible with OpenBB's
AI SDK/Copilot pattern.

### 1.1 What This System Is

A **reasoning layer**, not a trading system. It answers: *what is the current
macro regime, what does each model believe about growth/inflation/policy, how
does that compare to what markets are pricing, and — if a gap exists — what
would a clean, well-constructed trade expression of that gap look like.* It
does not place orders. It does not manage live positions. Execution remains a
human (or a separate, deliberately-scoped execution system) reading its output.

### 1.2 Phase 1 Scope (What Ships First)

### 22.3 Resolves Finding #3 — Genuine US-Only Scope, Honestly Stated

**The prior claim of multi-country generality was not earned by the actual
code and is retracted.** The corrected, honest scope:

> **Phases 0–4 build a US-only system.** Every function, schema, and
> endpoint is explicitly US-scoped (`country: str = "us"` is not a
> generalization — it is a label on a system that currently only works for
> one value of it). Multi-country support (`de`, `jp`, `gb`) is Tier 5 —
> Phase 5+ — and requires, for EACH new country: its own verified data
> sources (Section 21.1-style registry), its own central-bank reaction
> function (a genuinely different Module 4 instantiation per Section
> 15's ECB/BoJ/BoE/PBoC entries — these are NOT the Fed's Taylor Rule with
> a different country label; the ECB's structural 20-country-compromise
> dynamic, the BoJ's institutional deflation-scar-tissue bias, and the
> PBoC's non-Western reaction function each require distinct logic), and
> its own instrument set. **No function may claim country-genericity it
> has not earned** — `select_instrument()`, corrected below (22.3.1),
> is representative of the standard every "multi-country-ready" function
> must actually meet.


- OpenBB-backed data layer for US macro/market data (Section 5).
- Core models: Taylor-rule family, rule-based regime classifier, simple
  inflation nowcast, labor synthesis score, simple GDP nowcast, yield curve
  level/slope/curvature + breakevens (Section 6, "starter" versions of each).
- MacroThesis schema and `build_us_macro_thesis()` (Section 7).
- FastAPI service with `/health`, `/thesis/us`, `/dashboard_data` (Section 8).
- Basic risk metrics (volatility, historical VaR) — no portfolio optimizer yet.
- Unit tests for all of the above.

### 1.3 Later Phases (Explicitly Deferred, Hooks Designed In Now)

- Markov-switching regime model (`statsmodels.tsa.regime_switching`).
- Bayesian thesis updating (PyMC / scipy.stats).
- FX carry/parity models, commodity framework, equity macro factor models.
- GARCH-family volatility (`arch`), full VaR/CVaR suite, stress testing.
- Riskfolio-Lib portfolio construction.
- `vectorbt` rapid backtesting, `NautilusTrader` event-driven architecture.
- `MLflow` experiment tracking (only once multiple model variants exist).
- `APScheduler` automation.
- Multi-country theses (ECB, BoJ, BoE) — architecture supports this from day
  one via a `country` parameter threaded through every layer, but only `us`
  is implemented in Phase 1.

---

## 2. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         OpenBB Workspace (future)                     │
│              custom agent/backend registration, UI rendering          │
└───────────────────────────────┬──────────────────────────────────────┘
                                 │ HTTP (JSON + SSE streaming)
┌───────────────────────────────▼──────────────────────────────────────┐
│                          API LAYER (FastAPI)                          │
│   /health   /thesis/{country}   /query   /dashboard_data              │
│   reasoning_step SSE stream · request/response Pydantic schemas       │
└───────────────────────────────┬──────────────────────────────────────┘
                                 │
┌───────────────────────────────▼──────────────────────────────────────┐
│                         THESIS LAYER (Module 14)                      │
│   build_us_macro_thesis() → MacroThesis                               │
│   - consumes ALL model outputs                                        │
│   - maps numeric model outputs → regime label, views, gap, signals    │
│   - encodes hypothesis→thesis→evidence→probability→risk→catalyst      │
│     →instrument→sizing pipeline as data, not prose                    │
└───────────────────────────────┬──────────────────────────────────────┘
                                 │
┌───────────────────────────────▼──────────────────────────────────────┐
│                    MODELS LAYER (Modules 4–11, 17–18)                 │
│  ┌────────────┐ ┌──────────┐ ┌───────────┐ ┌────────────┐            │
│  │Policy Rules│ │  Regime  │ │ Inflation │ │   Labor    │            │
│  │ (Mod. 4)   │ │(Mod. 3/4)│ │ Nowcast   │ │ Synthesis  │            │
│  └────────────┘ └──────────┘ │ (Mod. 5)  │ │ (Mod. 6)   │            │
│  ┌────────────┐ ┌──────────┐ └───────────┘ └────────────┘            │
│  │GDP Nowcast │ │  Yield   │ ┌───────────┐ ┌────────────┐            │
│  │ (Mod. 7)   │ │  Curve   │ │FX Carry / │ │ Commodity/ │            │
│  └────────────┘ │(Mod. 8)  │ │Parity(9)  │ │ Oil (10)   │            │
│  ┌────────────┐ └──────────┘ └───────────┘ └────────────┘            │
│  │Equity Macro│ ┌──────────┐ ┌───────────┐                           │
│  │ (Mod. 11)  │ │Volatility│ │Risk/VaR   │                           │
│  └────────────┘ │(Mod. 17) │ │(Mod.17/18)│                           │
│                  └──────────┘ └───────────┘                          │
└───────────────────────────────┬──────────────────────────────────────┘
                                 │
┌───────────────────────────────▼──────────────────────────────────────┐
│                         DATA LAYER                                    │
│   OpenBBClient (local API :6900 / Python package fallback)            │
│   MacroDataSnapshot Pydantic schemas · validation · retries/backoff   │
│   Local persistence: CSV/Parquet now → DuckDB hook (Section 12)       │
└───────────────────────────────┬──────────────────────────────────────┘
                                 │
┌───────────────────────────────▼──────────────────────────────────────┐
│                    OpenBB Platform (local, :6900)                     │
│         FRED · Treasury · BLS/BEA (via FRED) · FX · Commodities        │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.1 Layer Responsibilities

| Layer | Responsibility | Does NOT do |
|---|---|---|
| Data | Fetch, validate, timestamp, persist raw series | Interpret meaning |
| Models | Turn raw series into quantified views (rates, gaps, scores, regime probabilities) | Decide what to trade |
| Thesis | Synthesize model outputs into one coherent, structured, falsifiable view with gap/risk/catalyst/instrument | Execute anything |
| API | Expose thesis/model output over HTTP, stream reasoning | Contain macro logic itself |

### 2.2 Data Flow

`OpenBB → OpenBBClient (data layer) → MacroDataSnapshot → Models (each model
consumes the snapshot + its own config) → Model outputs (typed, with
confidence/uncertainty) → Thesis builder (cross-checks convergence, computes
model-vs-market gap, assembles MacroThesis) → API layer serializes to JSON /
streams reasoning_step events → (future) Workspace renders`

### 2.3 Extension Points Built In From Day One

Every layer accepts a `country: str` parameter (default `"us"`) even though
only US logic is implemented in Phase 1 — this avoids a refactor later when
ECB/BoJ/BoE theses are added. Every model returns a typed result with an
explicit `confidence: float` and `data_vintage: datetime` field so DuckDB
point-in-time storage (Section 12) and MLflow experiment tracking (Section 12)
can be bolted on without changing model signatures. The Risk layer's
`RiskInputs` schema is deliberately shaped to match what `vectorbt` and
`Riskfolio-Lib` expect natively, minimizing adapter code later.

---

## 3. Repository Layout and Module Structure

```
macro-reasoning-engine/
├── pyproject.toml
├── .env.example
├── README.md
├── config/
│   ├── settings.yaml              # country list, model params, thresholds
│   ├── series_registry.yaml       # OpenBB series → internal field mapping
│   └── logging.yaml
├── src/
│   └── macro_engine/
│       ├── __init__.py
│       ├── data_layer/
│       │   ├── openbb_client.py       # OpenBBClient — Section 5
│       │   ├── schemas.py             # MacroDataSnapshot, per-domain schemas
│       │   ├── validation.py          # sanity checks, Section 5.4
│       │   └── persistence.py         # CSV/Parquet writer; DuckDB hook stub
│       ├── models/
│       │   ├── policy_rules.py        # Module 4 ↔ Taylor/Balanced/1st-Diff
│       │   ├── regime.py              # Modules 3/4 ↔ rule-based + Markov hook
│       │   ├── inflation_nowcast.py   # Module 5
│       │   ├── labor_synthesis.py     # Module 6
│       │   ├── gdp_nowcast.py         # Module 7
│       │   ├── yield_curve.py         # Module 8
│       │   ├── fx_carry.py            # Module 9
│       │   ├── commodities.py         # Module 10
│       │   ├── equity_macro.py        # Module 11
│       │   ├── volatility.py          # Module 17 (starter; arch/GARCH hook)
│       │   └── risk.py                # Modules 17–18 ↔ VaR/CVaR/drawdown
│       ├── thesis_layer/
│       │   ├── schemas.py             # MacroThesis, sub-schemas
│       │   └── builder.py             # build_us_macro_thesis()
│       ├── portfolio/
│       │   └── risk_budget.py         # Riskfolio-Lib hook, Section 9
│       ├── api_layer/
│       │   ├── app.py                 # FastAPI app factory
│       │   ├── routes_health.py
│       │   ├── routes_thesis.py
│       │   ├── routes_query.py
│       │   ├── routes_dashboard.py
│       │   ├── reasoning_stream.py    # SSE reasoning_step events
│       │   └── schemas.py             # request/response models
│       ├── extensions/                # Section 12 — deferred, stubbed only
│       │   ├── duckdb_store.py
│       │   ├── bayesian_updater.py
│       │   ├── backtest_vbt.py
│       │   ├── nautilus_adapter.py
│       │   ├── mlflow_tracking.py
│       │   └── scheduler.py
│       └── config.py                  # Pydantic settings loader
├── tests/
│   ├── data_layer/
│   ├── models/
│   ├── thesis_layer/
│   └── api_layer/
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DECISIONS.md
│   ├── MODULE_MAPPING.md              # Section 14 table, as a living doc
│   └── CHANGELOG.md
└── tools/
    └── manual_series_check.py         # quick CLI to test one OpenBB series
```

### 3.1 Module-to-Course Mapping (summary — full table in Section 14)

| Code module | Course module(s) |
|---|---|
| `models/policy_rules.py` | Module 4 |
| `models/regime.py` | Modules 3, 4 |
| `models/inflation_nowcast.py` | Module 5 |
| `models/labor_synthesis.py` | Module 6 |
| `models/gdp_nowcast.py` | Module 7 |
| `models/yield_curve.py` | Module 8 |
| `models/fx_carry.py` | Module 9 |
| `models/commodities.py` | Module 10 |
| `models/equity_macro.py` | Module 11 |
| `models/volatility.py`, `models/risk.py`, `portfolio/risk_budget.py` | Modules 17, 18 |
| `thesis_layer/builder.py` | Module 14 |
| `extensions/backtest_vbt.py`, `extensions/nautilus_adapter.py` | Module 15 (case-study-informed validation) |

---

## 4. Tooling and Dependencies

| Tool | Purpose | Used by | Phase |
|---|---|---|---|
| `openbb` (Python package) | Primary data gateway | Data layer | 1 |
| `httpx` | HTTP client to local OpenBB API (:6900) as fallback/alt path | Data layer | 1 |
| `pydantic` v2 | All schemas — data, models, thesis, API | Every layer | 1 |
| `pyyaml` | Config files | `config.py` | 1 |
| `python-dotenv` | `.env` secrets loading | `config.py` | 1 |
| `fastapi` + `uvicorn` | API layer | API layer | 1 |
| `pandas`, `numpy` | Core numerical/time-series handling | Data, models | 1 |
| `scipy` | Simple stats, Bayesian point updates | `models/*`, risk | 1 |
| `pytest`, `ruff`, `mypy` | Testing/quality | All | 1 |
| `statsmodels` | Regression, ADF/KPSS, `tsa.regime_switching` (Markov), `tsa.statespace` (Kalman) | `models/regime.py`, future cointegration/Kalman work | 1 (basic regression) / 5+ (Markov, Kalman) |
| `arch` | GARCH-family conditional volatility | `models/volatility.py` | 5+ |
| `scikit-learn` | PCA (yield curve factor structure), general ML utilities | `models/yield_curve.py` (PCA), future factor work | 5+ |
| `sktime` | Time-series forecasting model management | `models/gdp_nowcast.py`, `inflation_nowcast.py` advanced versions | 5+ |
| `pymc` | Full-posterior Bayesian models | `extensions/bayesian_updater.py` | 5+ (deferred; scipy.stats suffices for Phase 1 point updates) |
| `riskfolio-lib` | Portfolio optimization, risk budgeting | `portfolio/risk_budget.py` | 4 (basics) / 5+ (full) |
| `pyportfolioopt` | Only if a specific optimizer Riskfolio-Lib lacks is needed | `portfolio/risk_budget.py` | optional, evaluate at Phase 4 |
| `vectorbt` | Fast rule-based backtesting | `extensions/backtest_vbt.py` | 5+ |
| `nautilus_trader` | Event-driven architecture, future live execution simulation | `extensions/nautilus_adapter.py` | 5+ |
| `pysystemtrade` | Optional reference only — do not force integration if redundant with NautilusTrader | n/a | optional |
| `quantstats` | Performance/tear-sheet reporting | `extensions/backtest_vbt.py` reporting | 5+ |
| `apscheduler` | Scheduled refresh jobs | `extensions/scheduler.py` | 5+ |
| `mlflow` | Experiment tracking once multiple model variants exist | `extensions/mlflow_tracking.py` | 5+ (explicitly deferred per your instruction) |
| **NOT USED** | `pykalman` (unmaintained since ~2015) | — | prohibited; use `statsmodels.tsa.statespace` |

**Rule enforced throughout this spec:** no dependency is imported until the
phase that actually needs it. `extensions/` modules exist as file stubs with
docstrings and function signatures only in Phase 1 — no dead imports, no
installed-but-unused packages bloating the Phase 1 environment.

---

## 5. Data Layer Specification

### 5.1 OpenBB Client Design

```python
# src/macro_engine/data_layer/openbb_client.py

from __future__ import annotations
import logging
from datetime import datetime
from typing import Any

import httpx
import pandas as pd
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class OpenBBClientConfig(BaseModel):
    local_api_base_url: str = "http://127.0.0.1:6900"
    use_local_api_first: bool = True
    max_retries: int = 3
    backoff_seconds: float = 1.5
    timeout_seconds: float = 15.0

class OpenBBFetchError(Exception):
    """Raised when both the local API and the Python package path fail."""

class OpenBBClient:
    """
    Thin, resilient wrapper around OpenBB. Tries the local Platform API
    first (http://127.0.0.1:6900) for lower latency and to avoid re-
    initializing the SDK per call; falls back to the `openbb` Python
    package directly if the local API is unreachable.

    Every public method returns a pandas.DataFrame with a normalized
    schema: columns = [date, value, series_id, source], and raises
    OpenBBFetchError (never a raw provider exception) on total failure
    after retries — callers handle ONE exception type.
    """

    def __init__(self, config: OpenBBClientConfig | None = None):
        self.config = config or OpenBBClientConfig()
        self._http = httpx.Client(
            base_url=self.config.local_api_base_url,
            timeout=self.config.timeout_seconds,
        )
        self._obb = None  # lazy-imported openbb package, Python fallback path

    def _lazy_import_obb(self):
        if self._obb is None:
            from openbb import obb
            self._obb = obb
        return self._obb

    def fetch_series(
        self,
        provider: str,
        endpoint: str,
        params: dict[str, Any],
        series_label: str,
    ) -> pd.DataFrame:
        """
        provider: e.g. 'fred'
        endpoint: e.g. 'economy.fred_series'
        params: provider-specific query params (e.g. {'symbol': 'CPIAUCSL'})
        series_label: internal field name this maps to (see series_registry.yaml)
        """
        last_exc: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                if self.config.use_local_api_first:
                    return self._fetch_via_local_api(endpoint, params, series_label)
                return self._fetch_via_package(endpoint, params, series_label)
            except Exception as exc:  # noqa: BLE001 — intentionally broad, logged
                last_exc = exc
                logger.warning(
                    "fetch_series attempt %s/%s failed for %s: %s",
                    attempt, self.config.max_retries, series_label, exc,
                )
                if attempt < self.config.max_retries:
                    import time
                    time.sleep(self.config.backoff_seconds * attempt)
                else:
                    # final attempt: try the OTHER path once before giving up
                    try:
                        if self.config.use_local_api_first:
                            return self._fetch_via_package(endpoint, params, series_label)
                        return self._fetch_via_local_api(endpoint, params, series_label)
                    except Exception as fallback_exc:  # noqa: BLE001
                        last_exc = fallback_exc
        raise OpenBBFetchError(
            f"Failed to fetch {series_label} via both local API and package "
            f"after {self.config.max_retries} attempts: {last_exc}"
        )

    def _fetch_via_local_api(self, endpoint, params, series_label) -> pd.DataFrame:
        resp = self._http.get(f"/api/v1/{endpoint.replace('.', '/')}", params=params)
        resp.raise_for_status()
        payload = resp.json()
        return self._normalize(payload.get("results", payload), series_label)

    def _fetch_via_package(self, endpoint, params, series_label) -> pd.DataFrame:
        obb = self._lazy_import_obb()
        module_path = endpoint.split(".")
        target = obb
        for part in module_path:
            target = getattr(target, part)
        result = target(**params)
        return self._normalize(result.to_df() if hasattr(result, "to_df") else result, series_label)

    def _normalize(self, raw: Any, series_label: str) -> pd.DataFrame:
        df = pd.DataFrame(raw) if not isinstance(raw, pd.DataFrame) else raw
        df = df.rename(columns={c: c.lower() for c in df.columns})
        if "date" not in df.columns:
            raise OpenBBFetchError(f"Normalized frame for {series_label} missing 'date' column")
        value_col = "value" if "value" in df.columns else df.columns[-1]
        out = df[["date", value_col]].rename(columns={value_col: "value"})
        out["series_id"] = series_label
        out["source"] = "openbb"
        out["retrieved_at"] = datetime.utcnow()
        return out
```

### 5.2 Required Series (US, Phase 1)

Pulled through OpenBB's FRED-backed and Treasury-backed providers, mapped to
internal field names in `config/series_registry.yaml`:

| Internal field | OpenBB call (indicative) | Course module |
|---|---|---|
| `gdp_real` | `obb.economy.gdp.real` | 7 |
| `gdp_nominal` | `obb.economy.gdp.nominal` | 7 |
| `cpi_headline`, `cpi_core` | `obb.economy.fred_series(symbol=...)` | 5 |
| `pce_core` | `obb.economy.fred_series` | 5 |
| `ppi` | `obb.economy.fred_series` | 5 |
| `unemployment_rate` | `obb.economy.fred_series` | 6 |
| `initial_claims`, `continuing_claims` | `obb.economy.fred_series` | 6 |
| `jolts_openings`, `jolts_quits` | `obb.economy.fred_series` | 6 |
| `yield_curve` (1mo–30yr) | `obb.fixedincome.government.treasury_rates` | 2, 8 |
| `tips_yields` | `obb.fixedincome.government.tips_yields` (or FRED fallback) | 8 |
| `fed_funds_rate` | `obb.economy.fred_series(symbol='FEDFUNDS')` | 2, 4 |
| `fx_spot` (G10 pairs) | `obb.currency.price.historical` | 9 |
| `commodity_spot` (WTI, gold, copper) | `obb.commodity.price.spot` | 10 |
| `equity_index` (SPX, NDX, etc.) | `obb.equity.price.historical` | 11 |
| `credit_spread_hy`, `credit_spread_ig` | `obb.economy.fred_series` | 8, 17 |

### 5.3 Pydantic Schemas

```python
# src/macro_engine/data_layer/schemas.py

from datetime import datetime, date
from pydantic import BaseModel, Field

class ObservationPoint(BaseModel):
    observation_date: date
    value: float
    series_id: str
    source: str = "openbb"
    retrieved_at: datetime

class YieldCurveSnapshot(BaseModel):
    as_of: date
    tenors: dict[str, float]  # e.g. {"3mo": 5.3, "2yr": 4.8, ...}

class MacroDataSnapshot(BaseModel):
    """The single object passed into every model. One snapshot = one
    point-in-time bundle of everything a model might need, so models
    never fetch data themselves — pure separation of data vs. logic."""
    country: str = "us"
    as_of: datetime
    gdp_real: list[ObservationPoint] = Field(default_factory=list)
    gdp_nominal: list[ObservationPoint] = Field(default_factory=list)
    cpi_headline: list[ObservationPoint] = Field(default_factory=list)
    cpi_core: list[ObservationPoint] = Field(default_factory=list)
    pce_core: list[ObservationPoint] = Field(default_factory=list)
    ppi: list[ObservationPoint] = Field(default_factory=list)
    unemployment_rate: list[ObservationPoint] = Field(default_factory=list)
    initial_claims: list[ObservationPoint] = Field(default_factory=list)
    continuing_claims: list[ObservationPoint] = Field(default_factory=list)
    jolts_openings: list[ObservationPoint] = Field(default_factory=list)
    jolts_quits: list[ObservationPoint] = Field(default_factory=list)
    yield_curve: YieldCurveSnapshot | None = None
    tips_yields: YieldCurveSnapshot | None = None
    fed_funds_rate: list[ObservationPoint] = Field(default_factory=list)
    fx_spot: dict[str, list[ObservationPoint]] = Field(default_factory=dict)
    commodity_spot: dict[str, list[ObservationPoint]] = Field(default_factory=dict)
    equity_index: dict[str, list[ObservationPoint]] = Field(default_factory=dict)
    credit_spread_hy: list[ObservationPoint] = Field(default_factory=list)
    credit_spread_ig: list[ObservationPoint] = Field(default_factory=list)
```

### 5.4 Error Handling, Retries, Validation

- `OpenBBClient.fetch_series` retries with linear backoff (`attempt *
  backoff_seconds`), then attempts the *other* fetch path once before raising
  `OpenBBFetchError` — a single, caller-friendly exception type.
- `data_layer/validation.py` runs on every returned `ObservationPoint` list:
  - No negative CPI/PCE index level (both YoY *can* go negative in deflation,
    but the raw index level cannot).
  - Unemployment rate must be in `[0, 100]`.
  - Yield curve tenors must be internally consistent — flag (not silently
    fix) an inverted-looking value that's actually a data error (e.g., a
    30yr yield of 0.5% while 10yr is 4.5%, which is a data fault, not a real
    inversion — Module 8 taught real inversions happen at the short end).
  - Date ranges: no `observation_date` in the future relative to
    `retrieved_at`.
  - Anomalies are logged and attached to `MacroDataSnapshot` via an
    `data_quality_flags: list[str]` field (added to the schema above) —
    never silently dropped, matching the "flag, don't fix" principle used
    throughout the companion data-pipeline project.

### 5.5 Persistence

Phase 1: every `MacroDataSnapshot` fetch is also written to
`data/raw/{country}/{timestamp}.parquet` via `data_layer/persistence.py`
(simple `df.to_parquet()`), giving a basic point-in-time audit trail with
zero new infrastructure. `extensions/duckdb_store.py` (Section 12) is the
Phase 5+ upgrade path — same file format (Parquet), just queried through
DuckDB instead of re-read as flat files.

---

## 6. Models Layer Specification (Modules 4–11, 17)

### 22.8 Resolves Finding #8 — Confidence Is Computed, Never Hardcoded

**Every hardcoded** **`confidence=0.X`** **literal throughout this document is
retroactively replaced by a call to this function. No model may hardcode
confidence going forward:**

```python
class ConfidenceInputs(BaseModel):
    data_quality_flags_present: bool
    is_heuristic_not_calibrated: bool       # e.g. illustrative thresholds from Section 15.19/20
    source_independence_count: int          # from count_independent_families()
    depends_on_unobservable: bool           # r*, u*, potential GDP, TFP

def compute_confidence(inputs: ConfidenceInputs) -> float:
    """
    THE single confidence-computation rule (Finding #8). Base 0.7,
    penalized by each risk factor. Replaces every hardcoded confidence
    literal in this document. This is itself an illustrative starting
    formula (documented as such) — Phase 5+ calibrates it against realized
    forecast accuracy, but the STRUCTURE (confidence must be COMPUTED from
    stated factors, never asserted) is mandatory from Phase 2 onward.
    """
    conf = 0.7
    if inputs.data_quality_flags_present:
        conf -= 0.25
    if inputs.is_heuristic_not_calibrated:
        conf -= 0.20
    if inputs.depends_on_unobservable:
        conf -= 0.20
    conf += min(inputs.source_independence_count * 0.05, 0.15)
    return round(max(0.05, min(0.95, conf)), 3)

```

**Retroactive requirement:** every function in Sections 6, 15, 17, and 20
that currently hardcodes `confidence=` must be updated to call
`compute_confidence()` with its actual factor states before Phase 2/3/4
(whichever phase it belongs to) is considered complete.

---

### 22.9 Resolves Finding #9 — `ModelResult.value` Type Contract, Corrected

```python
class ModelResult(BaseModel):
    model_name: str
    country: str
    as_of: datetime
    value: float | int | str | bool | dict | list       # CORRECTED — matches actual heterogeneous returns
    confidence: float = Field(ge=0.0, le=1.0)             # now enforced via compute_confidence(), Finding #8
    interpretation: str
    context: str
    inputs_used: list[str]
    warnings: list[str] = Field(default_factory=list)

    class Config:
        # Every subclass (PolicyRuleResult, RegressionResult, etc.) must
        # document its OWN narrower value type in its own docstring —
        # this broad union is the outer contract, not license for any
        # individual model to be vague about what it actually returns.
        pass

```

---


Every model in this layer follows the same contract:

```python
class ModelResult(BaseModel):
    model_name: str
    country: str
    as_of: datetime
    value: float | dict          # the primary numeric output
    confidence: float            # 0-1, model's own confidence in its output
    interpretation: str          # plain-language meaning
    context: str                 # comparison point (vs target, vs prior, vs history)
    inputs_used: list[str]       # which snapshot fields fed this model
    warnings: list[str] = []     # e.g. "r* uncertain, using midpoint estimate"
```

This directly implements the CLAUDE.md "reason object" requirement — no
model ever returns a bare number.

### 6.1 Policy Rule Models (Module 4)

### 22.4 Resolves Finding #4 — One Canonical Policy-Gap Definition

**The prior ambiguity (Taylor alone? range? distribution? ensemble?) is
resolved with exactly one rule, replacing every other framing in this
document:**

```python
def canonical_policy_gap(taylor: PolicyRuleResult, balanced: PolicyRuleResult,
                          first_diff: PolicyRuleResult, market_implied: float) -> "MarketPricingGap":
    """
    THE canonical gap definition. No other definition is valid anywhere in
    this system.
      model_implied_value = median of {taylor, balanced, first_diff}
      raw_gap = model_implied_value - market_implied
      dispersion = max - min of the three rules
      is_meaningful = abs(raw_gap) > dispersion   <-- THE significance test (Section 16.2 Q6)
    Median, not mean or Taylor-alone, because it is robust to one rule
    being an outlier without needing to justify discarding it. Dispersion
    IS the noise floor — this was always the intent (Section 16.2), now
    made the single explicit rule rather than one interpretation among several.
    """
    values = sorted([taylor.value, balanced.value, first_diff.value])
    model_implied = values[1]  # median of 3
    gap = model_implied - market_implied
    dispersion = values[2] - values[0]
    return MarketPricingGap(
        model_implied_value=model_implied, market_implied_value=market_implied,
        raw_gap=gap, unit="%",
        interpretation=(f"Model (median of 3 rules) {model_implied:.2f}% vs market {market_implied:.2f}% "
                        f"= {gap:+.2f}% gap; rule dispersion {dispersion:.2f}pp "
                        f"({'MEANINGFUL' if abs(gap) > dispersion else 'WITHIN NOISE FLOOR'})"),
    )

```

---

### 22.5 Resolves Finding #5 — Market-Implied Policy Path, Corrected and Bounded

**The 2yr-yield-as-proxy was internally inconsistent with this document's
own term-premium decomposition (Section 8/20.8). Corrected:**

```python
def derive_market_implied_policy_path(short_yield: float, short_tenor_term_premium: float | None) -> ModelResult:
    """
    CORRECTED per Finding #5. Phase 1-4: subtract the tenor-matched ACM
    term premium (if available) from the raw yield to approximate the
    expectations component (per decompose_yield(), Section 20.8) — this is
    still a PROXY, but no longer one that ignores this document's own
    stated decomposition. If no term-premium series exists at the given
    tenor, the function returns the raw yield UNCHANGED but with a hard,
    unconditional warning — it never silently presents a contaminated
    number as a clean policy-path estimate.
    Phase 5+ REPLACES this entirely with a real Fed-funds-futures-implied
    probability distribution (Section 4/16's original intent) — this
    function's signature is stable so that replacement is a body swap, not
    a caller-facing breaking change.
    """
    if short_tenor_term_premium is not None:
        expectations_component = short_yield - short_tenor_term_premium
        conf, warn = 0.4, ["Still a PROXY (term-premium-adjusted yield), not a real Fed-funds-futures-implied distribution — Phase 5+ item"]
    else:
        expectations_component = short_yield
        conf, warn = 0.2, ["NO TERM PREMIUM ADJUSTMENT APPLIED — this raw yield is CONTAMINATED by term premium and is a materially weaker proxy than usual"]
    return ModelResult(
        model_name="derive_market_implied_policy_path", country="us", as_of=datetime.utcnow(),
        value=round(expectations_component, 3), confidence=conf,
        interpretation=f"Market-implied policy path proxy: {expectations_component:.3f}%",
        context="NEVER treat this as equivalent to a Fed-funds-futures-implied probability distribution",
        inputs_used=["short_yield", "short_tenor_term_premium"], warnings=warn,
    )

```

---


```python
# src/macro_engine/models/policy_rules.py

class TaylorRuleInputs(BaseModel):
    r_star: float           # neutral real rate, %
    pi_current: float       # current inflation, %
    pi_target: float = 2.0
    output_gap: float       # %, (actual-potential)/potential * 100

class PolicyRuleResult(ModelResult):
    rule_variant: str        # "taylor_1993" | "balanced_approach" | "first_difference"

def taylor_rule(inputs: TaylorRuleInputs) -> PolicyRuleResult:
    """i = r* + π + 0.5(π − π_target) + 0.5(output_gap)"""
    i = (inputs.r_star + inputs.pi_current
         + 0.5 * (inputs.pi_current - inputs.pi_target)
         + 0.5 * inputs.output_gap)
    return PolicyRuleResult(
        model_name="taylor_rule", rule_variant="taylor_1993",
        country="us", as_of=datetime.utcnow(), value=round(i, 2),
        confidence=0.6,  # r* uncertainty caps confidence — never overstate
        interpretation=f"Taylor Rule prescribes a policy rate of {i:.2f}%",
        context=f"vs r*={inputs.r_star}%, inflation gap={inputs.pi_current-inputs.pi_target:+.1f}pp, output gap={inputs.output_gap:+.1f}%",
        inputs_used=["r_star", "pi_current", "output_gap"],
        warnings=["r* is a model-dependent estimate, not observed — see regime.py r_star_estimator"],
    )

def balanced_approach_rule(inputs: TaylorRuleInputs) -> PolicyRuleResult:
    """Same as Taylor but output-gap coefficient = 1.0, not 0.5."""
    i = (inputs.r_star + inputs.pi_current
         + 0.5 * (inputs.pi_current - inputs.pi_target)
         + 1.0 * inputs.output_gap)
    return PolicyRuleResult(
        model_name="balanced_approach_rule", rule_variant="balanced_approach",
        country="us", as_of=datetime.utcnow(), value=round(i, 2),
        confidence=0.6,
        interpretation=f"Balanced-Approach Rule prescribes {i:.2f}%",
        context="Weights output gap 2x more heavily than classic Taylor Rule",
        inputs_used=["r_star", "pi_current", "output_gap"],
    )

class FirstDifferenceInputs(BaseModel):
    i_prev: float
    pi_current: float
    pi_target: float = 2.0
    output_gap_change: float   # Δ(output gap) since last period
    alpha: float = 0.5
    beta: float = 0.5

def first_difference_rule(inputs: FirstDifferenceInputs) -> PolicyRuleResult:
    """i_t - i_{t-1} = α(π - π_target) + β·Δ(output_gap) — avoids r* dependency."""
    delta_i = (inputs.alpha * (inputs.pi_current - inputs.pi_target)
               + inputs.beta * inputs.output_gap_change)
    i = inputs.i_prev + delta_i
    return PolicyRuleResult(
        model_name="first_difference_rule", rule_variant="first_difference",
        country="us", as_of=datetime.utcnow(), value=round(i, 2),
        confidence=0.7,  # HIGHER confidence — no r* dependency
        interpretation=f"Speed-Limit Rule prescribes {i:.2f}% ({delta_i:+.2f}pp from current)",
        context="Deliberately avoids unobservable r* — cross-check against Taylor/Balanced",
        inputs_used=["i_prev", "pi_current", "output_gap_change"],
    )

def policy_rule_ensemble(taylor: PolicyRuleResult, balanced: PolicyRuleResult,
                          first_diff: PolicyRuleResult) -> dict:
    """Never average — divergence between rules IS the signal (CLAUDE.md rule)."""
    values = [taylor.value, balanced.value, first_diff.value]
    return {
        "rules": {"taylor": taylor.value, "balanced": balanced.value, "first_difference": first_diff.value},
        "range": (min(values), max(values)),
        "dispersion": max(values) - min(values),
        "interpretation": (
            "Low dispersion (<50bp) = policy rules agree, genuine convergence signal. "
            "High dispersion (>100bp) = policy uncertainty, r*/output-gap estimates driving disagreement — do NOT average."
        ),
    }
```

### 6.2 Regime Detection (Modules 3, 4)

**Starter (Phase 1) — rule-based classifier:**

```python
# src/macro_engine/models/regime.py

class RegimeInputs(BaseModel):
    output_gap: float
    inflation_yoy: float
    inflation_trend_3m: float   # 3-month annualized change
    unemployment_gap: float     # u - u*

REGIME_STATES = [
    "early_expansion", "mid_expansion", "late_expansion",
    "slowdown", "recession", "recovery", "disinflation",
    "reflation", "stagflation",
]

def classify_regime_rule_based(inputs: RegimeInputs) -> ModelResult:
    if inputs.output_gap < -1.5 and inputs.inflation_trend_3m < 0:
        state = "recession"
    elif inputs.output_gap < -0.5 and inputs.inflation_trend_3m > 0:
        state = "stagflation"  # weak growth + rising inflation, Module 3.3 scenario
    elif inputs.output_gap > 1.0 and inputs.inflation_trend_3m > 0:
        state = "late_expansion"
    elif -0.5 <= inputs.output_gap <= 0.5 and inputs.inflation_trend_3m < 0:
        state = "disinflation"
    elif inputs.output_gap > 0 and inputs.inflation_trend_3m <= 0:
        state = "mid_expansion"
    else:
        state = "early_expansion"
    return ModelResult(
        model_name="regime_rule_based", country="us", as_of=datetime.utcnow(),
        value=state, confidence=0.5,  # deliberately modest — rule-based is a starter
        interpretation=f"Rule-based classifier: {state}",
        context=f"output_gap={inputs.output_gap:+.2f}%, 3m infl trend={inputs.inflation_trend_3m:+.2f}%",
        inputs_used=["output_gap", "inflation_yoy", "inflation_trend_3m", "unemployment_gap"],
        warnings=["Rule-based only — see Phase 5+ Markov-switching model for probabilistic regime"],
    )
```

**Phase 5+ hook (Markov-switching, specification only — not implemented in
Phase 1):**

```python
def classify_regime_markov_switching(series: pd.Series, k_regimes: int = 3) -> ModelResult:
    """
    Uses statsmodels.tsa.regime_switching.markov_regression.MarkovRegression
    fit on, e.g., real GDP growth or a composite growth/inflation index.
    Returns smoothed regime probabilities per period, not a hard label —
    genuinely probabilistic, unlike the Phase 1 rule-based classifier.
    Implementation deferred to Phase 5; signature fixed now so the thesis
    layer's contract doesn't change when this replaces the rule-based version.
    """
    raise NotImplementedError("Phase 5+ — see docs/DECISIONS.md for rollout plan")
```

### 6.3 Inflation Nowcast (Module 5)

```python
# src/macro_engine/models/inflation_nowcast.py

class InflationSubMeasures(BaseModel):
    cpi_headline_mom: float
    cpi_core_mom: float
    pce_core_mom: float
    # Phase 1: use what's cheaply derivable from OpenBB/FRED without
    # needing raw BLS microdata for supercore/trimmed-mean/median —
    # those require the BLS/Dallas Fed/Cleveland Fed direct sources
    # documented in the companion data-pipeline project, NOT OpenBB.
    # Phase 1 therefore computes a SIMPLE breadth proxy; full multi-measure
    # convergence (Module 5.3/13.2) is a Phase 5+ upgrade once those direct
    # sources are wired in as a supplementary OpenBB-independent feed.

def inflation_breadth_score(measures: InflationSubMeasures) -> ModelResult:
    values = [measures.cpi_headline_mom, measures.cpi_core_mom, measures.pce_core_mom]
    same_direction = all(v > 0 for v in values) or all(v < 0 for v in values)
    avg = sum(values) / len(values)
    return ModelResult(
        model_name="inflation_breadth_simple", country="us", as_of=datetime.utcnow(),
        value=avg, confidence=0.5 if same_direction else 0.3,
        interpretation=(
            f"{'Convergent' if same_direction else 'Divergent'} inflation signal across "
            f"headline/core CPI/core PCE, average {avg:+.2f}% m/m"
        ),
        context="Phase 1 simple 3-measure breadth; full 6+ measure convergence deferred to Phase 5",
        inputs_used=["cpi_headline_mom", "cpi_core_mom", "pce_core_mom"],
        warnings=[] if same_direction else ["Sub-measures disagree — per Module 13, investigate before treating as trend"],
    )
```

### 6.4 Labor Synthesis (Module 6)

```python
# src/macro_engine/models/labor_synthesis.py

class LaborInputs(BaseModel):
    initial_claims_4wk_avg_change_pct: float  # % change vs prior 4wk avg
    jolts_openings_yoy_pct: float
    jolts_quits_level_percentile: float       # 0-100, vs trailing 3yr
    nfp_3m_avg: float                          # thousands, 3-month avg pace

def labor_tightness_score(inputs: LaborInputs) -> ModelResult:
    """
    Composite, -100 (very loose) to +100 (very tight). Weighted toward
    LEADING series (claims, JOLTS) per Module 6.4's lead/lag hierarchy —
    NFP gets lower weight precisely because it's coincident/noisy/revised.
    """
    claims_component = -inputs.initial_claims_4wk_avg_change_pct * 2.0  # rising claims = looser
    jolts_component = inputs.jolts_openings_yoy_pct * 0.5 + (inputs.jolts_quits_level_percentile - 50) * 0.5
    nfp_component = (inputs.nfp_3m_avg - 150) / 10  # 150k treated as rough neutral pace, configurable

    score = 0.4 * claims_component + 0.4 * jolts_component + 0.2 * nfp_component
    score = max(-100, min(100, score))
    return ModelResult(
        model_name="labor_tightness_score", country="us", as_of=datetime.utcnow(),
        value=round(score, 1), confidence=0.6,
        interpretation=f"Labor market tightness score: {score:+.1f} (weighted toward leading claims/JOLTS)",
        context="Positive = tightening, Negative = loosening. Weights: claims 40%, JOLTS 40%, NFP 20%",
        inputs_used=["initial_claims_4wk_avg_change_pct", "jolts_openings_yoy_pct",
                     "jolts_quits_level_percentile", "nfp_3m_avg"],
        warnings=["NFP weighted low deliberately — coincident, heavily revised (Module 6.1)"],
    )
```

### 6.5 GDP Nowcast (Module 7)

```python
# src/macro_engine/models/gdp_nowcast.py

class OutputGapInputs(BaseModel):
    actual_gdp: float
    potential_gdp: float

def output_gap(inputs: OutputGapInputs) -> ModelResult:
    gap_pct = (inputs.actual_gdp - inputs.potential_gdp) / inputs.potential_gdp * 100
    return ModelResult(
        model_name="output_gap", country="us", as_of=datetime.utcnow(),
        value=round(gap_pct, 2), confidence=0.5,  # potential GDP itself is an estimate
        interpretation=f"Output gap: {gap_pct:+.2f}% ({'above' if gap_pct>0 else 'below'} potential)",
        context=f"Actual={inputs.actual_gdp}, Potential={inputs.potential_gdp}",
        inputs_used=["actual_gdp", "potential_gdp"],
        warnings=["Potential GDP is a Cobb-Douglas production-function ESTIMATE, not observed — Module 7.2"],
    )

class SimpleGDPNowcastInputs(BaseModel):
    retail_sales_mom: float
    durable_goods_mom: float
    trade_balance_change: float
    prior_quarter_annualized: float

def simple_gdp_nowcast(inputs: SimpleGDPNowcastInputs) -> ModelResult:
    """
    Phase 1 starter — crude expenditure-approach proxy, NOT a replacement
    for the Atlanta Fed's actual GDPNow (no free API; use the companion
    data pipeline's manual-entry mechanism to cross-check this against the
    real published GDPNow number). This exists so the thesis layer has
    something to consume before the full nowcast infrastructure exists.
    """
    c_proxy = inputs.retail_sales_mom * 0.6
    i_proxy = inputs.durable_goods_mom * 0.3
    nx_proxy = inputs.trade_balance_change * 0.1
    delta = c_proxy + i_proxy + nx_proxy
    nowcast = inputs.prior_quarter_annualized + delta
    return ModelResult(
        model_name="simple_gdp_nowcast", country="us", as_of=datetime.utcnow(),
        value=round(nowcast, 2), confidence=0.35,  # deliberately LOW — this is a crude proxy
        interpretation=f"Crude nowcast: {nowcast:.2f}% annualized",
        context="NOT the Atlanta Fed GDPNow — cross-check against manually-entered published figure",
        inputs_used=["retail_sales_mom", "durable_goods_mom", "trade_balance_change"],
        warnings=["Simple proxy model — see docs/DECISIONS.md re: full GDPNow-equivalent, Phase 5+"],
    )
```

### 6.6 Yield Curve Analytics (Module 8)

```python
# src/macro_engine/models/yield_curve.py

def curve_slope(tenors: dict[str, float], short: str = "2yr", long: str = "10yr") -> ModelResult:
    slope_bp = (tenors[long] - tenors[short]) * 100
    return ModelResult(
        model_name="curve_slope", country="us", as_of=datetime.utcnow(),
        value=round(slope_bp, 1), confidence=0.9,  # this is just arithmetic on observed data
        interpretation=f"{long.upper()}-{short.upper()} spread: {slope_bp:+.1f}bp "
                        f"({'inverted' if slope_bp < 0 else 'normal'})",
        context="Inversion = market pricing future cuts, historically 6-24mo recession lead (Module 8.1)",
        inputs_used=["yield_curve"],
        warnings=["Timing lag is 6-24 months and variable — do not treat as a precise calendar signal"],
    )

def breakeven_inflation(nominal: float, tips_real: float, tenor: str) -> ModelResult:
    breakeven = nominal - tips_real
    return ModelResult(
        model_name="breakeven_inflation", country="us", as_of=datetime.utcnow(),
        value=round(breakeven, 2), confidence=0.85,
        interpretation=f"{tenor} breakeven inflation: {breakeven:.2f}%",
        context=f"Nominal={nominal:.2f}%, TIPS real={tips_real:.2f}%",
        inputs_used=["yield_curve", "tips_yields"],
        warnings=["Breakeven includes an inflation risk premium — not pure expectations (Module 8.2)"],
    )

def yield_curve_pca(daily_changes: pd.DataFrame) -> ModelResult:
    """
    Phase 5+ — scikit-learn PCA on DAILY CHANGES (never raw levels, per
    Module 18.3) across the tenor panel. Returns explained variance and
    loadings for PC1 (level), PC2 (slope), PC3 (curvature) — confirmed via
    loadings, never auto-labeled.
    """
    raise NotImplementedError("Phase 5+ — requires scikit-learn, see Section 4")
```

### 6.7 FX Carry / Parity Models (Module 9)

```python
# src/macro_engine/models/fx_carry.py

class CIPInputs(BaseModel):
    spot: float
    forward: float
    i_domestic: float
    i_foreign: float

def cip_check(inputs: CIPInputs) -> ModelResult:
    """F/S = (1+i_d)/(1+i_f) — deviation is a funding-stress signal (Module 9.1)."""
    implied_forward = inputs.spot * (1 + inputs.i_domestic) / (1 + inputs.i_foreign)
    deviation_pct = (inputs.forward - implied_forward) / implied_forward * 100
    return ModelResult(
        model_name="cip_deviation", country="us", as_of=datetime.utcnow(),
        value=round(deviation_pct, 3), confidence=0.7,
        interpretation=f"CIP deviation: {deviation_pct:+.3f}% "
                        f"({'notable — possible funding stress' if abs(deviation_pct) > 0.1 else 'near-zero, as expected'})",
        context="CIP should hold near-exactly via arbitrage; deviation = stress signal, not opportunity (Module 9.1)",
        inputs_used=["spot", "forward", "i_domestic", "i_foreign"],
    )

class CarryScoreInputs(BaseModel):
    rate_differential: float   # i_domestic - i_foreign
    realized_vol_annualized: float

def carry_score(inputs: CarryScoreInputs) -> ModelResult:
    """Simple carry-to-vol ratio — a crude Sharpe-style carry attractiveness score."""
    score = inputs.rate_differential / max(inputs.realized_vol_annualized, 0.1)
    return ModelResult(
        model_name="carry_score", country="us", as_of=datetime.utcnow(),
        value=round(score, 3), confidence=0.5,
        interpretation=f"Carry-to-vol score: {score:.3f}",
        context="UIP predicts this carry should be arbitraged away — historically it isn't (forward premium puzzle, Module 9.1). Tail/crash risk NOT captured by this ratio.",
        inputs_used=["rate_differential", "realized_vol_annualized"],
        warnings=["Does not capture 'nickels in front of a steamroller' crash risk — pair with regime/risk-sentiment signal before sizing"],
    )

def dollar_smile_regime(vix_level: float, us_growth_surprise: float, us_vs_row_rate_diff: float) -> ModelResult:
    if vix_level > 25:
        side = "left (risk-off/crisis) — USD strength likely safe-haven driven, reversal-prone"
    elif us_growth_surprise > 0 and us_vs_row_rate_diff > 0:
        side = "right (US outperformance) — USD strength likely durable, rate/growth-driven"
    else:
        side = "middle (synchronized global growth) — USD likely weak, diversification flows dominate"
    return ModelResult(
        model_name="dollar_smile_regime", country="us", as_of=datetime.utcnow(),
        value=side, confidence=0.4,  # regime classification is inherently fuzzy
        interpretation=f"Dollar Smile regime: {side}",
        context=f"VIX={vix_level}, US growth surprise={us_growth_surprise:+.2f}, rate diff={us_vs_row_rate_diff:+.2f}",
        inputs_used=["vix_level", "us_growth_surprise", "us_vs_row_rate_diff"],
        warnings=["Regime classification is qualitative/threshold-based in Phase 1 — refine thresholds against history before trusting at size"],
    )
```

### 6.8 Commodities / Oil Framework (Module 10)

```python
# src/macro_engine/models/commodities.py

class OilBalanceInputs(BaseModel):
    inventory_change_weekly: float   # barrels, +/- vs 5yr seasonal avg
    opec_spare_capacity_proxy: float # informational only, not a trade signal per system scope

def oil_balance_signal(inputs: OilBalanceInputs) -> ModelResult:
    """
    INFORMATIONAL ONLY — this system does not trade commodities directly
    (matches the companion data pipeline's scope decision). This model
    exists purely to feed the inflation/growth transmission channel
    (Module 10 → Module 5/7), e.g. as an input to inflation_nowcast's
    energy-component context, NOT as a standalone trade signal.
    """
    tightness = -inputs.inventory_change_weekly  # draw = tightening
    return ModelResult(
        model_name="oil_balance_signal", country="us", as_of=datetime.utcnow(),
        value=round(tightness, 2), confidence=0.4,
        interpretation=f"Oil market {'tightening' if tightness > 0 else 'loosening'} (informational)",
        context="Feeds inflation/growth transmission only — this system does not express commodity views directly",
        inputs_used=["inventory_change_weekly"],
        warnings=["Do NOT use this as a standalone trade signal — commodities out of production scope"],
    )
```

### 6.9 Equity Macro Models (Module 11)

```python
# src/macro_engine/models/equity_macro.py

def sector_rotation_prior(regime_state: str) -> ModelResult:
    ROTATION_MAP = {
        "early_expansion": ["financials", "consumer_discretionary", "industrials"],
        "mid_expansion": ["technology"],
        "late_expansion": ["energy", "materials"],
        "recession": ["utilities", "staples", "healthcare"],
        "stagflation": ["staples", "energy"],  # defensive + inflation-linked
        "disinflation": ["technology", "financials"],
    }
    sectors = ROTATION_MAP.get(regime_state, ["diversified — no strong prior"])
    return ModelResult(
        model_name="sector_rotation_prior", country="us", as_of=datetime.utcnow(),
        value=sectors, confidence=0.4,  # base-rate PRIOR, not a rule — Module 11.1
        interpretation=f"Base-rate sector prior for '{regime_state}': {', '.join(sectors)}",
        context="This is a historical BASE-RATE PRIOR, not a mechanical rule — every cycle has idiosyncratic features (Module 11.1)",
        inputs_used=["regime_state"],
        warnings=["Adjust for cycle-specific features (starting valuations, policy mix) before acting"],
    )

def duration_sensitivity(is_growth: bool, rate_change_bp: float) -> ModelResult:
    """Crude equity-duration proxy: growth ~ long duration, value ~ short duration (Module 11.1)."""
    proxy_duration = 15 if is_growth else 5  # illustrative, calibrate against real data later
    est_pct_move = -proxy_duration * (rate_change_bp / 10000)
    return ModelResult(
        model_name="duration_sensitivity", country="us", as_of=datetime.utcnow(),
        value=round(est_pct_move * 100, 2), confidence=0.3,
        interpretation=f"Est. price impact from {rate_change_bp:+.0f}bp rate move: {est_pct_move*100:+.2f}%",
        context=f"Using illustrative duration proxy ({'growth' if is_growth else 'value'} = {proxy_duration}yr)",
        inputs_used=["is_growth", "rate_change_bp"],
        warnings=["Proxy duration is illustrative, not calibrated — refine with real sector-level regression, Phase 5+"],
    )
```

### 6.10 Volatility Models (Module 17)

```python
# src/macro_engine/models/volatility.py

def realized_vol_simple(returns: pd.Series, window: int = 21) -> ModelResult:
    """Phase 1 starter — rolling realized vol. GARCH via `arch` is Phase 5+."""
    vol_annualized = returns.rolling(window).std().iloc[-1] * (252 ** 0.5)
    return ModelResult(
        model_name="realized_vol_simple", country="us", as_of=datetime.utcnow(),
        value=round(vol_annualized * 100, 2), confidence=0.5,
        interpretation=f"Realized annualized vol ({window}d window): {vol_annualized*100:.2f}%",
        context="Simple rolling std dev — NOT a forecast, purely backward-looking",
        inputs_used=["returns"],
        warnings=["No forward-looking conditional forecast — see arch/GARCH hook, Section 12, for Phase 5+"],
    )
```

---

## 7. Thesis Layer Specification (Module 14)

### 7.1 MacroThesis Schema

```python
# src/macro_engine/thesis_layer/schemas.py

from enum import Enum
from datetime import datetime
from pydantic import BaseModel, Field

class ThesisStatus(str, Enum):
    DRAFT = "DRAFT"
    WATCH = "WATCH"
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    INVALIDATED = "INVALIDATED"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"

class MarketPricingGap(BaseModel):
    model_implied_value: float
    market_implied_value: float
    raw_gap: float
    unit: str                      # e.g. "%", "bp"
    interpretation: str

class ConfirmationSignal(BaseModel):
    source_model: str
    direction: str                 # "confirms" | "contradicts" | "neutral"
    detail: str

class ScenarioOutcome(BaseModel):
    scenario_name: str
    probability: float
    payoff_estimate: float
    unit: str = "bp_pnl_proxy"     # Phase 1: proxy units, not real $ P&L (needs position size)

class TradeIdea(BaseModel):
    instrument: str                # e.g. "UST 2yr note futures"
    direction: str                 # "long" | "short"
    timeframe: str                 # e.g. "6-12 months"
    sizing_logic: str              # plain-language, Phase 1: no auto Kelly sizing
    stop_or_invalidation: str
    catalysts: list[str]

class MacroThesis(BaseModel):
    thesis_id: str
    country: str
    created_at: datetime
    regime: dict                    # {"state": str, "confidence": float}
    growth_view: dict
    inflation_view: dict
    policy_view: dict
    market_pricing_gap: MarketPricingGap
    confirmation_signals: list[ConfirmationSignal]
    convergence_classification: str  # HIGH | MEDIUM | LOW | CONFLICTED
    prior_probability: float | None = None
    posterior_probability: float | None = None  # None until Bayesian layer, Phase 5+
    trade_idea: TradeIdea
    scenario_distribution: list[ScenarioOutcome]
    status: ThesisStatus = ThesisStatus.DRAFT
    warnings: list[str] = Field(default_factory=list)
```

### 7.2 `build_us_macro_thesis()` — Algorithmic Description

```python
# src/macro_engine/thesis_layer/builder.py

def build_us_macro_thesis(snapshot: MacroDataSnapshot) -> MacroThesis:
    """
    1. Run every Phase-1 model against the snapshot.
    2. Classify regime (rule-based, Phase 1).
    3. Compute policy rule ensemble + dispersion (never average).
    4. Compute market-implied policy path proxy (Phase 1: derive crudely
       from the front of the yield curve — a full Fed-funds-futures-based
       implied path is Phase 5+, requires a futures data source OpenBB
       may or may not expose cleanly; document as a known limitation if not).
    5. Compute gap = model_implied (policy rule ensemble midpoint) − market_implied.
    6. Classify convergence: check whether growth (output gap sign),
       inflation (breadth score sign), and policy gap direction all agree.
       - All three agree → HIGH
       - Two of three agree → MEDIUM
       - Growth/inflation disagree but no outright contradiction → LOW
       - Direct contradiction (e.g., growth says ease, inflation says hike) → CONFLICTED
    7. Map convergence + gap magnitude to a trade idea using the
       instrument-selection rules from Module 14/15 (e.g., a policy-path
       gap → 2yr/5yr rates instrument, a curve-shape-specific gap → duration-
       weighted steepener/flattener — Phase 1 implements the single most
       common case: outright short-end rates for a policy-path gap).
    8. Assemble scenario_distribution as a small, explicit 3-4 scenario set
       (base case, upside, downside, tail) with PLACEHOLDER probabilities
       in Phase 1 — Bayesian-derived probabilities are Phase 5+.
    9. Populate warnings from every underlying ModelResult.warnings list —
       never drop them; thesis-level warnings are the union of all
       model-level warnings plus any convergence-specific caveats.
    10. status = DRAFT always in Phase 1 — a human reviews and promotes
        status manually; no auto-promotion to ACTIVE until Phase 5+ risk
        gating exists.
    """
    ...  # full implementation follows this outline; omitted here for length,
         # but every step above must be a literal, separately-testable
         # function so unit tests can target each step independently.
```

### 7.3 Example Thesis Objects (JSON)

**Example — early-cycle disinflation, HIGH convergence:**

```json
{
  "thesis_id": "us-2026-03-a1",
  "country": "us",
  "created_at": "2026-03-14T13:05:00Z",
  "regime": {"state": "disinflation", "confidence": 0.5},
  "growth_view": {"output_gap": -0.8, "trend": "widening negative"},
  "inflation_view": {"breadth_score": -0.15, "direction": "convergent disinflation"},
  "policy_view": {
    "taylor": 3.2, "balanced": 2.6, "first_difference": 3.0,
    "dispersion": 0.6, "interpretation": "Low dispersion — rules agree"
  },
  "market_pricing_gap": {
    "model_implied_value": 2.9,
    "market_implied_value": 4.3,
    "raw_gap": -1.4,
    "unit": "%",
    "interpretation": "Model prescribes ~140bp below current market-implied path"
  },
  "confirmation_signals": [
    {"source_model": "labor_tightness_score", "direction": "confirms", "detail": "Score -42, loosening labor market"},
    {"source_model": "inflation_breadth_simple", "direction": "confirms", "detail": "All 3 sub-measures decelerating"},
    {"source_model": "curve_slope", "direction": "confirms", "detail": "2s10s inverted -35bp"}
  ],
  "convergence_classification": "HIGH",
  "trade_idea": {
    "instrument": "UST 2yr note futures",
    "direction": "long",
    "timeframe": "6-12 months",
    "sizing_logic": "Phase 1: human-determined, no auto-Kelly sizing yet",
    "stop_or_invalidation": "Exit if labor_tightness_score reverses above 0 OR inflation_breadth turns positive across all 3 measures",
    "catalysts": ["Next CPI release", "Next FOMC meeting + dot plot", "Next NFP release"]
  },
  "scenario_distribution": [
    {"scenario_name": "base_case_cuts_as_modeled", "probability": 0.5, "payoff_estimate": 120, "unit": "bp_pnl_proxy"},
    {"scenario_name": "cuts_delayed", "probability": 0.3, "payoff_estimate": -30, "unit": "bp_pnl_proxy"},
    {"scenario_name": "inflation_resurgence_tail", "probability": 0.1, "payoff_estimate": -180, "unit": "bp_pnl_proxy"},
    {"scenario_name": "recession_deeper_cuts", "probability": 0.1, "payoff_estimate": 250, "unit": "bp_pnl_proxy"}
  ],
  "status": "DRAFT",
  "warnings": [
    "r* is a model-dependent estimate, not observed",
    "Potential GDP is a Cobb-Douglas production-function ESTIMATE",
    "Market-implied path derived crudely from front-end yield curve in Phase 1 — not a true Fed-funds-futures-implied distribution"
  ]
}
```

**Example — CONFLICTED regime (illustrates the "divergence is information" rule):**

```json
{
  "thesis_id": "us-2026-04-b7",
  "regime": {"state": "stagflation", "confidence": 0.4},
  "growth_view": {"output_gap": -1.2, "trend": "weakening"},
  "inflation_view": {"breadth_score": 0.35, "direction": "reaccelerating"},
  "convergence_classification": "CONFLICTED",
  "trade_idea": {
    "instrument": "NONE — no clean expression until convergence improves",
    "direction": "n/a",
    "timeframe": "n/a",
    "sizing_logic": "Do not size a position against a CONFLICTED convergence classification",
    "stop_or_invalidation": "n/a",
    "catalysts": ["Watch for either growth or inflation signal to resolve the conflict"]
  },
  "status": "WATCH",
  "warnings": ["Growth signals easing, inflation signals tightening — genuine dual-mandate tension, not a data error. Module 12 principle: false confidence in an unclear picture is worse than correctly identified uncertainty."]
}
```

---

## 8. API Layer Specification

### 8.1 FastAPI Service Design

```python
# src/macro_engine/api_layer/app.py

from fastapi import FastAPI
from macro_engine.api_layer import routes_health, routes_thesis, routes_query, routes_dashboard

def create_app() -> FastAPI:
    app = FastAPI(
        title="Macro Reasoning Engine",
        version="1.0.0",
        description="Institutional macro thesis synthesis backend — see MODULE_MAPPING.md",
    )
    app.include_router(routes_health.router)
    app.include_router(routes_thesis.router, prefix="/thesis")
    app.include_router(routes_query.router)
    app.include_router(routes_dashboard.router)
    return app

app = create_app()
```

### 8.2 Endpoints

```python
# src/macro_engine/api_layer/routes_thesis.py

from fastapi import APIRouter, HTTPException
from macro_engine.thesis_layer.schemas import MacroThesis
from macro_engine.thesis_layer.builder import build_us_macro_thesis
from macro_engine.data_layer.openbb_client import OpenBBClient, OpenBBFetchError

router = APIRouter(tags=["thesis"])

@router.get("/{country}", response_model=MacroThesis)
async def get_thesis(country: str):
    if country != "us":
        raise HTTPException(status_code=501, detail=f"Country '{country}' not implemented — Phase 1 supports 'us' only")
    client = OpenBBClient()
    try:
        snapshot = await fetch_full_snapshot(client, country)  # orchestrates Section 5 calls
    except OpenBBFetchError as exc:
        raise HTTPException(status_code=502, detail=f"Data fetch failed: {exc}")
    return build_us_macro_thesis(snapshot)
```

```python
# src/macro_engine/api_layer/routes_health.py
from fastapi import APIRouter
router = APIRouter(tags=["health"])

@router.get("/health")
async def health():
    return {"status": "ok", "service": "macro-reasoning-engine", "version": "1.0.0"}
```

```python
# src/macro_engine/api_layer/routes_dashboard.py
from fastapi import APIRouter
router = APIRouter(tags=["dashboard"])

@router.get("/dashboard_data")
async def dashboard_data(country: str = "us"):
    """Flattened, UI-friendly view of the latest snapshot + model outputs —
    designed for eventual Workspace widget rendering, not the full
    MacroThesis object (which is richer/nested for programmatic consumers)."""
    ...
```

```python
# src/macro_engine/api_layer/routes_query.py
from fastapi import APIRouter
from pydantic import BaseModel
router = APIRouter(tags=["query"])

class QueryRequest(BaseModel):
    question: str
    country: str = "us"

class QueryResponse(BaseModel):
    answer: str
    supporting_thesis_id: str | None
    relevant_model_outputs: list[dict]

@router.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    """
    Phase 1: simple keyword routing to relevant model outputs (e.g.
    "inflation" → inflation_nowcast, "curve"/"recession" → yield_curve +
    regime). NOT an LLM-backed free-text answer in Phase 1 — that's an
    explicit Phase 5+ item once reasoning_step streaming (8.3) exists to
    support it properly rather than returning an unexplainable black box.
    """
    ...
```

### 8.3 Reasoning Step Streaming (OpenBB AI SDK / Copilot Compatible)

```python
# src/macro_engine/api_layer/reasoning_stream.py

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import json

router = APIRouter(tags=["streaming"])

async def reasoning_step_generator(country: str):
    steps = [
        {"step": "fetch_data", "status": "started", "detail": f"Fetching {country} macro snapshot via OpenBB"},
        {"step": "fetch_data", "status": "done", "detail": "Snapshot retrieved, 14 series"},
        {"step": "run_models", "status": "started", "detail": "Running policy rules, regime, inflation, labor, GDP, curve models"},
        {"step": "run_models", "status": "done", "detail": "9 models completed"},
        {"step": "compute_gap", "status": "done", "detail": "Model-implied policy path vs market-implied: gap = -140bp"},
        {"step": "classify_convergence", "status": "done", "detail": "HIGH convergence — growth/inflation/policy signals agree"},
        {"step": "build_thesis", "status": "done", "detail": "Thesis assembled: long UST 2yr, 6-12mo horizon"},
    ]
    for step in steps:
        yield f"data: {json.dumps(step)}\n\n"

@router.get("/thesis/{country}/stream")
async def stream_thesis_reasoning(country: str):
    return StreamingResponse(reasoning_step_generator(country), media_type="text/event-stream")
```

This SSE (`text/event-stream`) format is directly compatible with OpenBB's
AI SDK reasoning-step display pattern — each event is a JSON object with
`step`/`status`/`detail`, so Workspace can render a live "thinking" trace
once it consumes this backend.

### 8.4 Security

Phase 1: local-only (`127.0.0.1` binding), no auth — matches the local
OpenBB API's own security posture. `CORSMiddleware` configured permissively
for local Workspace connection only. If/when this is ever deployed beyond
localhost (explicitly out of Phase 1 scope), document required changes in
`docs/DECISIONS.md` before doing so: API key auth minimum, HTTPS mandatory,
CORS restricted to the specific Workspace origin.

### 8.5 Future Workspace Registration

Document in `docs/ARCHITECTURE.md` once Workspace's open-source frontend is
available: registration will require pointing Workspace at this service's
base URL and declaring the `/thesis/{country}` and `/thesis/{country}/stream`
endpoints per Workspace's custom-backend manifest format (exact format TBD
pending Workspace's public spec — flagged as an open dependency, not
something to guess at now).

---

## 9. Risk & Portfolio Layer (Modules 17–18)

### 9.1 Risk Metrics (Phase 1: basics; Phase 5+: full suite)

```python
# src/macro_engine/models/risk.py

def historical_var(returns: pd.Series, confidence: float = 0.95) -> ModelResult:
    var = -returns.quantile(1 - confidence)
    return ModelResult(
        model_name="historical_var", country="us", as_of=datetime.utcnow(),
        value=round(var * 100, 2), confidence=0.5,
        interpretation=f"{confidence*100:.0f}% historical VaR: {var*100:.2f}%",
        context="Based on empirical return distribution — no distributional assumption, but backward-looking only",
        inputs_used=["returns"],
        warnings=["VaR alone says nothing about tail magnitude beyond threshold — see Expected Shortfall, Phase 5+"],
    )

def expected_shortfall(returns: pd.Series, confidence: float = 0.95) -> ModelResult:
    """Phase 5+: ES = E[Loss | Loss > VaR] — the CVaR complement to VaR (Module 17.2)."""
    threshold = returns.quantile(1 - confidence)
    tail_losses = returns[returns <= threshold]
    es = -tail_losses.mean() if len(tail_losses) > 0 else None
    return ModelResult(
        model_name="expected_shortfall", country="us", as_of=datetime.utcnow(),
        value=round(es * 100, 2) if es else None, confidence=0.5,
        interpretation=f"Expected Shortfall beyond {confidence*100:.0f}% VaR: {es*100:.2f}%" if es else "Insufficient tail observations",
        context="Average loss CONDITIONAL on being in the worst tail — mandatory complement to VaR per Module 17.2",
        inputs_used=["returns"],
    )
```

### 9.2 Portfolio Construction (Riskfolio-Lib Hook)

```python
# src/macro_engine/portfolio/risk_budget.py

class RiskBudgetInputs(BaseModel):
    instrument_returns: pd.DataFrame   # columns = instruments, index = dates
    target_risk_contribution: dict[str, float]  # instrument -> target % of total portfolio vol

def compute_risk_parity_weights(inputs: RiskBudgetInputs):
    """
    Phase 4+ — wraps riskfolio.Portfolio for risk-budgeted (not equal-
    dollar) position sizing, matching Module 17.1's core principle: size by
    risk contribution, not notional. Signature fixed now; full
    implementation (covariance estimation, optimizer call, correlation
    stress-testing per Module 17.1's LTCM caveat) is a Phase 4 deliverable.
    """
    raise NotImplementedError("Phase 4 — see docs/DECISIONS.md")
```

### 9.3 Thesis → Position Translation

A `MacroThesis.trade_idea` is deliberately **not** auto-converted into a
sized position in Phase 1 — `sizing_logic` is a plain-language field a human
reads and acts on. Phase 4+ introduces `portfolio/risk_budget.py`'s
`translate_thesis_to_position()`, which will take a `MacroThesis` +
portfolio-level risk budget config and emit a proposed notional size —
still requiring human sign-off before Phase 5+'s NautilusTrader integration
could ever act on it (and even then, per the standalone data-pipeline
project's precedent, execution remains a deliberate, separate decision, not
an automatic consequence of a thesis existing).

### 9.4 Stress Testing (Module 16-Informed)

Phase 5+ scenario library, built from the course's actual case studies:
`scenarios/black_wednesday.yaml`, `scenarios/gfc_2008.yaml`,
`scenarios/covid_2020.yaml`, `scenarios/ltcm_1998.yaml` — each encoding a
coherent, multi-variable shock (per Module 17.2's "coherent scenarios, not
isolated shocks" principle) that the risk layer replays against current
portfolio composition to estimate stress P&L.

---

## 10. Testing, Quality, and Operations

### 10.1 Testing Strategy

- **Data layer**: mock `httpx` responses (offline), plus a small number of
  `@pytest.mark.live` tests against the real local OpenBB API.
- **Models**: pure unit tests with hand-computed expected values — e.g.
  `test_taylor_rule_matches_hand_calculation()` using the exact worked
  example from Module 4 (`r*=0.5, π=3%, gap=+1% → i=4.5%`) as a golden test.
- **Thesis layer**: test each of the 10 build steps (Section 7.2)
  independently with synthetic `MacroDataSnapshot` fixtures — including a
  fixture engineered to produce CONFLICTED convergence, to prove that path
  is actually reachable and correctly handled (not just the happy path).
- **API layer**: FastAPI `TestClient` for all routes; one test asserting
  `/thesis/de` (unimplemented country) returns 501, not a silent failure.

### 10.2 Linting/Type-Checking

`ruff` (default ruleset + `I` import sorting) and `mypy --strict` on
`src/macro_engine/` (not `tests/` or `extensions/` stubs, which can be
looser). Both run in pre-commit and CI.

### 10.3 Logging

Structured JSON logging (`logging` + a JSON formatter) — every model call
logs `model_name`, `country`, `duration_ms`, `confidence`; every data fetch
logs success/failure/retry count; every thesis build logs the final
`convergence_classification` and `thesis_id`. Log level `WARNING` for any
`ModelResult.warnings` being non-empty, so operational monitoring can grep
for exactly this.

### 10.4 Configuration

```yaml
# config/settings.yaml
countries: ["us"]  # Phase 1; extend later
policy_rules:
  r_star_estimate: 0.5  # placeholder until Kalman-filtered r*, Phase 5+
  pi_target: 2.0
regime:
  method: "rule_based"  # "rule_based" | "markov_switching" (Phase 5+)
risk:
  var_confidence: 0.95
openbb:
  local_api_base_url: "http://127.0.0.1:6900"
  use_local_api_first: true
```

Loaded via `config.py` into a `Settings(BaseSettings)` Pydantic model — any
malformed field fails fast at startup, not deep in a model call.

### 10.5 Secrets

`.env.example`:
```
# OpenBB provider credentials, if the local Platform API requires any
# for specific providers (e.g., a FRED API key configured within OpenBB
# itself, not duplicated here) — document exactly which OpenBB providers
# need keys once Phase 1 data-layer testing reveals it.
OPENBB_LOCAL_API_BASE_URL=http://127.0.0.1:6900
```

### 10.6 Future Automation Hooks

`extensions/scheduler.py` (Phase 5+): APScheduler jobs calling
`build_us_macro_thesis()` on a schedule aligned to the official release
calendar (same discipline as the companion data pipeline — FRED
`release/dates`, not a blind fixed time), persisting each generated thesis
so a history of theses-over-time exists for later Bayesian-updating
(Section 12) and backtesting (Section 12) work.

---

## 11. Step-by-Step Implementation Plan

| Phase | Objectives | Key files | Definition of Done |
|---|---|---|---|
| **0** | Repo skeleton, `pyproject.toml`, `uv`/pip tooling, CI basics (ruff, mypy, pytest in GitHub Actions or equivalent) | full directory tree (Section 3) | `pytest` runs (0 tests, passes), `ruff`/`mypy` run clean on empty stubs |
| **1** | Data layer + `MacroDataSnapshot` + basic thesis schema | `data_layer/*`, `thesis_layer/schemas.py` | Can fetch a real US snapshot from local OpenBB API and validate it against the Pydantic schema; offline + one live test pass |
| **2** | Core models: policy rules, rule-based regime, inflation breadth, labor score, simple GDP nowcast, curve slope/breakeven | `models/policy_rules.py`, `regime.py`, `inflation_nowcast.py`, `labor_synthesis.py`, `gdp_nowcast.py`, `yield_curve.py` | Taylor Rule golden test passes exactly; every model returns a valid `ModelResult` on a real snapshot |
| **3** | Thesis builder + API layer | `thesis_layer/builder.py`, `api_layer/*` | `GET /thesis/us` returns a valid `MacroThesis` JSON on a live snapshot; all 10 builder steps individually tested |
| **4** | Risk basics (VaR) + Riskfolio-Lib risk-budget hook | `models/risk.py`, `portfolio/risk_budget.py` | Historical VaR computed on real instrument return series; risk-budget function signature fixed and stubbed |
| **5+** | Markov-switching regime, Bayesian updater (PyMC/scipy), FX carry/parity full build-out, commodities/equity macro full build-out, GARCH volatility (`arch`), full VaR/ES suite, `vectorbt` backtests, `NautilusTrader` adapter, MLflow, APScheduler, multi-country (`de`, `jp`, `gb`) theses | `extensions/*`, model upgrades in place | Each item gated individually — do not batch; ship and test one extension at a time per its own Definition of Done, documented in `docs/DECISIONS.md` as it lands |

### 11.1 Mandatory Per-Phase Test Checklist (Do Not Skip)

Every phase in the table above is only "done" when these specific,
concrete tests pass — not when the code merely runs without error:

**Phase 0:** `pytest` collects 0 tests and exits 0 (no import errors across
the whole skeleton); `ruff`/`mypy` run clean on every stub file.

**Phase 1:** A live test proves `OpenBBClient.fetch_series()` returns a
correctly-shaped `MacroDataSnapshot` for at least one real FRED-backed
series and one real Treasury-yield series; an offline test proves
`OpenBBFetchError` is raised (not a raw provider exception) when both fetch
paths are mocked to fail; a validation test proves an engineered
"impossible value" (e.g., unemployment_rate = 150) is flagged in
`data_quality_flags`, not silently dropped or silently accepted.

**Phase 2:** `test_taylor_rule_matches_hand_calculation()` — the exact
Module 4 worked example (`r*=0.5, π=3%, target=2%, output_gap=+1% → i=4.5%`)
must reproduce `4.5` to at least 2 decimal places. `test_policy_rule_ensemble_never_averages()`
— asserts the ensemble function returns individual rule values and a
dispersion metric, and explicitly asserts there is NO code path that
returns a single averaged number in place of the three. `test_output_gap_sign()`
— actual > potential must yield a positive gap, and vice versa, on at least
two hand-picked numeric cases. `test_labor_tightness_score_weights()` —
asserts NFP's contribution coefficient is strictly lower than claims' and
JOLTS', matching the course's explicit lead/lag weighting.

**Phase 3:** `test_no_trade_when_gap_below_dispersion()` — an engineered
snapshot where the computed gap is smaller than the ensemble's dispersion
must produce `MacroThesis.status == WATCH` and `trade_idea.instrument ==
"NONE"`, proving the Q6 no-trade path (Section 16.2) is actually reachable,
not just described. `test_no_trade_when_conflicted()` — an engineered
snapshot with growth and inflation signals pointing opposite directions
must produce `convergence_classification == "CONFLICTED"` and the same
no-trade outcome. `test_thesis_has_invalidation_condition()` — asserts
every non-`WATCH`/`DRAFT`-with-no-trade thesis has a non-empty
`stop_or_invalidation` string (Module 1's LTCM-lesson hard gate,
Section 15's Module 1 entry). API test: `GET /thesis/de` returns HTTP 501,
not a silent empty/default thesis.

**Phase 4:** `test_historical_var_matches_hand_calculation()` on a small
synthetic return series with a known quantile. `test_fractional_kelly_never_exceeds_hard_limits()`
— feed a scenario distribution engineered to produce a large raw-Kelly
output, assert the final sized position never exceeds `RiskLimits.max_position_pct_of_portfolio`
regardless of how large the unclipped Kelly fraction would have been.

**Phase 5+ (per extension, as it lands):** each extension ships with at
least one test proving it does NOT change any Phase 1-4 model's public
function signature or `ModelResult` schema shape — a regression test
guarding the "hooks were designed in, not bolted on with breaking changes"
claim made throughout Section 12.

---

## 12. Advanced Extensions and Hooks

| Extension | Interface contract required now | Minimal change to plug in later |
|---|---|---|
| **DuckDB + Parquet** | `persistence.py` already writes Parquet; `MacroDataSnapshot` already carries `retrieved_at`/timestamps | Point a DuckDB `ATTACH` at the existing Parquet directory; no schema change |
| **PyMC Bayesian updater** | `MacroThesis.prior_probability`/`posterior_probability` fields already exist (nullable) | `extensions/bayesian_updater.py` populates these fields post-hoc; thesis schema unchanged |
| **vectorbt backtest** | `RiskInputs`/return-series shapes already match vectorbt's expected `pd.Series`/`pd.DataFrame` input | `extensions/backtest_vbt.py` consumes `models/*` outputs directly, no adapter layer needed |
| **NautilusTrader** | Thesis layer never auto-executes (Section 9.3) — a clean separation boundary already exists | `extensions/nautilus_adapter.py` reads `MacroThesis.trade_idea` as an external consumer, same as a human would |
| **Riskfolio-Lib** | `portfolio/risk_budget.py` stub signature fixed in Phase 1 (Section 9.2) | Fill in the function body; no callers need to change |
| **MLflow** | Every `ModelResult` already carries `model_name`, `confidence`, `as_of` | `extensions/mlflow_tracking.py` wraps model calls with `mlflow.log_metric()`; no model code changes |
| **APScheduler** | `build_us_macro_thesis()` is a pure function of a snapshot — trivially schedulable | `extensions/scheduler.py` calls it on a cron-like schedule; zero changes to the function itself |

---

## 13. Example End-to-End Flows

### 13.1 Example A — Generate Current US Macro Thesis

**Request:**
```
GET /thesis/us HTTP/1.1
Host: localhost:8000
```

**Flow:**
1. `routes_thesis.get_thesis("us")` called.
2. `OpenBBClient` fetches all Section 5.2 series (retries/fallback per 5.1).
3. Results normalized into `MacroDataSnapshot`, validated (Section 5.4).
4. `build_us_macro_thesis(snapshot)` runs — Section 7.2's 10 steps execute
   in order, each independently loggable.
5. Resulting `MacroThesis` serialized to JSON, returned with `200 OK`.

**Response:** (abbreviated — full shape per Section 7.3's first example)
```json
{ "thesis_id": "us-...", "regime": {...}, "trade_idea": {...}, "status": "DRAFT" }
```

**On failure at step 2** (OpenBB unreachable): `502 Bad Gateway` with
`{"detail": "Data fetch failed: ..."}` — never a silent empty thesis.

### 13.2 Example B — Stress Test Portfolio Under a GFC-Like Scenario (Phase 5+)

**Scenario definition** (`scenarios/gfc_2008.yaml`, illustrative):
```yaml
name: gfc_2008_like
growth_shock: -4.0          # output gap shift, pp
credit_spread_hy_shock: +600  # bp widening
equity_shock: -35            # % index decline
rate_shock: -300             # bp, Fed emergency cutting
correlation_override:
  treasuries_vs_hy_credit: -0.7  # flight to quality
```

**Flow:** `extensions/backtest_vbt.py` (or a dedicated
`extensions/scenario_engine.py`) applies the shock vector to current
portfolio instrument exposures, recomputes portfolio-level VaR/ES/drawdown
under the shocked correlation matrix (per Module 17.2's "coherent
scenario, not isolated shock" principle), and returns:

```json
{
  "scenario": "gfc_2008_like",
  "portfolio_pnl_estimate_pct": -18.4,
  "var_95_under_scenario": -22.1,
  "expected_shortfall_under_scenario": -29.6,
  "max_drawdown_estimate_pct": -24.0,
  "factor_exposure_breakdown": {"rates_duration": -12.0, "credit_beta": -4.1, "equity_beta": -2.3}
}
```

---

## 14. Glossary and Module-to-Code Mapping

### 14.1 Full Module Mapping Table

| Course Module | Code Module(s) | Key Functions | Endpoints |
|---|---|---|---|
| 1 — Foundations | (informs `docs/DECISIONS.md` narrative context only) | — | — |
| 2 — Rates & Bonds | `data_layer` (yield/TIPS fetch), `models/yield_curve.py` | `curve_slope`, `breakeven_inflation` | `/thesis/us` |
| 3 — Growth | `models/regime.py`, `models/gdp_nowcast.py` | `classify_regime_rule_based`, `output_gap` | `/thesis/us` |
| 4 — Central Banks | `models/policy_rules.py` | `taylor_rule`, `balanced_approach_rule`, `first_difference_rule`, `policy_rule_ensemble` | `/thesis/us` |
| 5 — Inflation | `models/inflation_nowcast.py` | `inflation_breadth_score` | `/thesis/us` |
| 6 — Labor | `models/labor_synthesis.py` | `labor_tightness_score` | `/thesis/us` |
| 7 — Output Gap/Nowcasting | `models/gdp_nowcast.py` | `output_gap`, `simple_gdp_nowcast` | `/thesis/us` |
| 8 — Yield Curve/Credit | `models/yield_curve.py`, `models/risk.py` | `curve_slope`, `breakeven_inflation`, `yield_curve_pca` | `/thesis/us` |
| 9 — FX | `models/fx_carry.py` | `cip_check`, `carry_score`, `dollar_smile_regime` | `/thesis/us` (future: `/thesis/fx/{pair}`) |
| 10 — Commodities | `models/commodities.py` | `oil_balance_signal` (informational only) | `/thesis/us` (transmission input only) |
| 11 — Equity Macro | `models/equity_macro.py` | `sector_rotation_prior`, `duration_sensitivity` | `/thesis/us` |
| 12–13 — Data/Synthesis | `data_layer/*`, `thesis_layer/builder.py` convergence logic | validation, convergence classifier | `/dashboard_data` |
| 14 — Trade Construction | `thesis_layer/*` | `build_us_macro_thesis` | `/thesis/us`, `/thesis/us/stream` |
| 15–16 — Case Studies | `extensions/` scenario YAMLs (Phase 5+) | scenario engine | (Phase 5+) |
| 17–18 — Risk/Portfolio | `models/risk.py`, `models/volatility.py`, `portfolio/risk_budget.py` | `historical_var`, `expected_shortfall`, `realized_vol_simple` | (Phase 4+) |

### 14.2 Glossary

- **Regime**: A classified macro-cycle state (e.g., `late_expansion`,
  `stagflation`) with an associated confidence, not a certainty.
- **Policy gap**: The difference between what a policy-rule ensemble
  prescribes and what the market is currently pricing — the foundational
  tradeable signal per Module 14.
- **Output gap**: `(actual GDP − potential GDP) / potential GDP × 100`.
- **Breakeven**: Market-implied average inflation over a bond's tenor,
  derived as `nominal yield − TIPS real yield`.
- **Carry**: The yield differential earned holding a higher-rate asset
  funded by a lower-rate one, before any FX move.
- **Convergence classification**: Whether independent model signals
  (growth, inflation, policy) agree (`HIGH`/`MEDIUM`) or disagree
  (`LOW`/`CONFLICTED`) — divergence is information, never smoothed away.
- **ModelResult**: The universal typed-output contract every model in this
  system returns — value + confidence + interpretation + context + inputs
  used + warnings. No model ever returns a bare number.

---

## 15. Module-by-Module Process Knowledge (Modules 1–18)

Every module below follows the same six-part structure. Formulas are taken
directly from course material (SOURCE_COURSE.pdf), not generic textbook
restatements, and are cross-referenced to the exact code artifacts already
specified in Sections 3–9 wherever an implementation exists.

---

### Module 1 — Global Macro Foundations, History, Crises

**Purpose & key concepts:** Why macro trading exists (information asymmetry
in policy/flows, not stock-picking-style edge); Bretton Woods, the Gold
Standard, the Nixon Shock, the trilemma (fixed rate + free capital + independent
monetary policy — pick two); Black Wednesday, LTCM, Dot-com, GFC, COVID as
foundational case studies establishing recurring failure patterns:
(a) regime/promise breaking under the trilemma, (b) leverage/liquidity
mismatch (positive EV, catastrophic tail).

**Inputs:** None directly — this module is conceptual, not quantitative. It
supplies *priors and epistemic discipline* consumed by every other module.

**Core logic (conceptual → system behavior):**
- The trilemma is encoded as a **structural check function**, not a formula:
  `check_trilemma_tension(country, has_capital_controls, has_fixed_fx, is_monetary_independent) -> warning|None`.
  Used by `models/fx_carry.py`'s EM checklist (Module 9) and the regime
  classifier when evaluating any pegged/managed currency.
- The LTCM lesson is encoded as a **hard system rule, not a suggestion**:
  no `MacroThesis.trade_idea` may be promoted past `DRAFT` status without a
  populated `stop_or_invalidation` and a scenario_distribution containing at
  least one tail scenario with negative payoff — enforced in
  `thesis_layer/builder.py` as a validation gate, not left to convention.
- The "surprise vs. priced expectation" principle (Lesson 1.1) is the single
  organizing idea behind `MarketPricingGap` (Section 7.1) — every gap
  computation in the system is implicitly answering "what does the market
  already expect, and how does that differ from what I expect."

**Outputs:** No `ModelResult` — Module 1 outputs are *system invariants*
documented in `docs/INVARIANTS.md`: (1) never promote a thesis without an
invalidation condition; (2) never treat a rule-prescribed rate/estimate as
observed truth; (3) always evaluate priced expectation before economic
condition when assessing a trade's edge.

**Mapping to thesis:** Governs `MacroThesis.status` transition rules and the
mandatory presence of `trade_idea.stop_or_invalidation` and
`scenario_distribution` tail entries.

**Mapping to 15 core questions:** Q6 (economically meaningful difference —
Lesson 1.1's core test), Q8 (invalidation — LTCM lesson), Q13 (loss
scenarios — LTCM lesson), Q15 (NO TRADE as legitimate outcome — Soros vs.
LTCM contrast: bounded-downside asymmetric bets get sized, symmetric
uncertain-payoff bets often shouldn't).

---

### Module 2 — Rates & Bonds (Plumbing and Math)

**Purpose & key concepts:** Central bank floor system (IORB/ON RRP/Standing
Repo), money creation (loan-creates-deposit, not the multiplier myth),
shadow banking/repo as a stress leading indicator, Eurodollar system (global
dollar funding, Fed as de facto global central bank), bond pricing,
duration, convexity.

**Inputs:** `yield_curve` (all tenors), `fed_funds_rate`, repo/SOFR series
(Section 5.2), credit spread series.

**Core logic (formulas, verbatim from course):**
```
Price = Σ_{t=1}^{n} [C / (1+y)^t] + F / (1+y)^n
MacDur = Σ [t × PV(CF_t)] / Price
ModDur = MacDur / (1 + y)
%ΔPrice ≈ −ModDur × Δy
%ΔPrice ≈ −ModDur × Δy + ½ × Convexity × (Δy)²        (favorable asymmetry: gains > linear on rallies, losses < linear on selloffs)
F/S = (1 + i_domestic) / (1 + i_foreign)               (CIP — Module 9 formal treatment)
```
Repo stress detection: flag when repo rate spikes materially above IORB/ON
RRP corridor bounds without a corresponding Fed action — this is the
"plumbing stress precedes headline stress" signal (Sept 2019 pattern),
encoded as a rule in `models/risk.py`'s early-warning checks (Phase 5+).

**Outputs:**
```python
class BondAnalytics(BaseModel):
    price: float
    macaulay_duration: float
    modified_duration: float
    convexity: float | None
    pct_price_change_est: float
```

**Mapping to thesis:** Feeds `models/yield_curve.py` (curve trades),
`portfolio/risk_budget.py` (duration-weighted sizing per Module 15.1's
"never equal-notional" rule), and `models/risk.py`'s duration-based
scenario P&L in `ScenarioOutcome`.

**Mapping to 15 core questions:** Q9 (cleanest instrument — duration math
is literally what makes instrument selection precise rather than guesswork),
Q11 (risk sizing via duration-weighted notional, not naive dollar amounts).

---

### Module 3 — Growth: National Accounts, Cycles, Long-Run Determinants

**Purpose & key concepts:** GDP = C+I+G+(X−M); savings-investment identity
(S−I)+(T−G)=(X−M) (why tariffs alone can't fix a trade deficit); business
cycle phases and why lagging-data reliance puts traders structurally behind
the market; policy-mix 2×2 (fiscal×monetary); Phillips Curve with
expectations (π=π^e−β(u−u*)); Minsky borrower classification
(Hedge/Speculative/Ponzi) as a credit-cycle leading indicator; demographics
as the high-confidence, slow-moving r* driver; productivity as the
low-confidence, high-impact wildcard.

**Inputs:** `gdp_real`, `gdp_nominal`, `unemployment_rate`, credit/lending
survey proxies (Phase 5+, requires a source beyond core OpenBB series — flag
as known limitation if unavailable), demographic/labor-force-growth
assumptions (config-supplied, not fetched — Section 10.4 `settings.yaml`).

**Core logic:**
```
GDP = C + I + G + (X − M)
(S − I) + (T − G) = (X − M)
π = π^e − β(u − u*)                                    (expectations-augmented Phillips Curve)
Potential Y = A × K^α × L^(1−α)                        (Cobb-Douglas — feeds Module 7's output gap)
```
Minsky borrower-mix drift (Hedge→Speculative→Ponzi) is encoded as a
**qualitative regime input**, not a formula — a config-driven flag
(`credit_cycle_stage: str`) manually or semi-manually updated from SLOOS
data, feeding the regime classifier's `stagflation`/`late_expansion`
disambiguation logic in `models/regime.py`.

**Outputs:** `PolicyRuleResult`-adjacent `GrowthAccountingResult` (feeds
`r_star_estimate` used by `taylor_rule` in Module 4) — schema TBD at
implementation time, deferred to Phase 3 per the phased plan (Section 11),
since it directly informs the `r_star` input already stubbed in
`TaylorRuleInputs` (Section 6.1).

**Mapping to thesis:** `MacroThesis.growth_view`; indirectly, `r_star`
feeding `policy_view`.

**Mapping to 15 core questions:** Q1 (what's happening — the accounting
identity is literally the diagnostic tool for decomposing a GDP print), Q2
(what's next — Phillips Curve forecast), Q7 (evidence strength — Minsky
composition as a corroborating, independent signal alongside raw credit
growth, per Module 13's "redundant vs. independent" distinction).

---

### Module 4 — Central Banks (Reaction Function Engine)

**Purpose & key concepts:** Full detail already specified in Section 6.1.
Additional course-specific nuance to encode: the **three-rule-ensemble
discipline** (never average divergent rule outputs — divergence is
information about policy uncertainty), forward-guidance language parsing
(hawkish/dovish shift detection via statement text-diff, Phase 5+), and the
critical per-central-bank reaction-function differences (Section 6.7's
`dollar_smile_regime` partially encodes this; a full `CentralBankProfile`
config per country is a Phase 5+ multi-country item).

**Inputs:** `fed_funds_rate`, inflation series, `output_gap` (Module 7
output), FOMC statement text (Phase 5+ — requires a text source beyond core
OpenBB series; federalreserve.gov RSS, matching the companion data
pipeline's approach).

**Core logic:** Already fully specified (Section 6.1) — Taylor/Balanced/
First-Difference formulas, `policy_rule_ensemble()`'s explicit
non-averaging dispersion output.

**Outputs:** `PolicyRuleResult`, `policy_rule_ensemble()` dict (Section 6.1).

**Mapping to thesis:** `MacroThesis.policy_view`, and directly,
`MarketPricingGap.model_implied_value` (the ensemble midpoint or, per
dispersion, a documented range rather than a false-precision point value).

**Mapping to 15 core questions:** Q3/Q4 (what's priced — market-implied
path vs. model), Q5 (the gap itself — this module's entire purpose), Q6
(is the gap economically meaningful — dispersion-adjusted; a 20bp gap when
rule dispersion is 150bp is NOT meaningful, per Module 4's explicit
"large divergence = uncertainty signal" caveat).

---

### Module 5 — Inflation (Measurement, Nowcasting, Transmission)

**Purpose & key concepts:** Full detail specified in Section 6.3 (Phase 1
simplified version) — CPI Laspeyres construction, PCE Fisher chain-weighting,
supercore/trimmed-mean/median as convergence cross-checks, PPI pipeline
pass-through, shelter/OER 12-18 month lag mechanism, and the critical
cross-asset transmission table (bonds/equities/gold/FX react to inflation
surprises via *different* mechanisms — real yields for gold, not headline
CPI directly).

**Inputs:** `cpi_headline`, `cpi_core`, `pce_core`, `ppi`, `yield_curve` +
`tips_yields` (for breakevens, shared with Module 8).

**Core logic:**
```
CPI_t = Σ(P_t,i × Q_0,i) / Σ(P_0,i × Q_0,i) × 100        (Laspeyres — substitution bias, overstates)
Fisher = √(Laspeyres × Paasche)                            (PCE chain-weighting — captures substitution)
Breakeven = Nominal_yield − TIPS_yield                     (shared formula with Module 8)
```
Gold/real-yield transmission rule (used by any future commodity-informational
model, Module 10): gold direction should be reasoned about via **real yield
changes**, never headline CPI directly — encoded as an explicit warning
string attached to any inflation-related `ModelResult` that a caller might
misuse for a gold view.

**Outputs:** `ModelResult` from `inflation_breadth_score` (Section 6.3);
Phase 5+ full multi-measure convergence output
(`InflationConvergenceResult` with `HIGH/MEDIUM/LOW/CONFLICTED` classification,
matching Module 13's convergence taxonomy exactly).

**Mapping to thesis:** `MacroThesis.inflation_view`; feeds
`confirmation_signals` (breadth agreement/disagreement across sub-measures).

**Mapping to 15 core questions:** Q7 (evidence strength — literally what the
breadth/convergence check exists to quantify), Q1/Q2 (current state and
trajectory).

---

### Module 6 — Labor (NFP, JOLTS, Claims, Wages)

**Purpose & key concepts:** Full detail specified in Section 6.4 — two-survey
divergence (Establishment vs. Household), birth-death model as an
error-prone estimate (not fact), revision-magnitude-at-turning-points,
JOLTS as forward-looking (openings/quits lead layoffs/unemployment), AHE
composition-distortion vs. ECI ground-truth, jobless claims as the
highest-frequency signal, and the full lead/lag data hierarchy synthesis.

**Inputs:** `unemployment_rate`, `initial_claims`, `continuing_claims`,
`jolts_openings`, `jolts_quits`.

**Core logic:** Already specified (Section 6.4) — `labor_tightness_score()`
weighting scheme (40% claims, 40% JOLTS, 20% NFP, deliberately underweighting
the coincident/noisy NFP series per the course's explicit lead/lag hierarchy).

**Outputs:** `ModelResult` from `labor_tightness_score`.

**Mapping to thesis:** Feeds `growth_view` (output gap corroboration) and
indirectly `inflation_view` (wage-price spiral mechanism — Phillips Curve's
`(u−u*)` term).

**Mapping to 15 core questions:** Q7 (evidence strength/independence — JOLTS
and claims come from genuinely separate BLS/DOL survey infrastructure, a
real independence check per Module 13's discipline), Q2 (forward-looking
signal for what happens next in growth/policy).

---

### Module 7 — Output Gap & Nowcasting

**Purpose & key concepts:** Full detail specified in Section 6.5 — three GDP
calculation approaches (expenditure/income/production), GDP vs. GDI
divergence as information, GDP Deflator vs. CPI/PCE (imports-exclusion
distinction), Cobb-Douglas potential GDP, output gap formula, LEI composite
convergence logic, GDPNow mechanics (no free API — manual entry required).

**Inputs:** `gdp_real`, `gdp_nominal`, config-supplied potential GDP
parameters (A, K, L, α — Section 10.4).

**Core logic:** Already specified (Section 6.5) —
```
Output Gap % = (Actual GDP − Potential GDP) / Potential GDP × 100
Potential Y = A × K^α × L^(1−α)
```

**Outputs:** `ModelResult` from `output_gap`, `simple_gdp_nowcast`.

**Mapping to thesis:** Direct input to `policy_view` (Taylor Rule's
`(y−y*)` term) and `growth_view`.

**Mapping to 15 core questions:** Q1 (current growth state — is the economy
above/below sustainable capacity), Q6 (is the output gap large enough to be
meaningful, given potential-GDP estimation uncertainty — this module's
`confidence=0.5` on `output_gap` exists precisely to force this question).

---

### Module 8 — Yield Curve & Credit

**Purpose & key concepts:** Full detail specified in Section 6.6 —
expectations-vs-term-premium curve decomposition, inversion mechanism
(market's own forward Fed-rate forecast, 6-24 month lag caveat), Treasury
auction mechanics (bid-to-cover, indirect bidder share), breakeven
construction, credit spreads (IG/HY) as a real-time financial-conditions
gauge distinct from the policy rate, HY-spread-widening as a recession
leading indicator with a *different* underlying mechanism than curve
inversion (default-risk repricing vs. rate-expectations repricing).

**Inputs:** `yield_curve`, `tips_yields`, `credit_spread_hy`,
`credit_spread_ig`.

**Core logic:** Already specified (Section 6.6) — `curve_slope()`,
`breakeven_inflation()`; Phase 5+ `yield_curve_pca()` (daily changes only,
never levels, per Module 18.3).

**Outputs:** `ModelResult` from `curve_slope`, `breakeven_inflation`.

**Mapping to thesis:** Direct input to `market_pricing_gap` (curve shape
IS the market's priced policy-path expectation) and `models/risk.py`'s FCI
components (credit spreads).

**Mapping to 15 core questions:** Q3/Q4 (what's priced — the curve's
expectations component literally answers this), Q7 (convergence check —
curve inversion + HY spread widening agreeing = stronger combined signal
per Module 8.3's explicit triangulation principle).

---

### Module 9 — FX (Parity Conditions, Carry, Dollar Smile, EM Crises)

**Purpose & key concepts:** Full detail specified in Section 6.7 — CIP as a
near-arbitrage identity whose *breakdown* is a funding-stress signal (not an
arbitrage opportunity); UIP's empirical failure as the theoretical
foundation of carry trades (forward premium puzzle); PPP as a multi-year
anchor never used for tactical timing; Dollar Smile (left=crisis/safe-haven,
right=US outperformance, middle=synchronized growth weakens USD); the three
EM structural vulnerabilities (currency mismatch/"original sin", capital-
inflow dependence, thin-reserve pegs) and the Asian Crisis as their full
mechanical demonstration.

**Inputs:** `fx_spot` (per pair), rate differentials (from `fed_funds_rate`
+ a foreign-country equivalent — Phase 5+ multi-country data requirement),
VIX/risk-sentiment proxy.

**Core logic:** Already specified (Section 6.7) —
```
F/S = (1 + i_d) / (1 + i_f)                              (CIP)
Expected %ΔS ≈ i_d − i_f                                  (UIP — fails empirically, this IS the carry edge)
Expected %ΔS = π_d − π_f                                  (Relative PPP — long-run anchor only)
```
EM vulnerability checklist (three-factor, per Module 9.4 and the companion
data pipeline's IMF/World Bank REST integration): current account balance,
USD-vs-local debt share, FX reserves/short-term external debt ratio —
**multiple failing checks override a favorable cointegration signal**, per
the course's explicit warning against trusting statistics without
fundamentals.

**Outputs:** `ModelResult` from `cip_check`, `carry_score`,
`dollar_smile_regime` (Section 6.7).

**Mapping to thesis:** Feeds a future `fx_thesis` extension of `MacroThesis`
(not built in Phase 1, which is US-rates-focused only) and, in Phase 1,
`dollar_smile_regime`'s output informs general risk-sentiment context for
the `regime` field.

**Mapping to 15 core questions:** Q9 (instrument purity — CIP/breakeven-style
"isolate the specific risk factor" discipline generalizes directly to FX
instrument choice), Q7 (EM checklist as an independent evidence layer beyond
pure price-based cointegration).

---

### Module 10 — Commodities (Informational Only)

**Purpose & key concepts:** Oil supply structure (OPEC+ policy-driven swing
capacity vs. shale's mechanical price-responsive supply), gold's three-layer
framework (real yields primary, central bank reserve diversification,
crisis/confidence-loss demand — explicitly NOT a simple "inflation hedge"),
copper as a China-concentrated growth barometer (not a generic global-growth
proxy), agricultural commodities' biological/seasonal (not investment-speed)
supply inelasticity.

**Inputs:** Commodity spot prices (informational — Section 6.8 explicitly
scopes this out of tradeable production logic, matching CLAUDE.md Section 5's
"FX, rates, equity indices only" production universe).

**Core logic:** No formulas produce trade signals here by design. The only
system-relevant logic is the **transmission-channel warning**: any inflation
or growth model consuming an oil/commodity shock must attribute it correctly
(imported-price shock vs. domestic-demand-driven), matching the GDP Deflator
vs. CPI distinction from Module 7.

**Outputs:** `ModelResult` from `oil_balance_signal` — explicitly labeled
informational-only in its `warnings` field (Section 6.8).

**Mapping to thesis:** Never populates `trade_idea.instrument` directly —
may appear in `inflation_view`'s context field as a contributing factor.

**Mapping to 15 core questions:** Q15 (NO TRADE logic — commodities are a
structurally enforced "no direct trade" domain in this system, a hard
architectural decision, not a soft preference).

---

### Module 11 — Equity Macro

**Purpose & key concepts:** Full detail specified in Section 6.9 — sector
rotation as a base-rate prior (not a mechanical rule), growth-vs-value as a
duration/discount-rate trade (mechanical, not fundamental), factor
performance as regime-dependent (momentum crashes at regime turns, value
works post-recession, quality/low-vol = flight-to-quality equity analog).

**Inputs:** `equity_index` (per index), regime state (from Module 3/4's
classifier), `fed_funds_rate`/curve (for the discount-rate channel).

**Core logic:** Already specified (Section 6.9) — `sector_rotation_prior()`,
`duration_sensitivity()`.

**Outputs:** `ModelResult` from both functions above.

**Mapping to thesis:** Feeds a future `equity_thesis` extension; in Phase 1,
contributes to general FCI context (equity trend/volatility as a financial-
conditions component per Module 12's FCI construction).

**Mapping to 15 core questions:** Q9 (instrument selection — broad indices
only, never single stocks, a hard system boundary matching CLAUDE.md
Section 5), Q6 (starting valuation context matters — same cycle phase,
different starting P/E = different risk/reward, per Module 11's explicit
caveat).

---

### Module 12 — Probability & Risk (FCI, Scorecard, Bayesian, Monte Carlo, Kelly)

**Purpose & key concepts:** Full detail specified in Section 5 of the
*standalone data-pipeline* companion project and partially re-specified here
via `models/risk.py`. Core ideas requiring explicit encoding in *this*
system: the Financial Conditions Index as a broader-than-policy-rate read
on effective monetary tightness; the four-pillar Macro Scorecard
(Growth/Inflation/FC/Policy) with convergence-not-averaging as the central
discipline; Bayes' theorem for thesis probability updating; Monte Carlo for
full outcome distributions (not point EV); fractional Kelly as the
mandatory position-sizing discipline (never full Kelly, given r*/potential-
GDP/regime-probability estimation uncertainty).

**Inputs:** All prior modules' `ModelResult` outputs (this is the
synthesis layer, matching `thesis_layer/builder.py`'s role exactly).

**Core logic:**
```
FCI = Σ w_i × (Component_i − avg_i)
P(A|B) = P(B|A) × P(A) / P(B)                             (Bayes' theorem)
EV = Σ p_i × Payoff_i
f* = (p×b − q) / b                                          (Kelly, conceptual reference only)
Fractional Kelly = f* / k, k ≥ 2                            (mandatory — never full Kelly)
```

**Outputs:** The four-pillar convergence classification
(`HIGH/MEDIUM/LOW/CONFLICTED`) IS `MacroThesis.convergence_classification`
directly — this module's output schema is not separate from the thesis
schema, it *is* the thesis-assembly logic itself.

**Mapping to thesis:** `convergence_classification`,
`prior_probability`/`posterior_probability` (Phase 5+ Bayesian layer),
`scenario_distribution` (Monte Carlo output), and the mandatory fractional-
Kelly constraint enforced wherever position sizing is ever computed
(`portfolio/risk_budget.py`, Section 9.2).

**Mapping to 15 core questions:** Q10 (expected outcome distribution — Monte
Carlo), Q11 (risk sizing — fractional Kelly), Q7 (evidence strength —
literally the convergence classifier's entire purpose).

---

### Module 13 — Data (Sourcing, Cross-Validation, Vintage Integrity)

**Purpose & key concepts:** Platform landscape (Bloomberg/FRED/Macrobond/
primary agencies), seasonal adjustment and revision-awareness, vintage/
point-in-time integrity as mandatory for any future backtesting, the
cross-validation workflow (multiple independent sources agreeing = real
confidence; multiple correlated-not-independent sources agreeing = false
confidence — the critical nuance the user independently derived in this
project's earlier conversation).

**Inputs:** N/A — this module IS the data layer's design discipline
(Section 5), not a model consuming a snapshot.

**Core logic:** The **independence-vs-redundancy check** is the single most
important piece of Module 13 to encode correctly: `convergence_classifier`
(Module 12's four-pillar logic) must weight evidence by genuine source
independence, not raw count — e.g., three CPI sub-measures derived from the
same BLS release are ONE vote, not three, when cross-checked against an
independently-sourced signal like TIPS breakevens or a labor-market read.

**Outputs:** No `ModelResult` — this module's "output" is the
`inputs_used` field discipline enforced on every other model (Section 6's
universal contract), which exists specifically so the convergence
classifier can later inspect *which* underlying data actually drove each
signal and detect redundancy.

**Mapping to thesis:** `confirmation_signals` list — each entry must
document enough about its source (via `inputs_used`) for the convergence
logic to correctly classify independence.

**Mapping to 15 core questions:** Q7 (evidence strength and independence —
this module's entire reason for existing).

---

### Module 14 — Trade Construction

Fully detailed separately in **Section 16** below, per your request — this
module IS the thesis layer itself, not a contributing input to it.

---

### 6.6b Financial Conditions Index (Module 12) — MISSING FROM ORIGINAL SPEC, ADDED HERE

### 22.7 Resolves Finding #7 — FCI Standardization (Z-Scores, Not Raw Mixed-Unit Deviations)

```python
def compute_fci_corrected(policy_rate: float, policy_rate_series_mean: float, policy_rate_series_std: float,
                           credit_spread: float, credit_spread_mean: float, credit_spread_std: float,
                           term_premium: float, term_premium_mean: float, term_premium_std: float,
                           dollar_change: float, dollar_change_mean: float, dollar_change_std: float,
                           equity_change: float, equity_change_mean: float, equity_change_std: float,
                           weights: dict[str, float] | None = None) -> ModelResult:
    """
    CORRECTED per Finding #7. Every component is Z-SCORE STANDARDIZED
    ((x - mean) / std) BEFORE weighting — percent, bp, and index-point
    units are not comparable as raw deviations, which the prior version
    incorrectly did. Standard deviations must be computed over a
    consistent, documented trailing window (config: fci.standardization_window_years,
    default 10) for every component.
    """
    w = weights or {"policy_rate": 0.25, "credit_spread": 0.30, "term_premium": 0.15, "dollar": 0.15, "equity": 0.15}
    z_policy = (policy_rate - policy_rate_series_mean) / policy_rate_series_std
    z_credit = (credit_spread - credit_spread_mean) / credit_spread_std
    z_term = (term_premium - term_premium_mean) / term_premium_std
    z_dollar = (dollar_change - dollar_change_mean) / dollar_change_std
    z_equity = (equity_change - equity_change_mean) / equity_change_std

    fci = (w["policy_rate"]*z_policy + w["credit_spread"]*z_credit + w["term_premium"]*z_term
           + w["dollar"]*z_dollar - w["equity"]*z_equity)
    return ModelResult(
        model_name="compute_fci_corrected", country="us", as_of=datetime.utcnow(),
        value=round(fci, 3), confidence=0.4,
        interpretation=f"FCI (z-score composite): {fci:+.3f}",
        context="All components z-standardized before combination — comparable units, not raw mixed-unit deviations (Finding #7 fix)",
        inputs_used=["policy_rate", "credit_spread", "term_premium", "dollar_change", "equity_change"],
        warnings=["Weights remain illustrative, not calibrated — cross-check against FRED NFCI mandatory before this feeds any thesis at meaningful confidence"],
    )

```

---


**This model was described narratively in Section 9 but never actually
implemented in Section 6 alongside the other Phase 2 core models — it
should have shipped in Phase 2 alongside policy_rules/regime/inflation/
labor/gdp/yield_curve. If Phase 2 is already built without this, it must
be retroactively added now, not deferred to Phase 5+.**

```python
# src/macro_engine/models/financial_conditions.py

class FCIInputs(BaseModel):
    policy_rate: float
    policy_rate_avg: float          # historical average, config-supplied
    credit_spread_hy: float
    credit_spread_hy_avg: float
    term_premium: float
    term_premium_avg: float
    dollar_index_change_pct: float
    equity_index_change_pct: float
    weights: dict[str, float] = Field(default_factory=lambda: {
        "policy_rate": 0.25, "credit_spread": 0.30, "term_premium": 0.15,
        "dollar": 0.15, "equity": 0.15,
    })

def compute_fci(inputs: FCIInputs) -> ModelResult:
    """
    FCI = w1(policy_rate - avg) + w2(credit_spread - avg) + w3(term_premium - avg)
          + w4(dollar_change) - w5(equity_change)
    Positive = tighter-than-average financial conditions; negative = looser.
    Weights are configurable (config/settings.yaml: fci.weights) — the
    defaults above are illustrative, NOT calibrated against the Chicago
    Fed's actual NFCI methodology. Cross-check against real NFCI data
    (FRED series NFCI) once available — large unexplained divergence
    between this custom FCI and NFCI should be investigated, not ignored,
    per Module 12's explicit cross-check requirement.
    """
    w = inputs.weights
    fci = (
        w["policy_rate"] * (inputs.policy_rate - inputs.policy_rate_avg)
        + w["credit_spread"] * (inputs.credit_spread_hy - inputs.credit_spread_hy_avg)
        + w["term_premium"] * (inputs.term_premium - inputs.term_premium_avg)
        + w["dollar"] * inputs.dollar_index_change_pct
        - w["equity"] * inputs.equity_index_change_pct
    )
    return ModelResult(
        model_name="compute_fci", country="us", as_of=datetime.utcnow(),
        value=round(fci, 3), confidence=0.4,
        interpretation=f"FCI: {fci:+.3f} ({'tighter' if fci > 0 else 'looser'} than average financial conditions)",
        context="Custom weighted composite — MUST cross-check vs Chicago Fed NFCI (FRED: NFCI) before trusting at size",
        inputs_used=["policy_rate", "credit_spread_hy", "term_premium", "dollar_index_change_pct", "equity_index_change_pct"],
        warnings=[
            "Weights are illustrative defaults, not calibrated — configurable in settings.yaml",
            "Cross-check against real NFCI mandatory before this feeds any thesis at meaningful confidence",
        ],
    )
```

**Mapping to thesis:** feeds a new `MacroThesis.financial_conditions_view` field
(add to Section 7.1's schema) and directly informs Q6 (is the gap
economically meaningful — a sharply tightening FCI independent of Fed
action is itself informative about urgency, per Module 12's "Pillar 3
speed/magnitude = timing" principle).

---

### 6.6c Drawdown Management & Rebalancing (Module 17.3) — MISSING FROM ORIGINAL SPEC, ADDED HERE

**Never assigned to any phase in the original document — genuinely absent,
not deferred. Belongs in `portfolio/risk_budget.py` alongside the
Riskfolio-Lib hook (Section 9.2), Phase 4.**

```python
# src/macro_engine/portfolio/risk_budget.py (addition)

class DrawdownState(BaseModel):
    high_water_mark: float
    current_value: float

    @property
    def drawdown_pct(self) -> float:
        return (self.high_water_mark - self.current_value) / self.high_water_mark

class DrawdownRule(BaseModel):
    threshold_pct: float
    risk_reduction_pct: float    # e.g. 0.5 = cut risk in half

DEFAULT_DRAWDOWN_RULES = [
    DrawdownRule(threshold_pct=0.10, risk_reduction_pct=0.50),
    DrawdownRule(threshold_pct=0.15, risk_reduction_pct=0.75),
    DrawdownRule(threshold_pct=0.20, risk_reduction_pct=1.00),  # stop trading entirely
]

def evaluate_drawdown_rules(state: DrawdownState, rules: list[DrawdownRule] = DEFAULT_DRAWDOWN_RULES) -> ModelResult:
    """
    Pre-committed, mechanical de-risking — deliberately NOT a discretionary
    decision made in the moment (Module 17.3's explicit behavioral-risk
    rationale: a trader mid-drawdown, convinced their thesis is still
    correct, is prone to doubling down rather than de-risking). Rules are
    evaluated in order; the MOST SEVERE triggered rule wins.
    """
    dd = state.drawdown_pct
    triggered = [r for r in rules if dd >= r.threshold_pct]
    if not triggered:
        return ModelResult(
            model_name="drawdown_rule_check", country="us", as_of=datetime.utcnow(),
            value=0.0, confidence=1.0,
            interpretation=f"Drawdown {dd:.1%} — no risk-reduction rule triggered",
            context=f"HWM={state.high_water_mark}, current={state.current_value}",
            inputs_used=["high_water_mark", "current_value"],
        )
    worst = max(triggered, key=lambda r: r.risk_reduction_pct)
    return ModelResult(
        model_name="drawdown_rule_check", country="us", as_of=datetime.utcnow(),
        value=worst.risk_reduction_pct, confidence=1.0,
        interpretation=f"Drawdown {dd:.1%} exceeds {worst.threshold_pct:.0%} threshold — reduce risk by {worst.risk_reduction_pct:.0%}",
        context="Pre-committed mechanical rule, NOT a discretionary judgment call — apply regardless of thesis conviction",
        inputs_used=["high_water_mark", "current_value"],
        warnings=["This overrides thesis conviction — a thesis believed correct does NOT exempt a position from this rule (Module 17.3 LTCM-lesson rationale)"],
    )

class RiskBudgetTarget(BaseModel):
    instrument: str
    target_risk_contribution_pct: float

def check_rebalancing_drift(current_contributions: dict[str, float],
                             targets: list[RiskBudgetTarget],
                             drift_threshold_pct: float = 0.10) -> ModelResult:
    """
    Detects when actual risk contribution has drifted from the originally
    intended risk budget — a SEPARATE process from thesis-invalidation
    (Module 17.3's named failure mode: conflating 'my portfolio drifted' with
    'my thesis is wrong' is a real, documented mistake this function exists
    specifically to prevent by keeping the two checks structurally distinct).
    """
    drifted = []
    for t in targets:
        actual = current_contributions.get(t.instrument, 0.0)
        if abs(actual - t.target_risk_contribution_pct) > drift_threshold_pct:
            drifted.append((t.instrument, t.target_risk_contribution_pct, actual))
    return ModelResult(
        model_name="rebalancing_drift_check", country="us", as_of=datetime.utcnow(),
        value=drifted, confidence=0.8,
        interpretation=f"{len(drifted)} instrument(s) drifted beyond {drift_threshold_pct:.0%} from target risk budget" if drifted else "No rebalancing needed",
        context="This is PORTFOLIO risk-budget maintenance, NOT a thesis-validity check — do not conflate with invalidation logic",
        inputs_used=["current_contributions", "targets"],
        warnings=["Rebalancing a drifted position does NOT mean its thesis is wrong, and a strong thesis does NOT exempt it from rebalancing (Module 17.3)"],
    )
```

---

### 15.1b Curve/Breakeven Trade Constructor (Module 15) — MISSING FROM ORIGINAL SPEC, ADDED HERE

**Section 6.6 only had read-only analytics (`curve_slope`, `breakeven_inflation`).
This is the actual trade-CONSTRUCTION math — the notional-weighting formulas
that build a tradeable structure, not just describe the current curve
shape. Belongs in `models/yield_curve.py`, should have been part of Phase 3
alongside `select_instrument()`.**

```python
# src/macro_engine/models/yield_curve.py (addition)

class CurveTradeConstructor(BaseModel):
    short_tenor: str
    long_tenor: str
    short_duration: float     # modified duration of the short-tenor instrument
    long_duration: float      # modified duration of the long-tenor instrument
    target_notional_short: float  # e.g., desired short-leg notional in $

def construct_duration_weighted_curve_trade(inputs: CurveTradeConstructor) -> ModelResult:
    """
    Steepener/flattener construction: Notional_long = Notional_short *
    (Dur_short / Dur_long) — this is what actually cancels net duration
    (PC1/level exposure) so P&L is driven by the spread change (PC2/slope),
    per Module 15.1/18.3. Equal-notional is EXPLICITLY WRONG per the
    course — this function exists specifically so nothing downstream ever
    builds an equal-notional curve trade by mistake.
    """
    notional_long = inputs.target_notional_short * (inputs.short_duration / inputs.long_duration)
    net_duration_check = (inputs.target_notional_short * inputs.short_duration) - (notional_long * inputs.long_duration)
    return ModelResult(
        model_name="construct_duration_weighted_curve_trade", country="us", as_of=datetime.utcnow(),
        value={"notional_short": inputs.target_notional_short, "notional_long": round(notional_long, 2),
               "net_duration_residual": round(net_duration_check, 6)},
        confidence=0.9,  # this is arithmetic, not an estimate — high confidence in the CALCULATION itself
        interpretation=f"Short {inputs.short_tenor} notional {inputs.target_notional_short}, "
                        f"Long {inputs.long_tenor} notional {notional_long:.2f} — net duration ≈ {net_duration_check:.6f} (should be ~0)",
        context="Duration-weighted per Module 15.1 — equal-notional would leave meaningful residual level/PC1 exposure",
        inputs_used=["short_duration", "long_duration", "target_notional_short"],
        warnings=[] if abs(net_duration_check) < 0.01 else ["Net duration residual non-trivial — check duration inputs"],
    )

class BreakevenTradeConstructor(BaseModel):
    tenor: str
    tips_duration: float
    nominal_duration: float
    target_notional_tips: float

def construct_breakeven_trade(inputs: BreakevenTradeConstructor) -> ModelResult:
    """
    Long TIPS + Short nominal, DURATION-MATCHED (not notional-matched) —
    Notional_nominal = Notional_TIPS * (Dur_TIPS / Dur_nominal), so parallel
    real-yield moves cancel and P&L is driven almost entirely by the
    breakeven spread change (Module 15.2). Same principle as the curve
    constructor above, applied to isolating inflation expectations instead
    of curve slope.
    """
    notional_nominal = inputs.target_notional_tips * (inputs.tips_duration / inputs.nominal_duration)
    return ModelResult(
        model_name="construct_breakeven_trade", country="us", as_of=datetime.utcnow(),
        value={"notional_tips_long": inputs.target_notional_tips, "notional_nominal_short": round(notional_nominal, 2)},
        confidence=0.9,
        interpretation=f"Long TIPS {inputs.tenor} notional {inputs.target_notional_tips}, Short nominal notional {notional_nominal:.2f}",
        context="Duration-matched per Module 15.2 — isolates breakeven/inflation-expectations exposure from real-yield direction",
        inputs_used=["tips_duration", "nominal_duration", "target_notional_tips"],
    )
```



**Purpose & key concepts:** Full detail specified in Section 15.1-15.4 of
the companion data-pipeline project's knowledge base, and directly informs
this system's instrument-selection logic: curve trades (duration-weighted,
never equal-notional), breakeven trades (duration-matched TIPS/nominal pair,
isolates inflation expectations from real-yield noise), cross-market
relative value (correlation-dependent, LTCM tail-risk caveat applies), EM
trades (hard-currency = credit risk only; local-currency = credit+FX risk,
choose deliberately), commodity-linked currencies (AUD/iron ore-China, CAD/
oil, NOK/oil-plus-fiscal-credibility).

**Inputs:** `MacroThesis` draft object (pre-instrument-selection stage) —
this module operates on the *thesis*, not raw data.

**Core logic:** Rule-based instrument selection matching thesis type:
```
Fed policy-path gap           → outright short-end rates (2yr/5yr)
Curve-shape-specific gap      → duration-weighted steepener/flattener
Cross-country policy divergence → cross-market RV (e.g., long US 10yr, short Bund)
Inflation-expectations gap    → breakeven trade (long TIPS, short nominal, duration-matched)
Credit-quality gap            → CDS or HY/IG spread trade (isolates credit from rates)
EM vulnerability thesis        → short EM FX (currency-mismatch-dominant) OR
                                  short local-currency bonds (combined credit+FX) OR
                                  short hard-currency bonds (credit only)
```

**Outputs:** `TradeIdea` (Section 7.1) — `instrument` field populated by
this selection logic.

**Mapping to thesis:** `MacroThesis.trade_idea.instrument`.

**Mapping to 15 core questions:** Q9, entirely — this module's sole purpose.

---

### Module 16 — Case Studies / Crisis Playbooks

Fully detailed separately in **Section 18** below, per your request.

---

### Module 17 — Portfolio Construction & Risk

Fully detailed separately in **Section 17** below, per your request
(expanding on the Section 9 stub).

---

### Module 18 — Quantitative Tools (Regression, Cointegration, PCA, Kalman)

**Purpose & key concepts:** Regression requires an economic mechanism BEFORE
statistical significance is trusted (never data-mine); non-stationary level
regression is spurious (test stationarity first); cointegration is the
formal backbone of every relative-value trade in Module 15, but is a
backward-looking statistical estimate that can break in regime change
(LTCM, formalized); PCA on yield-curve/portfolio **daily changes, never
levels**; Kalman filters as the formal machinery for estimating unobservable,
time-varying states (r*, potential GDP, time-varying hedge ratios) — the
same discipline `pykalman`-prohibition already encodes at the tooling level
(Section 4).

**Inputs:** Time-series of any two candidate cointegrated instruments
(for RV pair construction, Module 15); yield-curve tenor panel (for PCA).

**Core logic:**
```
Y = α + βX + ε                                            (regression; R² low = genuine humility signal, not failure)
Engle-Granger: regress Y on X → residuals → ADF test on residuals
PCA: Σ = VΛV'  (eigen-decomposition of covariance of DAILY CHANGES, never levels)
Kalman: predict x̂_{t|t-1} = F x̂_{t-1|t-1}; update via Kalman gain K_t
```

**Outputs:** Phase 5+ items — `yield_curve_pca()` (Section 6.6; **built, not a stub** — real body in
`models/yield_curve.py`, D-097-era; see `docs/PHASE5_DEFERRED.md` §1),
`extensions/bayesian_updater.py`'s Kalman-filtered r*/potential-GDP
estimates (replacing the Phase 1 static config values in `settings.yaml`).

**Mapping to thesis:** Improves the *confidence* field on
`policy_view`/`growth_view` once Kalman-filtered r*/potential-GDP replace
static estimates — a direct, measurable confidence upgrade path already
anticipated by every Phase-1 model's conservative `confidence` values.

**Mapping to 15 core questions:** Q7 (statistical rigor as one input to
evidence strength, always secondary to economic mechanism per this
module's own explicit ordering).

### 15.19 Addendum — Concrete Decision Thresholds (Filling Narrative Gaps)

The module entries above (5, 6, 7, 8, 13) described real course principles
narratively but did not convert several of them into explicit, codable
thresholds — leaving an implementing agent to guess at numbers the course
actually specified. This addendum closes that gap. **These thresholds are
starting heuristics anchored in the course's qualitative guidance, not
statistically fitted models** — each is explicitly marked for later
calibration against real historical data (Phase 5+), but the *structure*
must exist now so nothing is left undefined.

#### A. Module 6 — Claims Trend Significance (replaces vague "sustained uptrend")

```python
class ClaimsTrendInputs(BaseModel):
    weekly_initial_claims: list[float]   # most recent N weeks, oldest first
    trailing_3mo_avg: float

def claims_trend_signal(inputs: ClaimsTrendInputs) -> ModelResult:
    """
    Converts 'sustained multi-week uptrend, not a single noisy week' into
    an explicit rule: the 4-week moving average must be RISING for at
    least 3 consecutive weeks AND sit more than 5% above the trailing
    3-month average before this is treated as a genuine deterioration
    signal, not noise. Both conditions are configurable
    (config/settings.yaml: labor.claims_consecutive_weeks_threshold=3,
    labor.claims_pct_above_trailing_threshold=0.05) — the 3-week/5%
    starting values are illustrative, calibrate against real historical
    claims data before trusting at size.
    """
    weekly = inputs.weekly_initial_claims
    ma4 = [sum(weekly[i-3:i+1])/4 for i in range(3, len(weekly))]
    consecutive_rising = 0
    for i in range(len(ma4)-1, 0, -1):
        if ma4[i] > ma4[i-1]:
            consecutive_rising += 1
        else:
            break
    latest_ma4 = ma4[-1]
    pct_above_trailing = (latest_ma4 - inputs.trailing_3mo_avg) / inputs.trailing_3mo_avg
    is_signal = consecutive_rising >= 3 and pct_above_trailing > 0.05
    return ModelResult(
        model_name="claims_trend_signal", country="us", as_of=datetime.utcnow(),
        value={"consecutive_weeks_rising": consecutive_rising, "pct_above_trailing": round(pct_above_trailing, 3)},
        confidence=0.6 if is_signal else 0.3,
        interpretation=(
            f"GENUINE deterioration signal: {consecutive_rising} consecutive weeks rising, "
            f"{pct_above_trailing:+.1%} above trailing 3mo avg" if is_signal else
            "Not yet a signal — single-week noise or insufficient sustained rise"
        ),
        context="Threshold: >=3 consecutive rising weeks AND >5% above trailing 3mo avg (configurable, illustrative starting values)",
        inputs_used=["weekly_initial_claims", "trailing_3mo_avg"],
        warnings=["Thresholds are illustrative starting heuristics, not calibrated against historical claims data — Phase 5+ calibration required"],
    )

class ClaimsCorroborationInputs(BaseModel):
    initial_claims_signal: bool     # from claims_trend_signal above
    continuing_claims_rising: bool

def claims_corroboration(inputs: ClaimsCorroborationInputs) -> ModelResult:
    """Rising initial + stable continuing = churn. Rising initial + rising
    continuing = genuine downturn (re-employment difficulty), per Module 6.3."""
    if inputs.initial_claims_signal and inputs.continuing_claims_rising:
        verdict = "genuine_downturn_signal"
        confidence = 0.65
    elif inputs.initial_claims_signal and not inputs.continuing_claims_rising:
        verdict = "churn_not_downturn"
        confidence = 0.4
    else:
        verdict = "no_signal"
        confidence = 0.3
    return ModelResult(
        model_name="claims_corroboration", country="us", as_of=datetime.utcnow(),
        value=verdict, confidence=confidence,
        interpretation=f"Claims pattern: {verdict.replace('_', ' ')}",
        context="Continuing claims add re-employment-speed information initial claims alone cannot (Module 6.3)",
        inputs_used=["initial_claims_signal", "continuing_claims_rising"],
    )
```

#### B. Module 8 — Curve Inversion Duration/Magnitude → Recession Probability Adjustment

```python
class InversionHistoryInputs(BaseModel):
    current_slope_bp: float          # negative = inverted
    weeks_inverted: int
    base_rate_recession_prob_12mo: float = 0.15   # unconditional prior, configurable

def inversion_probability_adjustment(inputs: InversionHistoryInputs) -> ModelResult:
    """
    Converts 'inversions precede recessions by 6-24 months, poor for
    precise timing' into an explicit (illustrative, NOT historically
    fitted) probability adjustment: deeper and more persistent inversions
    add more to the base-rate probability, but the function deliberately
    CAPS the adjustment and never claims precision the course explicitly
    says doesn't exist. This is a placeholder logistic-style heuristic —
    a Phase 5+ item is to replace this with an actual historical
    logistic regression fit (Module 18's regression discipline: economic
    mechanism first, then statistical fit — this heuristic IS the
    mechanism-first placeholder that fit should later replace).
    """
    if inputs.current_slope_bp >= 0:
        return ModelResult(
            model_name="inversion_probability_adjustment", country="us", as_of=datetime.utcnow(),
            value=inputs.base_rate_recession_prob_12mo, confidence=0.3,
            interpretation="Curve not inverted — using unconditional base rate",
            context=f"Slope={inputs.current_slope_bp}bp", inputs_used=["current_slope_bp"],
        )
    depth_factor = min(abs(inputs.current_slope_bp) / 100, 1.0)      # caps at 100bp inversion
    duration_factor = min(inputs.weeks_inverted / 26, 1.0)           # caps at 6 months persistent
    adjustment = 0.35 * depth_factor * duration_factor               # max +35pp adjustment, illustrative
    adjusted_prob = min(inputs.base_rate_recession_prob_12mo + adjustment, 0.80)  # hard ceiling — never claim near-certainty
    return ModelResult(
        model_name="inversion_probability_adjustment", country="us", as_of=datetime.utcnow(),
        value=round(adjusted_prob, 3), confidence=0.35,
        interpretation=f"Recession probability (12mo): {adjusted_prob:.0%} (base {inputs.base_rate_recession_prob_12mo:.0%} + inversion adjustment)",
        context=f"Inverted {inputs.weeks_inverted} weeks at {inputs.current_slope_bp}bp",
        inputs_used=["current_slope_bp", "weeks_inverted"],
        warnings=[
            "ILLUSTRATIVE heuristic, not a fitted historical model — timing remains genuinely uncertain (6-24mo lag per Module 8.1)",
            "Hard-capped at 80% — this system never claims near-certainty about recession timing",
        ],
    )
```

#### C. Module 5 — Inflation Sub-Measure Convergence Classifier (mirrors Module 12's pattern exactly)

```python
class InflationConvergenceInputs(BaseModel):
    headline_cpi_direction: int      # +1 up, -1 down, 0 flat
    core_cpi_direction: int
    core_pce_direction: int
    # Phase 5+ additions once direct BLS/Dallas Fed/Cleveland Fed sources exist:
    supercore_direction: int | None = None
    trimmed_mean_direction: int | None = None
    median_cpi_direction: int | None = None

def inflation_convergence_classifier(inputs: InflationConvergenceInputs) -> ModelResult:
    """
    Explicit HIGH/MEDIUM/LOW/CONFLICTED classifier for inflation
    sub-measures, mirroring Module 12's four-pillar convergence logic
    exactly (Section 6 of the companion data-pipeline project). Phase 1
    only has 3 measures (headline/core CPI/core PCE) — full 6-measure
    breadth (adding supercore/trimmed-mean/median) is Phase 5+ once those
    direct sources are wired in, per Module 5/13's discipline that these
    are NOT available via generic OpenBB series and need dedicated
    BLS/Dallas Fed/Cleveland Fed integration.
    """
    directions = [inputs.headline_cpi_direction, inputs.core_cpi_direction, inputs.core_pce_direction]
    optional = [d for d in [inputs.supercore_direction, inputs.trimmed_mean_direction, inputs.median_cpi_direction] if d is not None]
    all_directions = directions + optional
    n = len(all_directions)
    agree_up = sum(1 for d in all_directions if d > 0)
    agree_down = sum(1 for d in all_directions if d < 0)
    majority = max(agree_up, agree_down)
    frac_agree = majority / n

    if directions[0] * directions[1] < 0:   # headline and core DIRECTLY oppose
        classification = "CONFLICTED"
    elif frac_agree >= 0.8:
        classification = "HIGH"
    elif frac_agree >= 0.6:
        classification = "MEDIUM"
    else:
        classification = "LOW"

    return ModelResult(
        model_name="inflation_convergence_classifier", country="us", as_of=datetime.utcnow(),
        value=classification, confidence=0.5 if n < 6 else 0.7,
        interpretation=f"Inflation sub-measure convergence: {classification} ({majority}/{n} measures agree)",
        context=f"Phase 1: {len(directions)} measures (headline/core CPI/core PCE). Full 6-measure breadth = Phase 5+.",
        inputs_used=["headline_cpi_direction", "core_cpi_direction", "core_pce_direction"],
        warnings=[] if n >= 6 else ["Only 3 of 6 course-specified inflation measures available in Phase 1 — classification confidence capped accordingly"],
    )
```

#### D. Module 13 — Source-Independence Tagging (prevents redundant-evidence false confidence)

```python
class EvidenceSourceFamily(str, Enum):
    BLS_CPI_RELEASE = "bls_cpi_release"          # headline, core, and any BLS-derived sub-measure share this tag
    BEA_PCE_RELEASE = "bea_pce_release"          # core PCE — genuinely separate release infrastructure from BLS CPI
    BLS_LABOR_ESTABLISHMENT = "bls_labor_establishment"   # NFP, AHE
    BLS_LABOR_HOUSEHOLD = "bls_labor_household"           # unemployment rate, participation — separate survey (Module 6.1)
    BLS_DOL_CLAIMS = "bls_dol_claims"            # initial/continuing claims — separate infrastructure again
    BLS_JOLTS = "bls_jolts"                      # openings/quits — yet another separate BLS survey
    MARKET_BASED_TIPS = "market_based_tips"      # breakevens — genuinely independent of ALL government statistical releases
    TREASURY_YIELDS = "treasury_yields"          # curve/term-premium — independent market pricing

def tag_evidence_source(model_result: ModelResult, family: EvidenceSourceFamily) -> ModelResult:
    """Attaches a source-family tag used by the convergence classifier
    (Modules 5, 12, 13) to detect when multiple 'agreeing' signals are
    actually the SAME underlying release counted multiple times — e.g.,
    headline CPI + core CPI + (Phase 5+) trimmed-mean/median/supercore are
    ALL bls_cpi_release — one vote, not five. Core PCE is a genuinely
    separate BEA release = a second, independent vote. TIPS breakevens are
    market-based, entirely independent of any government release = a third
    independent vote. This is the concrete implementation of the
    'redundant vs. independent' distinction this project's own earlier
    conversation identified as the critical nuance in convergence logic."""
    model_result.warnings.append(f"source_family={family.value}")
    return model_result

def count_independent_families(tagged_results: list[ModelResult]) -> int:
    """Extracts source_family tags and returns the count of DISTINCT
    families — this, not the raw count of agreeing ModelResults, is what
    the four-pillar and inflation convergence classifiers should actually
    weight confidence by."""
    families = set()
    for r in tagged_results:
        for w in r.warnings:
            if w.startswith("source_family="):
                families.add(w.split("=")[1])
    return len(families)
```

**Integration requirement:** every convergence-classification function in
this system (Module 5's `inflation_convergence_classifier`, Module 12's
four-pillar classifier, Module 13's evidence-strength logic) must call
`count_independent_families()` on its inputs and treat that count — not
the raw number of agreeing signals — as the actual denominator for
confidence. Five agreeing BLS-CPI-derived sub-measures should never
produce higher confidence than two genuinely independent sources agreeing
(one government release, one market-based signal).

### 15.20 Addendum 2 — Functions Referenced But Never Defined (AUDIT FINDINGS)

A systematic audit found six functions referenced narratively (in some
cases **by name, as if they already existed**) but never actually
specified as code. All are defined here. Phase assignment is noted per
function — several belong to already-completed phases and must be
retroactively backfilled.

#### A. Module 1 — Trilemma Check (referenced by name in Section 15 Module 1 AND Section 18.1's Black Wednesday detection rule, never defined) — **Phase 2 backfill**

```python
# src/macro_engine/models/regime.py (addition)

class TrilemmaInputs(BaseModel):
    country: str
    has_fixed_or_managed_fx: bool
    has_free_capital_movement: bool
    claims_monetary_independence: bool
    domestic_policy_direction_needed: str | None = None   # "easing" | "tightening" | None
    peg_defense_direction_required: str | None = None      # "easing" | "tightening" | None
    reserves_trend_pct_change_3mo: float | None = None     # negative = depleting

def check_trilemma_tension(inputs: TrilemmaInputs) -> ModelResult:
    """
    Module 1's trilemma: fixed FX + free capital + independent monetary
    policy = impossible simultaneously. Flags any country claiming all
    three, and escalates when domestic needs CONTRADICT peg-defense needs
    while reserves are depleting — the exact Black Wednesday setup
    (Section 18.1) and the Asian Crisis mechanism (Section 18.7).
    """
    all_three = (inputs.has_fixed_or_managed_fx and inputs.has_free_capital_movement
                 and inputs.claims_monetary_independence)
    direction_conflict = (
        inputs.domestic_policy_direction_needed is not None
        and inputs.peg_defense_direction_required is not None
        and inputs.domestic_policy_direction_needed != inputs.peg_defense_direction_required
    )
    reserves_depleting = (inputs.reserves_trend_pct_change_3mo or 0) < -0.10

    if all_three and direction_conflict and reserves_depleting:
        severity, confidence = "CRITICAL_PEG_STRESS", 0.7
    elif all_three and direction_conflict:
        severity, confidence = "TRILEMMA_VIOLATION", 0.6
    elif all_three:
        severity, confidence = "TRILEMMA_TENSION", 0.4
    else:
        severity, confidence = "NO_TENSION", 0.8

    return ModelResult(
        model_name="check_trilemma_tension", country=inputs.country, as_of=datetime.utcnow(),
        value=severity, confidence=confidence,
        interpretation=f"Trilemma status for {inputs.country}: {severity}",
        context=(f"fixed_fx={inputs.has_fixed_or_managed_fx}, free_capital={inputs.has_free_capital_movement}, "
                 f"claims_independence={inputs.claims_monetary_independence}, direction_conflict={direction_conflict}, "
                 f"reserves_3mo={inputs.reserves_trend_pct_change_3mo}"),
        inputs_used=["has_fixed_or_managed_fx", "has_free_capital_movement", "claims_monetary_independence"],
        warnings=["CRITICAL_PEG_STRESS matches the Black Wednesday / Asian Crisis setup — treat any FX thesis on this currency with extreme caution"] if severity == "CRITICAL_PEG_STRESS" else [],
    )
```

#### B. Module 9 — EM Vulnerability Checklist (described narratively 3+ times, never coded) — **Phase 5+ (needs IMF/World Bank data)**

```python
# src/macro_engine/models/fx_carry.py (addition)

class EMVulnerabilityInputs(BaseModel):
    country: str
    current_account_pct_gdp: float          # negative = deficit = vulnerable
    usd_denominated_debt_share: float       # 0-1, higher = more "original sin" exposure
    reserves_to_short_term_external_debt: float   # <1.0 = cannot cover ST debt from reserves

def em_vulnerability_checklist(inputs: EMVulnerabilityInputs) -> ModelResult:
    """
    Module 9.4's three structural vulnerabilities as an explicit check.
    Per the course's explicit rule: MULTIPLE FAILING CHECKS OVERRIDE any
    favorable statistical/cointegration/carry signal — this function's
    output must gate FX instrument selection, not merely inform it.
    Thresholds are configurable; defaults below are conventional EM-stress
    benchmarks, not fitted values.
    """
    failures = []
    if inputs.current_account_pct_gdp < -0.03:
        failures.append("current_account_deficit_exceeds_3pct_gdp")
    if inputs.usd_denominated_debt_share > 0.50:
        failures.append("majority_usd_denominated_debt_original_sin")
    if inputs.reserves_to_short_term_external_debt < 1.0:
        failures.append("reserves_below_short_term_external_debt")

    n = len(failures)
    verdict = {0: "LOW_VULNERABILITY", 1: "MODERATE_VULNERABILITY",
               2: "HIGH_VULNERABILITY", 3: "CRITICAL_VULNERABILITY"}[n]
    return ModelResult(
        model_name="em_vulnerability_checklist", country=inputs.country, as_of=datetime.utcnow(),
        value={"verdict": verdict, "failed_checks": failures, "n_failed": n},
        confidence=0.65,
        interpretation=f"{inputs.country}: {verdict} ({n}/3 checks failed)",
        context="Module 9.4 three-factor structural vulnerability framework",
        inputs_used=["current_account_pct_gdp", "usd_denominated_debt_share", "reserves_to_short_term_external_debt"],
        warnings=["2+ failing checks OVERRIDE any favorable carry/cointegration signal — do not size an FX position against this"] if n >= 2 else [],
    )
```

#### C. Module 17.1 — Portfolio Variance & Risk Contribution (the core correlation math) — **Phase 4 backfill**

```python
# src/macro_engine/portfolio/risk_budget.py (addition)

class TwoAssetPortfolioInputs(BaseModel):
    w1: float
    w2: float
    vol1: float
    vol2: float
    correlation: float

def portfolio_volatility_two_asset(inputs: TwoAssetPortfolioInputs) -> ModelResult:
    """
    sigma_p^2 = w1^2*sigma1^2 + w2^2*sigma2^2 + 2*w1*w2*rho*sigma1*sigma2
    The cross term is the whole point: rho=1 gives no diversification
    benefit; rho=0 makes portfolio vol meaningfully lower than the sum of
    parts; rho<0 lowers it further (Module 17.1).
    """
    var_p = (inputs.w1**2 * inputs.vol1**2
             + inputs.w2**2 * inputs.vol2**2
             + 2 * inputs.w1 * inputs.w2 * inputs.correlation * inputs.vol1 * inputs.vol2)
    vol_p = var_p ** 0.5
    return ModelResult(
        model_name="portfolio_volatility_two_asset", country="us", as_of=datetime.utcnow(),
        value=round(vol_p, 6), confidence=0.9,
        interpretation=f"Portfolio volatility: {vol_p:.2%} (vs weighted-sum-of-parts {inputs.w1*inputs.vol1 + inputs.w2*inputs.vol2:.2%})",
        context=f"rho={inputs.correlation} — diversification benefit exists only because rho < 1",
        inputs_used=["w1", "w2", "vol1", "vol2", "correlation"],
        warnings=["Correlation is an ESTIMATE that rises toward 1 in crisis — stress-test at rho=0.6 and rho=0.9 before sizing (Module 17.1 LTCM lesson)"],
    )

def portfolio_volatility_n_asset(weights: "np.ndarray", cov_matrix: "np.ndarray") -> ModelResult:
    """Full matrix form: sigma_p = sqrt(w' @ Sigma @ w)"""
    import numpy as np
    var_p = float(weights.T @ cov_matrix @ weights)
    vol_p = var_p ** 0.5
    return ModelResult(
        model_name="portfolio_volatility_n_asset", country="us", as_of=datetime.utcnow(),
        value=round(vol_p, 6), confidence=0.9,
        interpretation=f"Portfolio volatility (n-asset): {vol_p:.2%}",
        context="Full covariance-matrix form", inputs_used=["weights", "cov_matrix"],
        warnings=["Covariance matrix is backward-looking — see stress-correlation variants"],
    )

def marginal_risk_contributions(weights: "np.ndarray", cov_matrix: "np.ndarray") -> ModelResult:
    """
    RC_i = w_i * (Sigma @ w)_i / sigma_p  — each position's share of TOTAL
    portfolio risk. This, not dollar notional, is what risk budgeting
    actually allocates (Module 17.1's core principle: a high-vol instrument
    gets a SMALLER notional to contribute the same risk as a low-vol one).
    """
    import numpy as np
    vol_p = float((weights.T @ cov_matrix @ weights) ** 0.5)
    marginal = cov_matrix @ weights
    rc = (weights * marginal) / vol_p
    rc_pct = rc / rc.sum()
    return ModelResult(
        model_name="marginal_risk_contributions", country="us", as_of=datetime.utcnow(),
        value={"risk_contributions": rc.tolist(), "risk_contribution_pct": rc_pct.tolist()},
        confidence=0.85,
        interpretation="Per-position share of total portfolio risk (sums to 100%)",
        context="Dollar weights and RISK weights differ — a 40% dollar position can be 60% of risk (Module 17.1)",
        inputs_used=["weights", "cov_matrix"],
    )
```

#### D. Module 10 — Gold Three-Layer Framework (taught in depth, never coded) — **Phase 5+, informational only**

```python
# src/macro_engine/models/commodities.py (addition)

class GoldDriverInputs(BaseModel):
    real_yield_change_bp: float           # 10yr TIPS yield change — PRIMARY driver
    central_bank_net_purchases_trend: str  # "rising" | "flat" | "falling"
    crisis_indicator: bool                 # VIX spike / credit blowout / confidence event

def gold_driver_attribution(inputs: GoldDriverInputs) -> ModelResult:
    """
    Module 10.2's three-layer framework. Gold is a REAL-YIELD and
    CONFIDENCE hedge, NOT a simple inflation hedge — the single most
    important correction this module teaches. Attributes which layer is
    likely dominating, because each implies different DURABILITY:
      - real-yield-driven  -> mechanical, reverses if real yields reverse
      - CB-diversification -> slow, structural, durable
      - crisis-driven      -> sharp, often reverses when the acute phase passes
    INFORMATIONAL ONLY — commodities are outside this system's production
    trading universe (Section 6.8).
    """
    layers = []
    if abs(inputs.real_yield_change_bp) > 10:
        layers.append(("real_yield", "primary — mechanical opportunity-cost channel, reverses with real yields"))
    if inputs.central_bank_net_purchases_trend == "rising":
        layers.append(("cb_diversification", "structural — slow, durable, geopolitically motivated"))
    if inputs.crisis_indicator:
        layers.append(("crisis_confidence", "acute — sharp move, often reverses post-crisis"))

    dominant = layers[0][0] if layers else "none_identified"
    return ModelResult(
        model_name="gold_driver_attribution", country="global", as_of=datetime.utcnow(),
        value={"dominant_layer": dominant, "active_layers": [name for name, _ in layers]},
        confidence=0.35,
        interpretation=f"Gold move most likely driven by: {dominant}",
        context="Real yields primary; CB diversification structural; crisis demand acute. NOT an inflation hedge per se (Module 10.2)",
        inputs_used=["real_yield_change_bp", "central_bank_net_purchases_trend", "crisis_indicator"],
        warnings=["INFORMATIONAL ONLY — no commodity positions in this system's production universe",
                  "If gold rises WHILE real yields rise, the real-yield model is not dominating — check CB/crisis layers"],
    )
```

#### E. Module 11 — Factor Tilt Engine (in the mapping table, never coded) — **Phase 5+**

```python
# src/macro_engine/models/equity_macro.py (addition)

FACTOR_REGIME_MAP = {
    "early_expansion":  {"value": 1.0, "momentum": 0.5, "quality": -0.5, "low_vol": -1.0, "size": 0.5},
    "mid_expansion":    {"value": 0.0, "momentum": 1.0, "quality": 0.0,  "low_vol": -0.5, "size": 0.0},
    "late_expansion":   {"value": 0.5, "momentum": 0.5, "quality": 0.5,  "low_vol": 0.5,  "size": -0.5},
    "slowdown":         {"value": -0.5,"momentum": -0.5,"quality": 1.0,  "low_vol": 1.0,  "size": -1.0},
    "recession":        {"value": -0.5,"momentum": -1.0,"quality": 1.0,  "low_vol": 1.0,  "size": -1.0},
    "recovery":         {"value": 1.0, "momentum": 0.0, "quality": -0.5, "low_vol": -1.0, "size": 1.0},
    "disinflation":     {"value": 0.0, "momentum": 0.5, "quality": 0.5,  "low_vol": 0.0,  "size": 0.0},
    "reflation":        {"value": 1.0, "momentum": 0.5, "quality": -0.5, "low_vol": -0.5, "size": 0.5},
    "stagflation":      {"value": 0.5, "momentum": -0.5,"quality": 1.0,  "low_vol": 0.5,  "size": -1.0},
}

def factor_tilt_prior(regime_state: str) -> ModelResult:
    """
    Regime-conditional factor tilts (-1 underweight .. +1 overweight),
    Module 11.2. Like sector rotation, these are BASE-RATE PRIORS from
    historical regime behavior, NOT mechanical rules — momentum
    specifically is prone to sharp reversals ("momentum crashes") at
    genuine regime turns, which is exactly when a prior like this is
    least reliable.
    """
    tilts = FACTOR_REGIME_MAP.get(regime_state)
    if tilts is None:
        return ModelResult(
            model_name="factor_tilt_prior", country="us", as_of=datetime.utcnow(),
            value={}, confidence=0.0,
            interpretation=f"No factor prior defined for regime '{regime_state}'",
            context="Unknown regime — no tilt applied", inputs_used=["regime_state"],
            warnings=[f"Regime '{regime_state}' not in FACTOR_REGIME_MAP"],
        )
    return ModelResult(
        model_name="factor_tilt_prior", country="us", as_of=datetime.utcnow(),
        value=tilts, confidence=0.35,
        interpretation=f"Factor tilts for '{regime_state}': " + ", ".join(f"{k} {v:+.1f}" for k, v in tilts.items()),
        context="Base-rate priors from historical regime behavior — NOT mechanical rules (Module 11.2)",
        inputs_used=["regime_state"],
        warnings=["Momentum tilts are least reliable precisely at regime turns (momentum crashes) — the moment this prior matters most is when it's weakest"],
    )
```

#### F. Module 18 — Regression / Stationarity / Cointegration Stubs (formulas in prose only, no callable signatures) — **Phase 5+**

```python
# src/macro_engine/models/econometrics.py (NEW FILE, Phase 5+)

class RegressionResult(ModelResult):
    beta: dict[str, float]
    r_squared: float
    adj_r_squared: float
    p_values: dict[str, float]
    n_obs: int
    multicollinearity_vif: dict[str, float] | None = None

def run_regression(y: "pd.Series", X: "pd.DataFrame", require_mechanism: str) -> RegressionResult:
    """
    statsmodels OLS wrapper. `require_mechanism` is a MANDATORY free-text
    field documenting the economic mechanism hypothesized BEFORE fitting —
    Module 18's explicit discipline (mechanism first, statistics second).
    A caller that cannot articulate a mechanism should not be running the
    regression. Low R² is reported as information, not failure.
    """
    raise NotImplementedError("Phase 5+ — requires statsmodels")

def test_stationarity(series: "pd.Series") -> ModelResult:
    """
    Runs BOTH ADF (H0: unit root / non-stationary) and KPSS (H0: stationary)
    — their nulls are INVERTED, so professionals run both and check they
    agree. Disagreement between them is itself informative (inconclusive),
    not something to resolve by picking the convenient one.
    """
    raise NotImplementedError("Phase 5+ — requires statsmodels")

def test_cointegration(y: "pd.Series", x: "pd.Series", method: str = "engle_granger") -> ModelResult:
    """
    Engle-Granger (regress y on x, ADF the residuals) or Johansen.
    MUST return, alongside the test statistic: the spread series, its
    estimated half-life of mean reversion, and a regime-stability check.
    MUST warn that cointegration is a BACKWARD-LOOKING estimate that
    breaks in regime change (LTCM), and that multiple pairwise tests
    without a multiple-testing correction produce false positives at
    roughly the nominal rate.
    """
    raise NotImplementedError("Phase 5+ — requires statsmodels")

def compute_pca(daily_changes: "pd.DataFrame", n_components: int = 3) -> ModelResult:
    """
    scikit-learn PCA on DAILY CHANGES, never raw levels (levels are
    trend-dominated and produce a misleading PC1). Returns eigenvalues,
    explained variance ratios, and LOADINGS — components must be
    interpreted from loadings, never auto-labeled as level/slope/curvature.
    """
    raise NotImplementedError("Phase 5+ — requires scikit-learn")

def kalman_latent_state(observations: "pd.DataFrame", state_dim: int = 1) -> ModelResult:
    """
    statsmodels.tsa.statespace (NEVER pykalman — unmaintained since ~2015).
    For estimating unobservable time-varying states: r*, potential GDP,
    time-varying hedge ratios for cointegrated pairs. MUST return the
    filtered state WITH its uncertainty band — the filtered state is an
    estimate, never to be presented as observed truth.
    """
    raise NotImplementedError("Phase 5+ — requires statsmodels")
```



---

## 16. Thesis Construction Algorithm (Module 14) — Detailed

### 16.1 The Core Discipline Sentence, Field-by-Field

> *"I think [policy variable] will move by more than the market has priced,
> on this timeframe, expressed through this instrument, sized according to
> my conviction and the asymmetry of the payoff, with this stop and this
> catalyst calendar."*

| Sentence fragment | `MacroThesis` field |
|---|---|
| "I think [policy variable] will move" | `policy_view`, `growth_view`, `inflation_view` |
| "by more than the market has priced" | `market_pricing_gap.raw_gap` |
| "on this timeframe" | `trade_idea.timeframe` |
| "expressed through this instrument" | `trade_idea.instrument` |
| "sized according to my conviction" | `trade_idea.sizing_logic` (Phase 1: human; Phase 4+: fractional Kelly via `portfolio/risk_budget.py`) |
| "and the asymmetry of the payoff" | `scenario_distribution` (explicit upside/downside/tail payoffs) |
| "with this stop" | `trade_idea.stop_or_invalidation` |
| "and this catalyst calendar" | `trade_idea.catalysts` |

### 16.2 Full Algorithm — the 15 Core Questions, Answered Field-by-Field

```python
def build_us_macro_thesis(snapshot: MacroDataSnapshot) -> MacroThesis:
    # Q1: What is happening in the economy?
    growth = output_gap(...)              # Module 7
    inflation = inflation_breadth_score(...)  # Module 5
    labor = labor_tightness_score(...)     # Module 6
    regime = classify_regime_rule_based(...)  # Module 3/4

    # Q2: What is likely to happen next?
    #   Phillips Curve forecast (Module 3) using growth.value + labor.value
    #   as (u - u*) and (y - y*) proxies feeding an inflation trajectory view.
    inflation_forecast = project_inflation_trajectory(growth, labor, inflation)

    # Q3 & Q4: What does the market currently expect / what is already priced?
    market_implied = derive_market_implied_policy_path(snapshot.yield_curve)  # Module 8

    # Q5: Where does our estimate differ from market pricing?
    taylor = taylor_rule(...); balanced = balanced_approach_rule(...); fd = first_difference_rule(...)
    ensemble = policy_rule_ensemble(taylor, balanced, fd)  # Module 4 — never averaged blindly
    gap = MarketPricingGap(
        model_implied_value=ensemble["rules"]["taylor"],  # or ensemble midpoint, documented choice
        market_implied_value=market_implied,
        raw_gap=ensemble["rules"]["taylor"] - market_implied,
        unit="%",
        interpretation="..."
    )

    # Q6: Is the difference economically meaningful?
    #   Rule: |raw_gap| must exceed ensemble["dispersion"] to be treated as
    #   meaningful, NOT an arbitrary bp threshold — the rules' own
    #   disagreement sets the noise floor (Module 4's explicit caveat).
    is_meaningful = abs(gap.raw_gap) > ensemble["dispersion"]
    if not is_meaningful:
        return no_trade_thesis(reason="Gap does not exceed policy-rule dispersion — insufficient signal-to-noise")

    # Q7: How strong and independent is the evidence?
    convergence = classify_convergence([growth, inflation, labor, gap])  # Module 12/13
    if convergence == "CONFLICTED":
        return no_trade_thesis(reason="Growth/inflation/policy signals directly contradict — Module 12 dual-mandate-tension pattern")

    # Q8: What could invalidate the thesis?
    invalidation = derive_invalidation_conditions(growth, inflation, labor)  # Module 14 evidence-based stop, NOT price-based

    # Q9: What is the cleanest instrument to express the view?
    instrument = select_instrument(gap, regime)  # Module 15

    # Q10: What is the expected distribution of outcomes?
    scenarios = build_scenario_distribution(gap, convergence)  # Module 12 Monte Carlo (Phase 1: explicit 3-4 scenario set)

    # Q11: How much risk should be taken?
    sizing_logic = "Phase 1: human-determined; Phase 4+: fractional_kelly(scenarios, confidence)"  # Module 12/17

    # Q12: What portfolio exposures already exist?
    #   Phase 4+ hook: check current portfolio's factor loadings (PCA, Module 18)
    #   before finalizing sizing — avoid hidden concentration (Module 17.1).
    portfolio_check = "Phase 4+ — see portfolio/risk_budget.py"

    # Q13: Under what scenarios does the trade lose?
    #   Already populated in `scenarios` — explicit negative-payoff entries required.

    # Q14: When should the position be exited?
    #   Encoded as `invalidation` (evidence-based) OR gap-closure (thesis resolved).

    # Q15: Is the correct answer actually NO TRADE?
    #   Checked explicitly at Q6 and Q7 above — NO TRADE is a first-class,
    #   reachable code path, not a fallback for missing data.

    return MacroThesis(
        thesis_id=generate_id(), country="us", created_at=datetime.utcnow(),
        regime={"state": regime.value, "confidence": regime.confidence},
        growth_view={"output_gap": growth.value, ...},
        inflation_view={"breadth_score": inflation.value, ...},
        policy_view=ensemble,
        market_pricing_gap=gap,
        confirmation_signals=build_confirmation_signals(growth, inflation, labor, gap),
        convergence_classification=convergence,
        trade_idea=TradeIdea(
            instrument=instrument, direction="long" if gap.raw_gap < 0 else "short",
            timeframe="6-12 months", sizing_logic=sizing_logic,
            stop_or_invalidation=invalidation,
            catalysts=next_catalyst_calendar(),  # official sources only, per Module 13/companion pipeline
        ),
        scenario_distribution=scenarios,
        status=ThesisStatus.DRAFT,
        warnings=collect_all_warnings(growth, inflation, labor, gap),
    )

def no_trade_thesis(reason: str) -> MacroThesis:
    """NO TRADE is a first-class, fully-formed MacroThesis — not an
    exception, not a null return. Module 14's explicit teaching: prefer
    fewer high-quality decisions; correctly identifying 'no clean edge
    exists right now' is itself a valuable output, not a failure to answer."""
    return MacroThesis(
        thesis_id=generate_id(), country="us", created_at=datetime.utcnow(),
        trade_idea=TradeIdea(
            instrument="NONE", direction="n/a", timeframe="n/a",
            sizing_logic="No position — see warnings for reason",
            stop_or_invalidation="n/a", catalysts=[],
        ),
        status=ThesisStatus.WATCH,
        warnings=[reason],
        # other fields populated with whatever partial view was formed,
        # so a human can still see WHY the system concluded no-trade
    )
```

### 16.3 Why "NO TRADE" Is Architecturally First-Class, Not an Afterthought

### 22.10 Resolves Finding #10 — Code Correctness Fixes

```python
def classify_convergence(signals: list[ModelResult]) -> str:
    """
    CORRECTED per Finding #10 — no longer uses signals[0] as an arbitrary
    reference. Extracts each signal's DIRECTION explicitly (positive/
    negative/neutral), ignores neutral signals when computing agreement
    (a neutral signal is not evidence for either direction), and only
    flags CONFLICTED when a genuine directional opposition exists among
    NON-neutral signals.
    """
    directions = []
    for s in signals:
        v = s.value if isinstance(s.value, (int, float)) else None
        if v is None:
            continue
        directions.append(1 if v > 0 else (-1 if v < 0 else 0))
    non_neutral = [d for d in directions if d != 0]
    if not non_neutral:
        return "NO_SIGNAL"
    has_pos, has_neg = any(d > 0 for d in non_neutral), any(d < 0 for d in non_neutral)
    if has_pos and has_neg:
        return "CONFLICTED"
    agree_frac = max(sum(1 for d in non_neutral if d > 0), sum(1 for d in non_neutral if d < 0)) / len(non_neutral)
    return "HIGH" if agree_frac >= 0.8 else "MEDIUM" if agree_frac >= 0.6 else "LOW"

```

**Additional corrections mandated system-wide:**

- Replace every `datetime.utcnow()` with `datetime.now(timezone.utc)` — `utcnow()` is deprecated and returns a naive datetime, violating this document's own "always explicit tz info" rule (Section 10B).
- Every function signature must match its documented input schema exactly — any drift found during implementation is a `docs/DECISIONS.md` entry, not a silent adjustment.
- No function may reference a schema field that its `MacroThesis`/`ModelResult` parent does not actually declare — verified by a dedicated schema-consistency test (add `test_all_field_references_exist_in_schema` to the Phase 3 suite).

---

### 22.12 Resolves Finding #12 — One Explicit Boundary Rule: Analytical Universe ≠ Production Universe

> **This is the single rule governing every instrument reference in this
> document.** The **analytical asset universe** — everything this system
> is permitted to model, discuss, and reason about for macro understanding
> — includes CDS, HY/IG credit spreads, hard-currency and local-currency
> EM bonds, and commodities. The **production execution universe** —
> everything `TradeIdea.instrument` is permitted to actually contain — is
> **exclusively FX spot/forwards, sovereign rates instruments, and broad
> equity indices** (unchanged from CLAUDE.md Section 5's original
> boundary). **A thesis whose cleanest analytical expression is a credit
> or EM-bond instrument does not get a substitute production instrument
> assigned to it — it returns** **`ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT`**
> (Section 22.3.1's corrected `select_instrument()` already implements
> this). Module 15's CDS/HY-IG/EM-bond content remains in this document
> as course-derived analytical knowledge informing the system's
> understanding of credit and EM mechanics — it must never leak into an
> actual `TradeIdea.instrument` value.

---


Two explicit code paths return `no_trade_thesis()` above — insufficient
gap-vs-dispersion (Q6) and CONFLICTED convergence (Q7) — rather than the
system defaulting to *some* trade idea whenever models successfully run.
This directly encodes Module 14's discipline: a macro view only becomes a
trade after surviving every filter; failing any filter is a **valid,
loggable, reviewable outcome**, tracked the same way an active thesis is
(same schema, `status=WATCH`, same warnings-transparency), rather than
silently discarded.

---

### 16.4 Helper Functions Called by `build_us_macro_thesis()` — MISSING FROM ORIGINAL SPEC, ADDED HERE

#### 22.3.1 Corrected `select_instrument()` — Real Branching, Not a Single Fallback

```python
# src/macro_engine/models/instrument_selection.py (NEW FILE) — Phase 3, corrects Section 16.2's placeholder

class ThesisType(str, Enum):
    POLICY_PATH_GAP = "policy_path_gap"
    CURVE_SHAPE_GAP = "curve_shape_gap"
    CROSS_COUNTRY_DIVERGENCE = "cross_country_divergence"      # BLOCKED in Phase 1-4 (US-only)
    INFLATION_EXPECTATIONS_GAP = "inflation_expectations_gap"
    CREDIT_QUALITY_GAP = "credit_quality_gap"                   # analytical only, see 22.12
    EM_VULNERABILITY = "em_vulnerability"                        # BLOCKED in Phase 1-4 (US-only)
    EQUITY_MACRO = "equity_macro"

class InstrumentSelectionInputs(BaseModel):
    thesis_type: ThesisType
    gap_direction: str          # "positive" | "negative"
    curve_short_tenor: str | None = None
    curve_long_tenor: str | None = None

PRODUCTION_UNIVERSE = {"fx", "rates", "equity_index"}   # Section 22.12 — the hard boundary

def select_instrument(inputs: InstrumentSelectionInputs) -> ModelResult:
    """
    Explicit branch per Module 15's actual instrument-selection table
    (Section 15, Module 15 entry) — never a single fallback instrument.
    Every branch checks PRODUCTION_UNIVERSE membership before returning;
    a thesis type whose natural instrument sits outside FX/rates/equity
    indices returns an explicit ANALYTICAL_ONLY verdict, never silently
    substituting a production instrument for a different risk (Section 22.12).
    """
    if inputs.thesis_type == ThesisType.POLICY_PATH_GAP:
        instrument, universe = "UST 2yr note futures", "rates"
        rationale = "Most directly sensitive to expected policy path (Module 8 expectations component); avoids 30yr term-premium noise"
    elif inputs.thesis_type == ThesisType.CURVE_SHAPE_GAP:
        instrument = f"Duration-weighted {inputs.curve_short_tenor}/{inputs.curve_long_tenor} steepener/flattener"
        universe, rationale = "rates", "Isolates slope from level via duration weighting (Module 15.1)"
    elif inputs.thesis_type == ThesisType.INFLATION_EXPECTATIONS_GAP:
        instrument, universe = "Duration-matched TIPS long / nominal short (breakeven trade)", "rates"
        rationale = "Isolates inflation expectations from real-yield direction (Module 15.2)"
    elif inputs.thesis_type == ThesisType.EQUITY_MACRO:
        instrument, universe = "Broad equity index (per Section 6.9 duration/sector logic)", "equity_index"
        rationale = "No single-stock exposure (production universe boundary)"
    elif inputs.thesis_type == ThesisType.CROSS_COUNTRY_DIVERGENCE:
        return ModelResult(
            model_name="select_instrument", country="us", as_of=datetime.utcnow(),
            value="BLOCKED_MULTI_COUNTRY_NOT_BUILT", confidence=0.0,
            interpretation="Cross-country RV instrument selection requires a second country's rates system — not implemented in Phase 1-4",
            context="This system is genuinely US-only through Phase 4 (Section 22.3)", inputs_used=["thesis_type"],
            warnings=["Do not fabricate a cross-market RV trade against an unbuilt country system"],
        )
    elif inputs.thesis_type in (ThesisType.CREDIT_QUALITY_GAP, ThesisType.EM_VULNERABILITY):
        return ModelResult(
            model_name="select_instrument", country="us", as_of=datetime.utcnow(),
            value="ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT", confidence=0.0,
            interpretation=f"{inputs.thesis_type.value} is outside the production execution universe (FX/rates/equity indices only)",
            context="Section 22.12: analytical asset universe != production execution universe. CDS/HY-IG spreads/EM bonds are discussed for macro understanding only.",
            inputs_used=["thesis_type"],
            warnings=["This thesis type cannot produce a TradeIdea.instrument in this system by design"],
        )
    else:
        raise ValueError(f"Unhandled thesis_type: {inputs.thesis_type}")

    assert universe in PRODUCTION_UNIVERSE, "select_instrument must never return outside the production universe"
    return ModelResult(
        model_name="select_instrument", country="us", as_of=datetime.utcnow(),
        value={"instrument": instrument, "universe": universe}, confidence=0.7,
        interpretation=f"Selected: {instrument}",
        context=rationale, inputs_used=["thesis_type", "gap_direction"],
    )

```

---


**Section 16.2's algorithm called these functions in its pseudocode without
ever defining them. If Phase 3 is already built, the coding agent almost
certainly invented its own versions to make the code run — those invented
versions must now be checked against the real implementations below and
corrected if they diverge.**

```python
# src/macro_engine/models/bond_math.py — NEW, needed as an input to
# construct_duration_weighted_curve_trade / construct_breakeven_trade
# (Section 15.1b), which require duration numbers with no prior way to
# compute them. This is Module 2's actual bond math, never coded before.

class BondPricingInputs(BaseModel):
    face_value: float
    coupon_rate: float      # annual, decimal (e.g. 0.06)
    yield_rate: float       # annual required yield, decimal
    periods: int            # number of coupon periods to maturity

def price_bond(inputs: BondPricingInputs) -> ModelResult:
    """Price = Σ[C/(1+y)^t] + F/(1+y)^n — Module 2's multi-period formula."""
    c = inputs.face_value * inputs.coupon_rate
    y = inputs.yield_rate
    price = sum(c / (1 + y) ** t for t in range(1, inputs.periods + 1)) + inputs.face_value / (1 + y) ** inputs.periods
    return ModelResult(
        model_name="price_bond", country="us", as_of=datetime.utcnow(),
        value=round(price, 2), confidence=1.0,   # pure arithmetic, no estimation
        interpretation=f"Bond price: {price:.2f} ({'premium' if price > inputs.face_value else 'discount'} to face value)",
        context=f"Face={inputs.face_value}, coupon={inputs.coupon_rate:.2%}, yield={y:.2%}, periods={inputs.periods}",
        inputs_used=["face_value", "coupon_rate", "yield_rate", "periods"],
    )

def macaulay_duration(inputs: BondPricingInputs) -> ModelResult:
    """MacDur = Σ[t × PV(CFt)] / Price"""
    c = inputs.face_value * inputs.coupon_rate
    y = inputs.yield_rate
    price = sum(c / (1 + y) ** t for t in range(1, inputs.periods + 1)) + inputs.face_value / (1 + y) ** inputs.periods
    weighted = sum(t * (c / (1 + y) ** t) for t in range(1, inputs.periods)) \
        + inputs.periods * ((c + inputs.face_value) / (1 + y) ** inputs.periods)
    mac_dur = weighted / price
    return ModelResult(
        model_name="macaulay_duration", country="us", as_of=datetime.utcnow(),
        value=round(mac_dur, 3), confidence=1.0,
        interpretation=f"Macaulay Duration: {mac_dur:.3f} years",
        context=f"Bond price={price:.2f}", inputs_used=["face_value", "coupon_rate", "yield_rate", "periods"],
    )

def modified_duration(mac_dur: float, yield_rate: float) -> ModelResult:
    """ModDur = MacDur / (1 + y) — what curve/breakeven trade construction actually needs."""
    mod_dur = mac_dur / (1 + yield_rate)
    return ModelResult(
        model_name="modified_duration", country="us", as_of=datetime.utcnow(),
        value=round(mod_dur, 3), confidence=1.0,
        interpretation=f"Modified Duration: {mod_dur:.3f} — 1% yield rise ≈ {mod_dur:.2f}% price fall",
        context=f"MacDur={mac_dur}, yield={yield_rate:.2%}", inputs_used=["mac_dur", "yield_rate"],
    )
```

```python
# src/macro_engine/thesis_layer/builder.py — the 10 previously-undefined
# helper functions, now implemented

def project_inflation_trajectory(growth: ModelResult, labor: ModelResult, inflation: ModelResult) -> ModelResult:
    """Module 3's Phillips Curve: π = π^e − β(u − u*). Uses labor.value (as a
    (u-u*) proxy, since labor_tightness_score is signed the same direction)
    and current inflation trend to project forward direction — NOT a point
    forecast, a directional trajectory with confidence."""
    beta = 0.3  # illustrative sensitivity, configurable — Phase 5+ should
                # replace with a regression-estimated beta (Module 18)
    labor_slack_proxy = -labor.value / 100  # tightness score sign-flipped: negative score (loose) -> positive slack
    projected_change = -beta * labor_slack_proxy
    direction = "reaccelerating" if projected_change > 0.05 else "decelerating" if projected_change < -0.05 else "stable"
    return ModelResult(
        model_name="project_inflation_trajectory", country="us", as_of=datetime.utcnow(),
        value=round(projected_change, 3), confidence=0.35,
        interpretation=f"Inflation trajectory: {direction} (Phillips Curve projection using labor slack proxy)",
        context="Illustrative beta=0.3, NOT regression-fitted — Phase 5+ should calibrate against real historical Phillips Curve slope",
        inputs_used=["labor.value", "inflation.value"],
        warnings=["Phillips Curve beta is an illustrative placeholder, not empirically estimated"],
    )

def derive_market_implied_policy_path(yield_curve: YieldCurveSnapshot) -> float:
    """Phase 1 crude proxy: use the 2yr yield as a stand-in for the
    market's expected average policy rate over the near term (front-end
    yields are dominated by the expectations component, Module 8.1). This
    is explicitly NOT a full Fed-funds-futures-implied probability
    distribution (Section 6's known limitation) — replace with a genuine
    futures-derived path once that data source is confirmed available."""
    return yield_curve.tenors.get("2yr", yield_curve.tenors.get("1yr", 0.0))

def classify_convergence(signals: list[ModelResult]) -> str:
    """The GENERAL four-pillar convergence classifier (Module 12), distinct
    from inflation_convergence_classifier (Module 5, Section 15.19-C) which
    only checks inflation sub-measures. This checks agreement ACROSS
    growth/inflation/policy-gap direction. Uses count_independent_families
    (Section 15.19-D) as the actual weighting mechanism, not raw count."""
    independent_family_count = count_independent_families(signals)
    directions = [1 if isinstance(s.value, (int, float)) and s.value > 0 else
                  -1 if isinstance(s.value, (int, float)) and s.value < 0 else 0
                  for s in signals]
    if any(directions[i] * directions[j] < 0 for i in range(len(directions)) for j in range(i+1, len(directions))):
        return "CONFLICTED"
    agree_count = sum(1 for d in directions if d == directions[0] and d != 0)
    frac = agree_count / len(directions) if directions else 0
    if frac >= 0.8 and independent_family_count >= 3:
        return "HIGH"
    elif frac >= 0.6 and independent_family_count >= 2:
        return "MEDIUM"
    else:
        return "LOW"

def derive_invalidation_conditions(growth: ModelResult, inflation: ModelResult, labor: ModelResult) -> str:
    """Evidence-based, NOT price-based (Module 14's explicit thesis-
    invalidation-vs-price-stop distinction). Builds a plain-language
    condition string from whichever signals most directly support the
    current thesis direction."""
    conditions = []
    if labor.value < 0:  # thesis relies on labor loosening
        conditions.append("labor_tightness_score reverses positive (claims fall, JOLTS openings stabilize)")
    if inflation.value < 0:  # thesis relies on disinflation
        conditions.append("inflation_convergence_classifier shows broad-based reacceleration (not narrow, single-measure)")
    return " OR ".join(conditions) if conditions else "No clear evidence-based invalidation condition identified — DO NOT promote this thesis past DRAFT (Module 14 Q8 requirement)"

def select_instrument(gap: "MarketPricingGap", regime: ModelResult) -> str:
    """Module 15's rule-based instrument-selection table, actually coded
    (was only a narrative table before). Matches gap TYPE to instrument —
    Phase 1 only distinguishes 'policy path gap' since that's the only gap
    type this system currently computes; curve-shape-specific and
    cross-country gaps are Phase 5+ once multi-tenor and multi-country
    modeling exist."""
    if abs(gap.raw_gap) > 0:
        return "UST 2yr note futures"  # policy-path gap → short-end rates, per Module 15 table
    return "NONE"

def build_scenario_distribution(gap: "MarketPricingGap", convergence: str) -> list["ScenarioOutcome"]:
    """Phase 1: explicit 3-4 scenario set with ILLUSTRATIVE probabilities,
    NOT a real Monte Carlo simulation over correlated risk factors (that is
    genuinely Phase 5+, Section 17.1's monte_carlo_var pattern). Confidence
    in convergence adjusts the base-case probability weight."""
    base_prob = 0.55 if convergence == "HIGH" else 0.45 if convergence == "MEDIUM" else 0.30
    remaining = 1 - base_prob
    return [
        ScenarioOutcome(scenario_name="base_case_gap_closes_as_modeled", probability=base_prob,
                         payoff_estimate=abs(gap.raw_gap) * 100, unit="bp_pnl_proxy"),
        ScenarioOutcome(scenario_name="gap_partially_closes", probability=remaining * 0.5,
                         payoff_estimate=abs(gap.raw_gap) * 40, unit="bp_pnl_proxy"),
        ScenarioOutcome(scenario_name="thesis_invalidated_reversal", probability=remaining * 0.35,
                         payoff_estimate=-abs(gap.raw_gap) * 60, unit="bp_pnl_proxy"),
        ScenarioOutcome(scenario_name="tail_adverse_surprise", probability=remaining * 0.15,
                         payoff_estimate=-abs(gap.raw_gap) * 150, unit="bp_pnl_proxy"),
    ]

def next_catalyst_calendar() -> list[str]:
    """MUST pull from FRED release/dates + federalreserve.gov RSS (Section
    8, matching the companion data-pipeline project's rule) — NEVER a
    third-party calendar. Phase 1 placeholder returns a description; Phase
    2+ must wire this to the actual official calendar endpoints."""
    return ["Next CPI release (FRED release/dates)", "Next NFP release (FRED release/dates)",
            "Next FOMC meeting + dot plot (federalreserve.gov)"]

def build_confirmation_signals(growth: ModelResult, inflation: ModelResult, labor: ModelResult,
                                gap: "MarketPricingGap") -> list["ConfirmationSignal"]:
    signals = []
    for name, result in [("output_gap", growth), ("inflation_convergence", inflation), ("labor_tightness_score", labor)]:
        direction = "confirms" if (isinstance(result.value, (int, float)) and
                                    ((result.value < 0 and gap.raw_gap < 0) or (result.value > 0 and gap.raw_gap > 0))) else "contradicts"
        signals.append(ConfirmationSignal(source_model=name, direction=direction, detail=result.interpretation))
    return signals

def collect_all_warnings(*model_results: ModelResult) -> list[str]:
    all_warnings = []
    for r in model_results:
        all_warnings.extend(r.warnings)
    return list(dict.fromkeys(all_warnings))  # de-duplicated, order-preserved

def generate_id() -> str:
    import uuid
    return f"us-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
```

**Required action if Phase 3 is already built:** compare every one of these
10 functions against whatever the coding agent actually wrote to make
`build_us_macro_thesis()` run. Any divergence must be corrected to match
the implementations above, and the golden tests from Section 11.1 Phase 3
must be re-run after correction.



### 17.1 VaR / ES — All Three Methods

```python
# Parametric (variance-covariance) VaR
def parametric_var(portfolio_value: float, vol_annualized: float,
                    confidence: float = 0.95, horizon_days: int = 1) -> float:
    from scipy.stats import norm
    z = norm.ppf(confidence)
    horizon_vol = vol_annualized * (horizon_days / 252) ** 0.5
    return portfolio_value * z * horizon_vol

# Historical VaR — already specified, Section 9.1

# Monte Carlo VaR (outline)
def monte_carlo_var(scenario_generator: Callable, n_sims: int = 10_000,
                     confidence: float = 0.95) -> dict:
    """
    scenario_generator draws correlated shocks across the portfolio's risk
    factors (rates, FX, credit, equity) per Module 17.2's coherent-scenario
    principle — NOT independent single-variable shocks. Correlation matrix
    must include a STRESSED variant (crisis correlations → higher, per the
    LTCM lesson) alongside the "normal" historical matrix; report both.
    """
    normal_pnls = [scenario_generator(regime="normal") for _ in range(n_sims)]
    stressed_pnls = [scenario_generator(regime="stressed") for _ in range(n_sims)]
    return {
        "var_normal": float(np.percentile(normal_pnls, (1 - confidence) * 100)),
        "var_stressed": float(np.percentile(stressed_pnls, (1 - confidence) * 100)),
        "note": "Compare normal vs. stressed-correlation VaR — large gap = hidden correlation-breakdown risk (Module 17.1/1 LTCM lesson)",
    }
```

### 17.2 Stress Testing — Concrete Scenario Definitions

```yaml
# scenarios/gfc_2008.yaml
name: gfc_2008_like
narrative: "Credit/liquidity crisis, capital/solvency issue manifesting as liquidity crisis (Module 2's GFC framing)"
growth_shock_pp: -4.0
inflation_shock_pp: -1.0
credit_spread_hy_shock_bp: +600
credit_spread_ig_shock_bp: +150
equity_shock_pct: -35
rate_shock_bp: -300
correlation_overrides:
  treasuries_vs_hy_credit: -0.7      # flight to quality strengthens
  usd_vs_risk_assets: +0.6           # dollar smile LEFT side (Module 9.2)

# scenarios/covid_2020.yaml
name: covid_2020_like
narrative: "Simultaneous global supply AND demand shock — not a financial-imbalance crisis (Module 1 distinction from GFC)"
growth_shock_pp: -8.0
inflation_shock_pp: -0.5   # initial deflationary shock, BEFORE the later 2021-22 fiscal-driven reflation
equity_shock_pct: -34
rate_shock_bp: -150        # already near zero, less room than GFC
fiscal_response_flag: true # downstream inflation_forecast should account for this differently than GFC (Module 1.5)

# scenarios/em_crisis_like.yaml
name: em_crisis_like
narrative: "Asian-Crisis-style: Fed hiking cycle, EM capital outflow, currency mismatch compounding (Module 9.4)"
fed_rate_shock_bp: +200
em_fx_shock_pct: -25
em_credit_spread_shock_bp: +800
current_account_deficit_trigger: true   # only applies to EM instruments failing the Module 9.4 vulnerability checklist
```

### 17.3 Position Sizing, Leverage, Liquidity Constraints

### 22.6 Resolves Finding #6 — Real Kelly Implementation (GENUINE BLOCKER, NOW FIXED)

**The prior** **`raw_kelly = ev / 100`** **was a placeholder incorrectly labeled
Kelly. This is the actual, correct generalized Kelly criterion, replacing
that placeholder entirely — nothing in this system may call anything
"Kelly" except this function:**

```python
def generalized_kelly_fraction(scenarios: list["ScenarioOutcome"],
                                search_range: tuple[float, float] = (0.0, 1.0),
                                n_grid: int = 1000) -> ModelResult:
    """
    THE real Kelly implementation. For a DISCRETE scenario distribution
    (not a simple binary win/loss), the Kelly-optimal fraction f* is the
    value that MAXIMIZES expected log growth:
        f* = argmax_f  SUM_i [ p_i * log(1 + f * r_i) ]
    where r_i is scenario i's return AS A FRACTION of capital at risk
    (payoff_estimate / capital_base — the caller must supply payoffs
    already normalized to a fraction, not a raw dollar/bp figure).
    Solved by grid search over search_range (no closed form exists for
    >2 outcomes) — this is standard practice for multi-outcome Kelly, not
    an approximation invented for this system.
    """
    import numpy as np
    total_p = sum(s.probability for s in scenarios)
    if abs(total_p - 1.0) > 0.01:
        raise ValueError(f"Scenario probabilities sum to {total_p}, must sum to 1.0")

    f_grid = np.linspace(search_range[0], search_range[1], n_grid)
    best_f, best_growth = 0.0, float("-inf")
    for f in f_grid:
        growth = 0.0
        valid = True
        for s in scenarios:
            term = 1 + f * s.payoff_estimate
            if term <= 0:      # ruin at this f for this scenario — Kelly forbids this
                valid = False
                break
            growth += s.probability * np.log(term)
        if valid and growth > best_growth:
            best_f, best_growth = f, growth

    return ModelResult(
        model_name="generalized_kelly_fraction", country="us", as_of=datetime.utcnow(),
        value=round(best_f, 4), confidence=0.5,
        interpretation=f"Kelly-optimal fraction: {best_f:.2%} of capital",
        context="Grid-search-maximized expected log growth over the FULL scenario distribution — not a two-outcome approximation",
        inputs_used=["scenarios"],
        warnings=["This is FULL Kelly. It MUST be divided by kelly_fraction (k>=2) before use — Module 12.4's mandatory fractional-Kelly rule applies to this exact output"],
    )

def apply_fractional_kelly_corrected(scenarios: list["ScenarioOutcome"], kelly_fraction: float = 0.5,
                                      limits: "RiskLimits" = None) -> ModelResult:
    """CORRECTED — calls the real Kelly function above, replaces the Section 17.3 placeholder entirely."""
    limits = limits or RiskLimits()
    full_kelly = generalized_kelly_fraction(scenarios)
    sized = full_kelly.value * kelly_fraction
    final = min(sized, limits.max_position_pct_of_portfolio)
    clipped = final < sized
    return ModelResult(
        model_name="apply_fractional_kelly_corrected", country="us", as_of=datetime.utcnow(),
        value=round(final, 4), confidence=0.45,
        interpretation=f"Sized position: {final:.2%} of capital (full Kelly {full_kelly.value:.2%} x fraction {kelly_fraction})" +
                        (" [CLIPPED by RiskLimits]" if clipped else ""),
        context="Real generalized-Kelly output, fractionally sized, hard-constraint clipped",
        inputs_used=["scenarios", "kelly_fraction"],
        warnings=["CLIPPED by max_position_pct_of_portfolio — hard limits always win"] if clipped else [],
    )

```

---


```python
class RiskLimits(BaseModel):
    max_position_pct_of_portfolio: float = 0.15
    max_factor_exposure_pct: float = 0.30       # any single PCA factor (Module 17.1/18.3)
    max_drawdown_trigger_pct: float = 0.10      # drawdown-based de-risking, Module 17.3
    max_leverage: float = 3.0
    min_liquidity_days_to_unwind: int = 2       # never size beyond what can be unwound in N days

def apply_fractional_kelly(scenarios: list[ScenarioOutcome], kelly_fraction: float = 0.5,
                            limits: RiskLimits = RiskLimits()) -> float:
    """
    Computes a raw Kelly-optimal fraction from the scenario distribution,
    then divides by kelly_fraction's implied divisor (k>=2, i.e. half-Kelly
    default), THEN clips against every hard RiskLimits constraint — hard
    constraints ALWAYS win over the Kelly-derived size (Module 17.2's
    explicit rule: vol-targeting/Kelly sizing never overrides max position,
    max factor exposure, max drawdown, liquidity, or tail-risk limits).
    """
    ev = sum(s.probability * s.payoff_estimate for s in scenarios)
    # ... full Kelly derivation from scenario odds, omitted for brevity ...
    raw_kelly = ev / 100  # placeholder proportional relationship
    sized = raw_kelly / (1 / kelly_fraction)
    return min(sized, limits.max_position_pct_of_portfolio)
```

### 17.4 Feedback Into Thesis Validity

- A thesis whose `sizing_logic` output (once Phase 4+ auto-sizing exists)
  clips to near-zero against `RiskLimits` (e.g., liquidity constraint binds
  hard) should have its `status` automatically demoted from `CANDIDATE` back
  to `WATCH` — a thesis that can't be sized meaningfully isn't actionable,
  regardless of conviction (directly encodes the LTCM lesson: a "correct"
  idea you can't survive-size isn't a trade yet).
- Portfolio-level PCA concentration check (Module 17.1/18.3, Phase 5+):
  before promoting any thesis to `ACTIVE`, check whether its instrument
  loads heavily on a principal component the portfolio is *already*
  concentrated in — flag, don't silently allow, hidden concentration.

---

## 18. Crisis Playbooks (Modules 1 & 16) — Pattern Library

Each playbook below follows: setup/narrative → observable data patterns →
detection rule → system impact.

### 18.1 Black Wednesday (1992)

- **Setup:** Fixed exchange rate (ERM peg) + free capital + attempted
  independent monetary policy — a textbook trilemma violation.
- **Observable patterns:** Central bank reserves visibly depleting; policy
  rate hiked sharply and suddenly (BoE 10%→15% in a day) as a defensive,
  not proactive, move; currency under sustained one-directional pressure
  despite intervention.
- **Detection rule:** `check_trilemma_tension()` (Module 1, Section 15) flags
  any pegged currency where (a) domestic conditions argue for the opposite
  rate direction from what peg-defense requires, AND (b) reserves/GDP or
  reserves/short-term-external-debt is trending down sharply.
- **System impact:** Regime classifier flags `"peg_stress"` sub-state;
  any EM/FX thesis touching that currency inherits a mandatory warning
  citing the trilemma check.

### 18.2 LTCM (1998)

- **Setup:** Highly-levered convergence/relative-value trades, correlation
  assumed stable, Russia default triggers a flight-to-liquidity unrelated
  to the original mispricing thesis.
- **Observable patterns:** Credit spreads widening sharply and simultaneously
  across seemingly unrelated instruments; "safe" relative-value spreads
  *diverging further* instead of converging; extreme leverage ratios.
- **Detection rule:** `models/risk.py`'s Monte Carlo VaR (Section 17.1)
  explicitly computes both normal and stressed-correlation VaR — a large
  gap between them is the system's LTCM-pattern early warning, applied to
  any cross-market RV position (Module 15.3).
- **System impact:** Any `TradeIdea` built on a cross-market RV instrument
  (Module 15.3) MUST carry an explicit correlation-breakdown warning
  (already mandated in the companion instrument-library spec) and must
  never bypass the fractional-Kelly sizing constraint regardless of
  apparent (correlation-assumed) low risk.

### 18.3 Dot-Com Bubble (2000-2002)

- **Setup:** Accommodative policy + genuine technological revolution +
  valuations detached from any earnings-based metric; Fed tightening
  (1999-2000) as the proximate trigger via the discount-rate channel.
- **Observable patterns:** Long-duration growth equities' valuations
  extremely sensitive to discount-rate moves (Module 11's duration-channel
  logic, quantified in `duration_sensitivity()`, Section 6.9).
- **Detection rule:** `duration_sensitivity()` output combined with a
  rising-rate `policy_view` and elevated equity valuation percentiles
  (Phase 5+ valuation-context tracker) — a coincidence of all three is the
  pattern match.
- **System impact:** Sector-rotation prior (`sector_rotation_prior()`)
  weights toward value/short-duration when this pattern is detected,
  independent of the "which cycle phase" base rate.

### 18.4 Global Financial Crisis (2007-2009)

- **Setup:** Minsky drift (hedge→speculative→Ponzi subprime borrowers),
  securitization obscuring credit quality, repo/shadow-banking funding
  fragility, a capital/solvency crisis manifesting as a liquidity crisis.
- **Observable patterns:** Rising delinquencies well ahead of home-price
  peak; credit spreads (especially structured-product-linked) widening
  early (mid-2007) before broader market recognition; repo market stress.
- **Detection rule:** Module 3's Minsky borrower-composition flag +
  Module 2's repo-stress rule + Module 8's HY spread widening — three
  independently-sourced signals converging is the GFC-pattern match,
  directly implementing Module 8.3's triangulation principle.
- **System impact:** Regime classifier's `"stagflation"`/`"recession"`
  transition logic gets an additional GFC-specific override: credit-spread
  + repo-stress + Minsky-composition convergence can trigger a recession
  regime flag *before* the output-gap/GDP data itself confirms it (matching
  the course's explicit "don't wait for lagging confirmation" lesson).

### 18.5 Euro Debt Crisis (2010-2012)

- **Setup:** Single currency, no independent monetary policy per member
  state, sovereign-bank "doom loop" (banks holding own-sovereign debt).
- **Observable patterns:** Peripheral-vs-core sovereign spread blowout
  (e.g., Italy-Germany, not covered in Phase 1's US-only instrument set,
  but the pattern generalizes to any monetary-union-without-fiscal-union
  structure the system might later analyze).
- **Detection rule:** N/A for Phase 1 (no Eurozone peripheral-spread data
  source yet) — documented as a Phase 5+ multi-country gap in
  `docs/OPEN_ISSUES.md`.
- **System impact:** Deferred; flagged explicitly rather than silently
  omitted.

### 18.6 COVID (2020)

- **Setup:** Simultaneous global supply AND demand shock — genuinely
  different mechanism from GFC (not a financial-imbalance crisis) — fastest
  bear market in history, followed by unprecedented fiscal+monetary
  coordination.
- **Observable patterns:** Extremely fast equity decline + extremely fast
  Fed response (zero rates + QE within weeks) + (later) fiscal transfers
  directly reaching household spending power, distinct from 2009-2015 QE
  which stayed mostly in bank reserves (Module 2's money-creation
  distinction).
- **Detection rule:** `scenarios/covid_2020.yaml`'s `fiscal_response_flag`
  — when true, the inflation-forecast logic (Module 5/3) must weight the
  fiscal-transfer channel, not just the QE/reserves channel, when
  projecting forward inflation — directly preventing the "QE didn't cause
  2009-15 inflation, so it won't cause inflation now" mistake the course
  explicitly warns against.
- **System impact:** `project_inflation_trajectory()` (Section 16.2) takes
  a `fiscal_response_active: bool` parameter specifically to encode this
  distinction.

### 18.7 Asian Crisis (1997) — Full EM Vulnerability Mechanism

- **Setup:** Thailand, Indonesia, South Korea, Malaysia pegged/tightly
  managed to USD through the mid-1990s while running large current account
  deficits funded by short-term USD-denominated foreign borrowing — a
  textbook Minsky drift into speculative/Ponzi financing (Module 3),
  compounded by the "original sin" currency mismatch (Module 9.4).
- **Observable patterns:** Fed hiking cycle pulling capital toward USD
  assets (UIP/carry logic, Module 9.1); central bank reserves burning
  rapidly defending the peg; contagion — capital fleeing structurally
  similar countries pre-emptively, a self-fulfilling pattern (same bank-run
  logic as Module 1.2, applied to sovereign currencies).
- **Detection rule:** The EM vulnerability checklist itself (Module 9.4,
  Section 6.7) IS the detection rule — current account deficit, USD-vs-
  local debt share, reserves/short-term-external-debt ratio. When a Fed
  hiking cycle (`policy_view` showing tightening) coincides with any EM
  currency failing 2+ of these 3 checks, the system should flag
  `"em_crisis_risk"` regardless of what cointegration/carry signals say —
  matching the course's explicit "multiple failing checks override
  statistical signal" rule.
- **System impact:** Any future EM-currency thesis extension must run this
  checklist before instrument selection (Module 15's hard/local-currency
  bond distinction directly depends on which specific vulnerability is
  driving the flag).

### 18.8 Explicitly Deferred — Not Built in This Specification

The original course syllabus referenced the **2022 UK gilt crisis** (LDI
pension-fund leverage, BoE emergency intervention) and the **Bank of Japan's
Yield Curve Control episodes** as case studies. Both are honestly flagged
here as **not built** — this project's working sessions never developed
these to the same worked-example depth as Black Wednesday, LTCM, Dot-com,
GFC, COVID, and the Asian Crisis above. Rather than fabricate a detection
rule for a pattern that was never actually specified in detail, this is
logged as an open item in `docs/OPEN_ISSUES.md` — a future session should
develop these properly (setup/narrative/observable patterns/detection rule)
before the system claims any UK-gilt-market or BoJ-YCC-specific pattern
recognition capability.

### 19.1 Schema

```python
# src/macro_engine/api_layer/reasoning_stream.py (extends Section 8.3)

class ReasoningStep(BaseModel):
    step_id: str                    # e.g. "step-04"
    type: str                       # "fetch" | "model_run" | "gap_compute" | "convergence_check" | "instrument_select" | "thesis_assemble" | "no_trade_check"
    description: str                # human-readable
    data_refs: list[str] = []       # e.g. ["cpi_core", "yield_curve"]
    model_refs: list[str] = []      # e.g. ["taylor_rule", "policy_rule_ensemble"]
    module_ref: str | None = None   # e.g. "Module 4"
    conclusion: str | None = None   # populated once the step completes
    timestamp: datetime
```

### 19.2 Example Sequence A — HIGH Convergence, Trade Generated

```
step-01 [fetch]              data_refs=[all Section 5.2 series]         "Fetched US snapshot, 14 series, as of 2026-03-14T13:00Z"
step-02 [model_run]          model_refs=[output_gap]        module=Module 7   "Output gap: -0.8% (widening negative)"
step-03 [model_run]          model_refs=[inflation_breadth_score]  module=Module 5  "Breadth score -0.15, convergent disinflation across headline/core CPI/core PCE"
step-04 [model_run]          model_refs=[labor_tightness_score]    module=Module 6  "Score -42, loosening — claims up, JOLTS openings down, weighted per lead/lag hierarchy"
step-05 [model_run]          model_refs=[taylor_rule, balanced_approach_rule, first_difference_rule]  module=Module 4  "Ensemble: Taylor 2.9%, Balanced 2.6%, First-Diff 3.0% — dispersion 0.4pp, LOW dispersion = rules agree"
step-06 [gap_compute]        module=Module 4/14  "Model-implied 2.9% vs. market-implied 4.3% (derived from curve front-end) = -140bp gap"
step-07 [convergence_check]  module=Module 12/13  "Growth (Q7), inflation (Q5), labor (Q6) all confirm loosening/disinflation direction — HIGH convergence, evidence sources genuinely independent (BLS Establishment survey for NFP/wages, BLS/DOL claims infrastructure separate, TIPS market entirely independent of both)"
step-08 [instrument_select]  module=Module 15  "Policy-path gap → outright short-end rates selected: UST 2yr note futures (per Module 15's instrument-purity rule — 2yr more directly sensitive to policy path than 10yr/30yr term-premium noise)"
step-09 [no_trade_check]     module=Module 14 Q6/Q7/Q15  "Gap (140bp) exceeds rule dispersion (40bp) — meaningful. Convergence HIGH, not CONFLICTED. NO TRADE conditions NOT triggered — proceeding to thesis assembly."
step-10 [thesis_assemble]    module=Module 14  "MacroThesis us-2026-03-a1 assembled: long UST 2yr, 6-12mo horizon, status=DRAFT, invalidation = labor_tightness_score reversal OR broad inflation reacceleration"
```

### 19.3 Example Sequence B — CONFLICTED, NO TRADE

```
step-01 [fetch]              "Fetched US snapshot"
step-02 [model_run]          module=Module 7  "Output gap: -1.2% (weakening)"
step-03 [model_run]          module=Module 5  "Breadth score +0.35 (reaccelerating — headline AND core both rising)"
step-04 [convergence_check]  module=Module 12  "Growth says ease (weakening output gap), Inflation says tighten (reaccelerating, broad-based not narrow) — DIRECT CONTRADICTION, not just disagreement"
step-05 [no_trade_check]     module=Module 14 Q7/Q15  "CONFLICTED convergence detected — this is the Module 12 dual-mandate-tension pattern (Section 3.3/12.2), genuine unresolved tension, NOT a data error to be smoothed over. Returning NO TRADE."
step-06 [thesis_assemble]    module=Module 14  "MacroThesis us-2026-04-b7 assembled with status=WATCH, trade_idea.instrument='NONE', warning='Growth and inflation signals genuinely conflict — false confidence in an unclear picture is worse than correctly identified uncertainty (Module 12, LTCM lesson lineage)'"
```

### 19.4 Example Sequence C — Gap Present But Not Meaningful (Dispersion Too Wide)

```
step-01 [fetch]              "Fetched US snapshot"
step-02 [model_run]          module=Module 4  "Ensemble: Taylor 3.1%, Balanced 4.8%, First-Diff 3.9% — dispersion 1.7pp, HIGH dispersion"
step-03 [gap_compute]        "Model-implied (Taylor) 3.1% vs market-implied 3.4% = -30bp gap"
step-04 [no_trade_check]     module=Module 14 Q6  "Gap (30bp) does NOT exceed rule dispersion (170bp) — the disagreement between policy rules is itself larger than the model-vs-market gap. This is NOT a meaningful signal; it is r*/output-gap estimation noise masquerading as a policy view. Returning NO TRADE per Module 4's explicit 'divergence is information, do not average it away' principle applied at the gap-significance-test level."
step-05 [thesis_assemble]    "MacroThesis assembled with status=WATCH, warning='Policy rule dispersion (170bp) exceeds computed gap (30bp) — no reliable signal at this time'"
```

---

*End of specification.*
## 20. Complete Mechanical Audit — All Remaining Missing Functions

### 22.11 Resolves Finding #11 — Mechanical Rules Softened With Required Corroboration

**Three specific over-mechanized rules, corrected:**

1. **Repo stress (****`repo_stress_check`****, Section 20.2):** a single-snapshot
   SOFR-IORB spread is insufficient. **Corrected rule:** the function must
   also accept a `persistence_days: int` input and only return
   `ACUTE_REPO_STRESS` if the breach has persisted ≥3 consecutive days, AND
   must be cross-checked against `repo_volume_change_pct` (a spike
   concentrated in low volume is a different, weaker signal than one
   accompanied by high volume) before escalating to the risk layer.
   Corridor POSITION alone, one day, is now explicitly insufficient.
2. **CPI/PCE construction (Section 20.5):** `laspeyres_index`/`paasche_index`/
   `fisher_index` are already marked "reference implementations for testing
   and education only" (Section 21.1) — this is correct and sufficient;
   the review's concern is addressed by ensuring no caller ever invokes
   them expecting real BLS-microdata-accurate output. No code change
   needed, documentation emphasis strengthened here.
3. **Intervention capacity (****`intervention_capacity`****, Section 20.9):** the
   "unlimited ammunition" framing is corrected to make explicit that
   "unlimited" refers strictly to the MECHANICAL ability to print currency
   — the function's `warnings` field already notes the cost-driven
   abandonment failure mode (SNB 2015), but the `capacity` value itself
   is renamed from `"UNLIMITED_AMMUNITION_but_costly"` to
   `"MECHANICALLY_UNCONSTRAINED_COST_BOUNDED"` to prevent any caller from
   reading "unlimited" as "risk-free."

---


**This section is the result of a systematic, function-by-function audit of
every Module 1–18 lesson against the spec's actual code inventory. It found
34 additional missing functions.** Several are foundational (convexity,
Cobb-Douglas potential GDP, Bayesian updating, the shelter-lag projection)
and belong in already-completed phases.

**Append this section to AGENTS.md. Every function below must be
implemented — none may be skipped as "not important enough."**

---

### 20.1 Module 1 — Quantity Theory (COVID inflation mechanism)

```python
# src/macro_engine/models/monetary.py (NEW FILE) — Phase 2 backfill

class QuantityTheoryInputs(BaseModel):
    money_supply_growth_pct: float      # M
    velocity_change_pct: float          # V
    real_output_growth_pct: float       # Y

def quantity_theory_implied_inflation(inputs: QuantityTheoryInputs) -> ModelResult:
    """
    M x V = P x Y  =>  %dP ~= %dM + %dV - %dY
    The mechanism behind Module 1.5's COVID inflation explanation: QE alone
    (2009-15) raised M but V collapsed, so P barely moved. COVID raised M
    AND fiscal transfers kept V from collapsing, so P moved sharply.
    This is a DIAGNOSTIC identity, not a forecast — velocity is the term
    that makes naive 'money printing = inflation' predictions fail.
    """
    implied = inputs.money_supply_growth_pct + inputs.velocity_change_pct - inputs.real_output_growth_pct
    return ModelResult(
        model_name="quantity_theory_implied_inflation", country="us", as_of=datetime.utcnow(),
        value=round(implied, 2), confidence=0.25,
        interpretation=f"Identity-implied price-level change: {implied:+.2f}%",
        context="M x V = P x Y identity. LOW confidence by design — velocity is unstable and this is not a forecasting model",
        inputs_used=["money_supply_growth_pct", "velocity_change_pct", "real_output_growth_pct"],
        warnings=["Velocity instability makes this diagnostic only — never use as a standalone inflation forecast (Module 1.5/2.2)"],
    )
```

---

### 20.2 Module 2 — Convexity, Repo Stress, Floor-System Corridor

```python
# src/macro_engine/models/bond_math.py — Phase 2 backfill

def convexity(inputs: BondPricingInputs) -> ModelResult:
    """
    Convexity = SUM[ t*(t+1)*PV(CF_t) ] / (Price * (1+y)^2)
    Duration assumes a LINEAR price/yield relationship; the true
    relationship is curved. Convexity quantifies that curvature.
    """
    pv_weighted = 0.0
    price = 0.0
    for t in range(1, inputs.n_periods + 1):
        cf = inputs.coupon + (inputs.face_value if t == inputs.n_periods else 0.0)
        pv = cf / ((1 + inputs.yield_rate) ** t)
        price += pv
        pv_weighted += t * (t + 1) * pv
    conv = pv_weighted / (price * (1 + inputs.yield_rate) ** 2)
    return ModelResult(
        model_name="convexity", country="us", as_of=datetime.utcnow(),
        value=round(conv, 4), confidence=0.95,
        interpretation=f"Convexity: {conv:.4f}",
        context="Higher convexity = more favorable asymmetry (gains exceed linear on rallies, losses below linear on selloffs)",
        inputs_used=["coupon", "face_value", "yield_rate", "n_periods"],
    )

def price_change_with_convexity(mod_dur: float, conv: float, delta_y: float) -> ModelResult:
    """%dPrice ~= -ModDur * dy + 0.5 * Convexity * (dy)^2"""
    linear = -mod_dur * delta_y
    convex_adj = 0.5 * conv * (delta_y ** 2)
    total = linear + convex_adj
    return ModelResult(
        model_name="price_change_with_convexity", country="us", as_of=datetime.utcnow(),
        value=round(total * 100, 4), confidence=0.9,
        interpretation=f"Est. price change {total*100:+.4f}% (duration {linear*100:+.4f}%, convexity {convex_adj*100:+.4f}%)",
        context="Convexity term is ALWAYS positive — favorable to the bondholder in both directions (Module 2.6)",
        inputs_used=["mod_dur", "conv", "delta_y"],
    )

class RepoStressInputs(BaseModel):
    sofr: float
    iorb: float
    on_rrp_rate: float
    fed_funds_effective: float

def repo_stress_check(inputs: RepoStressInputs) -> ModelResult:
    """
    Module 2.1/2.3: the floor system means SOFR should trade inside the
    IORB/ON-RRP corridor. A spike materially ABOVE IORB without a Fed
    policy change is plumbing stress, which historically PRECEDES headline
    market stress (Sept 2019). This is an early-warning signal, not a
    policy signal.
    """
    spread_to_iorb_bp = (inputs.sofr - inputs.iorb) * 100
    if spread_to_iorb_bp > 25:
        severity, conf = "ACUTE_REPO_STRESS", 0.7
    elif spread_to_iorb_bp > 10:
        severity, conf = "ELEVATED", 0.5
    else:
        severity, conf = "NORMAL", 0.8
    return ModelResult(
        model_name="repo_stress_check", country="us", as_of=datetime.utcnow(),
        value={"severity": severity, "sofr_minus_iorb_bp": round(spread_to_iorb_bp, 1)},
        confidence=conf,
        interpretation=f"Repo market: {severity} (SOFR-IORB {spread_to_iorb_bp:+.1f}bp)",
        context="Floor system: SOFR should sit at/below IORB. Persistent breach = reserve scarcity (Sept 2019 pattern)",
        inputs_used=["sofr", "iorb", "on_rrp_rate"],
        warnings=["Plumbing stress precedes headline stress — escalate to risk layer immediately"] if severity == "ACUTE_REPO_STRESS" else [],
    )
```

---

### 20.3 Module 3 — Identities, Policy Mix, Phillips Curve, Potential GDP, Minsky

```python
# src/macro_engine/models/national_accounts.py (NEW FILE) — Phase 2 backfill

class SavingsInvestmentInputs(BaseModel):
    private_saving: float
    private_investment: float
    tax_revenue: float
    government_spending: float

def savings_investment_identity(inputs: SavingsInvestmentInputs) -> ModelResult:
    """
    (S - I) + (T - G) = (X - M)
    Module 3.1: the current account is NOT an independent policy variable.
    Use this to check whether a proposed trade-balance thesis is
    arithmetically coherent with the fiscal/saving position.
    """
    private_balance = inputs.private_saving - inputs.private_investment
    fiscal_balance = inputs.tax_revenue - inputs.government_spending
    implied_ca = private_balance + fiscal_balance
    return ModelResult(
        model_name="savings_investment_identity", country="us", as_of=datetime.utcnow(),
        value={"private_balance": private_balance, "fiscal_balance": fiscal_balance,
               "implied_current_account": implied_ca},
        confidence=0.95,
        interpretation=f"Identity-implied current account: {implied_ca:+,.1f} ({'surplus' if implied_ca>0 else 'deficit'})",
        context="(S-I)+(T-G)=(X-M). A trade-deficit thesis ignoring fiscal/saving is arithmetically incoherent (Module 3.1)",
        inputs_used=["private_saving", "private_investment", "tax_revenue", "government_spending"],
    )

class PolicyMixInputs(BaseModel):
    fiscal_deficit_pct_gdp: float
    fiscal_deficit_avg_pct_gdp: float
    policy_rate: float
    taylor_implied_rate: float

def policy_mix_classifier(inputs: PolicyMixInputs) -> ModelResult:
    """
    Module 3.2's 2x2. Fiscal loose/tight vs monetary loose/tight.
    Critical because naive Fed-only analysis misses half the picture when
    fiscal pulls the opposite direction (the post-2022 disinflation case).
    """
    fiscal_loose = inputs.fiscal_deficit_pct_gdp > inputs.fiscal_deficit_avg_pct_gdp
    monetary_loose = inputs.policy_rate < inputs.taylor_implied_rate
    quadrant = {
        (True, True): "MAX_STIMULUS",
        (True, False): "MIXED_FISCAL_LOOSE_MONETARY_TIGHT",
        (False, True): "MIXED_FISCAL_TIGHT_MONETARY_LOOSE",
        (False, False): "MAX_RESTRAINT",
    }[(fiscal_loose, monetary_loose)]
    return ModelResult(
        model_name="policy_mix_classifier", country="us", as_of=datetime.utcnow(),
        value=quadrant, confidence=0.6,
        interpretation=f"Policy mix: {quadrant}",
        context=f"Fiscal {'loose' if fiscal_loose else 'tight'} / Monetary {'loose' if monetary_loose else 'tight'} vs Taylor-implied",
        inputs_used=["fiscal_deficit_pct_gdp", "policy_rate", "taylor_implied_rate"],
        warnings=["MIXED quadrants mean Fed-only analysis is incomplete — fiscal is working against monetary (Module 3.2)"]
                 if "MIXED" in quadrant else [],
    )

class PhillipsCurveInputs(BaseModel):
    inflation_expectations: float     # pi^e
    unemployment_rate: float          # u
    nairu: float                      # u*
    beta: float = 0.5                 # sensitivity, configurable

def phillips_curve_inflation(inputs: PhillipsCurveInputs) -> ModelResult:
    """pi = pi^e - beta*(u - u*).  Module 3.3, expectations-augmented."""
    gap = inputs.unemployment_rate - inputs.nairu
    pi = inputs.inflation_expectations - inputs.beta * gap
    return ModelResult(
        model_name="phillips_curve_inflation", country="us", as_of=datetime.utcnow(),
        value=round(pi, 2), confidence=0.35,
        interpretation=f"Phillips-implied inflation: {pi:.2f}% (u-gap {gap:+.2f}pp)",
        context=f"pi^e={inputs.inflation_expectations}%, beta={inputs.beta}",
        inputs_used=["inflation_expectations", "unemployment_rate", "nairu", "beta"],
        warnings=["u* (NAIRU) is UNOBSERVABLE and revised significantly ex-post — this is the dominant uncertainty here (Module 3.3)",
                  "If pi^e is unanchored, the expectations term dominates and the slack term barely matters (1970s stagflation lesson)"],
    )

class PotentialGDPInputs(BaseModel):
    total_factor_productivity: float   # A
    capital_stock: float               # K
    labor_input: float                 # L
    alpha: float = 0.3                 # capital share

def potential_gdp_cobb_douglas(inputs: PotentialGDPInputs) -> ModelResult:
    """Potential Y = A * K^alpha * L^(1-alpha).  Module 3.5/7.2."""
    y = inputs.total_factor_productivity * (inputs.capital_stock ** inputs.alpha) * \
        (inputs.labor_input ** (1 - inputs.alpha))
    return ModelResult(
        model_name="potential_gdp_cobb_douglas", country="us", as_of=datetime.utcnow(),
        value=round(y, 2), confidence=0.3,
        interpretation=f"Estimated potential GDP: {y:,.2f}",
        context=f"A={inputs.total_factor_productivity}, K={inputs.capital_stock}, L={inputs.labor_input}, alpha={inputs.alpha}",
        inputs_used=["total_factor_productivity", "capital_stock", "labor_input", "alpha"],
        warnings=["A (productivity) is the LEAST predictable and MOST impactful term — Module 3.5",
                  "Track CBO/Fed/IMF estimates alongside this; dispersion across them IS the uncertainty band"],
    )

def growth_accounting_decomposition(labor_force_growth_pct: float,
                                     productivity_growth_pct: float) -> ModelResult:
    """Potential growth ~= labor force growth + productivity growth (Module 3.5)."""
    total = labor_force_growth_pct + productivity_growth_pct
    prod_share = productivity_growth_pct / total if total != 0 else 0
    return ModelResult(
        model_name="growth_accounting_decomposition", country="us", as_of=datetime.utcnow(),
        value={"potential_growth": round(total, 2), "productivity_share": round(prod_share, 3)},
        confidence=0.4,
        interpretation=f"Potential growth {total:.2f}% ({productivity_growth_pct:.2f}pp productivity, {labor_force_growth_pct:.2f}pp labor)",
        context="Demographics are HIGH-confidence; productivity is LOW-confidence. Confidence in the total scales inversely with productivity's share",
        inputs_used=["labor_force_growth_pct", "productivity_growth_pct"],
        warnings=[f"Productivity drives {prod_share:.0%} of this estimate — the less-predictable term dominates (Module 3.5)"]
                 if prod_share > 0.6 else [],
    )

class MinskyCompositionInputs(BaseModel):
    lending_standards_net_tightening_pct: float   # SLOOS, negative = loosening
    risky_credit_growth_pct: float                 # leveraged loans / subprime-equivalent
    total_credit_growth_pct: float

def minsky_composition_drift(inputs: MinskyCompositionInputs) -> ModelResult:
    """
    Module 3.4: the WARNING SIGN is composition drift toward speculative/
    Ponzi financing, visible in loosening standards + risky credit
    outgrowing total credit — NOT high credit growth per se, which can be
    perfectly healthy hedge-borrower expansion.
    """
    standards_loosening = inputs.lending_standards_net_tightening_pct < 0
    risky_outgrowing = inputs.risky_credit_growth_pct > inputs.total_credit_growth_pct * 1.2
    if standards_loosening and risky_outgrowing:
        stage, conf = "PONZI_DRIFT_WARNING", 0.6
    elif standards_loosening or risky_outgrowing:
        stage, conf = "SPECULATIVE_DRIFT", 0.45
    else:
        stage, conf = "HEDGE_DOMINANT", 0.5
    return ModelResult(
        model_name="minsky_composition_drift", country="us", as_of=datetime.utcnow(),
        value=stage, confidence=conf,
        interpretation=f"Credit cycle composition: {stage}",
        context="Composition drift, not aggregate credit growth, is the leading indicator (Module 3.4)",
        inputs_used=["lending_standards_net_tightening_pct", "risky_credit_growth_pct", "total_credit_growth_pct"],
        warnings=["Defaults are a LAGGING confirmation — by the time they rise, the drift already happened (Module 3.4)"]
                 if stage == "PONZI_DRIFT_WARNING" else [],
    )
```

---

### 20.4 Module 4 — QE/QT Balance Sheet, Forward Guidance Diff

```python
# src/macro_engine/models/policy_rules.py (additions) — Phase 2 backfill / Phase 5+ for text

class BalanceSheetInputs(BaseModel):
    balance_sheet_level: float
    balance_sheet_change_3mo: float
    reserve_balances: float
    reserve_balances_change_3mo: float

def qe_qt_stance(inputs: BalanceSheetInputs) -> ModelResult:
    """
    Module 4.1: QE/QT is a SECOND policy lever the policy rate alone
    misses. QT is riskier to calibrate than QE — 'ample reserves' level is
    unknown, and Sept 2019 showed reserves can hit scarcity unexpectedly.
    """
    if inputs.balance_sheet_change_3mo > 0:
        stance = "QE_EXPANDING"
    elif inputs.balance_sheet_change_3mo < 0:
        stance = "QT_CONTRACTING"
    else:
        stance = "NEUTRAL_HOLD"
    return ModelResult(
        model_name="qe_qt_stance", country="us", as_of=datetime.utcnow(),
        value={"stance": stance, "bs_change_3mo": inputs.balance_sheet_change_3mo,
               "reserve_change_3mo": inputs.reserve_balances_change_3mo},
        confidence=0.75,
        interpretation=f"Balance sheet stance: {stance}",
        context="Second policy lever beyond the policy rate — affects term premium via duration extraction (Module 4.1)",
        inputs_used=["balance_sheet_level", "balance_sheet_change_3mo", "reserve_balances"],
        warnings=["QT active — monitor repo_stress_check(); reserve scarcity is not predictable ex-ante (Sept 2019)"]
                 if stance == "QT_CONTRACTING" else [],
    )

HAWKISH_MARKERS = ["additional policy firming", "further tightening", "remains elevated",
                   "prepared to raise", "insufficient progress"]
DOVISH_MARKERS = ["not expected to be appropriate", "has eased", "prepared to adjust",
                  "reduce restriction", "sustainable progress"]

def statement_text_diff(prior_text: str, current_text: str) -> ModelResult:
    """
    Module 4.3: desks run word-level diffs on FOMC statements seconds after
    release. Removal or addition of specific conditional phrases is the
    signal — the CURRENT rate decision is usually already priced; the
    forward-looking language is where surprise lives.
    Phase 5+ (requires federalreserve.gov text source).
    """
    raise NotImplementedError("Phase 5+ — requires FOMC statement text feed")
```

---

### 20.5 Module 5 — Index Construction, Shelter Lag, PPI Pipeline, Cross-Asset Transmission

```python
# src/macro_engine/models/inflation_nowcast.py (additions) — Phase 2 backfill

def laspeyres_index(current_prices: dict[str, float], base_prices: dict[str, float],
                     base_quantities: dict[str, float]) -> ModelResult:
    """CPI_t = SUM(P_t*Q_0) / SUM(P_0*Q_0) * 100.  Fixed base quantities => substitution bias (overstates)."""
    num = sum(current_prices[k] * base_quantities[k] for k in base_quantities)
    den = sum(base_prices[k] * base_quantities[k] for k in base_quantities)
    idx = num / den * 100
    return ModelResult(
        model_name="laspeyres_index", country="us", as_of=datetime.utcnow(),
        value=round(idx, 4), confidence=0.95,
        interpretation=f"Laspeyres index: {idx:.4f}",
        context="Fixed base-period quantities — cannot capture substitution, therefore OVERSTATES cost-of-living (Module 5.1)",
        inputs_used=["current_prices", "base_prices", "base_quantities"],
    )

def paasche_index(current_prices, base_prices, current_quantities) -> ModelResult:
    """Paasche = SUM(P_t*Q_t)/SUM(P_0*Q_t)*100 — current quantities, UNDERSTATES."""
    num = sum(current_prices[k] * current_quantities[k] for k in current_quantities)
    den = sum(base_prices[k] * current_quantities[k] for k in current_quantities)
    idx = num / den * 100
    return ModelResult(
        model_name="paasche_index", country="us", as_of=datetime.utcnow(),
        value=round(idx, 4), confidence=0.95,
        interpretation=f"Paasche index: {idx:.4f}",
        context="Current-period quantities — UNDERSTATES inflation (opposite bias to Laspeyres)",
        inputs_used=["current_prices", "base_prices", "current_quantities"],
    )

def fisher_index(laspeyres: float, paasche: float) -> ModelResult:
    """Fisher = sqrt(Laspeyres * Paasche). PCE's chain-weighting basis (Module 5.2)."""
    idx = (laspeyres * paasche) ** 0.5
    return ModelResult(
        model_name="fisher_index", country="us", as_of=datetime.utcnow(),
        value=round(idx, 4), confidence=0.95,
        interpretation=f"Fisher ideal index: {idx:.4f}",
        context="Geometric mean of over-stating and under-stating indices — captures substitution (Module 5.2)",
        inputs_used=["laspeyres", "paasche"],
    )

class ShelterLagInputs(BaseModel):
    market_rent_growth_yoy_pct: list[float]   # most recent 18 months of real-time rent data, oldest first
    current_cpi_shelter_yoy_pct: float
    lag_months: int = 15                       # midpoint of the 12-18 month lease-turnover lag

def project_shelter_cpi(inputs: ShelterLagInputs) -> ModelResult:
    """
    Module 5.1's highest-value practical insight: CPI shelter lags
    real-time market rents by ~12-18 months because only ~1/12 of leases
    turn over monthly. This means future CPI shelter is PARTIALLY KNOWABLE
    TODAY from private rent indices — one of the few genuinely forecastable
    CPI components.
    """
    if len(inputs.market_rent_growth_yoy_pct) < inputs.lag_months:
        return ModelResult(
            model_name="project_shelter_cpi", country="us", as_of=datetime.utcnow(),
            value=None, confidence=0.0,
            interpretation="Insufficient market-rent history to project",
            context=f"Need >={inputs.lag_months} months", inputs_used=["market_rent_growth_yoy_pct"],
            warnings=["Insufficient data"],
        )
    projected = inputs.market_rent_growth_yoy_pct[-inputs.lag_months]
    direction = "cooling" if projected < inputs.current_cpi_shelter_yoy_pct else "reaccelerating"
    return ModelResult(
        model_name="project_shelter_cpi", country="us", as_of=datetime.utcnow(),
        value=round(projected, 2), confidence=0.55,
        interpretation=f"CPI shelter likely converging toward {projected:.2f}% ({direction} from current {inputs.current_cpi_shelter_yoy_pct:.2f}%)",
        context=f"Market rents from {inputs.lag_months} months ago, per the lease-turnover lag (Module 5.1)",
        inputs_used=["market_rent_growth_yoy_pct", "current_cpi_shelter_yoy_pct"],
        warnings=["Mechanical lag projection — assumes historical lease-turnover dynamics hold",
                  "Shelter is ~36% of CPI; this projection therefore drives a large share of forecastable core CPI"],
    )

class PPIPipelineInputs(BaseModel):
    crude_stage_yoy_pct: float
    intermediate_stage_yoy_pct: float
    final_demand_yoy_pct: float
    corporate_margin_trend: str    # "expanding" | "stable" | "compressing"
    demand_condition: str          # "strong" | "neutral" | "weak"

def ppi_pipeline_signal(inputs: PPIPipelineInputs) -> ModelResult:
    """
    Module 5.4: pressure moves crude -> intermediate -> final demand -> CPI.
    Crude rising while final demand is flat = pressure building UPSTREAM,
    likely to arrive downstream later. Pass-through is NOT 1:1 — margin
    absorption in weak-demand/competitive conditions mutes it.
    """
    upstream_building = (inputs.crude_stage_yoy_pct > inputs.intermediate_stage_yoy_pct >
                         inputs.final_demand_yoy_pct)
    pass_through = "muted" if (inputs.demand_condition == "weak" or
                                inputs.corporate_margin_trend == "compressing") else "fuller"
    return ModelResult(
        model_name="ppi_pipeline_signal", country="us", as_of=datetime.utcnow(),
        value={"upstream_pressure_building": upstream_building, "expected_pass_through": pass_through},
        confidence=0.4,
        interpretation=(f"{'Upstream cost pressure building' if upstream_building else 'No clear upstream gradient'}; "
                        f"expected pass-through to CPI: {pass_through}"),
        context="Crude > Intermediate > Final Demand gradient signals pressure moving downstream (Module 5.4)",
        inputs_used=["crude_stage_yoy_pct", "intermediate_stage_yoy_pct", "final_demand_yoy_pct",
                     "corporate_margin_trend", "demand_condition"],
        warnings=["PPI is NOT a 1:1 CPI predictor — margin absorption breaks the link (Module 5.4)"],
    )

class InflationTransmissionInputs(BaseModel):
    inflation_surprise_bp: float
    surprise_driver: str            # "demand" | "supply_shock" | "shelter_lag_mechanical"
    nominal_yield_change_bp: float
    breakeven_change_bp: float

def cross_asset_transmission(inputs: InflationTransmissionInputs) -> ModelResult:
    """
    Module 5.6's transmission map, as explicit directional expectations.
    The critical, non-obvious one: GOLD trades REAL yields, not inflation —
    a hot CPI print with real yields RISING is gold-NEGATIVE, which
    contradicts naive 'gold is an inflation hedge' reasoning.
    """
    real_yield_change = inputs.nominal_yield_change_bp - inputs.breakeven_change_bp
    expectations = {
        "bonds": "down" if inputs.nominal_yield_change_bp > 0 else "up",
        "long_duration_growth_equities": "down" if inputs.nominal_yield_change_bp > 0 else "up",
        "value_vs_growth": "value_outperforms" if inputs.nominal_yield_change_bp > 0 else "growth_outperforms",
        "gold": "down" if real_yield_change > 0 else "up",
        "usd": "up_if_relative_rate_expectations_rose",
    }
    if inputs.surprise_driver == "supply_shock":
        expectations["equities_overall"] = "worst_case_margin_compression_plus_higher_discount_rate"
    elif inputs.surprise_driver == "demand":
        expectations["equities_overall"] = "discount_rate_channel_dominant"
    else:
        expectations["equities_overall"] = "muted_mechanical_lag_effect"
    return ModelResult(
        model_name="cross_asset_transmission", country="us", as_of=datetime.utcnow(),
        value=expectations, confidence=0.45,
        interpretation=f"Transmission map for a {inputs.surprise_driver}-driven {inputs.inflation_surprise_bp:+.0f}bp surprise",
        context=f"Real yield change {real_yield_change:+.0f}bp drives the gold call, NOT the CPI print itself (Module 5.6)",
        inputs_used=["inflation_surprise_bp", "surprise_driver", "nominal_yield_change_bp", "breakeven_change_bp"],
        warnings=["USD direction requires the COUNTERPARTY central bank's reaction too — never a single-country read (Module 5.6/9)"],
    )
```

---

### 20.6 Module 6 — Two Surveys, Beveridge, Openings Ratio, AHE Distortion, Revisions

```python
# src/macro_engine/models/labor_synthesis.py (additions) — Phase 2 backfill

class TwoSurveyInputs(BaseModel):
    nfp_change_thousands: float           # Establishment
    household_employment_change_thousands: float
    unemployment_rate_change_pp: float
    participation_rate_change_pp: float

def two_survey_divergence(inputs: TwoSurveyInputs) -> ModelResult:
    """
    Module 6.1: Establishment counts JOBS, Household counts PEOPLE. They
    diverge, and the divergence is informative — payrolls up WITH
    unemployment up is usually rising participation (labor SUPPLY entering),
    not labor-demand weakness. Reading NFP alone misses this entirely.
    """
    payrolls_up = inputs.nfp_change_thousands > 0
    unemployment_up = inputs.unemployment_rate_change_pp > 0
    participation_up = inputs.participation_rate_change_pp > 0
    if payrolls_up and unemployment_up and participation_up:
        verdict = "PARTICIPATION_DRIVEN_not_weakness"
    elif payrolls_up and unemployment_up and not participation_up:
        verdict = "GENUINE_DIVERGENCE_investigate"
    elif not payrolls_up and unemployment_up:
        verdict = "BROAD_WEAKENING"
    else:
        verdict = "CONSISTENT_STRENGTH"
    return ModelResult(
        model_name="two_survey_divergence", country="us", as_of=datetime.utcnow(),
        value=verdict, confidence=0.6,
        interpretation=f"Two-survey read: {verdict}",
        context="Establishment (jobs) vs Household (people) — always check both before concluding from NFP (Module 6.1)",
        inputs_used=["nfp_change_thousands", "household_employment_change_thousands",
                     "unemployment_rate_change_pp", "participation_rate_change_pp"],
    )

def openings_to_unemployed_ratio(job_openings_thousands: float,
                                  unemployed_persons_thousands: float) -> ModelResult:
    """Fed's explicitly-cited preferred labor-tightness gauge (Module 6.2)."""
    ratio = job_openings_thousands / unemployed_persons_thousands
    if ratio > 1.5:
        tightness = "VERY_TIGHT"
    elif ratio > 1.0:
        tightness = "TIGHT"
    elif ratio > 0.7:
        tightness = "BALANCED"
    else:
        tightness = "SLACK"
    return ModelResult(
        model_name="openings_to_unemployed_ratio", country="us", as_of=datetime.utcnow(),
        value=round(ratio, 3), confidence=0.7,
        interpretation=f"Openings per unemployed worker: {ratio:.2f} ({tightness})",
        context="Explicitly cited by the Fed as a preferred tightness gauge (Module 6.2)",
        inputs_used=["job_openings_thousands", "unemployed_persons_thousands"],
    )

class BeveridgeInputs(BaseModel):
    openings_rate_pct: float
    unemployment_rate_pct: float
    historical_openings_at_this_u: float   # from the pre-shift fitted curve

def beveridge_curve_position(inputs: BeveridgeInputs) -> ModelResult:
    """
    Module 6.2: an OUTWARD shift (more openings needed for the same
    unemployment rate) signals STRUCTURAL mismatch — skills/location/
    industry — not cyclical slack. This matters because structural
    mismatch implies a higher u*, which changes the entire Phillips
    Curve and Taylor Rule calibration.
    """
    shift = inputs.openings_rate_pct - inputs.historical_openings_at_this_u
    if shift > 0.5:
        verdict = "OUTWARD_SHIFT_structural_mismatch"
    elif shift < -0.5:
        verdict = "INWARD_SHIFT_improved_matching"
    else:
        verdict = "ON_CURVE_cyclical"
    return ModelResult(
        model_name="beveridge_curve_position", country="us", as_of=datetime.utcnow(),
        value={"verdict": verdict, "shift_pp": round(shift, 2)}, confidence=0.45,
        interpretation=f"Beveridge position: {verdict} ({shift:+.2f}pp vs historical curve)",
        context="Outward shift = structural, not cyclical — implies a HIGHER u* (Module 6.2)",
        inputs_used=["openings_rate_pct", "unemployment_rate_pct", "historical_openings_at_this_u"],
        warnings=["Structural shift means the Phillips Curve's u* input must be revised UP — propagate to phillips_curve_inflation()"]
                 if verdict.startswith("OUTWARD") else [],
    )

class AHEDistortionInputs(BaseModel):
    ahe_growth_yoy_pct: float
    eci_growth_yoy_pct: float | None       # quarterly ground truth
    low_wage_sector_employment_change_pct: float

def ahe_composition_flag(inputs: AHEDistortionInputs) -> ModelResult:
    """
    Module 6.2: AHE rises mechanically when low-wage jobs are lost
    disproportionately, with nobody receiving a raise (COVID 2020). ECI
    holds job mix fixed and is the ground truth — but is quarterly.
    Flag when AHE and ECI diverge alongside a compositional shift.
    """
    distortion_risk = inputs.low_wage_sector_employment_change_pct < -1.0
    eci_divergence = (inputs.eci_growth_yoy_pct is not None and
                      abs(inputs.ahe_growth_yoy_pct - inputs.eci_growth_yoy_pct) > 0.75)
    flagged = distortion_risk and (eci_divergence or inputs.eci_growth_yoy_pct is None)
    return ModelResult(
        model_name="ahe_composition_flag", country="us", as_of=datetime.utcnow(),
        value={"distortion_flagged": flagged, "ahe_minus_eci_pp":
               round(inputs.ahe_growth_yoy_pct - inputs.eci_growth_yoy_pct, 2) if inputs.eci_growth_yoy_pct else None},
        confidence=0.6,
        interpretation="AHE likely composition-distorted — do not read as genuine wage growth" if flagged
                        else "No composition distortion flagged",
        context="Low-wage job losses inflate AHE without any individual raise (Module 6.2, COVID 2020 case)",
        inputs_used=["ahe_growth_yoy_pct", "eci_growth_yoy_pct", "low_wage_sector_employment_change_pct"],
        warnings=["Prefer ECI for the wage-inflation signal when this flag is set"] if flagged else [],
    )

class RevisionInputs(BaseModel):
    current_month_nfp: float
    prior_month_revision: float
    two_months_ago_revision: float

def nfp_revision_adjusted_read(inputs: RevisionInputs) -> ModelResult:
    """
    Module 6.1: a headline 'beat' bundled with large downward prior-month
    revisions is a WEAKER picture than the headline suggests. Revisions
    are largest exactly at cyclical turning points — when they matter most.
    """
    net_revisions = inputs.prior_month_revision + inputs.two_months_ago_revision
    adjusted = inputs.current_month_nfp + net_revisions
    misleading = (inputs.current_month_nfp > 0 and net_revisions < -50)
    return ModelResult(
        model_name="nfp_revision_adjusted_read", country="us", as_of=datetime.utcnow(),
        value={"headline": inputs.current_month_nfp, "net_revisions": net_revisions,
               "revision_adjusted": adjusted},
        confidence=0.7,
        interpretation=f"Headline {inputs.current_month_nfp:+.0f}k, net revisions {net_revisions:+.0f}k, adjusted {adjusted:+.0f}k",
        context="Prior-month revisions matter as much as the headline (Module 6.1)",
        inputs_used=["current_month_nfp", "prior_month_revision", "two_months_ago_revision"],
        warnings=["Headline beat masked by large downward revisions — the underlying picture is weaker than it appears"]
                 if misleading else [],
    )
```

---

### 20.7 Module 7 — Deflator, GDP/GDI Divergence, LEI

```python
# src/macro_engine/models/gdp_nowcast.py (additions) — Phase 2 backfill

def gdp_deflator(nominal_gdp: float, real_gdp: float) -> ModelResult:
    """
    Deflator = (Nominal/Real)*100. Module 7.1: covers ALL domestic output
    and EXCLUDES imports — so it diverges from CPI/PCE during an imported
    price shock (oil). That divergence tells you whether inflation is
    domestically generated (Fed-addressable) or imported (largely not).
    """
    defl = nominal_gdp / real_gdp * 100
    return ModelResult(
        model_name="gdp_deflator", country="us", as_of=datetime.utcnow(),
        value=round(defl, 3), confidence=0.9,
        interpretation=f"GDP deflator: {defl:.3f}",
        context="Domestic output only, excludes imports — compare vs CPI to separate imported from domestic inflation (Module 7.1)",
        inputs_used=["nominal_gdp", "real_gdp"],
    )

def gdp_gdi_divergence(gdp_growth_pct: float, gdi_growth_pct: float) -> ModelResult:
    """
    Module 7.1: GDP and GDI measure the same thing from opposite sides and
    should match; the statistical discrepancy is real information. When
    they diverge meaningfully, the average is often the better read — and
    the divergence itself warrants investigation, not averaging-away.
    """
    diff = gdp_growth_pct - gdi_growth_pct
    avg = (gdp_growth_pct + gdi_growth_pct) / 2
    significant = abs(diff) > 1.0
    return ModelResult(
        model_name="gdp_gdi_divergence", country="us", as_of=datetime.utcnow(),
        value={"gdp": gdp_growth_pct, "gdi": gdi_growth_pct, "divergence_pp": round(diff, 2),
               "average": round(avg, 2)},
        confidence=0.4 if significant else 0.7,
        interpretation=f"GDP {gdp_growth_pct:.2f}% vs GDI {gdi_growth_pct:.2f}% (diff {diff:+.2f}pp)",
        context="Should be identical in theory; divergence = measurement error worth investigating (Module 7.1)",
        inputs_used=["gdp_growth_pct", "gdi_growth_pct"],
        warnings=["Significant GDP/GDI divergence — one dataset is capturing something the other misses; lower confidence in both"]
                 if significant else [],
    )

class LEIInputs(BaseModel):
    components: dict[str, float]          # component -> 6mo annualized % change
    weights: dict[str, float] | None = None

def lei_composite(inputs: LEIInputs) -> ModelResult:
    """
    Module 7.3: a COMPOSITE, because any single leading indicator
    false-signals. The signal is a sustained, BROAD-BASED decline — a
    decline concentrated in one or two components is much weaker evidence.
    Known to have produced false positives in recent cycles.
    """
    w = inputs.weights or {k: 1.0 / len(inputs.components) for k in inputs.components}
    composite = sum(inputs.components[k] * w.get(k, 0) for k in inputs.components)
    n_declining = sum(1 for v in inputs.components.values() if v < 0)
    breadth = n_declining / len(inputs.components)
    broad_based = breadth >= 0.6
    return ModelResult(
        model_name="lei_composite", country="us", as_of=datetime.utcnow(),
        value={"composite_6mo_annualized": round(composite, 2), "breadth_declining": round(breadth, 2)},
        confidence=0.5 if broad_based else 0.3,
        interpretation=f"LEI composite {composite:+.2f}%, {n_declining}/{len(inputs.components)} components declining",
        context="Broad-based decline is the signal; narrow decline is weak evidence (Module 7.3)",
        inputs_used=list(inputs.components.keys()),
        warnings=["LEI has produced false positives in recent cycles — treat as a probability input, never a deterministic call"],
    )
```

---

### 20.8 Module 8 — Term Premium Decomposition, Auctions, Credit Spread Attribution

```python
# src/macro_engine/models/yield_curve.py (additions) — Phase 2/3 backfill

def decompose_yield(nominal_yield: float, acm_term_premium: float) -> ModelResult:
    """
    Module 8.1: Long yield = E[avg future short rates] + term premium.
    THE critical distinction — a yield rise from the expectations component
    is a Fed-policy-view signal; a rise from term premium is a
    supply/foreign-demand signal and is NOT a hawkish Fed signal.
    Conflating them is a real analytical error.
    """
    expectations_component = nominal_yield - acm_term_premium
    return ModelResult(
        model_name="decompose_yield", country="us", as_of=datetime.utcnow(),
        value={"nominal": nominal_yield, "expectations_component": round(expectations_component, 3),
               "term_premium": acm_term_premium},
        confidence=0.65,
        interpretation=f"Yield {nominal_yield:.2f}% = expectations {expectations_component:.2f}% + term premium {acm_term_premium:.2f}%",
        context="Use NY Fed ACM (FRED: THREEFYTP10). A TP-driven move is NOT a Fed-policy signal (Module 8.1)",
        inputs_used=["nominal_yield", "acm_term_premium"],
        warnings=["Always attribute a yield MOVE to a component before building a thesis on it"],
    )

class AuctionInputs(BaseModel):
    bid_to_cover: float
    bid_to_cover_trailing_avg: float
    indirect_bidder_pct: float
    indirect_bidder_trailing_avg: float
    stop_through_bp: float     # negative = tailed (cleared above expected yield)

def auction_demand_signal(inputs: AuctionInputs) -> ModelResult:
    """
    Module 8.2: auctions are real-time evidence of DURATION DEMAND. A
    weak/tailing auction confirms term-premium-driven yield moves rather
    than expectations-driven ones. Declining indirect-bidder share is the
    foreign-official-demand proxy.
    """
    weak_btc = inputs.bid_to_cover < inputs.bid_to_cover_trailing_avg * 0.95
    tailed = inputs.stop_through_bp < 0
    foreign_fading = inputs.indirect_bidder_pct < inputs.indirect_bidder_trailing_avg - 3.0
    if weak_btc and tailed:
        verdict = "WEAK_AUCTION_term_premium_pressure"
    elif not weak_btc and not tailed:
        verdict = "STRONG_AUCTION"
    else:
        verdict = "MIXED"
    return ModelResult(
        model_name="auction_demand_signal", country="us", as_of=datetime.utcnow(),
        value={"verdict": verdict, "foreign_demand_fading": foreign_fading},
        confidence=0.6,
        interpretation=f"Auction: {verdict}" + (" | indirect-bidder share fading" if foreign_fading else ""),
        context="Weak auctions corroborate term-premium-driven (not expectations-driven) yield moves (Module 8.2)",
        inputs_used=["bid_to_cover", "indirect_bidder_pct", "stop_through_bp"],
        warnings=["A single tailing auction can be a temporary liquidity artifact — require persistence before concluding structural demand shift"],
    )

class CreditSpreadInputs(BaseModel):
    hy_spread_bp: float
    hy_spread_change_bp: float
    ig_spread_change_bp: float
    equity_vol_change_pct: float
    default_rate_trend: str      # "rising" | "stable" | "falling"

def credit_spread_attribution(inputs: CreditSpreadInputs) -> ModelResult:
    """
    Module 8.3: spread widening is EITHER fundamental (default risk
    genuinely rising) OR technical (risk-aversion / flight-to-quality,
    LTCM-1998 style). These have opposite forward implications —
    fundamental widening is sticky; panic widening snaps back. Never treat
    them as the same signal.
    """
    fundamental = inputs.default_rate_trend == "rising"
    technical = inputs.equity_vol_change_pct > 20 and inputs.default_rate_trend != "rising"
    if fundamental and not technical:
        attribution, durability = "FUNDAMENTAL", "sticky_slow_to_reverse"
    elif technical and not fundamental:
        attribution, durability = "TECHNICAL_RISK_AVERSION", "can_snap_back_sharply"
    elif fundamental and technical:
        attribution, durability = "BOTH", "elevated_concern"
    else:
        attribution, durability = "UNCLEAR", "investigate"
    return ModelResult(
        model_name="credit_spread_attribution", country="us", as_of=datetime.utcnow(),
        value={"attribution": attribution, "expected_durability": durability,
               "hy_spread_bp": inputs.hy_spread_bp},
        confidence=0.45,
        interpretation=f"Spread widening attributed to: {attribution} ({durability})",
        context="Fundamental vs technical widening have OPPOSITE forward implications (Module 8.3, LTCM 1998)",
        inputs_used=["hy_spread_change_bp", "ig_spread_change_bp", "equity_vol_change_pct", "default_rate_trend"],
    )
```

---

### 20.9 Module 9 — UIP, PPP, Intervention Asymmetry

```python
# src/macro_engine/models/fx_carry.py (additions) — Phase 5+

def uip_expected_move(i_domestic: float, i_foreign: float) -> ModelResult:
    """
    UIP: E[%dS] ~= i_d - i_f. Module 9.1 — this FAILS empirically (forward
    premium puzzle), and that failure IS the carry trade's edge. This
    function exists to compute the UIP benchmark so a carry thesis can be
    stated explicitly as a bet AGAINST it, not to be used as a forecast.
    """
    expected = i_domestic - i_foreign
    return ModelResult(
        model_name="uip_expected_move", country="us", as_of=datetime.utcnow(),
        value=round(expected, 3), confidence=0.15,
        interpretation=f"UIP predicts the high-rate currency depreciates ~{abs(expected):.2f}%",
        context="DELIBERATELY LOW CONFIDENCE — UIP fails empirically; this is the benchmark a carry trade bets against (Module 9.1)",
        inputs_used=["i_domestic", "i_foreign"],
        warnings=["Do NOT use as a point forecast. Its empirical failure is the carry premium."],
    )

def ppp_valuation(spot_rate: float, ppp_implied_rate: float) -> ModelResult:
    """
    Module 9.2: PPP is a MULTI-YEAR anchor, never a timing tool.
    Deviations persist for years. Confidence is capped deliberately low
    for any horizon under several years.
    """
    deviation_pct = (spot_rate - ppp_implied_rate) / ppp_implied_rate * 100
    status = "overvalued" if deviation_pct > 0 else "undervalued"
    return ModelResult(
        model_name="ppp_valuation", country="global", as_of=datetime.utcnow(),
        value=round(deviation_pct, 2), confidence=0.2,
        interpretation=f"Currency {abs(deviation_pct):.1f}% {status} vs PPP",
        context="MULTI-YEAR anchor only. Deviations persist for years (Module 9.2)",
        inputs_used=["spot_rate", "ppp_implied_rate"],
        warnings=["NEVER use PPP for tactical timing — matching the tool's horizon to the trade's horizon is the discipline (Module 9.2)"],
    )

class InterventionCapacityInputs(BaseModel):
    country: str
    direction: str                      # "strengthen_own_currency" | "weaken_own_currency"
    fx_reserves_usd_bn: float | None
    reserves_to_gdp_pct: float | None

def intervention_capacity(inputs: InterventionCapacityInputs) -> ModelResult:
    """
    Module 9.3's ASYMMETRY — the single most important intervention fact:
      - Weakening own currency: print + sell own currency => MECHANICALLY
        UNLIMITED ammunition (but accumulates balance-sheet/inflation cost,
        the SNB-2015 failure mode — abandonment by cost, not by exhaustion).
      - Strengthening own currency: must SELL FINITE FX RESERVES =>
        CAPITAL-CONSTRAINED, breakable (Black Wednesday failure mode).
    """
    if inputs.direction == "weaken_own_currency":
        capacity, conf = "UNLIMITED_AMMUNITION_but_costly", 0.8
        note = "Can print unlimited own currency. Failure mode is cost-driven ABANDONMENT (SNB 2015), not exhaustion."
    else:
        capacity, conf = "RESERVE_CONSTRAINED_breakable", 0.7
        note = "Must sell finite reserves. Failure mode is EXHAUSTION under speculative attack (Black Wednesday 1992)."
    return ModelResult(
        model_name="intervention_capacity", country=inputs.country, as_of=datetime.utcnow(),
        value={"capacity": capacity, "reserves_usd_bn": inputs.fx_reserves_usd_bn},
        confidence=conf,
        interpretation=f"{inputs.country} defending via '{inputs.direction}': {capacity}",
        context=note, inputs_used=["direction", "fx_reserves_usd_bn", "reserves_to_gdp_pct"],
        warnings=["Reserve-constrained defenses are breakable — pair with check_trilemma_tension() before any peg-related thesis"]
                 if capacity.startswith("RESERVE") else
                 ["Unlimited-ammunition defenses still fail via accumulated cost — do not assume permanence (SNB 2015)"],
    )
```

---

### 20.10 Module 10 — Copper/China, Metals Complex Divergence

```python
# src/macro_engine/models/commodities.py (additions) — Phase 5+, INFORMATIONAL ONLY

class MetalsComplexInputs(BaseModel):
    copper_change_pct: float
    iron_ore_change_pct: float
    aluminum_change_pct: float

def metals_complex_divergence(inputs: MetalsComplexInputs) -> ModelResult:
    """
    Module 10.3's diagnostic: metals diverging tells you WHICH driver is
    active. Iron ore falling hardest + copper falling + aluminum flat =>
    China construction/property specific, NOT broad global industrial
    weakness (aluminum's stability is the discriminating evidence, since
    it is energy-cost driven with different end-use exposure).
    """
    construction_specific = (inputs.iron_ore_change_pct < inputs.copper_change_pct < 0
                              and abs(inputs.aluminum_change_pct) < 2.0)
    broad_industrial = all(x < -2.0 for x in
                           [inputs.copper_change_pct, inputs.iron_ore_change_pct, inputs.aluminum_change_pct])
    if construction_specific:
        verdict = "CHINA_CONSTRUCTION_SPECIFIC"
    elif broad_industrial:
        verdict = "BROAD_INDUSTRIAL_WEAKNESS"
    else:
        verdict = "MIXED_no_clear_pattern"
    return ModelResult(
        model_name="metals_complex_divergence", country="global", as_of=datetime.utcnow(),
        value=verdict, confidence=0.4,
        interpretation=f"Metals complex signal: {verdict}",
        context="Divergence across the complex identifies the driver; aluminum stability discriminates construction-specific from broad (Module 10.3)",
        inputs_used=["copper_change_pct", "iron_ore_change_pct", "aluminum_change_pct"],
        warnings=["INFORMATIONAL ONLY — no commodity positions in production universe",
                  "Copper is ~50% China demand — never read it as a clean GLOBAL growth proxy (Module 10.3)"],
    )
```

---

### 20.11 Module 12 — Bayesian Update, Expected Value, Full Scorecard

```python
# src/macro_engine/models/probability.py (NEW FILE) — Phase 2 backfill

class BayesInputs(BaseModel):
    prior: float                  # P(A)
    likelihood_given_true: float  # P(B|A)
    likelihood_given_false: float # P(B|~A)

def bayesian_update(inputs: BayesInputs) -> ModelResult:
    """
    P(A|B) = P(B|A)*P(A) / [P(B|A)*P(A) + P(B|~A)*P(~A)]
    Module 12.3. Forces EXPLICIT priors and likelihood ratios, which is
    what prevents confirmation bias and over-reaction to weak evidence.
    A strong prior REQUIRES a high likelihood ratio to move meaningfully —
    that is the math, not a disposition.
    """
    p_a, p_not_a = inputs.prior, 1 - inputs.prior
    p_b = inputs.likelihood_given_true * p_a + inputs.likelihood_given_false * p_not_a
    if p_b == 0:
        raise ValueError("P(B) = 0; evidence impossible under both hypotheses")
    posterior = (inputs.likelihood_given_true * p_a) / p_b
    lr = (inputs.likelihood_given_true / inputs.likelihood_given_false
          if inputs.likelihood_given_false > 0 else float("inf"))
    return ModelResult(
        model_name="bayesian_update", country="us", as_of=datetime.utcnow(),
        value={"prior": inputs.prior, "posterior": round(posterior, 4),
               "likelihood_ratio": round(lr, 2) if lr != float("inf") else None,
               "shift_pp": round((posterior - inputs.prior) * 100, 1)},
        confidence=0.8,
        interpretation=f"Prior {inputs.prior:.0%} -> posterior {posterior:.0%} (LR {lr:.2f})",
        context="Explicit prior + likelihood ratio — prevents confirmation bias and noise over-reaction (Module 12.3)",
        inputs_used=["prior", "likelihood_given_true", "likelihood_given_false"],
        warnings=["Likelihood ratio near 1.0 — this evidence is nearly uninformative; the posterior shift is noise"]
                 if 0.8 < lr < 1.25 else [],
    )

def expected_value(scenarios: list["ScenarioOutcome"]) -> ModelResult:
    """EV = SUM(p_i * payoff_i). Module 12.4 — necessary but NOT sufficient for sizing."""
    total_p = sum(s.probability for s in scenarios)
    if abs(total_p - 1.0) > 0.01:
        raise ValueError(f"Scenario probabilities sum to {total_p}, must sum to 1.0")
    ev = sum(s.probability * s.payoff_estimate for s in scenarios)
    worst = min(scenarios, key=lambda s: s.payoff_estimate)
    return ModelResult(
        model_name="expected_value", country="us", as_of=datetime.utcnow(),
        value={"ev": round(ev, 2), "worst_case_payoff": worst.payoff_estimate,
               "worst_case_probability": worst.probability},
        confidence=0.6,
        interpretation=f"EV {ev:+.2f}, worst case {worst.payoff_estimate:+.2f} at {worst.probability:.0%}",
        context="Positive EV is necessary but NOT sufficient — survivability of the tail governs sizing (Module 12.4, LTCM)",
        inputs_used=["scenarios"],
        warnings=["Positive EV with a large tail loss — size for SURVIVAL of the tail, not for the average (LTCM lesson)"]
                 if ev > 0 and worst.payoff_estimate < -2 * abs(ev) else [],
    )

class ScorecardInputs(BaseModel):
    growth_signal: int        # -1 easing-implying, 0 neutral, +1 tightening-implying
    inflation_signal: int
    financial_conditions_signal: int
    policy_gap_signal: int
    independent_source_families: int

def four_pillar_scorecard(inputs: ScorecardInputs) -> ModelResult:
    """
    Module 12.2's capstone. Convergence classified by agreement AND by
    genuine source independence (Module 13) — five agreeing signals from
    ONE release family is weaker than two from genuinely different ones.
    CONFLICTED is a first-class outcome that must block trade construction.
    """
    signals = [inputs.growth_signal, inputs.inflation_signal,
               inputs.financial_conditions_signal, inputs.policy_gap_signal]
    non_zero = [s for s in signals if s != 0]
    if not non_zero:
        return ModelResult(
            model_name="four_pillar_scorecard", country="us", as_of=datetime.utcnow(),
            value="NO_SIGNAL", confidence=0.2,
            interpretation="All four pillars neutral — no directional signal",
            context="No actionable read", inputs_used=["growth_signal", "inflation_signal",
                                                        "financial_conditions_signal", "policy_gap_signal"],
        )
    has_up, has_down = any(s > 0 for s in non_zero), any(s < 0 for s in non_zero)
    agree_frac = max(sum(1 for s in non_zero if s > 0),
                     sum(1 for s in non_zero if s < 0)) / len(non_zero)

    if has_up and has_down and (inputs.growth_signal * inputs.inflation_signal < 0):
        classification, conf = "CONFLICTED", 0.2
    elif agree_frac >= 0.9 and inputs.independent_source_families >= 3:
        classification, conf = "HIGH", 0.75
    elif agree_frac >= 0.75 and inputs.independent_source_families >= 2:
        classification, conf = "MEDIUM", 0.5
    else:
        classification, conf = "LOW", 0.3

    return ModelResult(
        model_name="four_pillar_scorecard", country="us", as_of=datetime.utcnow(),
        value={"classification": classification, "agreement_fraction": round(agree_frac, 2),
               "independent_families": inputs.independent_source_families},
        confidence=conf,
        interpretation=f"Four-pillar convergence: {classification}",
        context="Weighted by INDEPENDENT source families, not raw signal count (Modules 12.2/13)",
        inputs_used=["growth_signal", "inflation_signal", "financial_conditions_signal",
                     "policy_gap_signal", "independent_source_families"],
        warnings=["CONFLICTED — growth and inflation point opposite ways. This MUST block trade construction (Module 12.2)"]
                 if classification == "CONFLICTED" else
                 ["Agreement is high but source independence is low — likely redundant evidence, not genuine convergence"]
                 if agree_frac >= 0.9 and inputs.independent_source_families < 3 else [],
    )
```

---

### 20.12 Module 15 — Cross-Market RV Constructor

```python
# src/macro_engine/models/yield_curve.py (addition) — Phase 3 backfill

class CrossMarketRVInputs(BaseModel):
    market_a: str
    market_b: str
    duration_a: float
    duration_b: float
    target_notional_a: float
    correlation_normal: float
    correlation_stressed: float = 0.9

def construct_cross_market_rv(inputs: CrossMarketRVInputs) -> ModelResult:
    """
    Module 15.3: long A / short B, duration-matched so the common global
    factor cancels and only the RELATIVE view remains. MANDATORY: report
    the stressed-correlation P&L alongside the normal case — the hedge is
    a MODELING ASSUMPTION, and its failure is correlated with exactly the
    moments you can least afford it (LTCM 1998).
    """
    notional_b = inputs.target_notional_a * (inputs.duration_a / inputs.duration_b)
    hedge_effectiveness_normal = inputs.correlation_normal
    hedge_effectiveness_stressed = inputs.correlation_stressed
    degradation = hedge_effectiveness_normal - hedge_effectiveness_stressed
    return ModelResult(
        model_name="construct_cross_market_rv", country="global", as_of=datetime.utcnow(),
        value={"notional_a_long": inputs.target_notional_a, "notional_b_short": round(notional_b, 2),
               "correlation_normal": inputs.correlation_normal,
               "correlation_stressed": inputs.correlation_stressed,
               "hedge_degradation": round(degradation, 3)},
        confidence=0.5,
        interpretation=f"Long {inputs.market_a} {inputs.target_notional_a}, short {inputs.market_b} {notional_b:.2f} (duration-matched)",
        context="Common factor cancels ONLY if correlation holds — it does not hold in crisis (Module 15.3)",
        inputs_used=["duration_a", "duration_b", "target_notional_a", "correlation_normal"],
        warnings=["HEDGE IS A MODELING ASSUMPTION, NOT A GUARANTEE — correlation breakdown is correlated with crisis (LTCM 1998)",
                  "Lower apparent risk invites HIGHER leverage — that combination is the actual LTCM failure mechanism"],
    )
```

---

### 20.13 Module 17 — Volatility Targeting

```python
# src/macro_engine/portfolio/risk_budget.py (addition) — Phase 4 backfill

class VolTargetInputs(BaseModel):
    target_vol_annualized: float
    current_portfolio_vol: float
    current_gross_exposure: float
    limits: "RiskLimits"

def volatility_target_scaling(inputs: VolTargetInputs) -> ModelResult:
    """
    Module 17.2: scale = target_vol / current_vol. Hard constraints ALWAYS
    override the scaling result. Also surfaces the industry-wide reflexivity
    risk: when many funds run similar rules, a vol spike triggers
    simultaneous de-risking, which itself amplifies the vol spike.
    """
    if inputs.current_portfolio_vol <= 0:
        raise ValueError("current_portfolio_vol must be > 0")
    raw_scale = inputs.target_vol_annualized / inputs.current_portfolio_vol
    scaled_exposure = inputs.current_gross_exposure * raw_scale
    max_exposure = inputs.limits.max_leverage
    final_exposure = min(scaled_exposure, max_exposure)
    clipped = final_exposure < scaled_exposure
    return ModelResult(
        model_name="volatility_target_scaling", country="us", as_of=datetime.utcnow(),
        value={"raw_scale": round(raw_scale, 3), "scaled_exposure": round(scaled_exposure, 3),
               "final_exposure": round(final_exposure, 3), "clipped_by_limits": clipped},
        confidence=0.7,
        interpretation=f"Vol-target scale {raw_scale:.2f}x -> exposure {final_exposure:.2f}" +
                        (" (CLIPPED by leverage limit)" if clipped else ""),
        context="Hard constraints always win over vol-target scaling (Module 17.2)",
        inputs_used=["target_vol_annualized", "current_portfolio_vol", "current_gross_exposure"],
        warnings=["De-risking into a vol spike is industry-reflexive — many funds sell simultaneously, amplifying the move (Module 17.2, Aug 2024)"]
                 if raw_scale < 0.8 else [],
    )
```

---

### 20.14 Mandatory Golden Tests for Section 20

Every function above requires a hand-verified golden test. Minimum set:

- `test_convexity_hand_calculation` — 3yr 6% coupon 8% yield, verify against manual computation
- `test_price_change_with_convexity_asymmetry` — assert a −100bp move produces a LARGER absolute gain than a +100bp move produces a loss
- `test_savings_investment_identity_balances` — assert (S−I)+(T−G) equals the implied current account exactly
- `test_phillips_curve_at_nairu` — when u == u*, assert π == π^e exactly
- `test_potential_gdp_cobb_douglas` — A=1, K=100, L=100, α=0.3 must return exactly 100.0
- `test_growth_accounting_sums` — assert potential growth equals labor + productivity exactly
- `test_laspeyres_overstates_vs_paasche` — construct a genuine substitution scenario; assert Laspeyres > Paasche
- `test_fisher_between_laspeyres_and_paasche` — assert Paasche ≤ Fisher ≤ Laspeyres
- `test_shelter_lag_projection_uses_correct_month` — assert it reads index `[-lag_months]`, not the latest value
- `test_bayesian_update_matches_hand_calculation` — prior 0.40, P(B|A) 0.70, P(B|¬A) 0.20 must return posterior 0.70 exactly
- `test_bayesian_update_lr_near_one_warns` — assert the uninformative-evidence warning fires
- `test_expected_value_rejects_bad_probabilities` — probabilities not summing to 1.0 must raise
- `test_four_pillar_conflicted_blocks_trade` — growth and inflation opposed must return CONFLICTED
- `test_four_pillar_redundant_sources_warns` — high agreement with <3 independent families must warn
- `test_openings_to_unemployed_ratio` — verify against a hand-computed ratio
- `test_gdp_deflator` — nominal 21500, real 20000 must return exactly 107.5
- `test_intervention_capacity_asymmetry` — assert "strengthen" returns RESERVE_CONSTRAINED and "weaken" returns UNLIMITED
- `test_uip_confidence_is_low` — assert confidence ≤ 0.2 (its empirical failure is the point)
- `test_ppp_confidence_is_low` — assert confidence ≤ 0.2 and the no-tactical-timing warning fires
- `test_cross_market_rv_always_warns_correlation` — assert the LTCM warning is ALWAYS present, unconditionally
- `test_vol_target_respects_hard_limits` — engineer a scale that would exceed max_leverage; assert it clips
- `test_repo_stress_acute_threshold` — SOFR 25bp above IORB must return ACUTE_REPO_STRESS
- `test_decompose_yield_components_sum` — assert expectations + term premium equals the nominal yield exactly
- `test_two_survey_participation_driven` — payrolls up + unemployment up + participation up must return PARTICIPATION_DRIVEN
- `test_minsky_ponzi_drift_flags` — loosening standards + risky credit outgrowing total must flag PONZI_DRIFT_WARNING
- `test_metals_divergence_china_specific` — iron ore worst, copper down, aluminum flat must return CHINA_CONSTRUCTION_SPECIFIC
## 21. Input Sourcing Registry, Mandatory Implementation Process, and the No-Prototyping Rule

**This section closes the last structural loophole in this specification.**
Sections 6, 15, 17, and 20 define 103 functions consuming 212 distinct
input fields. Section 5.2 only documents the source for roughly 20 of them.
Every remaining input is a place where an implementing agent would have to
**guess** — and guessing is prohibited in this system.

---

### 21.0 THE NO-PROTOTYPING RULE (READ FIRST — THIS OVERRIDES CONVENIENCE)

This is a production financial system. Its outputs inform decisions that
risk real capital.

**Prohibited, without exception:**

1. **No function may be marked complete until it has been executed against
   real data from its real source.** A function that passes a unit test on
   synthetic inputs but has never seen a live series is NOT complete. Unit
   tests prove the arithmetic; live execution proves the wiring, the units,
   the nulls, the frequency, and the sign conventions.
2. **No placeholder, mock, dummy, or hardcoded return value may survive
   into a "complete" function.** If a real value cannot be sourced, the
   function raises `NotImplementedError` with an explicit reason — it does
   NOT return a plausible-looking number.
3. **No input may be invented.** If an input's source is not defined in
   Section 21.1 below, the agent MUST stop and ask, not assume. Filling an
   input with a "reasonable default" that was never specified is the single
   most dangerous failure mode available to this system, because the output
   will look completely normal while being silently wrong.
4. **No function may silently substitute a different series** for the one
   specified. The supercore incident (Section 15.20 / O-8) — where "all
   items less shelter" was labeled as supercore — is the canonical example
   of this failure and must never recur.
5. **Real-data validation must be recorded**, not just performed. Every
   function's completion report includes: the real series used, the actual
   values retrieved, the date of retrieval, and the function's output on
   that real input, with a sanity assessment of whether that output is
   economically plausible.

**A function is DONE when, and only when:**
- [ ] Implemented exactly as specified (no deviation without a logged decision)
- [ ] Unit test with hand-verified expected values passes
- [ ] Executed against real data from its documented source
- [ ] The real-data output is economically plausible and that assessment is written down
- [ ] Every `warnings` condition specified has been triggered at least once in a test
- [ ] `ruff` and `mypy --strict` clean
- [ ] Documented in `docs/BUILD_STATE.md` with its real-data validation record

---

### 21.1 Input Sourcing Registry — Every Input Has Exactly One Defined Source Type

Every model input falls into exactly one of five source types. **No input
may exist outside these five categories.**

| Type | Meaning | Rule |
|---|---|---|
| **LIVE** | Fetched from a documented external series | Must have a verified series ID (Phase 0 discipline) |
| **DERIVED** | Computed by another function in this spec | Must name the producing function |
| **CONFIG** | A parameter in `config/settings.yaml` | Must have a documented default AND a note on calibration status |
| **MANUAL** | Human-entered, no API exists | Must have a manual-entry CLI path and appear as "Manual Entry" in any output |
| **BLOCKED** | No source exists — function cannot run | Function raises `NotImplementedError`; must appear in `OPEN_ISSUES.md` |

#### Module 1–2 inputs

| Input | Type | Source |
|---|---|---|
| `money_supply_growth_pct` | LIVE | FRED `M2SL`, computed as YoY % change |
| `velocity_change_pct` | DERIVED | FRED `M2V` YoY % change (verify series exists in Phase 0) |
| `real_output_growth_pct` | LIVE | FRED `GDPC1` YoY % change |
| `coupon`, `face_value`, `yield_rate`, `n_periods` | LIVE/CONFIG | Instrument terms; yield from Treasury curve |
| `sofr` | LIVE | OpenBB `fixedincome/rate/sofr` (verified Phase 1) |
| `iorb` | LIVE | OpenBB `fixedincome/rate/iorb` (verified Phase 1) |
| `on_rrp_rate` | LIVE | FRED `RRPONTSYD` (verified Phase 1) |
| `fed_funds_effective` | LIVE | FRED `FEDFUNDS` / OpenBB `fixedincome/rate/effr` |

#### Module 3 inputs

| Input | Type | Source |
|---|---|---|
| `private_saving`, `private_investment` | LIVE | BEA NIPA tables (verify exact table in Phase 0) |
| `tax_revenue`, `government_spending` | LIVE | BEA NIPA / FRED `W006RC1Q027SBEA`, `FGEXPND` (VERIFY) |
| `fiscal_deficit_pct_gdp` | DERIVED | From the two above / nominal GDP |
| `fiscal_deficit_avg_pct_gdp` | CONFIG | `settings.yaml: policy_mix.fiscal_deficit_avg_pct_gdp` — trailing 10yr average, recompute annually |
| `inflation_expectations` (π^e) | LIVE | 5yr breakeven (FRED `T5YIE`) as market-based proxy; UMich `MICH` as survey cross-check |
| `nairu` (u*) | **CONFIG** | `settings.yaml: phillips.nairu` — **NOT OBSERVABLE.** Default 4.4 (CBO estimate). MUST track CBO revisions; MUST propagate its uncertainty into every downstream confidence value. |
| `beta` (Phillips sensitivity) | CONFIG | `settings.yaml: phillips.beta`, default 0.5, **uncalibrated** |
| `total_factor_productivity` (A) | **BLOCKED → CONFIG** | No direct series. Either (a) back out from the production function using known Y, K, L, or (b) use CBO's published potential-GDP series directly (FRED `GDPPOT`) and skip Cobb-Douglas entirely. **Prefer (b) in Phase 2** — log as decision. |
| `capital_stock` (K) | LIVE | BEA Fixed Assets tables (VERIFY availability in Phase 0) — or unused if using `GDPPOT` per above |
| `labor_input` (L) | LIVE | FRED `CLF16OV` (civilian labor force) or `PAYEMS` — document which |
| `alpha` | CONFIG | `settings.yaml: production_function.alpha`, default 0.3, conventional |
| `labor_force_growth_pct` | DERIVED | YoY % change of `CLF16OV` |
| `productivity_growth_pct` | LIVE | FRED `OPHNFB` (nonfarm business output per hour) YoY (VERIFY) |
| `lending_standards_net_tightening_pct` | LIVE | OpenBB `economy/survey/sloos` (route confirmed in Phase 1) |
| `risky_credit_growth_pct`, `total_credit_growth_pct` | **BLOCKED** | No clean free series for leveraged-loan growth. Raise `NotImplementedError`; log in `OPEN_ISSUES.md`. Do NOT substitute total credit growth as a proxy. |

#### Module 4 inputs

| Input | Type | Source |
|---|---|---|
| `r_star` | **CONFIG** | `settings.yaml: policy.r_star`, default 0.5. **NOT OBSERVABLE.** Track NY Fed Holston-Laubach-Williams published estimates; Phase 5+ replaces with Kalman estimate. Its uncertainty is the single largest driver of policy-rule dispersion. |
| `pi_current` | DERIVED | From `inflation_nowcast` — document whether headline or core is used (MUST be explicit) |
| `pi_target` | CONFIG | `settings.yaml: policy.pi_target`, 2.0 |
| `output_gap` | DERIVED | `output_gap()` |
| `i_prev` | LIVE | `FEDFUNDS`, prior period |
| `output_gap_change` | DERIVED | Current minus prior `output_gap()` |
| `balance_sheet_level`, `balance_sheet_change_3mo` | LIVE | FRED `WALCL` |
| `reserve_balances`, `reserve_balances_change_3mo` | LIVE | FRED `WRESBAL` |
| `prior_text`, `current_text` (statement diff) | MANUAL/LIVE | federalreserve.gov RSS. Phase 5+. |

#### Module 5 inputs

| Input | Type | Source |
|---|---|---|
| `cpi_headline_mom`, `cpi_core_mom` | LIVE | BLS `CUUR0000SA0`, `CUUR0000SA0L1E` |
| `pce_core_mom` | LIVE | BEA / FRED `PCEPILFE` |
| `*_direction` fields | DERIVED | Sign of the corresponding MoM change |
| `supercore_direction` | **BLOCKED** | Per O-8 — pass `None`. Classifier must degrade to 3 measures. |
| `trimmed_mean_direction` | **BLOCKED → MANUAL** | Dallas Fed publishes separately, not in BLS/OpenBB. Manual entry or Phase 5+ direct fetch. |
| `median_cpi_direction` | **BLOCKED → MANUAL** | Cleveland Fed, same as above. |
| `market_rent_growth_yoy_pct` | **MANUAL** | Zillow ZORI / Apartment List — no OpenBB route. Manual CSV import; document cadence. |
| `current_cpi_shelter_yoy_pct` | LIVE | BLS shelter sub-index (VERIFY exact series ID in Phase 0) |
| `lag_months` | CONFIG | `settings.yaml: inflation.shelter_lag_months`, default 15 |
| `crude_stage_yoy_pct`, `intermediate_stage_yoy_pct`, `final_demand_yoy_pct` | LIVE | BLS PPI staged series (VERIFY each) |
| `corporate_margin_trend` | **MANUAL** | No clean free series. Human assessment, documented. |
| `demand_condition` | DERIVED | From `regime` state — map explicitly, do not hand-assess |
| `current_prices`, `base_prices`, `base_quantities`, `current_quantities` | **BLOCKED** | Raw CPI microdata is not publicly available. `laspeyres_index`/`paasche_index`/`fisher_index` are **reference implementations for testing and education only** — they will never run on real BLS microdata in this system. Mark them clearly as such. |

#### Module 6 inputs

| Input | Type | Source |
|---|---|---|
| `weekly_initial_claims` | LIVE | FRED `ICSA` |
| `trailing_3mo_avg` | DERIVED | Computed from `ICSA` |
| `continuing_claims_rising` | DERIVED | Sign of `CCSA` trend |
| `jolts_openings_yoy_pct` | DERIVED | From FRED `JTSJOL` |
| `jolts_quits_level_percentile` | DERIVED | Percentile of `JTSQUR` vs trailing 3yr |
| `nfp_3m_avg` | DERIVED | 3-month average of `PAYEMS` change |
| `nfp_change_thousands` | LIVE | `PAYEMS` MoM change |
| `household_employment_change_thousands` | LIVE | FRED `CE16OV` MoM change |
| `unemployment_rate_change_pp` | LIVE | FRED `UNRATE` |
| `participation_rate_change_pp` | LIVE | FRED `CIVPART` |
| `job_openings_thousands` | LIVE | `JTSJOL` |
| `unemployed_persons_thousands` | LIVE | FRED `UNEMPLOY` |
| `openings_rate_pct` | LIVE | FRED `JTSJOR` (VERIFY) |
| `historical_openings_at_this_u` | **CONFIG** | `settings.yaml: beveridge.pre_covid_curve` — a fitted lookup table from pre-2020 data. Phase 5+ can refit. **Must be documented as a fitted assumption, not an observation.** |
| `ahe_growth_yoy_pct` | LIVE | FRED `AHETPI` / `AWHAETP` (confirm which in Phase 0) |
| `eci_growth_yoy_pct` | LIVE | FRED `ECIWAG` (quarterly; pass `None` between releases) |
| `low_wage_sector_employment_change_pct` | **MANUAL/DERIVED** | Requires sector-level payroll decomposition. If not cleanly available, pass a documented human assessment or raise. |
| `prior_month_revision`, `two_months_ago_revision` | DERIVED | **Requires vintage storage** — compute from the difference between the currently-published value and what was published previously. Depends on Phase 1's Parquet point-in-time records. Before sufficient vintage history accumulates, this returns `None`, not zero. |

#### Module 7–8 inputs

| Input | Type | Source |
|---|---|---|
| `actual_gdp` | LIVE | FRED `GDPC1` (real) — per D-2.1 use FRED levels, not econdb growth columns |
| `potential_gdp` | LIVE | FRED `GDPPOT` (CBO) — preferred over computing Cobb-Douglas |
| `nominal_gdp`, `real_gdp` | LIVE | FRED `GDP`, `GDPC1` |
| `gdi_growth_pct` | LIVE | BEA GDI (VERIFY series) |
| `retail_sales_mom` | LIVE | FRED `RSAFS` (VERIFY) |
| `durable_goods_mom` | LIVE | FRED `DGORDER` (VERIFY) |
| `trade_balance_change` | LIVE | FRED `BOPGSTB` (VERIFY) |
| `components` (LEI) | **MANUAL** | Conference Board LEI is licensed. Either manual entry of the published composite, or build an in-house composite from free components (claims, permits, curve slope, S&P 500) — **if in-house, it must NOT be called "LEI"**, it is a custom proxy. |
| `tenors` (yield curve) | LIVE | Treasury.gov / FRED `DGS*` |
| `nominal`, `tips_real` | LIVE | `DGS10` / `DFII10` — **5yr is the shortest breakeven** (D-2.1) |
| `acm_term_premium` | LIVE | NY Fed ACM direct CSV (FRED `THREEFYTP10` as alternate — verify which is current) |
| `bid_to_cover`, `indirect_bidder_pct`, `stop_through_bp` | LIVE | TreasuryDirect auction results API |
| `bid_to_cover_trailing_avg`, `indirect_bidder_trailing_avg` | DERIVED | Trailing average of the above; **requires accumulated history** |
| `hy_spread_bp` | LIVE | FRED `BAMLH0A0HYM2` |
| `ig_spread_change_bp` | LIVE | FRED `BAMLC0A0CM` or `BAA10Y` |
| `equity_vol_change_pct` | LIVE | VIX |
| `default_rate_trend` | **MANUAL** | No clean free real-time series. Human assessment or raise. |

#### Module 9–11 inputs

| Input | Type | Source |
|---|---|---|
| `spot`, `forward` | LIVE | IBKR or FX provider; forwards may be BLOCKED if unavailable |
| `i_domestic`, `i_foreign` | LIVE | Respective policy rates / short rates |
| `ppp_implied_rate` | **LIVE** | World Bank REST `PA.NUS.PPP`, direct (not OpenBB). **Upgraded from BLOCKED → MANUAL at D-117**: the "no clean free API" premise was measured false (D-043's FALSE-BLOCK class; `docs/PLAN_ppp_source.md`). The estimand is the RATIO `factor(domestic)/factor(foreign)`; the euro container is **DEU** (the World Bank's EMU aggregate measures 0 points, so the substitute is a recorded decision). A **disclosed vintage, not a point-in-time vintage** — the World Bank has no point-in-time selector. |
| `rate_differential` | DERIVED | i_domestic − i_foreign |
| `realized_vol_annualized` | DERIVED | `realized_vol_simple()` |
| `vix_level` | LIVE | CBOE / IBKR |
| `us_growth_surprise` | DERIVED | Actual vs consensus — **requires a consensus-estimate source, which is BLOCKED on free tiers.** Either manual entry or use GDPNow-vs-actual as an imperfect proxy, documented as such. |
| `current_account_pct_gdp` | LIVE | IMF IFS / World Bank REST (direct, not OpenBB) |
| `usd_denominated_debt_share` | LIVE | World Bank International Debt Statistics |
| `reserves_to_short_term_external_debt` | DERIVED | IMF reserves / World Bank ST external debt |
| `real_yield_change_bp` | DERIVED | Change in `DFII10` |
| `central_bank_net_purchases_trend` | **MANUAL** | World Gold Council, quarterly, no free API |
| `crisis_indicator` | DERIVED | From VIX threshold + credit-spread threshold, both configurable |
| `copper_change_pct`, `iron_ore_change_pct`, `aluminum_change_pct` | LIVE/BLOCKED | Copper & aluminum via IBKR/yfinance futures; **iron ore has no clean free source — likely BLOCKED**, document |
| `regime_state` | DERIVED | `classify_regime_rule_based()` |
| `is_growth`, `rate_change_bp` | DERIVED | Index classification + curve change |

#### Module 12, 17 inputs

| Input | Type | Source |
|---|---|---|
| `prior` | **DERIVED/MANUAL** | The previous thesis's `posterior_probability`, or an explicitly-documented base rate for a new thesis. **Never invented ad hoc.** |
| `likelihood_given_true`, `likelihood_given_false` | **CONFIG** | `settings.yaml: bayesian.likelihoods` — a documented table per evidence type. **These are judgment parameters and must be stated, versioned, and reviewable — not chosen per-call.** |
| `scenarios` | DERIVED | `build_scenario_distribution()` |
| `*_signal` (scorecard) | DERIVED | Sign of each pillar's model output |
| `independent_source_families` | DERIVED | `count_independent_families()` |
| `policy_rate_avg`, `credit_spread_hy_avg`, `term_premium_avg` | CONFIG | `settings.yaml: fci.averages` — trailing 5yr averages, recomputed on a documented schedule |
| FCI `weights` | CONFIG | `settings.yaml: fci.weights` — **uncalibrated defaults**; must cross-check output against FRED `NFCI` |
| `returns` | DERIVED | From price series |
| `vol1`, `vol2`, `correlation` | DERIVED | From return series — **correlation must ALWAYS be computed alongside a stressed variant** |
| `correlation_stressed` | CONFIG | `settings.yaml: risk.stress_correlation`, default 0.9 |
| `cov_matrix` | DERIVED | From return series |
| `high_water_mark`, `current_value` | LIVE | Portfolio state (external to this system in Phase 1–4) |
| `current_contributions` | DERIVED | `marginal_risk_contributions()` |
| `target_vol_annualized` | CONFIG | `settings.yaml: risk.target_vol` |
| `duration_a`, `duration_b`, `tips_duration`, `nominal_duration` | DERIVED | `modified_duration()` |

**Any input not listed above is BLOCKED by default.** The agent must stop
and ask rather than invent a source.

---

### 21.2 MANDATORY IMPLEMENTATION PROCESS — Function-by-Function, Never in Batch

Batch implementation is **prohibited**. An agent that writes ten functions
and then tests them has no way to know which one broke a shared assumption,
and — as this project has already experienced — will report "complete"
while carrying silent errors.

**For EVERY function, in this exact order:**

**Step 1 — Read.** Re-read the function's full specification, its Section 21.1
input sourcing row(s), and the module entry in Section 15 that explains its
economic purpose. State in one sentence what economic question it answers.

**Step 2 — Confirm inputs.** For each input, state its source type from
Section 21.1. If any input is BLOCKED or undocumented: **STOP and ask.**
Do not proceed with a guessed source.

**Step 3 — Implement.** Write exactly the specified logic. Every deviation
requires a logged entry in `docs/DECISIONS.md` explaining why, BEFORE the
deviation is written.

**Step 4 — Unit test with hand-verified values.** Compute the expected
output by hand first, write the assertion against that number, then run.
If the test passes on the first attempt without you having computed the
expected value independently, the test is worthless — you have asserted
whatever the code produced.

**Step 5 — Warning-path test.** Every condition that should populate
`warnings` must be triggered in at least one test. An untested warning path
is an untested safety mechanism.

**Step 6 — Real-data execution.** Fetch the real inputs from their real
sources. Run the function. Record: series used, values retrieved, retrieval
timestamp, function output.

**Step 7 — Plausibility assessment.** State in writing whether the
real-data output is economically sensible, and why. "The Taylor Rule
returned 4.2% with the Fed at 3.6% — a ~60bp gap, plausible given a
positive output gap and above-target inflation" is an assessment.
"It ran without errors" is not.

**Step 8 — Quality gates.** `ruff` clean, `mypy --strict` clean.

**Step 9 — Record.** Append to `docs/BUILD_STATE.md`: function name, status,
real-data validation record from Steps 6–7, any decisions logged.

**Step 10 — Report and wait.** Report Steps 1–9 for THIS function. Do not
begin the next function until approved.

---

### 21.3 Implementation Order (Dependency-Correct)

### 22.1 Resolves Finding #1 — Phase/Defer/Stub Contradiction

**One canonical rule, replacing every scattered phase reference:**

> A function has exactly one status at any time: **STUB** (correct
> signature, typed inputs/outputs, raises `NotImplementedError` with a
> reason) or **IMPLEMENTED** (full logic, real-data validated per Section
> 21.0). Section 20's "must be implemented — none may be skipped" means
> **every function must exist as a correctly-signed STUB immediately**,
> closing any risk of an undefined-reference error. It does NOT mean every
> function's *body* ships in Phase 2. The authoritative phase-to-body
> assignment is Section 21.3's five tiers — that table, and only that
> table, decides when a stub becomes IMPLEMENTED. Any other phase language
> elsewhere in this document (Section 4's tooling table, Section 11's
> phase table, individual "Phase 2 backfill" notes) is descriptive context,
> not a competing source of truth.

---


Functions must be built in dependency order — a function whose inputs come
from another function cannot be validated on real data until its
dependency exists.

**Tier 1 — no dependencies (pure arithmetic on live data):**
`price_bond`, `macaulay_duration`, `modified_duration`, `convexity`,
`price_change_with_convexity`, `gdp_deflator`, `output_gap`,
`curve_slope`, `breakeven_inflation`, `decompose_yield`,
`openings_to_unemployed_ratio`, `savings_investment_identity`,
`quantity_theory_implied_inflation`, `laspeyres_index`, `paasche_index`,
`fisher_index`, `repo_stress_check`, `historical_var`,
`expected_shortfall`, `parametric_var`, `realized_vol_simple`,
`portfolio_volatility_two_asset`, `portfolio_volatility_n_asset`

**Tier 2 — depend on Tier 1:**
`taylor_rule`, `balanced_approach_rule`, `first_difference_rule`,
`policy_rule_ensemble`, `phillips_curve_inflation`,
`potential_gdp_cobb_douglas`, `growth_accounting_decomposition`,
`claims_trend_signal`, `claims_corroboration`, `two_survey_divergence`,
`nfp_revision_adjusted_read`, `ahe_composition_flag`,
`beveridge_curve_position`, `labor_tightness_score`,
`inflation_breadth_score`, `project_shelter_cpi`, `ppi_pipeline_signal`,
`gdp_gdi_divergence`, `lei_composite`, `simple_gdp_nowcast`,
`auction_demand_signal`, `credit_spread_attribution`, `compute_fci`,
`qe_qt_stance`, `minsky_composition_drift`, `policy_mix_classifier`,
`marginal_risk_contributions`, `bayesian_update`, `expected_value`

**Tier 3 — synthesis:**
`classify_regime_rule_based`, `check_trilemma_tension`,
`inflation_convergence_classifier`, `tag_evidence_source`,
`count_independent_families`, `four_pillar_scorecard`,
`inversion_probability_adjustment`, `cross_asset_transmission`,
`classify_convergence`, `project_inflation_trajectory`,
`derive_market_implied_policy_path`, `evaluate_drawdown_rules`,
`check_rebalancing_drift`, `volatility_target_scaling`,
`apply_fractional_kelly`

**Tier 4 — construction:**
`select_instrument`, `construct_duration_weighted_curve_trade`,
`construct_breakeven_trade`, `construct_cross_market_rv`,
`derive_invalidation_conditions`, `build_scenario_distribution`,
`next_catalyst_calendar`, `build_confirmation_signals`,
`collect_all_warnings`, `no_trade_thesis`, `build_us_macro_thesis`

**Tier 5 — Phase 5+.** ⚠️ **"Tier 5" names two different things in this document, and they have
different status.** Do not conflate them.

| | Where | Status |
|---|---|---|
| **§21.3's Tier 5 — this list of 23 FUNCTIONS** | here | **COMPLETE.** Measured 2026-10-08: all 23 names below have real bodies in `src/` (0 raise `NotImplementedError`). The heading *"stubs only until their phase"* no longer described the shipped tree and was corrected. |
| **"Tier 5 — Phase 5+" — the PHASE** | §22.3 | **NOT COMPLETE.** §22.3 files **multi-country** under it (*"Multi-country support (`de`, `jp`, `gb`) is Tier 5 — Phase 5+"*), and only `us` is implemented (§1.3). |

**So this list being complete does NOT mean Phase 5+ is complete.** The system is **US-only**; the
multi-country leg — three tasks per country (its own verified sources, its own central-bank reaction
function, its own instrument set) — is not built.

The "stubs only" rule now bites in exactly one place: **`extensions/` — 6 modules, each gated on an
uninstalled §4 package.** Read the tags in this section as the **build ORDER**, not as a statement of
what is missing; for the genuinely outstanding items see `docs/PHASE5_DEFERRED.md` §2 (GARCH ·
crisis-shock engine · **multi-country** · FX-forward data coverage).
`cip_check`, `uip_expected_move`, `ppp_valuation`, `carry_score`,
`dollar_smile_regime`, `intervention_capacity`,
`em_vulnerability_checklist`, `oil_balance_signal`,
`gold_driver_attribution`, `metals_complex_divergence`,
`sector_rotation_prior`, `duration_sensitivity`, `factor_tilt_prior`,
`monte_carlo_var`, `compute_risk_parity_weights`,
`classify_regime_markov_switching`, `yield_curve_pca`, `run_regression`,
`test_stationarity`, `test_cointegration`, `compute_pca`,
`kalman_latent_state`, `statement_text_diff`

---

### 21.4 The Loophole Ledger — Where This System Is Allowed To Not Know

A system that cannot say "I don't know" will fabricate. Every BLOCKED item
in Section 21.1 is a place this system must explicitly return "unavailable"
rather than a plausible number. These must be tracked in `OPEN_ISSUES.md`
and surfaced in every thesis's `warnings`:

1. Supercore (O-8) — no valid BLS construction
2. Trimmed-mean / median CPI — Dallas/Cleveland Fed, separate sources
3. Raw CPI microdata — index functions are reference-only
4. Leveraged-loan / risky-credit growth — no free series
5. Conference Board LEI — licensed
6. Consensus estimates (for surprise calculation) — no free source
7. PPP conversion factors — OECD, manual
8. Iron ore prices — no clean free source
9. Central bank gold purchases — WGC quarterly, manual
10. Corporate margin trend — human assessment
11. Default rate trend — human assessment
12. FX forward points — may be unavailable depending on IBKR entitlements
13. r*, u*, potential GDP, TFP — **unobservable by nature**, config estimates only
14. Pre-launch data vintages — unrecoverable; revision analysis only works forward

**A thesis built while any of these materially affects its conclusion MUST
carry that limitation in `MacroThesis.warnings`.** The system's credibility
depends on it being explicit about what it cannot see.

### 22.13 Section 22 Implementation Requirement

Every corrected function in this section **replaces** its predecessor
entirely — the prior placeholder versions (naive `select_instrument`, the
fake-Kelly `apply_fractional_kelly`, the raw-deviation `compute_fci`, the
first-signal-referenced `classify_convergence`, the unadjusted
`derive_market_implied_policy_path`) must be deleted from the codebase if
already written, not left alongside the corrected versions. If Phase 2-4
already shipped any of these under their original names, this is a
mandatory retroactive correction, reported the same way every prior
backfill in this project has been reported: real-data validation, golden
test, explicit before/after comparison showing the old placeholder's wrong
behavior versus the corrected function's right behavior.
