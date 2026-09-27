# PLAN — `ppp_implied_rate`: is the data really "not found anywhere"?

**Written 2026-09-27, immediately after D-114 shipped `ppp_valuation`.**
**Status: ✅ EXECUTED — BOTH PHASES DONE. Plan C (record the finding) landed at
D-115/D-116; Plan A (wire the LIVE source) landed at D-117.**
This document began as **a MEASUREMENT, not a proposal to change code** — it
answered one question the operator asked: *"is the data not found anywhere?"*
Its §4 recommendation (*"Plan C now, Plan A as its own increment later"*) was
followed exactly, and §6 is the **completed** answer to the operator's follow-up
question about the four named sources.

> **⚠️ READ THIS FILE AS HISTORY, NOT AS A TO-DO.** Nothing here is outstanding.
> What shipped: `ppp_implied_rate` is now **`LIVE`** (§21.1), fetched by
> `src/macro_engine/data_layer/world_bank_client.py` from the World Bank REST API
> (`PA.NUS.PPP`). The **fetch is the only live path** (no MANUAL fallback), the
> euro leg is **DEU**, and the ALFRED question in §6 resolved to **"no — none of
> the four is a substitute"**. Where this file and `DECISIONS.md` D-117 disagree,
> **D-117 is the record of what was actually built.**

---

## 1. The question, and why it is the right one to ask

D-114 shipped `ppp_valuation` with `ppp_implied_rate` as a **`BLOCKED → MANUAL`**
input (§21.1, `AGENTS.md:5384`): *"OECD publishes PPP conversion factors; no clean
free API. Manual entry with a documented vintage."* The live check declared
`_PPP_LEG = 0.72` and disclosed the vintage.

**"BLOCKED" is a claim about the world**, and this project has already been wrong
about such claims three documented times:

* **D-043** — §21.1 said *"No clean free series for leveraged-loan growth"*; a
  single `fred_search` query found `BOGZ1FL623069503Q`. **A FALSE BLOCK.**
* **O-104** — the *"2 of 201 OpenBB commands"* figure was a **stale count** left
  standing.
* **D-047's lesson**, recorded verbatim in `config/series_registry.yaml:1182-1187`:
  *"a `blocked:` list catches FALSE blocks because a false entry is auditable. It
  cannot catch an ABSENT one … Any input the specification calls MANUAL or
  unreachable should therefore get a `blocked:` entry on the day it is discovered,
  even when the reason is only 'the specification says so'."*

`ppp_implied_rate` **already has a `blocked:` entry**
(`config/series_registry.yaml:1193-1195`), so it is auditable — and D-043's
precedent is to **re-probe it** rather than trust the prose. This document is that
re-probe.

---

## 2. What was measured (2026-09-27)

Every claim below is a command output, not a recollection.

### 2.1 OpenBB — genuinely no PPP

```
tools/openbb_reachability.py            ->  serving, 278 paths
GET /openapi.json, grep for
  ppp | purchas | conversion | price.level | oecd | reer | rer
                                        ->  0 paths of 278
```

**No OpenBB endpoint exposes PPP.** The spec's *"no clean free API"* is **TRUE for
OpenBB**.

### 2.2 FRED — reached, but not the conversion factor

The OpenBB FRED transport works (control: `DGS10` returns rows). A
`fred_search` for *"purchasing power parity"* returns **PPP series that exist** —
e.g. `MEXPPPSH` *"Purchasing Power Parity, Share of World for Mexico"* — but these
are **shares of world PPP**, not a conversion factor. Direct probes of the
conventional conversion-factor IDs (`PPPTTL`, `PPPTTLUS`, `PA.NUS.PPP`, `PPPGDP`)
return **empty**.

**FRED carries PPP-derived series but not (under these IDs) the conversion factor.**
Not decisive on its own — but it proves the transport is fine and the IDs are what
matter.

### 2.3 World Bank REST — **REACHABLE, and this is the finding**

The spec already sanctions this exact route for sibling inputs: §21.1 lists
`current_account_pct_gdp` as *"IMF IFS / World Bank REST **(direct, not OpenBB)**"*.

```
GET https://api.worldbank.org/v2/country/{ISO3}/indicator/PA.NUS.PPP?format=json
    (indicator: "PPP conversion factor, GDP (LCU per international $)")
```

| Country | Non-null points | Latest value |
|---|---|---|
| **USA** | 36 | `1` (by construction) |
| **DEU** | 36 | **`0.709983`** (2025) |
| **FRA** | 36 | `0.677618` |
| **GBR** | 36 | `0.677133` |
| **EMU** (aggregate) | **0** | *(not published)* |

**The data exists and is fetchable.** The DEU series is annual and current
(`0.709983` for 2025, `0.700862` for 2024, `0.701054` for 2023).

**Independent corroboration of D-114's manual leg:** the live check declared
`_PPP_LEG = 0.72`. The World Bank's DEU 2025 value is **`0.709983`** — within
**1.4 %**. The hand-entered figure was *the right number*; the question is whether
it should be *typed* when it can be *fetched*.

---

## 3. What this changes — three candidate plans

### Plan A — Upgrade to a LIVE (direct REST) source · *recommended, but sequenced*

`ppp_implied_rate` becomes a **`LIVE (direct, not OpenBB)`** input, fetched from
the World Bank `PA.NUS.PPP` indicator for the **country legs** of the pair, with
the annual frequency and the publication lag **disclosed** (the series is annual;
the 2025 point was published 2026-07-13, so the current point is always a few
months old — a *vintage*, but a *fetched* one).

* **Pro:** removes a MANUAL input; D-043's lesson says a re-probe that finds a
  source should be acted on, not recorded.
* **Caveats that must travel with it:**
  * **The EMU aggregate is empty** — the pair's euro leg must come from a
    **member state** (DEU/ FRA) or a constructed aggregate. **This is a real
    decision**, not a detail: "USD per EUR at PPP" has no single official value.
  * The indicator is **annual and lagged** — a *fresher-looking* number is not
    available, so the model's `limitations` must say the leg is a **fetched
    vintage**, not a live price.
  * The unit is **LCU per international $**, which for a USD-base pair is exactly
    the PPP-implied spot the model wants — **but this must be asserted, not
    assumed** (D-114's own live check verified `+58.35 %` by interrogating the
    magnitude; the same discipline applies).

### Plan B — Keep MANUAL, add the source as an OPTIONAL fetch

The input stays `float` (MANUAL-capable) but the model/library gains a **helper**
that fetches the World Bank value, so a caller may pass either a typed vintage or
a fetched one. **Pro:** non-breaking (D-114's tests keep passing). **Con:**
two code paths for one number, and the "which one did the thesis use" question
returns — the exact ambiguity §21.1 tries to remove.

### Plan C — Keep MANUAL, record the finding only

Update the `blocked:` entry's reason from *"no clean free API"* to *"reachable via
the World Bank REST API; held MANUAL at D-114 pending the operator's call."*
**Pro:** zero code risk. **Con:** leaves a **known-reachable** input typed by
hand, which is the state D-043 called *"a premise that was factually wrong"*.

---

## 4. Recommendation and sequencing

**Recommended: Plan C now, Plan A as its own increment later.**

**Why not fold A into D-114:** D-114 shipped, was pushed, and **CI-verified green**
(`18cedc1`, run `36279462642`). Widening its input resolution now would be a
**second function-shaped change** — a new data path, a new registry entry, a new
failure mode (network) — smuggled into a finished increment. The standing rule is
**one function per increment**; a source upgrade is its own job.

**Why C is not merely a delay:** D-043's defect was not *"a source existed and we
did not use it"*; it was *"the registry asserted no source existed, and that
assertion was false."* **Correcting the assertion is the defect fix.** Whether to
*wire* the source is the next increment's scope decision.

**What the next increment (call it a `ppp_valuation` source upgrade) must do, if
approved:**

1. **Decide the pair's legs explicitly** — the EMU aggregate is empty, so name
   which country series stand in for "euro area" and say why (a decision entry,
   not a constant).
2. **Add a `series:` registry entry** for the chosen World Bank indicator(s), with
   the frequency (annual), the vintage lag, and the unit (LCU per intl $).
3. **Assert the unit** — a test that the fetched value is the PPP-implied *spot*
   the model expects, not its inverse or a price index (D-114's live-check
   discipline, in test form).
4. **Keep the MANUAL path** as the declared fallback, so a network outage does not
   turn a thesis into a crash (§21.0: no invented inputs).
5. **Demonstrate the failure mode** the manual input was hiding: what does the
   model publish when the source is *stale* vs *absent*? (D-110's rule: a
   disclosure that can become an assertion should become one.)

---

## 5. The one-line answer to the operator's question

**No — the data is not "not found anywhere."** It is absent from **OpenBB** (0 of
278 paths, measured) and from **FRED** under the conventional conversion-factor
IDs; it **is** reachable via the **World Bank REST API** (`PA.NUS.PPP`), the same
*"direct, not OpenBB"* route §21.1 already uses for `current_account_pct_gdp` — for
**member countries** (DEU `0.709983`, FRA `0.677618`, GBR `0.677133`) but **not**
for the **EMU aggregate**. **D-114's `0.72` was in the right place (within 1.4 % of
DEU's 2025 value), so the model's number is sound; but `ppp_implied_rate` is very
likely another **FALSE BLOCK** (D-043's class), and the honest next step is to
correct the registry's claim and then decide — as its own increment — whether to
wire the source.

---

## 6. The four user-named sources, measured (2026-09-27)

The operator named four free PPP sources and asked whether one could serve as an
**ALFRED-style client**. That is a **specific architectural claim**, and it is
decided by one property, not by general reputation. This section measures all
four — plus the one thing that actually decides between them.

### 6.0 The criterion is NOT "does it have PPP data"

The engine already has a vintage client:
`src/macro_engine/data_layer/alfred_client.py`. Its contract is exact, and it is
the contract a candidate must satisfy to be an ALFRED-style substitute:

* `fetch_vintage_observations(series_id, as_of)` sets
  **`realtime_start == realtime_end == as_of`** — a **point-in-time selector**,
  returning *the values in force on that date* (measured: a date before
  publication returns `{}`, an honest empty set — `alfred_client.py:71-86`).
* `VintageUnavailableError` is **deliberately fatal**: *"a vintage that silently
  degrades to 'latest' is worse than no vintage at all."*
* The whole module exists because O-6 proved the OpenBB route **absorbs**
  `realtime_start` silently and returns the latest revision with HTTP 200.

So the deciding question is: **can the source return a specific past state, or
only "latest"?** A source that returns only latest is *useful data* but **not an
ALFRED-style client** — and wiring it as one would reproduce O-6's exact defect.

### 6.1 Measurement table

| Source | Reachable | Item is a **conversion factor**? | **Vintage / revision** retrieval | EMU aggregate |
|---|---|---|---|---|
| **World Bank** `PA.NUS.PPP` | **YES** (JSON REST) | **YES** — "PPP conversion factor, GDP (LCU per intl $)" | **NO** — latest only; `lastupdated` is a *publication* date, not a vintage selector | **EMPTY** (0 points) |
| **World Bank** `PA.NUS.PRVT.PP` | **YES** | **YES** — private-consumption conversion factor, DEU `0.718883` (2025) | **NO** — same | EMPTY |
| **IMF** `PPPEX` (DataMapper) | **YES** | **YES, by name** — "Implied PPP conversion rate" | **NO — and worse than NO** (see 6.3) | **ignored** (see 6.3) |
| **IMF** `PPPGDP` / `PPPPC` / `PPPSH` | YES | NO — PPP-**denominated GDP** / per-capita / world share, **not** a conversion factor | NO | n/a |
| **OECD** `DSD_PPP@DF_PPP` | **YES** (SDMX-JSON) | **YES** — `MEASURE=PPP`, `UNIT_MEASURE=XDC_USD`/`XDC_EUR`; DEU `0.701` base-USA (2023) | **NO** — latest only; a naive keyed query returned `NoRecordsFound` | **YES** — `EU27_2020` published (a *real* difference from World Bank) |
| **Eurostat** `prc_ppp_ind` | **YES** (JSON-stat) | **NO** — it is a **price level INDEX** (`PLI_EU27_2020`, EU27=100), not a conversion factor | **NO** | EU27 (not EMU) |

### 6.2 World Bank — the one to wire, and what it cannot do

Two indicators, both reachable, both fetched with a `lastupdated` field:

```
PA.NUS.PPP        (GDP conversion factor)          lastupdated 2026-07-13
  DEU 2025 -> 0.709983 | 2024 -> 0.700862 | 2023 -> 0.701054
PA.NUS.PRVT.PP    (private consumption)             lastupdated 2026-07-13
  DEU 2025 -> 0.718883 | 2024 -> 0.701547 | 2023 -> 0.702414
```

**It is the right *item* and it is fetchable.** What it is **not** is
vintage-capable: `lastupdated` tells you *when the current figure was refreshed*,
not *what the figure was on a chosen past date*. There is no
`realtime_start`-equivalent on the World Bank REST API. **It is therefore Plan A's
source (a `LIVE (direct, not OpenBB)` input), not an ALFRED-substitute.**

### 6.3 IMF — right name, wrong content, and a silent-parameter trap

The IMF DataMapper exposes `PPPEX`, labelled literally **"Implied PPP
conversion rate"** — the *exact estimand name*. Two measured disqualifiers:

1. **The values are WEO projections, not realizations.** DEU returns 52 points
   through **2031** (`2025:0.723, 2026:0.722, 2027:0.724 … 2031:0.737`) — that is
   a *forecast* of the conversion rate, which is not the same object as a
   *published* one. Using it would put a projected number where the model
   documents a vintage.
2. **`?version=` is silently absorbed — O-6's exact defect, reproduced.**
   Measured:

   ```
   GET /PPPEX/DEU                 2025 -> 0.723      (n=52)
   GET /PPPEX/DEU?version=2025-04  -> NO DEU SERIES  (HTTP 200, "same as base": False)
   GET /PPPEX/DEU?version=1990-01  -> NO DEU SERIES  (HTTP 200)
   ```

   The parameter does not select a vintage; it *corrupts* the read while returning
   HTTP 200. **This is the same failure mode O-6 recorded for OpenBB**, and it is
   the reason `alfred_client.py` forbids an OpenBB fallback path structurally.
   The EMU/EA/EU "aggregates" return HTTP 200 but the payload is **the same
   all-country block** — the code is ignored, not honoured. *(A 200 that means
   "parameter ignored" is precisely the trap this ledger exists to record.)*

**Verdict: IMF is the most dangerous of the four** — it has the right *label*, so
a keyword-driven integration would wire it, and it would then silently serve
latest-or-corrupted data behind a vintage-shaped API.

### 6.4 OECD — the richest PPP dataset, but a different vintage semantics

`DSD_PPP@DF_PPP` is genuinely large (44,064 series for 2022+), carries a real
conversion factor (`MEASURE=PPP` + `UNIT_MEASURE=XDC_USD`), and — uniquely — a
published **`EU27_2020` aggregate** (`XDC_USD` base-OECD `0.8`, base-USA `0.625`).
Reference values measured base-USA:

```
DEU 0.701 (2023) | FRA 0.679 (2023) | GBR 0.661 (2023) | EU27_2020 0.625 (2023)
```

SDMX has a **`updatedAfter` parameter** (HTTP 200) that filters by *modification
time* — but that is **not** a point-in-time vintage selector either: it answers
"what changed since T", not "what was true at T". There is **no `NoRecordsFound`
-free** path to a chosen past state, and a fully-keyed query returned
`NoRecordsFound`. **Verdict: a strong live source, not an ALFRED-substitute.**

### 6.5 Eurostat — wrong item

`prc_ppp_ind` returns a **price level index** (`PLI_EU27_2020`, EU27=100; 30 time
keys, `updated 2025-07-10`), **not** a conversion factor and **not** an implied
PPP rate. Changing the *item* is not comparable to the estimand. **Verdict: not
eligible** for `ppp_implied_rate`, whatever its vintage properties.

### 6.6 The answer to "can we use one as an ALFRED-style client?"

**No — none of the four can.** Not because they lack PPP data (three have it, in
the right unit), but because **not one of them implements a specific-vintage
selector**, which is the *only* property that makes `alfred_client`'s contract
satisfiable. Wiring any of them as a vintage source would reproduce **O-6's
silent-absorption defect** — the precise thing that module exists to prevent.

**What they *can* do, and the correct sequencing:**

* **Wire the World Bank as a `LIVE (direct, not OpenBB)` input** for
  `ppp_implied_rate` — **Plan A**, unchanged by this section. It is the same
  route §21.1 already sanctions for `current_account_pct_gdp`. It removes a
  MANUAL input and it is honest about being *latest-with-a-publication-date*
  rather than a vintage.
* **Keep the MANUAL path as the declared fallback** (Plan A step 4) — the World
  Bank's freshness guarantee is a *publication date*, and an annual series with a
  publication lag is a **disclosed vintage**, not a live price.
* **Do NOT route IMF `PPPEX`**, despite the attractive label: its content is a
  WEO projection and its vintage parameter is silently absorbed.
* **Use OECD only if the `EU27_2020` aggregate is needed** — it is the one
  measured advantage (World Bank's EMU aggregate is empty). Treat it as a second
  *live* source for the euro leg, decided in a later increment, **not** as a
  vintage client.

**Bottom line for the operator's question:** "use them as an ALFRED client" is
**not available** — measured, not asserted. The ALFRED-style capability for this
engine remains FRED/ALFRED-only (`alfred_client.py`), and the four sources are
candidates for a **live input upgrade**, of which the **World Bank** is the right
one and the **IMF is the one to avoid**.
