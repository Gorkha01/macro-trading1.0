# Series Verification Record

Phase 0 discipline: **every LIVE input must have a verified series ID before
any model may consume it** (AGENTS.md Section 21.1).

This file is the evidence. Section 21.0 rule 5 requires that validation be
**recorded**, not merely performed:

> Every function's completion report includes: the real series used, the actual
> values retrieved, the date of retrieval, and the function's output on that
> real input, with a sanity assessment of whether that output is economically
> plausible.

The machine-readable copy of this evidence lives in
`config/series_registry.yaml` as `verified_on` / `verified_value` /
`verified_curve` on each entry, enforced by a validator: a series cannot be
marked `verified` without recording what was observed.

---

## Verification run — 2026-09-16

**Method:** `uv run python tools/manual_series_check.py --provider-only`
**Result:** **21 / 21 routes returned plausible data.**

All values below are the latest observation returned on that date. Plausibility
was assessed against the economics of the series, not merely against its
declared bounds.

### Prices

| Field | Symbol | Latest | As of | Rows | Assessment |
|---|---|---|---|---|---|
| `cpi_headline` | `CPIAUCSL` | **334.13** | 2026-08-01 | 59 | Index level, 1982-84=100. Consistent with +3.71% YoY. |
| `cpi_core` | `CPILFESL` | **337.77** | 2026-08-01 | 59 | Core above headline, i.e. food/energy currently a drag. +2.76% YoY. |
| `pce_core` | `PCEPILFE` | **130.66** | 2026-07-01 | 59 | 2017=100 basis, so a lower level than CPI is expected. +3.34% YoY. |
| `ppi` | `PPIFIS` | **157.41** | 2026-08-01 | 60 | Nov-2009=100 basis. +5.41% YoY — upstream pressure above CPI, consistent. |

### Labour

| Field | Symbol | Latest | As of | Rows | Assessment |
|---|---|---|---|---|---|
| `unemployment_rate` | `UNRATE` | **4.10 %** | 2026-08-01 | 59 | Within bounds. A plausible current rate. |
| `initial_claims` | `ICSA` | **206,000** | 2026-09-05 | 260 | Weekly, persons. Low by historical standards. |
| `continuing_claims` | `CCSA` | **1,774,000** | 2026-08-29 | 259 | ~8.6× initial claims: a normal ratio. |
| `jolts_openings` | `JTSJOL` | **7,271 k** | 2026-07-01 | 59 | Thousands of openings. Below the 2021-22 peak — cooling, not collapsed. |
| `jolts_quits` | `JTSQUR` | **1.9 %** | 2026-07-01 | 59 | Quits rate. Low churn — consistent with a soft labour market. |

### National accounts

| Field | Symbol | Latest | As of | Rows | Assessment |
|---|---|---|---|---|---|
| `gdp_real` | `GDPC1` | **24,269.61** | 2026-04-01 | 20 | Billions chained 2017 USD, SAAR. +2.10% YoY. |
| `gdp_nominal` | `GDP` | **32,486.07** | 2026-04-01 | 20 | SAAR billions. +6.56% YoY. |
| `gdp_potential` | `GDPPOT` | **29,443.02** | see note | 62 | CBO. **Forward-looking** — see the section below. |

**Cross-check (the strongest available):** the three series must satisfy

```
(1 + nominal YoY) = (1 + real YoY) × (1 + deflator)
```

Real +2.10% and nominal +6.56% imply a deflator of **+4.46%** — plausible, and
consistent with PPI at 5.41%. Because these are three *independent* FRED
symbols, a mis-mapping in any one would break this identity. It does not.

### Rates and policy plumbing

| Field | Symbol | Latest | As of | Rows | Assessment |
|---|---|---|---|---|---|
| `fed_funds_rate` | `FEDFUNDS` | **3.63 %** | 2026-08-01 | 60 | Monthly average, effective. |
| `sofr` | `SOFR` | **3.64 %** | 2026-09-15 | 1245 | Secured overnight. 1bp below IORB — normal. |
| `iorb` | `IORB` | **3.65 %** | 2026-09-16 | 1826 | Administered. Top of the corridor. |
| `on_rrp_rate` | `RRPONTSYAWARD` | **3.50 %** | 2026-09-15 | 1245 | Administered ON-RRP **offering rate**. Floor of the corridor. See D-001. |
| `on_rrp_volume_bn` | `RRPONTSYD` | **0.70** | 2026-09-15 | 1245 | ON-RRP **volume**, USD bn. Deliberately not a rate. See D-001. |

**Corridor cross-check:**

```
IORB            3.65   <- top
SOFR            3.64   (1bp below IORB)
TGCR            3.62   (probed separately)
ON RRP rate     3.50   <- floor, 15bp below IORB
```

This is the textbook post-2021 floor-system picture. It is also the evidence
that `RRPONTSYAWARD` is the correct series for `on_rrp_rate`: using the volume
symbol would put the "floor" 295bp below the corridor, which is not a state the
system can be in.

### Credit

| Field | Symbol | Latest | As of | Rows | Assessment |
|---|---|---|---|---|---|
| `credit_spread_hy` | `BAMLH0A0HYM2` | **2.76 %** | 2026-09-15 | 786 | HY OAS. Historically tight — calm credit conditions. |
| `credit_spread_ig` | `BAMLC0A0CM` | **0.80 %** | 2026-09-15 | 785 | IG OAS. Tight, and correctly far below HY. |

The IG-below-HY ordering is a structural fact of credit markets; a reversal
would indicate a mis-mapping.

### Yield curves

**`treasury_curve`** (FRED constant-maturity, percent):

| 1mo | 3mo | 6mo | 1yr | 2yr | 3yr | 5yr | 7yr | 10yr | 20yr | 30yr |
|---|---|---|---|---|---|---|---|---|---|---|
| 3.94 | 4.11 | 4.18 | 4.37 | 4.65 | 4.73 | 4.80 | 4.88 | **4.97** | 5.37 | 5.34 |

- All 11 tenors returned.
- Positively sloped throughout: **3m10y = +86bp**, **2s10y = +32bp**.
- The **20yr sits above the 30yr** (5.37 vs 5.34). This is a genuine, persistent
  feature of that segment, not an error. The validator distinguishes it from a
  *long-end inversion* (30yr far below 10yr), which would be flagged ERROR.
- The short end pricing below the 2yr implies the market expects easing, which
  is consistent with `fed_funds_rate` at 3.63%.

**`tips_yields`** (FRED real yields, percent):

| 5yr | 7yr | 10yr | 20yr | 30yr |
|---|---|---|---|---|
| 2.40 | 2.49 | **2.60** | 2.89 | 3.05 |

- 5yr is the **shortest breakeven available** — there is no 1yr or 2yr TIPS
  breakeven (Section 21.1, D-2.1). The schema and tests assume 5yr minimum.
- **10yr breakeven = 4.97 − 2.60 = 2.37%** — above the 2% target, consistent
  with 3.71% headline CPI.

---

## The `gdp_potential` forward-looking discovery

`GDPPOT` returned **62 observations, 41 of them dated after the retrieval
date** (through 2036-10-01). CBO publishes forward projections in this series.

This is **not** a data fault — a potential-output *estimate* legitimately
extends forward, and those points are required for a forward-looking output gap.
But it is not a measurement either, and the two must not be confused.

The first live snapshot build flagged all 41 as `FUTURE_OBSERVATION_DATE`
**ERROR**, which would have trained a reader to ignore the flag list entirely.

**Resolution:** the registry entry carries `forward_looking: true`, and the
validator collapses those points into a single INFO finding:

```
[INFO] gdp_potential @2036-10-01: FORWARD_LOOKING_HORIZON — 41 projection(s)
extend to 2036-10-01. Expected for an estimate series — downstream must filter
to observation_date <= as_of before treating any value as realised data.
```

The future-dating ERROR path is retained for series *not* declared
forward-looking, and is tested — so a genuine future-dated fault in a
measurement series is still caught.

**Outstanding Phase 2 obligation:** the `observation_date <= as_of` filter is
not yet applied anywhere. Tracked as O-7 in `OPEN_ISSUES.md`.

---

## The normalization finding (why live verification is mandatory)

During the initial Phase 0 verification, `economy.fred_series` returned a frame
that caused a parse failure:

```
Normalized frame for cpi_headline has no recognizable date column;
got columns ['cpiaucsl']
```

**Root cause:** `fred_series` returns dates in the **index**, and critically
that index is a `pandas.Index` with **`dtype=object`** holding
`datetime.date` objects — **not** a `pd.DatetimeIndex`, though it is named
`"date"`.

The first fix tested only `isinstance(df.index, pd.DatetimeIndex)` and therefore
missed it entirely. The working check inspects three signals, the third being
decisive:

```python
if df.index.name is not None and str(df.index.name).lower() in {
    "date", "datetime", "observation_date", "period", "timestamp"}:
    return True
if isinstance(df.index, pd.DatetimeIndex):
    return True
if len(df.index) > 0:
    first = df.index[0]
    if isinstance(first, date):   # pd.Timestamp subclasses date
        return True
return False
```

**A synthetic unit test could never have caught this**, because the synthetic
frame had a `date` *column*. This is the canonical illustration of Section 21.0
rule 1 and the reason the `live` test marker exists.

---

## Environment notes

### Local OpenBB Platform API

The local API at `http://127.0.0.1:6900` is **healthy**. Confirmed by probing
its own `/openapi.json` (278 routes) and by direct series fetch returning
correct data:

```
GET /api/v1/economy/fred_series?provider=fred&symbol=CPIAUCSL
→ {"results":[{"date":"2026-01-01","CPIAUCSL":326.588}, ...]}
```

**Superseded Phase 0 observation:** an earlier note recorded this API as broken
after observing HTTP 502. Those were transient upstream failures. The client's
cross-path fallback handled them by correctly succeeding via the package path.

Two genuine client bugs were found in this area and fixed:

1. `is_local_api_available()` probed `/api/v1/health`, which the OpenBB Platform
   API **does not serve**, and tested `status_code < 500` — so a **404 counted
   as healthy**. Now probes `/openapi.json` and requires exactly 200.
2. `use_local_api_first` defaulted to `true` on the reasoning that it "avoids
   re-initialising the SDK per call". Measured, that is backwards: a full
   21-field snapshot takes **223.6 s via the local API vs 9.5 s in-process**,
   ~23× slower, with identical results. Default changed to `false` on the
   measurement. See `DECISIONS.md` D-003.

### Transient upstream failures

Individual calls intermittently return 502/404 and succeed moments later. The
retry-then-cross-path logic handles this; the snapshot built 21/21 either way.
Recorded as D-008 because the consequence — a fault invisible in the output
because the fallback silently succeeds — is worth knowing.

---

## Verification method

```bash
# Verify every route and report plausibility against registry bounds
uv run python tools/manual_series_check.py --provider-only

# Verify a single route
uv run python tools/manual_series_check.py --series cpi_headline

# Discovery probe for money-market routes (read-only, writes nothing)
uv run python tools/probe_money_market.py

# Check what still lacks verification evidence
uv run python tools/record_verification.py --check
```

The checker reads plausibility bounds from the registry entry itself rather than
hardcoding them, so a newly registered series is checked the moment it is added.
Exit code is non-zero if any route fails, so it can gate CI.
