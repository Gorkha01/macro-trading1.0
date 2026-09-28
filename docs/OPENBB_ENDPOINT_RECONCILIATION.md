# OpenBB endpoint reconciliation — what the engine uses vs. what it exposes

**Measured** against the live local service (`http://127.0.0.1:6900/openapi.json`,
fetched 2026-09-28). This is a measurement of *availability*, not a plan to wire
anything — no model, registry entry or threshold is changed by this file.

---

## 1. The live surface (your local OpenBB)

| Metric | Value |
| --- | --- |
| Paths / operations | **278** |
| Distinct providers (from `provider` enums) | **23** |
| Providers | `alpha_vantage`, `benzinga`, `biztoc`, `cboe`, `deribit`, `ecb`, `econdb`, `federal_reserve`, `finviz`, `fmp`, `fred`, `government_us`, `imf`, `intrinio`, `nasdaq`, `oecd`, `sec`, `seeking_alpha`, `tiingo`, `tmx`, `tradier`, `tradingeconomics`, `yfinance` |

Families, by path count:

| Family | Paths | Family | Paths |
| --- | --- | --- | --- |
| equity | 69 | uscongress | 12 |
| economy | 42 | etf | 12 |
| technical | 27 | imf_utils | 8 |
| fixedincome | 25 | regulators | 8 |
| quantitative | 19 | derivatives | 8 |
| econometrics | 15 | commodity | 7 |
| index | 7 | famafrench | 6 |
| currency | 4 | coverage | 3 |
| cftc | 2 | crypto | 2 |
| news | 2 | | |

---

## 2. What the engine ACTUALLY issues — **6 live commands** (derived, not recalled)

Confirmed by `tests/test_openbb_command_inventory.py` (`_live_commands()`):

| # | Command | What it feeds |
| --- | --- | --- |
| 1 | `economy.fred_series` | almost every registry series (FRED) |
| 2 | `economy.fred_search` | series discovery / probes |
| 3 | `fixedincome.government.yield_curve` | the Treasury curve, 11 tenors in one call |
| 4 | `economy.fomc_documents` | the catalyst calendar (source-literal, not a registry field) |
| 5 | `commodity.petroleum_status_report` | `oil_balance_signal` (D-120) |
| 6 | `commodity.short_term_energy_outlook` | `oil_balance_signal` (D-120) |

(`economy.calendar` appears in the registry but is `enabled: false` — deliberately
excluded, per the inventory test.)

**So: 6 of 278.** The other 272 are live, callable, and unused.

---

## 3. The three gaps you asked about — and the endpoints that fill them

### Gap A — **FX spot rates** (you wanted USDJPY)

| Available endpoint | Family | Fills it? |
| --- | --- | --- |
| `currency.price.historical` | currency | **YES — the spot/OHLC path** |
| `currency.reference_rates` | currency | **YES — the level path (ECB)** |
| `currency.snapshots` | currency | **YES — the latest quote** |
| `currency.search` | currency | discovery |

This is the real answer to your USDJPY question: `currency.price.historical` is the
command that would populate `fx_spot`. The registry currently contains **no FX-rate
field** (`series_registry.yaml:1915` names FRED's `DEXJPUS` and declines it because
H.10 has no forwards), so the gap is a **registry + fetcher** gap, not a
**provider** gap. The provider has FX; the engine does not subscribe.

### Gap B — **Cross-country macro**

| Available endpoint / provider | Fills it? |
| --- | --- |
| `oecd` (9 commands worth of coverage) | **YES — cross-country macro** |
| `imf` + `imf_utils` (8 paths) | **YES — cross-country macro/financial** |
| `ecb` | **YES — euro-area** |
| `econdb` | **YES — worldwide series** |
| `economy.indicators` | multi-country indicators |
| `economy.direction_of_trade` | bilateral trade |
| `economy.export_destinations` | bilateral trade |

Cross-country **data** is fully available. What §22.3 says is that **data is not the
blocker** — the blocker is the per-country *reaction function* (Module 4) and the
per-country *instrument set* (Module 18), which are US-specific logic, not data.

### Gap C — **Cross-asset breadth**

| Available endpoint | Family | Fills it? |
| --- | --- | --- |
| `commodity.price.spot` | commodity | commodity spot (currently `commodity_spot` is a starved field, DEF-005) |
| `index.price.historical` | index | index-level equity (the engine has index+vol only) |
| `cftc.cot` / `cftc.cot_search` | cftc | **positioning data** — COT, not currently used at all |
| `derivatives.futures.curve` | derivatives | futures term structure |
| `derivatives.options.surface` | derivatives | vol surface (huge for risk) |
| `derivatives.options.unusual` | derivatives | options flow |
| `fixedincome.*` (25 paths) | fixedincome | credit, spreads, corporates |
| `technical.*` (27 paths) | technical | indicators (RSI/MACD/etc.) |
| `equity.price.historical` | equity | single-name equity (currently unused) |
| `famafrench.*` (6 paths) | famafrench | factor returns (Fama-French) |

---

## 4. The honest summary

| Question | Answer |
| --- | --- |
| Does OpenBB expose cross-asset + multi-country data? | **YES — 278 paths, 23 providers** |
| Does the engine *use* it? | **NO — 6 of 278** |
| Is FX spot available? | **YES** (`currency.price.historical`) — engine has no FX-rate registry field |
| Is cross-country data available? | **YES** (`oecd`/`imf`/`ecb`) — the blocker is per-country *logic*, not data |
| Does the engine break if you add endpoints? | **NO** — adding a registry block + a fetcher is additive |

**The key distinction:** this is a **deliberate scope choice** (§22.3 US-only through
Phase 4), not a capability gap. The endpoints are there; the engine subscribes to a
US/FRED-centric subset on purpose, because each new asset class or country requires
its own verified source, its own logic and its own instrument set — not just a wire.

Every adoption is a **buildable increment**, and each one has to clear the project's
evidence standard (registry entry with unit + provenance, a live check, a mutation
sweep) before it counts.
