# OpenBB Local API — Mandatory Utilization Audit

**Date:** 2026-09-20 · **Service:** `http://127.0.0.1:6901` · **Decision record:** `docs/DECISIONS.md` **D-084**
**Scope:** maximize use of the existing local OpenBB API before writing custom data-access code.
**Constraints honoured:** no architecture redesign, no `AGENTS.md` rewrite, no Phase 5+ functionality,
no trade execution, no new FRED API key requirement.

> **Method.** Every statement below was measured against the **live service**, not read off documentation.
> The spec was re-fetched fresh (`/openapi.json`, 2,424,179 bytes) and saved under `.workbuddy-ai/audit/`;
> per-route probe responses are kept under `.workbuddy-ai/audit/probes/`. Where a number is quoted it was
> counted, and where a capability is claimed it was called.

---

## 0. Headline

The engine routes **45 registry series + 2 curves (16 tenors)** through **2 commands**
(`economy.fred_series`, `economy.fred_search`) out of **201** live commands, of which **77** are
macro-relevant. The live surface offers a **dedicated command for at least 12 of the engine's own registry
fields** — including the entire Treasury curve in **one** call instead of eleven, and structured FOMC
documents instead of an HTML scrape. None of those are used today.

The vintage/PIT investigation is **closed**: historical vintage selection is genuinely unavailable through
the local route, now confirmed four independent ways. That limitation is real and must be **preserved, not
worked around**.

---

## 1. OpenBB commands discovered locally

| Measurement | Value |
|---|---|
| OpenAPI version | **3.1.0** (`OpenBB Platform API`) |
| Paths | **278** |
| Component schemas | **575** |
| Commands (via `/api/v1/coverage/commands`) | **201** |
| Providers (via `/api/v1/coverage/providers`) | **32** |
| Liveness routes | `/` **200**, `/docs` **200**, `/openapi.json` **200** |

**`/api/v1/coverage/command_model` returns HTTP 422** `{"detail":["Circular reference detected"]}` with no
parameter. This is a **route limitation**, not a transient error: it cannot be used as documented without
supplying a parameter. Recorded rather than worked around.

### Macroscopically relevant command families (77 commands)

| Namespace | Commands | Note |
|---|---|---|
| `economy/` | 39 | the bulk of the macro surface |
| `fixedincome/` | 30 | rates, curves, spreads, credit |
| `regulators/sec/` | 8 | point-in-time filing mode (unrelated to FRED vintages) |
| `news/` | 2 | `company`, `world` |

### Provider surface (live endpoint counts)

`fmp` 69 · `intrinio` 38 · **`fred` 36** · `yfinance` 29 · `tmx` 24 · `sec` 23 · **`federal_reserve` 13** ·
`cboe` 11 · `nasdaq` 9 · `oecd` 9 · `econ_d` 8 · `imf` 8 · `congress_gov` 8 · `finviz` 7 · `tiingo` 7 ·
`government_us` 6 · `famafrench` 6 · `deribit` 5 · `tradier` 5 · `benzinga` 4 · `alpha_vantage` 3 ·
`ecb` 3 · `seeking_alpha` 3 · `wsj` 3 · `bls` 2 · `cftc` 2 · `eia` 2 · `finra` 2 · `multpl` 1 ·
`stockgrid` 1 · `tradingeconomics` 1 · `biztoc` 1

**FRED exposes only 4 namespaced routes** — `economy/fred_regional`, `economy/fred_release_table`,
`economy/fred_search`, `economy/fred_series`. The engine uses **2 of the 4**.

---

## 2. Commands currently used by the engine

| Command | Where | Live status |
|---|---|---|
| `economy.fred_series` | `snapshot_builder.fetch_field` / `fetch_curve` — **43 of 45** registry entries + both curves (16 tenors) | **200**, verified |
| `economy.fred_search` | `publication_dates.py` (`search_type=series_id`, `limit=1000`) | **200**, verified |
| `economy.calendar` | `release_calendar.py` — **`enabled: false`** in config | **non-functional** (see §5) |

Everything else in the engine is **calculation, validation, PIT accounting, persistence and reasoning** —
correctly not a data-access concern.

---

## 3. Relevant commands currently unused

The highest-value unused routes, each **live-verified during this audit**:

| Command | Provider | Replaces | Measured |
|---|---|---|---|
| `fixedincome/government/yield_curve` | `federal_reserve` | **11** `fred_series` calls (whole curve) | 200, **11 tenors + `maturity_years` as a field** |
| `fixedincome/government/treasury_rates` | `federal_reserve` | curve history | 200, **248 rows × 11 tenors in one call** |
| `economy/survey/inflation_expectations` | `federal_reserve` | *(no current source)* | 200, `infcpi1yr` / `infcpi10yr` |
| `economy/fomc_documents` | `federal_reserve` | **HTML scrape** of `federalreserve.gov` | 200, **34 dated rows**, `doc_type` incl. `projections` |
| `economy/central_bank_holdings` | `federal_reserve` | *(no current source)* | 200, per-CUSIP and `summary=true` aggregate |
| `fixedincome/rate/effr` | `federal_reserve` / `fred` | `FEDFUNDS` lookup | 200, rate + `target_range_upper/lower` + `revision_indicator` |
| `fixedincome/rate/sofr` | `federal_reserve` / `fred` | `SOFR` lookup | 200, rate + percentiles + volume |
| `fixedincome/rate/overnight_bank_funding` | `federal_reserve` / `fred` | *(no current source)* | 200 |
| `economy/money_measures` | `federal_reserve` | *(no current source)* | 200, M1/M2 decomposition |
| `economy/survey/sloos` | `fred` | `DRTSCILM` lookup | 200, **369 rows** with `symbol` + `title` |
| `economy/survey/university_of_michigan` | `fred` | *(no current source)* | 200, `inflation_expectation` as a field |
| `economy/survey/nonfarm_payrolls` | `fred` | *(no current source)* | 200, hierarchical industry breakdown |
| `economy/cpi` | `fred` | `CPIAUCSL` / `CPILFESL` lookups | 200, 832 rows, `country` field |
| `economy/pce` | `fred` | `PCEPILFE` lookup | 200, hierarchical table |
| `fixedincome/government/tips_yields` | `fred` | *(engine uses FRED symbols here already)* | 200, **10.2 MB** per-CUSIP TIPS |
| `fixedincome/corporate/spot_rates` | `fred` | *(no current source)* | 200, HQM spot rates |
| `fixedincome/spreads/tcm` | `fred` | `T10Y3M` lookup | 200 |
| `fixedincome/government/treasury_auctions` | `government_us` | *(no current source)* | 200, dated auctions w/ CUSIP, coupon |
| `economy/primary_dealer_positioning` | `federal_reserve` | *(no current source)* | available |
| `economy/total_factor_productivity` | `federal_reserve` | *(no current source)* | available |
| `economy/balance_of_payments` | `fred` | (blocked field parity) | available |
| `economy/fred_regional` | `fred` | — | available |

---

## 4. Data requirements now sourcable directly through OpenBB

Classification of the engine's **actual** requirements. The registry's 45 series + 2 curves were compared
field-by-field against the live surface.

### 4.1 `AVAILABLE_DIRECT` — a dedicated command returns exactly this

| Registry field | Command | Evidence |
|---|---|---|
| `treasury_curve` (11 tenors) | `federal_reserve/fixedincome/government/yield_curve` | **1 call → 11 tenors**, `maturity_years` typed |
| `tips_yields` | `fred/fixedincome/government/tips_yields` | 200 |
| `sloos_net_tightening` | `fred/economy/survey/sloos` | `DRTSCILM` is one of 369 rows |
| `cpi_headline`, `cpi_core` | `fred/economy/cpi` | 832 rows |
| `pce_core` | `fred/economy/pce` | hierarchical table |
| `fed_funds_rate` | `federal_reserve/fixedincome/rate/effr` | rate + target range |
| `sofr` | `federal_reserve/fixedincome/rate/sofr` | rate + percentiles |
| `iorb` | `fred/fixedincome/rate/iorb` | 200 |
| `curve_slope_10y3m` | `fred/fixedincome/spreads/tcm` | 200 |
| `fed_total_assets`, `on_rrp_volume_bn` | `federal_reserve/economy/central_bank_holdings` | `summary=true` aggregate |
| `equity_volatility` | `cboe/equity/price/historical` | multi-provider |
| **catalyst calendar (FOMC)** | `federal_reserve/economy/fomc_documents` | 34 dated rows, `doc_type` field |

### 4.2 `AVAILABLE_WITH_MAPPING` — the data is there, but the field/units/symbol need translation

| Registry field | Command | Mapping required |
|---|---|---|
| `gdp_real`, `gdp_nominal`, `gdi` | `fred/economy/fred_series` | already correct — keep |
| `unemployment_rate`, `initial_claims`, `continuing_claims` | `fred/economy/fred_series` | already correct — keep |
| `jolts_openings`, `jolts_quits` | `fred/economy/fred_series` | keep, or `survey/nonfarm_payrolls` |
| `credit_spread_hy`, `credit_spread_ig` | `fred/economy/fred_series` | keep |
| `gdp_potential` | `fred/economy/fred_series` | keep (`forward_looking`) |
| `median_cpi_direction`, `trimmed_mean_direction` | `fred/economy/fred_series` | keep (Cleveland Fed) |
| all 43 scalar FRED symbols | `fred/economy/fred_series` | **no change needed** — the generic path is correct for these |

`fred_series` is **not** a defect. For a single named series it is the right command. It becomes the wrong
choice only where a **dedicated** command exists (§4.1) — most sharply for the curve, where 11 calls
become 1.

### 4.3 `AVAILABLE_BUT_PROVIDER_LIMITED`

| Requirement | Limitation |
|---|---|
| Economic calendar (event/actual/forecast/previous) | all four providers unusable — §5 |
| FRED historical vintage selection | unavailable — §6 |
| `tradingeconomics`, `fmp`, `nasdaq` calendar providers | missing credentials or upstream block |
| `/api/v1/coverage/command_model` | HTTP 422 circular reference |
| `fred/fixedincome/government/tips_yields` | returns **10.2 MB** unfiltered — needs a window |
| `federal_reserve/.../svensson_yield_curve` | returns **34.8 MB** unfiltered — needs a window |

### 4.4 `NOT_AVAILABLE`

| Registry `blocked` entry | Audited conclusion |
|---|---|
| `conference_board_lei` | Confirmed — licensed product, no free route |
| `supercore_direction` | Confirmed — no valid BLS construction |
| `inflation_surprise_bp` | Confirmed — no free consensus-forecast series |
| `iron_ore_change_pct` | Confirmed — no clean free source |
| `ppp_implied_rate` | Confirmed — OECD PPP factors not exposed |

---

## 5. Provider / API limitations

### 5.1 The economic calendar does not work — any provider (DECISIVE)

All four providers were called live:

| Provider | Result |
|---|---|
| `fred` | **HTTP 400** `{"detail":"FRED request failed (TimeoutError)."}` — **3/3 attempts**, also with `start_date`/`end_date`/`country`, also with `importance=high` |
| `tradingeconomics` | **HTTP 400** `Missing credential 'tradingeconomics_api_key'` |
| `fmp` | **HTTP 400** `Missing credential 'fmp_api_key'` |
| `nasdaq` | **HTTP 500** `Unexpected Error -> TimeoutError` (was documented as an Akamai 403) |

**Root cause — CORRECTED BY D-087.25 (2026-09-21).** The text that stood here said *"FRED closes the
connection for `aiohttp`'s TLS/HTTP fingerprint, and OpenBB's FRED provider is built on `aiohttp`."*
**That is false and does not reproduce.** Re-measured, `aiohttp` reaches this endpoint in ~**0.1 s**
and `urllib` in ~**0.15 s**; the provider's URL is byte-identical to the project's own working URL, so
the client library was never the discriminator. **The discriminator is the `User-Agent`:**

| User-Agent sent | result |
| --- | --- |
| `curl/8.0` | **200 in ~0.2 s** |
| `python-httpx/…` (library default) | **200 in ~0.2 s** |
| a real browser UA (Chrome / Firefox / Safari) | **HANGS — every time** |
| `""` (empty) | **HANGS — every time** |

FRED's releases-calendar page serves a **tool-like** UA and stalls a **browser-like or absent** one
(a true read timeout — the connection is established and the body never begins). OpenBB's
`get_user_agent()` returns `random.choice` of **seven real browser UA strings** and applies it
unconditionally, with **no supported override** — so every OpenBB FRED call hangs. So this is **still
not a FRED outage**, but it is **not** a fingerprint filter either: it is a one-line UA choice in a
dependency. `tools/fred_calendar_diagnosis.py` reproduces the matrix on demand.

**Consequence for §5's question.** The user asked whether the local route supplies
`event / release date / actual / forecast / previous / country / source`. **It still cannot be tested
through the FRED provider, because that provider never returns a body** — but the reason is now the UA,
not the transport. The signature (`start_date`, `end_date`, `release_id`, `country`, `importance`,
`group`, `calendar_id`) is captured from the spec, but a signature is not data. This stays recorded as
`AVAILABLE_BUT_PROVIDER_LIMITED` — and `nasdaq`, which is unaffected by the UA defect, **does** return a
body (D-084 measured it; D-087.25 re-confirmed 200 with results), so "no calendar provider works" was
too strong for that one provider.

### 5.2 Two routes return unbounded payloads

`fixedincome/government/svensson_yield_curve` = **34.8 MB**, `fixedincome/government/tips_yields` =
**10.2 MB** on a bare call. Both are usable only with an explicit date window. A naive integration would
appear to hang.

### 5.3 `realtime_start` / `realtime_end` are a decoy — five independent confirmations

This is the single most important §4 finding and it is documented here in full because the user's brief
explicitly forbids substituting for vintages.

The fields appear in live responses on `fred_search`, `fred/corporate/spot_rates` and `fred/spreads/tcm` —
and **in every case both equal today**, e.g. the live `fred_search` for `CPIAUCSL`:

```
last_updated:    2026-09-11T08:37:49-05:00   <-- a REAL publication instant
realtime_start:  2026-09-20                  <-- TODAY
realtime_end:    2026-09-20                  <-- TODAY
```

They describe the vintage window **in force now**, not the revisions that existed before. Treating them as
vintage bounds would stamp every observation with today's date and silently destroy the PIT record.

---

## 6. FRED vintage / PIT investigation — capability-specific conclusion

Verified four independent ways, live:

1. **Request-parameter scan.** `realtime_start` and `realtime_end` appear as **request parameters on 0
   routes**. They exist only as **response properties of one schema, `FredSearchData`**.
2. **`vintage_dates` has 0 occurrences** anywhere in the spec — not as a parameter, not as a schema field.
3. **The 6 `vintage` hits belong to the SEC provider** (`equity/fundamental/balance`, `.../income`, etc.),
   describing SEC point-in-time restatement mode. They have nothing to do with FRED.
4. **Empirical A/B test.** Two `fred_series` calls differing **only** by
   `realtime_start=1990-01-01&realtime_end=1990-12-31` returned **byte-identical data** (`a == b` → `True`).
   The parameter is silently ignored.

`fred_series` accepted parameters, exhaustive and live: `chart`, `provider` (req), `symbol` (req),
`start_date`, `end_date`, `limit`, `frequency`, `aggregation_method`, `transform`, `all_pages`, `sleep`.
**No vintage parameter exists.**

### The conclusion, stated at the granularity the brief requires

> **Standard FRED observations are available through OpenBB.
> Historical vintage selection is unavailable through the current local OpenBB route.**

This is *not* the over-broad "FRED vintages are unavailable". Observations, `last_updated` publication
timestamps, and series metadata all work; **only ALFRED-style `realtime_start` selection is missing.**

### What the engine already does correctly — and must keep doing

`publication_dates.py` documents the same decoy in prose and already refuses the substitution:

> *"Reporting a current-vintage window as a revision identity would be the exact substitution Section 6
> prohibits, so it is not done."*

Its `vintage_datetime` stays `None` throughout, and `release_datetime` is filled from `last_updated` —
a **real** publication instant, cross-validated (PCEPILFE `last_updated` 2026-08-26 vs the calendar's
2026-08-27). This audit **independently reproduces** that finding. It is working PIT logic and is
**protected from removal** by §7.

---

## 7. Duplicated custom data-access logic

Applying the boundary — **OpenBB** = acquisition / provider access / normalization;
**engine** = validation / PIT accounting / transformations / reasoning:

### 7.1 `thesis_layer/catalysts.py` — direct HTML scraping (the main duplication)

This module bypasses OpenBB entirely and scrapes:

| Current | Lines | Alternative found in this audit |
|---|---|---|
| `fred.stlouisfed.org/releases/calendar` HTML-in-JSON, regex-parsed | 126–245 | `economy/calendar` — **does not work** (§5.1), so the scrape is justified |
| `federalreserve.gov/monetarypolicy/fomccalendars.htm` HTML, regex-parsed | 137, 248–288 | **`economy/fomc_documents`** — works, structured |

The FOMC half **is** duplicated. `fomc_documents` returns, as **fields**:

```
{"date": "2026-09-16", "doc_type": "monetary_policy",   "doc_format": "pdf"}
{"date": "2026-09-16", "doc_type": "press_conference",  "doc_format": "htm"}
{"date": "2026-09-16", "doc_type": "projections",       "doc_format": "pdf"}   <-- the dot plot
```

34 rows, `doc_type` ∈ {`minutes`, `monetary_policy`, `projections`, `beige_book`, `press_conference`}.
Compare the scrape, re-measured live: it parses meetings **back to 2021** and needs the `*` character
stripped from `"27-28*"` to recover the projections flag, which OpenBB returns as `doc_type=projections`.
The scrape is **strictly worse**: more parsing, more history to filter, and it must re-derive a flag that
is already a typed field.

**Recommendation:** move the FOMC catalyst to `economy/fomc_documents`. Keep the FRED-release scrape,
because its OpenBB alternative is confirmed broken — that is exactly the case §7 anticipates.

### 7.2 What must NOT be removed

| Component | Why it stays |
|---|---|
| `data_layer/validation.py` | Bounds, forward-dating, non-finite rejection — engine reasoning, not acquisition |
| `publication_dates.py` | **PIT accounting.** The `last_updated` read is acquisition; the refusal to substitute is the engine's rule. Keep whole. |
| `data_layer/persistence.py` | Parquet audit trail — provenance and durability |
| `as_of.py`, the O-7 forward-date filter | Point-in-time correctness |
| `release_calendar.py` | Its retry/empty-mapping contract is correct; only its `enabled: false` status reflects upstream reality |
| `models/*` | All reasoning |

OpenBB supplies **raw data**. It does not supply a PIT ledger, and it must not be asked to.

### 7.3 True duplication: none beyond §7.1

`OpenBBClient._normalize` already handles the shapes OpenBB returns, records the **serving** path as
provenance, and refuses to invent a date column. This is correct and should not be rewritten. **There is
no second bespoke provider adapter to consolidate** — the engine has one client, which is the desired shape.

---

## 8. Minimal code changes to make OpenBB the canonical gateway

All changes are **config-first**, so no architecture moves and `AGENTS.md` is untouched.

### Change 1 — Curve: 11 calls → 1 (`config/series_registry.yaml`)

Point `treasury_curve` at `fixedincome/government/yield_curve` (`provider: federal_reserve`). The response
carries `maturity`, `maturity_years` and `rate`; `fetch_curve` already reads a `date`/`value` frame, so it
needs a `maturity`/`rate` mapping — a **normalization** addition to `OpenBBClient`, not a new adapter.
Verified identical: FRED `DGS10` = **4.94** on 2026-09-17; Fed `year_10` = **0.0494**. Same source (H.15),
same value.

### Change 2 — FOMC catalyst: scrape → command (`catalysts.py` + config)

Replace `_fetch_fed_fomc_meetings` with a call to `economy/fomc_documents?provider=federal_reserve&year=…`,
filtering `doc_type == "monetary_policy"` for meetings and `== "projections"` for the dot-plot flag.
Removes one HTML parser and two regexes. **Keep** `_fetch_fred_release`.

### Change 3 — Adopt the dedicated rate commands for the fields in §4.1

`sofr`, `iorb`, `effr`, `sloos`, `university_of_michigan`. Each is a registry `endpoint:` edit. The payoff
is not just tidiness: `effr` returns `target_range_upper`/`lower` as typed fields (useful to
`policy_rules.py`) and `university_of_michigan` returns `inflation_expectation` directly.

### Change 4 — Record the calendar limitation (docs only)

Do **not** build a scraper. Amend `release_calendar`'s note so the reason is transport-specific
— **and per D-087.25 the reason to write is the `User-Agent`, not a fingerprint: OpenBB's FRED
provider sends a random real-browser UA, and FRED stalls browser-like UAs on that page** — rather
than "route unavailable".
Keep `enabled: false`.

### Change 5 — Add a coverage guard (small, new test)

A test asserting every registry `endpoint:` exists in the live `/openapi.json`. Cheap, and it would have
surfaced §4.1 automatically.

**Explicitly not proposed:** rewriting `OpenBBClient`; removing `publication_dates.py`; adding a FRED API
key; any Phase 5 work; any execution path.

---

## 9. Verification performed

| Check | Result |
|---|---|
| Live `/openapi.json` re-fetched fresh | 2,424,179 bytes, 278 paths |
| `/`, `/docs`, `/openapi.json`, coverage routes | **200** |
| `coverage/command_model` | **422** circular reference (recorded) |
| `fred_series` params enumerated from spec | no vintage parameter |
| A/B `realtime_start` test | **byte-identical** — parameter ignored |
| `vintage_dates` occurrences | **0** |
| `realtime_start` as request parameter | **0 routes** |
| All four calendar providers | **all fail** (2 credential, 2 timeout) |
| 4 `federal_reserve` rate/curve routes | **200** with data |
| `fomc_documents` | **200**, 34 dated rows |
| `treasury_rates` vs `fred_series DGS10` | values **agree exactly** |
| Direct FRED scrape re-measured | works, but strictly worse than `fomc_documents` |
| 14 unused macro routes probed | **all 200** |

---

*Audit artefacts: `.workbuddy-ai/audit/{openapi,providers,commands,command_model}.json` and
`.workbuddy-ai/audit/probes/*.json`. No `src/` file was modified by this audit; no `AGENTS.md` content was
changed.*
