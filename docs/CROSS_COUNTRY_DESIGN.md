# Cross-country reasoning — the fourth and last layer (design record)

> **SHIPPED 2026-10-10 (D-150).** This file was the design record written *before* implementation; §5
> below is the shipping record — **what actually landed, and where it deviated from the design**. Read
> §5 first if you want the current state; §1–§4 are the reasoning that produced it.

**Started 2026-10-10.** This is **layer 4** of the four-layer multi-country bar
(`docs/PHASE5_DEFERRED.md` §2.4.1) — the single capability still refused after `gb`, `eu`, `de` and
`jp` all landed end-to-end. The operator's instruction: *"start below with actual institutional
knowledge and self verification."*

The increment removes the last multi-country block: `CROSS_COUNTRY_DIVERGENCE` currently returns
`BLOCKED_MULTI_COUNTRY_NOT_BUILT` (`models/instrument_selection.py:505`) because, per §22.3, it needs
**two fully-built country systems AND a bridge between them.** Both conditions are now met (five
countries + the live FX spot layer), so the block must be **replaced by a real derivation**, not
merely flipped.

---

## 1. The institutional basis (primary sources)

A cross-country rates trade is the single most standard expression of a macro divergence view, and it
has a **canonical structure** that this layer must reproduce rather than invent.

### 1.1 The trade is a bet on the SPREAD, not the level
The canonical reference (and the one the spec itself names — `AGENTS.md` §22.3.1's rule table:
*"Cross-country policy divergence → cross-market RV (e.g., long US 10yr, short Bund)"*) is a
**duration-neutral relative-value** position: **long** the bond of the country whose yield is expected
to fall more (or rise less), **short** the other, sized so a *parallel* move in global yields cancels.
The payoff is linear in the **spread change**:

```
P&L(x) = x bp of spread change * DV01_per_bp          (DV01-neutral legs)
```

So the *reasoning* the engine owes the trader is **not** "US 10y is 4.3% and Bunds are 2.4%" — that
compares two numbers on different bases. It is **the sign and magnitude of the divergence, and whether
it is likely to compress or widen**. (Sources: the rates-RV literature; the spec's own §22.3.1.)

### 1.2 Three legs of a genuine divergence, each measurable
1. **Nominal policy/yield differential** — the raw spread, the thing the trade prices.
2. **Real-rate differential** — *nominal policy rate − headline CPI YoY*. This is the institutional
   headline comparison: *"a 4% policy rate against 5% inflation is looser than a 1% rate against zero
   inflation, even though the nominal level is far higher."* The **stance asymmetry** lives here.
   (Source: standard real-rate-differential practice across central-bank commentary.)
3. **Inflation-expectations differential** — the **breakeven** gap. A nominal yield spread mixes
   expected inflation and real rates; the breakeven (nominal − TIPS/indexed) isolates the
   expectations leg, which is a *different* thesis (INFLATION_EXPECTATIONS_GAP) in the spec's own
   vocabulary.

### 1.3 The FX bridge is what makes them comparable
Without FX the comparison is meaningless. The layer **must** route the two countries' quantities
through `models/fx_conversion.py` before any subtraction, and must state the basis (same currency,
same tenor, same horizon). `fx_spot` is live as of 2026-10-10.

### 1.4 The two ways a cross-country thesis is WRONG (the traps this layer must refuse)
- **Comparing different bases.** Two yields on different currencies/maturities/horizons is the
  definition of a fake spread. Refused: mismatched tenor or horizon; and an unconvertible pair.
- **The LTCM caveat.** A cross-market RV trade assumes the spread is stable enough to be a spread —
  in stress, correlations break and the two legs move together *adversarially*. §22.3.1 says this
  explicitly (*"correlation-dependent, LTCM tail-risk caveat applies"*), so the layer must **publish a
  stress-degradation measure** rather than imply the spread is riskless.

---

## 2. The contract the layer must satisfy (measured, not assumed)

Read from the shipped code, so the layer plugs in rather than restating anything:

| What exists | Where | What the layer must do |
|---|---|---|
| `CROSS_COUNTRY_DIVERGENCE` member | `ThesisType`, `instrument_selection.py:107` | route it, don't refuse it |
| the block | `instrument_selection.py:505` | replace with a real branch |
| `construct_cross_market_rv(CrossMarketRVInputs)` | `yield_curve.py:1516` | **feed** it (`market_a/b`, `duration_a/b`, `target_notional_a`, `correlation_normal`, `correlation_stressed`) — the trade-construction primitive already exists and is tested |
| `fx_conversion.convert(amount, frm=, to=, rate=FxRate)` | `models/fx_conversion.py:113` | route every cross-currency subtraction through it |
| `de` snapshot carries `eu_*` comparators | `orchestration.py:2906` (`_de_thesis_inputs`) | the **precedent**: a country snapshot may carry a counterpart-country's fields |
| `MacroDataSnapshot.country: str` | `data_layer/schemas.py:204` | one snapshot = one country; a cross-country record needs both countries' fields |

**The two result shapes** (O-87): `select_instrument` returns a **dict** on executable routes and a
**bare sentinel string** on refused ones. The new branch must return the dict shape; the sentinel's
meaning changes from "no second country exists" to "this specific pair is not convertible / not
comparable", which is a **narrower, honest** refusal.

---

## 3. The design

### WS1 — data: the comparator fields
A cross-country snapshot carries **both** countries' fields, exactly as the `de` snapshot carries the
`eu_*` comparators. No new fetch machinery: the series already exist in the registry per country. What
is new is a **pair resolver** naming which two countries and which shared basis.

### WS2 — the model: `cross_country_divergence` (a NEW function)
A pure function `cross_country_divergence(inputs)` → `ModelResult` that, given two countries' records
(each with a policy rate, headline inflation, a 10y yield, a breakeven if available, and a currency),
computes:

1. **nominal yield differential** (bp) — `y_a − y_b`, *after* confirming same tenor/horizon;
2. **real-rate differential** (pp) — `(i_a − π_a) − (i_b − π_b)` — the stance asymmetry;
3. **a divergence verdict** — sign + magnitude, against a config threshold, ignoring a differential
   that is inside the noise band;
4. **the FX-converted basis** — the two 10y yields expressed in ONE currency via `fx_conversion`;
5. **the stress-degradation disclosure** — the LTCM caveat, published.

It refuses (raises/named warning): two different tenors, two different horizons, a same-currency call
routed as cross-country, and an unconvertible pair.

**Why this is not a relabelled single-country rule** (the §22.3 un-fakeable test): a single-country
rule produces *a rate for one country*. This produces *a signed, FX-bridged differential between two
countries' conditions plus a stress disclosure* — a quantity that **does not exist** until two
complete country systems and a bridge are both present. It is the layer-4 primitive by construction.

### WS3 — wiring + the guard
- `select_instrument` gains the real `CROSS_COUNTRY_DIVERGENCE` branch: build the model result, and on
  a *meaningful* divergence feed `CrossMarketRVInputs` (long the higher-real-rate country's 10y, short
  the other), returning the executable dict. On a *not-meaningful* divergence, return the analytical
  sentinel with "spread inside the noise band" (an honest non-trade, not a build block).
- The `BLOCKED_MULTI_COUNTRY_NOT_BUILT` sentinel is **retained** for the genuinely un-comparable cases
  (an unconvertible pair) — narrower meaning, documented.

### Config
New `cross_country:` block: the **noise band** on the differential (a `fitted_assumption`), the shared
horizon, and the supported pairs. Every leaf carries unit + provenance + a *mover* proof (LAW 1).

---

## 4. Sources

- `AGENTS.md` §22.3.1 — the instrument-selection rule table (the spec's own cross-country mandate).
- `models/yield_curve.py` `construct_cross_market_rv` / §20.12 — the shipped trade constructor.
- `models/fx_conversion.py` — the CIP-derived bridge (D-147).
- Rates relative-value structure (spread-not-level; duration/DV01-neutral sizing; convexity drift).
- Real-rate-differential practice: nominal policy rate − headline CPI YoY as the stance comparison.
- §22.3.1's own "LTCM tail-risk caveat" for the stress disclosure.

---

## 5. The shipping record — what landed, and where it deviated

**D-150, 2026-10-10.** Shipped: `models/cross_country.py` (the model), the `cross_country:` config
block + `CrossCountrySettings`, the `_select_cross_country_instrument` branch in
`instrument_selection.py`, and the `build_us_macro_thesis(cross_country=...)` linkage —
`tests/models/test_cross_country.py` has 15 tests, the suite is at 1967 passed, all four gates green.

**Deviations from the design above, each deliberate:**

1. **`construct_cross_market_rv` is NOT fed by this layer.** §3/WS3 above proposed feeding the
   divergence straight into the trade constructor. It does not: the selector **names** the pair and
   stops, because **sizing is Module 15.3's** and coupling selection to sizing would put the DV01
   weights inside `select_instrument` — a second implementation of a quantity that already has one
   (LAW 2), and the `decision_prohibition` on the result says so explicitly. The trade constructor
   remains the sizing primitive; the selector declares the instrument.
2. **The model is a SEPARATE module, not a branch in `instrument_selection`.** The divergence is a
   *quantity*; the instrument is a *choice among expressions*. Keeping them apart means the quantity
   has ONE implementation and the selector reads a measured number rather than re-deriving it.
3. **The FX reconciliation is an INPUT, attested by `fx_converted`, not a call made here.** The design
   (§3/WS1) proposed the layer itself route through `fx_conversion.convert`. Instead, `CrossCountryInputs`
   requires the caller to have reconciled and to **attest** it — because `fx_conversion` converts
   *amounts*, and the legs here are *levels* (rates), which are not amounts. Converting a rate level
   through an FX rate is not the operation the bridge performs; the honest contract is to require the
   comparability as an input and refuse an un-attested cross-currency pair.
4. **`BLOCKED_MULTI_COUNTRY_NOT_BUILT` is retained but narrowed** (as §3/WS3 predicted): it now fires
   only on a malformed divergence record, never for "no second country exists".
5. **The two-snapshot orchestration — SHIPPED 2026-10-10 (D-153).** The design assumed a "cross-country
   snapshot carrying both countries' fields" (§3/WS1); the shipped layer instead takes the two
   countries' derived levels as an **input record**, so the model was reachable through the builder
   without a new snapshot shape. **The API-level path is now built**: `cross_country_thesis_inputs`
   (`api_layer/orchestration.py`) takes **two ordinary country snapshots**, derives each leg through
   that country's own derivation, and drives the divergence from one call — `docs/PHASE5_DEFERRED.md`
   §2.4.2. It is a **separate entry point**, not a nullable second argument on
   `snapshot_to_thesis_inputs`: the one-snapshot dispatch is one-snapshot by construction, and a
   nullable argument would let a caller pass one snapshot twice and get a zero-by-construction
   difference. Two leg-reader defects were fixed in the same increment (a US policy-rate field that
   disagreed with `_policy_rate`'s `iorb`-first preference; an index level published as a rate) — both
   recorded in the CHANGELOG's D-153 entry.

**The classifier trap measured during implementation:** `ProductionUniverse.category_for` is
keyword-based, so `"US 10y vs EU 10y"` classifies as `None` (refused) while `"UST 10y vs Bund 10y"`
classifies as `rates`. The `instrument_template`'s leading `"UST"` token is therefore load-bearing, and
`label_for(country)` raises for an unconfigured country rather than emitting a placeholder.
