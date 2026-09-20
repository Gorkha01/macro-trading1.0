# Build Progress

**Live tracking file.** Updated in place at each milestone — never restarted.
Last updated: **2026-09-20** (after **D-073 — the §17.4 risk-axis hook**. The last
Phase 4 item is closed: **PHASE 4 IS COMPLETE.** The finding worth carrying: the
`thesis_demotion_fraction` bound shipped at **0.02 could never fire** — the
smallest reachable published size is **0.02941** — so §17.4's demotion was
**declared, consumed, and unreachable** until the bound moved to **0.03**.
**PHASE 5 IS NOT STARTED, deliberately.**)

Legend: `[x]` done · `[ ]` not started · `[~]` in progress / partially covered

---

## ⏭️ SESSION HANDOFF — read this first if you are a new session

> **A NEW SESSION SHOULD START AT `.workbuddy-ai/memory/HANDOFF.md`** — written
> 2026-09-20 at D-073's close, and the purpose-built router for a cold start:
> status, read-order, the five time-wasters, Step 0, the binding *Next*
> instruction, carry-overs and the standing obligations. This file remains the
> **live tracker** it is and is the authority on status; HANDOFF is the entry
> point that points you here.

> **STARTING PHASE 5?** There is no handoff file for it yet, and **Phase 5 is not
> started** — see the *Next* block at the end of this file for its entry conditions.
> **`docs/PHASE4_HANDOFF.md` is now HISTORY**: it was purpose-built for Phase 4,
> which **closed at D-073**, and its scope description is superseded by the Phase 4
> block below. Read it for how Phase 4 was scoped, not as a live to-do list.
>
> The D-070 handoff below the Phase-4 pointer is older still and remains accurate
> for what it describes.

**WHERE WE ARE.** Phases **0 = 8/8 ✅ · 1 = 9/9 ✅ · 2 = 85/98 (13 outstanding, ALL
Tier 5 by §22.3) · 3 = 2/2 ✅ · 4 = 4/4 ✅ — CLOSED at D-073.** Tiers **1/2/3/4 =
23/23 · 29/29 · 15/15 · 11/11 — ALL COMPLETE**; Tier 5 = 0/20 **by design**.
**The front of the runway is now Phase 5 — and it has NOT been started, by
explicit instruction.** Phase 5 begins with the 13 Tier-5 deferrals (§22.3), each
of which needs its own registry, its own reaction function and its own instruments.

**THE LAST INCREMENT WAS D-073 — the §17.4 risk-budget hook. It is CLOSED.** Do
not re-open it. Its recorded state: `_apply_risk_axis` in
`thesis_layer/builder.py`; **9 applied / 8 killed / 1 control survived —
CERTIFIES**; live check **PASSED exit 0**.

**GATES AT D-073's CLOSE — these exact numbers are the baseline you inherit.**
Any deviation is either your change or a defect; do not assume drift.

```
ruff check src tests tools scripts        ->  All checks passed
ruff format --check src tests tools scripts ->  218 files already formatted
mypy --strict src tests tools scripts     ->  no issues in 218 source files
pytest -q                                 ->  2329 passed, 1 skipped
tests/thesis_layer/test_risk_axis.py      ->  17 passed
scripts/mutation_risk_axis.py             ->  9 applied / 8 killed / 1 survived  CERTIFIES
scripts/live_risk_axis_check.py           ->  PASSED, exit 0
```

**The count is 218 = 218** — ruff-format's file count equals mypy's (D-035).
**The single skip is pre-existing**: `tests/models/test_output_gap.py:255`, a
Phase-5-gated confidence constant, not a D-073 skip. **O-84 no longer fails** —
it is a live-marked data-layer test and is excluded from the default run; it
still fails under `-m live` and has **not** been fixed.

**STEP 0 OF ANY SESSION — do this before anything else:**
1. `uv run python tools/sweep_health.py` — inherit a clean tree, or find a leftover
   mutant from an interrupted sweep. **Never run the suite while a sweep is in
   flight** (lesson 5bi): the sweep mutates `src/` per mutant, so failures are
   phantoms.
2. `grep -rn "if False:\|if True:" src/macro_engine/` — must print **nothing**.
3. Read `AGENTS.md` (the SINGLE authority), then this file, then `REFERENCE.md`.

**THE FIVE THINGS THAT WILL COST YOU THE MOST TIME IF YOU DO NOT KNOW THEM:**
1. **`uv` exclusively.** `.git` is **UNBORN** — no commits, staged only. Do not do
   git work; report it and the user re-pushes.
2. **Every `settings.yaml` leaf is a `{value, calibration_status, note}` envelope**
   with `extra="forbid"`, so keys are `*_value`-suffixed and read through
   `@property` accessors. `ApiSettings` **is** the api block — read `api.host`, not
   `settings.api.host`.
3. **A gate row is a CLAIM, not a receipt** (O-88). Re-run the gate; never carry a
   count forward. `ruff format`'s file count must equal `mypy`'s (D-035) — **218**.
4. **A mutation survivor is a claim about your TESTS until you prove otherwise.**
   First question: *"is its killer in my selection?"* Never exempt a mutant to make
   a sweep go green; add the test.
5. **Verify a guard goes RED by planting the regression.** A guard that cannot fail
   converts "untested" into "verified" — that is worse than no guard (lesson 80).

**CARRY-OVERS INTO PHASE 5** (full text in `docs/OPEN_ISSUES.md`): **O-97** (§17.4
wired at the builder, unreached by the API — the parameter is optional, so a future
caller fails open), **O-96** (`CANDIDATE` has no producer, so §17.4's literal
transition is unreachable — the axis demotes `DRAFT`), **O-94** (Q12's exposure
half is not computed anywhere), **O-92** (two
production clients default to `trust_env=True`; loopback OpenBB traffic is proxied —
it works only by luck), **O-90** (process-global snapshot cache vs `--workers N`),
**O-91** (async SSE generator awaits a synchronous build), **O-87**,
**O-86**, **O-84**. **None of these block starting Phase 5.**

---

## How to read this file — phases vs tiers (they are different axes)

**PHASES are the architecture build order.** Phase 0 foundations → Phase 1 data
layer → **Phase 2 models layer ← you are here** → Phase 3 thesis + API → Phase 4
instruments → Phases 5+ (stubs by design).

**TIERS are dependency depth WITHIN Phase 2.** They are **not** phases. All five
tiers are the work order for turning a correctly-signed stub into an
implementation. Per **§22.1** (AGENTS.md), **every** function exists as a stub
immediately; that does not mean every *body* ships in Phase 2. **§21.3's tier
table is the sole authority** on when a stub becomes IMPLEMENTED; any other phase
language in `AGENTS.md` is descriptive context.

Tier 1 = no dependencies · Tier 2 = depends on Tier 1 · Tier 3 = synthesis ·
Tier 4 = construction · Tier 5 = deferred to Phase 5+.

**Consequences worth stating once, because they are easy to get wrong:**

- **There is no phase that "has four tiers."** Tier 4 is a tier.
- **Tier 4 straddles the Phase 2/3/4 boundary.** Its 11 functions: 4 are
  instruments (Phase 4), 4 are the thesis layer (Phase 3), 3 are supporting
  construction (Phase 3).
- **Tier 4 is COMPLETE (11/11) as of D-069.** `build_us_macro_thesis` — the
  function that appears in Tier 4 *and* in the Phase 3 checklist below, so that
  overlap **is the seam** — is implemented and runs end to end on real data.
  **The blocker on Phase 3 is therefore cleared, and only Phase 3's own work
  remains** (the §7 thesis-layer sign-off and the §8 API layer, neither started).
- **The runway to Phase 3 is 0 Tier-3 functions + 0 Tier-4 functions.**
- **Phase 2's 13 unfinished items are ALL Tier 5** — by design, deferred to
  Phase 5+. They are the non-US central-bank reaction functions and the
  Phase-5-only models. **No Phase-2 work blocks Phase 3.** See the note under
  the tier table for why "85/98" must not be read as a backlog.

---

## Overall

| Surface | Done | Total | % |
|---|---|---|---|
| **Phase 0 — foundations** | 8 | 8 | **100%** |
| **Phase 1 — data layer** | 9 | 9 | **100%** |
| **Phase 2 — models layer (US scope)** | 85 | 98 | **87%** — see the Tier-5 note |
| **Phase 3 — thesis + API** | 2 | 2 | **100%** ✅ |
| **Phase 4 — instruments** | 4 | 4 | **100%** ✅ |
| **Phases 5+** | — | — | stubs only by design |

**Phase 4's four items, all closed:** (1) `compute_risk_parity_weights` §9.2 =
**D-071**; (2) `translate_thesis_to_position` §9.3 = **D-072**;
(3) `portfolio_volatility_two_asset` / `marginal_risk_contributions` §20.12C =
**D-072**; (4) **the §17.4 risk-budget hook = D-073**. The four Phase-4
*instrument* functions under Tier 4 (D-058–D-062) shipped earlier and are counted
in Tier 4, not here.

### Function tiers (Section 21.3)

| Tier | Done | Total | % | Bar |
|---|---|---|---|---|
| **Tier 1** — no dependencies | 23 | 23 | **100%** | `████████████████████` |
| **Tier 2** — depend on Tier 1 | 29 | 29 | **100%** | `████████████████████` |
| **Tier 3** — synthesis | 15 | 15 | **100%** | `████████████████████` ✅ |
| **Tier 4** — construction | 11 | 11 | **100%** | `████████████████████` ✅ |
| **Tier 5** — Phase 5+ stubs | 0 | 20 | **0%** | by design |

**Read the "85 / 98" correctly — it is not a backlog.** 85 = 23 + 29 + 15 + 11,
i.e. **every Tier 1–4 function**. The 13 outstanding are **all Tier 5**, and
Tier 5 is the specification's own deferral list: the non-US central-bank
reaction functions (the ECB's 20-country-compromise dynamic, the BoJ's
institutional deflation-scar bias, the PBoC's non-Western reaction function —
each **genuinely different logic**, not the Fed's Taylor Rule with a different
country label) plus the Phase-5-only models. §22.3 scopes Phases 0–4 to the US,
so those 13 *cannot* be earned yet. **No Phase-2 item blocks Phase 3.**

**Phase 3 is COMPLETE (D-070).** `src/macro_engine/api_layer/` holds eight
modules (3383 lines) implementing all five §8 surfaces — `/health`,
`/thesis/{country}`, `/dashboard_data`, `/query` and the SSE reasoning stream. The
substantive work was the **orchestration gap**: `build_us_macro_thesis` takes six
required arguments and §8.2's sample supplies a snapshot, so the derivation lives
in `orchestration.py` alone. **Phase 4 was then the front of the runway** — and it
is now closed (below).

**Phase 4 is COMPLETE (D-071 · D-072 · D-073).** Four items, and the last one is
the one worth reading: §17.4's *"feedback into thesis validity"* was implemented as
`_apply_risk_axis` in `thesis_layer/builder.py`, and **the bound it demotes against
shipped at a value no input could reach.** Measured, the published
`fraction_of_capital` can only take six values — `0.02941 · 0.03472 · 0.042735 ·
0.069445 · 0.125 · 0.15` — so a `0.02` bound demotes **nothing, ever**, while the
test that would have caught it **skipped silently**. The bound is now **0.03**,
inside `[0.02941, 0.15)`. **This is the ninth instance of the project's
declared-consumed-unreachable class, in a third vocabulary** (a lifecycle state
rather than a guard or a sentinel) — see **O-96** and D-073.

**Remaining `NotImplementedError` stubs in `models/`: 0.** The last one,
`simple_gdp_nowcast`, is implemented (D-034). The only other
`NotImplementedError` in the models layer is `output_gap_from_snapshot`'s
`country != "us"` scope guard (§22.3), which is deliberate and is not an
unfinished function.

---

## Quality gates — last measured run

**Measured at D-073's close (2026-09-20), clean and SEQUENTIAL.** "Sequential" is
load-bearing: a mutation sweep **mutates `src/` for each mutant's duration**, so a
suite run alongside one reports phantom failures (skill lesson **5bi**). Every row
below was executed in this increment; none is carried forward (O-88).

| Gate | Result |
|---|---|
| `uv run ruff check src tests tools scripts` | **All checks passed** (**218** files; was 196 before D-073. The **scoped** path is the project gate — a **bare** `ruff check` reports errors because ruff has no `files` key and walks `.probe/`; see **O-63**) |
| `uv run ruff format --check src tests tools scripts` | **218 files already formatted** (matches the mypy count exactly — the gate-count discipline, D-035) |
| `uv run mypy --strict src tests tools scripts` | **no issues in 218 source files** (was 196 before D-073, 196 before D-070, 182 before D-069) |
| `uv run pytest -q` | **2329 passed, 1 skipped** — **zero failures.** (Was 2043/1/**1 failed** at D-070; the failure was O-84, a `live`-marked data-layer test excluded from the default run, so the default suite is now clean rather than repaired.) The one skip is the pre-existing `tests/models/test_output_gap.py:255` Phase-5-gated confidence constant |
| `uv run pytest tests/thesis_layer/test_risk_axis.py -q` | **17 passed, 0 skipped** — D-073's own suite. **Run 1 was 14 passed / 3 failed / 1 skipped**; the failures were mine (a wrong status literal and a fixture that flipped the status *string* while keeping bp-denominated payoffs, which `KellyInputs` rejects as *"beyond a total loss"*). **The skip is what exposed the increment's finding** — see below |
| `uv run python scripts/mutation_risk_axis.py` | **9 applied / 8 killed / 1 survived — CERTIFIES** (the survivor is the M5 honesty control). **Run 1 was 8/6/2** and both survivors were **real test gaps**: `M1.2` (the axis's local bound vs the config leaf — the tests read the leaf) and `M4.1` (`<=` → `<` — no test landed a size exactly on the bound). Both got a new test rather than an exemption |
| `uv run python scripts/live_risk_axis_check.py` | **PASSED, exit 0** — reproduces the reachable size set exactly and confirms that a 0.03 bound demotes **1 of 6** measured asymmetric scenarios |
| `uv run python tools/sweep_health.py` | **OK — 38 sweeps checked, 0 failures, 0 leftovers, 0 mutant shapes** (unchanged count from D-070; read critically per lesson **5bl** and **not** a bare green) |

### ⚠️ D-073's finding — the demotion bound could never fire, and a SKIP hid it

**`thesis_demotion_fraction` shipped at `0.02`. The smallest published
`fraction_of_capital` is `0.02941`.** So §17.4's whole feedback rule — the LTCM
lesson, the one place the risk layer writes back into the thesis lifecycle — was
**declared, consumed, and structurally incapable of firing**, and it had been since
the bound was written.

**How it was found: a test that skipped instead of failing.**
`test_a_demoted_thesis_moves_to_watch_and_says_why` was written, ran, and
**skipped** — which a suite reports as a **green tick**. A skip is a silent
assertion that the precondition does not apply; the project's rule (`open_issues`
Part 5) is that a **`skipif` on a reachable state is a defect**. Here it was
reachable in principle and unreachable in practice, which is the same defect wearing
a green tick.

**Why the reachable set is a set and not an interval.** Full Kelly is the argmax of
expected log growth; for a **two-branch** distribution with a positive edge that
objective is **monotone in `f`**, so `f*` pins at the edge of the search domain and
the *position cap* produces the published number rather than the Kelly fraction.
Only asymmetric branch sets land strictly inside the domain. The six reachable
values above are the **measured** sweep; `0.02941` is the full `f*` of `0.05882`
divided by `kelly.fractional_divisor` (2.0).

**The bound now carries three constraints, and the third is the find:**
`> 0`; `< max_position_fraction` (`0.15`); **`>= the smallest reachable size`
(`0.02941`)**. `0.03` satisfies all three. Recorded in `config/settings.yaml`'s
leaf note, in `config.py`'s accessor docstring, in D-073, and — decisively — in
`scripts/live_risk_axis_check.py`, which **recomputes the reachable set** and fails
if the bound stops splitting it. A config bound whose validity depends on the
model's reachable output is only safe if something re-derives that set.

**Two guards were amended, not deleted (D-067), each with a written reason.** The
Kelly guard in `test_integrity_gates.py` was **strengthened**: it now forbids raw
primitives, **enumerates the permitted surface** (`translate_thesis_to_position` is
the one sanctioned consumer), and adds a behavioural receipt
(`test_section_25_gate_precedes_kelly_on_the_translation_path`). The
`test_builder_strictness.py` prohibition on `macro_engine.portfolio` was removed
because the §17.4 hook **requires** that import — a guard forbidding the wiring the
spec mandates is a guard against the spec.

### ⚠️ D-070's harness defect — a green gate certified a selection nobody ran

**`PYTEST_TARGETS` declared FOUR test files; `run_pytest` ran THREE.**
`check_tests_collect` validated the **declaration**, which the run never used — so
the provider mutants' tests, living in the fourth file, could never be killed and
were reported as survivors across two runs.

**A target list is a CLAIM, true only where it is CONSUMED** (lesson 5be's stronger
form). Fixed structurally: both functions splat **one** shared constant, plus a new
gate — `check_the_run_and_the_declaration_agree()` — that parses the source and
**refuses to run** if either side re-inlines a path. Run 3 then certified **42/39/3**.

**Three guards were also manufacturing a green** and were replaced: a
self-referential version check (re-pinned against `pyproject.toml`), a loopback
guard that was a tautology under the shipped config (replaced with a legal
non-loopback bind requiring `False`), and **M8.6 — a real lie the tests missed**
(the stream named three gates when one fired).

### ⚠️ D-070's live check failed three times — all three defects were in the CHECK

1. **`GET /health?deep=true` → `404 {"detail":"Not Found"}` from a route that was
   registered and correct.** `httpx.Client` defaults to **`trust_env=True`**, so it
   honoured `HTTP_PROXY`. A **forward proxy takes the absolute-URI request form**
   (RFC 7230 §5.3.2) — `GET http://host:port/path` — and uvicorn unquotes that whole
   URI into `scope["path"]`, so no route matches. **The intermittency is the trap:
   the FIRST request on a FRESH connection goes origin-form and survives; a request
   on a REUSED keep-alive connection goes absolute-URI and 404s.** Isolated by a 2×2
   (reuse × `params`) socket tap: **reuse alone flips the form.** Found only by
   **printing the request line** — a routing-shaped symptom with a transport-shaped
   cause, indistinguishable by status code. Fixed with `trust_env=False` on every
   check client, guarded by two `ast` tests in `test_strictness.py` (verified **red**
   by planting the regression, then restored).
2. **`OPTIONS /health` → `400 Disallowed CORS origin`.** The check hardcoded
   `localhost:3000`; the config allows `:8000`. **Starlette was right and the check
   was wrong.** Fixed by deriving the origin from `settings.api.cors_origins`.
3. **The stream assertion failed on a CORRECT stream** — it searched for
   `"gap = +26.0bp"` while the stream emits `"gap = +0.2600pp (+26.0bp)"`. **Lesson
   5bf applies to CHECKS, not only tests: pin the VALUE, not a rendering.**

**One of the three root causes reaches production — filed as O-92, not fixed.**
`openbb_client.py:91` and `catalysts.py:213` both default to `trust_env=True`, and
the OpenBB client's mounts against `http://127.0.0.1:6900` are
`{http://: HTTPProxy, https://: HTTPProxy}` — **every loopback request is proxied**.
The provider still returns 21/21 fields **only because this environment's proxy
transparently forwards loopback** — luck, not design. Fixing it would invalidate
the provider mutants that certify the current behaviour, so it is recorded.

---

**The rows below are unchanged from the increment that measured them.**
| `uv run mypy --strict src tests tools scripts` | **no issues in 182 source files** (was 176 before D-069, 170 before D-067, 161 before D-066, 161 before D-065, 157 before D-064, 153 before D-063). **⚠️ CORRECTION: the D-068 row claimed "no issues in 176 source files" and that claim was FALSE** — D-068's own files held **29 errors** (13 in `test_no_trade.py`, 1 in `test_no_trade_strictness.py`, 1 in `test_no_trade_live.py`, 15 in `scripts/live_no_trade_check.py`). They were found by D-069 running the full gate rather than a per-file check, and **all 29 are now fixed**. Recorded as **O-88**; the lesson is that a gate row is a *claim* and must be re-derived by running the gate, never carried forward. This is the **D-035 class** one layer up: the documented gate was weaker than the code needed |
| `uv run pytest -q -m "not live"` | **1901 passed, 1 skipped, 16 deselected, 0 failed** (was 1829/1/10 before D-069, 1787/1/8 before D-068). The +72 are D-069's **51 tests in `test_builder.py` + 21 static guards in `test_builder_strictness.py`**, and the **+6 deselected** is the new live-marked file `test_builder_live.py`. **Re-run five consecutive times at close — five identical runs.** (`tests/thesis_layer/` alone: **299 passed, 11 deselected**.) |
| `uv run pytest -m live -k coherent_economic_picture` | **1 failed** — a genuine, **pre-existing** `iorb` future-date finding. **O-84's diagnosis is here CORRECTED**: it is **not** a frozen clock compared against a stale `retrieved_at`. The error text names the comparison itself — *`observation_date 2026-09-21 is after retrieval date 2026-09-19 by 2 day(s), beyond this series' declared tolerance of 1`* — so the tolerance **is** compared against the current date, and **the provider is publishing `iorb` 2–3 days ahead of the calendar**. The declared `future_date_tolerance_days: 1` covers the documented UTC-boundary case (a 1-day overshoot); a 2–3 day overshoot is outside it **by design**, so the ERROR path is armed and firing **correctly**. Proven not-D-069 two ways: `tests/thesis_layer/` is clean (299 passed) and the data layer carries no D-069 change. **The fix is a data-layer decision** (widen the tolerance, or re-point the series, or declare `forward_looking`) — **not** a D-069 defect |
| `uv run pytest -m live tests/thesis_layer/test_no_trade_live.py` | **2 passed** — the three triggers are reachable live; a CONFLICTED no-trade survives the schema gate |
| `uv run pytest tests/thesis_layer/test_signals.py tests/test_infrastructure.py -q -m "not live"` | **passed** |
| `uv run pytest tests/models/test_auctions.py -q -m "not live"` | **27 passed** |
| `uv run pytest tests/models/test_credit_spread.py -q -m "not live"` | **30 passed** |
| `uv run pytest tests/models/test_financial_conditions.py -q -m "not live"` | **29 passed** |
| `uv run pytest tests/models/test_policy_rules.py -q -m "not live"` | **54 passed** |
| `uv run pytest tests/models/test_national_accounts.py -q -m "not live"` | **57 passed** |
| `uv run pytest tests/models/test_probability.py -q -m "not live"` | **28 passed** |
| `uv run python scripts/live_labor_check.py` | **passes end to end** — Modules 3.2, 3.4, 4.1, 8.2, 8.3, 12. **3.4 now RUNS the model** (D-043 unblocked it) and 8.3 **derives** its trend; 4.1 demonstrates its dead branch live; 12 recomputes the mandated posterior via the odds form |
| `uv run python scripts/mutation_gdp_nowcast.py` | **39 / 39 killed** |
| `uv run python scripts/mutation_auction_demand.py` | **32 / 32 killed** |
| `uv run python scripts/mutation_credit_spread.py` | **34 applied / 33 killed / 1 survivor (the control)**, exit 0 — **REBUILT by D-061**. The D-060 audit recorded this sweep as "exit 1, unexplained survivor `C1d` — a REAL missing test". Executing the gate it lacked showed **three** problems instead: `C1d` was **AMBIGUOUS** (8 occurrences; `str.replace` rewrote `CreditTrendBaseRates` while the model reads `CreditSpreadBaseRates`) and `M4a`/`M5e` were **ABSENT** because D-043 had moved the source. A mis-target plus two stale anchors, not a coverage gap — and a correctly-targeted `C1d` is killed by the test that was already there (measured: exit 1 vs exit 0). Two published keys with no mutation gained one (`M5g`, `M5h`) |
| `uv run python scripts/mutation_financial_conditions.py` | **31 / 31 killed** |
| `uv run python scripts/mutation_policy_mix.py` | **23 / 23 killed** |
| `uv run python scripts/mutation_qe_stance.py` | **27 / 27 killed** |
| `uv run python scripts/mutation_minsky.py` | **25 / 25 killed** |
| `uv run python scripts/mutation_probability.py` | **29 / 29 killed** |
| `uv run python scripts/mutation_lei_proxy.py` | **36 / 36 killed** |
| `uv run python scripts/mutation_regime.py` | **40 / 40 killed** |
| `uv run python scripts/mutation_evidence.py` | **17 / 17 killed** |
| `uv run python scripts/mutation_inflation_convergence.py` | **25 / 25 killed, 2 inert by design** — 27 mutations; C4 (dead branch) and D2b (redundant term) survive *deliberately* and are marked `[INERT BY DESIGN]` |
| `uv run python scripts/live_inflation_convergence_check.py` | **passes end to end** — all six series live incl. two §21.1 called BLOCKED; units verified; base rates recomputed against config within 2%; the corrected gate fires on 6 of 522 real months (2008-12, 2017-03, 2020-03/04/05, 2026-06) |
| `uv run python scripts/mutation_yield_curve.py` | **67 / 68 killed, 1 inert by design** |
| `uv run python scripts/live_inversion_check.py` | **passes end to end** — base rates re-measured over 592 months (0.489 inverted / 0.157 not); the hump-shaped duration finding survives a censoring control |
| `uv run python scripts/mutation_scorecard.py` | **84 / 87 killed, 3 proven-inert** — re-run by D-051 after the census fix added three mutations; `check_targets` refused the re-run on three targets made AMBIGUOUS by `ConvergenceSettings` |
| `uv run python scripts/live_scorecard_check.py` | **passes end to end** — 761 real monthly readings, all four pillars DERIVED from FRED; `CONFLICTED` 66.2% / `HIGH` 33.0% / `NO_SIGNAL` 0.8%; space share 61.7% reported alongside; sign audit clean |
| `uv run python scripts/mutation_convergence.py` | **53 / 56 killed, 3 classified** — 1 honesty control (must survive), 1 comment-only no-op, 1 proven-inert trapdoor. `check_targets` refused the first run on four targets made AMBIGUOUS by the sibling `ScorecardSettings`; `check_tests_collect` refused the second after a nonexistent test path produced a false **56/56** |
| `uv run python scripts/live_convergence_check.py` | **passes end to end** — 761 readings; cross-check against `four_pillar_scorecard` **761 agree / 0 disagree** (it failed 95/761 on first run, indicting the *scorecard*); input space re-measured at 0.6173 matching config to 4 dp; padding attack repelled on real data |
| `uv run python scripts/mutation_transmission.py` | **55 / 58 killed, 3 proven-inert, 0 defects** — 58 mutations in 13 groups. `check_targets` refused the first run on **three AMBIGUOUS targets** (all self-inflicted). The three inert entries carry **executed** proofs, re-runnable via `--probe-inert`; the composition pair was proven by enumerating **643 200** cases with **0** differences. Re-run at record-set close per the increment's brief — clean |
| `uv run python scripts/live_transmission_check.py` | **passes end to end** — the real-yield identity `DGS10 − T10YIE − DFII10` is **exact over 5 931 daily obs** (max error 0.000000), so the derived leg is a restatement, not a proxy; **it caught two already-shipped config base rates being wrong** (`gold_call_base_rate` 0.7779 → **0.7556**, `measured_breakeven_negative_share` 0.2754 → **0.2652** — no population reproduced either); post-fix base-rate drift **0.0000** (bar 0.005); cross-check against `inversion_probability_adjustment` (D-049) on a **disjoint** input (no shared series), with a one-year window-overlap guard |
| `uv run python scripts/mutation_inflation_trajectory.py` | **21 / 24 killed, 3 expected survivors, 0 defects** — 24 mutations in 10 groups, one group per specification defect. `check_targets` refused **twice**: once on a mis-transcribed error-message string, once at close-out on a target `ruff format` had reflowed from one line into three. **The sweep found a real coverage gap** (M5.2 broke the `loose + expanding` corroboration quadrant that no test drove) and the missing quadrant test was added; the sweep then went **20 → 21 killed**. `_EXPECTED_INERT` is **empty**, which is a stronger statement than a populated one: nothing is excused from having a test. Re-run at record-set close per the increment's brief — clean |
| `uv run python scripts/live_projection_check.py` | **passes end to end** — and it **caught a 7× config error before the record set was written**. Its first run re-measured the configured `beta` by the band-corner method and failed; investigating showed the method itself was wrong (it measured a *contemporaneous level spread*, a different estimand from a projected change, and the band width and beta are **not independent** because the band's score-width *is* `band_pp / beta`). Re-derived from the OLS slope of the 6-month forward change: **+0.00598, se 0.00159, t +3.76, R² 0.047, n 290**. Config corrected **0.043 → 0.006**, band **±0.15 → ±0.05pp**. Base-state failure **eliminated**: label mix now `reaccelerating` 40.5% / `stable` 31.4% / `decelerating` 28.0% over 296 real months (the specification's own threshold gave `stable` 79.1%). Cross-check against `cross_asset_transmission` (D-052) on the shared labor leg, built from the start |
| `uv run python scripts/mutation_drawdown.py` | **46 / 47 killed, 1 survivor (the control), 0 defects** — 47 mutations in 13 groups, `_EXPECTED_INERT` **empty**. `check_targets` refused **three** runs, all on targets `ruff format` had reflowed or that I mis-transcribed (one was INERT BY CONSTRUCTION because my own constant said `risk_reduction_pct` where the source says `threshold_pct`) — the concrete warrant for honour 1. The first run was **42 / 47** with **four genuine coverage gaps**: `M5.1`/`M5.2` (a `Literal` losing a member — *a `Literal` is not runtime-enforced*, so a value assertion cannot see it; the fix is `typing.get_args()`), `M5.3` (the stop gate at `0.99`, which only differs on a reduction in `[0.99, 1.0)`), `CX3` (the tier **ceiling** — the floor was tested, the ceiling was not). Each closed with a new test; the sweep then went **42 → 46 killed**. The harness itself had to be fixed: `build_mutations()` reconstructed every `Mutation` from a 4-tuple and dropped `expect_killed`, so the correctly-surviving control `M9.1` was reported as an unexplained defect. Re-run at record-set close per the increment's brief — clean, and `LEFTOVER: NONE` |
| `uv run python scripts/mutation_rebalancing.py` | **64 / 64 applied, 61 killed, 3 survivors, 0 defects** — 64 mutations in 12 groups. `check_targets` refused the **first** run on **three AMBIGUOUS anchors** (`"outcome": outcome,`, `warnings: list[str] = [` and `is_heuristic_not_calibrated=True,` each appear **twice** in `risk_budget.py`, once per function) — re-anchored on a preceding line unique to the rebalancing block, which is exactly the job D-048 built the gate for. The first run was **64 applied / 52 killed / 12 survivors**, and **only six were real gaps**: two were **INERT BY CONSTRUCTION** (my mutants added dead code — an `if ...: pass` and an unused local) and **one was INERT BY ANCHORING** (`M10.1` inserted a `model_config` *before* the docstring, so the real config nine lines below shadowed it and the code under test **never changed** — proved by probing the attribute directly). The six genuine gaps (`M1.2`, `M3.3`, `M3.4`, `M4.1`, `M5.4`, `M10.4`) are all closed with new tests; **`M4.1` was the headline** — the original boundary fixture (`0.25 + 0.10 - 0.25 == 0.09999999999999998`) was *not on the boundary* and could not distinguish `>` from `>=`. **The first increment in the repo to populate `_EXPECTED_INERT` with proven entries**, and the two proofs are deliberately **different in strength**: `M4.6` **unconditional** (the `abs(signed) > threshold > 0` guard removes `signed == 0` from the direction test's domain entirely) vs `CX3` **conditional on the shipped config** (the `float()` cast is the identity on a `builtins.float` leaf today, and would become load-bearing if the leaf ever became a `str` or `Decimal`). The harness now prints the strength beside each proof and **returns exit 2** rather than certifying an excused mutation with no proof. Re-run at record-set close per the increment's brief — clean |
| `uv run python scripts/live_rebalancing_check.py` | **passes end to end** — five **real tradeable ETFs** (`SPY TLT IEF GLD UUP`) via `yfinance`/`etf.historical`, a real covariance over **504 sessions**, and Euler risk contributions `wᵢ(Cov w)ᵢ/σ_p`. `sigma_p = **8.33%**` annualized. **SPY carries 35.0% of notional and 56.14% of RISK** — the finding the module exists to make. `UUP` carries **−1.48%** (a genuine diversifier). Trip rate **9.7%** at the configured 10%, so the base state is not modal by construction. The first draft decomposed risk across FRED-macro legs and returned a **degenerate** estimate (a VIX leg at **136%** annualized vol, a **negative** equity leg) — not a code bug, but what happens when a price index and a volatility level share a covariance matrix; the honest basis is tradeable instruments on a common return convention. **The cross-check against `evaluate_drawdown_rules` is a REAL CALL, not a re-implementation** — so D-054's O-43 asymmetry is not repeated. It found three things no unit fixture could: the contract **cannot budget a hedge** (`RiskBudgetTarget` bounds the share to `[0,1]`, so pydantic rejects UUP's real contribution — recorded as **O-46**); a partitioned share vector **must be renormalised** (`total_current_contribution` came back **1.014778**, and the function **caught it with its own sum-to-one warning** — recorded as **O-47**); and the response is **V-shaped, not monotone**, which corrected the check's own invariant (the draft asserted `>` monotonicity and failed with `a larger displacement (0.50%) reported a SMALLER drift` — moving an instrument *toward* its target reduces the drift, so the sweep must go outward from the target on both sides) |
| `uv run python scripts/mutation_voltarget.py` | **23 / 23 applied, 21 killed, 2 survivors, 0 defects** — 23 mutations in 9 groups. `check_targets`: **0 problems** on the first run. The first run was **23 applied / 16 killed / 7 survivors**, and **only five were real gaps**: `M3.2` (the clip restricted to `raw_scale >= 1.0` — *every clipping test scaled up and every de-risking test sat below the ceiling*, so relocating the one-sided clip to the up-side passed the whole file: **the D-056 defect in mutation form**), `M2.3` (ceiling hardcoded to 3.0 — no test ever supplied a limits object whose ceiling **differed**), `M6.2` (`round(..., 6)` dropped — every assertion used `pytest.approx`, which cannot see precision), `CX3` (the unit guard widened to `<= 10.0` — the existing test used `15.0`, which any bound from 1.0 to 14.0 rejects, so a loosened guard still *looked alive*; the fix is the band `(1.0, 10.0)`), and `M7.1` — **a HARNESS defect, not a test defect**: the mutant inserted a *second* `model_config` above the class docstring and the real one below shadowed it, so the code under test never changed (INERT BY CONSTRUCTION). Each real gap closed with a new test; `M7.1` re-anchored; the sweep then went **16 → 21 killed**. **`M6.1` ships as the first entry in `_INERT_PROOFS` with a CONDITIONAL proof** — it replaces `compute_confidence(...)` with the literal `0.5`, which **is** the computed value (`0.7 − 0.2`) on the shipped config, so the two programs agree on every reachable input: **INERT BY ANCHORING (lesson 54), not by unreachability**. The proof expires when Phase 5+ recalibrates either constant. **The control `M8.1` survived as required.** Re-run at record-set close per the increment's brief — identical result (**23/21/2**), and `ruff format` touched nothing in between, which is why D-051's third-harness-defect scenario did not recur |
| `uv run python scripts/live_voltarget_check.py` | **passes end to end** — the same five **real tradeable ETFs** (`SPY TLT IEF GLD UUP`) over **1 938 inner-joined sessions** (2019-01-02 .. 2026-09-17), covariance over the last **504**. Annualized portfolio vol **8.33%** vs a **10.00%** target → scale **1.2010×**, *lever up*, `clipped=False`. Over **444** rolling 60-day observations: vol range **4.67% – 13.99%**, scale range **0.715× – 2.142×**, **the leverage clip fired 0 of 444 sessions (0.0%)** and the reflexivity warning **58 of 444 (13.1%)** — so D-056's defect 3 (**the only enforced limit cannot bind in the regime the function exists for**) is **re-derived from live data, not cited from the probe**. The check prints both rates rather than asserting the defect, so a config change that makes the clip reachable is *visible*. **TWO cross-checks, both real calls**: against `evaluate_drawdown_rules` (the shared *invariant* — monotone in stress, flat at zero stress) and against `check_rebalancing_drift` (the shared *disclosure shape* — which is what makes defect 4 legible, because the drift check publishes signed per-instrument magnitudes while the vol scaler publishes **one flag that is False on the entire de-risking side**). It also reproduced the **same** contract limitation D-055's check found on the same legs: `UUP` carries a **−0.12%** risk share and `RiskBudgetTarget` bounds the target to `[0, 1]`, so a diversifier has no legal target — partitioned, renormalised, and **named**, never clamped |
| `uv run python scripts/live_drawdown_check.py` | **passes end to end** — 2 513 real daily SP500 observations walked with a running high-water mark (2016-09-19 .. 2026-09-17; FRED serves a rolling ~10-year window, so the check asks for **whatever the provider returns** and asserts only that the window is still ≥20% deep). Outcome mix `no_action` 2 084 (82.9%) / `reduce_risk` 355 (14.1%) / `stop_trading` 74 (2.9%); every rung fires **at or beyond** its threshold; worst drawdown **33.92%** on 2020-03-23. Section 3 is **path-independence**, not time-monotonicity: 2 154 distinct drawdowns, **0** disagreements. Cross-check against `volatility_target_scaling` (§20.13) on three structural invariants — no path, no shared input, so it compares the shared **shape**. **Two of its own bugs were found and fixed before it passed**: (a) a hardcoded 2007–2010 episode FRED does not serve, and (b) a monotonicity assertion over consecutive path observations that reported **52 violations, every one a recovery** — a recovery *is* a shallower drawdown, so the ladder correctly prescribes less |
| `uv run python scripts/mutation_warnings.py` | **9 applied / 7 killed / 2 survivors (1 unreachable guard, 1 control), exit 0** — 9 mutations in 9 groups, **one file** (`thesis_layer/warnings.py`). Carries all three gates — `check_targets`, `check_anchor_landings`, `check_tests_collect` — with **`refuse_on_noop` on**. The groups pin: the raiser count survives de-duplication (M1), the raiser map keeps a list not a scalar (M2), first-seen order is preserved (M3), the raiser census (M4), `all_texts` orders `warnings` before `unattributed` (M5), a warning-free model stays out of the numerator (M6), `shared_warnings` filters (M7), the summary is frozen (M8). **Two findings are worth more than the kill count.** (a) **M5.1 SURVIVED the whole selection on the first run and was not inert** — `test_unattributed_order_is_preserved` passes only unattributed warnings, so the two halves of `all_texts` can never interleave and a reversal was invisible. Closed by **adding** `test_all_texts_puts_the_models_warnings_first` rather than by exempting the mutant (lesson 65's flag). (b) **M2 and M4 must be killed by a different gate than the one the sweep runs**: M2's mutant dies with an `AttributeError` raised *from inside the function under test*, and M4 deletes a guard that **no input can trip** (every warning belongs to exactly one model). That is why `tests/thesis_layer/test_warnings_strictness.py` exists — it kills M2 statically and pins M4's presence, and M4 is exempted by an **argument** (`inert_proof` states the construction), not by a label |
| `uv run python scripts/mutation_no_trade.py` | **14 applied / 13 killed / 1 survivor (the control), exit 0** — 14 mutations in 14 groups, **one file** (`thesis_layer/no_trade.py`). Carries all three gates — `check_targets`, `check_anchor_landings`, `check_tests_collect` — with **`refuse_on_noop` on**. The groups pin: the trigger survives into the warning line (M1), the vocabulary stays a closed `Literal` (M2, **STATIC**), every trigger has a label (M3), an empty reason is refused (M4), whitespace-only is refused too (M5), Q6 requires the gap (M6), `elapsed` is an absolute distance (M7), `elapsed` is not fabricated where it does not apply (M8), the no-trade idea writes `""` not `"n/a"` (M9), the reserved-field guard holds (M10), the trigger line is published (M11), the decision is frozen (M12), the status is WATCH (M13), and the control (M14). **This sweep had NO gaps to close on its first run** — unlike D-067's, whose `M5.1` survived and forced a new test. The reason is structural and worth recording: **every defect here is a PRESENCE defect** (a field, a guard, a label), and a presence defect has a test that names it directly; D-067's survivor was an **INTERACTION** defect (`all_texts`' two halves could never interleave), which no single-field test could see. **`check_targets` refused the first draft of the control** (`old == new`, INERT BY CONSTRUCTION) — the gate catching the harness author's own mistake, which is D-048 working. **M2's kill is doubly attested**: the sweep reports `test_every_trigger_has_a_label` raising on the `str`-widened vocabulary, and the static guard `test_the_trigger_vocabulary_is_closed` was verified to kill it **independently** (the strictness file alone, against the mutant, fails two tests) — a type is not observable through behaviour |
| `uv run python scripts/live_no_trade_check.py` | **passes end to end** — a live snapshot plus the **5 real models** that feed §16.2's Q6/Q7/Q8. Measured on 2026-09-19 (`as_of=2026-09-19`, 4 quality flags, growth=+0.83, labor=+3.5): **Q6 does NOT fire** (`|raw_gap=+0.77| > dispersion=0.42`), **Q7 does NOT fire** (3 agreeing / 0 disagreeing / 0 unreadable, directions `['confirms','confirms','confirms']`), **Q8 does NOT fire** (3 conditions identified). **The no-trade path is not the common case** — recorded so a future reader does not assume it is. The rendered thesis passes the live schema (`instrument='NONE'`, `status=WATCH`, `stop=''`, warning `No trade [caller] (...)`) and the **sentinel danger is confirmed live**: `TradeIdea(stop_or_invalidation='n/a')` returns **`is_trade is True`**, i.e. the schema accepts `"n/a"` as a stated falsifier, which is exactly why the shipped no-trade writes `''` |
| `uv run python scripts/mutation_builder.py` | **18 applied / 18, 17 killed / 1 survivor (the control), exit 0** — 18 mutations in 18 groups, the **seam function** (`thesis_layer/builder.py`). Carries all three gates — `check_targets`, `check_anchor_landings`, `check_tests_collect` — with **`refuse_on_noop` on** and a SIGTERM/SIGINT `_restore_inflight` handler. **THE FIRST RUN REFUSED TO CERTIFY — SIX survivors, and every one was a REAL test gap, not an inert mutant:** `M8` — **the defect this increment had just fixed** (`_render` dropping every model warning and §22.5's contamination disclosure on a stand-down) — **survived**, because its regression test had been written **only in `test_builder_live.py`**, which `-m "not live"` deselects. `M9`/`M10`/`M11`/`M12`/`M13` survived on assertions that were too weak: a **disjunction** any sentinel satisfies; a direction pinned only as a *relationship* rather than against a disagreeing fixture; scenarios checked only on the live path. Each closed with a **new offline test** (6 added; the file went 40 → **51** tests), which is the D-067 lesson applied: **fix the test, not the mutant.** **THE SECOND RUN THEN KILLED THE HONESTY CONTROL** (`M18`) — `test_the_sample_s_gap_only_direction_rule_survives_only_as_a_fallback` asserted the fallback's **literal source text**, so a semantically equivalent rewrite tripped it: the test was asserting **spelling, not meaning**. Rewritten to pin **order and structure via `ast.parse`**, leaving behaviour to the test that drives the function. **Two mutants were also mis-aimed and had to be retargeted**: `M12`'s anchor sat in `_render` rather than `_direction_for`, and `M13`'s replacement was a behavioural no-op — both caught by `check_anchor_landings`/inspection. **Lessons 5be and 5bf.** Re-run at record-set close per the increment's brief — identical result (**18/17/1**), `EXIT=0` |
| `uv run python scripts/live_builder_check.py` | **passes end to end** on real data — the seam function builds a thesis from a live snapshot and **5 real models**. Measured 2026-09-19: `status=WATCH`, `gates=['conflicted_signals']`, `gap=-0.5300 dispersion=0.4200`, `scenarios=0`, `families=0`, **`warnings=13`**, **`contaminated=1 proxy=1`**, `MacroThesis.model_validate` round-trip **valid**, `thesis_id` stable, and the three stand-down invariants hold (`instrument == 'NONE'`, **falsifier is empty**, no scenario distribution). **THIS CHECK FOUND THE INCREMENT'S REAL DEFECT.** An earlier run printed `contaminated=0 proxy=0` on a path where the contaminated branch was *definitely* taken, and `warnings=1` (the trigger line alone) — exposing that `_render` **collected no warnings at all**. The temptation was to read `0/0` as "nothing to report"; the fix (render first, then **append** the model warnings behind the trigger line, because `render_no_trade_thesis` *owns* `warnings` and refuses to be handed it) moved the measurement to **13 warnings, 1/1**. **No unit fixture could have found this**: every offline test asserted the trigger line was *present*, and it was — the defect was that it was **alone** |
| `uv run python tools/sweep_health.py` | **OK — 37 sweeps checked, 0 failures, 0 leftovers** (was 36 before D-069, 35 before D-068, 34 before D-067, 33 before D-066, 32 before D-065, 31 before D-064, 30 before D-063). It loads every sweep, runs each one's `check_targets` / `check_anchor_landings` where it has them, scans for a leftover mutation, and exits 1 on any failure. It reports the **14 sweeps that still carry no gate at all** (O-29) rather than failing on them. **D-067 found the scan is SCOPED, not blind (O-83).** The leftover check is **per-sweep**: it only looks for mutations that *the sweep being checked* declares, so a mutation left applied in a file **shared with a different increment** is invisible. Measured once: D-064's `M6.3` mutant (`if False:` in `config.py`) was **still on disk** while this tool reported **0 leftovers**. **At D-069's close the scan reports 0 leftovers AND the manual whole-tree probe agrees** — `grep -rn "if False:\|if True:" src/macro_engine/` prints **nothing** (exit 1), which is the mandatory Step-0 check O-83 prescribes until the tool's remedy is implemented |
| `uv run python scripts/mutation_kelly.py` | **25 / 25 applied, 21 killed, 4 survivors, 0 defects** — 25 mutations in 10 groups, one group per specification defect. `check_targets`: **0 problems** on the final run — after refusing **twice** earlier, both times on *my* mis-transcription: `M2.3`'s bare `if at_search_edge:` appears **twice** in the module, and `M3.2`'s anchor was written on the **wrong side of its own swap**. The first run was **25 applied / 21 killed / 4 survivors** with **three genuine coverage gaps** — `M1.2` (the context-string claim about the deleted placeholder was untested), `CX1` (`search_points` was never read from config; the fixture must move the leaf to **777**, because **1001's grid step is exactly `1e-3` and would not discriminate**), `CX2` (the `points < 2` floor was untested) — each closed with a new test, and `CX` re-ran **3 / 3 killed**. The three remaining survivors carry **executed** proofs and are all genuinely proven: `M5.4` **INERT BY EQUIVALENCE** (`min(requested, cap)` vs the guarded form are the same function written two ways), `M3.3` and `M7.1` **INERT BY UNREACHABILITY** (the argmax initialiser is dead because the grid's first candidate is always `f = 0` with growth exactly `0.0`; and the two zero-guards are equivalent because a cap of exactly `0.0` is a **`ValidationError`**, so the state the module's docstring calls `clipped_by_position_limit` *with a zero result* is unreachable — **the proof corrects the prose**). `M9.1` is the **honesty control** and survived as required. **The harness had to be fixed twice while this ran**: without `-x` the selection is ~40 minutes rather than ~95 s, and a `SIGTERM` on the harness **bypassed the `finally` restore**, leaving `M5.2` then `M9.1` applied in `src/` — D-049's failure mode recurring. Both were repaired by hand; the harness now passes `-x` unconditionally and installs a **SIGTERM/SIGINT handler** that restores the in-flight mutation. Re-run at record-set close per the increment's brief — identical result (**25/21/4**), `EXIT=0` |
| `uv run python scripts/live_kelly_check.py` | **passes end to end** — **offline by design**, because Kelly's input is a caller-supplied *distribution*, not a series: there is no live pull that could falsify it, so the honest live check is a cross-check against an independent oracle. Section 1 runs the **shipped grid** against the **binary closed form** `f* = (p·b − q·a)/(a·b)` over **80** `(p, b, a)` combinations — worst absolute error **3.33e-16**, i.e. the grid and the analytic optimum are the same number to machine precision. Section 2 **refutes the deleted placeholder** on the live config (it returns 200× the reference thesis's real answer, the direction of the D-057 defect). Section 3 reads the mandatory **fractional divisor** out of the shipped YAML, not a literal. Section 4 reproduces the **P5b search-edge collapse** on real inputs: three genuinely edge-pinned theses (`(0.70, 2.00, 0.25)`, `(0.90, 1.00, 0.10)`, `(0.80, 1.00, 0.25)`) publish **`distinct REQUESTS: 1 of 3`** while `distinct GROWTHS: 3 of 3` — the collapse is a **disclosure** the module makes, not a bug it hides. Print `LIVE CHECK PASSED` |
| `uv run python scripts/mutation_instrument_selection.py` | **31 / 31 applied, 27 killed, 4 survivors, 0 defects** — 31 mutations in 7 groups across **three** files; the first sweep in this directory to cover `thesis_layer/schemas.py`. `check_targets`: **0 problems** (after refusing **once**, correctly, on a `CX4` anchor transcribed from memory — D-048's gate doing its job). **Six mutations survived the first run and every one was a missing or under-specified TEST**: `M2.1` (the fixture could not tell the ordering guard from the gap guard, because `("10y","2y")` fails both — fixed by asserting the **message**); `M8.5` (the docstring's example was **false** — `"US HY credit index"` does not contain the *phrase* `"equity index"`, so the ordering could not be observed — replaced with `"commodity index futures"`, which contains BOTH `"index futures"` and `"commodity"`); `M8.3` (`permits`'s fast path is rescued by its delegate, so it is **inert by redundancy** — `M8.4`, which mutates the delegate, IS killed); `CX1`/`CX2` (the hardcoded `"2y"`/`"10y"` **equalled** the config values, so no comparison could falsify them — fixed by **moving the config leaf** to `3y`/`7y`); `M6.4` (**inert by invariant** — the category-agreement guard makes `observed_category == category` true on every returned result). Final survivors: `M3.3`, `M6.4`, `M6.5`, `M8.3` — all with **executed** proofs — plus the **honesty control** `M9.1`. **The pattern across all six: a mutation survived because the test asserted an outcome BOTH programs produce, not because the mutation was harmless** |
| `uv run python scripts/live_instrument_selection.py` | **passes end to end** — **offline by design**, because this function's inputs are *labels* rather than series, so no pull could falsify it. The honest cross-check is against **the two authorities the function claims to obey**: (1) Section 22.12's real `ProductionUniverse` — all **8** executable `(thesis_type, direction)` pairs are emitted and each name is passed to the shipped matcher and must land in its declared category; (2) the live config's routing table — the default curve instrument's legs are asserted to be the config's own, re-deriving the moved-leaf fact the unit test pins. Sections 2–3 re-derive **the specification's own curve instrument** (probe P1) and confirm **both sentinels** carry `compute_confidence` = **0.5** (computed, non-zero — where §22.3.1 hardcoded `0.0`). Prints `LIVE CHECK PASSED` |

| `uv run python scripts/mutation_curve_trade.py` | **31 / 31 applied, 26 killed, 5 survivors, 0 defects** — 31 mutations in 9 groups across **two** files (`models/yield_curve.py`, `config.py`). **The first run reported 31 / 31 killed, and it was FALSE**: almost every "kill" named the same test, because that test failed on **unmutated** source — it asserted `implausible for '2y'` against a validator message naming the *long* leg. The **honesty control was killed too**, which cannot happen for a semantically identical program, and that is what exposed it (D-051's trap, new trigger). After the baseline was repaired: **two real test gaps closed** (`M6.3` — the direction test passed `is_steepener` explicitly in both states, so the default was untested; `M4.5` — every band-failure fixture used a bad *short* duration), **one wrong mutation fixed** (`M6.2`'s anchor replaced only the first of four concatenated string lines, so the asserted phrase survived), and **three genuinely inert** (`M5.1` — the tautology itself; `M3.2`/`M8.3` — unreachability, with the executed 1377-case proof and its **10× margin**). One anchor now **slices its target from the source file at import time**, so it cannot drift (the `CX4` fix, generalised) |
| `uv run python scripts/live_curve_trade.py` | **passes end to end** — **offline by design**, because the inputs are *durations and tenors* rather than series, so no pull could falsify it. The cross-check is against **`bond_math`**, a different code path: the emitted notional is compared to the **dollar-duration-matched** notional and agrees to **0.0004** once the exact relation `N_l(dw) = N_l(dollardur) · P_l/P_s` is accounted for. That relation IS the finding: §15.1b claims duration-weighting "cancels level (PC1) exposure", and it does so only when the legs trade at the **same price** — a 1.23% discrepancy for cash bonds (**O-57**). Also sweeps the band over **32 real Treasury duration pairs** (8 tenors × 4 coupons, all inside), demonstrates the decimal/percent slip is **caught** and the Macaulay-for-Modified 2.10% error **cannot be**, and closes the **D-058/D-059 seam** (`select_instrument` emits `'Duration-weighted 2y/10y UST steepener'`, the universe admits it as `rates`) |
| `uv run python scripts/mutation_curve_trade.py` (close-out re-run) | **31 / 31 applied, 26 killed, 5 survivors** — re-run **after** `ruff format` touched both new files, because a formatted anchor is how a mutation silently stops matching (D-058's `CX4`). `check_targets`: **0 problems** both times |
| `uv run python scripts/mutation_breakeven_trade.py` | **26 / 26 applied, 23 killed, 3 survivors, 0 defects** (1 name-not-value proven **byte-identical** by execution, 1 unreachability under **O-56**'s scale caveat, 1 control). First run left **two unproven survivors** and the harness **refused to certify** (exit 2): `M6.1` was a real **test gap** (the mutant *adds* a warning the shipped code never emits -- D-038's "absence half"), and `M2.1` was **name-not-value**. A third exemption (`M1.3`) was **retired** because the new absence test now kills it. |
| `uv run python scripts/live_breakeven_trade.py` | **passes end to end** — **offline by design** (the inputs are durations and prices from the shipped pricer, no series). The check **fails against the shipped rule on purpose**: it asserts the exact closed form `shipped/exact = P_nom/P_tips`, measured through **`bond_math`**, rather than an equality the arithmetic does not support. The correction over **48 real configurations** is **−56.4% .. +98.7%** and **flips sign at the TIPS leg's par price** (**O-59**) — which is why it cannot be hedged with a constant adjustment. Also refutes §15.1b's "the TIPS leg is always longer" (the nominal is longer in **19 of 48** real pairs) and closes the **D-058/D-060 seam** — a **two-keyword** round-trip (`select_instrument` emits `'Duration-matched TIPS long / nominal short (breakeven trade)'` for `INFLATION_EXPECTATIONS_GAP`; the universe admits it as `rates`). |

| `uv run python scripts/mutation_cross_market_rv.py` | **41 applied / 40 killed / 1 survivor (the control), exit 0** — 41 mutations in 9 groups across two files. **The first run was 41/38/3 and the harness REFUSED TO CERTIFY** because two survivors carried no proof. `M5.5` (the long leg publishing the short market's label) was a **real coverage gap** — the key-set test cannot see it and the interpretation test reads a different string — closed with two tests. `M8.1` (`confidence=0.5`) **was not a gap at all**: its anchor occurs **first in `curve_slope`**, so the mutant rewrote a neighbouring function whose tests are not in the selection and the sweep reported a survivor about code nobody had mutated. An audit of all 41 anchors found **three** mis-targets; `_slice_source` gained an `after=` scope parameter and the sweep gained **`check_anchor_landings`**. Re-run at close: identical. Both sibling sweeps re-run and reproduce their original counts exactly (`curve_trade` **31/26/5**, `breakeven` **26/23/3**), which is what proves adding a third constructor to the file did not break them |
| `uv run python scripts/live_cross_market_rv.py` | **passes end to end** — **pulled, not offline**: 8 real US cross-market pairs on daily changes, correlation measured normal and in **two** independent stress states (S&P worst decile, n=248; VIX ≥ 90th pct, n=928). **The specification's default is refuted on real data through the shipped function**: `degradation` is negative for **8 of 8** pairs, because the configured stressed correlation 0.9 exceeds the normal correlation of every one (max 0.820). The measured `|degradation|` is **two-signed** (3 of 8 S&P tail, 4 of 8 VIX tail) — **O-59's shape in a third constructor**. Cross-check against `construct_duration_weighted_curve_trade` is a **REAL CALL**, and it caught a degenerate fixture of my own: the first draft priced both legs at par, so `shipped/exact` was 1.000000 and proved nothing. Off-par legs give **95.2700 / 111.9700**, `shipped/exact = 1.175291 = P_b/P_a` exactly, under-hedge **+17.53%**. **It also corrected a config note in the same increment that wrote it** — the `max_abs_hedge_degradation` note claimed "about 3x headroom" from the S&P tail alone; the VIX tail makes it **1.56x** |
| `uv run python tools/sweep_health.py` | **OK — 30 sweeps checked, 0 failures, 0 leftovers** (new in D-062, **O-62**). It loads every sweep, runs each one's `check_targets` / `check_anchor_landings` where it has them, scans for a leftover mutation, and exits 1 on any failure. It reports the **14 sweeps that still carry no gate at all** (O-29) rather than failing on them. **It earned its place immediately:** it found `MX3d` STILL APPLIED in `yield_curve.py`, left by an interrupted legacy sweep — **O-61's incident recurring**, caught because the tool exists. It also produced a false positive on its first run (`new` was the empty string for a deletion mutation, so `new in text` matched 27 133 times); the fix reports deletion mutations as *unverifiable* rather than as leftovers |
| `uv run python scripts/mutation_drawdown.py` | **47 applied / 46 killed / 1 survivor (the control), exit 0** — **REPAIRED by D-061/D-062 (O-62)**. Four anchors were AMBIGUOUS in `risk_budget.py` and the sweep had been **REFUSING TO RUN (exit 2)** since D-055 added a second function to the file. Each was extended past its shared prefix — `"outcome": outcome,` through the drawdown-specific key above it, `warnings: list[str] = [` through the conviction-override warning, `country="us",` through the model name, and `depends_on_unobservable=False,` through the drawdown-specific comment block inside `_HEURISTIC`. It now reproduces D-054's original **46/47** exactly |

| `uv run python scripts/mutation_scenario_distribution.py` | **23 applied / 22 killed / 1 survivor (the control), exit 0** — 23 mutations in 8 groups across **five** files (`thesis_layer/scenarios.py`, `models/probability.py`, `config.py`, `portfolio/risk_budget.py`, `thesis_layer/schemas.py`). **The first run of the harness was REFUSED by `check_anchor_landings` on four false mis-targets** — `_DISTRIBUTABLE` and `_CONVERTIBLE_GAP_UNITS` (module-level constants, legitimately owned) and `KellyPayoffUnit`, which the checker reported as landing in `volatility_target_scaling` **150 lines away**. Root cause: the checker pattern-matched `line.startswith(("def ", "class "))`, which is **true of a prose comment**. Fixed by resolving the owner through **`ast.parse`** with `end_lineno` bounding each symbol. The **honesty control was a no-op on its first draft** (`old == new`, so it was never APPLIED and could be neither killed nor survived) and the harness correctly refused to certify; replaced with a real rewrite that re-wraps the same three literals into a **byte-identical** value. The repaired control then **killed a stale test** — `test_the_distribution_is_consumable_by_the_kelly_contract` asserted `literal_error` while omitting `limits`, which **could not pass unless `payoff_unit` was optional**: independent proof the default was load-bearing |
| `uv run python scripts/live_scenario_check.py` | **passes end to end** — **pulled, not offline**: 3 real upstream rule models (`taylor_rule`, `balanced_approach_rule`, `first_difference_rule`) over live FRED series → `canonical_policy_gap` → the shipped `build_scenario_distribution`. Real values at close: core PCE **+2.1676%**, output gap **−0.2497%**, fed funds **3.6300%**, gap **−1.00%**, dispersion **0.67**, `is_meaningful=True`, direction `model_below_market`. **It found a defect no fixture carried**: the distribution is **direction-blind** — a **+1.0%** and a **−1.0%** gap produce **byte-identical payoffs and probabilities**, and it was hit only because the live gap is negative while every unit fixture used `+1.0`. Recorded as **O-71** |
| `uv run python scripts/mutation_catalyst_calendar.py` | **10 applied / 8 killed / 2 survivors (1 control, 1 inert), exit 0** — 10 mutations in 8 groups across **two** files (`thesis_layer/catalysts.py`, `config.py`). **The sweep REFUSED TO CERTIFY on its first full run**, which was the right outcome twice over: the two survivors it named (`M1.3` horizon, `M4.1` flat-text parse) were **not** implementation defects but **test gaps**, and chasing them found a **real implementation defect** (the horizon bounded the *request* but not the *result*, so a 1-day horizon still returned a 60-day event) and a **fixture defect** (the synthetic FOMC note carried no year, so it could not reproduce the phantom the live page produces). After both were fixed the mutants are killed. It also **caught its own anchors moving** when the horizon fix rewrote them — `check_targets` refused rather than mutating a stale site (D-048). **`refuse_on_noop` is on**: an unapplied mutation is a **refusal**, not a note, which is D-064's lesson 93 implemented rather than remembered |
| `uv run python scripts/live_catalyst_calendar_check.py` | **passes end to end** — **pulled, not offline**, and it confirms every source defect the increment was written around on **live** data: FRED and the Fed both answer over **httpx/HTTP-1.1** (2266 and 167 489 chars); the three configured release ids **still name** Consumer Price Index / Employment Situation / Personal Income and Outlays; the calendar returns **4 dated catalysts** (PCE 2026-09-30, NFP 2026-10-02, CPI 2026-10-14, FOMC 2026-10-28); **FRED `rid=101` covers 41 of 41 calendar days (100%)**, so a reader trusting it as "the next FOMC" reports *today, every day*; the **flat-text parse of the Fed page invents 2 phantom meetings** (55 hits vs 53 structured) from the page's trailing 2028 note; and a 1-day horizon returns **0** entries, proving the bound is applied locally |
| `uv run python scripts/mutation_confirmation_signals.py` | **9 applied / 8 killed / 1 survivor (the control), exit 0** — 9 mutations in 8 groups across **two** files (`thesis_layer/signals.py`, `config.py`). Carries all three gates — `check_targets`, `check_anchor_landings`, `check_tests_collect` — with **`refuse_on_noop` on**, and a real honesty control (group **M8** re-wraps the same three-way branch across lines, byte-identical behaviour). **The first draft of M4.1/M4.2 was refused by `check_targets` as AMBIGUOUS**: the two `source_family=_family_of(result),` anchors are byte-identical apart from indentation, so each anchor is a substring of the other — fixed by widening each to span its own `direction=` line, which is D-048 working as intended rather than a false finding. The groups pin each measured defect: an unreadable dict reads `neutral` not `contradicts` (M1), a zero reads `neutral` (M2), labels are derived from the model and not hardcoded (M3), `source_family` is carried through on both sides (M4), a zero gap yields no `confirms` (M5), a `bool` is excluded before the numeric test (M6), and the warning marker survives (M7) |
| `uv run python scripts/live_confirmation_signals_check.py` | **passes end to end** — **pulled, not offline**: `build_snapshot(country="us")` + `output_gap_from_snapshot` produce the gap leg, and the three real Q1 models are read through the shipped function. Five checks: the three models exist, are callable, and report their own names; the live growth leg is **readable and plausible** (`|gap| <= 15%`); the **label disagreement is real** (the spec's `"inflation_convergence"` is not the model that is passed); a **dict-valued** real model reads `neutral`, not `contradicts`; and the census totals the list. **It found a genuine defect in its own first draft** and the fix is the increment's clearest lesson: the first version hand-rolled the growth leg with `.iloc[-1]` on `GDPC1` and `GDPPOT`, returning an output gap of **−17.57%**, because `GDPPOT` is a **CBO projection series** whose last observation is **2036-10-01**. Routed through `output_gap_from_snapshot` (O-7 horizon filter + D-009 same-quarter pairing) the same date gives **+0.83%**, with **42** forward points withheld |
| `uv run python scripts/mutation_kelly.py` | **27 / 27 applied, 27 killed, 0 survivors, 0 defects** — **extended by D-064** from 25 to 27 mutations so the payoff-unit seam is covered from both sides: `M4.3` (the unit refusal removed) and `M4.4` (the vocabulary re-narrowed to one member). Both are killed. `check_targets`: **0 problems** after re-anchoring `M9.2` — the anchor had been written on the removed `Literal[*get_args(...)]` form, and the gate correctly refused rather than running a mutation that no longer matched anything. Re-run at record-set close per the increment's brief |
| `uv run python scripts/mutation_invalidation.py` | **24 applied / 23 killed / 1 survivor (the control), exit 0** — 24 mutations in 9 groups across two files, with both `check_targets` and `check_anchor_landings`. **The first run was 24/20/4 and the harness REFUSED TO CERTIFY.** Three real gaps: `M1.2` survived because **no fixture carried a numeric-looking string** (`"CONVERGING_DOWN"` and `["-1"]` fail `float()` for other reasons) — closed with `"1.5"`/`"-2.5"`; `M7.2` (`frozen=True` removed) survived because the test only asserted `extra="forbid"` — closed with a parametrised frozen test over all four published models. The fourth was **not a gap**: `M1.5`'s first draft wrote `neutral.append(...) or unreadable.append(...)`, and since `list.append` returns `None`, `None or X` still ran X — **the mutant never changed the program.** Re-run at close: identical |
| `uv run python scripts/live_invalidation_check.py` | **passes end to end** — **pulled, not offline**: 8 real FRED series driving **4 real upstream models** (`output_gap`, `inflation_breadth_score`, `inflation_convergence_classifier`, `labor_tightness_score`). It prints each published `value`'s TYPE rather than describing it, and **reproduces the specification's `TypeError` on real data** — `'<' not supported between instances of 'dict' and 'int'` — against the live classifier's verdict. Then the shipped function reads all three shapes, and the **gate is exercised both ways**: a real falsifier is accepted by `TradeIdea`; the specification's own fallback sentence is **also** accepted (the defect, measured); and the shipped assessment's **empty** text is **refused**. Real values at close: `output_gap` **−17.57**, `inflation_breadth_score` **+0.3104**, `labor_tightness_score` **−0.7**, verdict **HIGH** |
| `uv run python tools/sweep_health.py` | **OK — 36 sweeps checked, 0 failures, 0 leftovers** (was 35 before D-068, 34 before D-067, 33 before D-066, 32 before D-065, 31 before D-064, 30 before D-063). Its `_legacy_targets()` was also widened by D-064 to resolve a **list** of candidate paths, fixing five false **ABSENT** reports for `mutation_lei_proxy.py`, and `_own_target_check()` now runs the tool's own uniqueness check on the **14 ungated sweeps** (O-29). **The leftover scan caught O-61 recurring live a third time** — a `SIGTERM` killed the kelly sweep and left `M9.1` applied in `risk_budget.py` (`clipped = bool(final_fraction < requested) is True`), which had also **corrupted two unrelated anchors** whose text the leftover destroyed. Restored by hand and re-verified. The **`enclosing_symbol` fix** (AST, `end_lineno`-bounded) landed here first and was inlined into the new sweep, because importing it made one file two modules under `mypy` (`tools/` has no `__init__.py`). **D-067 found the scan is SCOPED, not blind (O-83).** The leftover check is **per-sweep**: it only looks for mutations that *the sweep being checked* declares, so a mutation left applied in a file **shared with a different increment** is invisible. Measured live: D-064's `M6.3` mutant (`if False:` in `config.py`'s `_remaining_shares_must_sum_to_one`) was **still on disk**, and this tool reported **0 leftovers** — because `config.py` belongs to the scenario sweep, which was target-clean only because the mutation had **already fired**. The constraint was restored and that sweep then ran **23 applied / 22 killed**. A one-line whole-tree scan for `if False:` across `src/` is the obvious remedy and is **not** yet implemented |

**D-035's correction was itself caught by this table.** The live-check row was
green when D-034 closed, but re-running the check as the first step of the next
increment failed: the accuracy record did not match a live recomputation. The
cause was an estimand error in D-034's own measurement, not a data change. Every
figure in the accuracy block has been recomputed; the tolerance was **tightened**
(0.5pp → 0.15pp) rather than widened. See **D-035**.

**The 1 failure recorded in the previous run is resolved, and the skip is the
only remaining exclusion.** The failure was
`test_live_snapshot_build_produces_a_coherent_economic_picture` on the FRED
`IORB` wall-clock condition — recorded as D-030, deferred, then recurring twice
more. On the third recurrence the decision was taken rather than deferred: the
registry now carries a per-series `future_date_tolerance_days` (1 on `iorb` and
`sofr`, 0 elsewhere), so the condition is disclosed as INFO while the ERROR path
stays armed outside the tolerance. See **D-033**. The 1 skip is the documented
Phase 5+ confidence-coincidence case in `test_output_gap.py`.

**Regression note.** Both failures in that run were caught by the **full** suite,
not by the increment's own evidence — its 55 tests, mutation sweep and
live check were all green first. A per-increment green light validates the new
code; it does not validate that the new code left every existing contract
intact. Run the full suite after any registry or schema change (**D-033**).

---

## Tier 1 — 23 / 23 ✅ COMPLETE

- [x] Bond math: `price_bond`, `macaulay_duration`, `modified_duration`,
      `convexity`, `price_change_with_convexity`
- [x] National accounts: `gdp_deflator`, `output_gap`, `savings_investment_identity`
- [x] Yield curve: `curve_slope`, `breakeven_inflation`, `decompose_yield`
- [x] Labor: `openings_to_unemployed_ratio`
- [x] Index numbers: `laspeyres_index`, `paasche_index`, `fisher_index`
- [x] Quantity theory: `quantity_theory_implied_inflation`
- [x] Policy plumbing: `repo_stress_check`
- [x] Risk: `historical_var`, `expected_shortfall`, `parametric_var`,
      `realized_vol_simple`, `portfolio_volatility_two_asset`,
      `portfolio_volatility_n_asset`

## Tier 2 — 29 / 29 ✅ COMPLETE

- [x] `taylor_rule`
- [x] `balanced_approach_rule`
- [x] `first_difference_rule`
- [x] `policy_rule_ensemble`
- [x] `phillips_curve_inflation` — Module 3.3 · **D-026**
- [x] `potential_gdp_cobb_douglas` — Module 3.5 · **D-027**
- [x] `growth_accounting_decomposition` — Module 7.2 · **D-027**
- [x] `claims_trend_signal`
- [x] `claims_corroboration`
- [x] `two_survey_divergence`
- [x] `nfp_revision_adjusted_read`
- [x] `ahe_composition_flag`
- [x] `beveridge_curve_position`
- [x] `labor_tightness_score`
- [x] `inflation_breadth_score`
- [x] `project_shelter_cpi` — Module 5.1 · **D-028**
- [x] `ppi_pipeline_signal` — Module 5.4 · **D-029**
- [x] `gdp_gdi_divergence` — Module 7.1 · **D-031**
- [x] `leading_indicator_proxy` — Module 7.3 · **D-032**
      *(spec name `lei_composite`; renamed per Section 21.1 — an in-house
      composite over free components must not be called "LEI")*
- [x] `simple_gdp_nowcast` — Module 7.5 · **D-034**, measurement corrected **D-035**
      *(the specification's formula is ANTI-correlated with the growth it
      names: −0.169 over 137 live quarters, beaten by reporting the prior
      quarter's print. Four defects corrected, the measured error published)*
- [x] `auction_demand_signal` — Module 8.2 · **D-036**
      *(the tail input is **MANUAL**: §21.1 assigns it to the TreasuryDirect
      auction route, which carries no when-issued yield in any of its 91
      columns. The other four inputs are live. Also found: the indirect share
      has two bases differing by 27pp, `security_term` splits one tenor across
      three labels, and the published bid-to-cover is not reproducible from the
      feed's own totals)*
- [x] `credit_spread_attribution` — Module 8.3 · **D-037**
      *(the specification's `BOTH` branch was **dead code** — `fundamental`
      requires the trend to be "rising" while `technical` requires it not to
      be, so the two are mutually exclusive and `elevated_concern` could never
      be produced. Three of the five inputs were also inert: the two spread
      changes appear only in `inputs_used`. They ship as a **diagnostic**, not
      a predicate, per the user's decision)*
- [x] `compute_fci` — Module 12 · **D-038**
      *(a **backfill**: never implemented or even stubbed, and §22.7 says it
      "must be retroactively added now". The `fci.averages` block it needed was
      **removed, not corrected** — `credit_spread_hy_avg` was stored as 4.0
      against a measured 3.12, an error of **2.1 sigma**. The mandatory NFCI
      cross-check is now part of the model's contract)*
- [x] `qe_qt_stance` — Module 4.1 · **D-040**
      *(the specification's `else: NEUTRAL_HOLD` requires a thirteen-week change of
      **exactly zero** — measured at **0 of 1226 weeks**, so the branch was dead code.
      Corrected to a relative band, which **changes today's answer**: +0.226% is
      `NEUTRAL_HOLD`, where the spec's `> 0` test says `QE_EXPANDING`. Two of four
      inputs were also declared, listed in `inputs_used`, and never read)*
- [x] `minsky_composition_drift` — Module 3.4 · **D-041** · **INPUTS BLOCKED**
      *(§21.1 marks two of the three inputs BLOCKED and **forbids** substituting
      total credit growth as a proxy — my first instinct was exactly that
      substitution. The logic ships and is fully tested; the live check is a
      **block-check** and does not run the model. Its `risky > total * 1.2` test
      **inverts when credit contracts** — 3.3% of weeks, including 2009-09 — so
      de-risking was reported as drift toward risky)*
- [x] `policy_mix_classifier` — Module 3.2 · **D-039**
      *(the source deficit series is **negative for a deficit**, so feeding it raw
      INVERTS the fiscal comparison — a D-034-class sign trap. **My own probe fell
      into it** and reported four wrong base rates; the live check, which asserts
      the sign first, caught it. The spec's bare-string `value=quadrant` and its
      three-input `inputs_used` are both corrected)*
- [x] `marginal_risk_contributions` — **found already implemented**
      *(it was complete and to standard in `models/risk.py` — `compute_confidence()`, `utc_now()`, full shape/symmetry/PSD validation, the
      **Euler identity** check, and 6 passing tests — while this list still showed
      it as outstanding. The checkbox was stale, so the Tier 2 count was one low.
      Its docstring records a real past correction: the contributions sum to the
      portfolio **variance**, not the volatility, and checking against `sigma_p`
      failed on a perfectly valid matrix)*
- [x] `bayesian_update` — Module 12.3 · **D-042**
- [x] `expected_value` — Module 12.4 · **D-042**

## Tier 3 — 15 / 15 ✅ COMPLETE

- [x] `derive_market_implied_policy_path`
- [x] `classify_regime_rule_based` — Module 3.1 · **D-045**
      *(the specification's own logic reaches **6 of its 9 declared states** —
      `slowdown`, `recovery` and `reflation` are unreachable, and their territory
      is **occupied and mislabelled**: the `else` catches the entire
      `trend < 0, -1.5 <= gap < -0.5` band, the textbook slowdown zone, and calls
      it `early_expansion`. Its `recession` branch requires *falling* inflation,
      so the 1974/1980 shape returns `stagflation`. Two of four declared inputs
      were **never read**. The live check then found a fourth defect **upstream of
      the function**: the inflation axis reads `rising` in **93.75% of 240 real
      quarters**, because it is defined on the sign of a *3-month annualized*
      change and the price level falls in only a small minority of months — so
      four states are rare by construction, not by economics. Fixed as far as the
      function can reach; the axis is **disclosed and tracked as O-23**, not
      silently swapped. A fifth defect was found while writing the record —
      `GrowthAxis` declared an `at_trend` member the function could never return,
      and the docstring claimed a `>= settings_late` guard that does not exist —
      corrected under **D-045a**. 40/40 mutations killed.)*
- [x] `check_trilemma_tension` — Module 1 · **D-048**
      *(**a crisis detector that reports no crisis.** §15.20-A's 3-month
      threshold does not fire on §18.1's own reference episode: Black Wednesday's
      month reads **−5.37%** on the 3-month measure, inside the −10% threshold.
      D-048 adds a **1-month acute-break threshold** (−7%, fires on 7.8% of
      months) alongside it; the two tests are **not nested** — the UK breaches
      each alone in 53 and 30 months, Korea in 35 and 14. Also corrected: the
      specification's hardcoded confidences (**flat across severities** now, per
      §22.8) and its **`or 0`** trap, which turned an absent reading into
      evidence of calm.*
- [x] `inversion_probability_adjustment` — Module 8 · **D-049**
      *(**the base rate was 3.1× wrong, and the two dimensions are not the same
      shape.** §15.20-B's literal `0.15` is not a rounded 0.489 — the measured
      12-month-forward recession rate conditional on inversion is **0.489** over
      **592** monthly observations, against **0.209** unconditional and **0.157**
      not-inverted. The literal was not shipped; the base rate is now a required
      input with **no default**, so no caller inherits it. The specification also
      hardcodes confidences `0.3`/`0.35`, which §22.8 reserves. Measured over real
      history: **depth is monotone** (`0.412 / 0.417 / 0.552 / 0.857`) and
      **duration is hump-shaped** (`0.250 / 0.286 / 0.412 / 0.769 / 0.520`), so the
      configured 26-week cap sits **exactly at the peak** — the mechanism never
      enters the region where its own monotonicity assumption is contradicted.
      The hump **survives a censoring control**. Also corrected: a **dead warning
      branch of my own** (a guard that fired on every call and described a clamp
      that had not happened), and a **field/property name collision** that
      resolved a setting to its `CalibratedValue` wrapper. 67/68 mutations killed,
      1 proven-inert.)*

      *Structurally this build's §22.3 US-only scope means the function **can
      only ever return `NO_TENSION`** on its supported path — the dollar floats,
      so the fixed-FX leg is never satisfied. Stated rather than hidden: the
      logic is validated live against the **UK's 1992 and Korea's 1997** history
      through a labelled fixture, and the entire admissible US input plane is
      asserted calm, so making it reachable on `us` forces someone to say why.*

      *The live check's first run **failed**, and that was the increment's most
      valuable moment: `TRESEGGBM052N` reports **843 observations but only 837
      are monthly** — the first six are annual. Every threshold here names a
      number of months, so a "3-month change" across that prefix spans *years*.
      Indonesia is worse (**700 → 668**). Base rates re-measured on the monthly
      span only: **10.6% / 7.8% over 834**. New generalised rule: **a series'
      observation count is not its measurement window.***

      *The mutation sweep then found something more general: **six mutations
      were silently rewriting the wrong function**, because `country="us",`,
      `source_independence_count=0,`, `depends_on_unobservable=True,` and the
      `measured` property body each occur **twice** in their file and
      `str.replace(..., 1)` takes the first. They were reported as weak tests
      when they had never touched the code under test. The runner now **refuses
      to start** on an ambiguous target; the table is generated from a
      behavioural matrix. **60/62 killed, 0 pattern-misses, 2 proven-inert.**)*
- [x] `inflation_convergence_classifier` — Module 5.3 · **D-047**
      *(**the first function obligated by §15.19-D**, and it discharges the
      obligation by calling `count_independent_families()` on its own tagged
      inputs and passing **the family count, not the signal count**, to
      `compute_confidence()` — the audit that D-046's supplier was built to
      serve. Three corrections to the specification's own logic, each measured
      on **522 real months**:*

      *1. the conflict gate is two-measure and the rest are decorative.* It read
      `headline` and `core` only. Measured effect of the correction: **6 months
      (1.15%)**, and on exactly the right ones — `2008-12`, `2017-03`, `2020-03`,
      `2020-04`, `2020-05`, `2026-06`. It now asks whether the **losing side**
      reaches `deep_conflict_share` of the *whole* set, so a 5–1 split with
      one dissenter no longer masquerades as agreement.*

      *2. HIGH is the base state, not a finding.* It fires **89.5%** of the time
      at six measures and **86.6%** at three — reproducing the config to the
      decimal, because the config was measured from this function. The base rate
      now travels with the verdict.*

      *3. the thresholds are degenerate below n = 5.* At n = 3, `>= 0.8` demands
      unanimity and MEDIUM has exactly one attainable value, 2/3 — so **MEDIUM
      is unreachable at n = 3**, and the CONFLICTED gate fires on a *single*
      dissenter. Disclosed at n < 5; the reachability proof moved to n = 6.*

      *(The increment's own input space turned out to be narrower than assumed:
      `core_pce_direction` is **required**, so the floor is 3 measures spanning
      **2 families**, and `independent_families` can only ever be **{2, 3}**.
      §15.19-D's single-family warning and its confidence ceiling are therefore
      **unreachable through the API** — recorded, not hidden. The probe also
      found **two of the three §21.1-"blocked" measures were live** — the
      **O-21 defect class for the third time**. 25/25 mutations killed, 2 inert
      by design.)*
- [x] `tag_evidence_source` — Module 13 · **D-046**
      *(the **supplier** for the `source_independence_count` argument of
      `compute_confidence()` — which had been `0` at every one of its ~15 call
      sites in `models/` since Phase 2, because no function could produce a
      non-zero value for it. A contract with a hole in it. **Typed field, not a
      warning string**: §15.19-D puts the tag in `warnings` and parses it back
      with `startswith`, which any warning-rewriting caller destroys silently
      and a hand-written warning can forge. **Returns a copy, not the
      argument**; a conflicting re-tag is **refused**, not overwritten)*
- [x] `count_independent_families` — Module 13 · **D-046**
      *(returns a `ModelResult`, not §15.19-D's bare `int` — and substantively,
      because the count is uninterpretable without its **untagged denominator**.
      `EvidenceTally` carries `distinct_families`, the sorted `families`
      membership, `tagged`, `untagged` and `duplicate_results`. Its own
      confidence is **not** credited for the families it found — D-027
      circularity. The 31-member `EvidenceSourceFamily` enum **moved out of
      `thesis_layer` into `models/`**: it had shipped as an orphan with no
      constructor and no importing test, in a layer no model-layer convergence
      classifier could reach downward. 17/17 mutations killed, after correctly
      classifying all five first-run survivors — 2 broken, 2 inert, 1 weak test)*
- [x] `four_pillar_scorecard` — Module 12.2 · **D-050**
      *(**a blocking verdict that missed 32 of the 50 configurations it existed to
      block, and a repair whose thresholds turned out to be inert.** The
      specification computes "the pillars oppose each other" and then requires an
      additional, narrower condition — `growth × inflation < 0` — before returning
      `CONFLICTED`. Enumerated over all `3⁴ = 81` pillar combinations: **50**
      genuinely oppose, the shipped rule catches **18**, and the 32 it misses
      include every *"bad news is good news"* split, where growth and inflation
      agree while conditions and policy oppose. The specification's `agree_frac`
      gates are also not the two thresholds they look like: the denominator is the
      **non-neutral** pillar count, so the reachable ratios are `{1.0}` / `{0.5, 1.0}`
      / `{0.667, 1.0}` / `{0.5, 0.75, 1.0}` — **nothing ever lands in `[0.9, 1.0)`**,
      so `0.9` and `1.0` are the same test, and one dissenter out of three scored
      `LOW` while one out of four scored `MEDIUM`. Rewritten as **dissent counts**,
      with the fraction, the dissent count and a new agreement **margin** all
      published so the thresholds are auditable from the output. §15.19-D was
      then discharged — the specification took `independent_source_families: int`,
      which cannot distinguish *four independent families* from *four sub-measures
      of one release*, so a caller passing `4` got `HIGH` silently; the function
      now **calls `count_independent_families()` itself** and the error is
      unrepresentable. Measured: the same four directions `(1, 0, 1, 0)` read
      `HIGH` at 4 families and `LOW` at 1.)*

      *The fifth defect was found by the mutation sweep, and it is the repair's
      own: **`CONFLICTED` is tested first and consumes every opposed read**, so a
      read that reaches the dissent gates has `max(up, down) == n` and therefore
      `dissent == 0` — always. `dissent <= 0`, `<= 1` and `<= 2` are the same
      predicate, the MEDIUM ceiling cannot bind, and the `LOW` "weak agreement"
      branch is **unreachable by construction**. Three mutants proved it by
      surviving. The gates are kept, with tripwire tests, because deleting them
      would freeze the current gate *order* as permanent. **D-047's
      "declared, unreachable" class, found inside the repair.***

      *Live, over **761 real monthly readings** derived from FRED rather than
      supplied: `CONFLICTED` **66.2%**, `HIGH` **33.0%**, `NO_SIGNAL` **0.8%**.
      The space share (**61.7%**, enumerated over 567 configurations) and the
      history share are **different claims and they disagree** — real pillars are
      correlated, so genuine splits are *more* common than the independent-input
      model predicts, not less. Both travel on every output. The live check also
      found real history produces **6 all-neutral readings**, which an earlier
      revision of the input model **refused outright** — the fix is an explicit
      `allow_all_neutral` opt-in, because a state the data produces must not be
      unrepresentable. **81/84 mutations killed, 3 proven-inert**, after
      `check_targets` refused the first run on two self-inflicted ABSENT targets.
      The sweep's most valuable catch after the fifth defect: **four config
      accessors were replaceable by their own shipped literals with the suite
      green** — an accessor test that asserts today's value cannot tell a live
      config read from a hardcoded copy.)*
- [x] `classify_convergence` — Module 12 · **D-051**
      *(**a classifier that could not run, and a cross-check that found a defect
      in an already-closed increment.** Seven specification defects in four
      groups. Group 1: `count_independent_families()` returns a `ModelResult`
      (D-046) and §22.10 compares it to an `int`, so **every call reaching the
      family gate raised `TypeError`** — the section's two halves were written
      against different supplier versions and never run together; and the
      `directions[0]` reference the prose claimed to remove was still there,
      making **132 of 1800** multisets change verdict under permutation. Group 2:
      §12 and §22.10 disagree about the agreement denominator (0.500 vs 1.000 on
      `[+1,+1,0,0]`), `NO_SIGNAL` is declared and unreachable, and `LOW`
      conflates a unanimous single-family read with weak agreement. Group 3:
      D-050's inert-gate defect, structural to the same gate order. Group 4 — a
      defect introduced **by this repair**, found by its own test: the census ran
      over all signals, so appending three neutral signals from three new
      families promoted `MEDIUM`/0.60 to `HIGH`/0.75 with no new directional
      evidence.)*

      *The finding that matters most is not in the new module. The live check
      cross-checks it against `four_pillar_scorecard` on the ground that they are
      the same predicate; **that assertion failed on 95 of 761 real months, and
      the cause was the already-closed D-050 module** — its census counted
      neutral pillars, so one directional pillar plus three neutral ones read
      `HIGH` where the same directional content alone reads `LOW`. D-050's suite
      could not see it because every family-count test there used an
      all-directional read. Fixed; the two now agree on **all 81 cells of the 3⁴
      space** and 761/761 months. **When two functions share a defect pattern,
      one function's repair is a defect report against the other.**)*

      *Two harness defects were found by the sweep's own machinery. A test path
      that does not exist makes `pytest` exit 4, which "non-zero means killed"
      counted as a kill — the first run reported a false **56/56**, exposed only
      by a control mutation that could not fail; `check_tests_collect` now gates
      the run. And four config targets became **ambiguous** once
      `ConvergenceSettings` landed beside `ScorecardSettings`, which both sweeps'
      `check_targets` refused — the scorecard's re-run then caught three of its
      own.)*
- [x] `cross_asset_transmission` — Module 5.6 · **D-052**
      *(**the gold rule did not run the trigger its own paragraph states, and
      two shipped base rates were transcriptions no population reproduced.**
      §20.5 says gold falls when the **nominal** yield rises; the shipped rule
      keys on the **real** leg — correct economics, *opposite* to the prose — so
      `driver_channel` is now published on every output and `M5.2` pins it. A
      `x > 0 else "up"` direction reported an **unchanged** yield as a rise, on a
      same-day read where a flat leg is ordinary; repaired by a three-way
      `_leg_direction` with the flat case tested **first**. `inflation_surprise_bp`
      is declared, listed in `inputs_used`, and read by nothing — kept as a
      disclosed input, refused as a hidden one, and registered `blocked:` because
      a genuine surprise needs a consensus nobody publishes free. Three published
      keys came from **one** predicate, so `gold_call` + two equity reads looked
      like three confirmations and were one. `usd` was a sentence, not a
      direction: it emits `unresolved` rather than guessing a regime fact it has
      no input for. `surprise_driver: str` → `Literal`. `confidence=0.45` →
      `compute_confidence()` (§22.8).)*

      ***The composition defect the brief asked to look for was found and
      proven.*** *The driver split tests `both_channels` before `real_driven`, so
      every input that would reach `real_driven` is consumed earlier —
      **D-050's exact shape**. Two mutants survived (**M2.7**, **M2.8**) and
      neither was written off as a weak test: the prover enumerates the whole
      admissible space, **643 200 cases, 0 differences**, and the proof re-executes
      on demand. This increment also named the **third kind of inertness** —
      **name-not-value** (**M9.2** rewrites a published *key name*, not a value) —
      beside D-050's threshold and composition kinds.*

      *The live check's first run **failed**, and both failures were in artifacts
      already shipped. `gold_call_base_rate` read **0.7779**; the monthly
      recomputation is **0.7556** (daily **0.8846**) — **no population reproduced
      the shipped figure**, which is O-30's class reproduced in a config leaf: a
      recalled number, plausible, error-free by every existing gate, catchable only
      by re-fetching. `measured_breakeven_negative_share` was wrong the same way
      (0.2754 → **0.2652**). A third note cited a **daily** denominator under a
      **monthly** heading. All three corrected, with the failure recorded in the
      leaf rather than the number quietly swapped.*

      ***The requested cross-check was built — and the obvious candidate was
      rejected.*** *Comparing the derived real yield to the observed one is
      **arithmetic, not evidence**: the check first proves the identity
      `DGS10 − T10YIE − DFII10` is exact (max error **0.000000** over 5 931 obs),
      which is the *proof the derivation is not a proxy* rather than a
      cross-check. The real cross-check is against `inversion_probability_adjustment`
      (D-049), chosen because it is genuinely **disjoint** — a same-day long-end
      *decomposition* versus a short-end *level*, directional calls versus a
      probability, **no shared input** — so agreement is evidence rather than
      tautology (D-027's disjointness rule).*

      *Harness finding: **a wording collision masquerading as coverage.**
      `M10.3` survived because the warning guard matched `"below the"`, which
      occurs in **two** branch texts, so deleting one left the guard green. Fixed
      by mutually non-colliding markers plus a guard asserting each warning matches
      **exactly one** marker.*

      ***Honours discharged:*** *the sweep was re-run at close (clean, all proofs
      hold) per the brief's first requirement, and the cross-check was built from
      the start per the second — which is what found the composition defect **and**
      indicted the two shipped config values. **55/58 killed, 3 proven-inert, 0
      defects**; 58 mutations in 13 groups; 52 tests.)*
- [x] `project_inflation_trajectory` — Module 3.6 · **D-053**
      *(**the specification's own threshold made `stable` the base state, and its
      bands and its slope were not independently choosable.** §16.2's band was
      `±0.15pp` against a `beta` of `0.043`: on the declared score range that
      labels **79.1% of 296 real months** `stable`, so the classifier carries no
      information — **D-047's base-state failure**, reproduced. The repair is not
      a narrower band, because **the band's score-width *is* `band_pp / beta`**:
      band and beta are **not independent**, so choosing both at once chooses the
      partition and the slope simultaneously. They are now measured separately —
      beta from the **OLS slope of the 6-month forward core-inflation change on
      the labor score** (no band needed), the band as an **independent statement
      about what counts as a meaningful move**. Seven specification defects in
      total, including a **double negation that cancels** (`slack = -s/100` then
      `pc = -beta*slack` ⇒ `pc = +beta*s/100`; the first functional run returned
      `reaccelerating` for the *loosest* possible score), and an unnamed
      **estimand** (a projected *change* reasoned about with a *level* spread).
      The live check **caught a 7× config error** — `0.043 → 0.006` — before the
      record set was written; band `±0.15 → ±0.05pp`. Base-state failure
      eliminated: label mix `reaccelerating` 40.5% / `stable` 31.4% /
      `decelerating` 28.0%. The relation is **real but small** (survives
      12-month detrending at **+0.348**; R² 0.047) and holds over **3-9 months**
      — it **reverses at 24 months** (slope −0.0114, t −2.94), the signature of a
      policy reaction rather than an instability. The sweep found a **genuine
      coverage gap** — `M5.2` survived because each per-state test drove one
      quadrant, so nothing covered both agreement branches against the disagreeing
      inputs sharing their sign pattern. 21/24 killed, 3 expected survivors, 0
      unexplained; 47 tests.)*
- [x] `evaluate_drawdown_rules`
      *(D-054. 65 tests, 13 mutation groups, 47 mutations. **A de-risking ladder
      that could never fire.** §6.6c writes its thresholds as FRACTIONS
      (`DrawdownRule(0.10, 0.50)`); `config/settings.yaml` writes them as PERCENTS
      (`{drawdown_pct: 10.0}`). A function reading one and comparing against the
      other is off by 100×, and the **direction of the error was the opposite of
      what the probe predicted**: not "every tier fires", but **no tier can ever
      fire**, so the ladder is permanently silent and reports "no risk-reduction
      rule triggered" at a 90% drawdown. For a de-risking rule, failing toward
      *inaction* is the worst failure mode available. Resolved by normalising at
      one boundary (`_tiers()`) and adding a magnitude floor to `DrawdownTier` so
      the file's convention is **checkable at load time**. Four further spec
      defects: unbounded `risk_reduction_pct` (a 500% "reduction" was legal);
      "evaluated in order" contradicting "most severe wins" (the result is
      permutation-invariant); `max(key=severity)` vs `max(key=threshold)`
      indistinguishable on the shipped ladder and divergent off it; and `0.0`
      ambiguous between "nothing fired" and "fired, prescribed zero" (fixed with a
      `RuleOutcome` `Literal`). **The accessor had no consumer at all** — a clean
      "declared, consumed, unreachable" instance. The base-state rule (lesson 5g)
      **does not apply** and the non-application is recorded: `no_action` is modal
      and *correct*. Sweep **46/47 killed, 1 survivor (the control)**; the first
      run was 42/47 with four genuine gaps, all closed. Live check walks a real
      daily SP500 path (2513 obs); all three outcomes reachable, 33.92% worst
      drawdown on 2020-03-23, path-independence 0 violations.)*
- [x] `check_rebalancing_drift`
      *(D-055. 58 tests, 12 mutation groups, 64 mutations. **A drift check that
      could not see an instrument it was not told about.** All four specification
      defects are the same shape — every input the function is not told about is
      treated as a confident zero rather than as unknown: (1) a target with no
      current value reads as `0.0` via `.get(..., 0.0)`, so a book omitting a
      budgeted instrument reports a **maximal underweight on no evidence**;
      (2) an instrument held with **no target** is never iterated, so a book that
      has drifted *entirely* into unbudgeted positions reports `balanced` — the
      same census defect D-050 found in `four_pillar_scorecard`; (3) the
      threshold's unit was unstated for the **third consecutive increment**
      (a **fraction** leaf sitting beside `_pct` percent leaves), now pinned in the
      guard message rather than a docstring; (4) `>` is strict at the boundary —
      **and the first boundary fixture did not sit on it**: `0.25 + 0.10 - 0.25`
      is `0.09999999999999998`, a hair *below* `0.10`, so the test passed for the
      wrong reason and the `>` → `>=` mutant **survived**. Rebuilt on the
      binary-exact pair `0.225 - 0.125 == 0.10`. **The failure direction is the
      opposite of D-054's**: that ladder failed toward *silence*, this function
      fails toward **false confidence**, and both are fail-safe-looking outputs
      produced by a missing input. The prediction (census shape) **held** and aimed
      the design — but the hazard was *omission inside one caller*, not *divergence
      between callers*. Base-state rule **not applied**, and the non-application is
      recorded (live trip rate **9.7%** at the configured 10%, so `balanced` is not
      modal by construction). First increment in the repo to **populate
      `_EXPECTED_INERT` with proven entries**, and the two proofs are of
      deliberately **different strength** — `M4.6` unconditionally inert (the
      `abs(signed) > threshold > 0` guard removes `signed == 0` from the direction
      test's domain entirely) versus `CX3` inert **conditional on the shipped
      config** (the `float()` cast is the identity on a `builtins.float` leaf, and
      would become load-bearing if the leaf ever became a `str` or `Decimal`). The
      harness now **refuses to certify** an excused mutation carrying no proof
      (exit 2). Sweep **64/64 applied, 61 killed, 3 survivors, 0 unexplained**; the
      first run had 12 survivors of which only 6 were real gaps — two **inert by
      construction** (dead code in the mutant), one **inert by anchoring** (a new
      `model_config` shadowed 9 lines later, so the code under test never changed).
      Live check: five real ETFs (`SPY TLT IEF GLD UUP`), 504-session covariance,
      `sigma_p = 8.33%`, **SPY 35.0% of notional → 56.14% of risk**, UUP `-1.48%`,
      and the cross-check against `evaluate_drawdown_rules` is a **real call**, not
      a re-implementation, so D-054's O-43 asymmetry is not repeated. It found
      three things no fixture could: the contract **cannot budget a hedge**
      (O-46), a partitioned share vector **must be renormalised** — caught by the
      function's own sum-to-one warning at `1.014778` (O-47) — and the response is
      **V-shaped, not monotone**, which corrected the check's own invariant.)*
- [x] `volatility_target_scaling` — Module 17.2 · **D-056**
      *(**§20.13's entire constraint enforcement is `min(scaled, max_leverage)` —
      a ONE-SIDED UPPER BOUND.** So the only limit the function implements is
      inert exactly when a vol target matters: on the de-risking side `min(0.25,
      3.0)` is a no-op, and on the live path the clip fires **0.0%** of 444
      sessions while the reflexivity warning fires **13.1%**. The failure
      DIRECTION is D-054's — toward **silence** — arriving through a different
      mechanism. **(2)** Four of the five limits §17.3 declares beside it
      (`max_position_pct_of_portfolio`, `max_factor_exposure_pct`,
      `min_liquidity_days_to_unwind`, and `max_drawdown_trigger_pct`) had **zero
      references anywhere in the repository** — the **D-037 class** again
      ("declared, consumed, unreachable"), and the repair is *disclosure*
      (O-48), not enforcement. **(3)** The mandatory §20.14 golden test
      `test_vol_target_respects_hard_limits` is a **HIT, not a PARTITION**
      (lesson 49): it names `max_leverage` and passes while four limits stay
      unenforced. **(4)** `clipped_by_limits` covers one side and reads as
      covering both — a **94%** de-risking reports `clipped=False`; repaired by
      the `de_risking_fraction` key. **(5)** `current_gross_exposure`'s unit was
      unstated; the vol identity `realised == target` holds for **every** gross
      under the multiple reading, which is what fixes it. **(6)** A **pre-existing
      leverage breach** (gross 5.0 > cap 3.0) was reported as an ordinary
      vol-target adjustment — right arithmetic, wrong **attribution**; now a
      separate published flag with a warning that says so. **O-45 resolved by
      DELETION** (`RiskLimits.max_drawdown_trigger_pct` was the **same trigger**
      as the ladder's first rung and unreachable from this signature — the ladder
      governs, so the duplicate field is gone and `RiskLimits` ships with **4**
      fields). **O-43 discharged** (`live_drawdown_check.py` §4 now CALLS this
      function instead of re-implementing §20.13). Base-state rule **not
      applied** — recorded, because the output is a *magnitude* and the probe's
      live clip rate is **0.0%**, so no state is modal by construction. The unit
      trap is live for the **fourth** consecutive increment: `max_position_pct_of_portfolio:
      0.15` is a **FRACTION despite `_pct`**, and the guard is a magnitude bound
      (`<= 1.0`) because that is the only contract a `float` admits — deliberately
      **not** applied to `max_leverage`, where `3.0` is a legal multiple *and* a
      legal-looking percent. Sweep **23/23 applied, 21 killed, 2 survivors, 0
      defects**; the first run had 7 survivors of which **5 were real gaps** —
      including `M3.2`, *the D-056 defect in mutation form* (relocating the
      one-sided clip to the up-scaling side passed the entire file, because every
      clipping test scaled up and every de-risking test sat below the ceiling) and
      `CX3` (a guard widened to `<= 10.0` still rejected the test's `15.0`, so it
      *looked alive*; the fix is the **band** `(1.0, 10.0)`). **`M6.1` is the
      first entry to carry a proof through the `_INERT_PROOFS` gate** — INERT BY
      **ANCHORING** (lesson 54) with a **conditional** proof, because its literal
      `0.5` *is* `0.7 − 0.2`. Live check: real 5-ETF book, vol **8.33%** vs a
      **10.00%** target → scale **1.2010×**, and **TWO cross-checks built from
      the start** — `evaluate_drawdown_rules` on the shared *invariant* and
      `check_rebalancing_drift` on the shared *disclosure shape*.)*
- [x] `apply_fractional_kelly` — Module 17.3 · **D-057** · **TIER 3 COMPLETE**
      *(**§17.3's `raw_kelly = ev / 100` is a placeholder §22.6 calls
      "incorrectly labeled Kelly" and §22.13 makes deleting MANDATORY** — so the
      real generalized Kelly `f* = argmax_f SUM_i [p_i log(1 + f r_i)]` ships as a
      grid search over the **full discrete distribution**, divided by the
      mandatory fractional divisor, then clipped. **(1)** The placeholder is
      **3 077×** wrong *and* wrong in **shape** — linear in EV versus a ratio of
      odds with a domain ending at ruin — and ships in **no form, not even behind
      a flag**. **(2)** §22.6's own `n_grid = 1000` literal is **too coarse**: a
      1000-point grid returns **`0.200200`** where the closed form is exactly
      `0.200000` — **400×** the 6 dp the result is rounded to, so the published
      digits were search noise; moved to `kelly.grid_points = 100001`. **(3)**
      §22.6's payoff-unit rule is **contradicted by the thesis layer's own
      `ScenarioOutcome`**, whose `unit` defaults to **`bp_pnl_proxy`**; repaired by
      a **required enumerated** `payoff_unit`, but the bp payload's *gain* side is
      not refused by the `< -1.0` guard and the conflict is recorded as **O-50**.
      **(4)** A 100× unit error produces a **smaller, cap-slipping** number —
      **a THIRD failure direction**: D-054 failed toward *silence*, D-056 toward
      *false confidence*, **Kelly toward prudence**. **(5)** A binding cap
      collapses **4 of 5** distinct sizes onto one, and the **pre-clip request
      collapses too** (P5b, found by the increment's own test): every
      all-positive-edge distribution pins `f*` at 1.0, so the request is
      identically `1/k` — repaired by publishing the request *and*
      `expected_log_growth_at_request`, the key that still discriminates.
      **(6)** Reusing D-056's unenforced-limits list would have named
      `max_position_pct_of_portfolio` — the one limit Kelly **does** enforce — as
      unenforced; a second property names the correct, **different** set. **The
      mandated cross-check is the function's own analytic oracle** — the binary
      closed form `f* = (p b − q a)/(a b)` — and agrees to **3.33e-16**, machine
      precision. Sweep **25/25 applied, 21 killed, 4 classified survivors**; the
      three proven-inert are UNREACHABILITY/EQUIVALENCE proofs, and **`M7.1`'s
      proof corrected the module's own docstring** (the "clipped to zero" state is
      unreachable, because a cap small enough to zero the size is not a legal cap).
      **Running the sweep broke the tree once** — `SIGTERM` bypassed the
      `finally` restore and left a hardcoded divisor in `src/`; `-x` plus a signal
      handler now guard it, and the incident is recorded in the harness docstring.)*
- [x] **`apply_fractional_kelly` was the last Tier 3 function — TIER 3 IS COMPLETE
      (15/15).** Tier 4 then opened with `select_instrument` (D-058). It gates
      Phase 3.

## Tier 4 — 11 / 11 ✅ COMPLETE

- [x] `select_instrument` — **D-058.** §22.3.1's corrected router, and the one
      function whose output reaches `TradeIdea.instrument`, so §22.12's boundary
      is enforced here. The probe found **eleven** findings, **four of them in the
      specification itself**: its own curve instrument failed its own universe
      check (P1/P2); its own `assert universe in PRODUCTION_UNIVERSE` was vacuous
      (P4); `gap_direction` was declared, validated nowhere and consumed nowhere
      (P5); and both confidence values were hardcoded (P6, §22.8). `ProductionUniverse`
      had **zero tests and zero callers** (P8) and **three latent defects** (a real
      G10 FX instrument rejected, P9; a case-sensitive `NONE` sentinel, P10), all
      repaired here. 63 + 30 tests, a 31-mutation sweep (**27 killed, 4 survivors**,
      3 proven inert + 1 control), and an offline authority cross-check.
- [x] `construct_duration_weighted_curve_trade` — **D-059.** §15.1b's curve-trade
      arithmetic, in `models/yield_curve.py` as the specification places it. **The
      specification's only guard is a tautology**: `net_duration_residual` is the
      notional's own definition algebraically simplified, so `abs(residual) >= 0.01`
      ("check duration inputs") can never fire on a wrong duration — a duration
      wrong by **ten times** gives an identical result. Measured over 1377 cases:
      1185 exactly 0.0, worst nonzero **9.766e-04** (9.8% of the tolerance), so the
      guard is unreachable by a **10× scale-conditional margin**, recorded as
      **O-56**. Replaced with a real duration/tenor band `[0.15, 1.05]` in config,
      plus an explicit Macaulay-vs-Modified attestation for the 1–2% error the band
      **cannot** see. **The sweep's first run reported 31/31 killed and was false** —
      a test was failing unmutated, and the honesty control is what exposed it. The
      live cross-check found that duration-weighting equals true level-cancellation
      only when the legs trade at the same price (**O-57**), and that
      `price_bond`'s `coupon_rate` docstring contradicts its behaviour (**O-58**).
      50 tests, a 31-mutation sweep (**26 killed, 5 survivors**: 3 proven inert +
      1 construction + 1 control), and an offline `bond_math` cross-check that also
      closes the D-058/D-059 seam.
- [x] `construct_breakeven_trade` — **D-060.** §15.1b's breakeven half, the same
      duration-matching rule applied across a **TIPS / nominal** pair. **The spec
      publishes no guard of any kind** (no residual, no `warnings` list — D-059's
      sibling at least had a dead one), so a 10×-wrong duration or a swapped pair
      was silent; the contract now carries a per-leg band **and** a ratio band
      `[0.5, 1.6]`. **The substantive finding: the rule matches *duration* while the
      level exposure it claims to cancel cancels on *dollar* duration**, with the
      exact closed form `shipped/exact = P_nom/P_tips`. Priced through the shipped
      `bond_math` over 48 real configurations the correction runs
      **−56.4% .. +98.7%** and **flips sign at the TIPS leg's own par price**, so no
      constant adjustment can hedge it — **O-59**. Two of my own errors were caught
      by the cross-check: the shortfall is **two-signed**, not the "always too small"
      I first asserted; and the config note's ratio range came from a **simplified
      probe pricer** rather than shipped code (**O-60**, tightening the ceiling's
      headroom from a claimed 14% to a real 3%). 31 tests, a 26-mutation sweep
      (**23 killed, 3 survivors**: 1 name-not-value with byte-identical output,
      1 unreachability + 1 control), and an offline cross-check that asserts the
      closed form and closes the **two-keyword** D-058/D-060 seam.
- [x] `construct_cross_market_rv` — **D-062.** §20.12's cross-market relative-value
      constructor, in `models/yield_curve.py` beside its two siblings. **The finding is a
      sign the specification never checks**: §20.12 defaults `correlation_stressed` to the
      literal `0.9`, and over 8 real US cross-market pairs (daily changes, two independent
      stress states) the **normal** correlation runs **−0.623 .. 0.820** — so the published
      `hedge_degradation` is **negative for 8 of 8 pairs**, i.e. the specification asserts,
      universally and silently, that the hedge *improves* in a crisis. The arithmetic is
      right; the sign is unchecked. **A new failure direction: false reassurance** (D-054
      silence · D-056 false confidence · D-057 prudence · D-058 false executability ·
      **D-062 the number says the risk fell when it rose**). Repairs: the stressed
      correlation comes from §21.1's own leaf — an accessor (`stress_corr`) with **zero
      consumers anywhere in the tree** until now, which is what kept the default's effect
      invisible — the **route is published**, the direction is a **three-way `Literal`**
      with `unchanged` tested first, a **measured plausibility bound** refuses the values
      the default produces (up to −1.523), and a **conditional warning** names the LTCM
      leverage mechanism. Six further spec defects: `country="global"` against §22.3 and
      `ModelResult.country`'s own contract; **no input contract at all** (`duration_b = 0`
      divides by zero, one market on both legs prices no trade); the band cannot be a
      duration/tenor ratio (a cross-market pair has no shared maturity — measured ratio
      **0.0161 .. 62.21**); `inputs_used` listed 4 of 7 fields; `confidence=0.5` hardcoded;
      and `hedge_effectiveness_*` were re-exports rather than derivations. **The seam
      CANNOT be closed**: no `ThesisType` names a cross-market RV, and the only member that
      does is blocked for the same reason §22.3 forbids `global` — so the live check
      *enumerates the vocabulary and demonstrates the absence* (**O-66**). The cross-check
      is a **REAL CALL** to `construct_duration_weighted_curve_trade` and caught a
      degenerate fixture of my own (both legs at par → a 1.000000 ratio proving nothing);
      off-par legs give `shipped/exact = P_b/P_a` exactly, under-hedge **+17.53%**. The
      live check also **corrected a config note in the same increment that wrote it**
      ("about 3x headroom" → **1.56x** once the VIX tail counted). 50 tests, a 41-mutation
      sweep (**40 killed, 1 survivor = the control**) whose first run was 41/38/3 and whose
      harness **refused to certify**, and `check_anchor_landings` — a new gate that proves
      an anchor lands in the function it was written for (**O-67**).
- [x] `derive_invalidation_conditions` — **D-063.** Module 14's evidence-based stop,
      §16.2 Q8 / §20.15, and the **first thesis-layer function** in Tier 4. **The
      specification's thesis builder cannot execute its own Q8**: it writes
      `inflation.value < 0` while `inflation_convergence_classifier` publishes
      `InflationConvergenceVerdict(...).model_dump()` — a **dict** — so the comparison is
      `dict < int` and **raises**. **Reproduced on real data**, not a fixture. The crash is
      *latent*: §16.2's Q1 happens to pass `inflation_breadth_score` (a float), while
      §20.15's own docstring names the dict-valued model — and the same section's
      `build_confirmation_signals` guards with `isinstance(...)`, so **the two halves of
      §16.4 disagree about the contract they share**. Three further defects: **`growth` is
      declared and never read**; **the fallback sentence SATISFIES the LTCM hard gate it
      says is unmet** (measured: `TradeIdea` accepts *"no falsifier was found"* as a
      falsifier — D-052's "a guard must be a PARTITION, not a HIT" reached through the
      schema); and **the model §20.15 names is direction-blind** (its vocabulary is
      agreement STRENGTH, and `agreeing` is the majority count, not the majority side),
      so it cannot express the "reacceleration" attributed to it. **The return type
      becomes `InvalidationAssessment`** — a recorded divergence from §16.4's `-> str`,
      because a bare string cannot distinguish "a falsifier was found" from "none was"
      in a way the gate can consume. Its `text` is **empty when nothing was identified**,
      so the gate fires and the builder must route to `no_trade_thesis(...)`: **the gate
      becomes load-bearing.** The narrowing is explicit and total (`bool` excluded before
      `int`, because `isinstance(True, int)`; verdicts read only against the classifier's
      OWN vocabulary; every other shape **reported**, never crashed on and never silently
      skipped), both signs produce a condition (the spec's two `< 0` tests could only ever
      describe a loosening/disinflation thesis), a signal exactly on the crossing produces
      none, and every condition names its model, its value and its threshold. 37 tests, a
      24-mutation sweep (**23 killed, 1 survivor = the control**) whose first run was
      24/20/4 and whose harness **refused to certify** — two real gaps closed, and a third
      survivor exposed as **a mutant that never changed the program**
      (`neutral.append(...) or unreadable.append(...)`: `list.append` returns `None`), and
      a **pulled** live check over 8 real series and 4 real upstream models.
- [x] `build_scenario_distribution` — **D-064.** Module 12's outcome set, §16.4.
      **This increment was recovered, not started**: an interrupted session had
      written the function, its 38 tests, its config block and `sweep_health.py`'s
      extension, and had written **no record of any kind** — the tree was dirty and
      all gates happened to pass, which is exactly why "it passes" is not the
      standard. **The headline finding is a silent default.** §16.4's
      `payoff_unit` is declared `Literal["fraction_of_capital"] = Field(...)`, and a
      one-member `Literal` with a description and no explicit `default=` is still
      **optional** to pydantic — so `KellyInputs(scenarios=<bp distribution>,
      limits=...)` **succeeded** and relabelled a bp-payoff distribution as a
      fraction-of-capital one, entering the Kelly arithmetic with the wrong units and
      no error (**O-50**'s seam, closed here; the neighbouring defect was **O-51**'s
      class collision, also closed). The repair makes the field **required**, widens
      the vocabulary to `KellyPayoffUnit = Literal["bp_pnl_proxy",
      "fraction_of_capital"]`, and adds a **named refusal** so the wrong unit is
      *nameable and refused* rather than silently absent. Three further defects in
      §16.4's own four leaves, all measured. And the **live check found a fifth**:
      the distribution is **direction-blind** — a **+1.0%** and a **−1.0%** gap
      produce byte-identical payoffs *and* probabilities, invisible to every fixture
      because every fixture used `+1.0` while the live gap is negative (**O-71**).
      Two gates had to be repaired to get here: the shared
      **`check_anchor_landings` was manufacturing findings** (it resolved an anchor's
      owner by matching `line.startswith(("def ", "class "))`, which is true of a
      *comment*, so `KellyPayoffUnit` was reported as landing 150 lines away in
      `volatility_target_scaling`) — fixed by resolving through `ast.parse` with
      `end_lineno` bounding, in both the shared tool and the new sweep; and the
      sweep's **honesty control was a no-op** (`old == new`, so it was never APPLIED
      and could be neither killed nor survived — lesson 80's own trap). 38 tests, a
      23-mutation / 8-group sweep across **five** files (**22 killed, 1 survivor =
      the control**), the kelly sweep **extended 25 → 27** so the seam is covered
      from both sides, and a **pulled** live check over 3 real rule models and live
      FRED series. **O-61 recurred live — FOUR times in this increment, and the
      last one was the worst.** A `SIGTERM` left `M9.1` applied in
      `risk_budget.py` (`clipped = bool(final_fraction < requested) is True`);
      an earlier restore fixed the corrupted anchors but **left the `clipped`
      line mutated**, and a later `ruff format` run **baked the residue into the
      record set**. It was caught only at close-out, because the kelly sweep then
      reported **25 applied / 27** with two mutations as **"NOT APPLIED
      (no-op)"**. Three things made it severe: **`sweep_health.py` reported 0
      leftovers both before and after** (its detector looks for the mutation's
      *replacement* string, which **was** the corruption — **O-72** demonstrated);
      the sweep **still certified** at 25/27 with 0 survivors; and **every gate
      was green on the corrupted tree**, including **1705 passing tests**, because
      `bool(x) is True` equals `x` for a `bool` — no test *could* fail. Restored;
      the sweep then reproduced **27/27 killed, 0 survivors** exactly. **Lesson 93.**
- [x] `next_catalyst_calendar` — **D-065.** The forward official calendar, §16.4.
      §16.4's sample returns **three dateless strings**; this returns **dated**
      entries from the **two official sources** it names. **Five measured defects**
      in the sources themselves, all confirmed on live data: (1) FRED's
      ``ptic`` is a **pagination total, not an event count** — 2806 for a window
      whose first page holds 50 rows; (2) the **unfiltered** FRED path costs
      **one HTTP request per calendar day** and times out; (3) FRED's release
      **101 "FOMC Press Release" returns a row for EVERY calendar day** (41/41
      measured), so a reader trusting it reports "the next FOMC" as *tomorrow,
      forever* — the FOMC is therefore read from **federalreserve.gov**, which is
      what §16.4 names; (4) **flattening the Fed's page to text makes phantom
      meetings** (55 hits vs 53 structured) from the trailing 2028 note, so the
      parse reads ``fomc-meeting__month``/``fomc-meeting__date`` and never flat
      text; (5) the endpoint **drops urllib's and aiohttp's connections**
      (``RemoteDisconnected`` / ``TimeoutError``) while answering **httpx on
      HTTP/1.1** — which is *why* ``obb.economy.calendar`` times out here at all,
      since OpenBB's FRED provider is aiohttp-based. Two further defects found in
      **this increment's own code**: a **false-positive warning** (the name guard
      compared ``"CPI"`` against ``"Consumer Price Index"``) and a horizon that
      bounded the **request** but not the **result**. **Lesson 94.**
- [x] `build_confirmation_signals` — **D-066.** §16.4 Q7's signal set. The
      headline is a **fall-through that invents disagreement**: the sample derives
      `direction` from one `if` with a bare `else`, so every outcome its condition
      cannot express becomes `"contradicts"` — measured for a **dict** (which
      `four_pillar_scorecard` and `inflation_convergence_classifier` both publish),
      for **`0.0`**, for **`True`**, and for a non-zero value against a **zero**
      gap. Three of the four are not disagreement at all; an unreadable value was
      reported as an *active claim of directional opposition*, which is D-056's
      false-confidence direction. **O-69's full extent measured: six distinct
      `source_model` labels across three spec locations, one common, and
      `curve_slope` is not a parameter at all** — so the shipped function derives
      every label from the result's own `model_name`. Three further defects:
      `source_family` never populated (**the count unreachable, not wrong**),
      `detail` = raw interpretation (a signal can undercut itself unflagged), and a
      return type that cannot carry Q7's second half (so the shipped return is a
      `ConfirmationSignalAssessment` with `unreadable` and a census). **A config
      leaf was correctly REFUSED by the infrastructure gate** — the guard requires a
      numeric accessor, and a display token is not a fact about the economy; it is
      now a module constant, pinned by a test that also asserts no config block
      exists. 32 offline + 1 live test, a 9-mutation / 8-group sweep with all three
      gates and a real control (**8 killed, 1 survivor = the control**), and a
      **pulled** live check whose **own first draft** hand-rolled the growth leg and
      produced **−17.57%** from `GDPPOT`'s **2036** projection — fixed by routing
      through `output_gap_from_snapshot` (**+0.83%**, 42 points withheld).
      **Lesson 95.**
- [x] `collect_all_warnings` — **D-067.** §16.4's thesis-wide warning
      aggregate, and the **D-027/D-046 summariser class**. The sample is nine
      lines whose entire content is a `dict.fromkeys` de-duplication, and it
      fills the field the specification describes in its strongest terms —
      *"never dropped"* (§7.2 step 9) — while §21.4 makes two further classes
      **mandatory**. **Seven defects, all measured before any code was written**
      (three probes, no data needed for the first four): de-duplication
      **destroys the count, and the count is the signal** (4 models → 1 entry;
      **D-046 inverted**); the output **cannot attribute a warning to its
      source**; whether de-dup fires at all is a **producer convention nobody
      states** (**0 of 8** live warnings name their own model); "no warnings"
      and "not passed" are the **same value** (D-066's shape); **§21.4's blocked
      class has no route in** (a blocked input is one no model could run on, so
      it is **not a `ModelResult`** — 5 registry members, **0 routes**); **§5.4's
      flags do not reach it either** (5 of 5 absent); and **defects 1 and 6 are
      COUPLED** — the natural fix for 6 makes every model carry the **same
      string**, which is exactly what defect 1 collapses. The repair picks no
      side: the return becomes a `WarningSummary` whose `warnings` is §16.4's
      list **verbatim**, with `sources` (which models raised each text),
      `unattributed` (a closed `origin` vocabulary for the two mandatory
      classes), `model_warnings`, and the two **denominators** that make the
      list readable as a severity. **It does not walk the registry or snapshot
      itself** — `unattributed` is a parameter, because a function that reached
      into global config would make §21.4 look discharged whether or not the
      caller passed anything. **The sweep found a real hole in this increment's
      own tests** (M5.1 survived and was not inert — closed by *adding* a test,
      not exempting the mutant) and proved **two mutants must be killed by a
      different gate** (a type annotation, and a guard **no input can trip**),
      which is why `tests/thesis_layer/test_warnings_strictness.py` exists.
      33 offline tests (28 + 5 strictness), a 9-mutation / 9-group sweep with all
      three gates and a real control (**7 killed, 1 unreachable guard exempted
      by argument, 1 control**), and a **pulled** live check. **Lessons 98–100.**
- [x] `no_trade_thesis` — **D-068.** §16.3's first-class stand-down, routed to
      from **three** places §16.2 names — **Q6** (gap inside the rules' own
      dispersion), **Q7** (`CONFLICTED`), **Q8** (no falsifier, which D-063
      added). **Five defects, all measured before any code was written** (two
      probes: one structural, one live). **The sample body does not run** — the
      six required `MacroThesis` fields make it a `ValidationError`, so the
      `# other fields populated with whatever partial view was formed` comment is
      the author admitting a known gap in prose. **One string slot for three
      triggers**: whether two stand-downs are distinguishable is a property of
      the *author*, not the data. **Each trigger already holds a rich object and
      all three are discarded** (the gap's magnitudes; the per-model direction
      table; the invalidation's `unreadable`/`neutral` reasons) — **D-067's
      defect 2 one function on, and worse**, because the dropped object is the
      only record of *which* of three very different things happened.
      `warnings=[reason]` **accepts `""` and `[]`**, so "we stood down" and "we
      stood down and forgot to say why" are the **same object** (D-066's
      shape). And `stop_or_invalidation="n/a"` **is truthy** — measured, the
      LTCM gate **accepts it as a stated falsifier**, so the spec's no-trade
      shape is one `is_trade` flip from asserting a falsifier it does not have.
      The repair is a `NoTradeDecision` carrying a **closed `Literal`
      `trigger`** (`gap_below_dispersion`/`conflicted_signals`/`no_falsifier`/
      `caller`), the typed `evidence` the gate already held, `elapsed` for Q6
      (`dispersion - |raw_gap|` — a gap 1bp short of meaningful and one 200bp
      short are not the same call), and a labelled warning line, plus a renderer
      that refuses `trade_idea`/`status`/`warnings` overrides and writes `''`
      and not `"n/a"`. **35 offline tests + 7 static guards**, a **14-mutation /
      14-group sweep with all three gates and a real control — 13 killed, 1
      survivor, and NO gaps to close on the first run** (the structural reason:
      every defect here is a **PRESENCE** defect, which has a test that names it,
      unlike D-067's **INTERACTION** defect), and a **pulled** live check. Opens
      **O-85** (the trigger is an unchecked caller claim) and **O-86**
      (`WATCH` cannot distinguish "no edge" from "waiting").
- [x] `build_us_macro_thesis` — **D-069, and TIER 4 IS COMPLETE (11/11).** §7.2 /
      §16.2, and **the seam function** — it appears on the Tier 4 *and* the Phase 3
      checklists, and that overlap **is** the phase seam: the models layer stops
      producing numbers and the thesis layer starts making claims. **Nine measured
      divergences from §16.2's sample**, including a correction of my own carried-in
      premise: the sample omits **zero** required `MacroThesis` fields (the "six"
      belonged to §16.4's `no_trade_thesis` sample, which is D-068's). The
      substantive finding is a **plumbing gap measured, not assumed**: **no
      snapshot-fed helper exists** for `inflation_breadth_score` or
      `labor_tightness_score` (the census of snapshot-taking helpers is `[]` for
      `inflation_nowcast`, `labor_synthesis`, `regime` and `national_accounts`), so
      Q1's three reads became a **parameter** (`EconomyReads`, a frozen dataclass)
      rather than a faked transform. Likewise `MarketPricingGap` is **not** a
      `ModelResult`, so §16.2's sample fails pydantic validation — an explicit
      `_as_signal` adapter bridges it. The three no-trade gates fire in order
      **Q6 → Q7 → Q8**, each routing to a helper that **owns its own trigger
      literal** rather than re-deriving it. **THE INCREMENT'S REAL DEFECT was an
      INTERACTION defect, and the live check found it**: `_render` collected **no
      warnings at all**, so every stand-down dropped the model warnings *and*
      §22.5's market-path contamination disclosure — printed as `contaminated=0
      proxy=0` on a path where the contaminated branch had definitely been taken.
      The repair renders first and **appends** the warnings behind the trigger line,
      because `render_no_trade_thesis` *owns* `warnings` and refuses to be handed
      it; measured after the fix, **`warnings=13`, `contaminated=1 proxy=1`**. No
      unit fixture could see this: every offline test asserted the trigger line was
      *present*, and it was — the defect was that it was **alone**. **The sweep
      refused to certify on its first run — SIX survivors, all real test gaps**,
      including **M8, the very defect just fixed**, whose regression test lived
      **only in the deselected live file**; the six were closed by **adding** tests,
      not by exempting mutants. **The second run then killed the honesty control**,
      because a strictness test asserted the fallback's **literal text** instead of
      its meaning — rewritten to pin order and structure by AST. **It also opened
      O-87** (`select_instrument` publishes **two** value shapes — a dict on the
      executable routes, a bare **sentinel string** on the refused ones — while its
      own `_selection_value` declares *"always returns a dict value"*: **that
      sibling claim is wrong**), **O-88** (the false D-068 mypy row), and **O-89**.
      78 tests (51 + 21 static + 6 live), an 18-mutation sweep (**17 killed, 1
      survivor = the control**), a pulled live check, and **the gate that mattered:
      `mypy --strict` at a true 182 files** after fixing all 29 pre-existing errors
      D-068 had left behind. **Lessons 5be, 5bf.**
- [x] **TIER 4 IS COMPLETE — 11 / 11.** The instrument half closed at D-062
      (Module 15, all four functions); the thesis-layer half closed at D-069 with
      `build_us_macro_thesis`. **The blocker on Phase 3 is cleared.**

---

## Phase 3 — ✅ COMPLETE (2 / 2)

**Status: 2 / 2. Complete as of D-070.** `build_us_macro_thesis` (D-069) runs end
to end on real data and publishes a schema-valid `MacroThesis`; the §8 API layer
(D-070) exposes it over five surfaces with a published status contract.

- [x] **Thesis layer (§7)** — `MacroThesis` complete, `build_us_macro_thesis()`
      decomposed into separately-testable steps, §7.3 example objects, evidence
      tagging, **NO TRADE as a first-class outcome**.
      *DONE: `thesis_layer/` is nine modules (D-063 … D-069) with the no-trade
      path first-class (D-068). The builder composes rather than reimplements.*
- [x] **API layer (§8)** — FastAPI app; `/health`, `/thesis/us`,
      `/dashboard_data`, `/query`; SSE reasoning stream; §8.4 security; all
      routes and ports from config.
      *DONE (D-070): eight modules, 3383 lines. **The orchestration gap** — the
      builder's six required arguments — is closed by `orchestration.py`, and it
      is the one place that reads snapshot fields for a builder argument.*

**What remains is not a §8 surface but its execution model:** a process-global
cache that a multi-worker deployment silently defeats (**O-90**), and an async
stream that blocks its event loop on a synchronous build (**O-91**). Both are
recorded rather than fixed, because fixing either would invalidate the provider
mutants that certify the current behaviour — and both are Phase-4 deployment
decisions rather than Phase-3 omissions.

---

## Phase 4 — ✅ COMPLETE (4 of 4 items) — closed at D-073

**Status: closed.** Phase 4's scope (§3b of `docs/PHASE4_HANDOFF.md`) was **risk
basics (VaR) + the risk-budget hook**. VaR and the four instrument functions were
already shipped under Tier 4 (D-058–D-062); the remaining work was the **portfolio
layer that consumes them**, and it is done.

- [x] **D-058–D-062 — the four Phase-4 instrument functions** (shipped under
      Tier 4): `evaluate_drawdown_rules`, `check_rebalancing_drift`,
      `volatility_target_scaling`, `kelly_position_size` /
      `apply_fractional_kelly`. These are the primitives the risk axis composes.
- [x] **D-071 — `compute_risk_parity_weights` (§9.2, Module 17.1)**: the
      risk-budgeted weight construction, with `sample_covariance`,
      `risk_contributions` and the **correlation stress re-solve**. Solved by a
      fixed-point iteration on the risk-contribution shares; the annualisation
      leaf carries a **cross-module obligation** to agree with
      `realized_vol_simple` and the vol-target block, which is asserted by a test.
      *Evidence: hand-computed oracles, the real five-leg ETF live check, and a
      cross-check against `models/risk.py`'s own Euler decomposition.*
- [x] **D-072 — `translate_thesis_to_position` (§9.3, Module 17.4)**: the
      thesis→position **seam**. Four gates, each able only to *stop* a proposal;
      the risk budget **published as a bound and never applied**, because a risk
      share is not convertible to a notional without a covariance §9.3 does not
      supply (the naive conversion was measured **6.7x** wrong). *Evidence: 45
      tests, a 22-mutation sweep that CERTIFIES, and a live check that establishes
      the function **cannot size any live thesis today** — all four US families
      stand down at gate 1.*
- [x] **D-073 — the risk-axis hook into `thesis_layer/builder.py` (§17.4)** —
      **CLOSED.** `build_us_macro_thesis` gained
      `risk_budget_target: RiskBudgetTarget | None = None`, and a new
      `_apply_risk_axis(thesis, target)` runs after the thesis is constructed and
      before it is returned. It has **three outcomes, all disclosed**: no budget →
      §17.4 **DID NOT RUN** (stated in a warning, never silent); a translator
      **refusal** → the thesis keeps `DRAFT` and the warning says *"this is a
      REFUSAL, not a demotion"* (§17.4 demotes a thesis **too small**, which is a
      different finding); a size at or below `risk.thesis_demotion_fraction` →
      **DEMOTED to `WATCH`** with the binding constraint named. The stand-down path
      returns **before** the axis, which was **measured** to be correct — §17.4
      governs only theses that reach sizing. *Evidence: 17 tests, a 9-mutation
      sweep that CERTIFIES (8 killed, 1 honesty control), and
      `scripts/live_risk_axis_check.py` **PASSED exit 0**.*

**The finding, stated once where a reader will meet it:** §17.4's demotion bound
shipped at **0.02**, and the smallest published `fraction_of_capital` any input can
produce is **0.02941** — so the rule **could not fire**, and the test that would
have caught it **skipped**, which the suite renders as a green tick. This is the
ninth instance of the project's **declared-consumed-unreachable** class and the
third distinct vocabulary it has appeared in (a lifecycle state, after a guard and
an instrument sentinel). **Also filed as O-96:** §17.4's literal
`CANDIDATE → WATCH` names a transition whose source state **has no producer** —
nothing in the tree writes `CANDIDATE` — so the axis acts on `DRAFT`, the state
that actually reaches sizing.

**What Phase 4 hands to Phase 5, recorded rather than silently deferred:**

- **O-94** — §16.2 Q12's **exposure half** is not computed anywhere. The
  translator sizes one instrument and cannot see the book; a concentration check
  needs Module 18's factor loadings (Phase 5+). Disclosed on every result rather
  than only the ones that sized.
- **O-93** — the two no-instrument sentinels are **different strings**, and four
  documentation sites said they were the same. Corrected; the corrected fact is
  *worse* than the false one (`is_trade` returns `True` for the analytical
  sentinel).
- **O-95** — `tools/sweep_health.py` read sources with `read_bytes()` while every
  sweep reads `read_text()`, so **87% of its findings were line-ending artefacts**
  — and that noise was **masking a live leftover mutant** in `yield_curve.py`
  (O-61's fifth recurrence). Fixed; the fix is what surfaced it.
- **O-96** — `CANDIDATE` has no producer, so §17.4's literal transition is
  unreachable. The axis demotes `DRAFT` and **says so verbatim**.

---

## Decisions recorded

| ID | Title | Status |
|---|---|---|
| D-009 | Pair on latest common **date** | governing |
| D-021 | An assertion can be right about behaviour and wrong about coverage | |
| D-022 | `claims_trend_signal`'s second input declared as a raw level, used as a 4-week average | |
| D-023 | A verdict's severity must not leak into its wording | |
| D-024 | Magnitude test compares latest to the same quarter-weeks a year prior | |
| D-025 | A monthly series can have a month genuinely absent, and `[-2]` hides it | |
| D-026 | The specification names the wrong dominant uncertainty; live data proves it | |
| D-027 | A calibrated input makes a "cross-check" circular | |
| D-028 | `[-lag_months]` is not "lag_months ago"; its meaning moves with list length | |
| **D-029** | **The PPI stage gradient is a coin flip, presented as a signal** | governing |
| D-030 | A closed config vocabulary is a feature; adding a registry entry is not local | |
| D-031 | The GDP/GDI divergence is a residual, and its sign is a coin flip | governing |
| D-032 | The composite logic is sound; the licensed LEI is not reachable, so Module 7.3 ships as `leading_indicator_proxy` | |
| D-033 | A registry entry has exactly two resolution paths, and a daily series may outrun the UTC clock | |
| **D-034** | **The specification's GDP nowcast is anti-correlated with the growth it names; the corrected form ships with its measured error published rather than fitted away** | |
| **D-035** | **The accuracy record measured a quantity the model does not compute — a cumulative reconstruction against a one-quarter-ahead claim. Corrected, and the corrected measurement exposed that the adjustment is over-weighted, not inert** | **governing** |
| **D-043** | **A blocking reason that was false, found by searching instead of guessing — §21.1's "no clean free series for leveraged-loan growth" was wrong, and two functions moved from written-and-tested to validated-live** | **new, governing** |
| **D-042** | **Two probability functions with no input bounds, no calibration, and a likelihood-ratio band that was asymmetric by accident — plus `marginal_risk_contributions` found already complete while PROGRESS called it outstanding** | **new, governing** |
| **D-041** | **A function the registry blocks, and a comparison that inverts in a crisis — `risky > total * 1.2` fires when risky credit shrinks fastest. Logic ships and is tested; the live check refuses to run it** | **new, governing** |
| **D-040** | **The specification's neutral branch requires a balance sheet that never moves — 0 of 1226 weeks had a change of exactly zero. The relative band that replaces it changes today's answer** | **new, governing** |
| **D-039** | **The deficit series is negative for a deficit, and my own probe fell into it — four wrong base rates, caught only by a check that signs-verifies the series independently** | **new, governing** |
| **D-038** | **The frozen z-score denominators were wrong by two standard deviations — `fci.averages` removed, not corrected, and the mandatory NFCI cross-check moved into the model's contract** | **new, governing** |
| **D-037** | **The specification's own logic forbids the state it has a branch for — `BOTH` was dead code. Three of five inputs were inert, so it attributed widening without checking for it; the two spread changes now ship as a disclosed diagnostic** | **new, governing** |
| **D-036** | **The auction route cannot supply the input §21.1 assigns to it — `stop_through_bp` has no when-issued yield source in any of 91 columns, so it ships as MANUAL. Three further probe findings change what two other inputs mean** | **new, governing** |
| **D-046** | **Five signals are not five votes — `source_independence_count` was `0` at every call site because nothing could supply it. Typed provenance not a warning string; a count with its denominator; a census not scored by its own subject matter. The orphaned 31-member enum moved to the layer that needs it** | **new, governing** |
| **D-047** | **The conflict gate reads two measures and ignores the rest — 6 of 522 real months misclassified, on 2008-12 and 2020-03/04/05. HIGH is the base state at 89.5%, not a finding. The thresholds are degenerate below n=5, so MEDIUM is unreachable at n=3. Two of three §21.1-"blocked" inputs were live — the O-21 class for the third time. §15.19-D's ceiling is unreachable because the floor is 2 families, not 1** | **new, governing** |
| **D-052** | **A gold rule that did not run the trigger its own paragraph states, and two configured base rates no population reproduced — a live check recomputing them from raw series is the only gate that could see it** | **new, governing** |
| **D-053** | **The specification's own threshold made `stable` the base state at 79.1%, and its band and its slope were not independently choosable — the band's score-width *is* `band_pp / beta`. Separated them and the fix was a 7× config error the live check caught. Seven spec defects; a double negation that cancels; an unnamed estimand** | **new, governing** |
| **D-054** | **A de-risking ladder that could never fire, and a safety mechanism whose failure mode was silence — the specification's thresholds are fractions and its own `settings.yaml` writes percents, a 100× error that reports "no rule triggered" at a 90% drawdown. The direction was the opposite of the predicted one. Five defects; the base-state rule deliberately NOT applied; the accessor's first genuine consumer** | **new, governing** |
| **D-057** | **A placeholder the spec says to delete, a payoff contract the thesis layer silently violates, and a request that collapses at the search boundary — Module 17.3's real Kelly ships, `ev/100` ships in no form, and the failure direction is a THIRD one: toward prudence (a 100× unit error produces a SMALLER, cap-slipping number). TIER 3 COMPLETE 15/15** | **new, governing** |
| **D-067** | **A summariser that cannot say how many models saw the same thing — §16.4's `collect_all_warnings` is nine lines whose whole content is a `dict.fromkeys` de-duplication, and it fills the field the spec describes in its strongest terms ("never dropped", §7.2 step 9). **Seven defects, all measured before any code was written.** Four structural: de-duplication **destroys the count and the count IS the signal** (4 models → 1 entry — **D-046 inverted**, not repeated); the output **cannot attribute a warning to its source**; whether de-dup fires is a **producer convention nobody states** (**0 of 8** live warnings name their own model); "no warnings" and "not passed" are the **same value**. Three about what it cannot carry: **§21.4's blocked class has no route in** (a blocked input is not a `ModelResult`, so §16.4's signature cannot express it — 5 registry members, **0 routes**); **§5.4's flags never reach it** (5 of 5 absent); and **defects 1 and 6 are COUPLED** — the natural fix for 6 makes every model carry the **same string**, which is exactly what defect 1 collapses. The repair picks no side: a `WarningSummary` whose `warnings` is §16.4's list **verbatim**, plus `sources`, `unattributed` (a closed `origin` vocabulary), `model_warnings` and the two **denominators**. `unattributed` is a **parameter**, not a config lookup, because inferring it would make §21.4 **look** discharged. The sweep found a **real hole in this increment's own tests** (M5.1 survived and was not inert — closed by *adding* a test) and proved **two mutants must be killed by a different gate** (a type annotation, and a guard **no input can trip**). At close, **D-064's `M6.3` mutant was found still applied in `config.py`** while `sweep_health.py` reported 0 leftovers (**O-83**). **Lessons 98–100** | **new, governing** |
| **D-073** | **§17.4's demotion bound could never fire, and a SKIP hid it — PHASE 4 COMPLETE (4/4).** §17.4 is the only rule that carries a *risk-layer* finding back into the *thesis lifecycle*: a thesis whose `sizing_logic` clips to "near-zero" against `RiskLimits` should be demoted. The bounded word is **"near-zero"**, so it belongs in config; the implementation is `_apply_risk_axis(thesis, target)` in `thesis_layer/builder.py`, called after the thesis is built and **before it is returned**, on the live path only — the stand-down path returns first, which was **measured** correct because §17.4 governs only theses that reach sizing. **Three outcomes, all disclosed:** no budget → *"§17.4 DID NOT RUN"* (a `DRAFT` here means "not yet sized against a book", and §21.1 defines **no source** for portfolio holdings, so no honest book exists and §21.0 rule 3 forbids inventing one); a translator **refusal** → the thesis keeps `DRAFT` with *"this is a REFUSAL, not a demotion"* (§17.4 demotes a thesis **too small**, which is a different finding, and collapsing the two would publish a size as a risk verdict); a size `<= risk.thesis_demotion_fraction` → **DEMOTED to `WATCH`**, naming the binding constraint. **THE FINDING: the bound shipped at `0.02` and the smallest published `fraction_of_capital` any input can produce is `0.02941` — so the rule was declared, consumed, and structurally incapable of firing, and the test that would have caught it SKIPPED, which a suite renders as a green tick.** Measured, the reachable set is **six discrete values** — `0.02941 · 0.03472 · 0.042735 · 0.069445 · 0.125 · 0.15` — and it is a **set, not an interval**, because full Kelly is the argmax of expected log growth and for a two-branch distribution with a positive edge that objective is **monotone in `f`**, so `f*` pins at the search-domain edge and the *position cap* produces the number; only asymmetric branch sets land inside. `0.02941` is full `f*` `0.05882` over `kelly.fractional_divisor` `2.0`. The bound now carries **three** constraints and the third is the find: `> 0`, `< max_position_fraction` (0.15), **`>= the smallest reachable size`**; `0.03` satisfies all three, inside `[0.02941, 0.15)`. **The remedy is not a better number but a live check that re-derives the set** — `scripts/live_risk_axis_check.py` recomputes it and fails if the bound stops splitting it. **This is the ninth instance of the declared-consumed-unreachable class (D-045/046/048, O-53, O-27, twice in D-072) and the THIRD distinct vocabulary** — a lifecycle state, after a guard and an instrument sentinel. **Also: §17.4's literal `CANDIDATE → WATCH` names a transition whose SOURCE STATE HAS NO PRODUCER** — nothing in the tree writes `CANDIDATE` (promotion is a human act by design) — so the axis acts on `DRAFT`, the state that actually reaches sizing; recorded as **O-96** rather than silently reinterpreted, because the two readings differ downstream. **THE SWEEP REFUSED TO CERTIFY ON ITS FIRST RUN — 8 applied / 6 killed / 2 survived, and BOTH survivors were real test gaps:** `M1.2` moved the axis's **local** bound while the tests asserted on the **config leaf** (both "the bound", neither touching the other — O-29's mis-target class one level up), fixed by `test_the_bound_the_axis_actually_uses_splits_the_reachable_set` driving the **outcome**; `M4.1` changed `<=` to `<` and survived because every test landed *below* the bound, fixed by `test_the_demotion_fires_at_the_boundary_not_only_below_it`. Both closed by **adding tests, never by exempting a mutant**. Second run **9/8/1 CERTIFIES** (the survivor is the M5 honesty control). **Two architectural guards were amended, not deleted (D-067), each with a written reason** — the Kelly guard in `test_integrity_gates.py` was **strengthened** (forbids primitives, **enumerates the permitted surface**, adds a behavioural receipt `test_section_25_gate_precedes_kelly_on_the_translation_path`), and `test_builder_strictness.py`'s prohibition on `macro_engine.portfolio` was removed because **the §17.4 hook REQUIRES that import** — a guard forbidding the wiring the spec mandates is a guard against the spec. Gates at close: ruff 218 = format **218** = mypy **218** (D-035 parity), suite **2329 passed / 1 skipped**, live check **PASSED exit 0**, `sweep_health.py` **40 sweeps, 0 failures, 0 leftovers** (2 inherited `[FAIL]`s — `mutation_regime.py` M8d, `mutation_lei_proxy.py` M8e; `mutation_risk_axis.py` reads `[ok]`). Opens **O-96**. 17 tests + a 9-mutation sweep certifying 8/1 + a live check at exit 0. **Lessons 5bp, 5bq, 5br, 5bs** | **new, governing** |
| **D-072** | **The thesis→position seam, and the nine-times-wrong naive conversion — `translate_thesis_to_position` (§9.3, Module 17.4).** Four gates, each able only to **stop** a proposal, never to enlarge one. The risk budget is **published as a bound and never applied**, because a risk share is not convertible to a notional without a covariance §9.3 does not supply — and the naive conversion the spec invites was **measured 6.7x wrong**. All four live US families **stand down at gate 1**, so the function **cannot size any live thesis today**, which is a finding about the system rather than about the function. **`portfolio_volatility_two_asset` and `marginal_risk_contributions` (§20.12C) closed here too** — the latter was found **already complete** while PROGRESS called it outstanding (D-042). **O-93** is the documentation defect this increment discovered: the two no-instrument sentinels are **different strings**, four doc sites said they were the same, and three tests written *from the docs* failed on first run; the corrected fact is **worse** than the false one (`TradeIdea.is_trade` returns **`True`** for the analytical sentinel, and `ProductionUniverse.permits` returns `False` for it while returning `True` for `"NONE"`, so each check alone is insufficient at gate 1 and both are now enforced and pinned by name). **O-95** is its incident: `tools/sweep_health.py` read sources with `read_bytes()` while every sweep reads `read_text()`, so **87% of its findings were line-ending artefacts** — and that noise was **masking a real leftover mutant** in `yield_curve.py` (O-61's fifth recurrence), where the false positive and the true positive were **the same line**. Opens **O-93**, **O-94**, **O-95**. 45 tests + a 22-mutation sweep that CERTIFIES + a live check. **Lessons 5bl, 5bm, 5bn, 5bo** | **new, governing** |
| **D-071** | **The risk-budgeted weight construction — `compute_risk_parity_weights` (§9.2, Module 17.1).** Weight construction from risk-contribution shares, with `sample_covariance`, `risk_contributions` and a **correlation stress re-solve**, solved by **fixed-point iteration** on the contribution shares. The annualisation leaf carries a **cross-module obligation** — it must agree with `realized_vol_simple` and the vol-target block — asserted by a test rather than left to convention, because a single annualisation constant duplicated in three modules is exactly the kind of drift the project keeps finding. *Evidence: hand-computed oracles, a real five-leg ETF live check, and a cross-check against `models/risk.py`'s own Euler decomposition.* **Also closed the O-93 documentation defect's first half** — see D-072. | **new, governing** |
| **D-070** | **The §8 API layer, and a mutation sweep that certified a test selection it never ran — PHASE 3 COMPLETE. `build_us_macro_thesis` takes six required arguments and §8.2's sample supplies a snapshot alone (`TypeError: missing 6 required argument(s)`), so the derivation became its own module (`orchestration.py`, 1043 lines) and the gap is one auditable file. **Refusal, not defaulting**: 502 for missing data, 501 for an unimplemented country, 422 for a bad `thesis_type`, 500 reserved for real bugs, and **200 + WATCH for a stand-down** — because §16.3 forbids a fabricated no-trade, which would be indistinguishable from a genuine 'no edge'. **Three measured unit traps in the labor leg**, the dangerous one being `jolts_quits` = `1.9`, a rate in percent that **passes the model's own `ge=0, le=100` validator** while needing a percentile of its trailing range. **The increment's own defect:** `_yoy_percent` accepted 'the latest observation at or before the anniversary', which SUCCEEDS for a point **31 days away** — the adjacent month — and published the ratio under the words 'year-over-year'; fixed by `api.yoy_match_tolerance_days` (5), whose whole purpose is that it **excludes the adjacent month**. **§8.4's pairing is enforced at load time**: a permissive CORS list with a non-loopback bind is refused, because the service has no authentication and the bind address IS the access control. **THE SWEEP REFUSED TO CERTIFY THREE TIMES.** First run 42/31/11 — ten survivors with no proof, each diagnosed by APPLYING it: three were **real lies the tests missed** (M8.6 made the stream name three gates when one fired; M10.2's version guard compared the constant to itself; M9.5's loopback guard was a tautology under the shipped config), five were **genuine coverage gaps** closed by writing `test_snapshot_provider.py` (15 tests), and two were **proven inert with a traced mechanism** (M1.5's second overlapping guard; M4.3's second independent guard, traced to `gdp_nowcast.py:442`). Second run 42/36/6 — and M9.1/M9.2/M9.3 survived AGAIN on a tree where each is measurably killed. **That contradiction was the defect: `PYTEST_TARGETS` declared four test files, `run_pytest` ran three, and `check_tests_collect` validated the declaration the run never used — a GREEN GATE CERTIFIED A SELECTION NOBODY EXECUTED, and the resulting survivors looked exactly like inert mutants.** Fixed structurally: both functions splat one constant, plus a new gate that parses the source and refuses to run if either re-inlines a path (verified by planting the regression). **O-83's remedy is implemented**: `sweep_health.py` scans the whole tree for mutant SHAPES with no catalogue, verified live by catching an in-flight `# MUTANT`. Third run **42/39/3 — CERTIFIES**: two measured-inert (`M1.5`, `M4.3`, each with a traced mechanism) and the honesty control. **The live check then found three more defects, and all three were in the CHECK, not the service**: (1) `GET /health?deep=true` returned a **404 from a registered route** — this environment exports `HTTP_PROXY`, `httpx` honours it by default, and a forward proxy must use the **absolute-URI** request form (RFC 7230 §5.3.2), which uvicorn then reads as the path; the intermittency was that the *first* request on a fresh connection survived while a *reused keep-alive* one did not, and it was found by tapping the socket and printing the **request line** rather than the status code; (2) the CORS preflight 400'd because the check hardcoded `:3000` while the config allows `:8000` — **Starlette was right and the check was wrong**; (3) the stream assertion failed on a **correct** stream because it searched for a *spacing* the stream never promised (lesson 5bf applied to the check). Fixed, guarded structurally (`trust_env=False` enforced by an `ast` read; the proxy variables are printed so runs stay reproducible), and the live check now **passes end to end at exit 0**. The same root cause is present in two PRODUCTION clients (`openbb_client.py:91`, `catalysts.py:213` both default to `trust_env=True`; the OpenBB client's mounts against `127.0.0.1:6900` are HTTPProxy) — filed as **O-92** rather than fixed, because it changes data-layer network behaviour this increment did not touch and would have invalidated the sweep certifying it. Opens **O-90** (the cache is process-global), **O-91** (the async stream blocks its event loop) and **O-92** (the production proxy exposure). 125 tests + a 42-mutation sweep certifying 39/3 + a live uvicorn check at exit 0 | **new, governing** |
| **D-069** | **The seam function, and the defect that only a live check could see — Section 7.2/§16.2's `build_us_macro_thesis` appears on BOTH the Tier 4 and the Phase 3 checklists, and that overlap **is** the phase seam: the models layer stops producing numbers and the thesis layer starts making claims. **TIER 4 COMPLETE 11/11.** **Nine measured divergences from §16.2's sample**, including a correction of my own carried-in premise: the sample omits **zero** required `MacroThesis` fields (the "six" belonged to §16.4's `no_trade_thesis` sample — D-068's). The substantive finding is a **plumbing gap measured rather than assumed**: **no snapshot-fed helper exists** for `inflation_breadth_score` or `labor_tightness_score` (the census of snapshot-taking helpers is `[]` for `inflation_nowcast`, `labor_synthesis`, `regime`, `national_accounts`), so Q1's three reads became a **PARAMETER** (`EconomyReads`, a frozen dataclass) rather than a faked transform — and `MarketPricingGap` is **not** a `ModelResult`, so §16.2's sample fails pydantic validation, bridged by an explicit `_as_signal` adapter. The three no-trade gates fire in order **Q6 → Q7 → Q8**, each routing to a helper that **owns its own trigger literal** rather than re-deriving it. **THE INCREMENT'S REAL DEFECT WAS AN INTERACTION DEFECT AND THE LIVE CHECK FOUND IT:** `_render` collected **no warnings at all**, so **every stand-down silently dropped the model warnings AND §22.5's market-path contamination disclosure** — printed `contaminated=0 proxy=0` on a path where the contaminated branch had definitely been taken, and `warnings=1` (the trigger line alone). The repair renders first and **APPENDS** the warnings behind the trigger line, because `render_no_trade_thesis` *owns* `warnings` and refuses to be handed it; measured after, **`warnings=13`, `contaminated=1 proxy=1`**. **No unit fixture could have found this**: every offline test asserted the trigger line was *present*, and it was — the defect was that it was **ALONE**. **The sweep refused to certify on its first run — SIX survivors, every one a REAL test gap**, including **M8, the very defect just fixed**, whose regression test lived **only in the deselected live file**; all six closed by **ADDING** tests rather than exempting mutants. **The second run then killed the honesty control**, because a strictness test asserted the fallback's **literal source text** rather than its meaning — rewritten to pin **order and structure via `ast.parse`**. Two mutants were also **mis-aimed** and retargeted (`M12`'s anchor was in `_render` not `_direction_for`; `M13`'s replacement was a behavioural no-op). **It corrected a FALSE published gate row:** D-068 claimed `mypy --strict` was clean at 176 files while **29 errors** sat in D-068's own files — all now fixed, so the gate is **true at 182**. Opens **O-87** (`select_instrument` publishes **two** value shapes — a dict on the executable routes, a bare **sentinel string** on the refused ones — while its own `_selection_value` declares *"always returns a dict value"*; **that sibling claim is wrong**), **O-88** (the false gate row), and **O-89**. 78 tests (51 + 21 static + 6 live), an 18-mutation sweep (**17 killed, 1 survivor = the control**, exit 0), and a pulled live check. **Lessons 5be, 5bf** | **new, governing** |
| **D-066** | **A fall-through that invents disagreement — §16.4 Q7 derives `direction` from one `if` and a bare `else`, so every outcome the condition cannot express becomes `"contradicts"`, while the schema's own vocabulary has three members. Measured: a **dict**, **`0.0`**, **`True`**, and a non-zero value against a **zero gap** all became an *active claim of opposition* — D-056's false confidence. **O-69's full extent: six `source_model` labels across three spec locations, ONE common, and `curve_slope` is never a parameter** — so labels are derived from the model actually read. Plus: `source_family` never populated (the independence count made *unreachable*, not wrong), `detail` = raw interpretation, and a return type that cannot carry Q7's second half. The increment's **config leaf was correctly REFUSED** by the numeric-accessor infrastructure gate, and its **own live check hand-rolled the growth leg** into a −17.57% gap off a **2036** CBO projection. **Lesson 95** | **new, governing** |
| **D-064** | **A "validated" declaration that validates nothing — §16.4's `payoff_unit: Literal["fraction_of_capital"] = Field(description=...)` has a one-member `Literal` and no `default=`, which pydantic treats as OPTIONAL, so a `bp_pnl_proxy` distribution was accepted and silently relabelled as fraction-of-capital, entering the Kelly arithmetic in the wrong units and with no error (closes **O-50**/silences **O-51**). The repair makes the field REQUIRED, widens the vocabulary to `KellyPayoffUnit`, and adds a named refusal. Three further §16.4 defects, and the LIVE CHECK found a fifth: the distribution is DIRECTION-BLIND — a +1.0% and a −1.0% gap give byte-identical payoffs and probabilities (**O-71**), invisible to every fixture because all of them used `+1.0`. The shared `check_anchor_landings` was MANUFACTURING FINDINGS (owner resolved by `line.startswith(("def ", "class "))`, true of a comment) — fixed with `ast.parse` + `end_lineno`. The sweep's honesty control was a NO-OP (`old == new`). O-61 recurred live a third time. RECOVERED increment: the interrupted session wrote the code, the tests, the config and `sweep_health.py`'s extension and NO record of any kind** | **new, governing** |
| **D-065** | **A catalyst with no date is not a catalyst — §16.4 returns THREE HARDCODED STRINGS** (`"Next CPI release (FRED release/dates)"`), naming the source and omitting the schedule, and §16.4 says it **MUST** pull FRED `release/dates` + federalreserve.gov and **NEVER** a third-party calendar. The implementation returns **dated** entries from those two sources, and doing so exposed **five source defects**, all measured live: FRED's `ptic` is a **pagination total, not a count** (2806 vs a 50-row page); the unfiltered FRED path is **one request per calendar day** and times out; FRED's release **101 "FOMC Press Release" answers for EVERY calendar day** (41/41), so trusting it reports the next FOMC as *tomorrow forever* — hence FOMC comes from the Fed, as §16.4 says; **flattening the Fed's HTML to text invents phantom meetings** (55 vs 53) from a trailing 2028 note, so the parse reads the structured `fomc-meeting__*` cells; and the endpoint **drops urllib/aiohttp by TLS fingerprint** while answering **httpx/HTTP-1.1** — which is *why* `obb.economy.calendar` times out on this host at all. Two defects in this increment's own code: a **false-positive warning** on correct data, and a horizon that bounded the **request** but not the **result**. The sweep **refused to certify** its first run and the two survivors it named led to the implementation defect. **Lesson 94** | **new, governing** |
| **D-063** | **The specification's thesis builder cannot execute its own Q8 — §20.15 compares `inflation.value < 0` against a `dict`, because `inflation_convergence_classifier` publishes `InflationConvergenceVerdict(...).model_dump()`. Reproduced on REAL data. Three further defects: `growth` declared and never read; the fallback sentence SATISFIES the LTCM gate it says is unmet (measured — `TradeIdea` accepts "no falsifier was found"); and the model §20.15 names is DIRECTION-BLIND, so it cannot express the "reacceleration" attributed to it. Return type becomes `InvalidationAssessment` so the gate becomes load-bearing. First thesis-layer function** | **new, governing** |
| **D-062** | **A sign the specification never checks — §20.12 defaults `correlation_stressed` to the literal `0.9`, which exceeds the *normal* correlation of all 8 real US cross-market pairs measured, so the published `hedge_degradation` is negative for 8 of 8: the spec asserts universally and silently that the hedge IMPROVES in a crisis. A new failure direction — toward FALSE REASSURANCE. The seam with `select_instrument` CANNOT be closed (no `ThesisType` names a cross-market RV). MODULE 15 COMPLETE** | **new, governing** |
| **D-061** | **The O-62 repair — and the audit's diagnosis was wrong in the way that matters: `C1d` was a MIS-TARGET (8 occurrences, `str.replace` rewrote `CreditTrendBaseRates` while the model reads `CreditSpreadBaseRates`), not the "real missing test" it was recorded as, and `M4a`/`M5e` were anchors D-043 had staled. Executing the gate the file lacked is what showed it. Also found: every sweep in the repo was NEWLINE-LOSSY — `write_text` translated LF to CRLF, so a sweep silently rewrote its target and `git status` reported whole-file modifications with no content, destroying the clean-tree precondition** | **new, governing** |
| **D-056** | **A constraint that is inert exactly where the risk is — §20.13's whole enforcement is `min(scaled, max_leverage)`, a one-sided upper bound, and four of the five limits declared beside it had zero references anywhere. The repair for the inert four is disclosure, not enforcement** | **new, governing** |
| **D-055** | **A drift check that could not see an instrument it was not told about — all four spec defects are the same shape: every input it is not told about is a confident zero, so a book drifted entirely into *unbudgeted* positions reports `balanced`. The failure direction is the opposite of D-054's (false confidence, not silence). The first boundary fixture did not sit on the boundary (`0.99…98` vs `0.10`) and the `>`→`>=` mutant survived. First increment to populate `_EXPECTED_INERT` with proven entries, of deliberately *different strength*; `M10.1` was INERT BY ANCHORING — a shadowed insertion, so the code under test never changed** | **new, governing** |

---

## The generalised rules this project now enforces

1. **Pairing, nine axes** — common *date*, common *window* and *right
   window*, common *span*, common *parameter*, common *cadence*, (D-029) a flag
   delivered with its **base rate** and an enumerated field typed as `Literal`,
   (D-031) a common **unit**, and (D-035) a common **estimand** — a backtest must
   reconstruct the function's declared horizon, not its maximum available
   information.
2. **No literals in models** — every threshold from config via a `.property`.
3. **No hardcoded confidence** — `compute_confidence()` is the only producer.
4. **`extra="forbid"`** on every input model; **`Literal`** for every enumerated
   field where a typo would fall through to a permissive branch (D-029).
5. **A cross-check must not share an input with the thing it checks** (D-027).
6. **A test that cannot fail is not a test** — mutation-test every guard. A
   survivor is one of **four** things: a weak test, an **inert** mutation, a
   **broken** mutation, or a **mis-targeted** one. Only the first is a test gap
   (D-031, D-040). **D-046 adds the failure mode behind two of the four:** an
   invariance test that compares **a function to itself** cannot detect a change
   to a constant both sides read — pin the **absolute** value instead.
7. **A test that reads its expectation from the same config the code reads
   cannot detect a literal** — break the symmetry by patching the config to a
   value the literal cannot produce (D-031). **D-035 extends this to a swap:**
   an assertion that reads both sides from the same accessor moves both when the
   accessor is swapped, so the fixture must be a synthetic record whose leaves
   are **all distinct**.
8. **A boundary fixture is built by addition, never subtraction** (D-029).
9. **Beyond a live registry entry lie the snapshot schema and the verification
   record** — the entry alone is silently dropped (D-030). **D-047 widens this
   to three states, all of which must be satisfied for a *different* layer:**
   the route (probed), the schema resolution (**exactly two** shapes — a real
   `MacroDataSnapshot` field, or `not_a_snapshot_field: true`), and the
   verification record. A new entry that satisfies the first and neither of the
   others leaves **every model-layer gate green** — the registry is read by the
   *data layer*, so only the data layer's tests can see it. And the
   `verified_value` in that record is **written by hand, read by no code, and
   recomputed by no consumer** — the one number in the tree with no enforcement
   mechanism, which is why two were written from memory in D-047 and both were
   wrong. **Probe first, transcribe second.**
10. **A mutation targeting a repeated string must be scoped to its block** — a
    bare token appearing elsewhere in the module may absorb the edit (D-031).
11. **A config surface serving two consumers must let each declare which it is**
    — a default that fits one silently misfits the other, and it is the *next*
    entry that breaks, not the ones already there (D-033).
12. **A series that is monthly, or daily, is not thereby regular** — a declared
    per-series tolerance beats a code-wide exception, because the exception
    cannot tell a legitimate clock artifact from a broken mapping (D-033).
13. **The full suite is its own gate** — an increment's own tests, mutation
    sweep and live check can all be green while it breaks a contract elsewhere;
    run the full suite after every registry or schema change, not only after
    code changes (D-033).
14. **A blocked input is never substituted** — the composite logic may be kept
    under a name that does not claim the blocked product, and the block stays
    recorded so the substitution cannot happen silently later (D-032).
15. **A backtest must reconstruct the function's declared horizon, not its
    maximum available information** — a cumulative reconstruction measured
    against a one-quarter-ahead claim is a different estimand, and it is always
    the flattering one, because more information looks like more skill (D-035).
16. **A recomputation assertion's tolerance is a claim about the estimand, not a
    convenience knob** — when a live check fails by more than its tolerance, ask
    which side is wrong before adjusting the number, especially when the
    tolerance's own message says not to (D-035).
17. **A trap hit twice in one session needs a test, not a docstring** — the
    field-shadows-its-own-property collision has now occurred five times; a
    docstring warning was already sitting eight lines above the fifth (D-035).
18. **A mutation is only killed by a fixture in which the mutation changes the
    outcome** — patching a value is not enough, the fixture must place the
    decision on the boundary the patch moves; and a test that supplies a value
    *explicitly* cannot test the default that supplies it. Three sweeps took the
    count 35 → 37 → 39, each step a different kind of blindness (D-035).
19. **A guard that cannot survive its own interruption is not a guard** — a
    mutation sweep killed mid-run leaves the mutated file on disk, and the next
    run adopts it as the baseline. Detect by `old` absent *and* `new` present;
    heal by inverting the pair; run the sweep under `try/finally` (D-035).
20. **A contract argument nobody can supply is decorative** — `source_independence_count`
    was in `ConfidenceInputs`, documented, consumed by the confidence rule, and
    hardcoded to `0` at every call site for the life of the project, because no
    function could produce a non-zero value. Grep a contract parameter for a
    **call site that supplies a non-zero value**, not merely for uses (D-046).
21. **Provenance is typed data, not prose** — a structured fact placed in a
    free-text field (`warnings`) is destroyed by any downstream reformatting,
    silently and without an error, and can be forged by hand. A field that must
    survive rewriting belongs in a field (D-046).
22. **A count without a denominator is not a measurement** — report the untagged
    remainder, because "unknown provenance" and "no independence" are different
    claims and must not be pooled (D-046).
23. **A summariser must not be scored by its own output** — a census counting
    independent families must not take its own confidence from the count it just
    produced. It is the D-027 circularity class, and it inverts the ranking:
    nine genuinely independent sources would out-score the same census finding
    five redundant ones (D-046).
24. **A statistic whose base rate is its own modal output is not reporting a
    finding** — `HIGH` fires 89.5% of the time, so the classifier's most
    confident-looking verdict is the absence of news. When a rule's modal answer
    is one particular value, that value's **frequency must travel with it**; a
    label alone reads as a discovery (D-029's base-rate rule, reached again from
    a different direction — D-047).
25. **A gate that reads two fields of a set must justify excluding the rest** —
    the conflict gate asked whether `headline` and `core` disagreed and never
    looked at the other four measures, so a 5–1 split with one dissenter passed
    as agreement. Test the **losing side against the whole set**, not a
    privileged pair against itself (D-047).
26. **A threshold is only meaningful relative to the granularity of what it
    scores** — `>= 0.8` on a set of 3 attainable fractions is a unanimity rule
    wearing a percentage's clothes, and `0.25` of a set of 3 fires on one
    dissenter. Before pinning a share, enumerate the values it can actually take
    at every admissible `n`, and **disclose the degeneracy** rather than
    retuning the number to hide it (D-047).
27. **A config value nothing reads is undetectable by any test that reads config**
    — `confidence_ceiling_by_independent_families` said `3` while the constants
    it was supposed to mirror saturated at `5`. No test failed, because the only
    reader was the code that had already stopped using it. **Make the value
    derive itself from its source and raise on disagreement**, so a future drift
    is a startup error rather than a dead comment (D-047).
28. **A comment asserting that a condition is load-bearing must be tested as
    hard as the condition** — the all-flat guard was described in-source as
    protecting the division, and mutation proved it protected nothing: `losing`
    is `0` when nothing moves, and `0 >= share * total` is already `False`. The
    comment was the defect. **A stated rationale is a claim, and claims get
    mutations** (D-047).
29. **A mutation anchored on a bare scalar will hit the wrong setting** — the
    ceiling mutation keyed on `      value: 5`, which occurs four times in
    `settings.yaml`, including under `credit_spread`; it mutated the *wrong
    config entry* and survived for that reason, not because the test was weak.
    **Anchor on the key line as well as the value**, and when a mutation
    survives, prove *what it actually changed* before concluding the test is
    thin (D-031's rule 10, generalised to YAML — D-047).
30. **A sweep must prove its mutations applied where it intended, before it
    reports anything.** Six mutations in D-048's table were reported as
    survivors that looked like weak tests. They were rewriting the wrong
    *function*: `country="us",`, `source_independence_count=0,`,
    `depends_on_unobservable=True,` and the `measured` property body each occur
    **twice** in their file, and `str.replace(old, new, 1)` silently takes the
    first occurrence. The file changes, so the mutation looks applied; the tests
    pass, because they never exercised the mutated path; and the conclusion —
    "the suite is weak" — is drawn about code nobody touched. **A mis-target and
    a weak test produce identical output and have opposite remedies.** Count
    occurrences and refuse to run on anything ambiguous (D-048).
31. **A series' observation count is not its measurement window.** The live
    check's gap-free assertion failed on its first run and found that
    `TRESEGGBM052N` reports **843 observations but only 837 are monthly** — the
    first six are annual. Since every threshold here is a change over a *named
    number of months*, a "3-month change" across that prefix spans years.
    Indonesia is worse: 700 observations, 668 monthly. Re-measuring over the
    monthly span moved the base rates from 10.8%/8.2% to **10.6%/7.8%**. Verify
    the cadence over the window the threshold names, and disclose what was
    excluded (D-048; the out-of-sample case of D-025).
32. **An equivalent mutation is a finding, not a gap.** The `or 0` rewrite
    cannot be killed, and the reason is arithmetic: for `t <= 0`, `(x or 0.0) < t`
    and `x is not None and x < t` agree for **every** `x`. They diverge only for
    `t > 0`, and both thresholds are reserves-depletion thresholds. The right
    response is not to delete the mutation but to **record the proof and pin the
    contingency** — a test now asserts no threshold can cross zero, so if one
    ever does, the entry becomes wrong and the survivor must be killed (D-048).

33. **A recalled number is not a fetched one, and the registry is where that
    gets expensive.** Two of the three `verified_value`s written for the
    `trilemma_reserves_*` entries were **wrong** (GB written as `93221.49`,
    actual `169355.66`; KR `411301.2` vs actual `421968.56`) because they were
    written from recollection rather than read from the provider in the same
    session. Neither was absurd and nothing raised an error — §21.0's failure
    mode reproduced inside the very record set §21.0 protects. A
    `verified_value` must be **fetched and written in the same breath**; two of
    three being wrong is not an acceptable rate for a field whose name promises
    verification (D-048 amendment).

34. **An exclusion's SIZE does not describe its STRUCTURE.** The cadence note
    said Indonesia's excluded prefix was "32 annual observations" and that GB/KR's
    was "6". The counts were right; the shapes were not. GB/KR change cadence
    **once** (7 annual Decembers, then monthly); Indonesia changes **twice**
    (16 annual 1950-12..1964-12, then a continuous quarterly block
    1965-03..1968-12, then monthly). One cadence change at one date was the
    assumption both descriptions invited, and it mis-dates Indonesia's usable
    window by four years. **State the shape, not just the size** (D-048
    amendment).

35. **A parameter can sit exactly at the point where the data stops supporting
    it.** `inversion_probability_adjustment` multiplies a depth factor by a
    duration factor, so it *assumes* both are monotone in the outcome. Measured:
    **depth is monotone** (0.412 / 0.417 / 0.552 / 0.857) and **duration is
    hump-shaped** (0.250 / 0.286 / 0.412 / **0.769** / 0.520). The configured
    26-week cap is the **26-52 week bucket boundary** — the peak. So the mechanism
    never reaches the region where its assumption fails, and **the cap is by far
    the best choice available for keeping the mechanism self-consistent**: it
    cannot be "fixed" by moving it, because moving it exposes the contradiction.
    The correct response is to *state* it — the cap is disclosed on every
    saturated output and the finding is an open calibration item (D-049). **A
    mechanism can be arithmetically sound, empirically anchored, and resting on an
    assumption its own data contradicts — invisibly, because the parameter
    intercepts the evidence.**

36. **Validate a shared definition on a case that the code under test does NOT
    exercise.** The live check's forward window was `t .. t+11` instead of
    `t+1 .. t+12`. On the number the function actually consumes — the inverted
    rate — the two windows agree to **0.0001**; on the unconditional rate they
    differ by a **full percentage point** (0.2095 vs 0.2196). A check that
    validated only the consumed rate would have **passed with the wrong window in
    it**, and every future function reading the same table would inherit the
    error. It was caught because the check reconciles all three rates, including
    two nothing uses yet (D-049). **The un-used cases are the ones that catch a
    definition error, because the used case is the one whose errors were already
    tuned away.**

37. **A gate can make its own thresholds inert, and only a mutation sweep will
    say so.** `four_pillar_scorecard` tests `CONFLICTED` first, and `CONFLICTED`
    consumes every opposed read. A non-opposed read has all its non-neutral
    pillars pointing the same way, so `max(up, down) == n` and therefore
    `dissent = n - max(up, down) == 0` — **always**. The consequence is that
    `dissent <= 0`, `<= 1` and `<= 2` are the *same predicate* on every reachable
    input: the MEDIUM dissent ceiling cannot bind, and the `LOW` "weak agreement"
    branch is **unreachable by construction**. Three mutants proved it by
    surviving, and no amount of reading would have: each gate is individually
    correct, and the defect is in their *composition*. **When a threshold is a
    comparison against a quantity, establish the quantity's reachable range at
    that point in the control flow — not its type, and not its range in general**
    (D-050).

38. **An accessor test that asserts today's value cannot tell a live config read
    from a hardcoded copy of the same number.** Four `ScorecardSettings`
    accessors were replaced by `return 0` / `return 1` / `return 3` / `return 2`
    — literally the values they already returned — with the entire suite green.
    Every existing test asserted the *value*, and the value was identical, so the
    "no hardcoded values" rule (§22.8) was rendered toothless in exactly the
    component whose job is to hold the tunable. The fix that works: assert
    against a **perturbed** settings object, so the read is exercised rather than
    the number. **A test that passes for the literal and for the read is not
    testing the read** (D-050).

39. **The input-space share and the historical share are different claims, and
    they can disagree in either direction.** `CONFLICTED` is **61.7%** of the
    admissible four-pillar space (measured by enumerating 567 configurations) and
    **66.2%** of 761 real monthly readings. The naive expectation is that real
    correlation *reduces* the share; it raises it, because correlation among
    pillars is not the same as agreement. An earlier draft of this document
    predicted the opposite in prose. **Report both numbers on the output, and
    never let a measured share from one domain stand in for the other** (D-050;
    cf. D-047's 89.5%).

40. **A sweep must verify that its tests are COLLECTED, not merely that they were
    named.** The first `mutation_convergence.py` listed `tests/test_config.py`,
    a path that does not exist. `pytest` exits **4** for a missing path, and
    "non-zero means killed" counted it as a kill — the run reported **56 of 56
    mutations killed**, including a control that was semantically identical to
    the shipped code and could not fail any test. The headline was an artefact of
    the harness. `check_tests_collect()` now gates the run, and exit 4 is no
    longer a kill. **A number produced by an error exit code is not a mutation
    score**, and a deliberately-unfailable control mutation is what exposes it —
    without the control, a perfect score is indistinguishable from a broken
    harness (D-051; cf. D-048's `check_targets`, which does the same job for the
    mutation targets).

41. **When two functions implement the same predicate, one function's REPAIR is a
    defect report against the other.** D-051's live check cross-checks
    `classify_convergence` against `four_pillar_scorecard` on the ground that
    they must agree. The assertion failed on **95 of 761 real months**, and the
    cause was the already-closed D-050 module — its census counted neutral
    pillars, so one directional pillar plus three neutrals read `HIGH` where the
    same directional content alone reads `LOW`: the exact defect D-051 had just
    found in its own first draft. D-050's suite could not see it, because every
    family-count test there used an all-directional read, and the defect is only
    reachable with a neutral pillar present. **A cross-check between two
    implementations is worth more than either one's test suite**, because it
    tests the *agreement* rather than the output, and the agreement is what a
    shared misconception breaks (D-051).

42. **A target can become ambiguous in a module you did not edit.** Adding
    `ConvergenceSettings` beside `ScorecardSettings` in `config.py` duplicated
    five validator and accessor bodies verbatim, so targets in the *scorecard*
    sweep silently became ambiguous. Both sweeps' `check_targets` refused to run.
    The rule is not "check your new targets" but **"re-run every sweep whose
    file you touched"** — a sibling class can invalidate a target it never
    mentions (D-051).

43. **A test written from a mutation's REPLACEMENT string guards the mutation, not
    the contract.** Re-running the D-051 sweep at record-set close,
    `check_targets` reported `M8.5`'s target **ABSENT**. The mutation's `old` and
    `new` arguments had been **transposed** since it was written, so the sweep
    was checking that the *mutated* literal appeared in the shipped source — it
    never applied, and the mutation named for `inputs_used` had never run. With
    the arguments corrected, `M8.5` **survived**, and the reason is the point: the
    test that should have killed it asserted
    `result.inputs_used == ["signal[0]", ...]` — **the mutant's output** — while
    the shipped code returns the fixture names `["s0", ...]`. The test **failed
    on the real code and passed only under the mutation**, so it was not a weak
    test but an *inverted* one: it encoded the defect as the expectation.
    **Two lessons, and the second is the generalisable one.** (a) Assert against
    the fixture's own values, never against a literal copied from a mutation's
    replacement string. (b) A transposed `old`/`new` is invisible to every gate
    except `check_targets`, which is why that gate must run **immediately before
    each sweep** and not once at authoring time — the defect surfaced only when
    the sweep was re-run after the records were written (D-051; cf. lesson 40,
    which is the same failure mode in the test *selection* rather than the target
    *text*).

44. **A mutation can be inert because it rewrites a NAME and not a VALUE — the
    third kind.** D-050 named two: *threshold* inertness (the threshold differs
    only on an input the function cannot reach) and *composition* inertness (an
    earlier gate consumes every input on which the mutant would differ). `M9.2`
    is neither. It re-spells a key in the published `value` dict — `M9.2 published
    value key \`long_duration_growth_equities\` altered` — and survives because the
    consumer of that key reads it by a second alias, so **the rename changes what
    the key is called and nothing about what the function returns**. Proving it
    required reading the three branches out of the source rather than reasoning
    about reachability, which is exactly the difference: threshold and composition
    inertness are facts about the *input domain*, and this one is a fact about the
    *namespace*. **Before calling a survivor a weak test, establish which of the
    three it is; the remedies are not interchangeable** (D-052).

45. **A warned condition is not covered until its marker is unique.** `M10.3` —
    "the indeterminate warning is not emitted" — survived with a warning-coverage
    guard in place, because the guard matched substrings and `"below the"` occurred
    in **two** different branch texts. Deleting one branch left the guard matching
    the other, so a coverage check reported coverage of a branch that was gone.
    **This is a wording collision masquerading as a test**, and it is invisible in
    both directions: the guard is green either way and no test names the
    duplicate. The repair is to make each branch's marker **mutually
    non-colliding** and to add a guard asserting every emitted warning matches
    **exactly one** marker — a *partition*, not a *hit*. Applies to every
    `assert any(marker in w for …)` coverage check in this project (D-052).

46. **An exact identity is not a cross-check; it is a proof that a derivation is
    not a proxy.** `cross_asset_transmission` derives the real yield from
    `DGS10 − T10YIE`, and the tempting cross-check is to compare the derived
    series against observed `DFII10`. The identity holds to **0.000000** over
    5 931 observations, so that comparison **cannot fail** and carries no
    independent content — it is D-027's circularity in a new costume: the two
    sides share an input. The identity is still worth computing, for the opposite
    reason: it proves the derived leg is a **restatement rather than a proxy**,
    which is a claim about the derivation that nothing else in the suite
    establishes. **When a relation is exact, it is evidence for the derivation and
    useless as a cross-check; a real cross-check needs a disjoint input** — here
    `inversion_probability_adjustment` (D-049), which shares no series with it
    (D-052; cf. lesson 5).

47. **A base rate stored without its population is unverifiable, and the only
    check that can catch it recomputes from raw series.** Two config leaves in
    this increment read `0.7779` and `0.2754`. Neither is absurd; neither is
    reproducible from **any** cadence (monthly 0.7556 / daily 0.8846, and
    0.2652 monthly). Every existing gate passed — the unit tests read the same
    config the code reads (lesson 7), the registry loaded, and the notes stated a
    population in prose that nothing could check. **The live check's
    recompute-and-drift-diff assertion is the only mechanism in the tree that can
    detect a config value that was recalled rather than measured**, and it is why
    that assertion is worth its runtime. Name the population in the **leaf's data**,
    not only in its note — prose is not a contract (D-052, O-38; cf. lesson 33).

48. **A threshold and the slope it is compared against are not two configuration
    choices if one of them has a score dimension.** §16.2 set a band of `±0.15pp`
    and a `beta` of `0.043`. Both are numbers in a config file, so both look
    free — but the band's **score-width is exactly `band_pp / beta`**, which means
    setting both sets the *partition* and the *slope* at once, and neither number
    can then be validated against the other. The first live attempt to
    re-measure `beta` **by the band corners** failed for exactly this reason: the
    measurement partly read back the configuration it was meant to test. **The
    tell is a parameter whose value is only defined relative to another
    parameter.** The repair is to give each its own **estimand** — beta from the
    forward-change regression, which needs no band; the band from a stated claim
    about what a meaningful move is — and then add a test asserting the two config
    leaves *are* independently settable. A band corner is a **level spread**; a
    projection is a **change**; the two are not the same quantity, and reasoning
    across them is the unnamed-estimand defect (lesson 42) in arithmetic form
    (D-053).

49. **Every per-state test passing is not a partition of the state space.** All
    four corroboration states in `project_inflation_trajectory` had a test, and
    the sweep still found a **genuine gap**: `M5.2` survived because each test
    drove **one** quadrant, so nothing ever placed the *disagreeing* inputs
    sharing a sign pattern against both *agreeing* branches. The mutant flipped a
    comparison that only diverges on two of the reachable cases. **N states with N
    tests is a hit, not a partition** — the same distinction lesson 45 draws for
    warning markers. The repair is a test that drives the **quadrant grid** (all
    sign combinations) plus a companion asserting every state is reachable, not
    merely one test per declared name (D-053).

50. **A transcribed harness target is a copy of the source that no gate keeps in
    sync — only re-running the harness at close does.** `check_targets` refuses a
    sweep whose mutation target is ABSENT from the source, which is what makes the
    gate worth having: a sweep that silently mutates the wrong line reports a weak
    test where it means a mis-aimed mutation (D-031's class). But the target is a
    **literal transcription**, and `ruff format` reflows code. In this increment
    the *authoring* run passed and the **close-out** run refused — a call that was
    one line at authoring time was three lines minutes later, with no semantic
    change. The second drift in the same increment was a leading-space miscopy in
    an error-message literal (M10.2). **Neither is detectable by reading the
    harness; both are detectable by executing it.** This is the concrete warrant
    for the standing rule that the sweep is re-run at close and not only at
    authoring, and it is why a swept target should be anchored on the **narrowest
    stable fragment** of the line rather than a whole-line transcription (D-053;
    cf. D-051, where the close-out re-run found a transposed `old`/`new` and an
    inverted test that passed *only* under its own mutation).

51. **A unit convention that differs between the specification and the config is
    a silent defect if nothing converts between them — and the failure direction
    of a safety rule is the part that matters.** §6.6c declares `DrawdownRule`'s
    `threshold_pct` and `risk_reduction_pct` as **fractions** (`le=1.0`);
    `config/settings.yaml` writes `drawdown_tiers` as **percents** (`10.0`, `50.0`).
    Fed across unconverted that is a **100×** error, and every ladder rung becomes
    unreachable: the function reports *"no risk-reduction rule triggered"* at a
    **90% drawdown**. **This project already has three unit suffixes in play**
    (`*_pp` = percentage points, `*_share`/`*_rate`/`*_fraction` = fractions,
    `*_pct` in `settings.yaml` = **percent**) and `*_pct` is the ambiguous one —
    it reads like a fraction and is written as a percent. The tell is a field
    whose name matches a fraction's name but whose config value is
    `> 1`, and the repair is to convert at **exactly one boundary** and assert the
    conversion in a test that reads the **shipped config through the shipped
    loader**, not a literal. **But the magnitude is the less important half:** a
    100× scale error in a **de-risking** rule fails toward **silence/inaction** —
    the ladder declines to cut risk, which is the worst available failure mode
    for a safety mechanism and the **opposite** of "always cuts 100%". My written
    prediction (that this would be a guard chain over a path, biased toward
    max-aggression) was **wrong about the direction**, and the wrong prediction
    would have mis-aimed the whole cross-check had it been treated as an
    assumption rather than as a hypothesis (D-054; cf. lesson 41's unit axis).

52. **Check whether a defect class applies BEFORE applying it — a mechanical
    application of a true rule is itself a defect.** The project's **base-state
    rule** (D-047/D-053: the uninformative label is the modal output, so the
    classifier carries no information) is a real and repeatedly-earned finding.
    It does **not** apply to `evaluate_drawdown_rules`: the function is not a
    classifier, there is no "uninformative label", and its modal output
    `no_action` is **correct** — 82.9% of real trading days genuinely warrant no
    intervention. Applying the rule here would have "fixed" the entire design.
    **An unrecorded non-application is indistinguishable from an oversight**, so
    the negative result is part of the deliverable: it ships as a test
    (`test_the_base_state_failure_does_not_apply_here`) that asserts the *reason*
    (the modal label is the semantically correct one, and the partition is
    non-degenerate) rather than merely asserting a count. The general form: **a
    lesson learned from one function is a hypothesis about the next one, never a
    specification for it** (D-054).

53. **A boundary fixture must be built by ADDITION of binary-exact values — and
    that exactness must be CHECKED, not assumed.** The test asserting "a drift
    exactly at the threshold does not flag" used `0.25 + 0.10 - 0.25`, whose float
    difference is **`0.09999999999999998`** — a hair *below* `0.10`. It passed, so
    it looked like boundary coverage; but it was **not on the boundary at all**,
    and the mutant that swaps `>` for `>=` **survived**. Rebuilt on the
    binary-exact pair `0.225 - 0.125 == 0.10` (`>` is `False`, `>=` is `True`) and
    the mutant dies. The one-line check — `assert 0.225 - 0.125 == 0.10` — belongs
    **in the test**, with a comment saying why those numbers were chosen. This is
    D-051's lesson in a new costume: **a test that is not exactly where it claims
    to be guards nothing.** The general form: whenever a test's *name* says
    "exactly at", "just above" or "just below", the fixture's position relative to
    the boundary is a **claim**, and a claim in a test needs an assertion (D-055).

54. **A mutation that is applied but does not change the semantics is
    indistinguishable from a missing test — so a survivor must be classified
    INERT BY CONSTRUCTION or INERT BY ANCHORING before it is called a gap.**
    D-055's first sweep run had 12 survivors and **only six were real gaps**: two
    mutants inserted *dead code* (an `if ...: pass`, an unused local), and one —
    `M10.1` — inserted a `model_config` **before** the class docstring, where a
    real `model_config` nine lines below **shadowed it**, so the code under test
    **never changed**. That last one is the sibling of D-051's transposed
    `old`/`new`: both produce a "missing test" conclusion about code nobody
    mutated. The cheapest proof is to **read back the attribute the mutation was
    about** rather than to reason about the diff. Corollary that bit twice in one
    increment: **a mutant that changes only PART of a message has not changed the
    message** — this guard's message was two concatenated f-strings, the mutant
    replaced one, and `"percent"` survived in the other, so the new test still
    passed (D-055).

55. **An inert mutation is not one claim but two, and the difference is exactly
    what a later reader would mistake.** "We could not write a failing test" and
    "the two programs are equivalent" are different statements, and equivalence
    itself has two strengths:

    * **UNCONDITIONAL** — no input can reach the branch. Characterisable in one
      sentence, and permanent while the surrounding guard exists. (`M4.6`: the
      `abs(signed) > threshold > 0` guard removes `signed == 0` from the direction
      test's domain **entirely**, so `>` and `>=` are the same predicate on every
      reachable input.)
    * **CONDITIONAL ON THE SHIPPED CONFIG** — true *today* because of a value in
      `settings.yaml` or a runtime type, and it **would evaporate if that
      changed**. (`CX3`: the `float()` cast is the identity on a `builtins.float`
      leaf; a leaf that ever became a `str` or `Decimal` would make it
      load-bearing and the proof would stop applying.)

    D-053 and D-054 both shipped `_EXPECTED_INERT` **empty**, which is a stronger
    claim than a populated one (O-42). D-055 populates it for the first time, and
    the discipline has to survive being used: **an excused mutation carries its
    excuse, and the strength of the excuse is part of the excuse.** The harness
    now prints the strength beside each proof and **returns exit 2** rather than
    certifying an entry that has none — the mechanical form of O-42 (D-055).

56. **When a function is built from a census of caller-supplied inputs, every
    input NOT supplied is a confident default — and the defaults are where the
    defects are.** All four of D-055's specification defects are one shape.
    `.get(target.instrument, 0.0)` cannot distinguish "I hold none of this" from
    "I forgot to tell you about this", and it picks the **stronger** claim. Worse:
    iterating `targets` means a position with **no target** is never visited at
    all, so a book that has drifted **entirely** into unbudgeted instruments
    reports `balanced`. The repair is a **census** — publish the set differences —
    rather than a warning string: the same discipline §15.19-D demands, and the
    same defect D-050 found in `four_pillar_scorecard`. **A drift check that only
    iterates the declared budget measures compliance with the budget, not risk.**
    And note the **failure direction is the opposite of D-054's**: that ladder
    failed toward *silence*, this one toward **false confidence** — both
    fail-safe-looking outputs produced by a missing input, both worse than an
    exception. Cf. **O-35** (four classifiers hand-building the same census
    inputs): there the risk is *divergence between callers*; here it is *omission
    inside one caller*, and the second is invisible at the call site because
    `.get(..., 0.0)` is the idiomatic spelling of a lookup that "cannot fail"
    (D-055).

57. **A mutation whose replacement string is transcribed from the value it
    replaces is INERT BY ANCHORING even when the branch is perfectly reachable.**
    Lesson 54 named the class (a mutation that does not change the semantics); this
    is the second worked instance and the first with a **conditional** proof.
    `M6.1` replaces the whole `compute_confidence(...)` call with the literal
    `0.5` — and `0.5` **is** the computed value, because the shipped config gives
    `base 0.7 − heuristic_penalty 0.2`. The two programs agree on every reachable
    input, so the survivor says nothing about the tests. **This is the opposite of
    the usual "could not write a failing test" excuse**: the absence is a
    property of the *mutation*, not of the coverage. The practical rule — when a
    mutant targets a **computation returning a constant**, the replacement must
    differ from the constant or the mutation proves nothing; and the honest
    response is to say so in the proof rather than to weaken the test until it
    "catches" it. Cf. lesson 55: the proof is **CONDITIONAL**, because Phase 5+
    recalibrating either constant would make the same mutant killable (D-056).

58. **A one-sided bound is not a weaker constraint than a two-sided one — it is
    a different object, and it is inert exactly where the risk is.** §20.13's
    entire enforcement is `min(scaled, max_leverage)`, and `min()` is an **upper**
    bound by construction. On the de-risking side — the side a vol target exists
    for — it is a no-op: `min(0.25, 3.0)` is `0.25`. Measured live: **the clip
    fires on 0 of 444 sessions** while the reflexivity warning fires on 13.1%.
    The unit tests could not see this because they were written from the
    specification's own wording, and the specification was pleased with one side.
    **The failure DIRECTION is D-054's — toward silence — arriving through a
    different mechanism** (arithmetic rather than a unit convention), which is the
    second time this project has found that the *direction* of a safety
    mechanism's failure is more informative than its magnitude. The sweep found
    the same hazard in mutation form: `M3.2` relocates the clip to
    `raw_scale >= 1.0` and **passes the entire file**, because every clipping test
    scaled up and every de-risking test sat below the ceiling. A test written from
    a specification inherits the specification's blind side (D-037, D-056).

59. **A cross-check that calls TWO siblings sees more than one that calls one,
    and the second comparison is often the one that finds the repair.** D-056
    cross-checks `evaluate_drawdown_rules` (the sibling *de-risker*) on the shared
    **invariant** — monotone in stress, flat at zero stress — and
    `check_rebalancing_drift` (the sibling *position-sizer*) on the shared
    **disclosure shape**. The first proves the arithmetic family; the second is
    what made defect 4 legible, because the drift check publishes per-instrument
    rows with **signed magnitudes and directions**, so "a book being cut is never
    described as no constraint engaged" becomes a comparison a reader can act on.
    Lesson 5's distinction (a restatement is not a cross-check) is the reason both
    are **real calls**. Corollary for the next increment: when a function has more
    than one plausible sibling, comparing against the *nearest structural* match
    often says less than comparing against the one whose **output vocabulary**
    differs (D-056).

60. **The same finding produced twice by independent checkers is evidence, not
    repetition — and it is a property of the contract, not of a fixture.**
    `RiskBudgetTarget` bounds `target_risk_contribution_pct` to `[0, 1]`, so a
    **diversifying leg** (a negative marginal risk contribution) has **no legal
    target**. D-055's live check found this on `SPY TLT IEF GLD UUP` and recorded
    it as **O-46**; D-056's live check, written independently and told nothing
    about it, found it **again on the same legs** (`UUP` at **−0.12%**). That
    agreement is what establishes the item as a contract limitation rather than a
    quirk of one script's book — which is precisely the distinction O-46 needed
    and could not have got from one observation. Both checks handle it the same
    honest way: **partition, renormalise, and NAME the excluded leg** — never
    clamp it, because clamping asserts a diversifier carries no risk (D-056).

61. **A killing tool that cannot be interrupted safely is more dangerous than the
    bugs it hunts.** The D-057 sweep rewrites `src/` in place, and its restore
    path was a `finally`. When the run was killed with `SIGTERM`, the `finally`
    never executed and the tree was left **carrying a mutant** — once
    `multiplier = 0.5` (a hardcoded divisor) and once
    `clipped = bool(...) is True`. Both were invisible in isolation; each was
    caught only because an **existing test reads the mutated constant from
    config**. The second kill came through a `tee` pipe, so the signal reached
    `tee` rather than the harness. The fix is not a better `finally` — it is a
    **signal handler that restores the in-flight file before exiting** (`SIGTERM`
    *and* `SIGINT`), plus `-x` in the inner test call so the run is short enough
    that nobody is tempted to interrupt it. **Any tool that mutates the tree must
    survive being killed**, because the kill is exactly the moment its cleanup is
    most likely to be skipped (D-057; D-049's failure mode recurring).

62. **A transcribed harness anchor is a copy of the source that no gate keeps in
    sync — and it can be wrong on the *wrong side of its own swap*.** `M3.2`'s
    anchor was written from memory as `index / (grid_points - 1)` while the source
    momentarily said `index / grid_points`; I "fixed" the refusal by inverting the
    anchor rather than by checking the source, which **entrenched** the error. The
    distinguishing test is arithmetic, not visual: `20000 / 100001 = 0.199998`
    (the shipped grid) versus `20000 / 100000 = 0.2` (a step of exactly `1e-3`).
    **When `check_targets` refuses, read the file — do not re-derive the anchor
    from the same memory that produced it** (D-057; lesson 50 is its sibling).

63. **A boundary fixture's grid must be fine enough to land OFF the boundary, or
    it tests nothing.** `CX1` moves `kelly.grid_points` to prove the resolution is
    read from config rather than hardcoded — and the obvious choice, **1001**,
    **would not discriminate**: its step is exactly `1e-3`, so `0.2` lands on a
    grid point and both programs agree. The fixture uses **777** points (step
    `1/776`, nearest point `0.199742`) and asserts against
    `round(155.0/776.0, 6)`. **A fixture chosen for roundness can sit exactly on
    the boundary it was meant to probe** — this is lesson 5o in the resolution
    dimension rather than the value dimension (D-057).

64. **An INERT BY UNREACHABILITY proof is also a review of the prose that
    described the state as reachable.** `M7.1` swaps `full_fraction == 0.0` for
    `final_fraction == 0.0`, and the two are equivalent on every admissible input
    — because the cap carries a **field bound `gt=0.0`**, so a cap of exactly
    `0.0` is a `ValidationError`. That means the state `SizingOutcome`'s docstring
    calls `clipped_by_position_limit` **with a zero result** cannot occur. The
    proof is arithmetic (200 000 draws, **0** disagreements), and its *output* is a
    documentation correction: the closing test asserts the reachability fact
    instead of the phantom state, so a future bound change is **visible rather
    than silent**. **When a mutant survives by unreachability, ask what the code's
    own prose says about that state** — the excuse and the finding are the same
    observation read in two directions (D-057).

65. **A function whose input is a distribution cannot have a live check that
    pulls; it needs an oracle.** Kelly's inputs are caller-supplied outcomes and
    probabilities, so no market series could falsify it. The honest live check is
    therefore **offline by design** and its core is a **disjoint** cross-check:
    the shipped grid-search optimum against the **binary closed form**
    `f* = (p·b − q·a)/(a·b)`, agreeing to **3.33e-16** over 80 combinations. The
    remaining sections then do what a pull would have done — refute the deleted
    placeholder, read the divisor out of the shipped YAML, and **reproduce the
    search-edge collapse on real inputs** so the disclosure is measured rather
    than asserted. **"Offline" is not "not a live check"; it is a live check
    against an oracle instead of against a provider** (D-057; the third distinct
    live-check shape in the repo, after the pulled cross-check and the
    contract-invariant check).

66. **The failure direction is part of the defect's identity.** D-054 failed
    toward *silence* (a guard that never fired), D-056 toward *false confidence*
    (a clip that could not bind in the regime it existed for), and D-057 toward
    **prudence** — a 100× unit error (dollars where the contract requires a
    fraction of capital) produces a **smaller, cap-slipping, safer-looking**
    number. A `< -1.0` guard catches the loss side and is silent on `+120`, a
    perfectly legal 12000% gain. **Record the direction at authoring time**: it
    determines what the tests must probe, and in this case it moved the hazard out
    of the Kelly code and into the **unit declaration** on a schema three modules
    away **— O-50** (D-057).

67. **A mutation survives because the test asserted an outcome BOTH programs
    produce — not because the mutation was harmless.** D-058's sweep reported
    **six** survivors on its first run and every one was a **test** defect. The
    sharpest is `CX1`/`CX2`: a test comparing the emitted instrument to
    `settings.default_short_tenor` cannot falsify a hardcoded `"2y"` when the
    shipped config value **is** `"2y"`. The only form that can is one that
    **moves the config leaf** and requires the output to follow. When a mutation
    survives, ask which of the two it is — a harmless mutant, or a test that
    would pass on any program — before writing a new mutation.

68. **When guards overlap on a fixture, assert WHICH one fired.** `("10y","2y")`
    is refused by the ordering check *and* by the minimum-gap check (the gap is
    `-8y`), so `pytest.raises(ValueError)` proves nothing about either. D-058's
    fix was to parameterise on the exception **message**, which is the cheapest
    way to make a fixture discriminating. The same trap in reverse: a fixture
    whose *premise* is false tests nothing at all — `"US HY credit index"` does
    not contain the phrase `"equity index"`, so the exclusion-ordering test it
    was written for could not fire (`M8.5`).

69. **A docstring is not a test, and a claim inside one can be false.**
    D-058's `ProductionUniverse` docstring said `"US HY credit index"` would be
    admitted by an equity-first ordering. It would not have been. The sweep
    falsified the prose, and the repair was to replace the fixture with one where
    the claim is true. **Prose in a docstring that asserts behaviour is a claim
    the suite must be able to falsify** — otherwise it is the same class as a
    comment describing a guard that is not there.

70. **An invariant can make a mutation provably inert, and that is a finding
    rather than a gap.** `M6.4` publishes the routing table's declared category
    where the shipped code publishes the matcher's verdict. They are **equal on
    every returned result**, because the preceding guard raises when they differ.
    So the published field is a *measurement* only because that guard makes it
    one, and the honest response is an invariant proof plus a test that pins the
    **guard** — not a test that cannot exist. This is the third flavour of inert
    proof the project has now used (unreachability in D-055/D-057, equivalence in
    D-057, **invariant** here) — **O-55**.

71. **A boundary is only as real as the layer that enforces it, and the layer
    that names it may not be the layer that enforces it.** §22.3.1 hardcodes a
    `PRODUCTION_UNIVERSE` in `models/`; §22.12's actual enforcement object lives
    one layer **up** in `thesis_layer/`, which `models/` cannot import without
    inverting the dependency. D-058's repair is D-046's, reused: the vocabulary
    stays where it lives and is received as a **required argument**, typed by a
    `Protocol`. Copying it down would have created the second definition D-046
    exists to prevent — **and the two definitions would then drift** (O-54).

72. **A mutation score computed against a suite that does not pass unmutated
    measures NOTHING.** D-059's first sweep reported `31/31 killed, 0 survived`
    — a perfect score, and false. Almost every "kill" named the **same** test,
    which is only possible if that test fails on **shipped** source: it asserted
    ``implausible for '2y'`` against a validator message naming the *long* leg
    (`'3y'`), so it failed unconditionally and turned every mutation into a
    phantom kill. **The honesty control is what caught it** — a semantically
    identical program cannot be killed, so a killed control proves the harness is
    reporting kills it cannot justify. D-051 created the control for exactly this;
    D-059 is the first time it *fired*. **Corollary: run the sweep twice, and
    treat the second run as the real one.** D-051 found a transposed `old`/`new`
    on its close-out re-run; D-059 found a dead test on its. In two consecutive
    increments the *first* run was the misleading one.

73. **An anchor that spans a multi-line implicit string concatenation must span
    ALL of it.** `M6.2` asserted it removed the magnitude from a warning whose
    text is four physically concatenated string lines; the anchor replaced only
    the first, and the phrase the test pins (`"1-2%"`) lives on the third — so the
    mutation was a no-op on the very assertion it was written to break, and it
    "survived". The repair is stronger than transcription: **slice the block out
    of the source file at import time**, so the anchor cannot drift when
    `ruff format` reflows it. This generalises D-058's `CX4` fix, and an anchor
    that *cannot* differ from its target is worth more than a readable literal.

74. **Measure the margin before you call a guard unreachable.** The first draft of
    `M3.2`/`M3.3`'s proofs said the residual is "always 0.0", which was a guess:
    the executed 1377-case sweep found **1185 exact zeros and 192 nonzero**, worst
    `9.766e-04`. That is 9.8% of the 0.01 tolerance — a **10×** margin, not an
    infinite one — and repeating at `$5e12` notional makes the guard **reachable**.
    So the honest proof is **scale-conditional**, and the condition is a carry-over
    (O-56) rather than a sentence in an exemption. **An exemption that says
    "always" and is true "below $2tn" is the same class of overclaim this project
    keeps finding in the specification** — and the fix is identical: state the
    condition, and record it so it can decay.

75. **A wrapper that cancels "exposure" cancels exactly the exposure it names,
    and no more.** §15.1b says duration-weighting "cancels level (PC1) exposure".
    Duration-weighting sets `N_l·D_l = N_s·D_s`; level cancellation requires
    `N_l·P_l·D_l = N_s·P_s·D_s`. The two differ by `P_l/P_s` — zero only when both
    legs trade at the same price. For **futures** (both near par) they coincide,
    which is why the specification can treat them as interchangeable; for **cash
    bonds** the gap is real (**O-57**, 1.23% on a 4.5%/4.3% pair). The general
    lesson is not about curve trades: **check whether a named "exposure" is the
    risk factor or its price-normalised sibling**, because the formula that
    cancels one does not generally cancel the other. Found by the live cross-check
    the standing brief mandates — and it found it because the cross-check asserted
    the *exact relation* rather than a convenient equality.

---

## Next

Continue one at a time, per the standing instruction. **`simple_gdp_nowcast`**
(Module 7.5, D-034/D-035) and **`auction_demand_signal`** (Module 8.2, D-036)
are both done. `simple_gdp_nowcast` was the last `NotImplementedError` stub in
the models layer, so **every function in Tiers 1 and 2 that was stubbed is now
either implemented or deliberately blocked**. The only other
`NotImplementedError` in `models/` is `output_gap_from_snapshot`'s
`country != "us"` scope guard (§22.3), which is deliberate.

**Tier 3 stood at 6 / 15** when this paragraph was written; it stood at 8 / 15
when the next one was, and it is **9 / 15** as of D-051. *(Historical markers in
this section are deliberately left in place: each records the count at the moment
its paragraph was true, and the live count is the header above. Treat any figure
below that is not the header as a dated observation, not the current state.)*
Two of its first six were the Module 13 evidence pair
(**D-046**), which is plumbing rather than judgement: it supplies the
`source_independence_count` that `compute_confidence()` had been consuming as a
literal zero.

**That supplier now has its consumer.** `inflation_convergence_classifier`
(Module 5.3, **D-047**) is the **first function obligated by §15.19-D**, and it
discharges the obligation: it tags each direction with its evidence family, calls
`count_independent_families()`, and passes the **family count — not the number of
inputs — to `compute_confidence()`**. Six measures spanning two families now
score as two families, which is the whole point of the section.

The increment also produced the **third occurrence of the O-21 defect class**.
§21.1 listed three inflation measures as blocked; the probe found **two of them
live** (`MEDCPIM157SFRBCLE`, 524 obs; `PCETRIM1M158SFRBDAL`, 594 obs). So the
classifier runs at **six measures, not three** — which is precisely why the
degeneracy at low `n` had to be measured rather than assumed. It also means
**`median_cpi_direction` and `trimmed_mean_direction` move from blocked to
verifiable** in the registry; `supercore_direction` stays blocked, and the four
`blocked:` entries flagged in O-21 remain un-re-probed.

Three specification defects, all measured on **522 real months**:

1. **The conflict gate read two measures and ignored the other four.** 6 months
   (1.15%) were misclassified — `2008-12`, `2017-03`, `2020-03`, `2020-04`,
   `2020-05`, `2026-06`. The correction asks whether the **losing side** reaches
   `deep_conflict_share` of the whole set.
2. **`HIGH` is the base state, not a finding** — 89.5% at six measures, 86.6% at
   three, matching the config to the decimal because the config was measured from
   this function. The rate now travels with the verdict.
3. **The thresholds are degenerate below `n = 5`** — at `n = 3`, `high_threshold`
   is unanimity and `MEDIUM` has a single attainable value; the conflict gate
   fires on **one** dissenter. Disclosed at `n < 5`; the reachability proof moved
   to `n = 6`.

**One structural finding about the input space itself:** `core_pce_direction` is
**required**, so the floor is 3 measures spanning **2 families**, and
`independent_families` can only ever be **{2, 3}**. §15.19-D's single-family
warning and the `confidence_ceiling_by_independent_families` ceiling are both
**unreachable through the public API**. That is recorded, not hidden, and the
ceiling was rebuilt to **derive and cross-check** so it can no longer drift
against the constants it mirrors.

**`check_trilemma_tension` is now done (D-048), and the answer to the question
this section asked about it is: no — §15.19-D's single-family warning is *also*
unreachable there, but for a completely different reason.** Its inputs are three
manually-classified booleans, so the model pins `source_independence_count=0` and
`depends_on_unobservable=True` by construction rather than counting families at
all. The input-space lesson held twice in a row: **assumed input spaces are
wrong often enough that the floor must be measured, not reasoned about.**

The function's own headline finding is that **§15.20-A's threshold does not fire
on §18.1's reference episode** — Black Wednesday reads −5.37% on the 3-month
measure against a −10% threshold. A crisis detector silent during its own worked
example is not a detector, so a 1-month acute test was added (D-048). And the
live check's first run **failed**, which is how the cadence finding surfaced:
`TRESEGGBM052N` reports 843 observations but only 837 are monthly, because its
first **seven** points are annual — `1950-12 … 1956-12` — of which **six are
excluded** and the December that opens the monthly run is **retained**. Every
threshold here names a number of months, so the observation count is not the
measurement window. Indonesia is worse: **700 → 668**, and its exclusion changes
cadence **twice** (annual, then a four-year quarterly block), which an early
description of it got wrong — see the amendment to D-048.

**The increment's most transferable result is about the sweep, not the
function.** Six of the rebuilt table's mutations were reported as survivors that
looked like weak tests; they were in fact **rewriting the wrong function**.
`country="us",`, `source_independence_count=0,`,
`depends_on_unobservable=True,` and the `measured` property body each appear
**twice** in their file — once in `output_gap_from_snapshot` / `RegimeBaseRates`,
once in the trilemma pair — and `str.replace(..., 1)` takes the first. The file
changed, the tests passed, and the conclusion "the suite is weak" was drawn about
a mutation that had never touched the code under test.

This is D-031's **mis-targeted** class, and it is more dangerous than a
pattern-miss: a miss is visible, a mis-target is internally consistent. The
runner now **refuses to start** if any target is absent or ambiguous, and the
majority of the table is generated from a behavioural matrix so a mutation of
behaviour cannot fail to match. **60/62 killed, 0 pattern-misses, 2 proven-inert
with written proofs.**

**Closing the record produced two further corrections, both now written into the
D-048 amendment.** Three registry entries were added
(`trilemma_reserves_gb/kr/id`, each `not_a_snapshot_field: true` — the three
trilemma **legs** are manual, O-28, so the series are registered for provenance,
not to feed a snapshot field). Writing them exposed:

1. **Two of the three `verified_value`s were wrong** — written from recollection
   rather than fetched. GB was `93221.49` and is `169355.66`; KR was `411301.2`
   and is `421968.56`. Neither looked odd and nothing raised an error. This is
   §21.0's failure mode reproduced **inside the record set §21.0 exists to
   protect**, and it is lesson 33.
2. **The cadence note's *shapes* were wrong although its *counts* were right.**
   Indonesia does not change cadence once: it is **16 annual points
   (1950-12..1964-12), then a continuous quarterly block (1965-03..1968-12),
   then monthly** — so the earlier "annual to 1964-11, quarterly to 1969-11"
   mis-dated the usable window by four years. GB/KR change cadence once. Lesson
   34: **an exclusion's size does not describe its structure.**

The live check's own output was corrected in the same pass — it had printed
`monthly from 1956-12` (the *retained* December, not the first bare monthly
point) and the same Indonesian cutovers. It now prints
`monthly span opens at …` plus the retention convention, and the run is
**PASSED** with base-rate drift **0.000** on both thresholds.

**`auction_demand_signal` shipped with one of its five inputs reclassified
MANUAL.** §21.1 assigns `stop_through_bp` to the "TreasuryDirect auction results
API" as LIVE, but that route has no when-issued or expected-yield field in any
of its 91 columns, and its three yield fields are within-auction statistics that
agree to within 0.0011 on all 703 note auctions — so a tail cannot be derived
from them. The user chose MANUAL over a secondary-market proxy, on measurement:
a tail is 0-2bp and the proxy's own error is several bp. **The live check
therefore cannot exercise the tailed branch, and says so in its own output**;
the branch is covered by unit tests. See **D-036** and **O-15**.

**`credit_spread_attribution`** (Module 8.3, D-037) is done. It carried the
sharpest specification defect found so far: a branch for a state its own logic
forbids. Three of its five inputs were inert, so it attributed widening without
checking for it; the two spread changes now ship as a disclosed diagnostic
rather than a predicate, per the user's decision.

**`compute_fci`** (Module 12, §22.7 — *not* Module 3, which an earlier revision of
this file mislabelled) is done. It was the largest single defect found so far: a
config block that would have moved the composite by more than two standard
deviations while every number stayed plausible.

**`policy_mix_classifier`** (Module 3.2, D-039) is done. It carried a sign trap
that my own probe fell into — the source deficit series is negative for a
deficit, so the probe measured the inverted comparison and produced four wrong
base rates. The live check caught it because it signs-verifies the series
independently. **A rate measured by the same code path that carries the sign
error cannot detect it** — that is the lesson worth carrying forward.

**`qe_qt_stance`** (Module 4.1, D-040) is done. It was the fourth consecutive
increment with a material specification defect, and the second dead branch.

**TIER 2 IS COMPLETE — 29 / 29.** The last three closed together:

* `marginal_risk_contributions` was **found already implemented and to standard**
  in `models/risk.py` while this list called it outstanding. The checkbox was
  stale, so the count had been one low for some time. No code changed.
* `bayesian_update` and `expected_value` shipped as `models/probability.py`
  (**D-042**), with §11.1's three mandated tests by name.

**What "complete" still does not mean — and what D-043 changed.** As of
**D-043**, all 29 functions run against real data. `minsky_composition_drift` was
**unblocked**: §21.1's premise that no free leveraged-loan series exists was
**factually wrong**, and `fred_search` found one. Its live check is a real run
now, and its stage base rate is measured (31.4% / 43.1% / 25.5%) after being
unmeasurable. The credit model's `default_rate_trend` is likewise **derived**
from the FRED delinquency rate rather than hand-entered.

What remains is not a validation gap but a **disclosed limitation** on two
proxies: the leveraged-loan measure covers hedge funds' holdings and reads zero
before 2013-Q4, so it **excludes the 2008 crisis**; and delinquency *leads*
default rather than equalling it. Both are stated on every output.

**One function still has a branch the live check cannot reach:**
`auction_demand_signal`'s tailed branch, because the when-issued yield has no free
source (**O-15**) — confirmed absent from FRED, not merely unfound.

**Next: Tier 3 — synthesis (5 / 15 as of D-047).** Those functions compose the
Tier 1/2 outputs into judgements: regime classification, convergence, the
four-pillar scorecard, transmission. They are where the pieces finally meet, so
expect their reviews to be about *interaction* rather than arithmetic.

**The `classify_regime_rule_based` increment confirmed that expectation, and then
some.** Three defects were in the specification's own branch chain — a grid that
reaches six of nine declared states, a recession branch that excludes the 1974
shape, and two declared inputs that are never read — and a **fourth was found
only by running it**: the inflation axis is a near-constant (93.75% `rising` over
240 real quarters), so four states are rare by construction rather than by
economics. That fourth one is upstream of the function and is now **O-23**. The
lesson worth carrying: **a Tier 3 defect is not in the arithmetic, so the
pairing-axis discipline will not find it — the live check and the base-rate
measurement will.**

A candidate next function is `tag_evidence_source` / `count_independent_families`
(Module 12's scorecard plumbing), which is pure bookkeeping over already-produced
`ModelResult`s and would exercise the `source_independence_count` contract that
currently reads 0 nearly everywhere. `check_trilemma_tension` is the more
substantive choice and needs the FX/monetary inputs Tier 5 does not yet provide.

**DONE — both `tag_evidence_source` and `count_independent_families` shipped
(D-046), and the candidate above was the right call for the reason given.** The
`source_independence_count` contract was `0` at every one of its ~15 call sites
in `models/`: the argument existed, `compute_confidence()` consumed it, and
**nothing could supply a non-zero value for it.** The module is now the
supplier — five CPI sub-measures count as **one** vote, core PCE as a second, a
TIPS breakeven as a third.

It also cleared an oddity the specification could not have anticipated: a
**31-member** `EvidenceSourceFamily` had been sitting in `thesis_layer/schemas.py`
with **no constructor and no importing test**, in a layer that model-layer
convergence classifiers cannot reach downward. An orphaned declaration — the
D-045a class again, this time found by *looking* rather than by a live check.

**D-047 is the wiring D-046 warned not to fake.** It is worth stating what
actually changed: the supplier was correct and complete as shipped, and it was
still worth nothing until a caller existed. **A deliverable has no value until
something consumes it** — and the corollary, now that one consumer exists, is
that **every remaining `source_independence_count=0` site is a defect to be
worked off**, one per increment, not a neutral default. **The count is measured,
not estimated: 26 literal `source_independence_count=0` sites across 14 modules
after this increment** — one of which (`evidence.py`) is a legitimate D-027
self-census that must stay 0. The pre-D-047 "~15" was never counted; it was
inherited from D-046's prose and it was low by nearly half.

**What D-046 did NOT do:** §15.19-D requires every convergence classifier to
call `count_independent_families()` and use that count — **not** the raw number
of agreeing signals — as its denominator. None of those callers exists yet, so
the ~15 sites are now *suppliable* but not yet *supplied*. **The gap is closed at
the producer end only.**

**`inversion_probability_adjustment` (D-049) is Tier 3's first probability, and its
finding is about the shape of the data rather than the arithmetic.** The
specification supplies a base rate of `0.15`. The measured 12-month-forward
recession rate conditional on inversion is **`0.489`** over 592 monthly
observations of real `DGS2`/`DGS10`/`USREC` history — **3.1×** the literal, which
is not a rounding of it. That number was not shipped: the base rate is now a
**required input with no default**, so the disagreement has to be faced by
whoever supplies it. The two confidences the specification hardcodes (`0.3`,
`0.35`) were refused for the same reason as in D-048 — §22.8 reserves confidence
for `compute_confidence()`, and the function now returns **0.700 flat across every
branch**, because severity is a fact about the world and confidence is a fact
about the measurement.

The measured tables are the part worth carrying forward:

```
depth is MONOTONE      -0..-25bp 0.412   -25..-50bp 0.417
                       -50..-100bp 0.552  -100bp+   0.857
duration is HUMP-SHAPED  0-4wk 0.250   4-13wk 0.286   13-26wk 0.412
                         26-52wk 0.769  >=52wk  0.520
```

**Depth is monotone; duration is not.** The function's structure multiplies a
depth factor by a duration factor, so it assumes both are monotone. The configured
26-week cap lands **exactly at the 26-52 week peak**, which means the mechanism
never enters the region where its own assumption is contradicted — and, as lesson
35 records, that is the *best* available choice rather than a bug to fix, because
moving the cap exposes the contradiction rather than resolving it. The `>=52wk`
bucket's 0.520 is dominated by the 2022-07 … 2024-09 inversion (**113 weeks**),
whose forward window has not closed, so the check runs a **censoring control**;
the hump survives it and is now an open calibration item.

**The reference-episode dates in the first draft were wrong by up to six weeks**,
because I segmented at monthly resolution and the config's dates are claims about
a *daily* slope series. Three other figures from that first probe were also stale
(the `-25..-50bp` bucket reads 0.417 not 0.391; the duration table reads
0.769/0.520 not 0.750/0.409; the 2022-24 episode is 113 weeks not 107). All four
are corrected, and **the correction is written into the config docstring rather
than silently applied**, so the next reader sees that the numbers were re-measured
and why. The live check now reproduces all four episodes **to the day** and
reconciles the base rates to a largest drift of **0.0005**.

**Next: `cross_asset_transmission`.** D-051 closed `classify_convergence`,
which was the §15.19-D caller still owing that audit and the one whose input
shape differed most from the two that preceded it — an arbitrary `list` rather
than a fixed record. It closed that audit, and it also produced the increment's
most useful artefact: a **cross-check** between two implementations of the same
predicate, which found a defect in the already-closed D-050 module.

`cross_asset_transmission` is the next candidate and the one whose input space is
largest (a cross-market matrix), so it carries the most risk of the composition
defect D-050 found — *correct gates whose order makes one of them inert* — and
it should be built with a cross-check against anything comparable from the start.

**DONE — `cross_asset_transmission` shipped (D-052), and both things this
paragraph predicted were right.** It is the largest input space of the six, the
composition defect was there, and the cross-check built from the start is what
found it. What follows is what the paragraph could not have predicted, and it is
the part worth carrying:

**The composition defect was real and it is now proven rather than suspected.**
The driver split tests `both_channels` before `real_driven`, so every input that
would have reached `real_driven` is consumed earlier — `CONFLICTED`-first, one
level down. **M2.7** and **M2.8** survived, and the response was not "the suite is
weak" but an **enumeration**: the prover mirrors `_driver_of`'s branch structure
across the shipped / M2.7 / M2.8 forms and walks the whole space, **643 200 cases,
0 differences**. The proof re-executes on demand (`--probe-inert`), so the claim
stays live instead of decaying into a comment.

**A third kind of inertness got named.** D-050 established *threshold* inertness
and *composition* inertness. **M9.2** is neither: it rewrites the **name** of a key
in the published `value` dict, and the key's consumer reads it under a second
alias — so the mutant changes the namespace and not the output. Three kinds now,
and the remedies are not interchangeable: a threshold survivor is a question about
the input domain, a composition survivor about gate order, and a name survivor
about the consumer's binding. **Establishing which one it is must come before
concluding anything about the tests.**

**The live check found a defect in two artifacts that had already shipped — in
`config/settings.yaml`, not in the new function.** `gold_call_base_rate` read
`0.7779`; the monthly recomputation is **0.7556**, daily **0.8846**, and **no
population reproduced the shipped number**. `measured_breakeven_negative_share`
was wrong the same way (0.2754 → **0.2652**), and a third note quoted a **daily**
denominator under a **monthly** heading. This is **O-30's class** — a measurement
written from recollection, plausible, and invisible to every gate the project
has — reproduced in a *config leaf* rather than a registry `verified_value`. The
generalisable form is lesson 47: **a base rate without its population is
unverifiable, and the only check that can catch it recomputes from raw series.**
That assertion now has a reason to exist beyond tidiness, which is the same thing
that happened to `check_targets` in D-051.

**And the cross-check the brief asked for had to be *adjusted*, which is the
subtle part.** The obvious candidate — compare the derived real yield to the
observed one — was **rejected**, because the check's own first step proves the
identity is **exact** (max error 0.000000 over 5 931 observations). A comparison
that cannot fail is not a cross-check; it is the D-027 circularity in a new
costume. Rather than discard it, it was **repurposed**: the identity is now the
*proof that the derivation is a restatement rather than a proxy*, and the real
cross-check runs against `inversion_probability_adjustment` (D-049), which is
**disjoint by construction** — a same-day long-end decomposition against a
short-end level, directional calls against a probability, **no shared input**.

**Tier 3 stood at 10 / 15 there.** Five remained: `project_inflation_trajectory`,
`evaluate_drawdown_rules`, `check_rebalancing_drift`,
`volatility_target_scaling`, `apply_fractional_kelly`. None of them is a
cross-market matrix, so the input-space risk profile drops — but
`evaluate_drawdown_rules` and `volatility_target_scaling` are both **gate chains
over a path**, which is the same compositional shape that has now produced a
defect in D-050, D-051 and D-052. Expect the hazard there rather than in the
arithmetic.

**DONE — `project_inflation_trajectory` shipped (D-053), and the paragraph above
was right about the shape and wrong about where the hazard would be.** This
function is *not* a cross-market matrix and it is *not* a gate chain over a path —
it is a single affine map from a labor score to a projected change — and it
produced the increment's most consequential finding anyway. The hazard it carried
was not compositional. It was **dimensional**.

**DONE — `evaluate_drawdown_rules` shipped (D-054), and the prediction about its
shape was wrong a second time, in a way worth recording.** The paragraph above
named this function one of two "gate chains over a path". The probe showed it is
**neither**: there is no path (two scalars in, no sequence), no chain (every rung
reads the *same* operand, nothing is consumed), and the resolve step is a **max,
not an accumulating ladder** — so the composition defect is *unreachable* here, and
so is the ladder-accumulation question entirely. Its hazard was a **unit convention**
(fractions in the spec, percents in the config, 100× apart) with no converting
consumer. The prediction was written down, probed, and found wrong — which is the
useful outcome, because a prediction treated as an *assumption* would have aimed
the cross-check at the branch structure and missed the config entirely. **Treat a
written prediction about where the hazard lies as a hypothesis to test, never as
scaffolding to build on.**

**The specification's threshold made `stable` the base state.** §16.2's band is
`±0.15pp` against a `beta` of `0.043`. On the declared score range that labels
**79.1% of 296 real months** `stable` — **D-047's base-state failure**, reproduced
in a function that has nothing structurally in common with D-047's. The label
carries no information, and the failure is invisible in the arithmetic: the sign
is right, the units are right, the branch order is right, and every per-state unit
test passes. **This is the second time this project has measured a classifier's
base rate and found the specification's own number unsuitable** (lesson 39), and
the first time it has happened in an axis with no `Literal` state to audit against
— a three-member `Literal` all of whose members *are* reachable can still be
**effectively** two-member.

**The repair was not a narrower band, and finding out why was the increment.**
The obvious fix — tighten the band until `stable` is not the base state — is
wrong, because **the band's score-width is exactly `band_pp / beta`**. Band and
beta are **not independent configuration choices**; they are two labels on one
partition. Setting both at once fixes the partition *and* the slope together, and
then neither can be validated against the other. That is lesson 48, and it is the
reason the first live check **failed**: it tried to re-measure `beta` from the band
corners, and the measurement was partly reading back the number it was meant to
test. The resolution was to give each its own **estimand** — beta from the OLS
slope of the **6-month forward core-inflation change on the labor score** (which
needs no band at all), the band from a stated claim about **what counts as a
meaningful move** — and then to add a test asserting the two leaves are
independently settable. The corrected values are `0.006` and `±0.05pp`, a **7×
config error** the live check caught before the record set was written.

**That re-derivation is also where a genuine dilemma got resolved honestly rather
than patched.** Narrow bands (so `stable` is not the base state) and a large beta
(`0.043`) cannot both hold: the relation simply is not that strong. The temptation
is to keep the wide band, declare the relation real, and accept a classifier that
says nothing. The measured answer is that the relation is **real but small** —
`R² 0.047`, and it **survives 12-month detrending at +0.348**, so it is not two
persistent series agreeing by trend. It holds over **3-9 months**, and it
**reverses at 24 months** (slope −0.0114, t −2.94) — which is not instability but
the signature of a **policy reaction**: a tight labor market predicts inflation
three to nine months out and predicts it *down* two years out, because that is when
the central bank has answered. Publishing the small coefficient with its horizon
structure is the honest output; a fitted-to-look-strong version would have been
the defect.

**And a specification defect that only execution can find: the sign cancels
itself.** §16.2 negates **twice** — `slack = -s/100`, then `pc = -beta*slack` — so
the negations **cancel** and `pc = +beta*s/100`. My first implementation followed
the prose and wrote `beta * (-score)`; the first functional run returned
`reaccelerating` for a score of `-100`, the **loosest possible** labor market. The
algebra is now in the docstring with the double negation spelled out, so it cannot
recur. **A sign that appears twice in a specification is a sign nobody has
checked** — and the unit tests would not have caught it, because `_change_pp` was
self-consistent: every test asserted the function matched my own wrong formula.
That is lesson 7's cousin: **a suite that reads the same misconception as the code
is not a check on the code.**

**The sweep found a genuine coverage gap, and it is a new shape.** All four
corroboration states had a test and **M5.2 still survived**: each test drove **one**
quadrant (`tight labor + expanding growth`, etc.), and the mutant
(`growth_expanding = (growth_value > 0) == bool(tight_labor)`) breaks only the
`loose labor + expanding growth` case — which no test ever placed against the
*agreeing* branch sharing its sign pattern. **N states with N tests is a hit, not
a partition** (lesson 49, the same distinction lesson 45 draws for warning
markers). Fixed with a quadrant-grid test plus a reachability companion. The sweep
went **20 → 21 killed**; final **21/24 killed, 3 expected survivors, 0
unexplained**, and `_EXPECTED_INERT` was deliberately **emptied** — an empty
excuse set is a stronger statement than a populated one, because nothing is
excused from having a test.

**Both honours were discharged, and both earned their keep.** The cross-check was
built **from the start** (the brief's second requirement) against
`cross_asset_transmission` on the **shared labor leg** — and it is what indicted
the `beta`/band configuration. The sweep was **re-run at close** (the first
requirement) and **refused on a drifted target**: `ruff format` had reflowed the
`source_independence_count` call from one line into three after the authoring run,
so the close-out run's `check_targets` gate reported the target ABSENT. Fixing it
took a re-anchor; *skipping* the re-run would have shipped a sweep whose
close-out status was assumed rather than measured. **That is now the second
formatter-drift in this increment** (the first was M10.2's leading whitespace), and
the generalisable form is lesson 50: **a transcribed harness target is a copy of
the source that no gate keeps in sync — only re-running the harness at close does.**

**Tier 3 closed at 15 / 15 with `apply_fractional_kelly` (D-057)**, and it was
the increment the previous three had been pointing at. Every prior Tier 3 hazard
had been *somewhere other than where the prose said*; this one was **in the
specification itself, in the open**: §17.3's `raw_kelly = ev / 100` is a
placeholder **incorrectly labelled Kelly**, and §22.13 makes its deletion
mandatory. The increment's first job was therefore **deleting a formula the
specification had already shipped in prose** — which is not a mutation-testable
act at all, and the sweep's docstring says so rather than pretending otherwise.

**Three things this increment established that the earlier ones could not.**
First, **the honest live check for a function whose input is a distribution is a
cross-check, not a pull.** Kelly consumes a caller-supplied set of outcomes and
probabilities; there is no FRED series that could falsify it. So
`live_kelly_check.py` is **offline by design** and its Section 1 runs the shipped
grid against the **binary closed form** `f* = (p·b − q·a)/(a·b)` — a genuinely
**disjoint** oracle (arithmetic, not a re-implementation), agreeing to **3.33e-16**
over 80 combinations. Sections 2–4 then refute the placeholder, read the divisor
out of the YAML, and **reproduce the P5b collapse on real inputs**
(`distinct REQUESTS: 1 of 3` against `distinct GROWTHS: 3 of 3`) so that what the
module *does* when every candidate pins at the search edge is a **measured
disclosure**, not a claim.

Second, **a third failure direction.** D-054 failed toward *silence*, D-056 toward
*false confidence*; D-057 fails toward **prudence** — a 100× unit error (dollars
or basis points where the contract requires a **fraction of capital**) produces a
**smaller**, cap-slipping, safer-looking number. The `< -1.0` guard catches the
loss side and says nothing about `+120`, a legal 12000% gain. That asymmetry is
recorded as **O-50**, because the contradiction lives in
`thesis_layer.schemas.ScenarioOutcome`'s `unit="bp_pnl_proxy"` default, not in the
Kelly code.

Third, **an unreachability proof that corrects the module's own prose.** The
survivor `M7.1` swaps `full_fraction == 0.0` for `final_fraction == 0.0`, and the
proof shows the two guards are **equivalent over every input the contract admits**
— because the cap carries a **field bound `gt=0.0`**, so `final_fraction == 0.0`
forces `requested == 0.0`, which forces `full_fraction == 0.0`. Verified over
**200 000** random draws with **zero** disagreements. The consequence is a
**finding**: the state `SizingOutcome`'s docstring describes as
`clipped_by_position_limit` *with a zero result* is **unreachable**, since a cap
small enough to zero the size is not a legal cap. The closing test asserts the
reachability fact — including the `ValidationError` that makes a zero cap
illegal — so a future bound change is **visible rather than silent**.

**The harness, not the function, was the dangerous part this time.** Two defects
were found by *running* the sweep rather than by reading it. (a) `-x` was omitted
on the first authoring run: the selection is ~95 s, so 25 mutants took ~40 minutes
and invited the interruption that followed. (b) When the interruption came, the
`SIGTERM` **bypassed the `finally` that restores the mutated file** — D-049's
failure mode recurring, leaving `M5.2` (`multiplier = 0.5`, a hardcoded divisor)
applied in `src/`, caught only because an existing test reads the divisor from
config. The resumed background run was killed the same way via a `tee` pipe and
left `M9.1` applied. The harness now **passes `-x` unconditionally** and installs a
**SIGTERM/SIGINT handler** that restores the in-flight mutation before exiting.

**`check_targets` refused twice, and both refusals were self-inflicted** — which is
the gate doing exactly the job D-048 built it for. `M2.3`'s bare `if at_search_edge:`
appears **twice** in the module (AMBIGUOUS); `M3.2`'s anchor was written on the
**wrong side of its own swap**, so it described a formula the source did not
contain (ABSENT). Both were caught **before any mutation ran**.

**The sweep found three genuine coverage gaps** — `M1.2` (the context-string claim
about the deleted placeholder was untested), `CX1` (`search_points` was never read
from config) and `CX2` (the `points < 2` floor was untested). `CX1`'s fixture is
worth recording: the leaf had to be moved to **777**, because **1001's grid step is
exactly `1e-3` and would not discriminate** between a config-read resolution and a
literal one. All three were closed with new tests and `CX` re-ran **3 / 3 killed**.
The three remaining survivors carry **executed** proofs — one **INERT BY
EQUIVALENCE** and two **INERT BY UNREACHABILITY** — and `M9.1` survived as the
**honesty control**. Final: **25 / 25 applied, 21 killed, 4 classified, `EXIT=0`**.

**Both honours were discharged.** The cross-check against the binary closed form
was built **from the start** (the brief's second requirement) and is what makes the
grid's resolution a *measured* property rather than an asserted one. The sweep was
**re-run at close** (the first requirement) and returned an **identical** result
(**25/21/4**) — and this time `ruff format` touched nothing in between, which is
exactly why D-051's third-harness-defect scenario did not recur. The generalisable
form stands as lesson 50: **a transcribed harness target is a copy of the source
that no gate keeps in sync — only re-running the harness at close does.**

**Tier 3 is complete.** The compositional suspects the earlier narrative flagged —
the two path-gate functions — were built with cross-checks from the start, and
neither was where the hazard actually was. Across the five closing increments the
same shape recurred: **read every declared number for what it is a measurement
of, and read every contract for who consumes it, before reading the code for what
it does.**

Then **Tier 4** (11 functions) — which gates Phase 3, because
`build_us_macro_thesis` is a Tier 4 function and the Phase 3 checklist also
lists it. That overlap *is* the phase seam.

Then Phase 3 — the thesis layer (§7) and the API layer (§8).

### Carry-overs still owed

| Item | Since | Note |
|---|---|---|
| ~~`docs/MODULE_MAPPING.md`~~ **CLOSED 2026-09-17** | Session 4 | Written, and **generated from the code** rather than transcribed from the specification — which is what it is for, since the specification has been corrected 45 times. Resolves the longest-standing item. |
| ~~A structural guard against the property-vs-field collision~~ **CLOSED 2026-09-17** | D-035 | Implemented in `tests/test_infrastructure.py` and asserted against a deliberately broken model. **The first version was inert**: it intersected `model_fields` names with `property` objects in `vars(klass)`, and pydantic 2.13 *consumes* the property — storing the property object as the field's default and deleting it from the class dict — so that intersection is **provably empty**. The surviving signature is `isinstance(model_fields[name].default, property)`. See D-045. |
| The regime **inflation axis** is a near-constant (`rising` in 93.75% of 240 real quarters) | D-045 | Recorded as **O-23**. A defect in the *input definition*, not the grid: `inflation_trend_3m` is a 3-month annualized change, so its sign measures the price level's drift rather than momentum. Four states are rare by construction. Measured alternatives (12-month change of the YoY rate: 124/10/106) exist and are recorded; swapping the input redefines a §6.2-declared input, so it awaits an explicit decision. Disclosed on every output meanwhile. |
| **§15.19-D's integration requirement is unwired** | D-047 | The section obliges every convergence classifier to call `count_independent_families()` and use that count — **not** the number of agreeing signals — as its confidence denominator. None of those callers existed when D-046 shipped, so the `source_independence_count=0` sites (**26 of them, measured after D-047**; D-046's "~15" was an estimate and was low) were *suppliable* but not *supplied*. **THE FIRST CONSUMER IS WIRED as of D-047:** `inflation_convergence_classifier` tags its six inputs, calls the census, and passes the family count to `compute_confidence()`. **Still open for `classify_convergence` and the remaining convergence classifiers** — each must be audited, and `source_independence_count=0` at a call site that *could* supply a family count is now a defect, not a starting state. **Measured after D-047: 26 sites across 14 modules**, of which one (`evidence.py`) is the legitimate self-census. They should be re-checked one per increment. **A SECOND CONSUMER IS WIRED as of D-050:** `four_pillar_scorecard` takes tagged `PillarRead`s, calls `_pillar_census`, and passes the measured family count to `compute_confidence()` — and it removed the specification's `independent_source_families: int` parameter, so the raw-signal-count error is *unrepresentable* rather than merely discouraged. **FOUR CALLERS as of D-051:** `classify_convergence` takes an arbitrary `list[ModelResult]`, filters to the DIRECTIONAL subset, calls `count_independent_families()` on it, and passes the measured count to `compute_confidence()` — publishing the neutral-only families it excluded so the exclusion is visible. The increment also **corrected D-050's own caller**: `four_pillar_scorecard`'s census had counted neutral pillars, so one directional pillar plus three neutral ones read `HIGH` instead of `LOW`. The remaining convergence classifiers still owe this audit. |
| Module 7.3.1 — the `GdpNowcastSettings` accuracy block is a *snapshot* | D-034 | The accuracy figures are a measurement over a fixed 137-quarter window. The live check recomputes every one of them, so drift is detected, but Phase 5+ should make the window a config parameter rather than a constant the code reconstructs. Recorded as **O-12**. |
| FRED `GDPNOW` is a settled per-quarter record, not a real-time nowcast | D-034 | Recorded as **O-13**. The cross-check gap cannot be interpreted as a nowcast error without a real-time vintage store. |
| `indirect_bidder_pct` accepts a fraction passed as a percentage | D-036 | The `[0, 100]` bound does not catch `0.55` meaning 55%, and the error reads as a demand collapse. Recorded as **O-14**; needs a cross-field scale check or a units convention. |
| No when-issued yield source | D-036 | Recorded as **O-15**. Needs a real-time market-data vendor; out of scope for a free OpenBB build. Until then the tail is manual and the live check cannot validate it. |
| **Seven older sweeps lack the `check_targets` gate** | D-048 | Recorded as **O-29**. The gate exists in `mutation_trilemma.py` and `mutation_yield_curve.py` only. The four older sweeps (`mutation_regime.py`, `mutation_evidence.py`, `mutation_inflation_convergence.py`, and the Tier 1/2 scripts) can silently rewrite the wrong function and report a weak test — D-031's **mis-targeted** class. The fix is mechanical: port `check_targets` verbatim into each. |
| **The duration dimension is not monotone, and the cap hides it** | D-049 | Recorded as **O-31**. Over 592 observations the conditional rate is `0.250 / 0.286 / 0.412 / **0.769** / 0.520` by duration bucket: it peaks at 26-52 weeks and falls beyond. The configured 26-week cap sits at the peak, so the function never enters the contradicted region. The finding survives a censoring control. **No cap placement fixes this** — moving the cap exposes the contradiction instead of resolving it — so the open item is whether the duration factor should saturate at all, and it needs an explicit decision. Disclosed on every saturated output meanwhile. |
| **Three published keys are one predicate** | D-052 | Recorded as **O-37**. `gold_call` and two equity reads all derive from the single `bonds` direction, so a consumer counting outputs sees three corroborating calls where there is one cause. `driver_channel` discloses the coupling, but only in prose-adjacent form; whether `value` should carry a machine-readable `derived_from` per key is not settled. |
| **A `measured_*` leaf's population lives in prose** | D-052 | Recorded as **O-38**. Two leaves were unverifiable — and one was wrong — because the population they were measured over was stated in a note rather than stored as data. The live check now recomputes and drift-diffs them, which is what caught it, but the leaf itself still cannot say what it is a measurement *of*. |
| **`beta` is an OLS estimate on 290 months, not a calibrated structural parameter** | D-053 | Recorded as **O-40**. `beta_core_inflation_pp_per_score_point = 0.006` comes from a single full-sample regression (`se 0.00159`, `t +3.76`, `R² 0.047`). It is stable across three subsamples and survives detrending, so it is not an artefact — but it is a **reduced-form** number with no theory behind the point estimate, and the `R²` means **95% of the variance in the 6-month forward change is not explained by this score**. It is published on every output with the horizon structure (positive at 3-9 months, reversing at 24). Phase 5+ should either calibrate it structurally or replace the point estimate with a coefficient **distribution**, so the confidence reflects estimation uncertainty rather than only data-quality flags. |
| **A config pair whose values are only meaningful jointly** | D-053 | Recorded as **O-41**. Lesson 48's band/beta case is the first instance, but the check that catches it is local. A project-wide audit should grep `config/settings.yaml` for other leaf pairs where one value's *natural unit* is derived from the other (any `_per_*` leaf beside the thing it is per). Whether this warrants a structural guard — as the property-vs-field collision got in D-045 — is not settled. |
| ~~**`_EXPECTED_INERT` emptied is a stronger claim, and it is not enforced**~~ **DISCHARGED for the live path, 2026-09-18** | D-053 → **D-056** | Was recorded as **O-42**.  The sweep for this increment deliberately lists **zero** expected-inert mutations, which says nothing is excused from having a test. Nothing in the harness *requires* that discipline — a future increment could quietly repopulate the set and excuse a survivor. Whether an empty set should be the required default, with an explicit argued exemption for each entry, is a policy question. |
| ~~**D-054's cross-check is a re-implementation, not a call**~~ **CLOSED 2026-09-18** | D-054 → **D-056** | Was recorded as **O-43**.  `live_drawdown_check.py`'s Section 4 checks three structural invariants shared with `volatility_target_scaling` (§20.13), but the vol-target side is a **local re-implementation of the shape** because the function does not exist yet. The invariants are therefore checked against my reading of §20.13, not against the shipped code — a restatement, not a cross-check (lesson 5's distinction). It must be re-pointed at the real function in the `volatility_target_scaling` increment. |
| **`.probe/` makes the unscoped `ruff check` number unusable** | D-054 | Recorded as **O-44**. `uv run ruff check` with no path reports **711 errors**, all in the untracked `.probe/` scratch directory created by this project's probe-first workflow. The project's real gate is `ruff check src tests tools scripts` (clean), which is what every increment runs — but a reader who runs the obvious command gets an alarming number that means nothing. Either `.probe/` should be added to `pyproject.toml`'s `exclude`, or the probe convention should be documented at the top of the gates table. Mechanical fix; not yet done. |
| **`RiskLimits.max_drawdown_trigger_pct` restates this ladder's first rung** | D-054 | Recorded as **O-45**. §17.3 declares `RiskLimits` with `max_drawdown_trigger_pct: float = 0.10` — **fraction convention** — while `evaluate_drawdown_rules` reads `risk.drawdown_thresholds.tiers`, whose first rung is `10.0` **percent**. Two configured triggers for the same event, in two conventions, with **no stated precedence**. One of them is now consumed; the other is a config surface with a reader and no consumer, which is the D-037 class. It must be resolved in the `volatility_target_scaling` increment, which also touches `RiskLimits`. |
| **A sweep killed mid-run leaves the tree MUTATED, silently** | D-060 | Recorded as **O-61** (severity 3, **incident**). Running the sweep set in **batches in the background** meant one batch was killed mid-flight, leaving `inflation_nowcast.py` holding `vintage_index_from_end = lag_months` (shipped: `+ 1`) and `convergence.py` holding `opposed = up > 0 or down > 0` (shipped: `and`). The leak was **silent** because a sweep whose anchor no longer matches takes the **pattern-not-found** path and reports a **survivor**, not an error — so two falsified copies read as two weak tests. It surfaced only in a later full-suite run as **8 failures in modules D-060 never touched**, and the first hypothesis ("stale anchor") produced **wrong edits to an anchor and a new test**, both reverted. **Binding rule: never sweep in the background; never batch sweeps.** Open remedy: a **clean-tree precondition** — refuse on a dirty tree instead of certifying it. |
| **Three sweeps are broken and there is no sweep-health check** | D-060 | Recorded as **O-62**. A full walk of `scripts/`: `mutation_drawdown.py` exits **2** (four AMBIGUOUS anchors in `risk_budget.py`, D-055 class); `mutation_credit_spread.py` exits **1** with an **unexplained survivor** `C1d` (`observations_measured` hardcoded `0` — the D-046 shape, a **real missing test**); `mutation_convergence.py` was exit 2 *only* from O-61's leftover and is **CLOSED** at `56/53/3`. `mutation_curve_trade.py` was broken by **D-060's own sibling class** in the same file (the **D-051** trap) and was **repaired**, reproducing `31/26/5` exactly. The project's **strongest** gate is the one nothing gates: nothing runs all sweeps and nothing checks that any one **ran**. Remedy: a single **sweep-health check** run at every close, failing on exit 2/4, on an unexplained survivor, or on a count differing from the recorded baseline. Recorded, not fixed — neither broken sweep is D-060's module. |
| ~~**`.probe/` makes the unscoped `ruff check` number unusable**~~ **SUPERSEDED by O-63** | D-054 → **D-060** | Was recorded as **O-44**. It is the same defect seen whole: ruff has **no `files` key** at all (mypy does — §10.2/D-035), so a bare invocation walks the entire repository including `.probe/`. The number grew from **711** (D-054) to **1703** (D-060) as the tree grew, which is what made the underlying shape visible. Now **O-63**, with a `pyproject.toml` comment recording the requirement and a gate script as the open remedy. |
| ~~**Three sweeps are broken and there is no sweep-health check**~~ **PARTIALLY DISCHARGED 2026-09-18** | D-060 → **D-061/D-062** | Was recorded as **O-62**. All three broken sweeps are repaired — `mutation_credit_spread.py` rebuilt (**34/33/1**), `mutation_drawdown.py`'s four AMBIGUOUS anchors re-anchored (**47/46/1**, reproducing D-054's original), `mutation_convergence.py` closed at **56/53/3** — and the missing gate now exists: **`tools/sweep_health.py`** reports **30 sweeps, 0 failures, 0 leftovers** and names the **14 that still carry no gate** (O-29). It found a live leftover (`MX3d`) on its first real use. **Still open:** it runs by hand, not in CI, and it cannot see a sweep whose anchors resolve but whose tests no longer kill. |
| **`check_targets` proves an anchor is UNIQUE, never that it is in the RIGHT function** | D-062 | Recorded as **O-67**. The first run of `mutation_cross_market_rv.py` reported `M8.1` as a survivor; its anchor occurs **first in `curve_slope`**, so the mutant rewrote a neighbour whose tests are not in the selection. An audit found **three** mis-targets. The new `check_anchor_landings` gate refuses on it, and only one sweep has it. **This is the second mis-target in one session** (`C1d` was the first) — back-port it everywhere. |
| **§20.12 labels a US-only constructor's output `country="global"`** | D-062 | Recorded as **O-64**. `ModelResult.country`'s own description says *'"us" only through Phase 4'*. The function now publishes `"us"`, but the **specification text** still says `global`. |
| **`risk.stress_correlation = 0.9` is not reproducible from any measured pair** | D-062 | Recorded as **O-65**. Worst measured \|stressed correlation\| is 0.858 (S&P tail) / 0.736 (VIX tail); the normal correlations run −0.623 .. 0.820. The leaf overstates, and as §20.12's default it makes the published degradation negative on every real pair. |
| **No `ThesisType` names a cross-market relative-value trade** | D-062 | Recorded as **O-66**. `construct_cross_market_rv` has **no route** in `select_instrument`, so unlike D-059/D-060 the seam cannot be closed. |
| **The LTCM hard gate is a PRESENCE check on a field whose sentinel is a valid presence** | D-063 | Recorded as **O-68** (severity 3). `TradeIdea` accepts the specification's fallback sentence, so a live trade whose stated falsifier is "no falsifier was found" passes. Repaired for this caller (empty `text`), open for any other. |
| ~~**§16 names three different inflation models for one argument slot**~~ **SUBSTANTIALLY CLOSED for the code 2026-09-19** | D-063 → **D-066** | Was recorded as **O-69** (`inflation_breadth_score` at Q1, `inflation_convergence_classifier` in §20.15's docstring, `"inflation_convergence"` in `build_confirmation_signals`). D-066 measured the full surface — **six distinct labels across three spec locations, one in common, and `curve_slope` never a parameter** — and the shipped function now **derives every label from `result.model_name`**, with the slot name as a fallback for an empty `model_name` only. **What remains open is the specification's own text**, which still names three inconsistent sets. |
| ~~**The Q8 round-trip is asserted against a hand-built `TradeIdea`**~~ **CLOSED 2026-09-19** | D-063 → **D-069** | Was recorded as **O-70**. `build_us_macro_thesis` did not exist, so the caller's seam was untested. **D-069 shipped the caller:** it passes `invalidation.text` (not the assessment) and routes to `no_trade_thesis(...)` when `identified` is False — the third of three ordered gates. Tests: `test_q8_fires_when_nothing_can_be_read_and_hands_over_the_assessment`, `test_q8_running_third_means_q6_and_q7_both_had_to_pass_first`, `test_no_stand_down_leaves_a_falsifier_that_satisfies_the_ltcm_gate`, plus the live suite. Retained for the audit trail. |
| ~~**O-50's `payoff_unit` seam is silently defaulted**~~ **CLOSED 2026-09-19** | D-064 | Was recorded as **O-50** (partial, carried by D-057). The field `payoff_unit: Literal["fraction_of_capital"] = Field(description=...)` had **one member and no `default=`**, so pydantic treated it as optional and a `bp_pnl_proxy` distribution was accepted and relabelled `fraction_of_capital`. Now **required**, with the vocabulary widened to `KellyPayoffUnit` and a **named refusal** for the wrong unit; `mutation_kelly.py` extended 25 → 27 to cover both halves. **What remains open is the class, not the instance**: any *other* closed vocabulary whose producer can emit a member its consumer's `Literal` excludes is still silent. |
| ~~**`ScenarioOutcome` / `MarketPricingGap` existed twice**~~ **CLOSED 2026-09-19** | D-064 | Was recorded as **O-51**. The models layer and the thesis layer each declared the pair, so a change to one could not be seen by the other. Now **re-exported from the models layer**, so they can no longer drift. |
| **The scenario distribution is DIRECTION-BLIND** | D-064 | Recorded as **O-71** (severity 3). Measured on live data: a gap of **+1.0%** and one of **−1.0%** produce **byte-identical payoffs and probabilities**, so the four outcomes do not depend on which side of the market the model is on. Invisible to all 38 unit fixtures because every one of them used `+1.0`. Whether the fix is a sign-symmetric relabelling or a genuine directional branch is a **modelling decision** (it changes what the four outcomes *mean*), so it is recorded rather than guessed — but the current output is **disclosed** on every call. |
| **`check_anchor_landings` is not yet back-ported** | D-064 → **O-67** | The gate exists in **two** sweeps (`cross_market_rv`, `scenario_distribution`) and its **first version was itself a defect** — it resolved the owning symbol by matching `line.startswith(("def ", "class "))`, which is true of a comment, and refused four sweeps over a mis-target that did not exist. Fixed by `ast.parse` + `end_lineno` in `tools/sweep_health.py` and inlined into the new sweep. **O-67 stands and is now sharper**: back-port the FIXED version, not the original. |
| **`sweep_health.py` still runs by hand, and cannot see a *stale* kill** | D-064 → **O-72** | New. The tool proves a sweep **loads**, its **anchors resolve**, and no mutation is **left applied** — it cannot see a sweep whose anchors resolve but whose selection no longer **kills** anything (the D-051 trap, where the first `curve_trade` run reported 31/31 killed on a broken baseline). It also runs by hand, not in CI. Cheap partial remedy: have it execute each sweep against a **deliberately broken baseline** and require a non-zero exit; not done. |
| **`Literal[*get_args(...)]` cannot be a mypy type alias** | D-064 → **O-73** | New, minor. The consumer vocabulary is written out and **enforced by a test** (`set(get_args(KellyPayoffUnit)) == set(get_args(PayoffUnit))`) rather than derived in the type system, because `mypy --strict` rejects the computed form (*"Invalid type alias: expression is not a valid type"*). The test is strictly weaker than a type and **louder** than a silent drift; recorded so the trade-off is deliberate rather than forgotten. |
| **The catalyst calendar depends on two live third-party hosts at thesis-build time** | D-065 → **O-74** | New. `next_catalyst_calendar` makes up to **four HTTP requests** (three FRED release windows + the Fed's FOMC page) and a thesis build now blocks on them. `httpx` timeouts (30s each) bound this, and a source failure **omits** its catalyst rather than failing the build — so the failure direction is a **silently shorter calendar**, which is the D-054 shape one layer up. What is NOT done: **caching**. FRED's release dates change rarely and the FOMC page changes four times a year, so a thesis built twice in an hour re-fetches everything. A cache with a stated TTL is the obvious remedy and is recorded rather than guessed. |
| **Whether `120` days is the right horizon is uncalibrated** | D-065 → **O-75** | New. `horizon_days` is `uncalibrated_illustrative` and the sweep can only prove the leaf is **read**, not that it is **right**. A 6-12 month thesis needs its first scheduled test visible, but no measurement is behind the number. Distinct from the usual uncalibrated-leaf note because the *failure* is asymmetric: too short and the calendar omits a real catalyst (silence), too long and it lists events beyond the thesis's own timeframe (noise). |
| **The FOMC projections marker is surfaced as text, not as a datum** | D-065 → **O-76** | New, minor. §16.4 says "FOMC meeting **+ dot plot**", and the Fed's page marks projections-carrying meetings with an `*`. The function renders that as the substring `" + projections"` inside a display string, so a consumer wanting to *branch* on "is this a SEP meeting" must **re-parse our prose** instead of reading a field. `TradeIdea.catalysts` is typed `list[str]`, so there is nowhere to put a flag today — the fix is a typed catalyst object, which is a schema change and therefore a separate increment. |
| **`direction` has no `unreadable` member, so an unread input is indistinguishable from a read-and-neutral one** | D-066 → **O-77** | New, severity 2. `ConfirmationSignal.direction` permits exactly three members (§22.10 / Finding #10), and the increment's repair routes every unreadable value to `neutral`. That is strictly better than §16.4's fall-through (which claimed `contradicts`), but a consumer reading `signals` alone **cannot tell "this model is balanced" from "this model could not be read"** — the distinction survives only in `ConfirmationSignalAssessment.unreadable`, which a caller that takes `.signals` will drop. The correct fix is a fourth member, which is a `MacroThesis` schema change (§22.13) and therefore a separate increment. Disclosed in the module docstring and pinned by a test; recorded rather than widened. |
| **The warning count is appended to `detail` as prose, so it cannot be branched on** | D-066 → **O-78** | New, minor. §16.4's `detail` is the model's own interpretation string, and the increment appends `(<n> warning(s))` under a stable module-level token when the upstream result carries warnings. That makes the caveat **visible** (the D-066 defect being that a signal could undercut itself unflagged), but a consumer wanting to know *whether the model warned at all* must parse our prose — **O-76's shape in a second field**, and the same class: `ConfirmationSignal` has no `warnings` field to put it in. A typed field is a schema change. |
| **`build_confirmation_signals` reads a `MarketPricingGap` that Q1 may route away from** | D-066 → **O-79**, **CLOSED by D-069** | **The ordering is now ENFORCED.** `build_us_macro_thesis` evaluates Q6 **first**, and `not gap.is_meaningful` returns a `gap_below_dispersion` stand-down **before** `build_confirmation_signals` is called — so the function is no longer reachable with a zero gap through the production path, and its totality-on-inputs is a **second line of defence** rather than the only one. Tests: `test_q6_fires_before_q7_so_the_convergence_field_records_never_classified`, `test_the_three_gates_produce_three_distinguishable_theses`. **What remains open** is that the ordering lives in the builder's control flow, not in a type — a future second caller could still skip Q6. That is caller hygiene, not a missing caller. |
| **A suite and a mutation sweep run concurrently produce FALSE failures** | D-066 → **O-80** | New, severity 2. While recording D-066 the full suite was backgrounded **while the sweep was still mutating `signals.py`**; it reported **2 failed / 1752 passed** on exactly the two tests the sweep's `M2` mutant rewrites, and **1754 passed** five times once the sweep finished. **O-61's clean-tree precondition turned on the increment's own recording step.** The project has **no test-order randomisation**, so a failure that moves between runs means a **concurrent writer** — not a flaky test. Nothing enforces serialisation; the diagnosis procedure is recorded as lesson 5ay. |
| ~~**Section 21.4's blocked class still has no CALL SITE**~~ **THE CALL SITE NOW EXISTS — CLOSABLE** | D-067 → **O-81**, **advanced by D-069** | The mechanism (`UnattributedWarning(origin="blocked_input")`) was built and tested but **no production call path passed it**. **D-069 shipped the call site**: `build_us_macro_thesis` takes `unattributed: Sequence[UnattributedWarning] = ()` and passes it to `collect_all_warnings` on **every** return path, **including all three stand-downs** after the `_render` fix; the live check measures `warnings=13` reaching the published thesis. **What remains open:** the builder deliberately does **not** walk the registry itself (lesson 99 — doing so would make the obligation *look* discharged), so the §8 API layer must construct the argument. |
| **Section 5.4's data-quality flags still do not reach any model's own warnings** | D-067 → **O-82** | New, severity 2. Measured live: **5 of 5** snapshot flags are absent from the aggregate. The flag currently only *lowers confidence* (D-033 / §22.8) and is never surfaced as text; it survives in `MacroThesis.snapshot_quality_flags`, so nothing is lost — but §21.4 says *warnings*, and warnings does not get it. The wiring lives in the **models layer**, so no change to `warnings.py` closes this. |
| **`tools/sweep_health.py`'s leftover scan is SCOPED, not blind** | D-067 → **O-83** | New, severity 3, **incident**. The leftover check is **per-sweep**: it looks only for mutations that *the sweep being checked* declares. Measured live: D-064's `M6.3` mutant (`if False:` in `config.py`'s `_remaining_shares_must_sum_to_one`) was **still on disk** and the tool reported **0 leftovers**, because `config.py` is owned by the **scenario** sweep — which was target-clean only because the mutation had **already fired**. The constraint was restored by hand and the scenario sweep then ran **23 applied / 22 killed** (it had been refusing on the absent anchor). **O-61's family with a new mechanism: the gate was not blind, it was scoped.** The remedy — a whole-tree scan of `src/` for the `if False:` shape — is a one-line change and is **not yet implemented**. |
| **`iorb`'s future-date tolerance is checked against a FROZEN clock** | D-067 → **O-84**, **DIAGNOSIS CORRECTED by D-069** | **The frozen-clock diagnosis was WRONG.** The failure text names its own comparison — *"observation_date 2026-09-21 is after retrieval date 2026-09-19 by 2 day(s), beyond this series' declared tolerance of 1"* — and the retrieval date is **today**, so the check **is** evaluated against the current date and does **not** decay with cache age. **The real finding: FRED publishes `iorb` 2–3 days ahead of the calendar** while the series declares `future_date_tolerance_days: 1` (a tolerance sized for the documented **1-day** UTC-boundary case). The ERROR path is **armed and firing correctly** — this is the guard working. **Fix is a data-layer decision** (widen, re-point, or declare `forward_looking`). **Lesson: D-067 inferred the comparison from the symptom instead of reading the error message that stated it.** |
| **The no-trade trigger is an unchecked CLAIM by the caller** | D-068 -> **O-85**, **REDUCED by D-069** | Severity 2. `no_trade_thesis` records the `trigger` it is told and the `evidence` it is handed, verifying neither. **D-069 reduces it to a one-call-site problem:** the builder branches on the gate it **actually observed** and each branch calls a dedicated helper (`_q6_decision` / `_q7_decision` / `_q8_decision`) that **owns its own trigger literal in its own body**, so the trigger is produced beside the condition that justifies it and a deviation is unrepresentable at that call site. **What remains open** is that the *function* still accepts a caller-supplied trigger, so a different future caller can still misdescribe a stand-down. |
| **`status=WATCH` cannot distinguish 'no edge' from 'waiting'** | D-068 -> **O-86** | New, minor. Section 16.4 sets `WATCH` for a no-trade, and `WATCH` is also what a live thesis carries before promotion. The new `trigger` field distinguishes them **on the decision object**, and the rendered warning line carries it into `MacroThesis.warnings` - but a consumer reading only `MacroThesis.status` still cannot tell a stand-down from a pending thesis. The remedy is a thesis-level field or a status member, i.e. a `MacroThesis` schema change (Section 22.13), so it is a separate increment. |
| **The `O-61` class recurred FOUR times in D-064, and the last was the worst** | D-064 | Existing incident, **re-confirmed at the highest severity yet — now the strongest argument for the clean-tree precondition.** A `SIGTERM` on the kelly sweep bypassed the `finally` restore and left `M9.1` applied in `risk_budget.py` (`clipped = bool(final_fraction < requested) is True`), which **also corrupted two unrelated anchors** whose text it had destroyed — `check_targets` then reported them ABSENT, a *false* finding of exactly the kind lesson 88 names. **An earlier restore fixed the anchors but LEFT the `clipped` line mutated**, and a later `ruff format` run **baked the residue into the record set**. It was caught only at close-out because the kelly sweep reported **25/27** with two mutations **"NOT APPLIED (no-op)"**. Three aggravating facts: **`sweep_health.py` reported 0 leftovers BOTH before and after** (it searches for the mutation's *replacement* string, which was the corruption — **O-72** demonstrated, not theorised); the sweep **still certified** at 25/27 with 0 survivors, because a no-op silently left the denominator; and **every gate was green on the corrupted tree** — ruff, format, mypy and **1705 passing tests** — since `bool(x) is True` equals `x` for a `bool`, so **no test could fail**. Restored and re-verified (**27/27**). **New remedy this increment produced: a sweep should REFUSE when any mutation reports `NOT APPLIED`, rather than dropping it from the denominator and certifying.** |

---

## Next (2026-09-18, after D-062) — Tier 4 #5, and the standing obligations

**Where we are.** Tier 4 stands at **4 / 11**; Phase 2 at **79 / 98 (81%)**.
**Module 15 is complete** — `select_instrument` (D-058), the curve constructor
(D-059), the breakeven constructor (D-060) and the cross-market RV constructor
(D-062) — which means the instrument half of Tier 4 is done and the remaining
six are the thesis layer (four) and its supporting construction (two).

**Tier 4 remaining, in §21.3 order:** `build_scenario_distribution` ·
`next_catalyst_calendar` · `build_confirmation_signals` · `collect_all_warnings` ·
`no_trade_thesis` · `build_us_macro_thesis`. Four of these are **Phase 3**
functions and `build_us_macro_thesis` is the phase seam.

**The standing obligations that now have a home in the loop:**

1. **Run `tools/sweep_health.py` at every close.** It is cheap (seconds, no
   mutation) and it is the only thing that runs the gates' own gates. It caught a
   live leftover on its first real use — and again in D-064, where a `SIGTERM` left
   a control mutation applied in `risk_budget.py` for the **third** time (O-61).
2. **Re-run every sweep whose file you touched, and the neighbours'.** D-060 and
   D-062 both added a constructor to a file holding two swept siblings; both times
   the *sibling's* counts had to be re-confirmed (they reproduced exactly:
   `31/26/5` and `26/23/3`).
3. **`check_anchor_landings` should be back-ported** to every sweep that has
   `check_targets` (**O-67**). Two mis-targets in one session is a rate, not an
   accident. D-064 found it was **itself manufacturing findings**, which is the
   warrant for auditing the gates rather than trusting them (lesson 80).
4. **Read every declared number for what it is a measurement OF** — and when you
   write one, let the live check measure it back. D-062's live check corrected a
   config note **in the same increment that wrote it**; so did D-064's, which
   found a defect (**O-71**, direction-blindness) that no unit fixture could have
   carried because every fixture used the same sign.
5. **A declaration that looks like it validates may not.** `Literal["x"] = Field(
   description=...)` with no `default=` is **still optional**; the fix is either
   `default=` or a named validator, and the difference is invisible until the wrong
   value is actually passed (D-064's headline).

**Where to expect the hazard next.** The remaining six are **composition**
functions: they assemble outputs from other models rather than doing arithmetic,
so the D-050/D-052 **composition defect** (an earlier gate consuming every input a
later one differs on) is the live risk — and `collect_all_warnings` is literally a
summariser, which is the D-027/D-046 **"a summariser must not be scored by its own
output"** class. `build_us_macro_thesis` composes all of them, so it inherits
every published key's contract — including the two D-064 leaves it must now pass
through: `invalidation.text` (empty ⇒ the gate fires ⇒ route to
`no_trade_thesis`) and the scenario distribution's `payoff_unit`, which it must
declare explicitly rather than inherit.

### Lessons 72-80

**72 — `check_targets` proves an anchor is UNIQUE, never that it is in the RIGHT
function.** `M8.1`'s anchor, `confidence=compute_confidence(`, occurs first in
`curve_slope`. The mutant rewrote a neighbour whose tests are not in the
selection, so the sweep reported a **weak test about code nobody had mutated**.
An audit found **three** such anchors in one sweep. The remedy is a landing-site
gate, and `_slice_source` gained an `after=` scope parameter so an anchor can be
*scoped* to a function rather than merely being unique in a file.

**73 — a diagnosis carried in a record is a hypothesis, and this one was wrong.**
D-060's audit recorded `C1d` as "a REAL missing test". Executing the gate the file
lacked showed it was a **mis-target** plus two anchors D-043 had staled, and that
the test which would kill a correctly-targeted `C1d` **already existed** (measured:
exit 1 vs exit 0). **The brief repeated the record's diagnosis, and the record was
the thing that needed checking.**

**74 — a tool that restores a file must restore its BYTES, not its content.**
`Path.write_text` translates `"\n"` to `os.linesep` while `read_text` normalises,
so the round-trip is stable in memory and lossy on disk. Every sweep in the repo
was silently converting its target to CRLF, and `git status` reported whole-file
modifications with **no content change** — which destroys the clean-tree
precondition that the sweep gates depend on. **A tree that is dirty for an
invisible reason is worse than no version control at all.**

**75 — a golden case exact by construction cannot test its inputs.** D-062's first
cross-check priced both legs at par (`coupon == yield`), so `shipped/exact` was
exactly `1.000000` and the section proved nothing while looking green. Off-par
legs give `1.175291 = P_b/P_a` and a **+17.53%** under-hedge. Pair every
by-construction case with a non-cancelling asymmetric one.

**76 — a live check can correct a config leaf in the SAME increment that wrote
it.** The `max_abs_hedge_degradation` note claimed "about 3x headroom" from the S&P
tail; the check's own headroom assertion counted the VIX tail and reported
**1.56x**. Every prior instance of this class (D-052, D-053, D-060) was caught
*after* the leaf shipped. **Write the assertion that measures your own claim, in
the same increment.**

**77 — a two-signed correction cannot be hedged by a constant, and this is now the
THIRD constructor with that shape.** O-57 (the curve trade), O-59 (the breakeven)
and O-62's measured `|degradation|` (3 of 8 negative on one stress definition, 4
of 8 on another). The tell is the same each time: **the specification states a
rule unconditionally and the measured correction changes sign inside the real
configuration space.**

**78 — the failure-direction taxonomy gains a fifth entry: FALSE REASSURANCE.**
D-054 silence · D-056 false confidence · D-057 prudence · D-058 false executability
· **D-062: the number says the risk fell when the risk rose.** It is the hardest
to see because the output is not merely wrong, it is *comforting* — and it arrives
attached to the very warning that says the opposite.

**79 — an accessor with no consumer is where a default's effect hides.** Third
sighting: D-054's `drawdown_tiers` (a config surface nothing executed, which is
what made a 100× error invisible), D-056's `RiskLimits` (four of five fields with
zero references), D-062's `RiskSettings.stress_corr` (**zero callers anywhere in
the tree** until this function). **A config surface nothing reads cannot disagree
with anything** — so wiring it is not plumbing, it is the step that makes the
value's consequences observable.

**80 — a mutation whose replacement is the EMPTY STRING makes the leftover
detector vacuous.** `"".count` matches at every position, so
`old not in text and new in text` reported a deletion mutation as "STILL APPLIED"
on the sweep-health check's first run. A deletion has no replacement to look for;
it must be reported as **unverifiable** rather than as a leftover. **A detector
whose predicate is trivially true is worse than no detector** — it manufactures
findings, and findings are what make a gate ignorable.

---

## Next (2026-09-19, after D-067) — Tier 4 #10, and the no-trade hazard

**Where we are.** Tier 4 stands at **9 / 11**; Phase 2 at **84 / 98 (86%)**.
**The instrument half of Tier 4 is done** (Module 15, D-058/D-059/D-060/D-062) and
**four thesis-layer functions have shipped** (D-063's invalidation, D-064's
scenarios, D-065's catalyst calendar, D-066's confirmation signals).

**Tier 4 remaining, in §21.3 order:** `build_us_macro_thesis`.
**One function, and it is the phase seam** — it appears on both the Tier 4 and the
Phase 3 checklists, and that overlap is deliberate.

**D-066 and D-067 together changed the shape of the remaining work in one
specific way, and the two findings are the same finding at two scales.** D-066's
four defects were all *"a value that could not be read was reported as a value
that was read"* — a bare `else` turned "unreadable" into "contradicts", and a
label named a model nobody had called. D-067's seven defects are all *"a question
the return type had no slot for"* — the raiser count, the attribution, the two
denominators, and both mandatory warning classes. The generalisation is the same:
**a return value is a set of claims, and every claim it cannot express becomes a
claim it silently makes.**

**Every remaining function is a composition function**, and D-063/D-064/D-066 are
the evidence of what that means: their subject was not arithmetic but a
**contract**. D-066's four defects were a fall-through, an unfilled provenance
field, a rich-text field carrying a caveat it could not flag, and a return type
too narrow for its own question — **none of the nine pairing axes would have
found any of them.**

**Where to expect the hazard:**

- ~~**`collect_all_warnings`**~~ — **shipped as D-067.** The hazard it was
  expected to have it had, and the shape was right: de-duplication **did** drop
  the count (D-046 inverted, not repeated), and the repair **is** a typed bucket
  per question rather than a phrase. Two things were **not** anticipated and are
  the increment's real findings: **(a) both mandatory warning classes were
  structurally unroutable** — a §21.4 blocked input is not a `ModelResult`, so
  §16.4's signature could not carry it, and §5.4's flags never left the models
  layer; and **(b) the two defects are COUPLED**, so the obvious fix for one
  activates the other. A future summariser should start from the question
  *"which mandatory disclosures have no route into this function at all?"*
  before asking whether the arithmetic is right.
- ~~**`no_trade_thesis`**~~ — **shipped as D-068.** The hazard was **named
  exactly right** on the previous close: *"a reason code that cannot say which of
  the three triggers fired, which is D-067's shape one function on."* That is
  what it was, and the increment found **four more** on top of it — the sample
  body **does not run** (six required `MacroThesis` fields), the empty reason is
  **accepted**, and `stop_or_invalidation="n/a"` **satisfies the LTCM gate it
  stands down from** (measured live). The load-bearing-three-times framing was
  also correct; what was *not* anticipated is that the three triggers arrive as
  **three different object types** (a gap, a signal assessment, an invalidation
  assessment), so the repair needed a **union of evidence**, not just a better
  reason string. **The lesson for the next construction function: a function
  called from several places needs its callers' *objects* enumerated before its
  reason strings.**
- **`build_us_macro_thesis`** is the seam: it composes all of the above, and
  **O-70** already records that its Q8 call site must pass `invalidation.text`
  and route to `no_trade_thesis(...)` when nothing was identified. It must also
  now pass **`payoff_unit` explicitly** to the Kelly contract (D-064 made that
  field required, so a forgetful builder gets a `ValidationError` rather than a
  silently relabelled distribution — **the intended failure direction**) and
  **unpack `ConfirmationSignalAssessment.signals`** rather than taking Q7's
  return as a list (D-066). It must now **also** pass
  `collect_all_warnings(...)`'s `unattributed=` argument with the registry's
  blocked entries and the snapshot's quality flags (**O-81**/**O-82**), because
  the aggregate deliberately does **not** discover them itself and §21.4's
  obligation is currently unmet. **§16.2's Q1–Q8 sample now diverges from the
  shipped contracts in seven places**, and the builder is where all seven land. **D-068 adds one**: the Q6/Q7/Q8 call sites must now state the **trigger** they observed and hand over the **gate object** as `evidence` (**O-85**), which means the builder derives the trigger rather than accepting it — and the renderer supplies the six required `MacroThesis` fields the no-trade sample never could.

### Lessons 81-103

**81 — `ModelResult.value` is a UNION, so every comparison against it is a
narrowing question, not an arithmetic one.** §20.15 writes `inflation.value < 0`;
`inflation_convergence_classifier` publishes a **dict**; the result is
`TypeError: '<' not supported between instances of 'dict' and 'int'`. The same
section's `build_confirmation_signals` guards with `isinstance(result.value,
(int, float))` — **the two halves of §16.4 disagree about the contract they
share**, and the one that forgets is the one that decides what would falsify the
thesis. Reproduced on **real** data, not a fixture.

**82 — a gate that tests PRESENCE on a field whose sentinel value is a valid
presence cannot distinguish "found" from "not found".** `TradeIdea`'s LTCM gate is
`not self.stop_or_invalidation.strip()`, and §20.15's fallback — *"No clear
evidence-based invalidation condition identified — DO NOT promote this thesis past
DRAFT"* — is **non-empty**. Measured: `TradeIdea` **accepts** it. A live trade
whose stated falsifier is *"no falsifier was found"* passes the gate the falsifier
exists for. This is D-052's *"a coverage guard must be a PARTITION, not a HIT"*
reached through the schema. **A guard whose two states are both non-empty strings
is a guard for one state.**

**83 — a model can be NAMED for a condition it cannot express.** §20.15
attributes *"broad-based reacceleration"* to `inflation_convergence_classifier`,
whose vocabulary is `HIGH / MEDIUM / LOW / CONFLICTED` and whose `agreeing` field
is the majority **count**, not the majority **side**. A `HIGH` verdict is equally
compatible with six measures agreeing down and with six agreeing up: it is
**direction-blind**. **Read the model's own published vocabulary before
attributing a claim to it** — the sentence is plausible, the field set is not.

**84 — a mutant that does not change the program is not a test gap.** `M1.5`'s
first draft wrote `neutral.append(...) or unreadable.append(...)`. `list.append`
returns `None`, so `None or X` **still ran X**: the mutant appended to `unreadable`
exactly as the shipped code does, and survived. The fix was the mutation, not a
test. **Triage a survivor as `broken` before concluding `weak`** — this is the
same distinction D-062 had to draw for `M8.1` (a unique anchor in the wrong
function), and both were mis-read as coverage gaps on first sight.

**85 — a return type that cannot represent "nothing found" forces the caller to
encode it in prose, and prose cannot be a gate.** §16.4 declares
`derive_invalidation_conditions(...) -> str` and then, for the empty case, returns
a *sentence instructing the caller not to promote the thesis*. Nothing consumes
the instruction: `build_us_macro_thesis` sets `status=DRAFT` unconditionally, so
the function's strongest output is **inert**. Returning
`InvalidationAssessment` — with `identified: bool` and an **empty** `text` — turns
the sentence into a value the schema can act on. **When a function's output
includes an instruction to the caller, that instruction is a typed field the
caller has not been given.**

**86 — a one-member `Literal` with a description and no `default=` is still
OPTIONAL.** §16.4's `payoff_unit: Literal["fraction_of_capital"] = Field(
description=...)` reads like a validated declaration, and pydantic accepts it with
the field omitted — because `Field(...)` with only `description` supplies no
default and no requiredness. Measured both ways: the old declaration accepted
`KellyInputs(scenarios=<bp distribution>, limits=...)` **with no unit argument at
all** and labelled the distribution `fraction_of_capital`; the new one refuses.
**The defect is not that the value was wrong — it is that the *vocabulary had one
member*, so there was no wrong value to pass.** The repair has two halves and
neither alone is sufficient: widen the vocabulary to make the wrong unit
*nameable*, and make the field required **with a named refusal** so naming it is
what fails. **A closed vocabulary of size one cannot express its own
incompatibility.** (This closes **O-50**'s seam and is **O-51**'s class — a
duplicate `ScenarioOutcome`/`MarketPricingGap` pair re-exported from the models
layer, so the two layers can no longer drift.)

**87 — a derived type alias is a runtime fact, not a static one.**
`Literal[*get_args(PayoffUnit)]` is **correct at runtime** and `mypy --strict`
reports *"Invalid type alias: expression is not a valid type"*. Writing the
literal out is **weaker as a type** (nothing stops the two drifting) and
**stronger as a test** (a set-equality assertion over `get_args` fails loudly the
moment either side changes). It ships with the test, and the test is named for
what it enforces (`test_the_consumer_vocabulary_is_derived_from_the_producers`).
**When a property cannot be expressed in the type system, express it as a test
and say so in the name** — the alternative is a `# type: ignore` that hides the
drift it was added to prevent.

**88 — a gate can MANUFACTURE findings, and that is worse than having no gate.**
`check_anchor_landings` resolved an anchor's owning symbol by walking backwards
to a line beginning `def ` or `class ` — which is **also true of a prose
comment**. It therefore attributed `KellyPayoffUnit` to `volatility_target_scaling`
**150 lines away** and refused four sweeps over a mis-target that did not exist.
**A false positive in a gate teaches you to ignore the gate**, which is exactly
how a real finding gets skipped later. The fix is to resolve the owner by
**parsing** (`ast.parse`, with `end_lineno` bounding each symbol) rather than by
matching text. **A checker that reasons about code by looking at lines is a
checker that will eventually reason about a comment.**

**89 — an honesty control that cannot be APPLIED is not a control.** The new
sweep's control was written as `old == new`, so the harness never applied it and
it could be **neither killed nor survive** — and the harness **refused to
certify** on exactly that ground, which is the behaviour lesson 80 asks for. It
was replaced by a real rewrite that re-wraps the same three string literals across
three lines into a **byte-identical** value: the program is semantically
unchanged, so any test that kills it is testing text rather than behaviour.
**A control must change the source and not the program** — and when it cannot,
the honest answer is to say so rather than to pass.

**90 — a stale test can be the strongest evidence FOR the defect it was written
under.** The repaired control killed `test_the_distribution_is_consumable_by_the_
kelly_contract`, which the interrupted session had written to assert
`literal_error` while **omitting** `limits`. Tracing why showed the test could
**not have passed unless `payoff_unit` was optional** — the test's own shape was a
proof that the default was load-bearing, and it had been written by the session
that was about to certify the opposite. **When making a field required breaks a
test, read the test before rewriting it**: it may be the only artifact that
recorded what the field used to accept.

**91 — a fixture that holds one variable constant cannot falsify dependence on
that variable, however many fixtures you write.** `build_scenario_distribution`
was exercised by 38 tests and certified by a 23-mutation sweep; **none of them
varied the sign of the gap**, because every fixture used `+1.0`. Driving the
function from live data — where the measured gap is **negative** — produced
byte-identical payoffs *and* probabilities for `+1.0%` and `−1.0%`: the
distribution is **direction-blind** (**O-71**). **A number of tests is not a
coverage claim; only a varied input is.** The live check is not a formality that
follows the sweep — it is the only artifact that asks the question the fixtures
were not built to ask.

**92 — a recovered increment is a distinct failure mode: the tree is green and
the record is empty.** An interrupted session left the function, its tests, its
config block and a shared tool's repair on disk — and **no DECISIONS entry, no
PROGRESS update, no open-issue, no memory note**. Every gate passed on the code as
found, which is precisely why "it passes" is not this project's standard: the
gates answer *"does the code behave?"*, not *"is the increment complete?"*. What
the **record** caught that the gates could not: a `Literal` whose default was the
defect (lesson 86), a sweep whose control was a no-op (lesson 89), a stale test
that encoded the old contract (lesson 90), and a distribution no fixture had ever
asked to be sign-aware (lesson 91). **Treat an unrecorded tree as UNVERIFIED, not
as done** — and when you adopt someone else's finished-looking work, the first
thing to write is the record that says what it is.

**93 — a semantically identical leftover can survive EVERY gate, and the sweep
that should catch it certifies instead.** `M9.1` was left applied by a `SIGTERM`,
so `risk_budget.py` shipped

```python
clipped = bool(final_fraction < requested) is True   # mutated
clipped = final_fraction < requested                 # shipped
```

The two programs are **the same function** — `bool(x) is True` equals `x` for a
`bool` — so no test could fail, and none did: ruff, format, `mypy --strict` and
**1705 passing tests** were all green on the corrupted tree. The residue was then
**baked in by a later `ruff format`**, which is the increment's own anchor-drift
remedy (D-058's `CX4`) working *against* it. Three lessons compound here.
**(a) A no-op is not a survivor.** The sweep reported **25 applied / 27** — two
mutations "NOT APPLIED" — and then **certified**, because a no-op silently leaves
the denominator instead of failing it. **A harness must REFUSE when an anchor no
longer matches its own source**, since that is precisely the state a leftover
produces. **(b) A leftover detector that searches for the REPLACEMENT string is
blind to exactly the leftover it exists for.** `sweep_health.py` reported 0
leftovers before and after, because `M9.1`'s replacement **was** the corruption —
so the tool's evidence of cleanliness was produced by the defect (**O-72**).
**(c) An equivalence-preserving mutation is the only kind that can hide here**, so
the honesty control is the one mutation whose survival is *required* — which makes
the control's own residue uniquely undetectable by tests. **The remedy cannot be a
test; it can only be a precondition** — verify the tree against a known-good
baseline *before* mutating it. This is why O-61's open item is a clean-tree
precondition rather than another assertion.

**94 — a data source can be structurally wrong in a way that returns plausible
data, and no fixture can see it.** D-065's five source defects were not bugs in
our arithmetic; they were facts about two live endpoints that all five returned
**well-formed, correctly-dated, plausible-looking** output:

- FRED's `ptic` is a **pagination total** — `2806` for a window whose first page
  holds `50` rows. Reading it as a count is wrong by 56x and produces no error.
- FRED's release **101 `"FOMC Press Release"` answers for EVERY calendar day**
  (measured: 41 of 41). A reader that trusted it would report the next FOMC as
  **tomorrow, every day, forever** — a steady stream of *confident, dated, wrong*
  answers, which is strictly worse than failing.
- **Flattening the Fed's HTML to text invents meetings**: the page's trailing
  `"Note: A two-day meeting is scheduled for January 25-26, 2028"` sits inside
  the 2027 panel, so a flat parse emits a phantom 2027 meeting (**55 hits vs 53
  structured**). The structured markup disambiguates; the text destroys the
  disambiguation. *HTML is structured data — strip the tags and you have thrown
  away the semantics, not just the formatting.*
- The endpoint **drops `urllib` and `aiohttp` by TLS/HTTP fingerprint** while
  answering **`httpx` on HTTP/1.1** — which is *why* `obb.economy.calendar` times
  out on this host at all: OpenBB's FRED provider is `aiohttp`-based, so the
  route §16.4 names is unusable here through the library the project uses.

Three consequences worth carrying. **(a) A probe must print the numbers, not
assert them.** Every one of these was found by *reading* probe output
(`ptic= 2806  parsed= 50` on adjacent lines), not by a failing test — which is
the same reason D-064's direction-blindness surfaced only in the live check.
**(b) A warning that fires on correct data is itself a defect.** The first name
guard compared `"CPI"` against `"Consumer Price Index"`, so it warned on **every
healthy call**; a guard that cries wolf trains its reader to ignore it, which
costs more than the guard is worth. It was fixed by comparing the **full release
name** and pinned by an explicit *silence* test — a guard needs a test that it
does **not** fire, and that test is as load-bearing as the one that it does.
**(c) Bound the request AND the result.** The horizon was passed as a query
parameter but never applied locally, so a 1-day horizon still returned a 60-day
event — because **a request parameter cannot un-return a row**. The test that
found this was written to kill a mutant, and it killed a real defect instead.

**95 — an `if` with a bare `else` has an implicit third outcome, and the `else`
is claiming it.** §16.4 Q7 assigns `direction` with one condition and a bare
`else`:

```python
direction = "confirms" if (<all the real cases>) else "contradicts"
```

`ConfirmationSignal`'s own vocabulary permits **three** members — `confirms`,
`contradicts`, `neutral` (`_validate_direction`, §22.10 / Finding #10). The
sample supplies **two branches for three outcomes**, so the third is whatever
`else` happens to do — and `else` does not mean "otherwise unrelated", it means
**"everything the author did not enumerate"**. Four such outcomes were measured,
and **three are not disagreement at all**: a **dict** (`four_pillar_scorecard`
and `inflation_convergence_classifier` both publish one), **`0.0`**, **`True`**,
and a non-zero value against a **zero** gap. Each was published as an *active
claim that the evidence contradicts the thesis*. **The defect is not a wrong
direction; it is a direction that was never derived** — D-056's false-confidence
direction, one layer in from the arithmetic. The repair is not a better `else`:
it is to **make the unrepresentable case representable** — a third branch for
`neutral` and a typed `unreadable` bucket on the return, so "I could not read
this" is a value rather than a mislabelled `contradicts`. **Count the schema's
vocabulary against the branch's cases; a mismatch is a defect in one of them.**

**96 — a label is a claim about what was READ, so deriving it from the thing you
read is the only form that cannot drift from the argument list.** **O-69** was
recorded (D-063) as "three different inflation models for one argument slot".
Measuring the whole surface produced **six distinct `source_model` labels for
three slots across three locations** — and **`curve_slope`**, which §7.1's golden
sample names, **is not a parameter of the function at all**. A `source_model` is
how a reader finds the model that made a claim; a label naming a model the
builder never called is **worse than a missing one**, because it is findable and
wrong. The shipped function derives each label from `result.model_name` — the
result it actually read — and keeps the slot name only as a fallback for an empty
`model_name`, which is pinned by a test. **When a function takes both a value and
a name for that value, the name is a redundant argument and will eventually
disagree with the value; the derived form has one source of truth by
construction.**

**97 — a live check that hand-rolls its inputs tests the hand-rolling, not the
system.** The first draft of this increment's live check built the growth leg
directly: `fetch_series("GDPC1")` and `fetch_series("GDPPOT")`, then `.iloc[-1]`
on each, and it returned an output gap of **−17.57%**. `GDPPOT` is a **CBO
projection series** whose last observation is **2036-10-01** — a capacity
*forecast* ten years out — and the arithmetic is perfectly valid, so nothing
raised. Only the **plausibility** of the number exposed it. `output_gap_from_snapshot`
applies the **O-7 horizon filter** and the **D-009 same-quarter pairing** and
returns **+0.83%**, with **42** forward points withheld. The rule this yields is
the one D-063 already proved for `invalidation`: **a live check must go through
the shipped plumbing, and it must assert a bound that would be violated by a
plausible-but-wrong answer** — readability alone passes a gap off by a decade.
This is lesson 84 (*a mutant that does not change the program is not a test
gap*) in a new costume: here the probe was the broken instrument, and its first
output looked exactly like a finding.

**98 — de-duplication is a claim about WHICH question is being asked, and a
summariser that answers one question silently answers the other.** §16.4's
`list(dict.fromkeys(...))` is correct for *"what should a human read"* and wrong
for *"how many models are looking through the same degraded input"* — and the
same three lines serve both. Measured: four models raising one identical string
aggregate to **one** entry with **no trace of the fourth**. The two readings are
not a bug and a fix; they are two questions with one return value, and choosing
is a **specification** decision (it changes what the published field *means*).
The repair therefore preserves §16.4's list **verbatim** and carries the count in
a sibling field. **D-046's "five signals are not five votes" and this defect are
the same error in opposite directions** — there, correlated measures were
over-counted as independent votes; here, one fact seen by N models is
under-counted as one. Both are fixed by the same discipline: **record the
provenance, and let the reader apply the weight.** The live check makes the
coupling concrete: routing one snapshot flag into all five models makes §16.4's
list show it **once** while its `WarningSource` records **5 raisers**.

**99 — a mandatory obligation can be unreachable from the function that is
supposed to meet it, and the honest repair is a PARAMETER rather than a
config lookup.** §21.4 says every BLOCKED input "must be ... surfaced in every
thesis's `warnings`", and §16.4's signature is
`collect_all_warnings(*model_results: ModelResult)`. A BLOCKED input is one **no
model could run on**, so it is by definition **not a `ModelResult`** — the
obligation had no route into the function required to discharge it. Measured
against the live registry: **5 blocked members, 0 routes**. The tempting fix is
to have the function reach into the registry and the snapshot itself; that is
**worse than the defect**, because it makes the obligation *look* discharged
whether or not anything was passed, and it hides what the caller omitted. The
shipped form takes `unattributed` as an argument with a **closed** `origin`
vocabulary, so the caller must **name** what it is omitting. **This is the same
reasoning as D-062's mandatory scope warning and D-064's direction-blindness:
when the right answer depends on something the callee cannot see, make it an
input and make its absence visible — never infer it.** The consequence is that
the obligation is still **open** (O-81) until the builder passes it, and that is
the correct state to record rather than to paper over.

**100 — a gate scoped to one artefact can report GREEN on a tree that a
different artefact corrupted, and "0 leftovers" is exactly the number a scoped
scan is built to produce.** `tools/sweep_health.py` checks each sweep's own
declared mutations, so a mutation left applied in a file **shared between
increments** is in nobody's scan. Measured live: D-064's `M6.3` mutant — `if
False:` replacing `abs(total - 1.0) > tolerance` in
`config.py`'s `_remaining_shares_must_sum_to_one` — was **still on disk**, and
the tool reported **0 leftovers**, because `config.py` belongs to the scenario
sweep, which was target-clean *only because the mutation had already fired*.
The corrupted state was invisible **precisely because it had succeeded**. The
scenario sweep was refusing on an unrelated absent anchor at the time, which is
the only reason it surfaced. **O-61's family with a new mechanism: the gate was
not blind, it was scoped, and a scoped gate's clean result is conditional on the
scope being complete.** The remedy is one line — scan `src/` for the mutant
shapes (`if False:`, `if True:`) independently of any catalogue — and it is not
yet implemented (O-83). The general form: **when a checker derives its search
space from the thing being checked, it cannot see what that thing forgot.**

**101 — a function called from several places must have its CALLERS' OBJECTS
enumerated before its reason strings.** `no_trade_thesis` takes `reason: str`
because §16.4 was written from the perspective of the *sentence*. But the three
call sites named in §16.2 (Q6, Q7, Q8) each hold a **different object** at the
moment they call it — a `MarketPricingGap`, a `ConfirmationSignalAssessment`, an
`InvalidationAssessment` — and each is the only surviving record of what that
gate actually saw. A signature designed around the prose the function *emits*
lost three objects the function's *callers* already had. **Ask what the callers
are holding, not what the output should say.**

**102 — a PRESENCE defect has a test that names it; an INTERACTION defect does
not, and that difference is visible in the sweep's first run.** D-067's sweep
reported `M5.1 SURVIVED` on its first run and forced a new test, because its
defect was an **interaction** (`all_texts`' two halves could never interleave
under any fixture the file used). D-068's sweep reported `13 killed / 1 survivor
(the control)` with **no gaps at all**, because every one of its defects is a
**presence** defect — a missing field, a missing guard, a missing label — and a
presence defect has a fixture that names it directly. **A clean first sweep is a
statement about the SHAPE of the increment, not a statement that it was easier.**
An increment whose defects are interactions should expect a first run with
survivors; one whose defects are presences should be suspicious if it gets one.

**103 — a sentinel that satisfies the gate it stands down from is a latent
false assertion, not a harmless filler.** §16.4 writes
`stop_or_invalidation="n/a"` on the no-trade `TradeIdea`. The LTCM gate is a
**presence** check, and `bool("n/a".strip())` is `True` — measured live: a
`TradeIdea` carrying only that sentinel returns `is_trade is True`, i.e. the
schema accepts `"n/a"` as a stated falsifier. Nothing breaks today because a
no-trade has `is_trade = False` and the gate is skipped. But the sentinel means
the no-trade shape is **one field flip away from asserting a falsifier it does
not have**, and the honest value for a position that does not exist is the empty
string (which is also `TradeIdea`'s own default). **D-052's "a coverage guard
must be a PARTITION, not a HIT" reached through a default value.**

---

## Next (2026-09-19, after D-069) — TIER 4 COMPLETE, and Phase 3 opens

**Where we are.** **Tier 4 stands at 11 / 11 — COMPLETE.** Phase 2 stands at
**85 / 98**, and **all 13 outstanding items are Tier 5** (Phase 5+ deferrals by
§22.3's US-only scoping), so **no Phase-2 work blocks Phase 3**. Phase 3 stands at
**0 / 2** and its blocker is now cleared.

**What just closed.** `build_us_macro_thesis` (D-069) — the **seam function**,
which appears on both the Tier 4 and the Phase 3 checklists. That overlap was
never an inconsistency; it *is* the seam. With it implemented, the models layer
stops producing numbers and the thesis layer starts making claims, which is
precisely what Phase 3 is for.

**What is genuinely outstanding, in order:**

1. **Phase 3 item 1 — the §7 thesis-layer sign-off.** The builder exists and runs
   (`thesis_layer/builder.py`, 1174 lines), the no-trade path is first-class
   (D-068), and a schema-valid thesis is published live. Outstanding: **§7.3's
   example objects** and the **evidence-tagging sign-off**.
2. **Phase 3 item 2 — the §8 API layer.** `src/macro_engine/api/` **does not
   exist**. Nothing serves the thesis: no FastAPI app, no `/health`, no
   `/thesis/us`, no `/dashboard_data`, no `/query`, no SSE reasoning stream. This
   is the largest unstarted surface in the repository.
3. **O-70 — the obligation `build_us_macro_thesis` was created to discharge is
   now DISCHARGED, and should be closed.** §21.4 requires every BLOCKED input to
   be "surfaced in every thesis's `warnings`". D-067 built the mechanism
   (`UnattributedWarning(origin="blocked_input")`) with **no production call
   path**; D-069's builder now passes `unattributed` through to
   `collect_all_warnings` on **every** return path — including all three
   stand-downs, after the `_render` fix. The live check confirms the disclosures
   reach the published thesis (`warnings=13`).
4. **O-87 — `select_instrument`'s two value shapes.** A dict on the executable
   routes; a **bare sentinel string** on the refused ones. The module's own
   `_selection_value` declares *"select_instrument always returns a dict value"*
   and raises otherwise. **That sibling claim is wrong**, and the builder now
   reads both shapes explicitly (`_instrument_from`), which is evidence the
   boundary is real. The fix is to make the declaration true or to split the
   return type.
5. **O-84 — corrected, and it needs a data-layer decision.** The `iorb`
   future-date failure is **not** a frozen clock: *"observation_date 2026-09-21 is
   after retrieval date 2026-09-19 by 2 day(s)"* — the tolerance **is** compared
   against the current date, and **the provider is publishing `iorb` 2–3 days
   ahead of the calendar** while `future_date_tolerance_days` is `1`. The ERROR
   path is armed and firing **correctly**. Fix is one of: widen the tolerance,
   re-point the series, or declare it `forward_looking` — a data-layer call, not
   a thesis-layer one.
6. **O-83's remedy** — implement the whole-tree `if False:` / `if True:` scan
   inside `tools/sweep_health.py`, so the scoped leftover scan stops being a
   manual Step-0 grep.

### Lessons 5be, 5bf (D-069)

**5be — a sweep's `PYTEST_TARGETS` is a CLAIM about where a defect's refutation
lives, and a survivor is the first evidence that the claim is wrong.** D-069's
first sweep reported **six survivors**, and the headline was `M8` — **the very
defect the increment had just fixed** — surviving. Its regression test was
correct and it passed; it simply lived in `test_builder_live.py`, which
`-m "not live"` **deselects**, so the mutation ran against a selection in which
nothing could fail. **The first question when a mutant survives is never "is the
mutant inert?" but "is its killer in my selection?"** The remedy is to **add**
the missing test, never to exempt the mutant: all six gaps closed that way, and
the file went 40 → 51 tests.

**5bf — an honesty control can fail for the RIGHT reason, and it is telling you
that a test asserts SPELLING rather than MEANING.** D-069's second sweep killed
the control `M18`, whose whole job is to be semantically inert
(`x < 0` rewritten as its De Morgan negation). It was killed by
`test_the_sample_s_gap_only_direction_rule_survives_only_as_a_fallback`, which
asserted the source text `'return "long" if gap.raw_gap < 0 else "short"'`.
That assertion is true of the **written form** and false of a
**semantically equivalent** rewrite — i.e. the test was pinning a typographic
choice. Rewritten to pin **order and structure through `ast.parse`** (the
published branch precedes the fallback; the fallback is the last unconditional
return), leaving behaviour to the test that actually drives the function. **A
control that dies is more valuable than one that passes: it is the only mutant
whose failure is guaranteed to be the test's fault.**

---

## Next (2026-09-19, after D-070) — ✅ PHASE 3 COMPLETE (2/2); PHASE 4 IS THE RUNWAY

> **SUPERSEDED — kept as the chronological record of D-070's close.** Phase 4
> **closed at D-073**; see the *Next* block at the end of this file, which is the
> current one. This block's "Phase 4 has not started" was true at the time it was
> written and is no longer.

**Where we are.** **Phase 0 = 8/8 · Phase 1 = 9/9 · Phase 2 = 85/98 (all 13
outstanding are Tier 5, deferred by §22.3) · Phase 3 = 2/2 ✅ COMPLETE.**
Tier 1/2/3/4 = **23/23 · 29/29 · 15/15 · 11/11 — ALL COMPLETE.** Tier 5 = 0/20
**by design**. **Phase 4 had not started as of this block.**

**What D-070 closed.** The §8 API layer — five surfaces (`/health`,
`/thesis/{country}`, `/dashboard_data`, `/query`, the SSE reasoning stream) across
eight modules in `src/macro_engine/api_layer/`. The increment's **reason for
existing** was the **orchestration gap**: `build_us_macro_thesis` takes **six
required arguments** while §8.2's sample supplies a snapshot alone, so all
derivation lives in `orchestration.py` — **one auditable file**. The status
contract is **refusal, not defaulting**: 502 missing data · 501 unimplemented
country · 422 bad `thesis_type` · 500 real bug · **200 + `WATCH` for a
stand-down** (§16.3 forbids a fabricated no-trade).

**The immediate next increment is Phase 4: risk basics (VaR) plus the risk-budget
hook.** It builds on the four Phase-4 instrument functions already shipped under
Tier 4 — `evaluate_drawdown_rules`, `check_rebalancing_drift`,
`volatility_target_scaling` and `kelly_position_size` (D-058–D-062) — which are
the portfolio layer it will consume. Read those entries before starting.

**Carry into Phase 4 (recorded, not fixed — full text in `docs/OPEN_ISSUES.md`):**

- **O-92** — two **production** HTTP clients default to `trust_env=True`
  (`openbb_client.py:91`, `catalysts.py:213`) and the OpenBB client's loopback
  mounts are `{http://: HTTPProxy}`. Every loopback request is proxied; it works
  here **only because this environment's proxy transparently forwards loopback —
  luck, not design**. **Not patched because patching would invalidate the provider
  mutants that certify the current behaviour.**
- **O-90** — the memoized snapshot is **process-global**, so `--workers N`
  silently multiplies the measured **223.6 s** build while the response still
  discloses a correct age. Needs a `workers=1` contract or a shared store.
- **O-91** — the async SSE generator **awaits a synchronous build**, blocking the
  event loop so `/health` goes unanswered during a slow build. Needs `to_thread`.
- **O-87** — `select_instrument`'s two value shapes. **O-86** — `WATCH` cannot
  distinguish "no edge" from "waiting". **O-84** — the data-layer `iorb`
  tolerance decision (the only failing test).

**Standing obligations at every close:** run the full gate set **sequentially**
(never alongside a sweep — lesson **5bi**); run `tools/sweep_health.py`; quote the
**measured** file count and check that ruff-format's equals mypy's (D-035); and
write the record set in the order DECISIONS → PROGRESS → **OPEN_ISSUES** →
BUILD_STATE → MODULE_MAPPING → CHANGELOG → memory → skill.

### Lessons 5bg, 5bh, 5bi (D-070)

**5bg — a ROUTING-shaped symptom can have a TRANSPORT-shaped cause; print the
request line.** D-070's live check hit `404 {"detail":"Not Found"}` from a route
that was registered, prefixed and correct. The cause was in the **client**:
`httpx.Client` defaults to `trust_env=True`, so it honoured `HTTP_PROXY`, and a
forward proxy takes the **absolute-URI form** (RFC 7230 §5.3.2) — which uvicorn
unquotes into `scope["path"]`. **The intermittency is what costs the day: the
first request on a FRESH connection survives; a request on a REUSED keep-alive
404s.** Isolate it with a 2×2 (connection-reuse × query-params) against a raw
socket server printing the first line of each request head. **Rule: in a live
check, always pass `trust_env=False` for a loopback service, and guard it with an
`ast` test.** Three earlier hypotheses (query-param encoding, router prefix, h11's
16 KiB header limit) were all tested and discarded — the h11 limit produced a
**clean 431** on a fresh connection, a *different* failure with a similar shape.

**5bh — lesson 5bf applies to CHECKS, not only tests: pin the VALUE, never a
rendering.** The same check asserted the stream contained `"gap = +26.0bp"` while
the stream correctly emits `"gap = +0.2600pp (+26.0bp)"` — a **string the format
never produces**, so a passing service failed the check. **Derive what you expect
from the value you measured** and require every rendering you depend on. And the
check must **supply the input the config declares**: it hardcoded a CORS origin of
`localhost:3000` while the allow-list held `:8000`, so Starlette correctly answered
`400 Disallowed CORS origin` — **the middleware was right and the check was wrong.**

**5bi — NEVER run the test suite while a mutation sweep is in flight.** D-070's
full run reported three phantom failures in `test_orchestration.py` and one flaky
failure in `test_routes.py`; all vanished on a clean re-run. A sweep is a
**writer**: it mutates `src/` for the duration of each mutant. Any gate that reads
`src/` must run either side of it, in sequence.

---

## Next (2026-09-20, after D-073) — PHASE 4 IS COMPLETE · **PHASE 5 IS NOT STARTED**

**Where we are.** **Phase 0 = 8/8 · Phase 1 = 9/9 · Phase 2 = 85/98 (all 13
outstanding are Tier 5, deferred by §22.3) · Phase 3 = 2/2 ✅ COMPLETE ·
Phase 4 = 4/4 ✅ COMPLETE (closed at D-073).** Tier 1/2/3/4 = **23/23 · 29/29 ·
15/15 · 11/11 — ALL COMPLETE.** Tier 5 = 0/20 **by design**.

**Do NOT begin Phase 5 without a fresh instruction.** The user's instruction at
D-073's close was explicit: *"do not start phase 5, complete phase 4."* Phase 4 is
now complete, which means the correct terminal state of the runway is **"Phase 5
startable, not started"** — not "Phase 5 in progress". Phase 5's entry point is the
**13 Tier-5 deferrals**, and §22.3 requires that **each** of them bring **its own
verified data-source registry, its own central-bank reaction function** (the ECB's
20-country compromise, the BoJ's deflation-scar bias and the PBoC's non-Western
rule are **genuinely different logic**, not the Fed's Taylor Rule relabelled), and
**its own instrument set**. It is not a phase to open by momentum.

**What D-073 opened and closed.** The §17.4 risk axis now runs inside
`build_us_macro_thesis`. It is the **only** place the risk layer writes back into
the thesis lifecycle, and it now **cannot be silently inert**: with no budget it
publishes *"§17.4 DID NOT RUN"*, with a refusal it names the refusal, and with a
size at or below the bound it demotes to `WATCH` and names the binding constraint.
Its bound was **corrected from 0.02 to 0.03** because 0.02 was unreachable — see
O-96 and the finding block above.

**Carry into Phase 5 (recorded, not fixed — full text in `docs/OPEN_ISSUES.md`):**

- **O-97** — §17.4 is wired at the **builder** and **unreached by the API**: none of
  the three production call sites passes a risk budget, so every API path publishes
  *"DID NOT RUN"*. **Verified spec-conformant** (the rule is scoped to *"once
  Phase 4+ auto-sizing exists"* and names `RiskLimits`, a Phase-5+ object), and the
  **disclosure was checked to reach a consumer**: the route returns the thesis
  object itself and `warnings` is a first-class field, so a client that reads only
  `status` sees `DRAFT` but the warning travels beside it. **The open part is
  enforcement** — the parameter is optional, so a future caller that forgets it
  fails open.
- **O-96** — `CANDIDATE` has no producer, so §17.4's literal `CANDIDATE → WATCH`
  is unreachable. The axis demotes `DRAFT` and says so. **The generalisable form:
  the declared-consumed-unreachable class has now appeared through a guard
  (D-045/046/048), an instrument sentinel (O-53) and a lifecycle state (here). If
  a fourth vocabulary exists, nobody has named it yet.**
- **O-94** — Q12's exposure half. Needs Module 18 (Phase 5+) — **which Phase 5 is
  the phase that builds it.**
- **O-95** — `tools/sweep_health.py`'s reader mismatch is **fixed**, but the residual
  question stands: whether any *other* tool compares source text against anchors
  with a different reader than the sweeps use. `tools/reachability_audit.py` is the
  obvious next one to check, since it also parses shipped source.
- **O-93** — the sentinel documentation defect, corrected at four sites. **The
  generalisable rule: a claim repeated in four documents is four times less likely
  to be re-derived** (lesson 5bj).
- **O-92 · O-90 · O-91 · O-87 · O-86 · O-84** — unchanged.
- **The two inherited sweep failures** — `mutation_regime.py`'s `M8d` and
  `mutation_lei_proxy.py`'s `M8e`, both *"target ABSENT"* in a sweep that has no
  own gate. These are the only two `sweep_health.py` failures left, and both are
  real anchors that no longer match their source.

**Standing obligations at every close:** run the full gate set **sequentially**
(never alongside a sweep — lesson **5bi**); run `tools/sweep_health.py` **and read
its output critically** (lesson **5bl**: a large homogeneous block of failures is
more likely to be the gate than the code); quote the **measured** file count and
check that ruff-format's equals mypy's (D-035); and write the record set in the
order DECISIONS → PROGRESS → **OPEN_ISSUES** → BUILD_STATE → MODULE_MAPPING →
CHANGELOG → memory → skill.

### Lessons 5bp, 5bq, 5br, 5bs (D-073)

**5bp — a SKIP is a green tick, and a `skipif` on an in-principle-reachable state
is a defect.** `test_a_demoted_thesis_moves_to_watch_and_says_why` ran, skipped, and
was counted as passing for the whole increment's first pass. **The skip was not a
statement that the state was unreachable — it was a statement that the precondition
happened not to be met, reported in the same colour as success.** A `skipif` must
name a state that is **structurally** unreachable (see O-27's
`test_a_single_family_input_is_unreachable`) and never one that a config value could
make reachable. **When a test you just wrote skips, treat it as a failure until you
can prove the state is unconstructible.**

**5bq — a config bound whose validity depends on the model's OUTPUT must re-derive
that output.** `thesis_demotion_fraction` is only meaningful relative to the set of
sizes the pipeline can publish, and that set is **not an interval** — it is six
discrete values, because full Kelly pins `f*` at the search-domain edge for a
two-branch distribution with a positive edge. **A bound written against the
continuous model in an implementer's head was wrong against the discrete set the
code produces.** The remedy is not a better number but a **live check that
recomputes the set** every run, which is what `live_risk_axis_check.py` now does.

**5br — when two mutants survive a sweep in the same run, ask whether the tests are
reading a DIFFERENT SYMBOL than the code uses.** `M1.2` moved the axis's **local**
bound while the tests asserted on the **config leaf** — both were "the bound", and
neither test touched the other. This is O-29's mis-target class one level up: not a
mutation that rewrites the wrong function, but a **test that asserts on the wrong
copy of the same value.** The killer is a test that drives the axis and reads the
**outcome**, not one that re-reads the setting.

**5bs — a boundary operator is only as tested as the observation that lands EXACTLY
on it.** `M4.1` changed `<=` to `<` and survived, because every demotion test used a
size *below* the bound. **`<=` and `<` differ on exactly one value, and if no input
ever produces that value, the two operators are the same function and the tests
cannot tell them apart.** Plant an input **on** the boundary — which is what
`test_the_demotion_fires_at_the_boundary_not_only_below_it` does — or the operator
is unverified.


### Lessons 5bl, 5bm, 5bn, 5bo (D-072)

**5bl — a check producing a large, homogeneous block of failures is more likely
broken than the thing it checks.** 39 of `sweep_health.py`'s 45 findings described
one file's line endings. **The tell is uniformity**; **the remedy is a second,
independent reader.**

**5bm — a false positive can MASK a true positive on the very same line.** The
garbage output and the real leftover mutant shared a line, and the real defect
looked exactly like the noise around it. **A noisy gate is actively dangerous,
because the signal it hides is shaped like its noise.**

**5bn — a refusal must be a genuinely different OUTCOME.** A mutant kept the
outcome identical and changed only the reason, and the test asserted a substring
both branches contained. **Assert the branch's own distinguishing phrase**, which
forces the test to know *which* check fired.

**5bo — a claim in a docstring is a claim, and `get_args` cannot read.** The type
docstring said *nine* for a `Literal` of *six*, through a repair that removed
three. **Pin every counting claim about a type against the type**, using a
word→number map so reflow does not force a loose edit.


## 2026-09-20 — Phase 0–4 final audit (D-074) — **PHASE 4 RE-CONFIRMED COMPLETE (4/4)**

**Trigger:** external audit directive. **No Phase 5 work; no architecture change;
`AGENTS.md` unchanged.**

### What the audit found

Four defects — three live code, one deployment — each fixed with a RED→GREEN
regression test. The common thread: **every one of them was invisible to the
existing gates, and each was a MISSING-DATA conversion.**

1. **Non-finite values passed every gate** (`nan`/`±inf`). `dropna()` removes
   nulls, not `inf`; Pydantic accepts `nan` by default; and the plausibility
   check is **made of comparisons, all of which are `False` for `NaN`** — so a
   poisoned series reported **CLEAN**. `±inf` was only caught when the series
   carried a `plausible_range`, and **2 of 45 series carry none**. Fixed at
   four layers: normalisation drop, `allow_inf_nan=False` on
   `ObservationPoint.value`, `MacroDataSnapshot.assert_finite()` before
   persistence, and a `NON_FINITE_VALUE` ERROR as the **first** validation check.
2. **One `NaN` FCI component inverted the composite.** `sum()` propagates
   `NaN`; `NaN > 0.0` is `False`; the model then reported *"looser than
   average"* **invented from absent data** — the exact `missing → False`
   conversion the directive forbids. `std = inf` gave `z_score == 0.0`, an
   invented "exactly average". Fixed in the schema and at the point of use.
3. **Provenance recorded the preference, not the path.** A cross-path fallback
   labelled package-served data as `openbb:http://127.0.0.1:6901` — a
   fabricated transport fact. Fixed with a mandatory keyword-only `served_by`.
4. **Config pointed at `:6900`** against an explicit "do not use `6900`".
   Both ports were live and identical — an ambiguity, not an outage. Repinned.

### The vintage directive is not executable — and the code was already right

The directive prescribed the `series_vintages` → `realtime_start`/`realtime_end`
route. **Measured five ways: it does not exist on this deployment.** 278 live
operations, zero with `vintage` in the path; zero with any `realtime*` param;
and sending the parameters anyway returns **HTTP 200 with `warnings: null` and
1947 data — silently ignored.** The in-process SDK has no `obb.economy.fred`.
`config.py`, `publication_dates.py` and `schemas.py` already document this
correctly, so **no code change was made**; the evidence was appended to O-6.
Confirmed the engine needs no `FRED_API_KEY` of its own.

### Lessons

**5bt — a comparison is not a check when the value can be `NaN`.** Every
plausibility bound, every threshold, every `>` / `<` / `==` returns `False` for
`NaN`. **A NaN therefore passes a bounds check by failing to fail it**, and the
report reads CLEAN. **The guard must test FINITENESS, not magnitude** — and it
must run *first*, because all the checks after it are comparisons. (D-074.1)

**5bu — a "by default" is a decision someone else made for you.** Pydantic's
`float` accepts `nan` and `inf` unless you say otherwise; `dropna` removes
nulls and not infinities; `sum()` propagates `NaN` without raising. **Three
defaults, chosen by libraries, in the exact direction of silent fabrication.**
The audit question is not "does this function work?" but "**what does this
function do with the value it was never designed for?**" (D-074.1, D-074.2)

**5bv — `bool(x > 0)` is a two-valued function wearing a missing value's
clothes.** When `x` is `NaN` the comparison returns a **valid-looking `False`**,
so the missing-data case is *not* distinguishable from the genuine negative
case in the output. **Any code that reduces a computed float to a boolean must
first prove the float is finite**, or it has converted absent data into a
substantive claim. (D-074.2)

**5bw — provenance must be a RECEIPT, not an INTENTION.** The label was derived
from `use_local_api_first` — what the client *meant* to do — rather than from
which path *answered*. **A provenance string is evidence about the past and
must be written by the code that observed it**, never reconstructed from the
configuration that requested it. (D-074.3)

**5bx — a prescribed fix can be unrunnable, and "unrunnable" is a finding, not
a failure to follow instructions.** The vintage procedure is correct macro
practice and cannot execute here. **The honest response was to measure why
(five ways), confirm the codebase already handles the absence, and record it —
not to write code that appears to do it.** A parameter that is *silently
ignored* is more dangerous than one that 404s: the 200 looks like success.
(D-074, O-6)

---

## 2026-09-20 — Phase 0–4 audit, session 2: the sweep anchors and the non-finite verdicts

**Status: Phase 4 COMPLETE (unchanged 4/4). No phase started.** This session was
an audit of the shipped build, per the standing instruction to keep Phase 5
unstarted.

### What was found and fixed

**D-075 — two sweeps had silently stopped gating.** `mutation_drawdown.py` CX5
and `mutation_regime.py` M8d both anchored text that had drifted: CX5's anchor
predated a defensive default (`get("tiers")` → `get("tiers", [])`), and M8d's
anchor pinned two lines as *adjacent* while a four-line comment block had been
inserted between them. **Both matched 0 occurrences**, so both sweeps reported
`target ABSENT` and their mutants were invisible — the O-95 self-concealing
shape. Both are one-line anchor repairs; neither mutation surface had changed.
`sweep_health.py` went from **2 failures → 0**: **40 sweeps, 0 leftovers, 0
mutant shapes.** The HANDOFF's "2 INHERITED failures (do-not-fix)" line was
stale in **both** directions (documented `M8d`+`M8e`; measured `CX5`+`M8d`).

**D-075.3 — three docstring-cited decision numbers that had no entry.** The tree
carried code fixes citing `(D-076)` and `(D-077)` with **neither entry written
anywhere.** Both are now recorded at the numbers their docstrings asserted — a
docstring citing a record is a claim with no receipt (the O-88 class in prose).

**D-076 — `withheld_forward_points` held a two-category sum under a
one-category name.** It was assigned `withheld + unpaired`, so it read **42**
where the series held **41** projections. Now the O-7 horizon count verbatim,
with the unpaired count published separately and the total a **derived
property**.

**D-077 — the provenance share was read from a census that cannot report it.**
`classify_convergence` read `untagged` from a census over the *directional*
signals, where a family is structurally guaranteed (so it is always 0), while
the disclosure that consumes it counts over the *whole* signal list. The
published "untagged" share was **structurally unfireable**; the `else 0` branch
also converted a *missing* key into a *measured* zero.

**D-078 — `nan` was a readable value in all four verdict-producing paths.** The
session's most important finding, and **active** rather than latent:

| Path | With a non-finite input | Published |
|---|---|---|
| `classify_regime_rule_based(output_gap=nan)` | `_growth_axis` fallthrough | `above_trend` / `reflation` |
| `classify_regime_rule_based(inflation_trend_3m=nan)` | `_inflation_axis` fallthrough | `flat` |
| `taylor_rule(pi_current=nan)` | no guard | `value=nan` |
| `MarketPricingGap(raw_gap=nan)` | `direction` fallthrough | **`aligned`** |
| `_direction_for(nan, +1)` | `"contradicts"` | **an active disagreement** |

The `MarketPricingGap` case is the worst: `direction='aligned'` with
`is_meaningful=False` states *"the model and the market agree, insignificantly"*
— **a silent NO-TRADE manufactured from absent data**, in the one class the
whole pipeline exists to build a *disagreement* from. The `_direction_for` case
is the subtlest: it is the exact outcome `test_signals.py`'s documented defects
1 and 2 exist to prevent, arriving **through the readability gate those fixes sit
behind**, because `nan` **is** a `float` instance.

**Fix shape — guard the input DOMAIN, not the range.** Every guard is on what a
field may *be*, not on what a value may *equal*: a `model_validator` on
`RegimeInputs` (on the object, so every helper is covered, including the ones
reached from `regime_tension` and the trilemma check), a shared `_FiniteInputs`
base for the policy-rule input groups, `allow_inf_nan=False` on
`MarketPricingGap`'s four numeric fields, and `isfinite` in `_signed_scalar` so
a non-finite signal is **reported** in the `unreadable` census.

### Gates (re-measured, per O-88 — not carried forward)

| Gate | Result |
|---|---|
| `ruff check src tests tools scripts` | All checks passed |
| `ruff format --check …` | **224** files already formatted |
| `mypy --strict src tests tools scripts` | **224** source files, no issues (**224 = 224**, D-035) |
| `pytest -q` | **2401 passed, 1 skipped, 0 failed** |
| `tools/sweep_health.py` | 40 sweeps, 0 leftovers, 0 mutant shapes, **0 failures** |

The count moved 221 → 224 because **three test files were added** this session
and the last; D-035 parity is `ruff format` == `mypy`, and it holds at 224.

### Lessons

**5by — an anchor is a CLAIM about the source, and nothing re-checks it.** A
sweep whose anchor drifted reports `target ABSENT`, which reads like a *code*
problem and is a *harness* problem. Read it as **"this gate is off."**

**5bz — a name is a unit.** `withheld_forward_points` was assigned a sum of two
differently-reasoned counts. A quantity's label carries its scope; widening the
scope while keeping the label is how an off-by-one enters a disclosure whose
only job is to be noticed.

**5ca — a disclosure and its source must be counted over the same population.**
The `untagged` bug was not arithmetic; it was two different denominators, and
neither number could see the other.

**5cb — a fallthrough is a decision, and `nan` takes it.** Bucket tests
partition the real line *for real numbers*. `nan` is in no bucket, so the last
branch is not a complement — it is a **default**, and the default is always the
most extreme label the helper can produce. **Any function ending in a bare
`return <most-extreme-value>` answers confidently when it cannot answer at all.**

**5cc — a type test is not a validity test.** `isinstance(x, (int, float))` is
`True` for `nan`. `bool` was excluded by hand because someone noticed `True` is
an `int`; `nan` was not, for the same reason.
