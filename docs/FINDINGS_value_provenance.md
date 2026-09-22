# Findings: what time-varying values the data layer can and cannot obtain

**Date:** 2026-09-20
**Scope:** `src/macro_engine/data_layer/` — the §6 point-in-time provenance contract
**Method:** direct empirical probing of the live OpenBB server at `http://127.0.0.1:6901`,
plus enumeration of all 278 operations / 305 parameters in its OpenAPI surface.

This document lists every value-related field we tested, what it actually contains,
and an explicit verdict. The point is to be able to say *"this is obtainable"* or
*"this is not obtainable, and here is the test that proves it"* — without hedging.

---

## 0. The four timestamps, and why they are not interchangeable

Section 6 requires four distinct timestamps on every `ObservationPoint`. They answer
four different questions:

| Field | Question it answers | Status |
|---|---|---|
| `observation_date` | What period does the value *describe*? | **OBTAINED** |
| `release_datetime` | When did the value *become public*? | **OBTAINED** |
| `vintage_datetime` | Which *revision* of the value is this? | **NOT OBTAINED** |
| `retrieved_at` | When did *this process* read it? | **OBTAINED** |

> **STATUS 2026-09-22 (D-088) — the row above is now historical.** `vintage_datetime`
> is **reachable**: `alfred_client.py` reads ALFRED directly using the credential
> OpenBB already owns, and `fetch_field_vintage` stamps it for any series declared
> `vintage_eligible` (currently `cpi_headline`, `gdp_real`). The right-hand column
> recorded the state **of the OpenBB route** at the time this finding was written,
> and that part is unchanged — the route still cannot do it. Read the rest of this
> document as the evidence for *why the OpenBB route could not*, which is still
> correct and is still the reason the direct route exists. The section below that
> says "not obtainable from this deployment" now needs the qualifier **"via
> OpenBB"**. ALFRED is off by default (`alfred_vintage.enabled: false`).

The failure mode this guards against is substituting `observation_date` for a
release date. A month's CPI is stamped the 1st of that month but is published
mid-way through the *following* month. Treating the stamp as the release date
makes the system look point-in-time correct while actually leaking future
information. That is why the two release-side fields default to `None`
(= UNKNOWN) rather than falling back to the observation date.

---

## 1. `observation_date` — OBTAINED

- **Source:** every time-series route (`economy.fred_series`, etc.).
- **Coverage:** 100% of points, by construction.
- **Confidence:** definitional.

Nothing to flag. This is the anchor field.

---

## 2. `release_datetime` — OBTAINED (two independent routes)

### 2a. Primary — `last_updated` metadata via `economy.fred_search`

- **Route:** `GET /api/v1/economy/fred_search?search_type=series_id&query=<SYMBOL>`
- **Field:** `last_updated` on each result row.
- **Returns:** a real per-series **publication** stamp, historically dated.
- **Coverage at `limit=1000`:** **42 / 42** registry symbols.
- **Transport errors:** 0.
- **Status:** promoted to primary. Implemented in `publication_dates.py`.

**Cross-validation (proves `last_updated` is a publication date, not a period stamp):**

| Series | `observation_date` end | `last_updated` |
|---|---|---|
| PCEPILFE | 2026-07 | **2026-08-26** |
| GDP | 2026-04-01 | **2026-08-26** |

The observation periods end well before the `last_updated` stamp. A period stamp
would equal the period end; these do not. Independent check: the Core PCE
`last_updated` of 2026-08-26 sits one day before the calendar-documented Core PCE
release of 2026-08-27 — consistent with an embargo-boundary stamp.

### 2b. Fallback — release calendar via `economy.calendar`

- **Route:** `GET /api/v1/economy/calendar?provider=nasdaq`
- **Status:** works, but **currently disabled** in the registry
  (`release_calendar.enabled: false`), retained as a documented fallback.
- **Why not primary:** requires an event-name join (fragile — the calendar's event
  labels must be matched to our series), whereas `last_updated` is per-series and
  needs no join.
- **Merge behaviour:** primary-wins on conflict; both are consulted.

### 2c. Do NOT use — the calendar route's failure modes (for the record)

The `economy.calendar` route fails in **three structurally different ways**, all of
which must be distinguished or the failure will be silently mistaken for "no data":

1. **HTTP 200 with `{"detail": ...}`** — an error body wearing a success code.
2. **HTTP 500 from OpenBB wrapping a 403** — the real cause is downstream auth.
3. **Transport error / edge block** — `Server: AkamaiGHost`, `X-Reference-Error`.
   This is **host-wide, not endpoint-specific**, which is why it looked like a
   dead end for so long.

Evidence: an earlier audit concluded no route returned release dates at all. That
conclusion was wrong **twice** — first because `economy.calendar` was tried with
only one of its four providers (`nasdaq` works), and again because enumerating all
278 operations surfaced `fred_search`.

---

## 3. `vintage_datetime` — NOT OBTAINED (established by test, not assumed)

> **SUPERSEDED IN SCOPE 2026-09-22 (D-088).** The verdict below is about the
> **OpenBB route**, and it is still correct: OpenBB pops the vintage fields
> (`openbb_fred/models/series.py:156-157`) and cannot transmit the parameter. But
> "not obtainable from this deployment" was too broad — ALFRED is reachable by a
> direct call, and D-088 implemented exactly that. Read the evidence below as the
> proof of why the OpenBB path fails, which remains the reason `alfred_client.py`
> must never route through it. **The scan for the current state is
> `docs/DECISIONS.md` D-088.**

This is the field the user asked about directly. Verdict: **not obtainable from this
deployment** *via OpenBB* — and here is the evidence.

### What we tried, and what each test showed

**Test A — `realtime_start` / `realtime_end` on `fred_search`:**
The route *does* return these fields. But for **every series, both equal *today***.
They describe the vintage window currently in force — not which revisions existed
historically. This is a live window, not a history.

**Test B — passing `realtime_start` as a query parameter (A/B test):**
**Silently ignored.** Two requests — one with a historical `realtime_start`, one
without — returned structurally identical payloads, differing only in the
`timestamp`/`duration` of the response envelope. So the parameter is accepted,
discarded, and not reported as an error.

**Test C — `economy.fred_release_table` with its `date` parameter:**

This route genuinely exists and genuinely does something interesting. It is
discussed in full in §4 below, because it is the one result worth acting on. The
**short version for vintages specifically**: `date` returns the release *edition*
current at that date, but does **not** expose revisions of a period already
published. Detail and the disproving test are in §4.

### Why this is an entitlement question, not a routing question

The data that would answer "which revision is this" is ALFRED's vintage series.
Reaching it requires a **credentialed FRED/ALFRED API key**, which is not
configured in this environment. So:

- "When did this become public?" → **answerable** (§2).
- "Which revision of this value is it?" → **not answerable here.**

These are different questions. Only the first can be filled. `vintage_datetime`
stays `None`, and `None` means **UNKNOWN** — never "same as observation_date".

---

## 4. `fred_release_table` and its `date` parameter — the one live lead

Discovered by enumerating the OpenAPI surface after the user pointed at the
metadata API. This is the correction of an earlier, too-hasty "dead end" verdict.

- **Route:** `GET /api/v1/economy/fred_release_table`
- **Params:** `release_id` (required), `element_id` (optional), **`date`** (optional,
  documented as *"A specific date to get data for"*).
- **Release IDs:** `fred_search` with `search_type=release` enumerates them.
  Confirmed: `10` = CPI, `53` = GDP, `116` = Unemployment.

### What `date` demonstrably does

The returned values **change with `date`**. That is real historical state, not the
latest series.

CPI, `release_id=10`, `element_id=34483`, symbol `CPIAUCSL`:

| requested `date` | returned `observation_date` | returned `value` |
|---|---|---|
| 2024-01-11 | 2024-01-01 | **309.698** |
| 2025-01-15 | 2025-01-01 | **318.961** |
| 2026-06-10 | 2026-06-01 | **332.568** |
| 2026-08-12 | 2026-08-01 | **334.131** |
| *(no date)* | 2026-08-01 | 334.131 |

GDP, `release_id=53`, `/1.1.1/Quarterly` (element `38375`), symbol `A191RL1Q225SBEA`:

| requested `date` | returned `observation_date` | returned `value` |
|---|---|---|
| 2024-01-25 | 2024-03-31 | 0.8 |
| 2024-04-25 | 2024-06-30 | 3.6 |
| 2025-07-30 | 2025-09-30 | 4.4 |
| 2026-01-29 | 2026-03-31 | **2.1** |
| 2026-04-30 | 2026-06-30 | 1.5 |
| *(no date)* | 2026-06-30 | 1.5 |

### The 204 boundary — a usable signal

- `date` **before** a release's first publication → **HTTP 204 No Content**.
- `date` in the **future** → **HTTP 204 No Content**.
- `date` **after** a release but before the next → 200, with that edition's figures.

The 204↔200 transition therefore marks a genuine **publication boundary**.

### The disproving test for vintages (this is the important part)

The question that decides between "point-in-time edition" and "revision history" is:
*does one observation period's value ever change when requested at a later date?*

**It does not.** Chasing one observation period forward:

**CPI, obs `2026-07-01`:**

| requested `date` | obs | value |
|---|---|---|
| 2026-07-10 | 2026-07-01 | 332.813 |
| 2026-07-16 | 2026-07-01 | 332.813 |
| 2026-07-25 | 2026-07-01 | 332.813 |
| 2026-07-31 | 2026-07-01 | 332.813 |
| 2026-08-05 | **2026-08-01** | **334.131** ← window moved on |

**GDP, obs `2026-03-31`:** value `2.1` at request `2026-01-29`; every request from
`2026-04-01` onward jumps to the newest table entirely, rather than returning a
revised Q1 figure.

**Verdict on §4:** `date` selects **which release edition was current** at that date.
When a newer period is published, the window advances — it does not retain "what we
previously believed about *this* period". So this gives a
**publication-boundary oracle** (useful — see §5) but **not** a vintage oracle.

---

## 5. Summary table — every field, with verdict

| Field | Obtainable? | Where it comes from | Verdict |
|---|---|---|---|
| `observation_date` | **YES** | every series route | definitional |
| `release_datetime` | **YES** | `last_updated` (`fred_search`) 42/42; calendar fallback | primary source live |
| `vintage_datetime` | **NO** | — | needs credentialed ALFRED key; `realtime_*` are today-only and ignored as params |
| `retrieved_at` | **YES** | local clock, set at read | definitional |
| publication **boundary** (204↔200) | **YES** | `fred_release_table` + `date` | usable, not yet harvested |
| revision-of-a-known-period | **NO** | — | proven by chase-forward test in §4 |
| `last_updated` | **YES** | `fred_search` | real publication stamp |
| `realtime_start` / `realtime_end` | **partially** | `fred_search` | always today — current window, not history |
| release IDs / `release_id` | **YES** | `fred_search?search_type=release` | enumerable (10=CPI, 53=GDP, 116=Unemp) |
| release table tree | **YES** | `fred_release_table` + `element_id` | walkable: section → table → data rows |
| FRED `value` per release table row | **YES** | `fred_release_table` | edition-current, not vintage |

---

## 6. What this means in practice

**Safe to state:** for each point, *when* it became public. That is now populated
across the registry and the live build reports `release_source: publication_dates`
with no `RELEASE_TIMING_UNKNOWN` flags.

**Not safe to state:** which revision a value is, or what a past release *said*
about a period it has since revised. Any reasoning that depends on "the number as
it was known then" is **not supported** by this data source.

**One improvement is available but unbuilt:** harvest the 204↔200 publication
boundary per series to derive exact `release_datetime` values, with no API key
required. Cost is roughly one request per candidate day per series, so it needs
caching. This is a genuine capability and worth doing — but it strengthens §2, not
§3. It does not move `vintage_datetime` off `None`.

---

## 7. Method note

An earlier pass concluded `vintage_datetime` was a "genuine dead end" after a
keyword search over two endpoints. That was methodologically wrong: it sampled the
surface instead of enumerating it. Enumerating all **278 operations and 305
parameter names** is what surfaced both `fred_search` (fixing `release_datetime`)
and `fred_release_table` (the lead in §4).

The lesson worth keeping: **enumerate the surface before declaring an absence.**
The corrected verdict is more precise than either the original claim or the
pushback against it — the routes exist, `release_datetime` is now populated, and
`vintage_datetime` is still unfillable, but for a *tested* reason rather than an
assumed one.
