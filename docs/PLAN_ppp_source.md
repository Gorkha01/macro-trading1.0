# PLAN — `ppp_implied_rate`: is the data really "not found anywhere"?

**Written 2026-09-27, immediately after D-114 shipped `ppp_valuation`.**
**Status:** a **MEASUREMENT**, not a proposal to change code yet. It answers one
question the operator asked — *"is the data not found anywhere?"* — and it changes
what the next increment should do about `ppp_valuation`'s input.

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
