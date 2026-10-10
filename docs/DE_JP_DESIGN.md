# `de` / `jp` — the third and fourth multi-country increments (design record)

**Started 2026-10-10; SHIPPED the same day as D-149.** Completes §22.3's per-country bar for the last
two named countries: with this increment **all five modelled countries** (`us`, `gb`, `eu`, `de`,
`jp`) are implemented end-to-end, and the only remaining multi-country capability is the cross-country
*reasoning* layer. The operator's instruction: *"finish remaining for multi country for both end to
end and in production way and with actual institutional knowledge for data — use that openbb expose api,
they have lots; query them properly, don't say they did not provide."* **Full evidence (rule math,
the 20/20 mutation sweep, the live theses): `docs/DECISIONS.md` §D-149.**

## 1. The data probe (MEASURED live on the OpenBB service, `:6900`)

Every route below was **CALLED**, not enumerated from the inventory (the D-137 / §5.1 lesson).

| Leg | Route | Provider | Japan | Germany |
|---|---|---|---|---|
| CPI YoY | `economy.cpi` | **imf** | 2026-08 = **1.963%** | 2026-08 = **2.862%** |
| CPI YoY (alt) | `economy.cpi` | oecd | **STALE 2021-06** | 2025-12 |
| CPI YoY (alt) | `economy.fred_series` | fred | `CPALTT01JPM659N` **STALE 2021-06** | — |
| Unemployment | `economy.unemployment` | **oecd** | 2026-08 = 2.6% | 2026-08 = 4.3% |
| GDP real | `economy.gdp/real` (`frequency=quarter`) | **oecd** | 2026-04 | 2026-04 |
| Interest rates | `economy.interest_rates` | **oecd** | 2026-08 = 1.56% | 2026-09 = 2.635% |
| 10y yield | `economy.fred_series` | fred | `IRLTLT01JPM156N` 2026-08 = 2.94% | `IRLTLT01DEM156N` 2026-08 = 3.18% |
| 3m rate | `economy.fred_series` | fred | `IR3TIB01JPM156N` 2026-07 = 1.458% | `IR3TIB01DEM156N` 2026-08 = 2.513% |
| Call/interbank | `economy.fred_series` | fred | `IRSTCI01JPM156N` 2026-08 = 0.977% | `IRSTCI01DEM156N` 2026-08 = 2.187% |
| CLI | `economy.composite_leading_indicator` | **oecd** | 2026-09 = 100.35 | 2026-09 = 101.01 |
| Full snapshot | `economy.country_profile` | **econdb** | policy_rate 1.043% | yield_10y 3.069% |

### The FALSE BLOCK (D-043 class, caught before it was recorded)

**Japan CPI on the OECD route AND on FRED stops at 2021-06.** `JPNCPIALLMINMEI`,
`CPALTT01JPM659N` and OECD `economy.cpi` all end 2021-06 — five years stale. A probe that
stopped there would file "Japan CPI is unavailable" as a measured constraint.

**It is not.** The **IMF provider** on `economy.cpi` serves Japan CPI **current to 2026-08**
(`series_id CPI::CPI::CPI__T`, unit "Year-over-year (YOY) percent change"). The route was
never the problem; the *provider* was. **This is the seventh FALSE BLOCK** of the class this
repo tracks — a sourcing claim that reads like a measurement but was an un-tried route.

## 2. The institutional structure that decides the reaction functions

This is the part that cannot be faked, and the research (primary sources, below) fixes it:

### Germany: **no own monetary policy.**
The Bundesbank's own site: *"The Bundesbank is responsible for conducting the Eurosystem's
monetary policy operations with German counterparties"* — the **ECB Governing Council sets the
single policy rate** for the currency union. So a "German Taylor rule" would be a **relabelled
ECB rule** — exactly the §22.3 / D-146 trap, and worse than the gb case because Germany does not
even have a separate rate to relabel.

**The genuinely distinct German content is the *appropriateness gap*: how the ECB's single stance
maps onto *German* conditions.** The ECB's own concept (Economic Bulletin 5/2024, "The dynamics of
inflation differentials in the euro area"): a single rate is too loose for high-inflation members
and too tight for low-inflation ones; Germany's inflation, output gap and its own Bund curve
diverge from the aggregate. The `de` arm therefore measures **the sign and size of the divergence
of German conditions from the euro-area aggregate the ECB actually reacts to** — a member-state
rule, not a central-bank rule.

### Japan: **a genuinely distinct central bank.** The BoJ's framework is not a Taylor rule:
- **Yield Curve Control** (Sept 2016): the policy instrument is the **10-year JGB yield** (target
  ~0%), not only the overnight rate.
- **Inflation-Overshooting Commitment** (Sept 2016): continue expanding the base *"until the
  year-on-year rate of increase in the observed CPI (all items less fresh food) exceeds 2 percent
  and stays above the target in a stable manner."* Deliberately **tolerates overshooting**.
- **ZLB / NIRP**: −0.1% until the March-2024 exit to 0–0.1%.

**The primary source that proves the differentiation** is Hasui & Teranishi (2025, HIAS-E-149),
read via `pypdf`:

> *"We show that the Taylor-type rule **can not** replicate inflation overshooting, even though
> the zero interest rate policy continues… the augmented Taylor-type rule with a strong history
> dependence can work as a price-level targeting policy."*

Its formal rule is the **Reifschneider–Williams (2000)** shadow-rate rule:

```
i_t   = max[0, ĩ_t − φ_z · z_t]                       # the ZLB floor + the cumulative shortfall
ĩ_t   = (1 − ρ_i)·{i* + φ_π·(π_t − π̄) + φ_x·x_t} + ρ_i·ĩ_{t−1}
z_t   = z_{t−1} + (i_t − ĩ_t)                          # past ZLB "debt"
```

with **φ_z = 0.5** (Nakov 2008), **natural rate −0.5%**, **anchored inflation expectation ~1.5%**
(BoJ 2024 breakeven), **inflation persistence γ = 1.4** (Kawamoto et al. 2025) — all from the
paper's own calibration table. **The `max[0, ·]` floor and the `z_t` term are what a plain Taylor
rule cannot reproduce**, which is the structural marker the `jp` arm must carry.

## 3. The build plan

- **WS1** — registry: `de_*` and `jp_*` series (the table in §1), registered in
  `persistence.SCALAR_SERIES_FIELDS` in the same change.
- **WS2** — reaction functions in `models/policy_rules.py`:
  - `de`: `de_member_appropriateness_rule` (national divergence from the ECB stance) +
    `de_bund_spread_rule` + `de_real_rate_rule` — the trio reads GERMAN data, not the aggregate.
  - `jp`: `jp_reifschneider_williams_rule` (the shadow-rate ZLB rule above) +
    `jp_ycc_reference_rule` + `jp_overshoot_commitment_rule`.
  - config under `policy.de` / `policy.jp`; `country="de"` / `"jp"`; distinct `rule_variant`s.
- **WS3** — instruments: `ProductionUniverse(country="de")` (Bunds/Bobl/Schatz, Bund futures,
  DAX) and `(country="jp")` (JGBs, JGB futures, Nikkei/Topix); `country_routes`; the
  `snapshot_to_thesis_inputs` dispatch (`_de_thesis_inputs` / `_jp_thesis_inputs`); enable both.
- **Tests + mutation proofs + gates**, then docs (this file, README, CHANGELOG, DECISIONS D-149,
  PHASE5_DEFERRED §2.4).

## 4. Sources

- Deutsche Bundesbank, *Monetary policy framework* — the Eurosystem sets the single policy.
- ECB Economic Bulletin 5/2024, *The dynamics of inflation differentials in the euro area*.
- Hasui & Teranishi (2025), *Good Luck or Not: Bank of Japan's Monetary Policy*, HIAS-E-149.
- Reifschneider & Williams (2000); Nakov (2008) — the shadow-rate rule and φ_z = 0.5.
- Bank of Japan (2016), *New Framework for Strengthening Monetary Easing* (YCC + overshooting
  commitment); Bank of Japan (2024) — the March-2024 exit from NIRP/YCC.
