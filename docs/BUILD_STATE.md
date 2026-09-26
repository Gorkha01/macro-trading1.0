# Build State

Per-function completion record (AGENTS.md Section 21.0 / 21.2 Step 9).

> **A function is DONE when, and only when:**
>
> - [ ] Implemented exactly as specified (no deviation without a logged decision)
> - [ ] Unit test with hand-verified expected values passes
> - [ ] Executed against real data from its documented source
> - [ ] The real-data output is economically plausible and that assessment is written down
> - [ ] Every `warnings` condition specified has been triggered at least once in a test
> - [ ] `ruff` and `mypy --strict` clean
> - [ ] Documented with its real-data validation record

---



## Quality gates - measured 2026-09-20, after the D-080..D-082 audit-and-fix pass

```
ruff check src tests tools scripts ->  All checks passed!
ruff format --check               ->  225 files already formatted
mypy (strict, python_version 3.12)->  Success: no issues found in 225 source files
                                      (src, tests, scripts AND tools all typed)
                                      [225 = 225, D-035 count parity satisfied]
                                      (the pair moved 224 -> 225 when
                                       scripts/_sweep_gate.py was added; the
                                       earlier "224 = 224" was carried forward
                                       rather than re-measured -- O-88)
pytest -q                         ->  2432 passed, 1 skipped, 0 failed
                                      (measured by counting outcome markers --
                                      2432 dots, 0 F, 0 E -- NOT by exit code:
                                      the harness's safe-delete guard makes the
                                      process exit 1 while every test passes; D-082.2)
uv run python tools/sweep_health.py -> 40 sweeps checked, 0 leftovers,
                                      0 mutant shapes, 0 failures,
                                      0 sweeps with NO sweep-owned gate
                                      (D-075 cured the 2 "INHERITED" failures --
                                      they were STALE ANCHORS, not by-design
                                      absences; D-081 fixed the tool's diagnosis;
                                      D-082 wired the last 14 gates)
tools/reachability_audit.py --check-baseline -> PASS, 59 = 59
scripts/live_risk_axis_check.py   ->  PASSED (exit 0)
scripts/mutation_lei_proxy.py     ->  36/36 killed  (run in full at D-080;
                                      M8e and M8g both KILLED)
scripts/mutation_regime.py        ->  gate 40 mutations / 0 problems;
                                      interrupted run self-heals from sidecar (D-082)
grep -rn "if False://|if True:"  src/macro_engine/  ->  nothing (required)
```

### The interrupt defence does NOT work on this platform (D-082)

`mutation_api_layer.py` installs a `SIGTERM`/`SIGINT` handler to restore a
mutation left in flight. **On `win32` that handler is never entered** - measured
with three probes, including a trace wrapper that printed nothing while
`signal.getsignal` confirmed the handler installed and the payload was armed.
`os.kill(pid, SIGTERM)` maps to `TerminateProcess`. **The record that credited
`_restore_in_flight` as a defence is corrected:** it is correct on POSIX and kept
for that reason, but it protects nothing here.

The defence that does work is `scripts/_sweep_gate.py`'s **sidecar recovery** -
`record_pristine()` writes pristine text to `<name>.sweepbackup` before the first
mutation, `restore_from_sidecar()` heals on the next run. It needs only the
filesystem, so no kill can bypass it, and it is **strictly stronger than
`repair_leftover_mutations`**, which can only heal a mutation the catalogue still
recognises. Adopted by **all 42 sweeps — O-103 COMPLETE (D-087.26), extended at
D-087.27: 40 call the `sweep_lifecycle()` wrapper, 2 (`mutation_api_layer.py`,
`mutation_regime.py`) assemble the same mechanism by hand** because they must heal
**before** `check_targets` (lesson 5co). A bare `sweep_lifecycle(` grep reads 40/42
and under-counts — cite the union. *(41 at D-087.26; `mutation_command_inventory.py`
added at D-087.27.)*

### The do-not-fix sweep list is EMPTY, and it was wrong 3 times out of 3 (D-075, D-080)

This file twice recorded sweep failures as *"inherited - targets absent by design -
DO NOT FIX."* **Both claims are retracted, and so is the category.** Every entry
was run in full and every one is **KILLED**:

| entry | recorded claim | measured |
| --- | --- | --- |
| `mutation_drawdown.py` `CX5` | target absent by design | **stale anchor** (D-075) → sweep now 47/47 |
| `mutation_regime.py` `M8d` | target absent by design | **stale anchor** (D-075) → sweep now **40/40 killed** |
| `mutation_lei_proxy.py` `M8e` | target absent by design | **never a limitation** (D-080) → sweep now **36/36 killed** |

**In all three cases the label was an artifact of the CHECK, not a property of the
code.** The operational rules recorded:

- A `target ABSENT` means **the gate is OFF**. It certifies nothing — it is the
  O-95 self-concealing class, where a mutation that no longer applies is
  indistinguishable from one that never existed.
- A do-not-fix label is an **unverified claim requiring re-derivation**, never a
  risk acceptance. The list should be treated as a **to-do list**.

**D-080 also exposed a real survivor** — `M8g` — which the do-not-fix noise had
been sitting next to for two sessions. See below; it is a genuine test gap
(O-101), closed with a RED→GREEN test and verified `git diff --quiet` clean.

### The "INHERITED" sweep failures were stale anchors (D-075)

`mutation_drawdown.py` `CX5` and `mutation_regime.py` `M8d` were previously
recorded, in this file and in the handoff memory, as *"targets absent by design -
DO NOT FIX."* **That claim was wrong and is retracted.** Both were **stale
anchors**: the mutation surface had not changed, but the source text each anchor
pinned had drifted (a defensive `get("tiers", [])` default; a four-line comment
block inserted between two lines the anchor pinned as adjacent). Each anchor
matched **0 occurrences**, so the sweep reported `target ABSENT` - the O-95
self-concealing class, where a mutation that no longer applies is indistinguishable
from a mutation that never existed.

After repair: `mutation_drawdown.py` **47/47 applied, 46 killed, 1 expected control
survivor**; `mutation_regime.py` **40/40 killed** (including `M8d`). Both EXIT 0.
The lesson is O-88's, one layer down: *an anchor is a CLAIM about the source text,
and a claim must be re-measured, not carried forward.*

### The last entry was not a limitation either, and it hid a real gap (D-080)

`mutation_lei_proxy.py` `M8e` was the final do-not-fix entry. Run in full, the
sweep reported **36/36 killed** — **`M8e` is KILLED**, so the third and last
do-not-fix claim is retracted too. The single survivor that appeared *before* the
repair was a **different** mutant, **`M8g`**: deleting `and not forward_looking`
from the `SAME_DAY_PUBLICATION_AHEAD_OF_CLOCK` guard (`validation.py:314`).

**It survived because the test asserting that property cannot reach the branch.**
`test_the_tolerance_is_not_applied_to_forward_looking_series` supplies a point
dated **2030-01-01** against a retrieval of **2026-09-16** with tolerance **1** —
so the point lands in `future_dates`, **not** `tolerated_future_dates`, and the
guard is never consulted. **A test can assert the right property and still be
unable to reach the branch that enforces it** (lesson 5ce). *This is the class the
do-not-fix noise was sitting next to for two sessions.*

**What it hid:** a **projection** series carrying a tolerated point would emit
`SAME_DAY_PUBLICATION_AHEAD_OF_CLOCK`, whose own text declares the points
**"realised data"** — false about the object it is attached to, at INFO severity,
with no `FORWARD_LOOKING_HORIZON` line to contradict it. Closed with a new test
(lead **1**, tolerance **3**, plus a positive control); RED→GREEN verified in both
directions and the source verified `git diff --quiet` clean afterwards, so the
repair is the **test**, not a source edit. **No production source was changed.**

**Scope: latent, not a live leak.** Only `sofr`/`iorb` declare a non-zero tolerance
and both are `forward_looking=False`, so the armed cell is unreachable today. The
new test **pins the silence** so arming it later fails loudly against **O-101**.

### Live OpenBB validation - `http://127.0.0.1:6901` (D-074)

```
snapshot   -> 22 fields populated, 0 failed, is_complete=True, assert_finite() PASS
validation -> 2 INFO findings, 0 errors, 0 warnings
              (FORWARD_LOOKING_HORIZON, SAME_DAY_PUBLICATION_AHEAD_OF_CLOCK)
thesis     -> status WATCH / convergence NO_SIGNAL / instrument NONE
              11 warnings; gap 0.26 inside the rules' own dispersion 0.86
              => NO TRADE, and that is the correct outcome
```

Real observations captured: `cpi_headline 334.131 @ 2026-08-01` (released
2026-09-11), `cpi_core 337.765`, `pce_core 130.658`, `unemployment_rate 4.1`,
`fed_funds_rate 3.63`, `gdp_real 24269.613`, `gdp_potential` projected to
`2036-10-01` (forward-dated CBO projections correctly withheld from the
snapshot field and preserved as an INFO flag), `sofr 3.85` vs `iorb 3.90`
(corridor intact), `credit_spread_hy 2.70` > `ig 0.78` (ordering intact).
Curve: 10YR-2YR slope `+27.0`bp; breakevens 5yr 2.32% / 7yr 2.34% / 10yr 2.33%
/ 20yr 2.45% / 30yr 2.25%.

### Audit scope, stated honestly (D-074)

**Four defects found and fixed** (three code, one deployment); **one prescribed
procedure proven not to exist** and documented as a negative finding; **eight
classes of suspected defect investigated and confirmed already correct.** No
Phase 5+ code was introduced, the architecture was not changed, and
`AGENTS.md` was not modified. Full text: `docs/DECISIONS.md` **D-074**.

## Quality gates — measured 2026-09-18, after Module 15.1 (`D-059`)

```
ruff check src tests tools scripts ->  All checks passed!
ruff format --check               ->  142 files already formatted
mypy (strict, python_version 3.12)->  Success: no issues found in 145 source files
                                     (src, tests, scripts AND tools all typed)
pytest -q                         ->  1583 passed, 1 skipped, 0 failed
uv run python scripts/mutation_regime.py                 ->  40 / 40 killed
uv run python scripts/mutation_evidence.py               ->  17 / 17 killed
uv run python scripts/mutation_inflation_convergence.py  ->  25 / 25 killed, 2 inert by design
uv run python scripts/mutation_trilemma.py               ->  60 / 62 killed, 2 inert by design
uv run python scripts/mutation_yield_curve.py            ->  67 / 68 killed, 1 inert by design
uv run python scripts/live_regime_check.py               ->  passes end to end, zero base-rate drift
uv run python scripts/live_inflation_convergence_check.py->  passes end to end, 522 real months
uv run python scripts/live_trilemma_check.py             ->  passes end to end, drift 0.000
uv run python scripts/live_inversion_check.py            ->  passes end to end, drift 0.0005
uv run python scripts/mutation_scorecard.py              ->  84 / 87 killed, 3 proven-inert
uv run python scripts/live_scorecard_check.py            ->  passes end to end, 761 real months
uv run python scripts/mutation_convergence.py            ->  53 / 56 killed, 3 classified
uv run python scripts/live_convergence_check.py          ->  passes end to end, 761 months,
                                                             cross-check 761 agree / 0 disagree
uv run python scripts/mutation_transmission.py           ->  55 / 58 killed, 3 proven-inert,
                                                             0 defects  (58 mutations, 13 groups)
uv run python scripts/live_transmission_check.py         ->  passes end to end; real-yield
                                                             identity EXACT (5 931 obs, max err
                                                             0.000000); base-rate drift 0.0000
                                                             (bar 0.005); cross-check against
                                                             inversion_probability_adjustment
uv run python scripts/mutation_inflation_trajectory.py   ->  21 / 24 killed, 3 expected
                                                             survivors, 0 unexplained;
                                                             `_EXPECTED_INERT` deliberately
                                                             EMPTY  (24 mutations, 10 groups)
uv run python scripts/live_projection_check.py           ->  passes end to end; beta re-measured
                                                             (n 290, se 0.00159, t +3.76,
                                                             R^2 0.047); base-state bar cleared;
                                                             cross-check agrees on the shared
                                                             labor leg; fiscal flag live
uv run python scripts/mutation_drawdown.py               ->  46 / 47 killed, 1 survivor (the
                                                             honesty control), 0 defects;
                                                             `_EXPECTED_INERT` deliberately
                                                             EMPTY  (47 mutations, 13 groups)
uv run python scripts/live_drawdown_check.py             ->  passes end to end; 2 513 real
                                                             daily SP500 obs; all three outcomes
                                                             reachable; worst drawdown 33.92%;
                                                             path-independence 0 violations;
                                                             cross-check vs
                                                             volatility_target_scaling on the
                                                             shared SHAPE -- now a REAL CALL
                                                             since D-056 shipped the function
                                                             (O-43 discharged)
uv run python scripts/mutation_rebalancing.py            ->  64 / 64 applied, 61 killed,
                                                             3 survivors -- 2 PROVEN INERT
                                                             (1 unconditional, 1 conditional
                                                             on the shipped config) and 1
                                                             honesty control; 0 defects
                                                             (64 mutations, 12 groups).
                                                             The harness now REFUSES to
                                                             certify an excused mutation
                                                             carrying no proof (exit 2)
uv run python scripts/live_rebalancing_check.py          ->  passes end to end; 5 real tradeable
                                                             ETFs, 504-session covariance,
                                                             sigma_p 8.33%; SPY 35.0% of
                                                             notional -> 56.14% of RISK; UUP
                                                             -1.48%; trip rate 9.7% at the
                                                             configured 10%; cross-check vs
                                                             evaluate_drawdown_rules is a REAL
                                                             CALL, not a re-implementation
uv run python scripts/mutation_voltarget.py              ->  23 / 23 applied, 21 killed,
                                                             2 survivors -- 1 PROVEN INERT
                                                             (conditional, INERT BY ANCHORING)
                                                             and 1 honesty control; 0 defects
                                                             (23 mutations, 9 groups).
                                                             The first run was 16 killed with
                                                             7 survivors: 5 REAL gaps closed
                                                             with new tests, 1 harness defect
                                                             (a mutation that shadowed a later
                                                             model_config and so changed NOTHING),
                                                             and M6.1 which ships as the first
                                                             entry in _INERT_PROOFS
uv run python scripts/live_voltarget_check.py            ->  passes end to end; 5 real tradeable
                                                             ETFs, 1 938 sessions, 504-session
                                                             covariance, sigma_p 8.33% vs a
                                                             10.00% target -> scale 1.2010x;
                                                             over 444 rolling obs the leverage
                                                             clip fires 0.0% and the reflexivity
                                                             warning 13.1%; TWO cross-checks
                                                             (evaluate_drawdown_rules on the
                                                             shared invariant,
                                                             check_rebalancing_drift on the
                                                             shared DISCLOSURE shape), both
                                                             REAL CALLS
uv run python scripts/mutation_kelly.py                  ->  25 / 25 applied, 21 killed,
                                                             4 survivors -- 3 PROVEN INERT
                                                             (1 by EQUIVALENCE, 2 by
                                                             UNREACHABILITY) and 1 honesty
                                                             control; 0 defects
                                                             (25 mutations, 10 groups).
                                                             check_targets refused TWICE,
                                                             both self-inflicted (an
                                                             AMBIGUOUS anchor appearing twice,
                                                             and an anchor written on the WRONG
                                                             SIDE of its own swap). The first
                                                             run had 3 REAL gaps (M1.2 CX1 CX2)
                                                             all closed with new tests. The
                                                             harness was fixed twice: -x is now
                                                             unconditional (without it the
                                                             selection is ~40 min, not ~95 s)
                                                             and a SIGTERM/SIGINT handler
                                                             restores the in-flight mutation,
                                                             because SIGTERM BYPASSED the
                                                             finally and left M5.2 then M9.1
                                                             applied in src/ (D-049's failure
                                                             mode recurring). M7.1's
                                                             unreachability proof CORRECTS the
                                                             module's own docstring
uv run python scripts/live_kelly_check.py                ->  passes end to end; OFFLINE BY
                                                             DESIGN (Kelly's input is a caller
                                                             distribution, not a series), so
                                                             the live check is a cross-check
                                                             against an ORACLE: the shipped grid
                                                             vs the binary closed form
                                                             f*=(p*b-q*a)/(a*b) over 80 combos,
                                                             worst |err| 3.33e-16. Section 2
                                                             refutes the deleted EV/100
                                                             placeholder on the live config;
                                                             section 3 reads the divisor from
                                                             the shipped YAML; section 4
                                                             reproduces the P5b search-edge
                                                             collapse on real inputs
                                                             (distinct REQUESTS: 1 of 3,
                                                             distinct GROWTHS: 3 of 3)
uv run python scripts/mutation_instrument_selection.py   ->  31 / 31 applied, 27 killed,
                                                             4 survivors -- ALL PROVEN
                                                             INERT across THREE classes
                                                             (M3.3 M6.5 by UNREACHABILITY,
                                                             M8.3 by REDUNDANCY, M6.4 by
                                                             INVARIANT) and 0 unexplained;
                                                             the honesty control M9.1 is
                                                             among the 27 killed
                                                             (31 mutations, 7 groups, THREE
                                                             files: instrument_selection.py,
                                                             thesis_layer/schemas.py,
                                                             config.py). `check_targets`
                                                             refused ONCE (CX4: the anchor
                                                             was the accessor's DOCSTRING
                                                             line, not `return {str(key):
                                                             dict(value) for key, value in
                                                             raw.items()}`) and
                                                             `check_tests_collect` is new
                                                             in this harness. The FIRST run
                                                             had 6 survivors, ALL test
                                                             defects, ALL closed
uv run python scripts/live_instrument_selection.py       ->  passes end to end; OFFLINE
                                                             cross-check against the REAL
                                                             ProductionUniverse: all 8
                                                             executable (thesis_type,
                                                             direction) pairs probed, the
                                                             curve instrument re-derived
                                                             from the shipped legs, both
                                                             sentinels confirmed to carry a
                                                             COMPUTED confidence of 0.5,
                                                             and the default legs asserted
                                                             to come from config rather
                                                             than a literal
```
uv run python scripts/mutation_curve_trade.py             ->  31 / 31 applied, 26 killed,
                                                             5 survivors -- 4 PROVEN INERT
                                                             (M5.1 by CONSTRUCTION, M3.2
                                                             and M8.3 and M3.3 by
                                                             UNREACHABILITY) plus the
                                                             honesty control M9.1, which
                                                             SURVIVED as required (31
                                                             mutations, 9 groups, TWO
                                                             files). The FIRST run reported
                                                             31 / 31 KILLED and was FALSE:
                                                             almost every kill named the
                                                             SAME test, which failed on
                                                             UNMUTATED source -- it
                                                             asserted `implausible for '2y'`
                                                             against a validator message
                                                             naming the LONG leg. The
                                                             control was killed too and
                                                             that is what exposed it. Two
                                                             real test gaps closed (M6.3:
                                                             the default direction was
                                                             never tested; M4.5: every
                                                             band fixture used a bad SHORT
                                                             duration), one wrong mutation
                                                             fixed (M6.2's anchor spanned
                                                             only the first of four
                                                             concatenated string lines).
                                                             One anchor now SLICES ITS
                                                             TARGET FROM THE SOURCE FILE
                                                             at import time so it cannot
                                                             drift
                                                              -- NOTE: D-060 REPAIRED
                                                             this sweep. The new
                                                             BreakevenTradeConstructor in
                                                             the SAME FILE shares
                                                             byte-identical validator text,
                                                             so EIGHT of these anchors went
                                                             AMBIGUOUS and the sweep began
                                                             REFUSING TO RUN (exit 2). Every
                                                             affected anchor was extended
                                                             past the shared prefix; the
                                                             repaired sweep reproduced its
                                                             ORIGINAL 31 / 26 / 5 exactly.
uv run python scripts/mutation_breakeven_trade.py         ->  26 / 26 applied, 23 killed,
                                                             3 survivors -- 1 NAME-NOT-VALUE
                                                             (M2.1: same expression, output
                                                             BYTE-IDENTICAL at 1.125481,
                                                             proven by execution),
                                                             1 UNREACHABILITY (M8.3, under
                                                             O-56's 10x float-noise margin)
                                                             plus the honesty control M9.1.
                                                             The FIRST run refused to
                                                             certify (exit 2): M6.1 was a
                                                             real TEST GAP (the mutant ADDS
                                                             a warning the shipped code
                                                             never emits -- D-038's "absence
                                                             half"), now closed; and M1.3's
                                                             exemption was RETIRED because
                                                             the new absence test kills it
uv run python scripts/live_breakeven_trade.py             ->  passes end to end; OFFLINE
uv run python scripts/live_curve_trade.py                ->  passes end to end; OFFLINE
                                                             cross-check against bond_math:
                                                             the notional agrees with the
                                                             DOLLAR-DURATION-matched value
                                                             to 0.0004 once the exact
                                                             relation N_l(dw) =
                                                             N_l(dollardur) * P_l/P_s is
                                                             accounted for -- which is
                                                             itself the finding that
                                                             Section 15.1b's "cancels
                                                             level (PC1) exposure" holds
                                                             only when both legs price
                                                             alike (O-57). Also sweeps
                                                             32 REAL Treasury duration
                                                             pairs (all inside the band),
                                                             shows the percent slip
                                                             CAUGHT and the Macaulay
                                                             substitution NOT caught, and
                                                             closes the D-058/D-059 seam
```

**Progress against the previous milestone:** 139 → 142 formatted files,
1552 → 1583 passing tests. Tier 4 (**3 of 11**): Module 15.2 gained
`models/instrument_selection.py` (the §22.3.1 router), **two new test files**
(`tests/models/test_instrument_selection.py`, 63 tests, and
`tests/thesis_layer/test_production_universe.py`, 30 tests — the first tests
`ProductionUniverse` has ever had), one mutation script (**31 mutations, 7
groups, three files**) and one **offline** live cross-check. One new
`config/settings.yaml` block (`instrument_selection:`, 7 leaves) and
**no registry change** (its inputs are a thesis type and a direction — labels,
not series). The increment also repaired a **latent defect in the already-shipped
`ProductionUniverse`** (`thesis_layer/schemas.py`): its currency matcher
admitted any 6-letter word whose first three letters were a G10 code, and it had
no curve vocabulary at all.

**This increment's failure direction is neither silence nor false confidence — it
is prudence.** A payoff supplied in dollars or basis points where §22.6 requires a
fraction of capital produces a **smaller** `f*`, a cap that *slips* rather than
binds, and a published number that looks **safer** than the correct one. The
function's own guard catches the loss side (`r_i < -1.0` is impossible for a
fractional return) and is silent on `+120`, a legal 12000% gain. The contradiction
is not in the Kelly code at all — it is in
`thesis_layer.schemas.ScenarioOutcome`'s `unit="bp_pnl_proxy"` **default**, three
modules away, and it is recorded as **O-50**. D-054 failed toward **silence**,
D-056 toward **false confidence**, D-057 toward **prudence**; all three are
fail-safe-looking outputs, and the third is the hardest to see because the error
*removes* the signal rather than corrupting it.

**This increment found a drift check that cannot see an instrument it was not told
about, and the failure direction is the *opposite* of the previous increment's.**
All four specification defects are one shape: an input the function was not given
is treated as a **confident zero**, never as unknown. A target with no current
value drifts maximally on no evidence; a position with no target is never iterated
at all — so a book that has drifted **entirely** into unbudgeted instruments
reports `balanced`. D-054's ladder failed toward **silence**; this one fails toward
**false confidence**. Both are fail-safe-looking outputs produced by a missing
input, and both are worse than an exception.

**The boundary fixture did not sit on the boundary, and that is the increment's
most portable finding.** The test asserting "a drift exactly at the threshold does
not flag" used `0.25 + 0.10 - 0.25`, whose float difference is
`0.09999999999999998` — **a hair below** `0.10`. It passed, so it looked like
coverage; but it could not distinguish `>` from `>=`, and the mutant that swaps
them **survived**. Rebuilt on the binary-exact pair `0.225 - 0.125 == 0.10`
(verified: `>` is `False`, `>=` is `True`), and the mutant now dies. **A fixture
must be built by addition of binary-exact values AND that exactness must be
checked, not assumed.**

**`_EXPECTED_INERT` is populated for the first time in this repository, and the
two proofs are deliberately of different strength.** D-053 and D-054 both shipped
it empty (O-42); this increment discharges that discipline with a worked example
and a mechanical guard — the harness **returns exit 2** rather than certifying an
entry that carries no proof. `M4.6` is inert **unconditionally** (the
`abs(signed) > threshold > 0` guard removes `signed == 0` from the direction
test's domain entirely); `CX3` is inert **conditional on the shipped config** (the
`float()` cast is the identity on a `builtins.float` leaf today, and would become
load-bearing if the leaf ever became a `str` or `Decimal`). **Writing both down as
"proven inert" would have been the defect** — the difference is exactly what a
later reader would mistake, so the harness prints the strength beside the proof.

**This increment found a ladder that could never fire, and the failure was
silent.** §6.6c declares its thresholds as **fractions**; `config/settings.yaml`
writes them as **percents**. Read across unconverted that is a **100×** error and
**every rung is unreachable** — the function reports "no risk-reduction rule
triggered" at a **90% drawdown**. For a **de-risking** rule, failing toward
*inaction* is the worst available failure mode, and it is the **opposite** of the
direction the probe predicted. Every gate that existed passed: the config loaded,
the arithmetic was right, the unit tests read the same config the code reads. Only
a probe that **asked what convention each file was written in** could see it.

**The headline finding is dimensional, not compositional.** The band's score-width
**is** `band_pp / beta`, so the two leaves were **not independently choosable** —
setting both set the partition and the slope at once, and neither could then be
validated against the other. That is why the live check's *first* estimator
(band corners) was incoherent: it measured a **contemporaneous level spread** while
the parameter is a coefficient on a **forward change**, and it partly read back the
configuration it was meant to test. See **lesson 48** and **O-41**.

**The specification's own thresholds made `stable` the base state at 79.1%** over
296 real months — **D-047's base-state failure reproduced in a module with no
structural relation to D-047**. It is a new sub-shape: all three members of the
`TrajectoryDirection` `Literal` **are** reachable, so D-045a's reachability check
passes, and the classifier is **effectively two-member** anyway. The reachability
enumeration cannot catch this; the **base-rate measurement** can.

**The sweep found a genuine coverage gap, and it is lesson 49's shape.** All four
corroboration states had a test and `M5.2` **still survived**, because each test
drove **one quadrant** and nothing placed the *disagreeing* inputs against both
*agreeing* branches. **N states with N tests is a hit, not a partition** — the same
distinction lesson 45 draws for warning markers. Repaired with a quadrant-grid test
plus a reachability companion; sweep went 20 → 21 killed.

**Both brief honours earned their keep, and the close-out re-run justified itself
again.** The **cross-check built from the start** (against
`cross_asset_transmission` on the shared labor leg) is what surfaced the config
error. The **sweep re-run at close** **refused on a drifted target**:
`ruff format` had reflowed the `source_independence_count` call from one line into
three after the authoring run. That is the **second formatter-drift in the same
increment** (M10.2's leading whitespace refused the very first run) and the
concrete warrant for lesson 50.

**`_EXPECTED_INERT` is deliberately EMPTY for this increment.** An earlier draft
listed `M8.3` as an expected survivor on the assumption that all fixtures carry
empty warning lists; one test passes a populated list, so it was **killed**. Rather
than substitute another survivor, the set was left empty — **nothing is excused
from having a test**. Carried as **O-42**, since nothing in the harness enforces
that discipline.

**The `check_targets` gate earned its place again.** It refused D-050's first sweep run
with **two ABSENT targets**, because fixing line lengths *inside the sweep file* had
silently rewritten the very strings the table pointed at. That is a mis-target created by
the author rather than inherited from a previous increment, and it was caught before a
single mutation was applied.

**The `check_targets` gate is now in two sweeps and is the load-bearing part of both.**
D-048 introduced it after six mutations turned out to be rewriting the *wrong function*;
D-049's sweep was written with it from the start, and it **refused to run three times** —
once on five mistranscribed targets, once on four, once on one that `ruff format` had
reflowed. No meaningless number was ever printed, which is the point: a sweep that cannot
tell you it did not apply its own mutation is worse than no sweep, because it reports a
false kill rate.

**A sweep that is killed mid-run leaves the SOURCE mutated.** The first D-049 sweep was
`SIGTERM`'d at the tool timeout, so its `finally`-block restore never ran and
`saturated = False` was left in the shipped function. It was found by the *next* run — whose
`check_targets` reported its own target ABSENT — not by the test suite, which passed with
the mutation still in place. Mutation sweeps **run in the foreground only** for this reason,
and the lesson is recorded in D-049.

**Three sweeps are retained, not one.** Each is per-function and none subsumes
another: a later increment can regress an earlier one's kill set, and the full
`pytest` row is the cross-cutting check that catches it while the per-increment
sweep is the narrow one that localises it. **The live-check rows are the same
argument** — `live_regime_check.py` is kept because `inflation_convergence` reads
the same price series, and a change to the shared unit handling would show up in
both.

**The `inert by design` count is now a printed, separate column.** Two mutations
in the Module 5.3 sweep are genuinely inert — they modify code paths that are
**unreachable through the public API** — and the runner reports them apart from
the kills rather than letting them dilute the ratio. A survivor that the author
*knows* is inert is a documented fact; a survivor nobody classified is an
unfinished sweep. See `_EXPECTED_INERT` in the sweep script.

**The mypy figure changed from 31 to 52 source files because** `tests/` **is now
typed too.** It was not before, and the reason turned out to be a missing PEP 561
marker rather than 33 genuine type errors: without `src/macro_engine/py.typed`,
mypy treats an *installed* package as untyped when analysing a different
directory, so every `import` in `tests/` reported `import-untyped` and the real
errors behind them were invisible. Adding the marker surfaced 11 actual problems
(seven `datetime | None` narrowings, four unnecessary `type: ignore` comments)
which are now fixed. The tests' `float(result.value)` call sites are narrowed
through `tests/helpers.py` rather than by casting, because `ModelResult.value` is
a union by design and a cast would defeat the very check that catches a test
reading a verdict as a magnitude.

**Per-function records below are appended in implementation order.** The
authoritative *current* status is `docs/PROGRESS.md`; this file is the evidence
trail behind it.

---



## Phase 0 — Repository skeleton and tooling

**Status: COMPLETE**


| Component          | File                                  | Notes                                                                                                                                |
| ------------------ | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Package management | `pyproject.toml`                      | `uv` only. Ruff config enables `DTZ` (bans naive datetimes) and `T20` (bans stray prints). mypy `strict`, `python_version = "3.12"`. |
| Package root       | `src/macro_engine/__init__.py`        | States the reasoning-layer-not-trading-system scope.                                                                                 |
| Settings           | `config/settings.yaml`                | Every parameter in a `{value, calibration_status, note}` envelope.                                                                   |
| Registry           | `config/series_registry.yaml`         | 21 series, 4 blocked, verification evidence per entry.                                                                               |
| Logging            | `config/logging.yaml`                 | Structured JSON, one object per line.                                                                                                |
| Secrets template   | `.env.example`                        | Secrets only; explicitly never committed.                                                                                            |
| CI                 | `.github/workflows/quality-gates.yml` | `quality` job on push; scheduled `live-data` job.                                                                                    |
| Docs               | `README.md`, `docs/*`                 | This file plus five others.                                                                                                          |




### Phase 0 verification — all 21 LIVE routes verified

Full evidence in `docs/SERIES_VERIFICATION.md`. Summary: **21/21 routes
returned plausible data** on 2026-09-16, each with its observed value recorded
in the registry.

The registry *enforces* this: `RegistrySeries._verified_requires_evidence`
rejects a `status: verified` entry that records no `verified_on` /
`verified_value`, and rejects a `verified_value` outside its own declared
`plausible_range`. An unbacked verification claim — the shortcut an agent would
take to unblock a downstream model — cannot be written.

---



## Phase 1 — Data layer, `MacroDataSnapshot`, thesis schema

**Status: COMPLETE**


| Module                           | Status      | Real-data validated                      |
| -------------------------------- | ----------- | ---------------------------------------- |
| `data_layer/openbb_client.py`    | IMPLEMENTED | yes — 4 series live-fetched              |
| `data_layer/schemas.py`          | IMPLEMENTED | yes — exercised by every live build      |
| `data_layer/validation.py`       | IMPLEMENTED | yes — runs over every live snapshot      |
| `data_layer/snapshot_builder.py` | IMPLEMENTED | yes — 21/21 fields on a full live build  |
| `data_layer/persistence.py`      | IMPLEMENTED | yes — live write/read round-trip         |
| `thesis_layer/schemas.py`        | IMPLEMENTED | yes — 5 schema gates tested              |
| `models/contracts.py`            | IMPLEMENTED | yes — drives every live confidence value |
| `extensions/*.py`                | STUBS       | n/a — Phase 4+, correctly signed         |




### Real-data validation record — `snapshot_builder.build_snapshot()`

**Function:** `build_snapshot(country="us")`
**Retrieved:** 2026-09-16
**Method:** `uv run python -c "from macro_engine.data_layer.snapshot_builder import build_snapshot; ..."`


| Measure                     | Result                                                         |
| --------------------------- | -------------------------------------------------------------- |
| Fields requested            | 21                                                             |
| Fields succeeded            | **21**                                                         |
| Fields failed               | **0**                                                          |
| Fields skipped (unverified) | **0**                                                          |
| Data-quality flags          | **1** (the documented `gdp_potential` forward-looking horizon) |


**Real values retrieved** (latest observation per series):

```
cpi_headline       334.13   @2026-08-01     unemployment_rate    4.10  @2026-08-01
cpi_core           337.77   @2026-08-01     initial_claims    206,000  @2026-09-05
pce_core           130.66   @2026-07-01     continuing_claims 1,774,000 @2026-08-29
ppi                157.41   @2026-08-01     jolts_openings      7,271  @2026-07-01
gdp_real        24,269.61   @2026-04-01     jolts_quits           1.9  @2026-07-01
gdp_nominal     32,486.07   @2026-04-01     fed_funds_rate       3.63  @2026-08-01
gdp_potential   29,443.02   (forward)       sofr                 3.64  @2026-09-15
credit_spread_hy     2.76   @2026-09-15     iorb                 3.65  @2026-09-16
credit_spread_ig     0.80   @2026-09-15     on_rrp_rate          3.50  @2026-09-15
                                            on_rrp_volume_bn     0.70  @2026-09-15
yield_curve (11 tenors)  1mo 3.94 ... 10yr 4.97 ... 30yr 5.34
tips_yields  (5 tenors)  5yr 2.40 ... 10yr 2.60 ... 30yr 3.05
```

**Plausibility assessment — the cross-checks, not just the levels:**


| Check                 | Computed                                          | Verdict                                                                                                         |
| --------------------- | ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| GDP deflator identity | real +2.10%, nominal +6.56% → deflator **+4.46%** | ✅ Three independent FRED symbols satisfy the identity. A mis-mapping would break it. Consistent with PPI 5.41%. |
| 3m10y slope           | **+86bp**                                         | ✅ Positively sloped.                                                                                            |
| 2s10y slope           | **+32bp**                                         | ✅ Positively sloped; short end pricing easing.                                                                  |
| 10yr breakeven        | **+237bp**                                        | ✅ Above the 2% target, consistent with 3.71% CPI.                                                               |
| SOFR − IORB           | **−1bp**                                          | ✅ Inside the corridor.                                                                                          |
| ON RRP rate − IORB    | **−15bp**                                         | ✅ ON RRP rate is the corridor floor.                                                                            |
| IG spread < HY spread | 0.80% < 2.76%                                     | ✅ Structurally required ordering.                                                                               |
| Curve shape           | 10yr 4.97% > 3mo 4.11%                            | ✅ Correct orientation; all 11 tenors present.                                                                   |


**Verdict: economically plausible.** Every cross-series relationship holds,
including the strongest available check (the three-symbol GDP identity).

### Verification that a partial snapshot is visible, not silent

Deliberately exercised by pointing the builder at a field list containing an
unverified series. Result: the field was reported in
`report.skipped_unverified` and flagged
`UNVERIFIED_SERIES_SKIPPED:<field>` in `data_quality_flags`, with the remaining
fields building normally. Graceful degradation with an audit trail.

`test_snapshot_build_reports_unverified_fields_rather_than_failing` asserts it.

### Schema gates — all five verified by test


| Gate                                                              | Enforced on                                                              | Verified              |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------ | --------------------- |
| A live trade requires non-empty `stop_or_invalidation`            | `TradeIdea` (moved here so it cannot be bypassed by skipping the parent) | ✅                     |
| `CONFLICTED` convergence blocks live trade construction           | `MacroThesis`                                                            | ✅                     |
| Scenario probabilities sum to 1.0 within config tolerance         | `MacroThesis`                                                            | ✅                     |
| A no-trade idea cannot carry a direction                          | `TradeIdea`                                                              | ✅                     |
| An instrument outside the production universe cannot be expressed | `ProductionUniverse`                                                     | ✅ 26/26 keyword cases |


**Contract verified:** `ModelResult.value` accepts `float | int | str | bool | dict | list | None` (Section 22.9), and `compute_confidence()` is the sole
producer of every confidence value.

---



## Defects found and fixed during Phase 0/1

Full narrative in `docs/OPEN_ISSUES.md` Part 4 and `docs/DECISIONS.md`.
Recorded here because the *method* by which each was found is the point.


| Defect                                                                          | Found by                 | Impact if shipped                                                   | Doc                 |
| ------------------------------------------------------------------------------- | ------------------------ | ------------------------------------------------------------------- | ------------------- |
| `fred_series` returns dates in an **object-dtype index**, not a `DatetimeIndex` | **live execution**       | Every series fails to parse                                         | SERIES_VERIFICATION |
| Registry `defaults:` block parsed but **never applied**                         | **live execution**       | All 20 scalar fetches fail                                          | D-004               |
| `treasury_curve` (registry key) ≠ `yield_curve` (schema field)                  | **live execution**       | Entire Treasury curve silently absent                               | D-005               |
| Curves written to parquet but **never reconstructed on load**                   | **live round-trip test** | Every curve vanishes from every loaded snapshot                     | D-006               |
| `on_rrp_rate` mapped to a **volume**, not a rate                                | **discovery probe**      | Corridor reads as broken by 295bp on every snapshot                 | D-001               |
| 41 legitimate CBO projections flagged **ERROR**                                 | **live execution**       | Reader trained to ignore the flag list                              | D-002, O-7          |
| Liveness probe treated **404 as healthy**                                       | **user report**          | `/health` would report a dead server as up                          | D-003               |
| `use_local_api_first` default was **~23× slower**                               | **measurement**          | Every build 224s instead of 9.5s — **RE-MEASURED at D-087.19: the 23× does not reproduce (warm ratio 1.20×); the two figures compared a COLD run with a WARM one** | D-003, D-087.19     |
| Validation flags **appended twice**                                             | **live inspection**      | Doubled flag list                                                   | Part 4              |
| Duplicate `fed_funds_rate` schema field                                         | **mypy --strict**        | One declaration silently shadowed                                   | Part 4              |
| Parallel literal field lists in persistence                                     | **design review**        | A field added to one and forgotten in the other disappears silently | D-006               |


**Seven of the eleven were invisible to synthetic tests.** Four of those seven
produced a plausible-looking result rather than an error. This is the standing
evidence for Section 21.0 rule 1 and the reason `docs/ARCHITECTURE.md` treats
live execution as non-substitutable.

---



## Known gaps carried forward


| Gap                                                                                 | Blocks                             | Tracked in         |
| ----------------------------------------------------------------------------------- | ---------------------------------- | ------------------ |
| `gdp_potential` forward projections must be filtered to `observation_date <= as_of` | `output_gap()` in Phase 2          | O-7                |
| `bayesian.likelihoods` table is empty                                               | `bayesian_update` raises by design | OPEN_ISSUES Part 3 |
| 4 inputs BLOCKED (risky credit, iron ore, PPP, supercore)                           | credit/commodity/FX-PPP legs       | OPEN_ISSUES Part 1 |
| Consensus estimates unavailable                                                     | economic-surprise calculation      | O-8                |
| ~~`api_layer/` is empty~~ — **BUILT in D-070** (8 modules, Phase 3 complete)        | —                                  | D-070              |
| `models/` contains only `contracts.py`                                              | Phase 2                            | —                  |
| FX spot / commodity / equity mappings are declared but unpopulated                  | Phase 2 Modules 9–11               | —                  |


---



## What is NOT yet built

**Phases 2–5 are not started.** No model function from Section 6, 15, 16 or 20
exists yet — including the 34 functions Section 20 requires. Those are Phase 2
backfill and will be implemented one at a time under the Section 21.2 process:

> **Step 1 — Read.** … **Step 4 — Unit test** with hand-verified expected
> values … **Step 6 — Real-data execution** … **Step 10 — Report and wait.** Do
> not begin the next function until approved.

Section 21.2 Step 10 governs what happens next: report the current function's
Steps 1–9 and **wait for approval** before beginning the next one.

---



## Phase 2 — Models layer

**Status: IN PROGRESS — 1 of 34 functions implemented (Section 21.2, one at a time)**


| Module | Function                     | Tier | Status          | Real-data validated |
| ------ | ---------------------------- | ---- | --------------- | ------------------- |
| 7      | `output_gap`                 | 1    | **IMPLEMENTED** | yes — 2026-09-16    |
| 7      | `simple_gdp_nowcast`         | 2    | STUB            | no                  |
| 3      | `classify_regime_rule_based` | 3    | STUB            | no                  |
| 3      | `regime_switching`           | 5+   | STUB            | no                  |


Supporting infrastructure implemented alongside:


| Component        | File                 | Purpose                                                                 |
| ---------------- | -------------------- | ----------------------------------------------------------------------- |
| As-of discipline | `models/as_of.py`    | `observation_as_of()` — the O-7 filter, shared by every series consumer |
| Models package   | `models/__init__.py` | States the no-fetching rule and the two-tier status contract            |




### Real-data validation record — `output_gap()`

**Function:** `output_gap` / `output_gap_from_snapshot`
**Retrieved:** 2026-09-16
**Series:** FRED `GDPC1` (gdp_real) and FRED `GDPPOT` (gdp_potential)
**Method:** `uv run python -c "from macro_engine.data_layer.snapshot_builder import build_snapshot; ..."`


| Measure           | Result                                                              |
| ----------------- | ------------------------------------------------------------------- |
| Fields fetched    | 2 / 2                                                               |
| Pairing date used | `2026-04-01` (latest quarter where BOTH series have an observation) |
| Actual GDP        | 24,269.613                                                          |
| Potential GDP     | 24,070.9386484                                                      |
| **Output gap**    | **+0.83%** (rounded from +0.8253701881011124)                       |
| Confidence        | 0.25 (computed, not asserted)                                       |
| Points withheld   | 42 — 41 CBO projections + 1 realised-but-unpaired quarter           |
| Withheld horizon  | 2036-10-01                                                          |
| Publication lag   | 1 quarter (normal)                                                  |


**Hand verification.** `(24269.613 - 24070.9386484) / 24070.9386484 * 100 = 0.8253701881011124`, which rounds to `0.83`. Computed independently of the code,
then asserted in `test_output_gap_matches_the_specified_formula_exactly`.

### Plausibility assessment — Step 7

The verdict is **economically plausible**, on three independent grounds rather
than on "it ran":

**1. The 20-quarter gap history is continuous and bracketed.**


| Quarter    | Actual         | Potential       | Gap        |
| ---------- | -------------- | --------------- | ---------- |
| 2024Q3     | 23,478.570     | 23,126.8961     | +1.52%     |
| 2024Q4     | 23,586.542     | 23,271.5417     | +1.35%     |
| 2025Q1     | 23,548.210     | 23,414.6564     | +0.57%     |
| 2025Q2     | 23,770.976     | 23,548.5177     | +0.94%     |
| 2025Q3     | 24,026.834     | 23,680.1525     | +1.46%     |
| 2025Q4     | 24,055.749     | 23,811.2239     | +1.03%     |
| 2026Q1     | 24,180.419     | 23,945.1378     | +0.98%     |
| **2026Q2** | **24,269.613** | **24,070.9386** | **+0.83%** |


Range over all 20 quarters: **+0.57% to +2.02%**, mean **+1.12%**. The new
value sits inside the series' own recent range and continues its direction
(gradual narrowing from the +1.52% peak). This is what a late-cycle economy
losing momentum looks like.

**2. The unpaired computation is visibly the outlier.** It returns **+0.29%** —
the lowest value in the entire 20-quarter window, breaking a series that runs
0.57–2.02%. A value that is individually plausible but sits outside the range
its own history occupies is the numerical signature of measuring a different
quantity, which is precisely what pairing Q2 actual against Q3 potential does.

**3. It agrees with the snapshot's independent signals.** Unemployment is
**4.10%** against a NAIRU config estimate of **4.4%** — the labour market is
tight by 0.30pp. A modestly *positive* output gap (+0.83%) and a modestly tight
labour market are the same statement about the same economy. (A negative gap
would not necessarily contradict it, since the output gap leads unemployment,
but the agreement here is corroboration rather than coincidence.)

**Growth-rate cross-check.** Potential GDP's QoQ annualised growth is
**+2.12%**, against CBO's long-run potential-growth assumption of roughly
1.5–2.0% — slightly high but within the range a strong-productivity quarter
would produce. Actual GDP's QoQ annualised growth is **+1.48%**, below
potential, consistent with the gap narrowing.

### Defects found during this function's implementation

Two genuine defects, both found by real-data execution and invisible to
synthetic tests — the third and fourth confirmations of Section 21.0 rule 1.


| Defect                                                                                       | Found by                              | Impact if shipped                                                                  | Doc            |
| -------------------------------------------------------------------------------------------- | ------------------------------------- | ---------------------------------------------------------------------------------- | -------------- |
| Output gap paired mismatched quarters (Q2 actual vs Q3 potential)                            | **real-data execution**               | +0.29% instead of +0.83% — plausible, wrong, and the lowest reading in 20 quarters | D-009          |
| `gdp_potential` verified against its own 2036 projection                                     | **registry audit triggered by D-009** | A 22% overstatement of current potential output, recorded as *evidence*            | D-010          |
| Confidence test could not distinguish a computation from the banned literal                  | **mutation testing**                  | Test would pass with `confidence=0.5` hardcoded, violating Section 22.8            | test docstring |
| Registry `seasonality` not recorded for a series compared against a differently-adjusted one | **FRED series-page check**            | SAAR/NSA mismatch invisible to any consumer                                        | D-010          |




### Warning paths — all triggered by test (Step 5)


| Warning                                       | Test                                                             |
| --------------------------------------------- | ---------------------------------------------------------------- |
| Potential GDP is an estimate, not observed    | `test_output_gap_always_warns_that_potential_is_an_estimate`     |
| CBO projections withheld (O-7)                | `test_output_gap_from_snapshot_warns_about_withheld_projections` |
| Potential runs a quarter beyond actual        | `test_output_gap_from_snapshot_warns_when_potential_runs_ahead`  |
| Actual-GDP fetch is stale (>1 quarter behind) | `test_output_gap_warns_when_the_actual_series_goes_stale`        |


The staleness test asserts the warning fires at **2** quarters **and does not
fire at 1** — a warning that fires on the ordinary case is noise, and noise is
how real warnings get ignored.

### Mutation testing — do the tests actually catch the defects?

Section 21.2 Step 4 warns that a test passing on the first attempt may be
asserting whatever the code produced. Each guard was therefore verified by
breaking it and confirming the suite fails:


| Mutation                                          | Tests failing     |
| ------------------------------------------------- | ----------------- |
| Remove the O-7 as-of filter                       | **4**             |
| Invert the gap sign                               | **6**             |
| Revert to each series' own latest quarter (D-009) | **4**             |
| Hardcode `confidence=0.5`                         | **0** — see below |
| Remove the D-010 registry guard                   | **2**             |


The confidence mutation is a **recorded finding, not a passed check**: with all
`confidence:` constants at `uncalibrated_illustrative`, the formula's output for
this model coincides exactly with Section 6.5's illustrative literal
(`base 0.7 − unobservable 0.2 = 0.5`). Under this config, no black-box assertion
on confidence alone can distinguish computation from a hardcoded literal. The
test is written to say so, and
`test_confidence_formula_becomes_discriminating_once_calibrated` enforces the
real requirement the moment Phase 5+ calibrates `base` — its skip is
conditional on a measured discrimination gap of zero, so it cannot rot into a
test nobody notices is not running.

### Known gaps carried forward from Phase 2


| Gap                                          | Blocks                        | Tracked in                  |
| -------------------------------------------- | ----------------------------- | --------------------------- |
| Confidence formula cannot be mutation-tested | Phase 5+ calibration          | test docstring, BUILD_STATE |
| `simple_gdp_nowcast` is a stub               | Module 7's nowcast output     | Section 21.3 Tier 2         |
| No consensus/expectations source             | economic-surprise computation | O-8                         |


Section 21.2 Step 10 governs what happens next: **report this function's Steps
1–9 and wait for approval** before beginning the next one.

---



## Phase 2 — Tier 1 complete and the enterprise infrastructure

**Status: Tier 1 of Phase 2 COMPLETE (23/23). Tier 2–4 outstanding.**

### Tier 1 functions implemented

All 23 Tier 1 functions now carry their own module, hand-verified tests, an
explicit warning path, and a `ModelResult` shape.


| Module | File                                                               | Functions                                                                                                                                                              |
| ------ | ------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1      | `models/output_gap.py`, `models/gdp_nowcast.py`, `models/as_of.py` | `output_gap`                                                                                                                                                           |
| 2      | `models/bond_math.py`                                              | `price_bond`, `macaulay_duration`, `modified_duration`, `convexity`, `price_change_with_convexity`, `repo_stress_check`                                                |
| 3      | `models/national_accounts.py`                                      | `gdp_deflator`, `savings_investment_identity`, `quantity_theory_implied_inflation`, `laspeyres_index`, `paasche_index`, `fisher_index`, `openings_to_unemployed_ratio` |
| 8      | `models/yield_curve.py`                                            | `curve_slope`, `breakeven_inflation`, `decompose_yield`                                                                                                                |
| 17–18  | `models/risk.py`                                                   | `historical_var`, `expected_shortfall`, `parametric_var`, `realized_vol_simple`, `portfolio_volatility_two_asset`                                                      |


Every threshold the specification states as a literal — repo-stress bands,
inversion depths, steepness bands, openings-ratio bands — is externalized to
`config/settings.yaml` under `bond_math` and `labor.openings_ratio`, each with a
`calibration_status` (D-013). No comparison in the models layer reads a numeric
literal.

### Enterprise infrastructure built this session

Four components, requested explicitly and delivered as first-class modules
rather than as conventions:


| Component                       | Module                       | Requirement it satisfies                                                                                                                                  |
| ------------------------------- | ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Environment-based configuration | `deployment.py`              | Every endpoint, credential, path and port resolves through a declared `EnvironmentVariable`; production requirements are checked at startup, all at once. |
| Database-driven settings        | `settings_store.py`          | Bitemporal, append-only revisions with mandatory actor and reason (D-014, D-017).                                                                         |
| Structured JSON logging         | `data_layer/logging_json.py` | One parseable object per line; credential-shaped keys redacted; audit fields carried (D-016).                                                             |
| Audit trails                    | `audit.py`                   | Append-only model and thesis ledgers storing inputs **by value, not by reference** (D-015).                                                               |




### Defects found and fixed in this batch


| #     | Defect                                                                                                                                                                                                                                                                       | Why tests missed it                                                                                    | Decision |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | -------- |
| D-011 | `Settings.scalar()` / `is_calibrated()` type-checked leaves against `dict` only, so every `CalibratedValue`-typed block was unreachable. Consequence: `calibration_status` was inert for every typed block and no model could earn the confidence its calibration justified. | No consumer had appeared for a typed block. The accessor was "tested" against one shape.               | D-011    |
| D-012 | `macaulay_duration()` divided by `price_bond()`'s value already rounded to 2dp for presentation, returning `2.828` against a hand-calculated `2.829`.                                                                                                                        | Both values are plausible; only hand-verification of the fourth digit exposed it.                      | D-012    |
| D-016 | `JsonFormatter` redacted values but never inspected keys, so `extra={"api_key": "..."}` shipped the secret verbatim.                                                                                                                                                         | There was no formatter test at all — only a `_redact` test, which passed. The bug was in the *caller*. | D-016    |
| D-017 | `settings_store` stamped revisions with a microsecond clock that **collides** (measured: 119 collisions / 2000 calls), collapsing revision intervals to zero width and making intermediate values unrecoverable by `value_at()`.                                             | First test ever written against `value_at()` found it.                                                 | D-017    |
| D-018 | `EnvironmentVariable.resolve()` had two states, not three: `MACRO_API_KEY_HASH` was neither required nor defaulted in development, so a clean checkout could not start the service.                                                                                          | The deployment config had no test until this session.                                                  | D-018    |


Three of the five (D-011, D-012, D-016) are the Section 21.0 failure class: a
**plausible-looking wrong value** rather than an error. None would have been
found by a synthetic test of the component in isolation, because in each case the
defect was at a seam — between an accessor and its first consumer, between a
rounding boundary and a caller that needed the unrounded value, between a helper
and the way it was invoked.

### Mutation testing — do the tests actually catch the defects?

Each guard added this session was removed individually and the suite re-run.


| Mutation applied                                              | Tests failed |
| ------------------------------------------------------------- | ------------ |
| Revert log redaction to value-only in the context block       | **3**        |
| Remove the monotonic timestamp bump in `settings_store.set()` | **1**        |


The second row is the instructive one. The **first** version of
`test_consecutive_writes_are_strictly_ordered` passed with the guard removed — a
SQLite round-trip costs more than a microsecond, so natural collisions do not
occur at database-write cadence and the guard never fired. The test was rewritten
to freeze `utc_now()` and inject the degenerate case directly. It now fails
without the guard. *A test that cannot fail is not a test*, and a passing
mutation is the only way to know which kind you have (D-017).

### Warning paths — triggered by test, not assumed


| Function                            | Warning path                                                                                                          | Test                                              |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| `repo_stress_check`                 | Severity capped to `ELEVATED` without persistence + volume corroboration (§22.11)                                     | 4 corroboration-combination tests                 |
| `repo_stress_check`                 | Corridor not intact (IORB <= ON-RRP) surfaced                                                                         | `test_corridor_breach_is_reported`                |
| `decompose_yield`                   | No term premium → `expectations_component: None` + hard warning, never a silent substitution of the raw yield (§22.5) | `test_decompose_yield_without_term_premium_warns` |
| `quantity_theory_implied_inflation` | Heuristic penalty applied; `is_calibrated` false                                                                      | `test_quantity_theory_is_marked_low_confidence`   |
| `output_gap`                        | Pairing on common observation date (§22.4 / D-009)                                                                    | `test_output_gap_pairs_on_common_quarter`         |




### Known gaps carried forward from Phase 2


| Gap                                                           | Blocks                                               | Tracked in                  |
| ------------------------------------------------------------- | ---------------------------------------------------- | --------------------------- |
| Confidence formula cannot be mutation-tested                  | Phase 5+ calibration                                 | test docstring, BUILD_STATE |
| `simple_gdp_nowcast` is a stub                                | Module 7's nowcast output                            | Section 21.3 Tier 2         |
| No consensus/expectations source                              | economic-surprise computation                        | O-8                         |
| `portfolio_volatility_n_asset`, `marginal_risk_contributions` | Tier 1 tail, needs a `weights`/`covariance` contract | Section 21.3 Tier 1         |
| `docs/MODULE_MAPPING.md` not written                          | specification-to-code traceability                   | Section 21.2 Step 9         |


Section 21.2 Step 10's "wait for approval between functions" is **suspended by
explicit user instruction** — the user directed completion of Phase 2 and
progression to Phase 3 — so Tier 2 proceeds continuously, with the same
per-function obligations (hand-verified unit test, warning-path test, real-data
execution, recorded evidence) intact.

---



## Phase 2 — Tier 2 module batch: labor synthesis (Module 6)

**Status: COMPLETE for this batch (4 functions). Tier 2 continues.**


| Function                  | Module | Status      | Hand-verified value        | Live-executed                 |
| ------------------------- | ------ | ----------- | -------------------------- | ----------------------------- |
| `labor_tightness_score`   | 6.4    | IMPLEMENTED | +3.52 raw → +3.5           | config-derived inputs         |
| `claims_trend_signal`     | 6.1    | IMPLEMENTED | see D-022/D-024            | **yes — real FRED ICSA/CCSA** |
| `claims_corroboration`    | 6.3    | IMPLEMENTED | 4 branches                 | **yes — real FRED ICSA/CCSA** |
| `inflation_breadth_score` | 6.3    | IMPLEMENTED | +0.2 from (+0.2,+0.3,+0.1) | config-derived inputs         |




### Defects found in this batch

Both were found by live execution against real FRED series, and neither was
visible to any synthetic test. This is the fifth and sixth confirmed instances of
the §21.0 pattern in Phase 2.


| Defect                                                                                  | Found by                                                                                               | Consequence                                                                                            | Decision |
| --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------ | -------- |
| Baseline window mis-sliced: a 4-week mean subtracted from a week of the trailing window | live ICSA run — **the rendered prose contradicted itself** ("only -3.1% above ... below the 5.0% bar") | a +2.2% quarterly rise reported as a **-3.1% decline**: a sign error, not a rounding artifact          | D-022    |
| "Leading quarter vs window mean" inverts the sign on any trending series                | the tests written for D-022 failing                                                                    | a +2%/week deterioration reports **-8.8%**; the model could never detect the thing it exists to detect | D-024    |
| Interpretation said "only X above" when X was negative                                  | same live run                                                                                          | a reader skimming the summary draws the wrong direction, which in a nowcast is the whole message       | D-023    |


D-024 supersedes D-022's *comparison logic* while retaining its finding. The
final definition compares the latest 4-week average against the same 4 weeks of
the prior quarter — disjoint, equally smoothed, same phase, and it is the
comparison an analyst actually makes.

### Mutation testing — every new guard


| Mutation                                                   | Tests that fail                                   |
| ---------------------------------------------------------- | ------------------------------------------------- |
| Swap `latest_ma4` / `trailing_ma4` windows                 | **7**                                             |
| Baseline → 13-week window mean (pre-D-024 shape)           | 1                                                 |
| Baseline → last 4 weeks of window (original pre-D-022 bug) | 6                                                 |
| `>` → `>=` on the magnitude threshold                      | **1** (after adding the boundary test it exposed) |
| Remove the claims sign inversion (`-2.0` → `+2.0`)         | 2                                                 |
| Remove the quits centring offset (`50.0` → `0.0`)          | 4                                                 |
| Make `claims_corroboration` confidence vary by verdict     | 1                                                 |


Two mutations initially **survived**, and both were investigated rather than
waved through:

- `>` → `>=` survived because no test pinned the boundary. A boundary test was
added, engineered to land exactly on the threshold, and the mutation now fails.
- The `has_structural_uncertainty` mutation survived because that penalty has
**no effect** once `is_heuristic_not_calibrated` is set — both produce `0.5`.
A second mutation with a genuinely varying confidence was run and **did** fail
the identical-confidence test, confirming the test is sound and the first
mutation was simply inert.



### Warning-path coverage

`claims_trend_signal` has four interpretation branches (both met, persistence
only, magnitude only, neither) plus a below-baseline variant of two of them; all
are exercised, and the branch wording for a negative reading is asserted not to
contain the contradictory "only … above" construction.

### The cross-field identity this batch is pinned to

```
pct_above_trailing == (latest_4wk_avg - trailing_4wk_avg) / trailing_4wk_avg
```

Asserted at the reported precision (3dp), and the **sign** asserted against
hand-built series whose direction is known before the code runs. A shape-only
assertion passed all three successive wrong implementations of this function;
the identity-plus-direction pair failed each one immediately.

---



## Phase 2 — Tier 2 module batch: Module 6 remainder (4 functions)

Built 2026-09-17, one function at a time in dependency order, per Section 21.2.

### Functions


| Function                     | `value` type                     | Branches | Status          |
| ---------------------------- | -------------------------------- | -------- | --------------- |
| `two_survey_divergence`      | `str` verdict                    | 4        | **IMPLEMENTED** |
| `beveridge_curve_position`   | `dict` (verdict, shift_pp)       | 3        | **IMPLEMENTED** |
| `ahe_composition_flag`       | `dict` (flag, gap)               | 4        | **IMPLEMENTED** |
| `nfp_revision_adjusted_read` | `dict` (headline, net, adjusted) | 2        | **IMPLEMENTED** |


Plus `TwoSurveyInputs`, `BeveridgeInputs`, `AHEDistortionInputs`,
`RevisionInputs` — all `extra="forbid"`.

### New configuration (no literals in any model)


| Path                                               | Value | Status                    | Why configurable                                                                            |
| -------------------------------------------------- | ----- | ------------------------- | ------------------------------------------------------------------------------------------- |
| `beveridge.shift_tolerance.shift_pp`               | 0.5   | uncalibrated_illustrative | Resolution of the fitted curve — should become the curve's standard error in Phase 5+       |
| `labor.two_survey.min_meaningful_change_thousands` | 0.0   | uncalibrated_illustrative | Published rule is sign-only; the slot exists so a calibrated dead-band needs no code change |
| `labor.ahe_distortion.low_wage_decline_pct`        | -1.0  | uncalibrated_illustrative | Section 20.6 literal                                                                        |
| `labor.ahe_distortion.eci_divergence_pp`           | 0.75  | uncalibrated_illustrative | Section 20.6 literal                                                                        |
| `labor.revisions.misleading_net_thousands`         | -50.0 | uncalibrated_illustrative | Section 20.6 literal                                                                        |


`BeveridgeSettings.openings_at()` (linear interpolation of the fitted pre-COVID
curve) already existed from Phase 1 and is now **used** rather than merely
present — the model takes the curve's prediction as an input
(`historical_openings_at_this_u`) instead of re-deriving a functional form,
so the fitted assumption stays in one documented place.

### Defects found in this batch

**None in the four new functions.** One finding was made against the
*verification script*, recorded as **D-025**: FRED's `UNRATE` genuinely omits
`2025-10-01`, so any `[-1] - [-2]` "month-over-month" arithmetic spans two
months across that gap. The model is not at fault — the caller supplies the
change — but the cadence check that would have caught it did not exist, and the
field descriptions do not yet name the span they expect. Recorded as an open
item for Phase 3 rather than patched locally.

### Mutation testing — every new guard

**13 mutations, 13 killed, 0 survivors.** Run against
`tests/models/test_labor_two_survey.py` after the final reformat.


| #   | Mutation                                            | Result |
| --- | --------------------------------------------------- | ------ |
| 1   | Beveridge thresholds swapped (`>` → `<`)            | killed |
| 2   | Beveridge operands reversed                         | killed |
| 3   | Beveridge band boundary `>` → `>=`                  | killed |
| 4   | AHE divergence loses `abs()`                        | killed |
| 5   | AHE drops the ECI-absent branch                     | killed |
| 6   | AHE mechanism test inverted                         | killed |
| 7   | AHE reports `0.0` instead of `None`                 | killed |
| 8   | Revision drops the positive-headline requirement    | killed |
| 9   | Revision net uses subtraction not addition          | killed |
| 10  | Two-survey benign branch inverted                   | killed |
| 11  | Two-survey benign branch requires bad participation | killed |
| 12  | Two-survey treats `0.0` as "up" (`>` → `>=`)        | killed |
| 13  | AHE divergence boundary `>` → `>=`                  | killed |


Four mutations (3, 12, 13, and the revision threshold) target `>` **vs** `>=` **at
a configurable boundary**. Those are the mutations that survive when no test
lands exactly on the threshold, so each has a dedicated boundary test whose
fixture is **built from the config value** — a recalibration moves the test with
the code instead of silently making it vacuous.

### Warning-path coverage

Every `warnings` branch is triggered at least once by test:

- two-survey: the absorption caveat (benign branch only), the disagreement
warning (fires only when signs differ), and the always-present sign-only
disclosure.
- Beveridge: `phillips_curve_inflation` propagation on outward **and** inward,
plus the "on-curve does not mean stable" caveat asserted on an on-curve result.
- AHE: the ECI-preference warning on a flagged result, and the aggregate-
limitation warning asserted on an **unflagged** result.
- Revisions: the masked-beat warning, and the benchmark-incompleteness
disclosure asserted on an unflagged result.



### The cross-field identities this batch is pinned to

```
beveridge:  shift_pp == openings_rate_pct - historical_openings_at_this_u
revisions:  revision_adjusted == headline + prior_month_revision + two_months_ago_revision
ahe:        ahe_minus_eci_pp is None exactly when eci_growth_yoy_pct is None
```

Each is asserted against **independently expressed** arithmetic, so an operand
swap or a dropped sign fails even when the branch thresholds happen to be met.
The AHE identity is the strongest of the three: it pins the *absence* semantics
(`None`, never `0.0`), which is the same defect class as substituting a proxy
for a BLOCKED input.

### Real-data validation record (Section 21.0)

`scripts/live_labor_check.py`, against the live local OpenBB API:


| Function                     | Real input                                                  | Output                       | Independent check                                                                  |
| ---------------------------- | ----------------------------------------------------------- | ---------------------------- | ---------------------------------------------------------------------------------- |
| `two_survey_divergence`      | PAYEMS +162k, CE16OV +569k, UNRATE +0.00pp, CIVPART +0.20pp | `CONSISTENT_STRENGTH`        | verdict re-derived from the four live signs; household/payrolls level ratio 1.0231 |
| `beveridge_curve_position`   | JTSJOL 7,271k → 4.328% openings, UNRATE 4.1%, curve 4.220%  | `ON_CURVE_cyclical`, +0.11pp | shift matches the script's own subtraction                                         |
| `nfp_revision_adjusted_read` | PAYEMS change +162k, zero revisions                         | adjusted == headline         | zero-revision identity asserted; no masked-beat warning fires                      |
| `ahe_composition_flag`       | ECI genuinely unavailable                                   | `ahe_minus_eci_pp is None`   | `None` not `0.0` asserted                                                          |


**The household half is now a genuinely different series.** `CE16OV`
(household employment, people) rather than a copy of payrolls, which makes the
two-survey call a real comparison. The level cross-check —
household/payrolls within 10% — is a **cross-series plausibility assertion**, so
a mis-mapped symbol fails here even though it would return an individually
plausible number.

### Known gaps carried forward

- `two_survey_divergence` classifies on **sign only** and says so in a warning.
A `min_meaningful_change` config slot exists but is **unused** — wiring it in
changes behaviour (small moves would stop counting) and was not specified.
Recorded rather than silently ignored.
- `beveridge_curve_position` is measured against a **pre-COVID** fitted curve.
If post-COVID matching genuinely changed, the baseline is stale and the shift
is overstated. Carried as a warning on the outward branch.
- `nfp_revision_adjusted_read` counts only **two** months of revisions; the
annual benchmark revises twice more. Carried as an always-present warning.
- `ahe_composition_flag`'s low-wage input is a **single aggregate** that cannot
separate composition shift within sectors from pay changes. Always warned.
- **D-025** — change-typed inputs do not name the span they cover.
`MacroDataSnapshot` should carry per-field observation dates in Phase 3.



## Phase 2 — Tier 2: `phillips_curve_inflation` (Module 3.3)

`src/macro_engine/models/inflation_dynamics.py` (new, ~250 lines),
`tests/models/test_inflation_dynamics.py` (new, 26 tests).

### Function


| Function                   | Module | `value` type | Confidence | Status      |
| -------------------------- | ------ | ------------ | ---------- | ----------- |
| `phillips_curve_inflation` | 3.3    | `float`      | `0.30`     | IMPLEMENTED |




### The sign convention, and why it gets its own paragraph

`pi = pi^e - beta * (u - u*)`. When unemployment is **below** u*, the parenthesised
term is negative, and *subtracting a negative* raises inflation. A tight labor
market is inflationary. The inverted implementation — `pi^e + beta * (u - u*)` —
returns **2.30%** on a tight market where the correct answer is **2.70%**, and
**3.00%** vs **2.00%** on a slack one. Both inverted numbers are individually
plausible readings of the same inputs. Nothing about the shape of the output
distinguishes them.

The defence is a **direction assertion against a case whose answer is known
before the code runs**: `test_tight_labor_market_raises_inflation_above_expectations`
asserts `value > pi^e` on a tight market, and its paired test asserts
`value < pi^e` on a slack one. Pinning `== 2.70` alone would be satisfied by an
implementation that got there for the wrong reason.

### `beta` is deliberately not an input field

The specification's sample declares `beta: float = 0.5` with the comment
"sensitivity, configurable", and `config/settings.yaml` already carries
`phillips.beta`. Two sources of truth where one has a **silent default** is the
§22.x defect class: callers who omit the argument get 0.5 regardless of config,
and a recalibration moves nothing. `test_beta_is_not_an_input_field` asserts
`set(PhillipsCurveInputs.model_fields) == {"inflation_expectations", "unemployment_rate", "nairu"}`, and `test_beta_passed_as_a_field_is_rejected_rather_than_ignored`
asserts the typo fails loudly under `extra="forbid"` rather than feeding a
default.

### Finding D-026 — the specification names the wrong dominant uncertainty

Module 3.3's warning says *"u (NAIRU) is UNOBSERVABLE ... this is the dominant
uncertainty here"*. Live data says otherwise:


| Source of variation                                            | Move in output |
| -------------------------------------------------------------- | -------------- |
| `pi^e` measure choice (Michigan 4.20% vs 10yr breakeven 2.37%) | **1.83pp**     |
| A 0.5pp error in u* (`beta * 0.5`)                             | **0.25pp**     |


The expectations-measure choice dominates by roughly **7×**. The model was
arithmetically correct — the caveat pointed readers at the *smaller* of two real
risks, which is worse than saying nothing, because it supplies a false sense of
where the error lives. The warning order and framing were corrected, and two new
tests pin it:

- `test_expectations_choice_warning_is_ranked_first` — asserts the phrase
`"largest single source of variation"` appears in `warnings[0]`, that the u*
warning contains `"SECOND-ORDER"`, and that it does **not** still contain
`"dominant uncertainty"`. A warning that exists but is ranked wrong is a
defect, so the assertion is **positional**.
- `test_expectations_ratio_exceeds_the_u_star_sensitivity` — asserts
`1.83 > abs(beta) * 0.5` arithmetically, so the ranking is checked against the
config value rather than a remembered literal. A recalibration that inverted
the ranking would fail here.



### Mutation testing — 13/13 killed, 0 survivors

Nine core guards (sign inversion, `beta` from a literal instead of config,
`gap = u* - u`, missing unobservable penalty, heuristic penalty dropped, rounding
moved before the clamp-free arithmetic, gap reported unrounded, `>=` vs `>` on
the negligible-slack threshold, negative-inflation warning removed) plus four
D-026 ordering guards.

One mutation survived on the first sweep — `abs(slack_contribution) < 0.05` →
`< 0.051` — because no fixture landed between the two. Reclassified as a **weak
test** rather than an inert mutation and fixed by moving a fixture onto the
threshold, per the boundary-mutation rule.

### Warning-path coverage


| Warning                                                  | Trigger                 | Test                                                    |
| -------------------------------------------------------- | ----------------------- | ------------------------------------------------------- |
| `pi^e` measure is the largest single source of variation | unconditional           | `test_expectations_choice_warning_is_ranked_first`      |
| u* unobservable, SECOND-ORDER effect                     | unconditional           | `test_expectations_choice_warning_is_ranked_first`      |
| Unanchored `pi^e` ⇒ slack term stops mattering           | unconditional           | `test_unanchored_expectations_caveat_is_always_present` |
| Negligible slack contribution                            | `abs(-beta*gap) < 0.05` | `test_negligible_slack_warning_fires_at_the_boundary`   |
| Negative implied inflation                               | `implied < 0.0`         | `test_negative_implied_inflation_is_flagged`            |




### Real-data validation record (Section 21.0)

`scripts/live_labor_check.py::_check_phillips`, against the live local OpenBB API.
**Both** `pi^e` measures are computed, because using only one would hide exactly
the variation D-026 identifies:


| Input         | Real value       | Series                                 |
| ------------- | ---------------- | -------------------------------------- |
| Market `pi^e` | `DGS10 - DFII10` | 10yr nominal minus 10yr TIPS           |
| Survey `pi^e` | `MICH`           | University of Michigan 1yr expectation |
| u             | `UNRATE`         | 4.1%                                   |
| u*            | config           | `phillips.nairu`                       |


Checks performed, all passing:

1. **Both measures differ by** `> 0.25pp`**.** This is a *cross-source* assertion: if
  either leg were mis-mapped the two would collapse toward each other. Two
   genuinely independent measures agreeing to the basis point would mean one of
   them is not what it claims to be.
2. **Direction against the live u-gap** — recomputed independently in the script
  rather than read back from the model.
3. **Cross-field identity** — `value == round(breakeven - beta * gap, 2)`,
  recomputed from the reported components.
4. **The dominance comparison is printed**, so the D-026 ranking is re-verified
  against live numbers on every run rather than only against the fixture that
   established it.



### Known gaps carried forward

- The model returns a **point estimate plus warnings**, not a range. Section
21.4 item 13 makes u* unobservable, so a genuinely honest output is a band
across u* values. `build_scenario_distribution` (Tier 4) is the specified
home for that; until it exists the dispersion is described in prose.
- `pi^e` has **no config default**, deliberately. The caller must choose and
record a measure. This is a design decision rather than a gap, but it means a
future `MacroDataSnapshot` field must name which measure it carries — the same
finding as **D-025** in a different dimension (a number with no provenance).



## Phase 2 — Tier 2: `potential_gdp_cobb_douglas` + `growth_accounting_decomposition` (Module 3.5 / 7.2)

`src/macro_engine/models/production_function.py` (new, ~470 lines),
`tests/models/test_production_function.py` (new, 43 tests),
`scripts/mutation_production_function.py` (new, 20-mutation sweep).

### Functions


| Function                          | Module    | `value` type | Confidence                       | Status      |
| --------------------------------- | --------- | ------------ | -------------------------------- | ----------- |
| `potential_gdp_cobb_douglas`      | 3.5 / 7.2 | `float`      | `0.30`                           | IMPLEMENTED |
| `growth_accounting_decomposition` | 3.5       | `dict`       | computed (drops under dominance) | IMPLEMENTED |


Tier 2 is now **15/29**.

### The golden case is exact by construction, which is why it needs a partner

Section 20.3's test — `A=1, K=100, L=100, alpha=0.3` returns exactly `100.0` —
holds because `100^0.3 * 100^0.7 = 100^1`. The cancellation is the *point*: it
isolates the exponent arithmetic from the inputs. But it also means an
implementation that assigns `alpha` to **both** factors still returns a
round-looking number (`100^0.3 * 100^0.3 = 15.85`), and a test that only asserts
`== 100.0` cannot distinguish a transposed implementation from a correct one
whenever `K == L`. A second case with `K != L` and non-cancelling terms
(`A=20, K=40,000, L=160,000 → 2,111,212.66`) supplies the discrimination.

### Defect found during implementation — a mis-stated hand calculation

The module docstring's second worked example originally carried
`L^0.7 = 6623.9047` and a product of `3,252,491.2`. `L^0.7` is **4394.2422**;
the product is **2,111,212.66**. Written from recollection rather than computed,
and every intermediate step still *looked* like arithmetic.

The test asserting the wrong value failed against a **correct** model — the right
direction for this class of defect, and the reason the hand-verified case is
written before the model rather than after it. Recorded in **D-027** rather than
quietly corrected.

### Defect found during the live run — a cadence mismatch, caught by the pairing assertion

`PRS85006023` (business-sector average weekly hours) is **quarterly** and runs to
`2026-04-01`. `PAYEMS` (payrolls) is **monthly** and runs to `2026-08-01`.
Multiplying `hours[-1] * emp[-1]` would have computed a "total hours" from Q2
hours and **August** employment — a number with no observation date, still smooth
and plausible.

The first version of the script asserted the two shared a latest date and
**failed on live data**, which is how the mismatch was found. Corrected to pair
on the **latest common date**, per D-009's rule in its third dimension
(date → window → span). The same fix was applied to the 4-quarter growth rates,
where `emp_raw[-5]` would have meant five *months* of payrolls against four
*quarters* of hours.

### Finding D-027 — a calibrated parameter makes a cross-check circular

The planned live cross-check was Cobb-Douglas vs CBO `GDPPOT`, reported as
Section 21.1's method-dispersion band. But `A` is the Solow residual and is not
published, so the script must calibrate it: `A = Y / (K^a * L^(1-a))` on actual
GDP. Once calibrated, the function reproduces actual GDP **by construction**, so
the "divergence" is just the output gap and carries **no** information about
whether the two methods agree.

Subtly worse than a wrong number: a plausible number attached to the wrong claim.
The script now says so explicitly. What the comparison still legitimately
establishes is (a) the input chain is self-consistent — a wrong `K` moves the
calibrated `A` and shifts the gap out of band — and (b) it **reproduces D-009's
recorded** `+0.83%` **same-quarter output gap through a completely different route**,
which is genuine corroboration since the two calculations share no inputs.

The generalisable rule, now recorded: **a cross-check must not share an input
with the thing it is checking.**

### Mutation testing — 20/20 killed, 0 survivors

Guards covered: exponent assignment (both directions), `alpha` from config rather
than a literal, `A` present in the product, both confidence penalties, the
A-first warning order, the estimate-not-measurement warning, the CRS disclosure,
the positive-factor constraint, the sum-not-difference in growth accounting, the
`None`-not-`0.0` rule, the strict-vs-non-strict dominance comparison, the
config-sourced threshold, all three warning-branch conditions, the
both-negative branch, the zero-total warning, and the reported contributions.

**Two survivors on the first sweep, diagnosed rather than accepted:**


| Survivor                           | Diagnosis                                                                                                                                                                           | Fix                                                                                                                                                      |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| M16 — both-negative branch removed | **Weak test.** The test asserted the two offsetting warnings were *absent* but never that the both-negative warning was *present* — a model emitting no warning at all also passed. | Added the presence assertion plus a second test on the warning's content.                                                                                |
| M18 — zero-total warning removed   | **Inert mutation.** The replacement targeted only the warning's first line; the tail survived and the substring match still succeeded.                                              | Mutation retargeted at the whole `warnings.append(...)` block, and the test strengthened to assert exactly one match and a phrase from the message body. |




### Warning-path coverage


| Warning                                             | Trigger                          | Test                                                                   |
| --------------------------------------------------- | -------------------------------- | ---------------------------------------------------------------------- |
| A is least predictable and most impactful           | unconditional                    | `test_productivity_is_named_as_the_least_predictable_term_first`       |
| Track CBO/Fed/IMF; dispersion IS the band           | unconditional                    | same (position 1)                                                      |
| Production-function estimate, not observed          | unconditional                    | `test_estimate_not_measurement_warning_is_always_present`              |
| `alpha` outside the interior `(0,1)`                | `alpha <= 0 or >= 1`             | covered by mutation M3 (config value change)                           |
| Both growth terms negative                          | `labor < 0 and productivity < 0` | `test_both_negative_warning_names_the_mechanical_gap_effect`           |
| Productive growth dominated by productivity         | `share > 0.6` (config)           | `test_dominance_warning_fires_above_the_config_threshold`              |
| Labor force shrinking, growth rests on productivity | `labor < 0 and productivity > 0` | `test_negative_labor_force_growth_is_flagged_and_names_the_dependency` |
| Productivity negative, headcount carrying it        | `productivity < 0 and labor > 0` | `test_negative_productivity_with_positive_labor_is_flagged`            |
| Share undefined (terms sum to zero)                 | `total == 0`                     | `test_share_is_none_rather_than_zero_when_terms_sum_to_zero`           |




### Cross-field identities

- `K` **and** `L` **are not interchangeable** — tested with `K != L`, because
transposition is unobservable when they are equal (which the golden case's
shape would otherwise conceal).
- **Output is linear in** `A` **but concave in** `K` — two separate tests pinning the
two different elasticities. Without the concavity test, an implementation that
replaced `K^alpha` with `K` would pass every other arithmetic assertion.
- `potential_growth == labor_contribution_pp + productivity_contribution_pp`
— recomputed from the reported components.
- **The reported** `productivity_share` **reconciles with the reported inputs** —
and its range is asserted only when both terms are positive.



### Real-data validation record (Section 21.0)

`scripts/live_labor_check.py::_check_production_function`, against the live local
OpenBB API:


| Input         | Series             | Real value                 | Note                             |
| ------------- | ------------------ | -------------------------- | -------------------------------- |
| `K`           | `RKNANPUSA666NRUG` | 80,822,920 mn (2023-01-01) | **annual**, 3.2 years behind GDP |
| `Y`           | `GDPC1`            | 24,269.613 bn (2026-04-01) | quarterly                        |
| hours         | `PRS85006023`      | 98.13 hrs/wk (2026-04-01)  | **quarterly**                    |
| employment    | `PAYEMS`           | 158,798k (2026-08-01)      | **monthly**                      |
| CBO potential | `GDPPOT`           | 24,070.939 bn (2026-04-01) | 42 forward points withheld       |


Checks performed, all passing:

1. `K` **lags** `Y` **by 1,186 days** — asserted `> 300`, so a change in the source's
  cadence fails loudly instead of silently pairing 2023 capital with 2026 output.
2. **Capital/output ratio = 3.33** — asserted inside the structural US band
  `(2, 5)`. This is the magnitude check that catches a millions-vs-billions
   error, which would otherwise produce a smooth, plausible number.
3. **CBO forward points withheld = 42** — asserted `> 0`, so the projection-block
  filter is confirmed to be working rather than passing on a series that no
   longer carries projections.
4. **Hours and employment paired on** `2026-04-01`, their latest *common* date,
  with the own-latest divergence printed.
5. **Cross-field identity** — `A*K^a*L^(1-a)` recomputed from reported
  components matches the module's output.
6. **Output gap = +0.83%** — asserted inside `(-10, +10)`, and cross-checked
  against D-009's independently recorded `+0.83%`.

Growth accounting on live 4-quarter changes:


| Term                        | Value                               |
| --------------------------- | ----------------------------------- |
| Real GDP growth             | +2.10%                              |
| Labor input growth          | +0.33%                              |
| Implied productivity growth | +1.77%                              |
| Productivity share          | **0.845** (dominance warning fires) |


The dominance warning firing on live data at `84.5%` is the model doing its job:
US potential growth is currently carried mostly by the term nobody can forecast.

### Known gaps carried forward

- **No independent second potential-output estimate** (D-027). The genuine
uncertainty band cannot be computed yet. Recorded in `OPEN_ISSUES.md` Part 3.
- `A` **is calibrated, never sourced.** The live check solves for it, which is
honest for a wiring check but is not a way to *forecast* potential GDP. A real
use needs an `A` path from a growth-accounting exercise, not a residual.
- `labor_input` **is hours, not quality-adjusted hours.** The specification names
the field `labor_input` precisely because the choice matters; the live check
uses employment × weekly hours × 52, which ignores composition and education.
- `K` **is 3.2 years stale by construction.** The perpetual-inventory capital
stock is annual and lagged. Any potential-GDP figure built from it inherits
that staleness, and no warning currently says so — the live script reports the
span but the model cannot, because it never sees dates.



## Phase 2 — Tier 2: `project_shelter_cpi` (Module 5.1)

`src/macro_engine/models/inflation_nowcast.py` (new, ~290 lines),
`tests/models/test_inflation_nowcast.py` (new, 26 tests),
`scripts/mutation_inflation_nowcast.py` (new, 19-mutation sweep).

### Function


| Function              | Module | `value` type   | Confidence                | Status      |
| --------------------- | ------ | -------------- | ------------------------- | ----------- |
| `project_shelter_cpi` | 5.1    | `float | None` | computed in both branches | IMPLEMENTED |


Tier 2 is now **16/29**.

### The defect this function is built around — D-028

The specification's sample indexes the market-rent vintage as
`market_rent_growth_yoy_pct[-lag_months]`. That is **not** "`lag_months`
ago":


|                      |                                                   |
| -------------------- | ------------------------------------------------- |
| `[-k]` selects       | the element `k - 1` positions before the end      |
| the end element is   | the *current* month                               |
| so `[-15]` reads     | **14 months ago**, not 15                         |
| and with 15 elements | index 0 — the same code reads a different vintage |


So the reported vintage depends on **how much history the caller passed**, which
is not a property of the lag. One month of drift inside a 15-month lag is
invisible to every range and shape check, and a regression test written with a
single list length passes while asserting nothing about the property an
off-by-one breaks.

The correction: derive the index from a named months-ago offset in one place
(`vintage_index_from_end = lag_months + 1`), require `lag_months + 1` points
(the current month is itself needed), and drop `lag_months` from the input
model so it cannot shadow config.

### Mutation testing — 19/19 killed, 0 survivors

**M1 reverts the index to the specification's own** `[-lag_months]` **and is
killed** — which is the point of the sweep. The correction is load-bearing, not
cosmetic.

The two guards that do that work:

- `test_vintage_is_stable_when_the_caller_passes_extra_history` — runs the same
economic data at four history lengths and asserts one distinct answer. This is
the property the specification's spelling destroys, and no single-length test
can observe it.
- `test_projection_reads_the_vintage_exactly_lag_months_ago` — uses a **marker
series** whose value at each index *equals its own months-ago number*, so
reading the wrong offset returns `lag - 1` rather than a plausible figure.
The fixture makes the defect name itself.



### Three further corrections to the specification's sample


| #   | Spec                         | Correction                            | Why                                                                                                                                     |
| --- | ---------------------------- | ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `lag_months: int = 15`       | read `inflation.shelter_lag_months`   | a signature default is a second source of truth and wins when the caller omits it                                                       |
| 2   | `len < lag_months` guard     | `len < lag_months + 1`                | a `lag`-element list's oldest point is only `lag - 1` months old, so the required vintage does not exist                                |
| 3   | `value=None, confidence=0.0` | `None` with computed floor confidence | §22.8 forbids a literal, and `0.0` is below the configured floor, which exists so a *returning* confidence differs from a *missing* one |


A fourth addition: the spec's binary `cooling`/`reaccelerating` test
classifies an **exact match** as "reaccelerating", asserting a direction change
where none exists. A config-supplied `shelter_converged_tolerance_pp` gives the
converged state a width, and the converged branch carries its own warning saying
the projection contains no forward information.

### New config (no literals in the model)

`shelter_converged_tolerance_pp` (0.1, `uncalibrated_illustrative`) with a
`.shelter_converged_tolerance` property, set at the reporting precision so a
rounding-level difference cannot manufacture a direction.

### Config-accessor trap — now guarded structurally

The same mistake — comparing a `CalibratedValue` envelope instead of its
accessor — was made for the **third** time on this function
(`shelter_converged_tolerance_pp`). It raises `TypeError` only when the branch
executes, so an untested branch survives until real data reaches it.

Rather than fix it by hand a third time, `tests/test_infrastructure.py` gained a
structural guard that walks the whole settings tree and asserts every
`CalibratedValue` leaf is readable as a plain number — by **either** a numeric
`.property` **or** `Settings.scalar("path")`, since both are legitimate and
`scalar()` unwraps the envelope itself.

The guard immediately found **19 existing leaves** readable only via `scalar()`,
which is why it accepts both routes rather than mandating properties. It also
does **not** prove a model *takes* the readable route — the mutation sweep's
"threshold from a literal instead of config" entry covers that half.

`test_calibrated_values_do_not_support_arithmetic_directly` documents *why* the
rule exists, so if `CalibratedValue` ever gains comparison operators the
relaxation is deliberate rather than accidental.

### Warning-path coverage


| Warning                                 | Trigger                 | Test                                                               |
| --------------------------------------- | ----------------------- | ------------------------------------------------------------------ |
| Lease-turnover dynamics assumed to hold | unconditional           | `test_lag_assumption_warning_is_always_present`                    |
| Shelter is ~⅓ of CPI                    | unconditional           | `test_shelter_share_warning_is_always_present`                     |
| Vintage is config-derived, not measured | unconditional           | `test_vintage_warning_names_the_config_driven_lag`                 |
| Extra history does not improve it       | `len > lag + 1`         | `test_extra_history_warning_fires_only_when_history_is_extra`      |
| Converged ⇒ no forward information      | `abs(gap) <= tolerance` | `test_converged_case_warns_that_it_carries_no_forward_information` |
| Insufficient data, no substitute used   | `len < lag + 1`         | `test_insufficient_history_returns_none_not_the_oldest_point`      |




### Real-data validation record (Section 21.0)

`scripts/live_labor_check.py::_check_shelter`, against the live local OpenBB API:


| Input                  | Series         | Real value                                      |
| ---------------------- | -------------- | ----------------------------------------------- |
| CPI shelter            | `CUSR0000SAH1` | 883 obs, latest `2026-08-01`, YoY **+3.03%**    |
| rent leg (substituted) | `CUSR0000SEHA` | 547 obs, latest `2026-08-01`                    |
| aligned YoY series     | —              | 535 common months, `1982-01-01` .. `2026-08-01` |


Checks performed, all passing:

1. **Independent vintage lookup.** `15 months before 2026-08-01` = `2025-04-01`,
  asserted against an index computed from the *definition* rather than copied
   from the model. A `[-lag]` off-by-one would land on `2025-05-01` and fail here.
2. **Day-span check, asymmetric.** The vintage spans **487 days**. The lower
  bound catches an off-by-one; the upper bound is loose because of D-025 (below).
3. **Direction and gap** recomputed independently: gap `+0.94pp` → `reaccelerating`,
  agreeing with the model.
4. `None`**-not-a-substitute** on a `lag`-length history, with
  `confidence = 0.45` — the computed floor, not the specification's `0.0`.

**D-025 recurs in a second series family.** Both `CUSR0000SAH1` and
`CUSR0000SEHA` carry a **61-day** gap. The cadence assertion, first written as
`max(gaps) <= 31`, **failed on real data** and was corrected to the D-025
treatment: assert the *latest* interval is a month, warn on historical gaps.

A consequence D-025 had not stated: **lag arithmetic counts OBSERVATIONS, not
calendar months.** Where a month is absent, indexing back 15 observations spans
488 days rather than ~456 — so the day-span assertion must be asymmetric. A
symmetric band would either fail on real data or fail to catch the off-by-one.

### Known gaps carried forward

- **The rent leg is substituted** (D-028). `ZORI` is EMPTY on this build and
Apartment List is not on FRED. The substitute is CPI rent of primary
residence, which already contains much of the lag the model exploits, so the
live magnitude is **understated**. The live check prints this caveat
unconditionally. Requires a non-FRED source; recorded in `OPEN_ISSUES.md`.
- `lag_months` **is a config constant, not a measured quantity.** Module 5.1
documents a 12–18 month range; 15 is its midpoint. The model warns that the
vintage moves if it is recalibrated, but cannot report the range.
- **Turnover speed is not observable here.** The lag is an average across a stock
of staggered leases, so a change in turnover rate shifts the *effective* lag
without changing the config value. No warning can quantify this.

---



## Phase 2 — Tier 2: `ppi_pipeline_signal` (Module 5.4)

**Status: IMPLEMENTED and real-data validated.**
Tier 2 progress: **17 of 29**. Source: `src/macro_engine/models/ppi_pipeline.py`.

### Function

```python
class PPIPipelineInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    crude_stage_yoy_pct: float
    intermediate_stage_yoy_pct: float
    final_demand_yoy_pct: float
    corporate_margin_trend: MarginTrend    # Literal["expanding","stable","compressing"]
    demand_condition: DemandCondition      # Literal["strong","neutral","weak"]

def ppi_pipeline_signal(inputs: PPIPipelineInputs) -> ModelResult: ...
```

`value` is a dict:


| key                           | type    | meaning                                            |
| ----------------------------- | ------- | -------------------------------------------------- |
| `upstream_pressure_building`  | `bool`  | the specification's strict ordering test, verbatim |
| `gradient_direction`          | `str`   | four-state restatement with a dead band            |
| `expected_pass_through`       | `str`   | `"muted" | "fuller"`                               |
| `base_rate_strict_descending` | `float` | measured 30.0% — see D-029                         |
| `base_rate_crude_above_final` | `float` | measured 44.2%                                     |
| `stage_spread_pp`             | `float` | `crude - final`                                    |


`confidence` = **0.30**, from `compute_confidence()` with
`is_heuristic_not_calibrated=True` (two of five inputs are judgements) and
`depends_on_unobservable=True` (Section 21.4 item 10).

### The finding this function is built around — D-029

The specification presents `crude > intermediate > final demand` as a signal.
Measured on this build's own three live series over the **190 months with a
common usable year-over-year reading** (2010-11 .. 2026-08):


| ordering                              | months | share     |
| ------------------------------------- | ------ | --------- |
| strict `crude > intermediate > final` | 57     | **30.0%** |
| loose `crude > final`                 | 84     | **44.2%** |


The specification's own test **fires less often than a coin flip.** The flag is
kept — it is what the spec specifies and it is not false — but it is now
reported with its **own measured base rate**, in `value` and in an unconditional
warning. A boolean delivered without its frequency invites the reader to treat
the rarer of two near-equal outcomes as an unusual state.

The `30.0% / 44.2%` figures carry `calibration_status: fitted_assumption`, not
`institutional_fact`: they are properties of *these three series over this
window*, not constants of the economy.

### Stage-to-series mapping, and the discontinued series


| stage        | symbol    | title                                         | window         |
| ------------ | --------- | --------------------------------------------- | -------------- |
| crude        | `WPSID62` | PPI unprocessed goods for intermediate demand | 1947-04 ..     |
| intermediate | `WPSID61` | PPI processed goods for intermediate demand   | 1947-04 ..     |
| final demand | `PPIFIS`  | PPI final demand                              | **2009-11 ..** |


`PPIFIS` bounds the common window to **202 observations**, not 953 — verified
live and asserted in the check.

`PPICRM` **is unusable and the live check proves it.** The obvious-looking
"crude materials for further processing" index was **discontinued by BLS**; its
last observation is **2015-12-01**, confirmed on live data. Using it would have
silently truncated every crude-stage reading by a decade. The check asserts
`last < 2020` and prints the date, so a future revival of the series would be
noticed rather than assumed away.

**Base years differ and that is fine, for a stated reason.** `WPSID`* are
1982=100 and `PPIFIS` is Nov 2009=100. Every input is a year-over-year percent
change *of a series against itself*, where the base cancels. It would matter
immediately if the levels were compared across stages — which is why the levels
are never combined. Documented in the module docstring and the registry.

### Corrections to the specification's sample

1. **Two free** `str` **fields →** `Literal` (D-029). A typo'd `"compress"` or
  `"Compressing"` silently fell through to `else` and reported `fuller`
   pass-through — the optimistic answer, manufactured by a spelling mistake,
   with nothing in the output to indicate it. This is the `extra="forbid"`
   defect class in a form `extra="forbid"` cannot reach.
2. `confidence=0.4` **→** `compute_confidence()` (Section 22.8).
3. `corporate_margin_trend` **disclosed as a human assessment.** Section 21.4
  item 10 lists it in the Loophole Ledger: no free margin series exists. One of
   five inputs — and one of the two that decides pass-through — carries
   judgement reliability rather than series reliability. Unconditional warning.
4. **A dead band on the reported direction.** Strict `>` makes a three-way tie
  "no clear gradient" and a 0.01pp difference "pressure building". A configured
   tolerance adds `no_clear_gradient` without altering the spec's boolean.
5. **A fourth state,** `non_monotonic`**.** The most common real outcome satisfies
  neither the ascending nor the descending test. The spec's boolean reports it
   as `False`, which reads as "no upstream gradient" — a different claim from
   "the stages disagree in direction".



### Mutation testing — 32/32 killed

`scripts/mutation_ppi_pipeline.py`. The three mutations that centre the sweep:

- **M1a/M1b** revert the two fields to the spec's free `str`. Both killed —
proving the `Literal` correction is load-bearing rather than cosmetic.
- **M2a** drops the base-rate keys from `value`; **M2d** removes the base-rate
warning. Both killed — the D-029 disclosure cannot be removed silently.
- **M3a** makes pass-through read the gradient, destroying margin absorption.
Killed — the mechanism the module exists to model is guarded.

Two first-sweep survivors were **weak tests** and became tests:

- **M4e** (dead band on one adjacent pair) — no test put both gaps on opposite
sides of the band while keeping the ordering monotonic. Now covered from both
directions by `test_the_dead_band_requires_both_adjacent_gaps_inside_it` and
`test_the_dead_band_requires_the_first_adjacent_gap_inside_it`.
- **M5b** (contradiction warning ignoring the margin trend) — the existing
negative test used an *inverted* gradient, where `upstream_pressure_building`
is already `False`, so it could not distinguish "building AND expanding" from
"building" alone. Now parametrized over `stable`/`compressing` with the
gradient held building.

A third candidate — mutating the `Field(description=...)` text — was diagnosed
as an **inert mutation** and removed: pydantic builds the `literal_error`
message from the `Literal` annotation, not the description, so the error text is
byte-identical either way. Inert mutations are not test gaps and counting them
would misreport the kill rate.

### Boundary-testing lesson (new)

The dead-band edge fixture was first written as `2.0 - tolerance` and **failed
against a correct model**. In IEEE-754, `2.0 - 0.1 == 1.9` but
`2.0 - 1.9 == 0.10000000000000009` — which *exceeds* the tolerance and
legitimately trips the strict comparison. A fixture that builds its own edge by
subtraction tests a point outside the band while claiming to test its edge.
Corrected to add from zero; the hazard is now documented executably by
`test_float_subtraction_cannot_build_a_boundary_fixture`.

Second lesson, from the mirror case: putting the two adjacent gaps on opposite
sides of the band **while keeping the ordering monotonic** is more constrained
than it looks. `crude=3t, intermediate=0, final=0.5t` satisfies "first gap
outside, second inside" but makes `intermediate < final`, so it tests the
`non_monotonic` branch instead. The corrected fixture is `4.0t > 1.0t > 0.4t`.

### Warning-path coverage


| warning                                   | condition                  | tested     |
| ----------------------------------------- | -------------------------- | ---------- |
| PPI not a 1:1 CPI predictor               | always                     | yes        |
| base rate + its measured frequency        | always                     | yes        |
| margin trend is a human assessment        | always                     | yes        |
| stage-to-series mapping is a build choice | always                     | yes        |
| building gradient vs expanding margins    | `building and expanding`   | both sides |
| gradient inverted                         | `crude < inter < final`    | both sides |
| non-monotonic ordering                    | neither strict order       | both sides |
| flat ends                                 | `abs(spread) <= tolerance` | both sides |




### New config (no literals in the model)


| key                                               | value | status                      |
| ------------------------------------------------- | ----- | --------------------------- |
| `inflation.pipeline_base_rate.strict_descending`  | 0.3   | `fitted_assumption`         |
| `inflation.pipeline_base_rate.crude_above_final`  | 0.442 | `fitted_assumption`         |
| `inflation.pipeline_base_rate.stale_after_months` | 3     | `uncalibrated_illustrative` |
| `inflation.pipeline_gradient_tolerance_pp`        | 0.1   | `uncalibrated_illustrative` |


`stale_after_months` is defined but not yet consumed by this function — it is
for the thesis layer's freshness gate. Recorded here so the unused key is
visible rather than assumed wired.

### Real-data validation record (Section 21.0)

Live at `2026-08-01`, from `uv run python scripts/live_labor_check.py`:

```
crude         WPSID62  n=  953 1947-04-01 .. 2026-08-01
intermediate  WPSID61  n=  953 1947-04-01 .. 2026-08-01
final_demand  PPIFIS   n=  202 2009-11-01 .. 2026-08-01
common observations = 202 (2009-11-01 .. 2026-08-01) — bounded by PPIFIS

crude         own-latest=2026-08-01 YoY@own=+13.06%  YoY@common=+13.06%
intermediate  own-latest=2026-08-01 YoY@own=+11.53%  YoY@common=+11.53%
final_demand  own-latest=2026-08-01 YoY@own= +5.41%  YoY@common= +5.41%

crude +13.06% > intermediate +11.53% > final +5.41%
  -> upstream_pressure_building=True
gradient_direction=building_upstream  pass_through=fuller  spread=+7.65pp
confidence = 0.3 (computed, not the spec's 0.4)

base-rate recomputation over 190 usable months:
  strict crude > inter > final : 57/190 = 30.0%   -> matches config
  loose  crude > final         : 84/190 = 44.2%   -> matches config
  CONFIRMED: neither ordering clears a coin flip (D-029)

PPICRM (crude materials, DISCONTINUED) last observation = 2015-12-01
```

Checks performed, all passing:

1. **The stage mapping fetches live** for all three series, and the common window
  is computed rather than presumed — bounded by `PPIFIS`, which starts 2009-11.
2. **Pairing discipline.** Own-latest and common-date readings are compared for
  every stage; they happen to agree here (all three end 2026-08-01) but the
   comparison is asserted, so a cadence change surfaces as a warning instead of a
   silent mis-pairing.
3. **Cross-field identity.** `upstream_pressure_building` is recomputed from the
  reported readings, and `stage_spread_pp` is re-derived as `crude - final`.
4. **The base rate is independently reproduced** over all 190 usable months and
  matched against config to within 1pp. The check also asserts the strict rate
   does **not** exceed 50% — if the relationship ever inverts, D-029's premise
   fails loudly rather than quietly going stale.
5. **The discontinued series is proven dead**, not assumed: `PPICRM` last
  observation `2015-12-01`, asserted `< 2020`.



### Known gaps carried forward

- **The base rate is measured, not calibrated.** 30.0% is a property of these
three series over 2010-11 .. 2026-08. A different crude-stage proxy (should
`PPICRM` ever be revived, or a better series appear) would move it, and the
figure would need re-measuring.
- `corporate_margin_trend` **has no series behind it** (Section 21.4 item 10).
Two of the five inputs, and one of the two that decides pass-through, are
human assessments. This is a permanent Loophole-Ledger item on this build, not
a Phase 2 stopgap.
- **The reported direction depends on a tolerance that is not calibrated.**
`pipeline_gradient_tolerance_pp = 0.1` is set at the reporting precision
rather than derived. A calibration would need a view on how much stage
separation is economically meaningful.
- **Pass-through is a label, not a magnitude.** `"muted"`/`"fuller"` says which
way margin absorption points; it does not estimate how much pressure arrives.
A magnitude would need a fitted pass-through coefficient, which does not exist
here.

---



## Phase 2 — Tier 2: `gdp_gdi_divergence` (Module 7.1)



### Function


| Field          | Value                                                        |
| -------------- | ------------------------------------------------------------ |
| Spec location  | `AGENTS.md:4714` (Section 20.7)                              |
| Implemented in | `src/macro_engine/models/gdp_nowcast.py`                     |
| Tier           | 2 (§21.3)                                                    |
| Signature      | `gdp_gdi_divergence(inputs: GdpGdiInputs) -> ModelResult`    |
| Inputs         | two year-over-year growth rates in percent                   |
| Confidence     | `compute_confidence(...)` → **0.30**, constant in the inputs |
| Tests          | 35 (`tests/models/test_gdp_gdi_divergence.py`)               |
| Mutation sweep | **30 mutations, 30 killed**                                  |
| Live check     | `_check_gdp_gdi` in `scripts/live_labor_check.py`            |


`value` keys: `gdp_growth_pct`, `gdi_growth_pct`, `divergence_pp`,
`average_growth_pct`, `significant`, `divergence_base_rate`,
`level_wedge_mean_pct`.

**Progress: Tier 2 17 → 18/29.**

### The finding this function is built around — D-031

Section 20.7 supplies four substantive claims. Three do not survive live data.


| Spec claim                                                             | Measured reality                                                               | Verdict                                                           |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------ | ----------------------------------------------------------------- |
| `abs(diff) > 1.0` marks significance                                   | fires **68/314 = 21.7%** of quarters                                           | rate is usable; threshold retained as `uncalibrated_illustrative` |
| divergence means "one dataset is capturing something the other misses" | GDP leads **47.8%**, GDI leads **52.2%**, mean **−0.009pp**                    | **sign carries no information**                                   |
| "the average is often the better read"                                 | true for growth; level wedge is **−0.459%** and negative in **7 of 9 decades** | **only true for growth**                                          |
| `confidence=0.4 if significant else 0.7`                               | violates §22.8                                                                 | replaced by `compute_confidence()`                                |


The permanent warning is now unconditional (four standing warnings), so the
output is never warning-free — the residual facts apply whatever the inputs.

### `gdi_growth_pct` verified before building (§21.1 marks it "VERIFY series")


| Symbol            | Probe result                                    | Verdict              |
| ----------------- | ----------------------------------------------- | -------------------- |
| `GDI`             | 318 quarters, 1947-01..2026-04, fully populated | **live, registered** |
| `GDINC1`          | empty frame                                     | dead                 |
| `A261RC1Q027SBEA` | empty frame                                     | dead                 |


`GDI` is **nominal**, deliberately paired with `GDP` (also nominal). The
registry entry states this, because pairing a nominal with a real series would
turn the discrepancy into a deflator wedge.

### Registry change — the three-part rule (D-030) applied again

Adding `gdi` required all three parts, and the parity test
(`test_snapshot_field_alias_is_resolvable`) is what proves part three was done:

1. `config/series_registry.yaml` — the `gdi` entry
2. `src/macro_engine/data_layer/schemas.py` — `MacroDataSnapshot.gdi`
3. `src/macro_engine/data_layer/persistence.py` — `"gdi"` in `SCALAR_SERIES_FIELDS`

The registry uses `decision_note`, not `note` — `note` is not a
`RegistrySeries` field and taking it down the wrong path fails eight data-layer
tests at once (D-030). Descriptions use commas, never colons (D-030).

### Mutation testing — 30/30 killed, and three defect classes diagnosed

The first sweep returned **19/30**. The eleven misses were not eleven test gaps
but three distinct defect classes, each diagnosed before fixing:


| Class           | Count | Mutations                | Cause                                                                                                                 |
| --------------- | ----- | ------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| Broken mutation | 3     | `M1a`, `M1b`, `M1e`      | `ruff format` had removed a trailing comma, so the fragment did not apply                                             |
| Inert mutation  | 6     | `M3a`–`M3c`, `M5c`–`M5d` | replaced only the **first line** of a multi-line f-string; asserted tokens survived in later lines                    |
| **Weak test**   | 3     | `M1d`, `M2a`, `M6e`      | test derived its expectation from the same config the code reads → a literal equal to the shipped value was invisible |


`M1d` had an additional cause: `depends_on_unobservable=True` occurs **three
times** in `gdp_nowcast.py`, and the mutation hit the first (in `output_gap`),
never reaching the code under test. Both `M1c`/`M1d` are now anchored to the
full `ConfidenceInputs(...)` call.

> **Rule.** When a mutation survives, establish *which* of three things
> happened — weak test, inert mutation, or broken mutation. Only the first is a
> test gap, and only the first should change the suite.



### The new symmetry-breaking test pattern

All three weak tests had one shape: the assertion and the implementation read
the same config, so they moved together. The fix is to **break the symmetry** —
patch the config object in-process to a value the shipped literal cannot
produce, and assert the output follows it:

```python
settings.gdp_gdi = original.model_copy(
    update={"significance_threshold_pp": original.significance_threshold_pp.model_copy(
        update={"value": 0.25})}
)
try:
    result = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=3.0, gdi_growth_pct=2.6))
    assert as_bool(result, key="significant") is True
finally:
    settings.gdp_gdi = original
```

Applied to the threshold, the revision window, and the confidence penalties.
This is a reusable pattern: **any config-derived value needs at least one test
that would fail if the code stopped reading the config.**

### An eighth pairing axis: unit

The pairing rule now covers common *date* (D-009), *window* (D-022), *span*
(D-025), *parameter* (D-027), *cadence* (D-029), *base rate* (D-029),
*enumerated field* (D-029), and **unit**. Two inputs that
must be differenced have to share a basis — nominal-vs-nominal or
real-vs-real — and that cannot be detected from two bare floats. The contract
lives in the input model's docstring and field descriptions, pinned by
`test_the_input_model_documents_the_unit_contract`.

### Warning-path coverage


| Path              | Warning                                                       |
| ----------------- | ------------------------------------------------------------- |
| always            | divergence is a residual + its 21.7% base rate                |
| always            | sign is a coin flip + both 47.8%/52.2% frequencies            |
| always            | `average_growth_pct` is a growth mean; level wedge is −0.459% |
| always            | revision-vintage asymmetry; stale after 2 quarters            |
| `significant`     | warrants investigation, not averaging-away                    |
| not `significant` | "not flagged" means typical, not "no discrepancy"             |




### New config (no literals in the model)

`config/settings.yaml` → `gdp_gdi:` (5 leaves, each with `calibration_status`
and a `note` explaining how it was obtained):


| Leaf                                            | Value  | Status                      |
| ----------------------------------------------- | ------ | --------------------------- |
| `significance_threshold_pp`                     | 1.0    | `uncalibrated_illustrative` |
| `level_wedge_mean_pct`                          | −0.459 | `fitted_assumption`         |
| `divergence_base_rate.significant_at_threshold` | 0.217  | `fitted_assumption`         |
| `divergence_base_rate.gdp_above_gdi`            | 0.478  | `fitted_assumption`         |
| `divergence_base_rate.stale_after_quarters`     | 2      | `uncalibrated_illustrative` |


> **Coupled pair.** `significant_at_threshold` is specific to
> `significance_threshold_pp`. If the threshold is re-calibrated in Phase 5+
> the rate MUST be recomputed in the same commit — they are one measurement,
> not two settings. Noted in both YAML comments and here.



### Real-data validation record (Section 21.0)

```
GDP: 318 quarters, 1947-01-01 .. 2026-04-01
GDI: 318 quarters, 1947-01-01 .. 2026-04-01
common quarters = 318
confirmed DEAD routes (must never be substituted): GDINC1, A261RC1Q027SBEA

level wedge (GDI-GDP)/GDP: mean = -0.459%     config says -0.459%
CONFIRMED: the LEVEL wedge is negative, so averaging levels is biased

growth pairs (same quarter prior year) = 314
growth divergence: mean = -0.0085pp (expected ~0)
GDP-led share     = 47.8%  (150/314)
|div| > 1.00pp     = 21.7%  (68/314)
base-rate significant matches config (21.7%)
base-rate gdp_led matches config (47.8%)
CONFIRMED: the GROWTH divergence is mean-zero and its sign is a coin flip

latest pair: 2026-04-01
  GDP +6.562%  GDI +6.614%  divergence -0.052pp  average growth +6.588%
  significant = False   confidence = 0.3
cross-field identities hold (diff = GDP - GDI; avg = mean of the two)
sign-neutrality warning present
```

The check **independently recomputes** all three published base rates from the
raw series and fails on >1pp of drift, so the config numbers are reproducible
rather than trusted. Cross-field identities are recomputed from the *reported*
components — the D-009 lesson, which catches window and sign defects that leave
every individual number plausible.

### Known gaps carried forward

- `significance_threshold_pp` is illustrative. The base rate and the threshold
are one measurement and must be recalibrated together.
- The model takes two floats and cannot detect a nominal/real mismatch; the
contract is documented and tested but not enforceable at runtime.
- No revision-vintage storage, so `stale_after_quarters` is a warning rather
than an age check against real vintages (§21.4 item 14).
- `simple_gdp_nowcast` remains the only `NotImplementedError` stub in the
models layer (`gdp_nowcast.py`).


---

## Phase 2 — Tier 2: `leading_indicator_proxy` (Module 7.3)

*Spec name `lei_composite`. Renamed per Section 21.1 — an in-house composite
over free components **must not** be called "LEI". See D-032.*

### Function

| Field          | Value                                                         |
| -------------- | ------------------------------------------------------------- |
| Spec location  | `AGENTS.md` (Section 20.7)                                    |
| Implemented in | `src/macro_engine/models/lei_proxy.py`                         |
| Tier           | 2 (§21.3)                                                     |
| Signature      | `leading_indicator_proxy(inputs: LeadingIndicatorProxyInputs) -> ModelResult` |
| Inputs         | `components: dict[str, float]` (six-month annualized % change), `weights: dict[str, float] \| None` |
| Confidence     | `compute_confidence(...)` → **0.30**, constant in the inputs   |
| Tests          | 55 (`tests/models/test_lei_proxy.py`) + 8 data-layer            |
| Mutation sweep | **36 mutations spanning 4 files, 36 killed** (2 survivors closed) |
| Live check     | `_check_leading_indicator` in `scripts/live_labor_check.py`    |

`value` keys: `composite_6mo_annualized`, `breadth_declining`, `n_declining`,
`n_components`, `broad_based`, `lead_direction`, `breadth_threshold`,
`breadth_null_rate`, `equal_weighted`.

`lead_direction` is a three-state `Literal`: `"broad_based_decline"`,
`"mixed"`, `"broad_based_advance"`.

**Progress: Tier 2 18 → 19/29.**

### The fork the specification left open — D-032

Section 21.1 gives Module 7.3 a genuine either/or: **manual entry of the
published composite, or an in-house composite from free components — and if
in-house, it must not be called "LEI".** The choice was resolved with live
evidence rather than assumption.

| Route | Evidence | Verdict |
|---|---|---|
| Conference Board LEI via FRED `USLEI` | **empty frame**, three attempts through the local API *and* three in-process | **BLOCKED** |
| Manual entry of the published figure | no refresh, no vintage, no observation date | **refused** on §21.0 grounds |
| In-house composite over free components | all four named components resolve live | **chosen** |

Component scope, all live-probed before any code was written:

| Component | Symbol | Observations |
|---|---|---|
| Initial claims (inverted) | `ICSA` | 3,114 |
| Building permits | `PERMIT` | 799 |
| 10y–3m curve slope | `T10Y3M` | 11,179 |
| S&P 500 | `SP500` | 2,512 |

### The judgement correction the specification does not make

The specification presents `composite` as *the* leading figure. Two live facts
undercut that, and both are disclosed in `value` rather than in prose:

1. **The sum is mixed-unit.** The four components arrive in persons,
   thousands of units, percentage points, and index points. Their weighted sum
   is additively meaningless, and in practice it is *dominated* by whichever
   member is most volatile. `composite_6mo_annualized` is published because the
   specification asks for it, and labelled as mixed-unit rather than as a
   percentage.
2. **Breadth is the quantity that survives.** Breadth is unit-free — the
   fraction of components moving in the leading direction — so it is the
   signal, and `broad_based` is computed from it, not from the composite.

### Two defects found by the live check — invisible to 55 unit tests

**1. The reported span was the latest date, not the prior date.** The change
helper returned `latest_date` where the caller printed it as the prior
observation, so every component appeared paired with *itself*. Live output
before the fix:

```
initial_claims_inverted  ICSA  n=3114  change=-3.286   prior=2026-09-16
```

The **arithmetic was correct**; the *diagnostic* was wrong, which is worse — a
reader checking the pairing had no way to tell the code was right. Fixed by
returning both dates. After:

```
initial_claims_inverted  ICSA  n= 3114 pair 2026-03-07 -> 2026-09-05 (213000 -> 206000) change=-3.29%
building_permits         PERMIT n=  799 pair 2025-12-01 -> 2026-07-01 (1482 -> 1433)     change=-3.31%
curve_slope_10y3m        T10Y3M n=11179 pair 2026-03-18 -> 2026-09-16 (0.530 -> 0.870)   change=+64.15%
sp500_index              SP500  n= 2512 pair 2026-03-17 -> 2026-09-15 (6716.09 -> 7585.73) change=+12.95%
```

Each component is a **different frequency** — weekly, monthly, daily, daily —
so the four pairs are four different date ranges by necessity. Pairing on
"182 days back" rather than on `values[-2]` is what makes each span real.

**2. Two branches returned different units.** `T10Y3M` has **1,252
non-positive observations** (minimum −1.89), so the spread branch is a live
path, not a defensive one. The level branch computed a ratio ×100 (percent);
the spread branch computed a raw difference **without** ×100 — same field, two
units, and the curve component would have entered the composite 100× too small.
Fixed with `(latest - prior) * 100`, so both branches produce percent.

Both defects are §21.0 in its purest form: the unit tests proved the arithmetic
and could not see either one, because neither is an arithmetic error.

### The orientation trap

The single most likely way to build this composite wrong: **`ICSA` is a
claims LEVEL, and a rising level means a weakening labour market.** Entered
directly it inverts the entire reading. Orientation is therefore stated per
component in `config/settings.yaml`, documented in the input model's docstring,
and **asserted live** — the check verifies that the raw `ICSA` change of
−3.286 entered as +3.286:

```
orientation CONFIRMED: ICSA raw -3.286 entered as +3.286 (inverted)
```

`T10Y3M`, `PERMIT` and `SP500` enter direct.

### D-029 applied — the breadth flag travels with its base rate

`breadth_declining >= 0.6` is a comparison over four noisy signs. With four
components the threshold requires 3 of 4, which under a sign-symmetric
no-signal null happens **31.25%** of the time — a coin flip presented as a
signal, exactly the D-029 pattern. `breadth_null_rate` is therefore computed
**exactly** (binomial tail, Pascal's triangle) and published in `value` *and* a
warning.

It is explicitly **combinatorial, not historical**: the output says so in those
words. Inventing a track record the series does not support would be its own
fabrication.

### The self-caught logic defect

First implementation labelled the "one big fall" fixture
(`claims -20.0, permits +1.0, curve +0.5, equity +2.0`) as `broad_based_advance`
while the composite printed **−4.12** — 3 of 4 components rose, so a
breadth-only advance test fired against a negative headline. Fixed by requiring
`composite > 0` for the advance label, documented with the worked example, and
pinned by `test_a_broad_advance_requires_the_composite_to_agree`.

### Live reading at implementation

```
composite_6mo_annualized = +19.270      breadth_declining = 0.25  (1/4)
broad_based              = False        lead_direction    = broad_based_advance
breadth_null_rate        = 31.2%        confidence        = 0.3
cross-field identity holds (composite = equal-weighted mean of components)
breadth RECOMPUTED from live signs: 1/4 declining
naming rule CONFIRMED: the output is a proxy, not the licensed LEI
```

### Known gaps carried forward

- **O-10** — Conference Board LEI is licensed and unreachable; `USLEI` returns
  empty. A licensed feed would supply a genuine source-independent second
  estimate and the two could be cross-checked.
- **O-11** — FRED `SP500` is a **rolling ~10-year window** (2,512 obs from
  2016-09-16) whose start date advances. Sufficient for the six-month change;
  insufficient for any long base rate, and the truncation is **silent**.
- The composite is a mixed-unit sum; `breadth` is the interpretable quantity.
- `compute_confidence` returns 0.30 — the `is_heuristic_not_calibrated` and
  `depends_on_unobservable` penalties both apply, and the aggregate is
  genuinely separate from the specification's `0.5 / 0.3` branch, though on
  this config it coincidentally equals the `else` value. The test asserts the
  **discriminating property** (confidence must not vary with the breadth flag)
  rather than the literal (D-031).

---

## Phase 2 — Tier 2: simple_gdp_nowcast (Module 7.5)

**Done.** Section 6.5's specification, implemented under four corrections — the
fourth of which is that the specification's own formula is **anti-correlated
with the quantity it names**. See D-034.

### The record

| Obligation | Evidence |
|---|---|
| Implemented as specified, or the deviation recorded | Four defects corrected, two more disclosed; D-034. Name and input surface retained per §22.1/§22.13 |
| Unit test with hand-verified values | `tests/models/test_gdp_nowcast.py`, 27 tests; the annualization arithmetic (mean × months) is hand-computed inline |
| Executed against real data | `_check_gdp_nowcast` in `scripts/live_labor_check.py` — passes end to end |
| Output economically plausible, and written down | The sign is verified against the **raw level**; see below |
| Every `warnings` condition triggered in a test | 7 warning paths, each with a presence assertion |
| `ruff` and `mypy` clean | Repo-wide: `ruff check` clean, `ruff format` unchanged, `mypy --strict` clean over 70 files |
| Documented with its real-data validation record | This section; D-034; `settings.yaml` accuracy block |

### What the model does

```
for each complete quarter:
    consumption  = mean(monthly MoM %) * 3
    investment   = mean(monthly MoM %) * 3
    net_exports  = mean(monthly MoM %) * 3
delta   =  consumption * 0.679
         + investment  * 0.182
         + net_exports * -0.031     <- NEGATIVE, the correction
nowcast =  prior_quarter_annualized + delta
```

The input model takes each series' monthly changes as a **list per quarter**, so
the model averages the quarter itself and cannot be handed a window that
disagrees with its own (D-022's rule). A quarter is usable only when **all
three** inputs have a complete month set; an incomplete one is dropped and
disclosed, never annualized short (§21.0 rule 4).

### The four corrections

1. **The trade term's sign.** For an all-negative series `v = -|v|`, the
   percent change is `|v[t]|/|v[t-1]| - 1` — the minus signs cancel — so `pct`
   measures the **absolute value's** move. `pct > 0` therefore means the deficit
   **widened**, which is contractionary, so the weight must be **negative**. The
   specification's `+0.1` inverted the term on **414/414** months.
2. **The cadence.** Monthly changes are annualized and averaged to a quarterly
   rate so both sides of the addition are commensurable.
3. **The basis.** Nominal components into a real base is disclosed in the input
   contract and warned about (D-031), since a `float` cannot carry a basis.
4. **The weights.** BEA expenditure shares (67.9 / 18.2 / −3.1), with the
   specification's 0.6/0.3/0.1 recorded in the config note as the rejected
   alternative.

### The measured accuracy, and why it is in the output

> **CORRECTED 2026-09-17 — see D-035.** The table originally recorded here was
> measured on a **cumulative** estimand (each reconstruction credited with its
> whole available window of monthly changes) rather than the **one-quarter-ahead**
> horizon the function claims. The live check's recomputation caught the
> discrepancy and the tolerance was tightened rather than widened. The figures
> below are the corrected ones; the superseded values are in D-035.

On **137** quarters of live data where all three inputs have a complete month
set and both realised prints exist, each reconstruction given **one** quarter,
against FRED `A191RL1Q225SBEA` (the series the model's own
`prior_quarter_annualized` field declares):

| form | corr | mean \|err\| | sign agreement |
|---|---|---|---|
| specification as written | −0.169 | 3.558pp | 83.2% |
| prior quarter's print **alone** | −0.168 | **2.915pp** | 85.4% |
| this corrected form | −0.092 | 3.026pp | 89.1% |

The corrected form is **0.11pp WORSE than repeating the prior quarter's print**,
and the gap to the 0.5pp improvement bar is not close. The correction did fix
the adjustment's *sign* (`corr(delta, actual − base)` = **+0.1727** against the
specification's **−0.0565**), and it does beat the specification's own error
(3.026pp vs 3.558pp) with the highest sign agreement of the three — but the
adjustment's *magnitude* is wrong in the opposite direction from too small.

The adjustment is measured and published as `delta_overweighting_ratio`:

```
mean |delta|                      = 1.4727pp
mean |change delta predicts|      = 2.9153pp
ratio                             = 0.5052
corr(delta, realised change)      = +0.1727
R^2                               = 0.0298
```

**The delta is over-weighted, not inert.** It runs at half the magnitude of the
change it predicts while explaining **3%** of that change's variance, so
applying it at unit weight adds more noise than information — which is exactly
the 0.11pp cost above. A scale sweep on the shipped delta:

| scale | mean \|err\| |
|---|---|
| 0.00 (pure persistence) | 2.9153 |
| 0.25 | 2.8769 |
| 0.50 (best, fitted) | **2.8758** |
| 1.00 (shipped) | 3.0261 |
| 2.00 | 3.8785 |

The best scale is ≈0.498 and recovers **0.0395pp** — inside the noise on 137
points and fitted on the same sample that measures it (D-027's circularity).

A constant-outcome note: realised growth was positive in **89.8%** of those
quarters, so any form's sign agreement below that is *worse than always
predicting "positive"* — the D-029 base-rate disclosure, applied to this
model's own record. (The corrected form's 89.1% is just under it; the
specification's 83.2% is well under.)

**The weights are therefore not fitted.** The error is published in `value`
alongside a `beats_persistence` flag that is **computed** from the record rather
than asserted, so it cannot go stale (D-029's discipline applied to the model's
own track record). The live check **recomputes** both the error and the flag and
fails if either has drifted.

### The sign check that matters

The sign is verified against the **raw level** of `BOPGSTB`, whose direction is
known before the model runs — a cross-series identity, not a restatement of the
code. That is the D-009 discipline, and it is the assertion that caught a
mistake *in this increment's own reasoning*: the first version of the check
compared the percent change's sign against the **inverse** of itself, which
would have let a wrong sign pass.

```
BOPGSTB levels over 2026-Q2: -52,883 -> -75,752 -> -71,182
level change over the quarter = -18,299  -> deficit WIDENED (contractionary)
net_exports_contribution      = -1.1088  -> negative, as required
```

### The cross-check Section 6.5 asked for

The specification's docstring states the published Atlanta Fed GDPNow has "no
free API" and prescribes manual entry. **False on this build**: FRED `GDPNOW`
returns 61 live observations, 2011-07..2026-07, one per quarter, zero
consecutive repeats. It is a **final per-quarter record**, not a real-time
nowcast — its own mean absolute error against the realised print is **1.364pp**
— so `gdpnow_cross_check_pp` ships with that caveat attached, and the manual
route is unnecessary. `NOWCAST`, `GDPNOWC1` and `ATLGDPNOW` return empty frames
and were rejected by probe.

### Defects found

- **A property shadowing its own config field** — `realised_positive_share` was
  both a field and a property, so the accessor returned the whole
  `CalibratedValue` envelope. Pydantic does not reject the collision; caught by
  reading the value. Fourth occurrence of this trap class. Field renamed.
- **Three registry `verified_value`s written from recollection were wrong** —
  `RSAFS`, `DGORDER`, `BOPGSTB`. Caught by fetching live values. A wrong
  `verified_value` still validates, so the failure is silent.

### Gates at close

```
ruff check        All checks passed
ruff format       73 files already formatted
mypy --strict     no issues in 73 source files
pytest -q         615 passed, 1 skipped, 0 failed
mutation sweep    39 / 39 killed
live check        passes end to end
Tier 2            22 / 29
```

> The D-034 close recorded `mypy` over 70 files and 607 tests. The 70 → 65 move
> was a **scope change**, not a regression: `pyproject.toml`'s `files` list
> omitted `scripts`, so a bare `uv run mypy --strict` checked less than the
> documented gate `mypy --strict src tests scripts`. D-035 added `scripts` to
> the list, which is why the count is now **73** and why
> `scripts/live_labor_check.py` is type-checked at all.
>
> The D-035 close also caught a **mutation left applied in the source** by a
> power loss mid-sweep (`M5b`, the no-usable-quarter refusal). The sweep script
> now repairs leftovers on startup, runs under `try/finally`, and fails if
> anything is still applied. A clean tree is verified after every run.

---

## Phase 2 — Tier 2: auction_demand_signal (Module 8.2)

### The function

Judges one Treasury auction's demand and says what it implies about duration
demand. Three-way verdict from two comparisons — bid-to-cover against its
trailing average, and whether the auction tailed — plus a separate flag for
whether foreign (indirect) demand is fading, which the verdict deliberately
does not fold in.

```
AuctionInputs(bid_to_cover, bid_to_cover_trailing_avg,
              indirect_bidder_pct, indirect_bidder_trailing_avg,
              stop_through_bp) -> ModelResult
```

### The blocker that shaped the increment

**§21.1 assigns `stop_through_bp` to the "TreasuryDirect auction results API"
as a LIVE input. That route cannot supply it.** All 91 columns of
`fixedincome.government.treasury_auctions` were inspected on the `note` security
type; there is no when-issued, expected, tail or benchmark field. The three
yields the route exposes are within-auction statistics — `high_yield -
avg_median_yield` spans only 0.0000 to 0.0011 across **all 703** note auctions,
so the median bid and the clearing yield are the same number to a rounding
error. A tail compares the clearing yield with the market's expectation *before*
the auction, which the Treasury does not publish.

**§21.0 rule 3 says stop rather than assume, so the question went to the user.**
MANUAL was chosen over a secondary-market proxy, on measurement: a Treasury tail
is 0-2bp and the proxy's own error is several bp — a proxy whose error exceeds
the signal it measures is the D-035 defect. The function takes the gap as a
caller-supplied float and the output carries both a
`stop_through_is_manual_entry: true` key and a warning naming the field.

**The cost is stated, not hidden: the live check cannot exercise the tailed
branch.** It runs at the definitional boundary (0.0bp) and says so in its own
output; the branch is covered by unit tests. See **D-036**, **O-15**.

### The four probe findings

| # | Finding | Consequence |
|---|---|---|
| 1 | `security_type` is **required** — the standard model defaults it to `None`, the provider refuses `None` | the live check passes it explicitly and asserts the refusal |
| 2 | `security_term` splits one tenor across **three** labels (`"10-Year"`, `"9-Year 11-Month"`, `"9-Year 10-Month"`) depending on reopening | grouping key is `original_security_term`; the raw string would build each average from a third of the history |
| 3 | the indirect share has **two bases differing by 27pp** — accepted 58.17% vs tendered 29.25%, largest single-auction gap **45.19pp** | the model takes the ACCEPTED basis (the market convention) and the input contract states it; the wrong basis moves the flag by nine times the 3pp threshold |
| 4 | `bid_to_cover_ratio` is **not reproducible** from the feed's own totals — 703/703 rows differ | the published ratio is used as-is; the model does not reconstruct it |

### The sign convention

`stop_through_bp` is `(expected - clearing)`, so **negative is a tail** and
weak. This reads backwards to most market conventions, and a caller supplying
`(clearing - expected)` would invert **every** verdict while producing perfectly
plausible output — D-034's failure mode exactly. So the convention is stated in
the field description, published as a `tailed` boolean beside the raw bp,
asserted against a value whose sign is known before the call, asserted for
consistency between flag and value at five points spanning zero, and warned
about in prose.

### Live reading at implementation

```
10-Year auctions usable: 143 (2015-01-13 .. 2026-09-09)
indirect share: ACCEPTED 58.17% vs TENDERED 29.25% (largest gap 45.19pp)
base rates over 137 auctions, window 6:
  weak bid-to-cover  25/137 = 18.2%
  foreign fading     45/137 = 32.8%
latest 10-Year auction 2026-09-09:
  bid_to_cover 2.71 vs trailing 2.49
  indirect     78.98% vs trailing 65.65%
  stop_through = 0.0bp (MANUAL, at the boundary)
  verdict = STRONG_AUCTION
```

**Plausibility.** A bid-to-cover of 2.71 against a 2.49 average, with indirect
bidders taking 79% against a 65.7% average, is a strongly subscribed auction —
STRONG is the right reading. Both base rates are disclosed with the verdict
precisely so such a print is not over-read: 18.2% of auctions are weak on
bid-to-cover and 32.8% are fading on indirect share, so neither flag alone is a
signal.

### What is NOT validated

The **tailed branch**. `stop_through_bp` is manual and no route publishes a
when-issued yield, so the live check runs at the boundary and says so. A green
live run does not validate the tail. Recorded as **O-15**.

The `[0, 100]` bound on `indirect_bidder_pct` also does **not** catch a caller
passing `0.55` meaning 55% — 0.55 is a legal percentage. The first version of
that test *claimed* to cover it and did not; the behaviour is now recorded in a
test that states the limitation. Recorded as **O-14**.

### Gates at close

```
ruff check        All checks passed
ruff format       76 files already formatted
mypy --strict     no issues in 76 source files
pytest -q         642 passed, 1 skipped, 0 failed
mutation sweep    32 / 32 killed
live check        passes end to end (tail not validated — see above)
Tier 2            22 / 29
```

The sweep's first run was **27/32**. Five survivors, each diagnosed per D-031:

| survivor | diagnosis | fix |
|---|---|---|
| `M2c` tail boundary literal | the config value *is* 0.0, so the literal is behaviourally identical — the test read the boundary from the same accessor the code reads (rule 7) | patch the boundary to 1.5 and assert the boundary moves |
| `C1d` boundary property hardcoded | same rule-7 defect | covered by the same fix, plus an assertion that the shipped boundary is exactly 0.0 |
| `M4c` sign warning dropped | **weak test** — the manual-entry and base-rate warnings were asserted, this one was not | assert it, including that it names the field and states the direction |
| `M6a` `extra="forbid"` removed | **weak test** — the fixture passed `stop_through` instead of `stop_through_bp` and matched `"stop_through"`, but the "field required" message also contains `stop_through_bp` | supply all five valid fields *plus* one extra, so only the forbid can make it raise |
| `C1a` window property hardcoded | **real gap** — `trailing_window_auctions` was read by no model code path, so mutating it changed nothing observable | publish it in `value`, then pin it with a patched distinct value |

---

## Phase 2 — Tier 2: credit_spread_attribution (Module 8.3)

### The function

Attributes a credit spread widening to a **fundamental** cause (default risk
genuinely rising) or a **technical** one (risk-aversion / flight-to-quality),
and reports how long the widening is expected to last. The two have opposite
forward implications — fundamental widening is sticky, panic widening snaps
back — which is the whole reason the module exists.

```
CreditSpreadInputs(hy_spread_bp, hy_spread_change_bp, ig_spread_change_bp,
                   equity_vol_change_pct, default_rate_trend) -> ModelResult
```

### The defect: a branch the specification's own logic forbids

```python
fundamental = inputs.default_rate_trend == "rising"
technical   = inputs.equity_vol_change_pct > 20 and inputs.default_rate_trend != "rising"
```

``fundamental`` requires the trend to be ``"rising"`` and ``technical`` requires
it not to be, so the two are mutually exclusive and the branch reporting
``BOTH`` / ``elevated_concern`` **could never execute**. Measured by
enumeration, not argued:

```
Reachable attributions over the whole declared input space:
  FUNDAMENTAL                   4 cases
  TECHNICAL_RISK_AVERSION       4 cases
  UNCLEAR                       4 cases
BOTH reachable? False
```

The exclusion is dropped, which makes all four reachable. A state with a named
durability value that no input can produce is a contradiction inside the
specification, not a deliberate restriction.

### The second defect: three of five inputs were inert

``hy_spread_change_bp`` and ``ig_spread_change_bp`` appear **only** in
``inputs_used``; ``hy_spread_bp`` is only echoed. So as written the function
attributed **widening** without ever checking that spreads widened — a
tightening week would still have been given a cause. The model now verifies
widening and reports ``NO_WIDENING`` / ``not_applicable`` otherwise, refusing
rather than substituting (§21.0 rule 4).

``NO_WIDENING`` is a **fifth** attribution value. All four of the
specification's are retained and reachable.

### The decision: diagnostic, not predicate

The two spread changes imply a discriminator the specification never wrote —
idiosyncratic stress widens HY relative to IG, a flight-to-quality widens both.
**The user chose to publish it as a disclosed diagnostic rather than let it
decide.** The attribution stays on the specification's trend-and-volatility
logic; the output carries ``hy_minus_ig_change_bp``,
``widenings_are_parallel``, and a warning stating the differentiation **is not
part of the attribution**. A test patches the threshold to a value that flips
the flag and asserts the attribution is unchanged.

### The units — two adjacent inputs, opposite conversions

| input | series | series units | conversion |
|---|---|---|---|
| `hy_spread_change_bp` | FRED `BAMLH0A0HYM2` | **percent** | × 100 → basis points |
| `ig_spread_change_bp` | FRED `BAMLC0A0CM` | **percent** | × 100 → basis points |
| `equity_vol_change_pct` | FRED `VIXCLS` | **index points** (a level) | none — the input is a percent change |

One conversion applied to both is a **100× error**, producing a plausible
attribution of the wrong kind. The live check asserts the raw magnitudes first
(spreads single-digit percent, VIX a level above 1.0, HY above IG); a unit test
pins that the **model** converts nothing.

### The window the specification omits

Every input is a change over a period and §20.8 names none. The same 20%
threshold fires at very different rates:

| window | VIX > +20% | HY widened |
|---|---|---|
| 1 day | 1.8% | 41.5% |
| **5 days** | **10.2%** | **42.6%** |
| 21 days | 18.2% | 37.7% |

Five trading days, recorded as ``conventional``. Note the asymmetry: the
widening rate barely moves across the windows while the volatility rate moves
tenfold — widening is near a coin flip at every horizon.

### Live reading at implementation

```
BAMLH0A0HYM2: 786 obs, last 2.76 percent
BAMLC0A0CM  : 785 obs, last 0.80 percent
VIXCLS      : 9274 obs, last 17.20 index points
units CONFIRMED: spreads in percent, VIX a level; HY above IG as required
aligned common dates: 772 (2023-09-18 .. 2026-09-15)

base rates over 767 five-day windows:
  volatility spike  78/767 = 10.2%
  HY widened        327/767 = 42.6%
  parallel widening 281/767 = 36.6%

latest window 2026-09-08 -> 2026-09-15:
  HY OAS  2.67 -> 2.76 percent = +9.0bp
  IG OAS  0.81 -> 0.80 percent = -1.0bp
  VIX     15.72 -> 17.20 = +9.4%

default_rate_trend=rising   -> FUNDAMENTAL
default_rate_trend=stable   -> UNCLEAR
default_rate_trend=falling  -> UNCLEAR
```

**Plausibility.** HY widened 9bp while IG tightened 1bp and VIX rose 9.4% —
below the 20% spike threshold. So the volatility predicate is False and the
attribution hinges entirely on the manual trend, which is exactly what the
three-line output shows. That is the honest reading: a modest, differentiated
widening with no volatility confirmation is **not** attributable to panic, and
is only "fundamental" if an operator asserts defaults are rising.

### What is NOT validated

**Which trend is true.** ``default_rate_trend`` is MANUAL per §21.1 and no free
series supplies it. The check runs all three trends and asserts the logic is
consistent for each; it cannot tell an operator which one holds. A green run
validates the machinery, not the verdict.

### Gates at close

```
ruff check        All checks passed
ruff format       79 files already formatted
mypy --strict     no issues in 79 source files
pytest -q         672 passed, 1 skipped, 0 failed
mutation sweep    33 / 33 killed
live check        passes end to end
Tier 2            22 / 29
```

The sweep's first run was **31/33**, with two survivors diagnosed per D-031:

| survivor | diagnosis | fix |
|---|---|---|
| `M3d` parallel band made strict | **weak test** — the other diagnostic tests patch the threshold to 1.0 and 50.0 against a 20bp difference, so nothing landed *exactly* on the boundary and `<=` vs `<` was unobservable | a fixture with the threshold patched to exactly 20.0 and the difference exactly 20.0 (30.0 − 10.0, built by addition so no float fuzz moves it off the boundary) |
| `C1g` parallel rate property swapped | **real gap** — `parallel_widening_rate` was read by no model code path, so swapping it changed nothing observable | publish it in `value`, then pin it with a patched distinct value |

---

## Phase 2 — Tier 2: compute_fci (Module 12, Section 22.7)

### A backfill, not a new function

`compute_fci` had **never been implemented and never even stubbed** — it is in
§21.3's Tier 2 list and nowhere in `src/`. §22.7 says so directly and requires
the retroactive add; §22.13 requires the **raw-deviation placeholder** be
deleted rather than left alongside the corrected version. Nothing was written,
so nothing needed deleting, but the placeholder form must never appear and the
suite asserts the property that distinguishes it.

### The correction

§22.7 / Finding #7: every component is **z-scored before weighting**, because
percent, basis-point and index-point units are not comparable as raw deviations
— *"which the prior version incorrectly did"*.

The property that separates the two is **scale invariance**: a z-score is
unchanged when a component's value, mean and std are rescaled together, while a
raw deviation scales with them. That is the test, and `M1a` — removing the
division by `std` — reproduces the placeholder exactly and is the sweep's most
important mutation.

### The finding: the stored denominators were wrong by two standard deviations

`fci.averages` held trailing means for three of five components, no standard
deviations, and no window:

| component | stored | measured | std | error |
|---|---|---|---|---|
| `credit_spread_hy` | **4.0** | **3.12** | 0.42 | **2.1 sigma** |
| `term_premium` | 0.3 | 0.132 | 0.35 | 0.48 sigma |
| `policy_rate` | 2.5 | 2.286 | 1.88 | 0.11 sigma |

The live spread of **2.65** scores **z = −1.12** against the measured mean and
**z = −3.2** against the stored one — dramatic looseness versus mild looseness,
with the output looking entirely normal either way.

**Removed, not corrected.** A corrected constant drifts on the same schedule.
§22.7 takes mean and std as parameters, so the caller computes them over the
configured window and nothing is frozen. `average_for()` went too: it raised
`KeyError` for two of the five components.

### The window is forced, and the reason is a provider limit

§22.7 suggests 10 years. `BAMLH0A0HYM2` returns **786 observations (~3.0
years)**, and that is a **provider limit, not a fetch window** — `start_date=1990-01-01`
returns the identical rows. The window is the **common** span of all five
components plus NFCI, not each series' own maximum, because different windows
make the z-scores incomparable. Achieved: **2.98 years**.

### The NFCI cross-check is in the contract

§21.1 calls it *"mandatory"*; NFCI is reachable (2,906 weekly obs, last −0.56).
The model takes an optional `nfci_value`, publishes the divergence, warns beyond
the configured bar — and **warns when the check is absent**, because silence
must not read as corroboration.

### Live reading at implementation

```
common span: 2023-09-18 .. 2026-09-11 = 2.98 years
binding constraint: credit_spread_hy (starts 2023-09-18)

  policy_rate        level     3.6300  mean   4.4972  std  0.6743
  credit_spread_hy   level     2.6500  mean   3.1208  std  0.4218
  term_premium       level     0.9610  mean   0.4937  std  0.1937
  equity_index       21-day change -1.1811%  mean +1.7403%  std 3.7062
  usd_index          21-day change -0.7600%  mean -0.0925%  std 1.3281

  z-scores and contributions:
    policy_rate        z= -1.2861  contribution= -0.3215
    credit_spread_hy   z= -1.1162  contribution= -0.2790
    term_premium       z= +2.4121  contribution= +0.4824
    equity_index       z= -0.7882  contribution= +0.1576
    usd_index          z= -0.5026  contribution= -0.0503
  cross-field identity holds (-0.0107 = sum of contributions)
  equity orientation CONFIRMED: its contribution opposes its z-score

  NFCI cross-check: -0.0107 vs -0.5600 -> divergence +0.5493, inside the 1.0 bar
  verdict: FCI -0.011 — LOOSER than average
```

**Plausibility.** The composite lands at **−0.011** — essentially neutral with a
slight loosening tilt — against an NFCI of **−0.56**. Both mildly loose, 0.55
apart, inside the bar: the expected outcome for two different constructions. The
largest single contribution is the **term premium at +0.48** (z = +2.41), and
that is the one worth attention — the ACM 10-year term premium is unusually high
against its own three-year distribution, a tightening force independent of the
policy rate, which is exactly what Module 8.1 says must be attributed to a
component before a thesis is built on it.

### What is NOT validated

The **weights**. They are `uncalibrated_illustrative`, so NFCI agreement would
not confirm them — the cross-check catches a divergence, not a
wrong-but-consistent weighting (**O-17**, **O-18**).

### Gates at close

```
ruff check        All checks passed
ruff format       82 files already formatted
mypy --strict     no issues in 82 source files
pytest -q         701 passed, 1 skipped, 0 failed
mutation sweep    31 / 31 killed
live check        passes end to end
Tier 2            23 / 29
```

The sweep's first run was **27/32**. Five survivors, each diagnosed per D-031:

| survivor | diagnosis | fix |
|---|---|---|
| `M4a` illustrative-weights warning dropped | **weak test** — the window, mismatch and cross-check warnings were asserted; this one was not | assert it |
| `M4b` window caveat dropped | **weak test**, same omission | assert it, including the window it names |
| `M5a` z-scores dropped | **vacuous test** — the identity test *iterated* `z_scores`, so an empty dict made the loop body never run and the test passed | assert the key set first (D-035's absence lesson) |
| `M6a` component `extra="forbid"` removed | **weak test** — the fixture passed an unknown field to `FCIInputs`, not to `FCIComponent`, so each model's own forbid went untested | test the component model directly |
| `C1b` empty-weights guard removed | **inert mutation / redundant code** — `sum({}.values()) == 0.0`, so the sum-to-one guard already raised | the **guard was deleted**, not the test (D-031) |

---

## Phase 2 — Tier 2: policy_mix_classifier (Module 3.2)

### The function

Places the policy stance in Module 3.2's fiscal/monetary 2x2. Section 20.3's
premise is that naive Fed-only analysis misses half the picture when fiscal
pulls the opposite direction — the post-2022 disinflation case, where fiscal was
loose while monetary tightened.

```
PolicyMixInputs(fiscal_deficit_pct_gdp, fiscal_deficit_avg_pct_gdp,
                policy_rate, taylor_implied_rate) -> ModelResult
```

### The trap: the deficit series is negative for a deficit

```python
fiscal_loose = fiscal_deficit_pct_gdp > fiscal_deficit_avg_pct_gdp
```

The comparison reads naturally — a *bigger* deficit is *looser* policy. The
source series disagrees. FRED `FYFSGDA188S` is **negative for a deficit**: 2025
reads **−5.77**, 2020's COVID deficit reads **−14.48**, and 83 of its 97
observations are negative.

**Fed in raw, the comparison inverts**: a larger deficit is *more* negative, so
`deficit > average` reports the most stimulative budgets in the sample as the
tightest fiscal policy — silently and plausibly. This is D-034's failure mode,
and it is the **second time in three increments**.

The field contract states the convention, the live check **asserts the raw sign,
negates, and asserts the negated sign**, and the model warns on any negative
deficit — which covers both the raw-FRED error and a genuine surplus.

### Two measurement defects, both caught before the model shipped

**1. A window mismatch on annual data.** The deficit series is **annual**, so
the common keys with the quarterly policy/inflation/output series are one per
year. The first probe stepped back four *observations* for a YoY inflation rate
— a **four-year** rate on annual data. That inflated the Taylor-implied rate and
made `monetary_loose` true in **100%** of the sample, leaving only two of four
quadrants apparently reachable.

**2. The probe then measured the inverted comparison.** With the window fixed it
still fed the **raw** series in, reporting quadrant frequencies of
17.5% / 28.1% / 22.8% / 31.6% — **all four wrong**. The live check, which
sign-verifies first, produced the correct figures.

> **The generalisable lesson: a rate measured by the same code path that carries
> the sign error cannot detect it.** The check recomputes from a series it has
> *independently* sign-verified, and the disagreement is what exposed the probe.

### The four quadrants, measured

| quadrant | measured | stored |
|---|---|---|
| `MAX_STIMULUS` | 13/57 = **22.8%** | 0.22807 |
| `MIXED_FISCAL_LOOSE_MONETARY_TIGHT` | 18/57 = **31.6%** | 0.31579 |
| `MIXED_FISCAL_TIGHT_MONETARY_LOOSE` | 11/57 = **19.3%** | 0.19298 |
| `MAX_RESTRAINT` | 15/57 = **26.3%** | 0.26316 |

All four reachable, none dominant. The two MIXED quadrants together are
**50.9%**, so a mixed policy mix is the *ordinary* case — worth publishing
because the module's framing could be read as implying otherwise.

Stored to five decimal places so the four sum to exactly 1.00000.

### Live reading at implementation

```
FYFSGDA188S: 97 obs, last -5.7691
  negative in 85.6% of observations (raw convention)
  RAW SIGN CONFIRMED: negative = deficit, so the series must be NEGATED
after negation: -4.30 to 26.86% of GDP
  surplus years: 14 of 97, e.g. [1960, 1969, 1998, 1999, 2000, 2001]

2025: core PCE +2.97% YoY, output gap +1.03%, fed funds 3.72%
  taylor_rule(r*=0.5) -> implied 4.47%
trailing 10-year mean deficit: 6.10% of GDP (stored expectation: 4.50%)

2025: deficit 5.77% vs average 6.10%  -> fiscal TIGHT
      fed funds 3.72% vs Taylor 4.47% -> monetary LOOSE
      quadrant = MIXED_FISCAL_TIGHT_MONETARY_LOOSE
```

**Plausibility.** The 2025 deficit (5.77%) sits *below* its own trailing
ten-year mean (6.10%) because the 2020 COVID deficit of 26.9% is inside that
window and drags the average up — while the funds rate (3.72%) sits *below* the
Taylor-implied 4.47%. So fiscal is tight and monetary loose: the mirror of the
post-2022 case the module was written about. The window is doing real work — the
same 5.77% deficit would be **loose** against a longer-window average, which is
exactly why the window is declared and the stored expectation's disagreement is
reported rather than hidden.

### Specification defects corrected

| Section 20.3 | Implemented | Why |
|---|---|---|
| `value=quadrant` — a **bare string** | a dict with the quadrant **and both predicates** | a bare string cannot be recomputed from its own output, so the D-009 identity is impossible |
| `inputs_used` lists **three** inputs | lists all four | `fiscal_deficit_avg_pct_gdp` decides half the quadrant |
| `"MIXED" in quadrant` | `fiscal_loose != monetary_loose` | a substring search on a name breaks silently on a rename |
| `confidence=0.6` | `compute_confidence()` | §22.8 |
| `datetime.utcnow()` | `utc_now()` | ruff DTZ |
| no base rate | the quadrant's frequency, in `value` and in a warning | D-029 |
| no sign guard | warns on a negative deficit | the trap above |

### Gates at close

```
ruff check        All checks passed
ruff format       83 files already formatted
mypy --strict     no issues in 83 source files
pytest -q         718 passed, 1 skipped, 0 failed
mutation sweep    23 / 23 killed
live check        passes end to end
Tier 2            24 / 29
```

The sweep's first run was **21/24**. Three survivors, three different diagnoses:

| survivor | diagnosis | fix |
|---|---|---|
| `M1c` substring test restored | **INERT by construction** — on the four current quadrant names `"MIXED" in quadrant` and `fiscal_loose != monetary_loose` are behaviourally IDENTICAL, so no test can distinguish them | the **mutation was removed** (D-031). The boolean form is still preferred — a rename would break the substring one silently — but a difference that does not exist cannot be swept for |
| `M4e` raw deficit dropped | **weak test** — the identity test reads the booleans and the base-rate test reads the rate; nothing read the raw inputs | assert all four inputs are republished |
| `C1a` average property hardcoded | **weak test** — the patch was 9.75, only **0.24** from the mutation's hardcoded 9.99, i.e. **inside the 0.5 mismatch tolerance**, so a literal passed every assertion | patch to **20.0**, far from both the shipped 4.5 and any plausible stand-in |

---

## Phase 2 — Tier 2: qe_qt_stance (Module 4.1)

### The function

Judges the Fed's balance-sheet stance — QE, QT, or a hold — as a **second policy
lever** the policy rate alone misses, and assesses how close reserves are to
scarcity.

```
BalanceSheetInputs(balance_sheet_level, balance_sheet_change_3mo,
                   reserve_balances, reserve_balances_change_3mo,
                   on_rrp_level=None) -> ModelResult
```

### The defect: a branch that needs a balance sheet that never moves

Section 20.4 decides the stance with `> 0` / `< 0` / `else`, so
**`NEUTRAL_HOLD` requires a thirteen-week change of exactly zero**. Measured over
1226 weeks of `WALCL`: **0 occurrences, 0.00%**. Dead code — D-037's class, for
the second time in four increments.

Corrected to a **relative band**: the change is a percentage of the level, and
±0.5% is neutral. Relative rather than absolute because the balance sheet has
ranged from $0.7T to $9.0T; a $34bn change is 0.5% of $6.7T and 5% of $0.7T.

**The correction changes today's answer.** Latest 13 weeks: **+0.226%** → inside
the band → `NEUTRAL_HOLD`. The spec's `> 0` test reads the same data as
`QE_EXPANDING`.

### The second defect: two of four inputs declared, listed, never read

`balance_sheet_level` and `reserve_balances` are named in `inputs_used`, absent
from `value`, and read by no line of the logic. The stance was decided by one
number while the output claimed three. All four are now used, and the levels are
published — a consumer cannot check a 0.5% band without the level it is a
percentage *of*.

### The scarcity assessment the warning was about

The spec warns that reserves can hit scarcity unexpectedly and says to monitor
`repo_stress_check()` — a generic sentence that fires on every QT reading.
**The mechanism is the ON RRP facility**: while it holds a buffer QT drains
*that*; once empty, the same QT comes out of reserves. That is September 2019.

So the model flags `direct_reserve_drain` (QT **and** reserves falling), reports
the ON RRP level against a drained threshold, and **discloses when the RRP level
was not supplied** — silence must not read as reassurance.

`on_rrp_level` is an addition to the spec's four inputs; optional, and the one
variable that makes the spec's own warning specific.

**76.8% of QT weeks also had reserves falling** — so the flag alone is weak
evidence, the *ordinary* case during QT. What makes it dangerous is the buffer
being gone. Both the flag and its frequency are published.

### The units, which are a 1000x trap

`WALCL` and `WRESBAL` are in **millions**; `RRPONTSYD` is in **billions**. The
RRP is compared against a threshold stated in billions, and the balance-sheet
level is the *denominator* of the relative change that decides the stance — so a
units error moves the answer while every number stays plausible. The live check
asserts each series' order of magnitude before combining anything.

### Live reading at implementation

```
WALCL 6,740,619 (mn) | WRESBAL 2,991,310 (mn) | RRPONTSYD 5.4 (bn)
units CONFIRMED: assets above reserves, RRP in the right order

Section 20.4's `change == 0` test, 1226 live weeks: 0 exactly zero
  -> the specification's NEUTRAL_HOLD branch is UNREACHABLE

base rates under +/-0.50%:
  QE_EXPANDING  597/1226 = 48.7%   QT_CONTRACTING 383/1226 = 31.2%
  NEUTRAL_HOLD  246/1226 = 20.1%   QT weeks with reserves falling: 294/383 = 76.8%

latest week 2026-06-10 -> 2026-09-09:
  balance sheet +15,222mn (+0.226%)  -> NEUTRAL_HOLD
  reserves      -89,413mn
  ON RRP        0.4bn  -> DRAINED
```

**Plausibility.** The balance sheet is flat (+0.226%) — `NEUTRAL_HOLD` is right
and the spec's test would have got it wrong. Reserves fell **$89bn** while the
ON RRP sits at **$0.4bn** against a peak of **$2,554bn**: the buffer is
exhausted, so any further contraction comes straight out of reserves. That is
exactly the September 2019 configuration the spec gestures at, and the model now
names it rather than printing the same sentence on every QT reading.

### Gates at close

```
ruff check        All checks passed
ruff format       84 files already formatted
mypy --strict     no issues in 84 source files
pytest -q         **788 passed, 1 skipped, 0 failed**
mutation sweep    27 / 27 killed
live check        passes end to end
Tier 2            25 / 29
```

The sweep's first run was **26/27**, with one survivor — and it was **my
instrument that was broken, not the test**:

| survivor | diagnosis | fix |
|---|---|---|
| `C1c` base-rate mapping hardcoded | **mis-targeted mutation** — it pointed at `return self.base_rates.rates`, which is **`PolicyMixSettings.quadrant_base_rates`**, a *different model's* property not covered by this sweep's tests. It survived for a reason that had nothing to do with QE | re-pointed at `QEStanceBaseRates.rates`' own entry, which is what the model actually reads |

That is a new failure mode for the D-031 taxonomy: not a weak test, not an inert
mutation, not a broken mutation — a mutation aimed at the wrong file's symbol.

---

## Phase 2 — Tier 2: minsky_composition_drift (Module 3.4) — INPUTS BLOCKED

### The registry blocks two of three inputs

§21.1:

> `risky_credit_growth_pct`, `total_credit_growth_pct` | **BLOCKED** | No clean
> free series for leveraged-loan growth. Raise `NotImplementedError`; log in
> `OPEN_ISSUES.md`. **Do NOT substitute total credit growth as a proxy.**

**My first instinct was to proxy it** with C&I loans or total bank credit — which
is precisely the substitution the specification anticipates and forbids. The
registry caught it before any code was written.

**The user chose** to implement the logic anyway, reading the block as about
*sourcing* rather than *arithmetic*: the model takes three raw floats and fetches
nothing, so the block belongs to the wiring. That reading matches the project's
own structure — `require_verified()` lives in the **snapshot builder**, not in
models.

**So the function ships and the live check refuses to run it.** Running it with a
stand-in would be the forbidden substitution, and a green run would read as
validation of something unvalidated. The check instead verifies both inputs are
in the registry's first-class **`blocked:`** list (the §21.4 Loophole Ledger) and
that neither has a `series` entry, recomputes the one measurable frequency, and
measures the defect's exposure on a series the model may **not** consume.

`total_credit_growth_pct` is registered as **blocked by association** — a
total-credit series *does* exist (TOTBKCR, TOTLL), so that block is a dependency,
not a data gap. The distinction is kept so a reader can see which is which.

### The defect: the comparison inverts when credit contracts

```python
risky_outgrowing = risky_credit_growth_pct > total_credit_growth_pct * 1.2
```

Multiplying a **negative** base by 1.2 makes it **more** negative, so the flag
fires when risky credit is shrinking **fastest**:

```
total -10.0%  risky -11.0%  ->  -11 > -12  ->  "outgrowing"   WRONG (de-risking)
total -10.0%  risky  -5.0%  ->  TRUE   (correct)
total +10.0%  risky +11.0%  ->  FALSE  (correct)
total +10.0%  risky +13.0%  ->  TRUE   (correct)
```

Measured over **2739 weeks**, total credit growth is negative in **91 (3.3%)**,
worst **−5.45%** — including **2009-09**, the crisis the module exists to flag. A
model calling de-risking "drift toward risky" at maximum stress is worse than no
model.

**The fix**: `(risky - total) > margin * abs(total)` — **algebraically identical**
to the specification whenever total growth is positive, sign-safe when it is not.
A test pins that equivalence across the boundary.

### The second defect: confidence biased toward alarm

§20.3 hardcodes **0.6 / 0.45 / 0.5** for PONZI / SPECULATIVE / HEDGE — so the
model is *more* confident when it says something is wrong, with no stated basis.
Confidence now comes from `compute_confidence()`, and a test asserts **all three
stages produce the same confidence**, so the bias cannot return.

### What the live check says

```
registry `blocked:` entries: [... 'risky_credit_growth_pct', ...,
  'total_credit_growth_pct']
-> the block is REAL and registered, not merely asserted

DRTSCILM (SLOOS net tightening): 146 quarterly obs, last +0.0
  net LOOSENING (< 0): 68/146 = 46.6%   (recorded 46.6%)
  exactly flat (= 0) : 7/146 = 4.8%

DEFECT EXPOSURE — measured on TOTBKCR, NOT a sanctioned input, evidence only:
  total credit YoY growth negative in 91/2739 weeks = 3.3%, worst -5.45%

NOT RUN: the model itself. Two inputs are BLOCKED.
```

The latest SLOOS reading is **exactly 0.0**, which §20.3's `< 0` test counts as
**not loosening** — true in 7 of 146 quarters, so the boundary is disclosed on
every call.

### Gates at close

```
ruff check        All checks passed
ruff format       85 files already formatted
mypy --strict     no issues in 85 source files
pytest -q         760 passed, 1 skipped, 0 failed
mutation sweep    25 / 25 killed
live check        passes end to end (Module 3.4 is a BLOCK-CHECK, not a run)
Tier 2            26 / 29
```

The sweep's first run was **21/25**. Four survivors: three were **weak tests**
(unasserted warnings), and the fourth was **rule 7 again** — the base-rate test
read its expectation from the *same accessor the model reads*, so a property
returning a hardcoded 0.0 moved both sides together and the mutation survived.

**Two defects in my own test file were caught this increment:**

- **Four test names collided** with the `policy_mix_classifier` tests added
  earlier in the same file. Python silently kept the *later* definition, so four
  policy_mix tests had **stopped running** while the suite stayed green. Found by
  ruff's `F811`; fixed by renaming the later definitions and verifying no
  duplicates remain.
- The mutation sweep's `C1b` initially appeared to target QE code but pointed at
  a **different model's property** (D-040's lesson), so the sweep now checks that
  a mutation's target belongs to the model under test.

---

## Phase 2 — Tier 2 COMPLETE (29 / 29)

### The last three

**`marginal_risk_contributions` was already done.** While starting this
increment it turned out to be **complete and to standard** in `models/risk.py` —
`compute_confidence()` rather than a literal, `utc_now()`, full
shape/symmetry/normalisation validation, the **Euler identity** check, and **6
passing tests** — while `PROGRESS.md` still listed it as `- [ ]`. The checkbox
was stale, so the Tier 2 count had been **one low**. No code changed.

Its docstring preserves a real past correction: the risk contributions sum to the
portfolio **variance**, not the volatility, and the first version's check against
`sigma_p` failed on a perfectly valid matrix.

**`bayesian_update` and `expected_value` shipped as `models/probability.py`**
(D-042), with §11.1's three mandated tests by name. Three defects corrected:

| §20.11 | Implemented | Why |
|---|---|---|
| **no input bounds** | `[0, 1]` on every probability | a **negative scenario probability** passes the sum-to-one check whenever another exceeds one (`1.5 + (-0.5) = 1.0`). A sum test is not a per-value test |
| `0.8 < lr < 1.25` | `\|lr - 1\| < band` | asymmetric **by accident**: 0.8 and 1.25 are the same distance from uninformative in log-space, and the specification treats them as 0.2 and 0.25 apart |
| `confidence=0.8 / 0.6` | `compute_confidence()` | the Bayesian constant asserts that an uninformative update and a decisive one are equally reliable |

### The verification, which is not a live check

**Neither function consumes a series.** No wiring, no units, no nulls, no
frequencies — the usual live check has nothing to do. What replaces it is the
strongest thing available: **an independent recomputation by a different
formulation.** The mandated posterior is recomputed via the **odds form**
(`posterior_odds = prior_odds × LR`), which is algebraically identical and
computationally different, so an arithmetic error in the direct form cannot
survive it.

```
Section 11.1 mandated case: prior 0.4, P(B|A) 0.7, P(B|~A) 0.2
  posterior (direct form) = 0.7
  posterior (odds form)   = 0.7000000000
  -> both formulations AGREE to 1e-9
cross-field identity holds | mandated warning FIRES | mandated refusal RAISES

tail boundary: EV +5.0000, worst -10.0000, multiple 2
  -> the comparison is strict, exactly at the configured multiple
EV identity holds (+10.8000 = sum of contributions)
```

The boundary fixture is **derived from the configured multiple**
(`base_gain = tail_loss * (1 + 2/multiple)`). The first version used payoffs of
+10 / −10·m, giving **EV = −5** — negative, so `tail_dominates` (which requires
`EV > 0`) could never be reached and the boundary was **untestable**. The check
failed on its own fixture rather than passing vacuously.

### Tier 2 — what "complete" does and does not mean

**Every one of the 29 functions is written, tested, and mutation-swept.** That is
what the count means.

**It does not mean every function is validated against real data.** One is not:

> `minsky_composition_drift` has **two BLOCKED inputs** (§21.1), so its live
> check is a block-check and **the model has never been run against real data**.
> Its stage base rate is unmeasurable. See **O-20**.

Two others ship with their validation limits stated rather than closed:
`auction_demand_signal` cannot validate its tailed branch (D-036, O-15), and
`credit_spread_attribution` cannot validate which manual trend is true (D-037).

### Gates at close

```
ruff check        All checks passed
ruff format       88 files already formatted
mypy --strict     no issues in 88 source files
pytest -q         **788 passed, 1 skipped, 0 failed**
mutation sweep    29 / 29 killed
live check        passes end to end
Tier 2            29 / 29 ✅ COMPLETE
```

The sweep's first run was **25/29**. All four survivors were **weak tests** —
including two **strictness** cases where nothing landed *exactly* on the
boundary, so `<` versus `<=` was unobservable. Both are now pinned with fixtures
built to sit on the boundary for any configured threshold value.

---

## Phase 2 — Tier 3 opens: `classify_regime_rule_based` (Module 3.1)

**Status: IMPLEMENTED, TESTED, MUTATION-SWEPT, LIVE-VALIDATED.** First Tier 3
function. D-045.

Tier 1 and Tier 2 are pure computation over supplied inputs. Tier 3 is
different in kind: it **composes other models' outputs**, so its defects are
*interaction* defects rather than arithmetic ones — a correct branch reading a
correct input that means the wrong thing. That is what this increment found,
four times.

### The function

`models/regime.py` — `classify_regime_rule_based(inputs: RegimeInputs) →
ModelResult`, mapping `(growth_axis, inflation_axis)` onto one of nine declared
regime states. `RegimeInputs` (`extra="forbid"`) takes `output_gap`,
`inflation_yoy`, `inflation_trend_3m`, `unemployment_gap`, an optional
`output_gap_change`, and `data_quality_flags_present`.

Two published axes rather than three private helpers: `growth_axis` and
`inflation_axis` appear in `value`, so a reader can audit *why* a label was
chosen instead of having to re-derive it. This is what made the fourth defect
visible (below).

### The three specification defects corrected

**1. The grid reached six of nine states.** §6.2's decision structure left three
declared states with **no cell that could produce them** — the same shape as
D-037's "dead branch" class. The corrected grid uses three asymmetries (depth
beats direction) and gates `recovery` on `output_gap_change > 0`, which is the
only reading that distinguishes "contracting and worsening" from "contracting
and improving". A test asserts every one of the nine `Literal` members is
reachable, so a future edit cannot silently re-orphan one.

**2. The `else` branch was the optimistic branch.** A growth reading that matched
neither the recession nor the weak threshold fell through to
"above trend". `Literal` typing on the axes (D-029) is what closes it; a bare
`str` would let a mis-typed value land in the optimistic cell.

**3. `deep_contraction` vs `contraction` was decided by inflation, not depth.**
Depth is the more informative axis — a -4% gap is a different object from a -0.6%
gap regardless of prices — so depth now selects the state and inflation only
refines which of `recession`/`stagflation` applies.

### The fourth defect — found by running it, not by reading it

**The inflation axis is a near-constant, and the cause is upstream of this
function.**

`inflation_trend_3m` is a **3-month ANNUALIZED** change — a month-over-month
measure of the price *level*. The level falls in only a small minority of months,
so an axis defined on its sign is near-constant by construction. Measured over
**240 real quarters (1966-07 … 2026-04)**:

```
inflation axis = 'rising'  in 225 / 240 quarters  =  93.75%
```

Consequence — measured state frequencies:

| State | Count / 240 | Rate |
|---|---|---|
| `late_expansion` | 117 | 48.75% |
| `recession` | 63 | 26.25% |
| `stagflation` | 37 | 15.42% |
| `reflation` | 15 | 6.25% |
| `recovery` | 3 | 1.25% |
| `slowdown` | 2 | 0.83% |
| `disinflation` | 2 | 0.83% |
| `mid_expansion` | 1 | 0.42% |
| `early_expansion` | **0** | **0.00%** |

**Two independent confirmations that this is construction, not economy:**

- **1985-Q3 and 1986-Q1** — definitionally the disinflation era — are labelled
  **`reflation`** (3-month annualized momentum +2.6% and +5.3%).
- The negative at-trend strip that *defines* `early_expansion` was entered by
  **eight quarters, every one of which had rising momentum.** The state is
  unreachable not by rarity but by contradiction.

**Alternatives measured over the same window**, so the correction can be made
deliberately rather than guessed at:

| Axis definition | rising / flat / falling |
|---|---|
| **§6.2 as written** — sign of the 3-month annualized change | **225 / 2 / 13** |
| 12-month change of the 12-month YoY rate | 124 / 10 / 106 |
| 3-month annualized reading *relative to* the 12-month YoY rate | 121 / 18 / 101 |

Either alternative is a genuinely two-sided axis.

**Deliberately not corrected here.** Which input defines the inflation axis is a
§6.2 **input-definition** decision — a specification matter, not an
implementation one, and swapping it would silently redefine a declared input.
Disclosed instead, on every output:

```
value["rising_inflation_base_rate"] = 0.9375        # read from config
warn: INFLATION-AXIS BASE RATE: over the same 240 observations the inflation
      axis read 'rising' in 93.8% of them. ...
```

Tracked as **O-23** (the axis) and **O-24** (five of nine base rates are
counters, not frequency estimates). The live check recomputes all nine from raw
series and **fails on >1pp drift**, so the numbers cannot go stale silently.

### The lingering carry-over, closed: the property-vs-field guard

The collision (a Pydantic field and a `@property` sharing a name) had been hit
**five times** and was owed a **structural** guard, not another docstring — D-035
rule 17: a trap hit twice needs a *test*.

**Pydantic 2.13's actual mechanism, measured** (the first guard was written on a
guess and was **inert**):

> Pydantic **consumes** the property, stores the **property object** as the
> field's default, and **deletes the name from the class dict**. So
> `vars(klass)` no longer contains the name — a name-intersection guard is
> provably blind — and `instance.field` returns a `<property object>` rather
> than a value.

The only surviving signature is `isinstance(model_fields[name].default, property)`.
`tests/test_infrastructure.py` now asserts that signature **against a
deliberately broken model**:

```python
class _PropertyAfterField(BaseModel):
    threshold: float = 1.0

    @property  # type: ignore[no-redef]
    def threshold(self) -> float:  # noqa: F811
        """Reuses the field name — the defect under test."""
        return 2.0
```

**The first version of this guard passed against the healthy models and also
passed against the broken one**, which is how the inertness was found: a guard
that is never pointed at the defect it claims to catch is a comment with
punctuation. Three assertions now pin the mechanism itself, including
`vars(_PropertyAfterField).get("threshold") is None` — the fact that made the
naive guard useless.

### `docs/MODULE_MAPPING.md` — the longest-standing carry-over, written

Owed since Session 4 and named in `PROGRESS.md`'s carry-over table as the oldest
open item. **Generated from the code rather than transcribed from the
specification**, because the specification has now been corrected 45 times and a
hand-copied mapping would encode the superseded version. Function lists come from
an `ast` walk; test mapping comes from the suite's actual `ImportFrom` nodes, so
a function with no importing test shows as a **gap** instead of silently
inheriting a neighbour's coverage. Columns: Spec | Module | Function | Source |
Test | Tier | Decision.

It maps all public `def`s in `models/` — 63 as of that increment, **65 now** —
and closes with a **"Gaps this mapping exposes"** section, including the note
that `select_instrument` is the standard the Tier 4 functions must meet (§22.3).
The file must be **regenerated, not hand-edited**, and its count re-derived
whenever a module is added.

### Mutation testing — 39 mutations, 39 killed

Two new mutation families for the new config leaf (`M6e`/`M6f`/`C1f`: the axis
base rate dropped from `value`, its warning dropped, and its property
hardcoded), because a disclosure that no test can break is a disclosure that can
be deleted without consequence.

**One survivor, and it was a genuine weak test — `M4b`.** The mutation removes
the zero-guard from `slack_corroborated`, leaving
`(output_gap < 0.0) == (unemployment_gap > 0.0)`. That is *not* uniformly `False`
for a zero reading, so the mutation is **observable in 4 of 7** configurations —
but the fixture had chosen two of the three **non-observable** ones
(`0.0, +1.0` and `-2.0, 0.0`). Enumerating all four zero cases:

| `output_gap` | `unemployment_gap` | guarded | mutation | observable? |
|---|---|---|---|---|
| `0.0` | `-2.0` | False | False | no |
| `0.0` | `+2.0` | False | False | no |
| `+2.0` | `0.0` | False | False | no |
| `+2.0` | `-2.0` | False | **True** | yes |
| `-2.0` | `+2.0` | True | True | no |
| `-2.0` | `0.0` | False | False | no |
| `0.0` | `0.0` | False | True | yes |

Fixed by re-fixturing the test to the observable rows **and** adding
`test_every_zero_reading_is_uncorroborated_whatever_the_partner_sign`, which
pins all four. A weak-test survivor is not a passing grade.

### A crash-safety lesson, paid for in a corrupted source file

While verifying `M4b` by hand I applied the mutation with a heredoc that
collapsed `\n` into a literal `/n`, producing a `SyntaxError` in
`models/regime.py`. The restore step then copied back a backup taken **after**
the corrupting write, so the corruption persisted — and there is no git in this
workspace. Repaired by editing the line back directly.

This is **D-035's crash-safety hazard in a new costume**: a mutation applied
outside the sweep's `try/finally` heals nothing. Confirmed afterwards by driving
`mutation_regime._MUTATIONS` directly that the script's own pattern was still
clean (`old in src` was `True`). The rule stands: **the sweep is the only thing
allowed to mutate the source.**

### Live reading at implementation — 2026-09-17

The live check builds all four inputs from raw FRED (pairing on the latest
**common** quarter, per D-009) and then recomputes the nine base rates
independently:

```
  input output_gap                     = <live>
  input inflation_trend_3m             = <live>
  state                                = late_expansion
  state_base_rate                      = 0.4875
  growth_axis / inflation_axis         = above_trend / rising
  confidence                           = 0.3
   warn: The state is a CATEGORICAL ... Over 240 measured observations this
         state occurred in 48.8% of them
   warn: INFLATION-AXIS BASE RATE: ... read 'rising' in 93.8% of them
  states reached historically: 8 / 9
  largest drift: mid_expansion 0.0000
  CONSISTENCY OK: every stored base rate matches a live recomputation
```

**`states reached historically: 8 / 9`** — the ninth is `early_expansion`, whose
absence in a sixty-year window is the finding, not a bug.

**A live-data defect found at the same time:** the check's CPI cadence assertion
(`max(gaps) <= 45`) **failed on its first real run** with
`CPIAUCSL is not monthly: gaps [28, 29, 30, 31, 61]`. The 61-day gap is
**2025-09-01 → 2025-11-01** — the same October 2025 hole D-025 documents for
`UNRATE`. Cadence is now a **disclosure** rather than an assertion (short gaps
must be `{28,29,30,31}`; long gaps are printed with a "never imputed" note).
The consequence was worse than the assertion failure: **`cpi[-13]` spans 396
days, not 365**, so the index-offset YoY was silently an *eleven-month* change
labelled twelve-month. YoY and momentum now use **calendar-month** lookup via
`_read_month(months_back)`, which returns `None` for an absent month and makes
its callers **assert rather than substitute**.

### Warning-path coverage

| Warning | Triggered by |
|---|---|
| state base rate, with its measured frequency | `test_the_state_base_rate_is_reported_with_its_own_frequency` |
| inflation-axis base rate, with its measured share | `test_the_inflation_axis_base_rate_is_disclosed_and_read_from_config` |
| unmeasured base rate reported as **absent, not zero** | `test_unmeasured_base_rate_is_reported_as_absent_not_zero` |
| zero reading not counted as corroboration | `test_every_zero_reading_is_uncorroborated_whatever_the_partner_sign` |
| recovery undecidable without `output_gap_change` | `test_recovery_needs_a_direction_not_just_a_level` |
| heuristic, not calibrated | `test_confidence_comes_from_compute_confidence` |

### A fifth defect, found while writing this record — the published axis (D-045a)

`GrowthAxis` declared **four** members and `_growth_axis` returned **three**.
`at_trend` was a published contract member no input could produce — the same
declared-but-unreachable shape as the state grid, one level down.

It survived because the only test touching it asked whether the returned value
**is a member** of the set, which any member satisfies; nothing asserted the
converse. The stronger half of a `Literal` contract — *every* member is
producible — was untested.

**Underneath it, a docstring describing a guard that does not exist.** The
function claimed its final bucket was "explicitly `>= settings_late` rather than
a fallthrough". There is no `settings_late`; the parameter is not in the
signature and could not be tested against. The partition is closed by the
arithmetic of a three-band split, not by a guard.

**Corrected:** `at_trend` removed with the reason recorded at the declaration
(it is not a missing branch — the near-trend strip is a sub-split of
`above_trend`); the docstring rewritten to describe the code; the grid diagram
now distinguishes the **cell grid** from the **axis vocabulary**.

**Two tests added**, both of which fail against the old declaration:
`test_the_growth_axis_has_no_at_trend_member`, and
`test_every_growth_axis_member_is_reachable_and_the_boundary_belongs_to_the_upper_band`
— the latter also pins that a gap sitting **exactly** on a configured threshold
belongs to the upper band, which nothing previously exercised.

**Mutation `M7a`** re-declares `at_trend` and is killed. 39 → **40 mutations**.

### A process finding: never run the mutation sweep in the background

While verifying `M4b` I ran the sweep in the background and then edited the
source. The sweep applies a mutation, runs the suite, and restores from a
**pre-sweep in-memory copy** — so my edits fell inside that window and were
silently reverted, and a test run I read as four new failures was actually
reading `M4b` **mid-application**.

Terminating the sweep hard then **left `M5b` applied**: the momentum disclosure
replaced by `"See documentation."`, which also broke the string concatenation so
the following sentence became a discarded expression. **A `try/finally` restore
does not run under a hard kill.** `repair_leftover_mutations()` at startup healed
it on the next clean run — which is exactly why the script has that function.

> **The sweep owns the source file for its entire duration. Run it in the
> foreground, and never concurrently with anything else that edits the tree.**

### Gates at close

```
ruff check        All checks passed                 (src, tests, scripts, tools)
ruff format       92 files already formatted
mypy --strict     no issues in 92 source files
pytest -q         848 passed, 1 skipped, 0 failed
mutation sweep    40 / 40 killed   (scripts/mutation_regime.py)
live check        passes end to end, zero base-rate drift
Tier 2            29 / 29
Tier 3            2 / 15
```

### What is NOT validated

- **Five of nine base rates are counters, not frequency estimates.** With
  `early_expansion` at 0/240 and `mid_expansion` at 1/240, a single observation
  moves the rate by 0.4pp. The config says so per leaf; see **O-24**.
- **The inflation axis is unchanged.** `classify_regime_rule_based` is validated
  *for the current input definition*, which is the near-constant one. If §6.2's
  axis is redefined per O-23, **all nine base rates must be re-measured** — they
  are properties of the axis, not of the economy.
- **`unemployment_gap` is used only for corroboration**, never to select a
  state. Whether it should carry more of the decision is untested.
- **The corroboration cross-check is not independent in the D-027 sense.** Both
  `output_gap` and `unemployment_gap` are ultimately derived from the same
  realised activity data, so agreement between them is weaker evidence than two
  genuinely disjoint measures would be.
- **The growth axis has three members, not four.** An earlier declaration
  advertised an `at_trend` no reading could produce (D-045a). The near-trend
  strip is visible in `state` (via `early_expansion`/`mid_expansion`) but not as
  an axis value, so a consumer who wants to know *whether the reading was inside
  the hysteresis band* must compare the gap against `growth_momentum_band_pp`
  themselves. Adding an explicit band flag to `value` would be a contract change
  and has not been made.

---

## Phase 2 — Tier 3: `tag_evidence_source` + `count_independent_families` (Module 13)

**Status: IMPLEMENTED, TESTED, MUTATION-SWEPT.** D-046. **No live check — the
module consumes no data series**, and that is a property of the function, not an
omission (see *What is NOT validated* below).

Tier 3's first pair of *plumbing* functions. They take no measurements and
compose no models; they exist so that a **count of agreeing signals can be
checked against the number of independent sources behind them**, and they are
the supplier for an argument that `compute_confidence()` has been consuming as a
literal zero since Phase 2.

### The function

`models/evidence.py` — two public functions and one result model:

```
tag_evidence_source(model_result, family, *, data_quality_flags_present=False) -> ModelResult
count_independent_families(tagged_results: list[ModelResult]) -> ModelResult
```

`value` is an `EvidenceTally`: `distinct_families`, `families` (sorted
membership), `tagged`, `untagged`, `duplicate_results`. The vocabulary is
`models/evidence_family.py` — `EvidenceSourceFamily`, 31 members.

### The gap this closes, and the gap it does not

`ConfidenceInputs.source_independence_count` has existed since Phase 2 and is
consumed by `compute_confidence()`. **Before this increment it was `0` at every
one of its roughly fifteen call sites in `models/`** — not because the models
were independent of each other, but because **no function could produce a
non-zero value for it.** Every confidence the system has ever published was
computed as though no result had ever had an independent source.

That is the D-045a class again, one layer up: **declared, consumed, unreachable**
— there it was an enum member, here an *argument*.

**What is closed:** the supplier exists.
**What is open:** §15.19-D obliges every convergence-classification function to
*call* it. None of those callers exists yet (they are the remaining Tier 3
work), so the fifteen sites are now **suppliable but not supplied**. This is
recorded as a carry-over in `PROGRESS.md` precisely because "the supplier
shipped" reads like completion and is not.

### The arithmetic, and why it needed a vocabulary

A convergence classifier asks *how many of my signals agree?* The trap:

```
headline CPI  ─┐
core CPI      ─┤
trimmed-mean  ─┼─ all built from ONE BLS survey → ONE family → ONE vote
median CPI    ─┤
supercore     ─┘
core PCE      ──── a separate BEA release → a SECOND vote
TIPS breakeven ─── market pricing, no release dependency → a THIRD vote
```

Five agreeing sub-measures are **one** observation reported five times. Counting
them as five manufactures a confidence the data does not support — and it is the
failure mode that looks most like diligence.

A family is a **shared upstream production process**: two series share one when a
single failure — survey redesign, rebenchmarking, collection outage, methodology
revision — would corrupt both at once. That is the membership test, and it is why
`BLS_CPI` and `BLS_PPI` are **separate** (separate surveys, separate samples)
while headline and core CPI are the **same** member. Independence is about
production-process redundancy, not topic overlap.

### The five corrections to §15.19-D

**1. The tag is a typed field, not a warning string.** The specification appends
`source_family=<value>` to `ModelResult.warnings` and parses it back with a
`startswith` match. A warning list is a **reporting surface**; provenance is a
fact about a value. Any caller that rewrites, truncates, deduplicates, sorts or
filters warnings destroys or corrupts the tag **silently and without error**,
and a hand-written warning can **forge** one. Two new `ModelResult` fields
replace it — `source_family: EvidenceSourceFamily | None` and
`data_quality_flags_present: bool`.

A human-readable note is still appended to `warnings`, because a reader of the
warnings should see it. The note is a **report of** the field, not the field —
which is exactly what makes stripping it harmless, and a test asserts that.

**2. It returns a `ModelResult`, not a bare `int`.** §22.9 requires it, but the
substantive reason is stronger: **the count is uninterpretable without its
denominator.** Three families across five signals and three families across nine
signals are different epistemic situations, and a bare integer cannot tell them
apart.

**3. Tagging does not mutate its argument.** The specification appends to the
caller's `warnings` and returns the **same object**, so tagging a result
referenced in five places silently relabels it in all five. The shipped version
returns a copy.

**4. A conflicting re-tag is refused, not silently overwritten.** A result that
already carries a family is one whose provenance somebody already decided;
overwriting discards that decision. Re-tagging the *same* family is idempotent
and allowed. The refusal message says what to do instead — *if two families
genuinely apply the result is composite and each component must be tagged
separately.*

**5. The census is not scored by its own output.** `source_independence_count=distinct`
would let the tally rate itself by the quantity it just measured — the D-027
circularity class. It is not cosmetic: it **inverts the ranking**, making nine
genuinely independent sources out-score the same census finding five redundant
ones, when the redundancy is the interesting finding. The census is heuristic,
and its confidence is pinned **absolutely** against `compute_confidence`.

### An architectural correction the specification could not have anticipated

`EvidenceSourceFamily` **already existed** — 31 members, in
`thesis_layer/schemas.py` — with **no constructor and no importing test.** It had
shipped as an **orphan**: a declaration nothing used, in the layer that is not
allowed to be imported by the layer that needs it.

- `models/` is the lower layer; `thesis_layer/` imports from it and never the
  reverse. The functions obligated by §15.19-D to consume this vocabulary
  (`inflation_convergence_classifier`, `four_pillar_scorecard`,
  `classify_convergence`) are **all model-layer**, so the enum sat where **no
  model-layer classifier could reach it downward.**
- It could not simply move into `contracts.py` either: `contracts.ModelResult`
  needs the enum for its typed field while `evidence.py` needs `contracts` for
  `ModelResult` and `compute_confidence`. A **circular import.**

Resolution: a third module, `models/evidence_family.py`, holding only the enum,
imported by both. `thesis_layer/schemas.py` **re-exports** it, so
`ConfirmationSignal.source_family` and every existing import are unaffected. A
test asserts the two import paths resolve to the **same object** rather than to
equal copies, because a fork would satisfy `==` and still be the defect.

The 31-member vocabulary was **kept** rather than reduced to the specification's
smaller set — the names correspond to real upstream production processes this
system consumes — and the D-045a lesson is enforced on the declaration itself by
`test_the_family_vocabulary_has_no_declared_but_unreachable_member`.

### The five first-run survivors, all four classes of them

The first sweep returned **12/17**. The five survivors were **not one problem**,
and correctly classifying them was most of the work:

| Mutation | Class | Why it survived | Fix |
|---|---|---|---|
| `M4a` typed field → plain string | **broken** | `object \| None` is *broader* than the enum, so pydantic still accepted it | rewritten to `str \| None`, which makes pydantic **demote the enum to a bare string** |
| `M4b` enum loses its `str` base | **broken** | the replacement text was a **comment-only no-op**; the file compiled and behaved identically | rewritten to change the actual base class |
| `M5b` untagged disclosure dropped | **inert** | I patched `{untagged}` → `{0}` inside an f-string, but the *asserted phrase* survived, so every assertion still passed | rewritten to disable the **guard** (`if untagged:` → `if False:`) |
| `M5c` one-family disclosure dropped | **inert** | same shape — patched the message, not the branch | rewritten to disable the guard |
| `M7b` heuristic penalty dropped | **weak test** | the invariance test compared **two calls of the same function** | added `test_the_census_confidence_is_the_heuristic_penalised_value`, pinning the **absolute** value |

The generalisable finding from `M7b`: **an invariance test that compares a
function to itself cannot detect a change to a constant both sides read.** The
fixture must pin an absolute value that the mutation moves.

### Warning-path coverage

Five warning branches, each with a test that triggers it, and
`test_every_warning_path_is_triggered_by_some_test` asserting the pairing:

| Branch | Trigger |
|---|---|
| empty list | `test_an_empty_list_is_zero_families_and_disclosed` |
| untagged results present | `test_the_count_reports_the_untagged_denominator` |
| duplicates collapsed | `test_five_cpi_measures_are_one_vote_not_five` |
| all from one family | `test_one_family_reported_many_times_is_called_out` |

### Gates at close

```
ruff check        All checks passed                 (src, tests, scripts, tools)
ruff format       96 files already formatted
mypy --strict     no issues in 96 source files
pytest -q         871 passed, 1 skipped, 0 failed
mutation sweep    17 / 17 killed   (scripts/mutation_evidence.py)
```

### What is NOT validated

- **No live check, by design.** The module consumes no FRED/Treasury series, so
  there is no wiring, unit or null-behaviour to validate against real data. The
  §21.0 discipline's live step has nothing to run. Like `bayesian_update` and
  `expected_value` (D-042), the strongest available substitute is an
  **independent recomputation**, which the test file supplies: the same
  three-family tally is reached from five redundant results *and* from two
  independent ones.
- **No caller.** Nothing in the codebase invokes either function yet.
  `source_independence_count` is still literally `0` everywhere it is passed.
  The contract is closed at the **producer** end only — see the carry-over row
  in `PROGRESS.md`.
- **The 31-member vocabulary is unexercised beyond construction.** Most members
  have no producing model yet (Phases 3–5 supply them). Membership was validated
  against production-process reasoning, not against a working tagger per family.
- **`duplicate_results` counts repeats, not near-repeats.** Two results from the
  same family are collapsed; two results from *correlated but distinct* families
  (e.g. a Cleveland Fed nowcast and a Dallas Fed trimmed mean, both ultimately
  CPI-derived) are counted as two. The family boundary is a judgement encoded in
  the vocabulary, not something the function can measure.

---

## Phase 2 — Tier 3: `inflation_convergence_classifier` (Module 5.3)

**Status: DONE.** Decision record **D-047**. Function count 65 → 66.

This is **the first function obligated by §15.19-D**, and the increment's real
subject is the discharge of that obligation. The section requires every
convergence classifier to call `count_independent_families()` on its inputs and
use **that count — not the number of agreeing signals — as the confidence
denominator.** D-046 built the supplier and warned explicitly that *the supplier
is not the wiring*. This is the wiring.

```python
tagged, _ = _tagged_measures(inputs, directions)
census = count_independent_families(tagged)
assert isinstance(census.value, dict)
independent_families = int(census.value["distinct_families"])
...
confidence=compute_confidence(
    ConfidenceInputs(
        is_heuristic_not_calibrated=True,
        source_independence_count=independent_families,   # FAMILIES, not len(directions)
    )
)
```

The published `value` is an `InflationConvergenceVerdict` carrying
`independent_families` and `family_names` **alongside** `measures_used`, so a
reader can see the two numbers diverge. That divergence is the finding.

### Correction 1 — the conflict gate read two measures and ignored the rest

The specification tests **`headline` and `core` only**. Every other measure —
including the two the probe had just unblocked — was decorative with respect to
the conflict decision.

The correction: rather than asking whether a privileged pair disagrees, ask
whether the **losing side** reaches `deep_conflict_share` of the *whole* set.

```python
losing = min(agreeing, opposing)
if headline * core < 0:
    return "CONFLICTED"
if total > 0 and losing >= deep_conflict_share * total:
    return "CONFLICTED"
```

**Measured effect on 522 real months: 6 months, 1.15%** — and they are exactly
the months one would want:

| Month | Why the pair gate missed it |
|---|---|
| `2008-12` | headline/core agreed; the broader measures split hard |
| `2017-03` | a soft-patch month, one dissenter among six |
| `2020-03` | COVID onset |
| `2020-04` | COVID trough |
| `2020-05` | COVID rebound |
| `2026-06` | the most recent conflict in the sample |

A 5–1 split with one dissenter no longer passes as agreement. **1.15% is the
right order of magnitude for this class of defect** — large enough to matter, small
enough that no plausible-looking output would have revealed it.

### Correction 2 — HIGH is the base state, not a finding

Measured on the same 522 months:

| Measures | `HIGH` share |
|---|---|
| six | **89.5%** |
| three | **86.6%** |

The config's `measured_base_rates` block recorded **89.5% and 86.6% to the
decimal** — because the config was measured *from this function*. So the
configuration was accurate and the finding was still that the function's most
confident-looking verdict is its modal output. `HIGH` means *the usual thing
happened.*

The base rate now travels with the verdict on every `HIGH`, in `value.base_rates`
and in a warning. This is **D-029's rule reached from a new direction**: there,
a boolean from a noisy comparison had to carry its frequency; here, an entire
*classification* is the modal case.

### Correction 3 — the thresholds are degenerate below n = 5

At `n = 3` with `high_threshold = 0.8`, the attainable fractions are
`{1/3, 2/3, 1}`. So:

- `>= 0.8` **requires unanimity** — a percentage threshold silently became a
  unanimity rule;
- `MEDIUM` (the `0.6 <= f < 0.8` band) has exactly **one** attainable value,
  `2/3` — it is unreachable for every other `n = 3` input;
- `deep_conflict_share = 0.25` on a set of 3 fires on **a single dissenter**
  (`1 >= 0.25 * 3`).

Two arithmetic tests expected `MEDIUM` and got `CONFLICTED`, which is how this
surfaced. The response was **not** to retune the share — retuning would have
hidden the degeneracy behind a number that happens to work at one `n`. Instead:

- the behaviour is **disclosed** in a warning at `n < 5`;
- the reachability proof for `MEDIUM` moved to `n = 6`, where the band is real;
- the config records the degeneracy in the entry's own note.

### The input space is narrower than the specification implies

`core_pce_direction` is **required**, so the floor is **3 measures spanning 2
families** (`BLS_CPI` + `BEA_PCE`). Therefore **`independent_families` can only
ever be `{2, 3}`** and two things are structurally unreachable through the API:

1. §15.19-D's **single-family self-corroboration warning** — the state it warns
   about cannot be constructed;
2. the **`confidence_ceiling_by_independent_families`** ceiling.

This was discovered by **11 failing tests**: my first fixtures assumed I could
supply 2 or 4 measures. The tests were wrong, not the function — and the resulting
finding is more interesting than the tests were.

Both are **recorded, not hidden**: `test_a_single_family_input_is_unreachable`
enumerates the admissible space and asserts the achievable set is exactly
`{2, 3}`, and `test_the_ceiling_warning_is_dead_code_through_the_api` documents
that the branch cannot fire. A test that pins an unreachable state as unreachable
is the D-045a discipline applied to a *finding* rather than to an enum.

### The O-21 defect class, for the third time

§21.1 listed three inflation dispersion measures as blocked. The probe found
**two of them live**:

| Registry key | Series | Observations |
|---|---|---|
| `median_cpi_direction` | `MEDCPIM157SFRBCLE` | 524 |
| `trimmed_mean_direction` | `PCETRIM1M158SFRBDAL` | 594 |

So the classifier runs at **six measures, not three** — which is exactly why the
`n < 5` degeneracy had to be measured rather than assumed. Had the blocked entries
been trusted, the function would have shipped with a unanimity rule disguised as
`>= 0.8` and nobody would have noticed, because three measures is a plausible
input set.

`supercore_direction` **stays blocked.** The four `blocked:` entries flagged in
O-21 (`iron_ore_change_pct`, `ppp_implied_rate`, `supercore_direction`,
`conference_board_lei`) are **still un-re-probed** and are now the oldest open
data-discovery debt in the project.

### The mis-targeted mutation I committed

The ceiling mutation (**C-1c**) survived, and the reason was **my error, not a
weak test**. I anchored it on the bare string `      value: 5`, which occurs
**four times** in `settings.yaml` — including under `credit_spread`. The mutation
edited the **wrong config entry** and the test correctly did not care.

This is **survivor class four, mis-targeting** — the D-040 class — and it is the
second time in two increments that a mutation's *actual* edit needed proving
before the test could be judged. Generalised as rule 29 in `PROGRESS.md`: anchor
on the key line as well as the value, and **prove what a surviving mutation
changed** before concluding the test is thin.

### A dead config value the code contradicted

`confidence_ceiling_by_independent_families` was configured as **3**. The
confidence constants saturate at **5** (`cap 0.25 / bonus 0.05`). Nothing read the
configured value, so **no test could fail** — a config value is only observable
through a reader, and the reader had stopped using it.

Fixed structurally rather than by editing `3` → `5`:

```python
@property
def families_for_full_credit(self) -> int:
    bonus = float(confidence.source_independence_bonus.value)
    cap = float(confidence.source_independence_bonus_cap.value)
    derived = math.ceil(cap / bonus) if bonus > 0 else 0
    configured = int(self.confidence_ceiling_by_independent_families.value)
    if configured != derived:
        raise ValueError(...)
    return derived
```

The value now **derives itself from its source and raises on disagreement**, so
future drift is a startup error. `test_families_for_full_credit_is_live_not_dead_config`
asserts the cross-check actually fires — the test that would have caught this
the first time.

### The first-run survivors, all four classes again

The first sweep returned **19/24**. Every one of the five survivors was classified
before any test was changed:

| Mutation | Class | Why it survived | Fix |
|---|---|---|---|
| `B2` pair gate disabled | **weak test** | at `n = 3` the whole-set gate **subsumes** the pair gate, so every test fired both | tested at `n = 6` with a 5–1 split, which fires only the pair gate |
| `C4` ceiling warning dropped | **inert** | the branch is **dead code** — `bands_available` is always all three classes | reclassified `[INERT BY DESIGN]`, and a test pins the deadness |
| `D2` all-flat guard removed | **inert** | `losing` is `0` when nothing moves, and `0 >= 0.25 * total` is **already** `False` | **the term was removed and the source comment corrected** |
| `C-1a` HIGH threshold hardcoded | **mis-targeted** | the test read the threshold back through **the same accessor the model uses** — D-027 circularity inside a config test | the literal `0.6` / `0.8` is now pinned |
| `C-1b` ceiling hardcoded | **weak test over dead config** | nothing read the configured value | made the property derive-and-cross-check; added `C-1c` |

**`D2` is the one worth dwelling on.** The source comment asserted that the
all-flat guard protected the division. Mutation proved it protected nothing. **The
comment was the defect** — a stated rationale is a claim, and claims get
mutations (rule 28). The term was deleted rather than kept as belt-and-braces,
because a guard that cannot fire is a guard whose removal cannot be detected.

`D2c` then survived as a genuine gap — `>=` versus `>` differs **only where
`share * total` is an integer**, i.e. **only at `n = 4`** — closed by
`test_the_conflict_boundary_is_inclusive` using the `n = 4`, 3–1 split where
`0.25 * 4 == 1.0` exactly.

### Warning-path coverage

| Branch | Trigger |
|---|---|
| threshold degeneracy at `n < 5` | `test_the_thresholds_are_disclosed_as_degenerate_below_five` |
| `HIGH` base-state disclosure | `test_the_base_state_share_travels_with_the_verdict` |
| band ceiling by independent families | dead through the API — pinned as unreachable |
| single-family self-corroboration | **unreachable** — `test_a_single_family_input_is_unreachable` |
| flat-reading exclusion | `test_a_flat_direction_is_excluded_from_both_sides` |
| whole-set conflict disclosure | `test_the_conflict_disclosure_names_the_losing_side` |
| method caveat (always on) | `test_the_method_caveat_is_always_present` |

### Gates at close

```
ruff check        All checks passed                 (src, tests, scripts, tools)
ruff format       100 files already formatted
mypy --strict     no issues in 100 source files
pytest -q         925 passed, 1 skipped, 0 failed
mutation sweep    25 / 25 killed, 2 inert by design  (scripts/mutation_inflation_convergence.py)
live check        7 sections, 522 real months, PASSED
```

### What is NOT validated

- **The verdict is heuristic, not calibrated.** `is_heuristic_not_calibrated=True`
  is passed unconditionally; the 0.6/0.8 thresholds are the specification's
  literals, not fitted values. The classifier says *how much the measures agree*,
  not *whether they are right*.
- **The family assignment is a judgement, not a measurement.** Whether
  `sticky_price_cpi_direction` belongs to `BLS_CPI` rather than to a distinct
  family is a decision encoded in `_INPUT_FAMILIES`. `median_cpi_direction` was
  deliberately **assigned to `BLS_CPI`, not `DALLAS_FED`**, even though a Dallas
  Fed series exists, because the Cleveland median is BLS-survey-derived — but a
  reasonable reviewer could assign it otherwise, and the confidence number moves
  if they do.
- **`independent_families ∈ {2, 3}` only.** The function has never been run with
  four or more families, because the input space cannot produce them. Any future
  widening of the required set changes this.
- **The 522-month sample ends at the FRED edge, not at the economic edge.**
  `2026-06` is the latest conflict and is close to the sample end; whether it
  resolves as the series revise is not something this check can know.
- **`supercore_direction` is still absent**, so the classifier's coverage of the
  core-inflation spectrum is incomplete — and it is incomplete in the direction
  that matters, since supercore is the measure the Fed most often cites.

---

## Module 1 — `check_trilemma_tension` (D-048)

**Tier 3 · 6 / 15.** The first Tier 3 function whose inputs are *not* data at all:
three manually-classified booleans about a country's institutional structure, two
policy directions, and two reserves readings. It returns an ordered severity —
`NO_TENSION` → `TRILEMMA_TENSION` → `TRILEMMA_VIOLATION` → `CRITICAL_PEG_STRESS` —
and it is a **structural** check: it reports that a configuration is impossible or
under stress, never a probability that a peg breaks, and it carries no timing.

### The headline finding: silent during its own worked example

§15.20-A's rule is a **3-month** reserves change below −10%. §18.1's reference
episode for the whole mechanism is **Black Wednesday, 1992-09-16**. On
`TRESEGGBM052N` the UK's reading in that very month is:

| measure | 1992-09 | threshold | fires? |
|---|---|---|---|
| 3-month change | **−5.37%** | −10.0% | **no** |
| 1-month change | −7.25% | −7.0% (added) | **yes** |

The specified threshold does not fire during the crisis it was written to detect;
the breach first appears the following month. **A detector that reports "no
tension" during the event is not a detector**, so D-048 adds the 1-month
acute-break test alongside the specified 3-month trend test. Both thresholds are
config-driven and both are published on every result.

The two tests are **not nested**, verified on real history rather than asserted:

| series | months where ONLY 3mo fires | months where ONLY 1mo fires |
|---|---|---|
| UK `TRESEGGBM052N` | 53 | 30 |
| Korea `TRESEGKRM052N` | 35 | 14 |

Neither subsumes the other, which is *why* the acute branch tests the 1-month
measure rather than "either" — a rule that admitted both would fire far more
often without adding a mechanism.

The three reference episodes, reconfirmed live:

| episode | 3mo | 1mo | severity |
|---|---|---|---|
| GB 1992-09 (Black Wednesday) | −5.37% no breach | −7.25% **breach** | CRITICAL_PEG_STRESS |
| KR 1997-09 (trend phase) | −10.80% **breach** | −2.30% no breach | CRITICAL_PEG_STRESS |
| KR 1997-11 (acute phase) | −21.66% breach | −20.04% breach | CRITICAL_PEG_STRESS |

### Where the increments diverge from §15.20-A

1. **Confidences.** The specification returns `0.7 / 0.6 / 0.4 / 0.8`. §22.8
   forbids hardcoded confidence, and the replacement is not just different
   numbers — it is **flat across severities**, because severity is a fact about
   the world and confidence is a fact about the measurement. A test asserts the
   flatness and the absence of the four literals.
2. **The `or 0` trap.** `(reserves_trend_pct_change_3mo or 0) < -0.10` makes an
   **absent** reading into a measured zero, i.e. evidence of calm from no
   evidence. Replaced with an explicit `is not None` guard; absence is disclosed
   and is inert in both directions.
3. **Datetimes.** `utc_now()`, per ruff `DTZ`.

### The cadence finding

The live check's **gap-free assertion failed on its first run**:

```
TRESEGGBM052N is not gap-free monthly: distinct month-gaps [1, 12]
```

| series | observations | monthly | excluded | monthly from |
|---|---|---|---|---|
| `TRESEGGBM052N` | 843 | **837** | 6 | 1956-12 |
| `TRESEGKRM052N` | 842 | **836** | 6 | 1956-12 |
| `TRESEGIDM052N` | 700 | **668** | 32 | 1970-12 |

The UK and Korean series are **annual before 1956-12**; Indonesia is annual to
1964-11 and then quarterly to 1969-11. Every threshold here names a number of
months, so a "3-month change" computed across the annual prefix spans **years**.
The check now isolates the monthly span, asserts it is gap-free, excludes the
prefix and **says what it dropped**. Base rates re-measured over the monthly span
only:

| series | 3mo | 1mo |
|---|---|---|
| UK (834 months) | **10.6%** | **7.8%** |
| Korea (833) | 7.9% | 5.4% |
| Indonesia (665) | 6.2% | 8.4% |

Both base rates travel with every result (D-029). The 3-month rate at 10.6% is
the important number: **"reserves are depleting" is a precondition, not a crisis
signal.**

### The structural limitation, stated plainly

§22.3 makes this a US-only build and the dollar floats. `has_fixed_or_managed_fx`
is therefore never true for `us`, `all_three` is never true, and the function
**can only ever return `NO_TENSION`** on its supported path.

This is recorded rather than hidden, and five separate things keep the function
real:

1. the guard is the same §22.3 guard `output_gap_from_snapshot` uses — it raises
   for `gb`, `kr`, `id`, `de`, `jp`, `US` and `""`;
2. the full four-severity escalation is exercised through the **public** function,
   so the wiring from `TrilemmaInputs` to `_depletion_severity` is under test;
3. the crisis logic is **validated live** against the UK's 1992 and Korea's 1997
   history, which is where §18.1 and §18.7 are actually observed;
4. every threshold and base rate is published on the result;
5. `test_us_cannot_reach_anything_but_no_tension` walks the whole admissible US
   input plane and asserts `NO_TENSION`, so making it reachable on `us` requires
   changing that test and therefore stating why.

### Input contract

| field | type | required |
|---|---|---|
| `country` | `str` | yes — must be `"us"` |
| `has_fixed_or_managed_fx` | `bool` | yes |
| `has_free_capital_movement` | `bool` | yes |
| `claims_monetary_independence` | `bool` | yes |
| `domestic_policy_direction_needed` | `Literal["easing","tightening"] \| None` | no |
| `peg_defense_direction_required` | `Literal["easing","tightening"] \| None` | no |
| `reserves_trend_pct_change_3mo` | `float \| None` | no |
| `reserves_trend_pct_change_1mo` | `float \| None` | no |
| `data_quality_flags_present` | `bool` | no, default `False` |

`extra="forbid"`. **`None` is not a conflict**: an unassessed direction is not
"the peg requires the opposite", and treating it as one would make every
unassessed input escalate.

### Output

`value` carries ten keys: `severity`, `all_three_legs_claimed`,
`direction_conflict`, `reserves_depleting_3mo`, `reserves_breaking_1mo`,
`reserves_trend_pct_change_3mo`, `reserves_trend_pct_change_1mo`,
`depletion_threshold_3mo`, `break_threshold_1mo`, `base_rates`.
`source_family` is `MANUAL_ASSESSMENT` — which is what stops a downstream
convergence count from treating three asserted booleans as three independently
sourced pieces of evidence.

### Gates at close

```
ruff check        All checks passed                 (src, tests, scripts, tools)
ruff format       103 files already formatted
mypy --strict     no issues in 103 source files
pytest -q         975 passed, 1 skipped, 0 failed
mutation sweep    60 / 62 killed, 0 pattern-misses, 2 proven-inert
                  (scripts/mutation_trilemma.py, run FOREGROUND — scope: whole repo)
live check        PASSED — 3 series, 3 episodes, base rates reconfirmed to 0.000 drift
```

### What is NOT validated

- **The three trilemma legs are manual classifications.** No route for any of
  them exists or can: "does this country manage its exchange rate" is a
  legal-institutional fact, not an observation. **A misclassified peg makes every
  severity wrong at once, and no data can disagree with the caller (O-28).**
- **The US path is untestable on real data.** The function's supported country
  cannot reach past `NO_TENSION`, so its crisis logic is validated on **other
  countries' history through a fixture whose label is `us`**. The label is what
  the guard requires; it is not a claim about what was measured.
- **The 3-month base rate's numerator mixes mechanisms.** On the UK the
  2016-09/10/11 cluster is **Brexit** — an earlier-than-expected-exit episode,
  not a defense of the ERC peg. A rate whose numerator spans two event types is
  a claim that has to be said out loud, and the model repeats it on every output.
- **The thresholds are not calibrated.** `−10%` is §15.20-A's literal; `−7%` is a
  fitted assumption. Neither is fitted against realized peg-break outcomes.
- **A structural check carries no timing.** The trilemma says a configuration
  cannot persist. It says nothing about *when* it ends, and nothing here should be
  read as a forecast of a break.

### Registry entries (D-030 three-part change)

Three series were registered under the `trilemma_reserves_*` group. They are
**provenance-only** — `not_a_snapshot_field: true` — because the trilemma **legs**
are manual (O-28), so no `MacroDataSnapshot` field carries them; the third part of
D-030's change is therefore the registry entry plus its verification record, not a
snapshot field.

| entry | symbol | raw obs | monthly | excluded | base-rate window | verified value |
|---|---|---|---|---|---|---|
| `trilemma_reserves_gb` | `TRESEGGBM052N` | 843 | 837 | **6** | 834 | 169355.6608 @ 2026-08-01 |
| `trilemma_reserves_kr` | `TRESEGKRM052N` | 842 | 836 | **6** | 833 | 421968.5648 @ 2026-07-01 |
| `trilemma_reserves_id` | `TRESEGIDM052N` | 700 | 668 | **32** | 665 | 133983.0891 @ 2026-07-01 |

**Both `verified_value` columns for GB and KR were wrong in the first draft** —
written from recollection (`93221.49`, `411301.2`) rather than fetched. The
entries were corrected against the provider and re-verified: all three now match
the live source to `< 1e-6` on both value and observation date. See the D-048
amendment and lesson 33.

**The exclusion SHAPE differs, not just its size.** GB and KR change cadence once
(seven annual Decembers 1950-12..1956-12, of which six are dropped and the last
retained, then monthly). Indonesia changes **twice**: 16 annual points
(1950-12..1964-12), then a continuous quarterly block (1965-03..1968-12), then
monthly. An earlier description of Indonesia's cutovers was wrong by four years.
See lesson 34.

---

## Module 8 — `inversion_probability_adjustment` (D-049)

**Tier 3 · 7 / 15.** The first Tier 3 function that produces a **probability**. It
takes a current slope, a duration, and a caller-supplied base rate, and returns
the 12-month-forward recession probability adjusted upward for the depth and the
length of the inversion. It is an **adjustment on a measured base rate**, not a
model: the specification's own structure is a heuristic multiplier, and it is
labelled as one on every output.

### The specification's base rate disagrees with the data by 3.1x

§15.20-B supplies `base_rate = 0.15`. Measured over a 592-observation
positive-`DGS10 − DGS2` history (1976-06 … 2026-09) against `USREC`:

| conditioning set | 12-month-forward recession rate | n |
|---|---|---|
| unconditional | 0.209 | 592 |
| curve **not** inverted | 0.157 | — |
| curve inverted | **0.489** | — |

`0.15` is not a rounded `0.489`; it is **3.1×** low. The literal was **not
shipped**. The base rate is now a **required input with no default**, so a caller
must supply a number and cannot silently inherit one that the data contradicts.
The specification also hardcodes the two confidences (`0.3` / `0.35`), which
§22.8 reserves for `compute_confidence()`; the function calls it with bare
`ConfidenceInputs()` and returns **0.700 flat across every branch** — D-048's
pattern, where severity is a fact about the world and confidence is a fact about
the measurement.

### Two dimensions, two different shapes

```
depth is MONOTONE      -0..-25bp 0.412   -25..-50bp 0.417
                       -50..-100bp 0.552  -100bp+   0.857
duration is HUMP-SHAPED  0-4wk 0.250   4-13wk 0.286   13-26wk 0.412
                         26-52wk 0.769  >=52wk  0.520
```

**Depth is monotone in the outcome; duration is not.** The configured 26-week cap
sits **exactly at the 26-52 week peak**, so the mechanism never enters the region
where its own monotonicity assumption is contradicted by the data. The `>=52wk`
bucket is dominated by the 2022-07 … 2024-09 inversion (**113 weeks**), which has
**not** been followed by a recession — so the check runs a **censoring control**
that excludes any bucket whose 12-month window is truncated. The hump survives
the control. Recorded as an open calibration item, not absorbed by the cap.

### Reference episodes (all four reproduce to the day)

| episode | window | length | min slope |
|---|---|---|---|
| `asian_1998` | 1998-05-26 … 1998-07-27 | 8 wk | −7 bp |
| `dotcom_2000` | 2000-02-02 … 2000-12-28 | 47 wk | −52 bp |
| `gfc_2006` | 2006-06-08 … 2007-06-05 | 51 wk | −19 bp |
| `recent_2022` | 2022-07-06 … 2024-09-05 | **113 wk** | −108 bp |

**These dates are the daily segmentation's output, not the first probe's.** The
first draft used monthly-resolution cutovers and disagreed with the checker by up
to six weeks; the checker was right, because a segmentation of a *daily* slope
series is what the config dates are claims about. The correction is recorded in
the config docstring rather than silently applied — and three *other* stale
figures from the first probe were corrected in the same pass (see below).

### Warning-path coverage

| Branch | Trigger |
|---|---|
| illustrative-heuristic disclosure | `test_the_illustrative_warning_is_always_present` |
| saturation + the measured hump quoted | `test_a_saturated_input_quotes_the_measured_hump` |
| duration past the cap | `test_duration_past_the_cap_says_so` |
| **ceiling clamped this result** | `test_the_ceiling_warning_fires_only_when_it_binds` |
| no inversion → the prior verbatim | `test_a_non_inverted_curve_returns_the_prior_unchanged` |
| every warning path is reached by some test | `test_inversion_adjustment_every_warning_path_is_triggered_by_some_test` |

### One dead branch was found in my own code, by relocating it

`_inversion_warnings` shipped with `if base_rate > 0.0 and ceiling <= 0.80:`. The
first clause is **always true** (`gt=0.0` is validated on the input) and the
second is **config-derived**, so the branch fired on every inverted call and
described a clamp **that had not happened**. It is D-037's dead-branch class — a
guard whose text promises discrimination and whose predicate cannot discriminate —
in the function rather than in the specification. Fixed by driving it from a
`ceiling_binding` parameter computed at the call site as `adjusted < uncapped`,
and pinned by the binding/non-binding pair above.

### A field and a property cannot share a name in pydantic

`YieldCurveSettings` declared `duration_saturation_weeks` as **both** a model
field and a `@property`. Pydantic 2.13 accepted the class and resolved
`settings.duration_saturation_weeks` to the wrapped **`CalibratedValue`**, so the
first live call failed with
`TypeError: unsupported operand type(s) for /: 'int' and 'CalibratedValue'`.
Renamed to `duration_saturation_cap` (field) / `duration_cap_weeks` (property).
Two structural tests now guard the class: one sweeps **the whole settings tree**
for any field/property collision, and one asserts the accessors the module reads
all exist and are floats. The comment I first wrote explaining the cause named the
wrong mechanism and was corrected.

### Gates at close

```
ruff check        All checks passed                 (src, tests, scripts, tools)
ruff format       105 files already formatted
mypy --strict     no issues in 105 source files
pytest -q         1009 passed, 1 skipped, 0 failed
mutation sweep    67 / 68 killed, 1 inert by design  (scripts/mutation_yield_curve.py)
live check        6 sections, 592 real months, PASSED (drift 0.0005)
```

### What is NOT validated

- **The adjustment is heuristic, not calibrated.** `max_adjustment = 0.35`,
  `depth_saturation = 100bp` and `duration_saturation_cap = 26wk` are the
  specification's literals carried through a `CalibratedValue` envelope with
  `calibration_status: uncalibrated_illustrative`. They are **not fitted** to the
  bucket table above, and the bucket table is not strong enough to fit them: the
  26-52 week bucket holds 26 observations.
- **The duration dimension is not monotone in the data, and the function treats it
  as if it were.** The cap means the contradiction is never reached, which makes
  the output well-behaved and the assumption untested. Disclosed on every
  saturated output and tracked in OPEN_ISSUES.
- **The `>=52wk` bucket is censored.** Its 0.520 comes partly from episodes whose
  forward window has not closed. The control agrees, but the control itself
  discards observations rather than repairing them.
- **The base rate is a single US sample.** `USREC` is NBER's ex-post dating, so
  the base rate is **revised history**, not a real-time signal; a real-time
  vintage store would produce a different and probably lower number (O-13).
- **A probability is not a forecast of the current episode.** The function never
  says "this inversion will cause a recession"; it says the historical rate under
  comparable conditions was X, adjusted by a heuristic. The reference episode
  `recent_2022` is evidence for the *hump finding*, not for a prediction.

---

## Module 12.2 — `four_pillar_scorecard` (D-050)

**Tier 3 · 8 / 15.** The capstone of Module 12: four directional pillar reads
(growth, inflation, financial conditions, policy gap) in, one convergence verdict
out — `NO_SIGNAL` / `CONFLICTED` / `HIGH` / `MEDIUM` / `LOW`. It answers *"do the
pillars agree, and is that agreement backed by independent evidence?"* and never
answers *"should we trade"*; `CONFLICTED` **blocks** construction elsewhere and
this function only reports it.

It is the §15.19-D caller with the most consequential failure mode: a mis-scored
`CONFLICTED` is a false green light on a mandatory block, and a mis-scored `HIGH`
is confidence in redundant evidence.

### Five specification defects

Four were measured before a line was written. The fifth was found by the mutation
sweep, and it is a defect in **the repair** — the first time this project has
produced one.

| # | defect | measured |
|---|---|---|
| 1 | `CONFLICTED` gate narrower than its own guard (`growth × inflation < 0`) | **50** opposed, **18** caught, **32 missed** |
| 2 | `agree_frac >= 0.9` and `>= 0.75` are the same test | nothing lands in `[0.9, 1.0)` |
| 3 | §15.19-D undischarged — `independent_source_families: int` | a caller passing `4` gets `HIGH` |
| 4 | four hardcoded confidences `0.2/0.75/0.5/0.3` | confounds severity with confidence |
| 5 | **the repair's dissent thresholds are inert** | see below |

#### Defect 1 — the gate did not cover the reads it exists to block

The specification computes "some pillar tightens, some eases" and then requires an
**additional, narrower** condition before returning `CONFLICTED`. The 32 misses
include every configuration where growth and inflation agree while conditions and
policy oppose — the *"bad news is good news"* split, and precisely the read a
trade must not be built on. Since the specification's own warning text calls
`CONFLICTED` a mandatory block, each miss is a **false green light**.

Repair: **the gate is the guard.** `opposed = up > 0 and down > 0` is computed
once and used for the verdict; the product condition is deleted.

#### Defect 2 — the thresholds were not two thresholds

`agree_frac`'s denominator is the **non-neutral** count:

```
n=1  {1.0}            n=3  {0.667, 1.0}
n=2  {0.5, 1.0}       n=4  {0.5, 0.75, 1.0}
```

No reachable value lies in `[0.9, 1.0)`, so `>= 0.9` ≡ `>= 1.0`, and `0.9 / 0.75`
separates exactly one configuration. The consequence the literals hide: **one
dissenter out of three scored `LOW` while one out of four scored `MEDIUM`.**

Repair: gates as **dissent counts** (0 for `HIGH`, ≤ 1 for `MEDIUM`), with the
fraction, the dissent count **and** an agreement **margin** all published so the
gates are auditable from the output.

#### Defect 3 — §15.19-D, the assigned audit

The specification takes the family count as a **caller-supplied int**, which the
function cannot verify — so a caller can pass the raw signal count (`4`) and be
believed. Repair changes what the function *asks for*: it takes tagged
`PillarRead`s and **calls `count_independent_families()` itself**, making the
error unrepresentable rather than merely discouraged. Measured:

```
unanimous (1,1,1,1):  4 families -> HIGH   0.700
                      2 families -> MEDIUM 0.600
                      1 family   -> LOW    0.500
```

**The pillars are not the vote; the families are.**

#### Defect 5 — the repair made its own thresholds inert

Found by the sweep: three mutants survived the whole suite (`MX2a` HIGH ceiling →
MEDIUM leaf, `MX2e` MEDIUM ceiling → HIGH leaf, `MX2f` MEDIUM ceiling 1 → 2).

`CONFLICTED` is tested **first** and consumes every opposed read. A non-opposed
read has all non-neutral pillars pointing the same way, so
`max(up, down) == n` and `dissent = n - max(up, down) == 0` — **always**. Therefore
`dissent <= 0`, `<= 1` and `<= 2` are the same predicate on every reachable input:
**the dissent ceilings cannot bind, and `MEDIUM` is reached through the family
floor.** The `LOW` *"weak agreement"* branch is **unreachable by construction**.

**Decision: keep the gates, document that they cannot bind, and add tripwires.**
Deleting them would freeze the current gate *order* as permanent; if the
opposition test ever moves below the dissent gates the thresholds become live and
a deleted branch is a silently missing verdict. Two tests hold the line:
`test_no_read_reaches_the_dissent_gates_with_a_dissenter` (reachable dissent set
past the gate is exactly `{0}`) and
`test_the_weak_agreement_low_branch_is_unreachable_by_construction`.

**This is D-047's "declared, unreachable" class, found inside the repair.**

### The measurement, and two shares that disagree

The live check derives all four pillars from FRED (`UNRATE`, `PCEPILFE`,
`DGS10`, `DFF`) rather than supplying them, because §20.11's inputs are four bare
ints — a contract under which every live check is a tautology. Over **761 real
monthly readings** (1962-01 .. 2026-07):

```
VERDICT DISTRIBUTION over 761 real monthly readings
  HIGH          251   33.0%
  CONFLICTED    504   66.2%
  NO_SIGNAL       6    0.8%

CONFLICTED in HISTORY   66.2%   vs in the INPUT SPACE  61.7%
```

The config's `0.617` is **measured by enumeration** (567 configurations, 350
`CONFLICTED`) and is a claim about the classifier on *arbitrary* inputs. The
history figure is what real pillars look like. They **disagree, and the history
share is higher** — real pillars are correlated, so genuine splits are more
common than the independent-input model predicts, not less. Both numbers travel
on every `CONFLICTED` output.

### The all-neutral state is real, and an earlier revision forbade it

Real history produces **6 all-neutral readings** (0.8%): `1963-05`, `1964-08`,
`2013-10`, `2014-07`, `2015-11`, `2017-10`. An earlier revision of the input
model **refused** the all-neutral state outright; the live check failed on
exactly those months, which is how it was found. The fix is an explicit
`allow_all_neutral` opt-in — the guard exists to stop "we see nothing" being
reached by an **empty default**, not to make a state the data produces
unrepresentable. The docstring's original claim that `NO_SIGNAL` was "dead code
through the public API" was corrected.

### Input contract

```python
class PillarRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    direction: Literal[-1, 0, 1]   # a magnitude is a category error
    family: EvidenceSourceFamily   # Module 13 provenance
    source: str = Field(min_length=1)

class ScorecardInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    growth: PillarRead
    inflation: PillarRead
    financial_conditions: PillarRead
    policy_gap: PillarRead
    allow_all_neutral: bool = False   # opt-in, not a refusal
```

The specification's fifth parameter `independent_source_families: int` is
**removed**, and `test_the_family_count_is_measured_not_accepted` asserts its
absence from the signature — the count is derived, so accepting one would
re-open defect 3.

### Output

```
classification         NO_SIGNAL | CONFLICTED | HIGH | MEDIUM | LOW
agreement_fraction     larger side / non-neutral count
agreement_margin       |up - down| / non-neutral count
dissenting_pillars     non-neutral - larger side
non_neutral_pillars    n
independent_families   MEASURED (not accepted)
family_names           sorted distinct family names
pillar_directions      all four, neutrals included
```

Confidence comes from `compute_confidence()` and is **flat across verdicts at a
fixed family count** — the D-048/D-049 pattern. `CONFLICTED` is not less certain
than `LOW`; it is a differently-shaped fact about the same quality of input.

### Warning paths

| path | fires on |
|---|---|
| illustrative-thresholds | every output |
| `CONFLICTED` blocks construction + base-state share | `CONFLICTED` |
| `NO_SIGNAL` is not `LOW` | all-neutral |
| agreement high, independence low | `agree_frac >= 0.75` and families < HIGH floor |
| fewer than four non-neutral pillars | `0 < n < 4` on a non-`CONFLICTED`/`NO_SIGNAL` read |

### Gates at close

```
ruff check        All checks passed                 (src, tests, scripts, tools)
ruff format       109 files already formatted
mypy --strict     no issues in 109 source files
pytest -q         1060 passed, 1 skipped, 0 failed
mutation sweep    81 / 84 killed, 3 proven-inert    (scripts/mutation_scorecard.py)
live check        761 real months, PASSED            (scripts/live_scorecard_check.py)
```

*Superseded by D-051:* re-measured at **84 / 87 killed** after the census
correction added three mutations, all killed by the two new tests. The
`live_scorecard_check.py` assertion that the four-family read reports 4 families
was itself stale — it had passed only because the census was counting neutrals —
and now asserts the count against the number of **directional** pillars.

### The sweep's survivor classes

| class | mutants | resolution |
|---|---|---|
| thresholds that cannot bind | `MX2a`, `MX2e`, `MX2f` | proven inert, with proofs, + 2 tripwire tests |
| output-observable, untested | `MX2m`, `MX3g` | 2 tests added |
| config accessors copy their own literal | `CX1`–`CX4` | 1 test, asserting against a **perturbed** settings object |
| published keys and prose unread | `MX4l`, `MX4m`, `MX4p`, `MX4q`, `MX5f`, `MX6g`, `MX6h` | 5 tests |
| `margin` indistinguishable from `fraction` | `MX4m` | 1 test on a **split** read |

`check_targets` refused the **first run** with two ABSENT targets — my own target
strings had been rewritten while fixing line lengths inside the sweep file. The
tree was verified restored after both full runs (`check_targets` clean,
`_applied_mutations` empty).

The `CX1`–`CX4` class is the most valuable catch after defect 5. **An accessor test
that asserts the value the accessor returns today cannot distinguish a live config
read from a hardcoded copy of the same number** — all four accessors were
replaceable by their own values with the suite green, which makes §22.8's "no
hardcoded values" rule toothless in the exact component whose job is to hold the
tunable. The fix asserts against a **perturbed** object, so the read is exercised
rather than the number.

### What is NOT validated

- **The family assignment is a judgement, not a measurement.** No FRED series
  carries a source-family label; the four-way mapping in the live check is a human
  decision, printed as a table so a reviewer can disagree with any row. §15.19-D's
  floor of 3 is therefore `uncalibrated_illustrative` and says so in its `note`.
- **The pillar bands are illustrative.** `0.1 / 0.05 / 0.10 / 0.10` are config
  leaves with no labelled outcome to fit against.
- **The two dissent ceilings cannot bind** (defect 5). They are kept as
  documentation of intent with tripwires, not as live thresholds. A reader
  auditing the config should treat `medium_dissent_ceiling` as **inert**.
- **Whether the verdicts are right is not tested.** The check proves the wiring
  produces a verdict from real data with the expected sign and family behaviour;
  it cannot say a `CONFLICTED` read predicted anything.
- **`LOW` is conflated with "insufficient" in the family-floor branch.** A read
  with four unanimous pillars over one family and a read with genuinely weak
  agreement both return `LOW`; only the reason string distinguishes them, and the
  second reason string is unreachable (defect 5). Tracked in OPEN_ISSUES.
- **CORRECTED BY D-051: the census counted neutral pillars.** See the Module 12
  section below. This section's numbers were measured before the correction; the
  distribution over real history is unchanged by it (the defect is only reachable
  with a neutral pillar present, and the scorecard's live population is
  dominated by all-directional reads), but the family counts on any
  neutral-bearing read were overstated.


## Module 5.6 — `cross_asset_transmission` (D-052)

**Tier 3 · 10 / 15.** The **largest input space of the six remaining Tier 3
functions**: a cross-market matrix of same-day moves on the nominal 10-year yield,
the breakeven, the **derived** real leg, and two equity reads — reduced to
directional calls on gold, bonds, long-duration equities and the dollar, plus the
`driver_channel` that says which single leg produced them.

It lives in `models/inflation_dynamics.py` beside the Module 3.3 Phillips curve,
because both consume the same inflation-momentum input.

### Seven specification defects

| # | defect | nature |
|---|---|---|
| 1 | `inflation_surprise_bp` declared, listed in `inputs_used`, read by nothing | declared, consumed, unreachable |
| 2 | three published keys derive from **one** predicate | `n` outputs, 1 cause |
| 3 | `usd` was a sentence describing an effect, not a direction | prose where a value belongs |
| 4 | the gold rule's stated trigger is **not** its implemented trigger | prose ≠ code |
| 5 | `surprise_driver: str` with an `else` fallthrough | a typo lands in a real branch |
| 6 | `x > 0 else "up"` reports an **unchanged** yield as a rise | a two-way map over a three-way fact |
| 7 | `confidence=0.45` hardcoded | §22.8 reserves confidence |

**Defect 4 is worth stating in full.** §20.5's gold paragraph says gold falls when
the **nominal** yield rises. Its own next sentence describes the case that breaks
the naive reading — a nominal rise driven by **breakeven** repricing with the real
yield *falling*, the "hot CPI, gold up" scenario. The implemented rule keys on the
**real** leg. That is the correct economics and the **opposite** of the prose, so
the shipped form makes the actual trigger inspectable (`driver_channel`) rather
than leaving a reader to infer it from the direction of a call.

**Defect 6 is reachable on real data.** A same-day cross-asset read sees a flat
leg routinely — a holiday, a stale print, a rounded feed — and
`"up" if change > 0 else "down"` calls every one of them a rise.
`_leg_direction(change_bp, flat_band)` is a three-way map with the flat case
tested **first**, and four mutations (`M3.1`, `M3.2`, `M4.1`, `M4.2`) pin the order.

### The composition defect, and the third kind of inertness

The user's brief asked for a cross-check from the start *"since
`cross_asset_transmission`'s input space is the largest of the remaining six and
carries the most risk of the D-050 composition defect — correct gates whose
ordering makes one of them inert."* The hazard was present.

The driver split tests `both_channels` **before** `real_driven`, so any input that
would reach `real_driven` and also satisfies the both-channels condition is
consumed by `both_channels` first. Two mutants survived:

| mutant | rewrites | why it survives |
|---|---|---|
| **M2.7** | `real_driven` is swallowed by `both_channels` | the branch is unreachable — every input reaching it is consumed earlier |
| **M2.8** | `breakeven_driven` is swallowed by `neither_channel` | the mirror on the other leg |

Neither was recorded as a weak test. The prover **enumerates** the admissible
space — 643 200 cases for each, **0 differences** — and the proof re-executes on
demand via `--probe-inert`.

**A third kind of inertness was named here.** D-050 established *threshold*
inertness (differs only on an unreachable input) and *composition* inertness (an
earlier gate consumes every differing input). **M9.2** — "published value key
`long_duration_growth_equities` altered" — is neither: it rewrites a **key name**,
and the key's consumer resolves it under a second alias, so the mutant changes the
namespace and not the value. Three kinds, with three different remedies; the
prover reads the three branches out of the source because a name fact is not a
domain fact.

### Published `value` — twelve keys

```
nominal_change_bp           the leg the function is actually given
breakeven_change_bp         the second given leg
real_change_bp              DERIVED from the identity, not supplied
driver_channel              which single leg produced the three calls
gold_call                   DOWN_ON_NOMINAL_RISE (measured base rate published)
bonds                       the one direction the equity keys share
long_duration_growth_equities   — one predicate with `bonds`
growth_equities             — one predicate with `bonds`
usd                         UNRESOLVED by design (a regime fact, no input)
surprise_driver             Literal
measured_shares             the four-way split, published beside the call
confidence                  from compute_confidence(), never a literal
```

Confidence comes from `compute_confidence()` with
`source_independence_count=distinct` — the measured family count from
`count_independent_families()` (§15.19-D), so the three keys sharing one predicate
count as **one** vote.

### Config — `TransmissionSettings`

`real_driven_share`, `breakeven_driven_share` (0.66 each), `trivial_move_bp`,
`measured_gold_down_on_nominal_rise_share` (`0.7556`), `measured_breakeven_negative_share`
(`0.2652`), with a `_check_change_signs_are_not_degenerate` validator.

**The two `measured_*` leaves are the increment's most transferable finding.** They
shipped as `0.7779` and `0.2754`, and the live check's recomputation shows
**no population reproduces either** (monthly 0.7556 / 0.2652, daily gold 0.8846).
Both were written from the authoring probe rather than fetched in the same breath —
**O-30's class, in the config layer instead of the registry.** Every gate passed
while they were wrong: the unit tests read the same config the code reads, the
registry loaded, and the population lived in a **note** that nothing reads. The
live check's **>0.5pp** drift bar is the only mechanism in the tree that can catch
this, and it is now a load-bearing assertion rather than a formality. See **O-38**.

### The live check

Eight steps; the first and the last are the instructive ones.

1. **It proves the identity is exact before relying on it.** `DGS10 − T10YIE −
   DFII10` over **5 931** daily observations: max error **0.000000**. So the
   derived real leg is a **restatement** of the observed one, not a proxy.
2. Recomputes and drift-checks every published base rate (bar **0.005**).
3. Re-derives the driver shares and the floor.
4. Reports cadence sensitivity — monthly and daily differ materially, and the
   difference is disclosed rather than averaged away.
5. Runs the function on the latest live repricing.
6. Asserts orientation on **real, opposed** repricings, not synthetic ones.
7. Asserts interior consistency of the shares.
8. **Cross-checks against `inversion_probability_adjustment`** (D-049).

### Why the cross-check is against D-049 and **not** against the observed real yield

The obvious candidate was rejected, and the rejection is the point. Because step 1
shows the identity is **exact**, comparing derived against observed real yield is
**arithmetic**: it cannot fail, so it is not evidence. It is D-027's circularity —
two sides sharing an input — in a new costume.

It was repurposed rather than discarded: the identity is now the **proof that the
derivation is a restatement rather than a proxy**, which nothing else establishes.
The real cross-check runs against a **disjoint** function:

| | `cross_asset_transmission` (D-052) | `inversion_probability_adjustment` (D-049) |
|---|---|---|
| input | the *curvature* of a same-day repricing | a *level* at the short end |
| domain | long-end decomposition | recession probability |
| output | directional asset calls | a probability |
| shared inputs | **none** | **none** |

Agreement between them is therefore evidence rather than tautology. A one-year
window-overlap guard stops the two comparing windows that do not intersect.

### The sweep's harness finding: a wording collision that read as coverage

`M10.3` — "the indeterminate warning is not emitted" — **survived** with a
warning-coverage guard in place. The cause was not a thin test: the guard matched
substrings and `"below the"` occurred in **two** branch texts, so deleting one
branch left the guard matching the neighbour and green.

Fixed by making `_warning_branches()` a dict of **mutually non-colliding** markers
(the indeterminate branch's marker is now `"SPLIT is measurable"`) and adding
`test_the_warning_markers_are_mutually_non_colliding`, which asserts each emitted
warning matches **exactly one** marker. A coverage check satisfiable by a
neighbouring branch's wording is not a coverage check.

### Gates at close

```
ruff check        All checks passed                 (src, tests, scripts, tools)
ruff format       116 files already formatted
mypy --strict     no issues in 113 source files
pytest -q         1168 passed, 1 skipped, 0 failed
mutation sweep    55 / 58 killed, 3 proven-inert, 0 defects
                  (scripts/mutation_transmission.py — 58 mutations, 13 groups)
live check        PASSED — identity exact over 5 931 obs, base-rate drift 0.0000,
                  cross-check against inversion_probability_adjustment
                  (scripts/live_transmission_check.py)
```

### The sweep's survivor classes

| class | mutants | resolution |
|---|---|---|
| `[DEFECT]` | 6 at first run: M6.1, M9.2, M10.3, M11.4, M2.7, M2.8 | three closed with new tests (M6.1, M10.3, M11.4); **M9.2 proven name-not-value inert**; **M2.7/M2.8 proven composition inert** |
| `[inert]` | M2.7, M2.8, M9.2 | in `_EXPECTED_INERT` with **executed** proofs, re-runnable via `--probe-inert`, each with a tripwire test |

The sweep **mis-classified its own inert survivors as `[DEFECT]` on the first run**,
because the classifier tested `mutation.inert_proof` and not membership in
`_EXPECTED_INERT`. Fixed by extending `unexplained` to test
`r.mutation.name not in _EXPECTED_INERT` and adding an `[inert]` print branch.

### What this check cannot validate

- **The driver-share thresholds are illustrative** (`uncalibrated_illustrative`) —
  a four-way split with no labelled outcome to fit against. The measured shares
  travel with the output so a call can be compared against the base state.
- **`usd` is `unresolved` by design** — the dollar's response to a real-yield move
  is a regime fact and the function has no input for it. It does not guess.
- **The surprise is reported, never used** — Defect 1, with a `blocked:` registry
  entry recording four probes and why `T5YIFR`/`EXPINF*YR` are **not** a consensus.
- **Whether the calls predict anything is not tested.** The check proves the
  wiring: the identity, the signs, the units, the cadence, the interior
  consistency, and the agreement with a disjoint function.

### Two honours the increment's brief required

- **The sweep was re-run at close**, not only at authoring — D-051's lesson 43.
  It came back clean (`check_targets` clean, all proofs hold, 55/58/3).
- **The cross-check was built from the start**, per the brief, and it is what
  found the composition defect and indicted the two shipped config values.

---

## Module 12 — `classify_convergence` (D-051)

**Tier 3 · 9 / 15.** The **general** convergence classifier: an arbitrary
`list[ModelResult]` in, one verdict out. It is the shape `build_us_macro_thesis`
(Q7) actually holds — it collects whatever the pipeline ran, so
`classify_convergence([growth, inflation, labor, gap])` is a *list*, not a record
with named fields.

| classifier | input contract |
|---|---|
| `inflation_convergence_classifier` (D-047) | a fixed inflation sub-measure set |
| `four_pillar_scorecard` (D-050) | four pillars addressed **by name** |
| **`classify_convergence`** | **an arbitrary `list[ModelResult]`** |

### Seven specification defects, in four groups

| group | defects | nature |
|---|---|---|
| 1 | 1, 2 | the function does not run, and is order-dependent |
| 2 | 3, 4, 5 | the arithmetic does not express the prose |
| 3 | 6 | the inert-gate composition defect, again |
| 4 | 7 | **introduced by this repair**, found by its own test |

**Group 1.** `count_independent_families()` returns a `ModelResult` (D-046) and
§22.10 compares it to an `int`, so **every call reaching the family gate raised
`TypeError`** — the section's two halves were written against different supplier
versions and had never been run together. And `directions[0]` was still the
reference despite the prose claiming its removal: **132 of 1800** multisets change
verdict under permutation (repaired to **0 of 117**).

**Group 2.** §12 and §22.10 disagree about the denominator (`[+1,+1,0,0]` reads
0.500 vs 1.000); `NO_SIGNAL` is declared first-class and **unproducible** (an
all-neutral read fell through to `LOW`); and `LOW` conflates a unanimous
single-family read with genuinely weak agreement, so the specification's own
"high agreement, low independence" warning could never fire.

**Group 3.** `CONFLICTED` is tested first and consumes every opposed read, so the
reachable dissenter count is exactly `{0}` and the reachable agreement fraction
exactly `{1.0}` — `>= 0.8` and `>= 0.6` are the same test. Kept with tripwires.

**Group 4.** The first draft censused **all** signals. Measured: two directional
signals across two families → `MEDIUM`/0.60; the same two plus three **neutral**
signals from three new families → `HIGH`/0.75, with no new directional
observation. §15.19-D's own failure mode, reached *through* its discharge. The
census now runs over the directional subset and publishes
`families_excluded_as_neutral`.

### The defect it found in a CLOSED increment

The live check cross-checks against `four_pillar_scorecard`. **That assertion
failed on 95 of 761 real months, and the cause was D-050's already-shipped
module**: its `_pillar_census` passed all four pillars — neutrals included — to
the supplier.

```
one directional pillar, 1 family                   -> LOW
the same pillar + 3 NEUTRAL pillars, 4 families    -> HIGH
```

D-050's suite could not see it because every family-count test there used an
all-directional read; the defect is only reachable with a neutral pillar present.
Fixed in this increment: `_pillar_census` now filters to directional pillars, two
tests were added to `test_scorecard.py`, and three mutations were added to its
sweep. The two classifiers now agree on **all 81 cells of the 3⁴ space** and
**761 / 761** real months.

### Published `value` — ten keys

```
classification              NO_SIGNAL / CONFLICTED / HIGH / MEDIUM / LOW
agreement_fraction          numerator = non-neutral count, NOT the whole list
agreement_margin            |up - down| / n — 0.0 on a tie, direction-neutral
dissenting_signals          n - max(up, down)
non_neutral_signals         the denominator
total_signals               the list length, including neutrals
independent_families        MEASURED over the directional subset (§15.19-D)
untagged_signals            provenance unknown -> excluded, not counted
families_excluded_as_neutral  what the census set aside, published so it is visible
directions                  per-signal, in input order
```

Confidence comes from `compute_confidence()` with
`source_independence_count=distinct` — the **measured** family count, so
confidence moves with independence and is flat across verdicts at a fixed count.

### Config — `ConvergenceSettings`

Five `CalibratedValue` leaves (`max_dissenting_signals_high: 0`,
`max_dissenting_signals_medium: 1`, `min_independent_families_high: 3`,
`min_independent_families_medium: 2`, `measured_conflicted_share: 0.6173`) with
five `.property` accessors and a `_gates_must_be_ordered` validator that refuses
inverted ceilings, a negative ceiling, a MEDIUM ceiling above 1, inverted family
floors, and a zero floor.

### Gates at close

```
ruff check        All checks passed                 (src, tests, scripts, tools)
ruff format       113 files already formatted
mypy --strict     no issues in 113 source files
pytest -q         1116 passed, 1 skipped, 0 failed
mutation sweep    53 / 56 killed, 3 classified      (scripts/mutation_convergence.py)
live check        761 months, PASSED, cross-check 761 agree / 0 disagree
                  (scripts/live_convergence_check.py)
```

### The sweep's survivor classes

| class | mutants | resolution |
|---|---|---|
| `[DEFECT]` | 6 at first run: M3.5, M3.7, M5.4, M5.5, M5.7, M7.4 | five closed with new tests; **M5.7 proven inert** |
| `[inert]` | M5.7 | the placeholder lands in the *subtrahend* of a set difference, so it can only remove families; verified equal for every reachable input |
| `[expected]` | M1.3, M4.2 | M1.3 is the **honesty control** (semantically identical, must survive); M4.2 is a comment-only edit |

### Two harness defects the sweep found in itself

- **A test path that does not exist makes `pytest` exit 4, and "non-zero means
  killed" counted it as a kill.** The first run reported a false **56/56**,
  including the control that cannot fail. `check_tests_collect()` now proves the
  selection collects before the sweep runs, and exit 4 is no longer a kill.
- **`check_targets` refused four config targets made ambiguous by the sibling
  `ScorecardSettings` class**, and the scorecard's re-run then refused three of
  its own. Both were fixed by anchoring each target on class-specific context.

### What this check cannot validate

- **The source-family assignment is a human judgement** — no FRED series carries a
  family label. Printed as a table so a reviewer can disagree with any row.
- **The family floors are illustrative.** §15.19-D's example gives 3, but no
  labelled outcome exists to calibrate it from; it stays
  `uncalibrated_illustrative` and says so.
- **Whether a verdict predicts anything is not tested.** The check proves the
  wiring: the input shape, the signs, the family behaviour, the published
  quantities, and the agreement between the two classifiers.
- **The MEDIUM dissent ceiling cannot bind** while `CONFLICTED` is tested first.
  Kept as documentation of intent with a tripwire, and disclosed in its own
  config `note`.

---

## Module 3.6 — `project_inflation_trajectory` (D-053)

**New model module.** `src/macro_engine/models/inflation_trajectory.py` — one
function and its input contract, sitting beside the Module 3.3 Phillips curve
because both consume the same labor-slack score.

```
project_inflation_trajectory(inputs: InflationTrajectoryInputs) -> ModelResult
```

### What it does

§16.2's projection in one line:

```text
change_pp = beta * score * fiscal_scale
```

where `score ∈ [-100, +100]` is the labor-slack score (positive = tight), `beta`
is a configured coefficient, and `fiscal_scale` is `1.0` or the §18.6 active-fiscal
multiplier. The sign is then mapped to `TrajectoryDirection` against a configured
band.

The interesting question was never "does this compute"; it was **"what are these
three numbers measurements of"**, and the answer took the whole increment.

### The seven specification defects

| # | Defect | Kind |
|---|---|---|
| 1 | §16.2 negates **twice** — `slack = -s/100`, `pc = -beta*slack` — so the negations **cancel** and the projection is **positive** in the score | sign |
| 2 | `beta`'s **estimand is never named**; the surrounding prose discusses it with a band, which is a **level** bound, so a *change* coefficient was reasoned about as a *level* spread | unnamed estimand |
| 3 | The band and `beta` are **not independent** — the band's score-width *is* `band_pp / beta` | dimensional coupling |
| 4 | §16.2's own values make **`stable` the base state at 79.1%** | base state |
| 5 | `fiscal_response_active` is a §18.6 flag used as a **binary gate**, not the §18.6 **multiplier** | flag vs magnitude |
| 6 | `growth_corroboration`'s two agreement branches carry **one** evidential content | collapsed states |
| 7 | §16.2's sketch returns a **literal confidence** | §22.8 |

**Defect 1 is the one that proves §21.0's discipline.** My first implementation
followed the prose literally and wrote `beta * (-score)`. The config-load smoke
test passed, mypy passed, **every unit test I had written passed** — because
`_change_pp` was my own expression factored into a helper, so each test compared
the function to its own misconception. The first *functional* run, on a score of
`-100` (the loosest possible labor market), returned `reaccelerating`. The
substitution is now in the docstring:

```text
pc = -beta * slack = -beta * (-score/100) = +beta * score / 100
```

**Defect 3 is the increment's finding,** and it generalises beyond this function.
Dividing the band comparison through by `beta`:

```text
reaccelerating  ⟺  beta*score*fiscal_scale >  upper_pp  ⟺  score >  upper_pp / beta
decelerating    ⟺  beta*score*fiscal_scale <  lower_pp  ⟺  score <  lower_pp / beta
```

so the two config leaves jointly fix the **partition** and, separately, the
**slope** — and neither can be validated against the other. **A parameter whose
value is only defined relative to another parameter is not a parameter** (lesson
48). The repair gives each its own estimand and adds
`test_the_band_and_beta_are_independent_config_values`.

**Defect 4 is D-047's base-state failure in a module with no structural relation
to D-047**, and it is a **new sub-shape**: all three members of
`TrajectoryDirection` **are** reachable, so D-045a's reachability enumeration
passes — yet the classifier is effectively two-member. Reachability cannot catch
this; the base-rate measurement can.

### The estimator correction — 7×, caught by the live check

The live check's **first run failed**. Its first estimator re-measured `beta` from
the **band corners**, giving `-0.02451` against a configured `+0.043`. It was
wrong in two ways at once (defects 2 and 3): it measured a **contemporaneous level
spread** rather than a forward-change coefficient, and it partly read back the very
configuration it was meant to test.

Re-derived from the estimand the function actually uses — the OLS slope of the
**6-month forward core-inflation YoY change on the labor score**:

| Quantity | Value |
|---|---|
| Slope | **+0.00598** |
| Standard error | 0.00159 |
| t-statistic | **+3.76** |
| R² | **0.047** |
| n | **290** |

Subsample stability (three disjoint windows): **+0.0078 / +0.0028 / +0.0074** — the
point estimate is not one regime's artefact.

Corrected: `beta 0.043 → 0.006`, band `±0.15 → ±0.05pp`.

### The relation is real, small, and horizon-dependent

| Check | Result |
|---|---|
| Contemporaneous, detrended | **+0.348** |
| Forward 3-9 months, detrended | **+0.17 to +0.19** |
| 6-month forward change regression | **+0.00598** (t **+3.76**) |
| Forward 24 months | **−0.0114** (t **−2.94**) |

The **12-month detrending control** is what rules out two persistent series
agreeing by trend. The **sign reversal at 24 months is a policy reaction**, not
instability: a tight labor market predicts core inflation up three to nine months
out, and down two years out, because two years is when the central bank has
answered. Publishing the single coefficient without the horizon would be half a
finding.

**The dilemma and its honest resolution.** A narrow band (so `stable` is not the
base state) and `beta = 0.043` **cannot both hold** — the measured `R²` is 0.047.
The rejected resolution is to keep the wide band, call the relation real, and ship
a classifier that says nothing four fifths of the time; D-047 already established
that this project does not ship that. The adopted resolution measures the two
quantities on **separate estimands** and publishes the small coefficient with its
horizon structure.

### Label mix over 296 real months

| Direction | Share | §16.2's thresholds |
|---|---|---|
| `reaccelerating` | **40.5%** | — |
| `stable` | **31.4%** | **79.1%** |
| `decelerating` | **28.0%** | — |

### Published `value`

```
projected_change_pp         beta * score * fiscal_scale
direction                   TrajectoryDirection (Literal)
beta_pp_per_score_point     the configured coefficient, published for audit
labor_score                 the input the projection reads
inflation_level             the current core level
growth_corroboration        coherence read against the growth leg
fiscal_response_active      §18.6 flag as given
fiscal_scale_applied        the multiplier actually applied (1.0 or >1.0)
```

`inputs_used = ["growth.value", "labor.value", "inflation.value",
"fiscal_response_active"]` — all four genuinely read.

Confidence from `compute_confidence(ConfidenceInputs(...))` with
`is_heuristic_not_calibrated=True` (the OLS point estimate, **O-40**),
`depends_on_unobservable=True` (the score as a sufficient statistic, which the
`R²` contradicts), and `data_quality_flags_present` from the labor warnings.
**Never a literal** (§22.8).

### Config — `phillips.trajectory`

```yaml
beta_core_inflation_pp_per_score_point: 0.006
bands:
  reaccelerating_above_pp: 0.05
  decelerating_below_pp: -0.05
fiscal_active_multiplier: 1.5
```

Each `CalibratedValue` carries the OLS provenance (n 290, se 0.00159, t +3.76,
R² 0.047), the three subsample slopes, and the correction record.

### Harness — 24 mutations, 10 groups

One group per specification defect (M1 sign, M2 unit, M3 band comparison, M4
reachability, M5 unread parameter, M6 §18.6 fiscal flag, M7 provenance, M8 §22.8,
M9 config, M10 honesty controls). **21 killed, 3 expected survivors, 0
unexplained.** `_EXPECTED_INERT` is deliberately **empty**.

**M5.2 survived and the gap was genuine.** All four corroboration states had a
test, but each test drove **one quadrant**, so nothing placed the *disagreeing*
inputs against both *agreeing* branches. `probe_m52.py` enumerated the difference:
**2 reachable cases**, both in `loose labor + expanding growth`. Repaired with
`test_all_four_corroboration_quadrants_are_distinguished` and
`test_every_corroboration_state_is_reachable` (**lesson 49**).

**`check_targets` refused twice, both formatter drift.** First `M10.2`'s
mis-transcribed leading whitespace (the authoring run). Then, at close,
`source_independence_count` reflowed from one line to three (**lesson 50**). Both
were caught by **executing** the harness, not by reading it — which is the concrete
warrant for re-running the sweep at close.

### Cross-check

Against `cross_asset_transmission` (D-052) on the **shared labor leg**: the two
functions must agree on the sign and magnitude of the labor contribution before
their own diverging logic applies. **Not disjoint** — they share an input — so
lesson 46's rule needed refining: a shared input makes a cross-check circular when
both sides *consume* it, and informative when the shared input is what both sides
are *claimed to agree about*. Built from the start, it is what surfaced the config
error.

---

## Module 17.3 — `evaluate_drawdown_rules` (D-054)

*The first Tier 3 function that is not a model. New package `portfolio/`.*

### Function

| Item | Value |
|---|---|
| Spec | §6.6c (thresholds + ladder), §17.3 (Module 17.3, `RiskLimits`) |
| Source | `src/macro_engine/portfolio/risk_budget.py` (**new package**) |
| Test | `tests/portfolio/test_risk_budget.py` (**new package**, 65 tests) |
| Sweep | `scripts/mutation_drawdown.py` (47 mutations, 13 groups) |
| Live | `scripts/live_drawdown_check.py` (2 513 real daily SP500 obs) |
| Registry change | **none** — inputs are two scalars, not series |
| Decision | **D-054** |

### What it computes

```text
drawdown_fraction = (high_water_mark - current_value) / high_water_mark
triggered         = { r in rules : drawdown_fraction >= r.threshold_pct }
trigger           = max(triggered, key=lambda r: r.risk_reduction_pct)   # or None
outcome           = "stop_trading" if reduction >= 1.0 else "reduce_risk"
                  | "no_action"    if trigger is None
```

Every threshold lives in `config/settings.yaml` (`risk.drawdown_thresholds.tiers`,
`calibration_status: mechanical_rule`); the module contains **no literal
thresholds**. Confidence is `compute_confidence(ConfidenceInputs(...))` and
**nothing else** (§22.8) — `base 0.7 − heuristic_penalty 0.2 = **0.5**`, the
project's midpoint, which the module docstring now states **because the earlier
draft claimed it was "high relative to the project's other models" and that claim
was never measured**.

### The five defects

1. **A 100× unit conflict between the specification and its own config, with no
   converting consumer.** §6.6c writes fractions (`le=1.0`); the YAML writes
   percents (`10.0`, `50.0`). Read across unconverted, **every rung is
   unreachable** — reported "no risk-reduction rule triggered" at a 90% drawdown.
   The **failure direction is the finding**: this is a *de-risking* rule, so the
   error makes it **silent**, not aggressive — the opposite of the prediction, and
   the worse of the two directions. Fixed by normalising at **exactly one
   boundary** (`_tiers()`) and adding `_reject_fraction_scale_entry` so a
   fraction-convention entry in a percent field is **refused at load time**.
2. **`risk_reduction_pct` was unbounded** — a 500% "reduction" was a legal config.
   Bounded `(0.0, 1.0]` after conversion, `(0.0, 100.0]` in the percent field.
3. **"Evaluated in order" contradicts "most severe wins".** §6.6c's prose implies
   accumulation; its own stated rule is a max. The result is
   **permutation-invariant**, pinned by a test that reorders the ladder and asserts
   the same answer — so an "early break" implementation is provably a different
   function.
4. **`max(key=severity)` vs `max(key=threshold)` are indistinguishable on the
   shipped ladder** and **divergent off it**, so no test on shipped config alone
   could tell them apart. Pinned by a custom ladder where they disagree.
5. **`0.0` was ambiguous between "nothing fired" and "fired, prescribed zero."** A
   `Literal` (`no_action` / `reduce_risk` / `stop_trading`) makes the distinction
   representable. **The `Literal` then needed two kinds of test**: a runtime value
   test *and* a `get_args()` test, because a `Literal` is **not enforced at
   runtime** — the value test alone could not see a lost member.

### The defect class that does NOT apply, recorded as part of the deliverable

`docs/PROGRESS.md` listed this function as a **"gate chain over a path"** — the
compositional shape behind D-050/051/052. **The probe showed it is neither.**
There is no path (two scalars in), no chain (every rung reads the *same* operand;
nothing is consumed), and the resolve step is a **max, not an accumulating
ladder**. The composition defect is **unreachable** here.

The **base-state rule** (D-047/D-053, lesson 5g) **also does not apply**: this is
not a classifier, and its modal label — `no_action`, **82.9%** of real trading days
— is the *correct* one. **An unrecorded non-application is indistinguishable from
an oversight**, so it ships as `test_the_base_state_failure_does_not_apply_here`,
asserting the **reason**, not a count.

**The prediction was written down, probed, and found wrong twice over** (wrong
about the shape, then wrong about the direction of the error). It is recorded in
`docs/PROGRESS.md` as a hypothesis rather than quietly deleted, because a
prediction treated as an assumption would have aimed the cross-check at the branch
structure and missed the config entirely.

### The accessor had no consumer

`RiskSettings.drawdown_tiers` had a reader and **no consumer** — a clean
"declared, consumed, unreachable" instance, the same class as `GrowthAxis.at_trend`
(D-045a) and `source_independence_count` (D-046). `evaluate_drawdown_rules` is its
**first genuine consumer**, and wiring it is what exposed the convention mismatch:
the producer wrote percents and the only consumer expected fractions, and nothing
had ever forced the two to meet.

### Mutation testing

| Run | Result |
|---|---|
| First authoring run | **42 / 47** — four **genuine coverage gaps** |
| After closing the four gaps | **46 / 47**, 1 survivor (the honesty control) |
| Close-out re-run | **46 / 47**, unchanged; `check_targets` CLEAN; `LEFTOVER: NONE` |

The four gaps and their repairs:

- **`M5.1` / `M5.2`** — the `Literal` losing a member or gaining one. A `Literal`
  is not runtime-enforced, so **no value assertion can see it**; repaired with
  `test_the_declared_outcome_set_is_pinned_to_the_type`, which reads
  `typing.get_args(RuleOutcome)`.
- **`M5.3`** — the stop gate moved from `1.0` to `0.99`, which **only differs on a
  reduction in `[0.99, 1.0)`**. Repaired with
  `test_the_stop_trading_boundary_is_exactly_one` using a `0.995` witness.
- **`CX3`** — the tier **ceiling**. The floor was tested; the ceiling was not.
  Repaired with `test_the_tier_ceiling_is_a_boundary_not_a_decoration`.

**`_EXPECTED_INERT` is deliberately EMPTY** (`frozenset()`), which is a stronger
statement than a populated one: nothing is excused from having a test.

**The harness itself carried a defect.** `build_mutations()` reconstructed every
`Mutation` from a 4-tuple and **dropped `expect_killed`**, so the correctly
surviving control `M9.1` was reported as an unexplained `[DEFECT]`. Repaired by
carrying `expect_killed=False if name.startswith("M9.1 ") else None`.

**`check_targets` refused three runs, all formatter drift or mis-transcription.**
One was **INERT BY CONSTRUCTION** — my own transcribed constant said
`trigger.risk_reduction_pct` where the source says `trigger.threshold_pct`. Two
were `ruff format` reflows (`tiers_triggered`, `_PUBLISHED_BLOCK`). **This is the
concrete warrant for honour 1**, and it struck **three times in one increment**.

### Live check — real data only

Walks a real daily SP500 path carrying a running high-water mark, using whatever
window the provider serves (FRED's `SP500` is a **rolling ~10-year window**,
2 513 obs, 2016-09-19 .. 2026-09-17) and asserting only that the window is still
**≥ 20% deep**.

| Outcome | Count | Share |
|---|---|---|
| `no_action` | 2 084 | 82.9% |
| `reduce_risk` | 355 | 14.1% |
| `stop_trading` | 74 | 2.9% |

Every rung fires **at or beyond** its threshold; worst drawdown **33.92%** on
2020-03-23 (COVID).

**Section 3 checks path-independence, not time-monotonicity.** The first draft
asserted the ladder's reduction is monotone over the *observation sequence* and
reported **52 violations — every one a recovery**. That assertion is simply wrong:
a recovery **is** a shallower drawdown, so the ladder **correctly** prescribes less.
The property that holds over a path is **path-independence** (the same drawdown
always gets the same answer, regardless of how it was reached): measured over
2 154 distinct drawdowns, **0** disagreements.

### Two of the check's own bugs, found before it passed

1. **A hardcoded 2007–2010 episode that FRED does not serve.** `series_registry.yaml`
   already recorded the rolling-window fact; the check had not read it.
2. **The monotonicity-over-path assertion** above, plus a smaller
   `min(rows, key=drawdown)` that selected the **smallest** drawdown and produced a
   misleading diagnostic. **A check whose own sections contradict each other has a
   check bug, not a data bug** — worth recording, because the instinct is to
   distrust the data.

### Cross-check (honour 2)

Against `volatility_target_scaling` (§20.13) on three **structural invariants**:
zero stress → no intervention; monotone response in the stress input; the hard
constraint **clips and never loosens**. There is **no shared input**, so this
compares the shared **shape** rather than a shared series. **O-43**: the
vol-target side is currently a **re-implementation** of §20.13, not a call to it,
so it must be re-pointed at the real function in the next increment.

### New configuration

`config/settings.yaml` was **not modified** — the defect was in the *reading*, not
the writing. `config.py` gained two module constants (`_MIN_DRAWDOWN_TIER_PCT`,
`_MIN_RISK_REDUCTION_PCT`), a `@model_validator` on `DrawdownTier`, and an extended
`RiskSettings.drawdown_tiers` docstring stating the percent convention and naming
the one conversion boundary.

### The live check found three defects — all three were in the check

`scripts/live_api_check.py` is the increment's proof that the *wiring* works, and
its first three runs failed. Every failure looked like a defect in the service.
None of them was. They are recorded here because the **diagnostic shape** — a
misleading symptom on a correct component — is the reusable part.

**1. `GET /health?deep=true` returned `404 {"detail": "Not Found"}` from a
registered route.**

The route was correct (`@router.get("/health")` with `deep: bool = Query(...)`)
and correctly mounted (`app.include_router(routes_health.router)`, no prefix). It
returned **200 to `TestClient`**. And a standalone probe returned **200** too, so
it presented as *intermittent*.

The cause was found by tapping the socket and printing the **request line**:

```
wire 0: b'GET /health HTTP/1.1'
wire 1: b'GET http://127.0.0.1:55264/health HTTP/1.1'    <-- absolute URI
```

This environment exports `HTTP_PROXY`/`HTTPS_PROXY`, `httpx` honours them by
default (`trust_env=True`), and **a forward proxy must receive the absolute-URI
request form** (RFC 7230 §5.3.2). The proxy forwarded that URI to the origin,
uvicorn unquoted the whole thing into the path, and no route matched.

The intermittency was the trap: the *first* request on a fresh connection went
out as origin-form and survived; a **reused keep-alive** connection went out as
absolute-URI and 404'd. Isolated by measuring all four combinations — reuse alone
flips the form, `params` is irrelevant — and proven by `trust_env=False` sending
origin-form on both requests.

Three wrong hypotheses were tested and discarded first: the query-param encoding,
a route/prefix mismatch, and h11's 16 KiB request-header limit. The last one is
instructive — an oversized header block genuinely does produce a protocol error
(h11 raises `RemoteProtocolError`, hint 431), but the *fresh-connection* case
returned a clean `431`, so it was a different failure with a superficially
similar shape. **The lesson is the general one: a routing-shaped symptom can have
a transport-shaped cause, and the status code cannot tell them apart. The request
line can.**

**2. The CORS preflight returned `400 Disallowed CORS origin`.**

The check had hardcoded `http://localhost:3000`; `config/settings.yaml` allows
`:8000`. **Starlette was right and the check was wrong.** Fixed by deriving the
origin from `settings.api.cors_origins` — which is the stronger test anyway,
because it asserts the property that matters ("an origin the service was
configured to accept is accepted") rather than a constant.

**3. The stream assertion failed on a *correct* stream.**

The assertion searched for `"gap = +26.0bp"`. The stream emits:

```
Model-implied 4.67 vs market-implied policy path: gap = +0.2600pp (+26.0bp), dispersion 0.8600pp, meaningful=False
```

The value was exactly right; the check had baked in a **spacing** the stream never
promised. This is lesson 5bf applied to a check — **pin the value, not the
spelling** — and it now requires **both** renderings (`+0.2600pp` and `(+26.0bp)`),
because a stream that hardcoded one unit while deriving the other would pass a
single-unit check.

**Guard added.** `test_the_live_check_does_not_route_its_loopback_traffic_through
_a_proxy` reads `scripts/live_api_check.py` with `ast` and requires every
`httpx.Client(...)` to set `trust_env=False`; a companion test requires the proxy
variables to be *printed* so the run stays reproducible. Verified red by planting
the regression (removed `trust_env`) — the guard failed and named the line — then
restored. It cannot be behavioural: the unit suite drives `TestClient`, which
never opens a socket.

**Production exposure recorded.** The same root cause affects two production
clients — `openbb_client.py:91` and `catalysts.py:213` both default to
`trust_env=True`, and the OpenBB client's mounts against
`http://127.0.0.1:6900` are `{http://: HTTPProxy, https://: HTTPProxy}`. The
provider *works* here (21/21 fields, 62.4–66.1s measured), so this environment's
proxy is transparently forwarding loopback. Filed as **O-92** rather than fixed:
it changes data-layer network behaviour, which this increment did not touch, and
altering the provider's transport would have invalidated the sweep certifying it.

### Carry-overs opened

| ID | Item |
|---|---|
| **O-43** | The cross-check is a re-implementation of §20.13, not a call. Re-point it when `volatility_target_scaling` ships. |
| **O-44** | `.probe/` makes the unscoped `ruff check` count unusable (711 errors, all scratch). The real gate is the scoped one. |
| **O-45** | `RiskLimits.max_drawdown_trigger_pct` (`0.10`, fraction) restates this ladder's first rung (`10.0`, percent) with no stated precedence — a config surface with a reader and no consumer (the D-037 class). Resolve in the `volatility_target_scaling` increment. |

---

## Module 17.3 — `check_rebalancing_drift` (D-055)

*The **second** function in the `portfolio/` package — same module, same class of
question (is the book still inside the risk policy?), different failure direction.*

### Function

| Item | Value |
|---|---|
| Spec | §20.13 (risk budgeting), §6.6c (the sibling ladder), §17.3 (`RiskLimits`) |
| Source | `src/macro_engine/portfolio/risk_budget.py` (appended to the D-054 module) |
| Test | `tests/portfolio/test_rebalancing_drift.py` (**58 tests**) |
| Sweep | `scripts/mutation_rebalancing.py` (64 mutations, 12 groups) |
| Live | `scripts/live_rebalancing_check.py` (5 real ETFs, 504-session covariance) |
| Registry change | **none** — inputs are a dict and a list, not series |
| Decision | **D-055** |

### What it computes

```text
for target in targets:
    seen.add(target.instrument)
    actual  = current_contributions.get(target.instrument, 0.0)
    signed  = actual - target.target_risk_contribution_pct
    if abs(signed) > threshold:                 # STRICT --
        drifted.append((target.instrument, signed, "over" if signed > 0 else "under"))

unbudgeted = sorted(set(current_contributions) - seen)
missing    = [t.instrument for t in targets if t.instrument not in current_contributions]
outcome    = "rebalance" if drifted else "balanced"
```

Every threshold lives in `config/settings.yaml`
(`risk.rebalancing_drift: {value: 0.10, calibration_status: mechanical_rule}`,
**fraction** convention); the module contains **no literal thresholds**. Confidence
is `compute_confidence(ConfidenceInputs(...))` and **nothing else** (§22.8).

### The four defects — all one shape

Every input the function was **not given** is treated as a **confident zero**,
never as unknown:

1. **A target with no current value reads as zero risk, not as unknown.**
   `.get(target.instrument, 0.0)` cannot distinguish "I hold none of this" from "I
   forgot to tell you about this", and it chooses the **stronger** claim — a
   maximal underweight on no evidence. Fixed by publishing `missing_instruments`,
   so the derivation is disclosed even though the arithmetic is unchanged.
2. **An instrument held but not budgeted is invisible.** The loop iterates
   `targets`, so a position with **no target** is never visited. A book that has
   drifted entirely into unbudgeted instruments reports `balanced`. Fixed by
   publishing `unbudgeted_instruments` — the same census discipline §15.19-D
   demands, and the same defect D-050 found in `four_pillar_scorecard`.
   **A drift check that only iterates the declared budget measures compliance with
   the budget, not risk.**
3. **The unit convention was unstated, for the third consecutive increment.** The
   leaf is a **fraction** (`0.10`) whose name carries `_threshold` not `_pct`,
   sitting beside `_pct` leaves carrying **percent**. Fixed by naming the unit in
   the **guard message** (`"A value above 1.0 is a percent written into a fraction
   field."`), not only in a docstring — the guard is the only place that runs.
4. **`>` is strict, and the boundary fixture did not sit on it.** The original test
   used `0.25 + 0.10 - 0.25 == 0.09999999999999998` — **a hair below** `0.10` — so
   it passed while being unable to distinguish `>` from `>=`, and the mutant that
   swaps them **survived**. Rebuilt on `0.225 - 0.125 == 0.10` (binary-exact;
   verified `>` is `False`, `>=` is `True`).

### The failure direction

**Opposite to D-054's.** That ladder failed toward **silence** (a de-risking rule
reporting `no_action` at a 90% drawdown). This function fails toward **false
confidence** (a drifted book reporting `balanced`). Both are fail-safe-looking
outputs produced by a *missing input*, and both are worse than an exception —
which is why the module header states the direction rather than only the behaviour.

### The two honours

**Cross-check built from the start, and it is a REAL CALL.** The comparable
function `evaluate_drawdown_rules` **exists**, so the live check calls both and
asserts three shared invariants: (A) no stress → no intervention; (B) the response
is a function of the displacement — **V-shaped** for drift, non-decreasing for the
ladder; (C) intervention is bounded. **This does not repeat D-054's O-43
asymmetry**, where the vol-target side had to be re-implemented because the
function did not exist.

**Invariant B was stated wrong first and the live check caught it.** The draft
asserted "a larger displacement reports a larger drift" and failed — because
**moving an instrument *toward* its target reduces the drift**. The property is
V-shaped, and the sweep must go **outward from the target on both sides**. Same
class as D-054's path-monotonicity error: an invariant asserted from intuition
rather than from the function's domain, caught only because the check ran against
real numbers.

**Sweep re-run at close** (honour 1) — clean: **64 / 64 applied, 61 killed,
3 survivors**, all classified.

### The sweep: 64 / 64 applied, 61 killed, 3 survivors, 0 defects

**First increment in the repository to populate `_EXPECTED_INERT` with proven
entries**, and the two proofs are deliberately **different in strength**:

* **`M4.6` — inert UNCONDITIONALLY.** A drift row is appended *only* inside
  `if abs(signed) > threshold:`, and the guard above enforces `threshold > 0.0`.
  So every row satisfies `abs(signed) > threshold > 0`, which excludes
  `signed == 0` from the direction test's domain **entirely**. `signed > 0` and
  `signed >= 0` are the same predicate on every reachable input.
* **`CX3` — inert CONDITIONAL ON THE SHIPPED CONFIG.** Probed: the leaf's runtime
  type is `builtins.float` and `float(v) is v` is `True`, so the cast is the
  identity on every value the shipped `settings.yaml` can produce. **Unkillable
  today, and NOT unkillable in general** — a leaf that ever became a `str` or
  `Decimal` would make it load-bearing and this proof would stop applying.
* **`M9.1`** — the honesty control, whose survival is **required**.

**The harness now refuses to certify an excused mutation with no proof.**
`_INERT_PROOFS.get(name, "(PROOF MISSING)")` plus an early `return 2` means an
entry added to `_EXPECTED_INERT` without an excuse **cannot be reported as
clean** — the mechanical form of O-42's discipline, and the first time it has been
enforced.

### Three harness defects found by running it

1. **Three `check_targets` AMBIGUOUS refusals on the first run** — `"outcome": outcome,`,
   `warnings: list[str] = [` and `is_heuristic_not_calibrated=True,` each appear
   **twice** in `risk_budget.py`, once per function. Re-anchored on a preceding
   line unique to the rebalancing block. **An ambiguous anchor mutates whichever
   `str.replace` hits first, and the sweep would have reported a kill for a
   mutation applied to the wrong function.**
2. **Twelve first-run survivors, only six of them real gaps.** Two were **INERT
   BY CONSTRUCTION** (my mutants inserted dead code) and one was **INERT BY
   ANCHORING** — `M10.1` inserted a `model_config` *before* the docstring, so the
   real config nine lines below shadowed it and **the code under test never
   changed**. The sibling of D-051's transposed `old`/`new`: both produce a
   "missing test" conclusion about code that was never actually mutated. The
   cheapest proof is to **read back the attribute the mutation was about**.
3. **`M3.8`'s first mutant rewrote only half the guard message** — the message is
   two concatenated f-strings, so `"percent"` survived in the second and the new
   test still passed. **A mutation that changes part of a message has not changed
   the message.**

### The live check, and what it found that no fixture could

Five **real tradeable ETFs** (`SPY TLT IEF GLD UUP`) via `yfinance` /
`etf.historical`, a real covariance over **504 sessions**, Euler risk
contributions `wᵢ(Cov w)ᵢ/σ_p`:

* **σ_p = 8.33%** annualized;
* **SPY carries 35.0% of notional and 56.14% of RISK** — the finding the module
  exists to make;
* **UUP carries −1.48%** — a genuine diversifier;
* **trip rate 9.7%** at the configured 10% threshold, so `balanced` is **not**
  modal by construction.

The first draft decomposed risk across **FRED-macro legs** and returned a
**degenerate** estimate (a VIX leg at **136%** annualized vol, a **negative**
equity leg). Not a code bug — it is what happens when a price index and a
volatility level share a covariance matrix. The honest basis is tradeable
instruments on a common return convention.

Three findings no unit fixture could produce:

1. **The contract cannot budget a hedge** — `RiskBudgetTarget` bounds the share to
   `[0, 1]`, so pydantic **rejects** UUP's real contribution. Recorded as **O-46**.
2. **A partitioned share vector must be renormalised** —
   `total_current_contribution` came back **1.014778**, and the function **caught
   it with its own sum-to-one warning**. Recorded as **O-47**.
3. **The response is V-shaped, not monotone** — see invariant B above.

### New configuration

`config/settings.yaml` gained one leaf:
`risk.rebalancing_drift: {value: 0.10, calibration_status: mechanical_rule}` —
**fraction** convention. `config.py` gained its accessor
(`RiskSettings.rebalancing_drift_threshold`), stated in a docstring as a
**fraction**, with its unit also named in the function's own guard message.
`tests/portfolio/test_risk_budget.py` needed three `RiskSettings(...)`
constructions updated with the new required field — a real consequence of adding a
config leaf, caught by `mypy --strict`.

### Carry-overs opened

| ID | Item |
|---|---|
| **O-46** | `RiskBudgetTarget.target_risk_contribution_pct` is bounded `[0,1]` but real diversifying legs contribute **negatively** (measured: `UUP` at `−1.48%`). The contract cannot express a hedge. Likely answer is **two concepts** (a budgeted share vs a measured contribution) rather than widening the bounds. |
| **O-47** | A partitioned risk-contribution vector must be **renormalised**, and nothing enforces it. The sum-to-one warning fires *after* the wrong number is computed and published. |
| **O-45** | **Still open, deliberately.** D-055 was not the `RiskLimits` increment — and it made O-45 **sharper**: `risk.rebalancing_drift` is now a **third**, fraction-convention leaf beside `_pct` (percent) leaves in the same block. |
| **O-44** | Unchanged, and now sharper: D-055 added **three more** `.probe/` scripts. |

---

## Module 17.2 — `volatility_target_scaling` (D-056)

| Field | Value |
|---|---|
| Spec | **§20.13** (Module 17 — Volatility Targeting); `RiskLimits` from **§17.3**; mandatory golden test from **§20.14** |
| Tier | **3 — synthesis** (14 / 15) |
| File | `src/macro_engine/portfolio/risk_budget.py` |
| Tests | `tests/portfolio/test_volatility_target.py` (**45 tests**) |
| Sweep | `scripts/mutation_voltarget.py` (23 mutations, 9 groups) |
| Live | `scripts/live_voltarget_check.py` (5 real ETFs, 1 938 sessions) |
| Decision | **D-056** |
| Registry | **no change** — inputs are two volatilities and an exposure, not series |

### The function

```python
raw_scale      = target_vol_annualized / current_portfolio_vol
scaled_exposure = current_gross_exposure * raw_scale
ceiling        = limits.max_leverage                       # from config
final_exposure = min(scaled_exposure, ceiling)             # ONE-SIDED
clipped        = final_exposure < scaled_exposure
pre_existing_breach = current_gross_exposure > ceiling
```

Nine published keys, three mutually exclusive warning paths, confidence from
`compute_confidence()` at the project midpoint **0.5**. It reports a **size** and
never places an order.

### The six specification defects, and what shipped for each

| # | Defect | What shipped |
|---|---|---|
| **D1** | Four of five declared `RiskLimits` had **zero references anywhere** (the D-037 class) | `unread_by_vol_targeting` + the published `limits_declared_but_not_enforced` — **disclosure, not enforcement** (O-48) |
| **D2** | §20.14's mandatory golden test is a **HIT, not a PARTITION** (lesson 49) | `test_the_golden_test_is_a_hit_not_a_partition` asserts the untouched limits are *reported*, so "not tested" cannot read as "enforced" |
| **D3** | `min()` is an **upper bound only** — inert on the de-risking side | `de_risking_fraction`, and a live check that **measures** the clip rate (**0.0%** of 444 sessions) |
| **D4** | `clipped_by_limits` covers one side, reads as covering both (94% cut → `clipped=False`) | same key as D3; the cross-check against `check_rebalancing_drift` is what shows it |
| **D5** | `current_gross_exposure`'s unit unstated | the vol identity `realised == target` holds for **every** gross under the multiple reading; documented in `VolTargetInputs` |
| **D6** | A pre-existing leverage breach reported as a vol-target adjustment | a separate `pre_existing_leverage_breach` flag and a warning that names the attribution |

### The two obligation resolutions

* **O-45 — resolved by DELETION.** `RiskLimits.max_drawdown_trigger_pct` was the
  **same trigger** as the ladder's first rung (`10.0` percent, verified equal) and
  is **unreachable** from a signature with no drawdown input. The ladder governs
  (it is a pre-commitment, D-054), so the duplicate field is **gone**:
  `RiskLimits` ships with **4** fields.
* **O-43 — discharged.** `live_drawdown_check.py` §4 no longer re-implements
  §20.13; it **calls `volatility_target_scaling`**. Its O-43 disclosure is replaced
  by one that says so, recorded rather than deleted.

### The deliberate non-defect

**The base-state rule (lesson 5g) does not apply**, and the non-application is
recorded rather than left implicit. The function publishes a **magnitude** rather
than a label, and the probe measured a live clip rate of **0.0%** — no state is
modal by construction, because the output moves continuously with the input.

### The unit trap, fourth increment running

`max_position_pct_of_portfolio` (`0.15`) and `max_factor_exposure_pct` (`0.30`)
are **fractions despite the `_pct` suffix**. The guard is a **magnitude bound**
(`0 < x <= 1.0`) because that is the only contract a `float` admits, and it is
enforced in **two layers** covering different objects: `RiskLimits`'s own field
bounds (pydantic rejects `1.01` before any validator runs) and
`RiskSettings._reject_percent_in_fraction_field` (which catches the bare
`CalibratedValue` leaves in `settings.yaml`, which have no bound of their own, and
names the unit in its message). It is **deliberately not applied to
`max_leverage`**: `3.0` is a legal multiple *and* a legal-looking percent.

### New configuration

`config/settings.yaml` gained five leaves under a
`Module 17.2 / 17.3 — the hard risk limits (RiskLimits)` block, all
`calibration_status: institutional_convention`:
`max_position_pct_of_portfolio: 0.15` (**fraction**), `max_factor_exposure_pct:
0.30` (**fraction**), `max_leverage: 3.0` (**multiple**),
`min_liquidity_days_to_unwind: 2` (**days**),
`vol_target_reflexivity_scale: 0.8` (**scale** — was a literal in the body).
`config.py` gained five accessors plus the unit validator. Three
`RiskSettings(...)` constructions and one `__all__` assertion in
`tests/portfolio/test_risk_budget.py` needed updating — a real consequence of
adding config leaves, caught by `mypy --strict` and the suite.

### The sweep

**23/23 applied, 21 killed, 2 survivors, 0 defects.** First run: **16 killed, 7
survivors** — **five real gaps** closed with new tests, **one harness defect**
(`M7.1` inserted a second `model_config` above the class docstring and the real
assignment below shadowed it, so the code under test never changed — INERT BY
CONSTRUCTION), and **`M6.1`, which ships as the first entry in `_INERT_PROOFS`**
with a **CONDITIONAL** proof: it replaces `compute_confidence(...)` with `0.5`,
which **is** the computed value (`0.7 − 0.2`), so the two programs agree on every
reachable input. **INERT BY ANCHORING (lesson 54), not by unreachability.** The
control `M8.1` **survived as required**. Re-run at close: identical, and
`ruff format` touched nothing in between.

The five real gaps, each now a test:

* **`M3.2`** — the clip applied only when `raw_scale >= 1.0`. **Every clipping
  test scaled up; every de-risking test sat below the ceiling** — so the D-056
  defect relocated to the up-side passed the whole file.
* **`M2.3`** — the ceiling hardcoded to `3.0`. No test ever supplied a limits
  object whose ceiling **differed** from the shipped one.
* **`M6.2`** — `round(..., 6)` dropped. Every assertion used `pytest.approx`,
  which cannot see precision.
* **`CX3`** — the unit guard widened to `<= 10.0`. The existing test used `15.0`,
  which **any** bound from 1.0 to 14.0 rejects, so a loosened guard still *looked
  alive*. The fix is the band `(1.0, 10.0)`.
* **`M7.1`** — the harness defect above.

### The live check

Real 5-ETF book (`SPY TLT IEF GLD UUP`, weights 35/25/20/12/8), **1 938**
inner-joined sessions (2019-01-02 .. 2026-09-17), covariance over the last
**504**. Annualized portfolio vol **8.33%** vs a **10.00%** target → scale
**1.2010×**, *lever up*, `clipped=False`. Over **444** rolling 60-day
observations: vol range **4.67% – 13.99%**, scale range **0.715× – 2.142×**, the
**leverage clip fires 0 of 444 (0.0%)**, the reflexivity warning **58 of 444
(13.1%)**. The clip rate is **measured, not cited from the probe**, so a config
change that makes it reachable is visible.

**Two cross-checks, both real calls.** Against `evaluate_drawdown_rules` on the
shared **invariant** (monotone in stress, flat at zero stress); against
`check_rebalancing_drift` on the shared **disclosure shape**, which is what makes
D4 legible. The check also reproduced the **same** contract limitation D-055's
check found on the same legs: `UUP` carries a **−0.12%** risk share, and
`RiskBudgetTarget`'s `[0, 1]` bound means a diversifier has **no legal target** —
partitioned, renormalised, and **named**, never clamped.

### Carry-overs opened / closed

| ID | Item |
|---|---|
| **O-45** | **RESOLVED** by deletion. `RiskLimits` = 4 fields. |
| **O-43** | **DISCHARGED.** The D-054 cross-check is now a real call. |
| **O-42** | **DISCHARGED for the live path.** The `_INERT_PROOFS` gate enforces no-proof-no-certification mechanically, and `M6.1` is the first entry through it. |
| **O-48** | **NEW (severity 3).** The four inert `RiskLimits` fields are **reported**, not **enforced**. D1's repair is disclosure. A consumer that reads the field and assumes it binds repeats D1's mistake. |
| **O-49** | **NEW (severity 2).** The clip has no lower bound and none is needed, but the **asymmetry is undocumented in §20.13**. Whether the specification should express a maximum de-risking rate is a design question this increment did not answer. |
| **O-46 / O-47** | Unchanged, and now **independently reproduced** by a second live check — which is what establishes them as properties of the contract rather than of one script's book. |
| **O-44** | Unchanged, and sharper again: D-056 added **four more** `.probe/` scripts. |

---

## Module 17.3 — `apply_fractional_kelly` (D-057)

**Status: IMPLEMENTED, TESTED, MUTATION-SWEPT, LIVE-VALIDATED.** The **last
Tier 3 function**, and with it **Tier 3 closes at 15 / 15**.

| Field | Value |
|---|---|
| Module | **17.3 — Fractional Kelly position sizing** |
| Section | **§20.14** (the golden tests) + **§22.6** (Finding #6 — the *real* Kelly) + §22.13 (the mandatory deletion) |
| Tier | **3 — synthesis** (15 / 15, COMPLETE) |
| Phase 2 | **77 / 98 (79%)** |
| Decision | **D-057** |
| Function | `apply_fractional_kelly` in `src/macro_engine/portfolio/risk_budget.py` |
| Public API | `__all__` 12 → **15** |
| Tests | `tests/portfolio/test_fractional_kelly.py` — **52 tests** (+3 this increment) |
| Sweep | `scripts/mutation_kelly.py` — **25 mutations, 10 groups** |
| Live check | `scripts/live_kelly_check.py` — **offline by design** |
| Registry change | **none** (the input is a caller-supplied outcome distribution) |

### What §22.6 requires, and why §17.3 was wrong

§22.6 defines the **real** Kelly criterion as the grid-search expected-log-growth
optimum:

```
f* = argmax_f  SUM_i [ p_i * log(1 + f * r_i) ]
```

§17.3 declares `raw_kelly = ev / 100` — a **placeholder incorrectly labelled
Kelly**, which is not that formula in any limit. §22.13 makes its deletion
**mandatory**, and the deletion is the first thing this increment did. **Only
`generalized_kelly_fraction` may call itself Kelly.**

The function is two-stage by design: `generalized_kelly_fraction` computes the
**full** optimum (grid search, publishing `at_search_edge`), and
`apply_fractional_kelly` applies the **mandatory** fractional divisor and the
position cap.

### The eleven defects

**D1 — the placeholder, deleted.** `raw_kelly = ev / 100` removed from §17.3's
implementation path; the function's context string now says the placeholder was
**replaced**, and a test asserts that direction.

**D2 — the grid resolution was a literal.** `n_grid = 1000` was specified; the
shipped grid is `config.kelly.grid_points` (**100001**), read through
`search_points`. The **400×** measurement is recorded in the config leaf's note.
The shipped formula is `fraction = index / (grid_points - 1)` — the subtraction
produces a step of exactly `1e-5` and lands **exactly** on the binary closed-form
optima.

**D3 — the payoff-unit contradiction.** §22.6 requires payoffs **already
normalized to a fraction of capital**; `ScenarioOutcome.unit` defaults to
`"bp_pnl_proxy"`. → **O-50**.

**D4 — the divisor was a literal.** `kelly_fraction_multiplier` is now
`1.0 / divisor`, with `divisor` behind a `KellySettings._enforce_fractional_kelly_floor`
that refuses `k < 2` at load time. `fractional_divisor: 2.0`.

**D5 — the cap collapsed the request.** The cap is applied to the **fractional**
request, not the full one, so a cap of `0.10` on an uncapped `0.99` yields `0.10`
— and the *published* `requested` collapses to the same value. This is a
**disclosure**, not a bug: the P5b collapse is reproduced live
(`distinct REQUESTS: 1 of 3`, `distinct GROWTHS: 3 of 3`).

**D6 — the per-function unenforced set.** `unread_by_position_sizing` names the
`RiskLimits` fields this function does not read, mirroring D-056's
`unread_by_vol_targeting`. The declared-but-unenforced set is published on every
output.

Plus the four recorded in the probe (P1–P4) and the two later findings (grid
resolution, request collapse).

### The sweep — 25 mutations, 10 groups

```
check_targets: 25 mutations, 0 problem(s)
test selection collects cleanly
applied 25 / killed 21 / survived 4
RESULT: every survivor is either expected or proven inert.
EXIT=0
```

**Three survivors are PROVEN INERT:**

| Mutation | Class | Proof |
|---|---|---|
| `M5.4` — the clip is applied to the up-sizing side only | **INERT BY EQUIVALENCE** | `min(requested, cap)` and `min(requested, cap) if requested > cap else requested` are the same function written two ways. No input distinguishes them, so **no test should have to**. |
| `M3.3` — the argmax initialiser makes zero unreachable | **INERT BY UNREACHABILITY** | The grid's first candidate is always `fraction = 0.0`, where `_expected_log_growth` is exactly `0.0` (every term is `p_i · log(1)`), and `best_growth` starts at `-inf`. So the first comparison assigns unconditionally — **the initialiser is dead**. The only non-assigning path raises rather than publishes. |
| `M7.1` — a clipped-zero is reported as `no_edge` | **INERT BY UNREACHABILITY** | `full_fraction == 0.0` and `final_fraction == 0.0` are **equivalent over every admissible input**, because the cap carries a field bound `gt=0.0` — a cap of exactly `0.0` is a `ValidationError`. Verified over **200 000** draws, **0** disagreements. |

`M9.1` is the **honesty control** and survived as required.

**`M7.1`'s proof is a FINDING, not an excuse.** It says the state
`SizingOutcome`'s docstring calls `clipped_by_position_limit` **with a zero
result** is **unreachable** — and the closing test
(`test_a_positive_edge_clipped_to_zero_is_not_no_edge`) asserts that reachability
fact, including the `ValidationError` that makes a zero cap illegal, so a future
bound change is **visible rather than silent**.

### What the sweep found: 3 genuine coverage gaps, all closed

| Gap | What was untested | Fix |
|---|---|---|
| `M1.2` | The context-string claim about the deleted placeholder | `test_the_context_states_the_placeholder_is_not_implemented` — asserts `"replaced" in context` **and** `"specified" not in context` |
| `CX1` | `search_points` was never read from config | `test_the_search_resolution_is_read_from_config_not_a_literal` — moves the leaf to **777** (1001's step is exactly `1e-3` and **would not discriminate**) |
| `CX2` | The `points < 2` floor | `test_a_one_point_grid_is_refused_at_load_time` — for `bad_value in (0, 1)`, expects `ValueError, match="must be at least 2"` |

`CX` re-ran **3 / 3 killed** after the fixes.

### The harness had to be fixed twice while this ran

**The `-x` omission.** The selection is **~95 s**; without `-x` the 25 mutants
take **~40 minutes**, which is what invited the interruption that followed. `-x`
is now passed **unconditionally** and documented as not optional.

**The `SIGTERM` bypass.** When the run was killed, `SIGTERM` **bypassed the
`finally` that restores the mutated file** — D-049's failure mode recurring.
`src/` was left carrying `M5.2` (`multiplier = 0.5`, a hardcoded divisor), caught
only because an existing test reads the divisor from config. The resumed run was
killed the same way through a `tee` pipe and left `M9.1` applied. Both were
repaired by hand, and the harness now installs a **SIGTERM/SIGINT handler** that
restores the in-flight mutation before exiting.

**`check_targets` refused twice, both self-inflicted** — the gate doing exactly
the job D-048 built it for. `M2.3`'s bare `if at_search_edge:` appears **twice** in
the module (AMBIGUOUS); `M3.2`'s anchor was written on the **wrong side of its own
swap** (ABSENT). Both caught **before any mutation ran**. The M3.2 case is worth
recording: I "fixed" the refusal by inverting the anchor rather than reading the
file, which **entrenched** the error. `20000 / 100001 = 0.199998` (shipped) versus
`20000 / 100000 = 0.2` (a step of exactly `1e-3`) is the arithmetic that settles
it.

### The live check — offline by design

Kelly's input is a **caller-supplied distribution**, so there is no series that
could falsify it. The honest live check is therefore a **cross-check against an
oracle**, not a pull:

1. The **shipped grid** against the **binary closed form**
   `f* = (p·b − q·a)/(a·b)` over **80** `(p, b, a)` combinations — worst absolute
   error **3.33e-16**.
2. The **deleted placeholder refuted** on the live config (200× the reference
   thesis's real answer — the direction of the defect).
3. The mandatory **fractional divisor** read out of the shipped YAML, not a
   literal.
4. The **P5b search-edge collapse** reproduced on real inputs: three genuinely
   edge-pinned theses (`(0.70, 2.00, 0.25)`, `(0.90, 1.00, 0.10)`,
   `(0.80, 1.00, 0.25)`) publish **`distinct REQUESTS: 1 of 3`** while
   `distinct GROWTHS: 3 of 3`.

Print: `LIVE CHECK PASSED`.

### Carry-overs opened / closed

| ID | Item |
|---|---|
| **O-50** | **NEW (severity 3).** §22.6's payoff-unit contract is contradicted by `thesis_layer.schemas.ScenarioOutcome`'s `unit="bp_pnl_proxy"` **default**, and the guard is one-sided (it catches the loss side, not `+120`). The failure direction is **prudence**. |
| **O-51** | **NEW (severity 2).** Two distinct classes are both named `ScenarioOutcome` — a class-level collision `mypy --strict` demonstrably does not detect. |
| **O-52** | **NEW (severity 2).** `_INERT_PROOFS` now carries **three** exemptions, two of them **unreachability** proofs whose truth is bound-dependent — and the harness records **presence**, not **strength**. |
| **O-42** | Unchanged in its residue: the gate checks a reason **exists**, not that it is **true**. |
| **O-44** | Unchanged, and sharper again: D-057 added two more `.probe/` scripts. |

---

## Module 15 — `select_instrument` (D-058)

**First function of Tier 4.** `models/instrument_selection.py`. §22.3.1 (the
corrected router, replacing §16.2's single-fallback placeholder) plus §22.12
(the production execution-universe boundary rule).

### Function

`select_instrument(inputs: InstrumentSelectionInputs, universe: InstrumentUniverse) -> ModelResult`

Maps a thesis *kind* and a *direction* onto the instrument through which the
thesis would actually be expressed — or onto an explicit sentinel saying no
production instrument exists. It answers one half of the thesis object's
instrument leg: **which** instrument, not how big. It never sizes, never prices,
and never trades.

### What it computes

Three outcome families, in this order of precedence:

1. **Blocked** — a multi-country thesis (`country != "us"`) returns
   `BLOCKED_MULTI_COUNTRY_NOT_BUILT`. §22.3 is explicit that Phases 0–4 are
   US-only and that `country="us"` is a *label*, not a generalization.
2. **Sentinel** — a route in the configured table whose entry names a
   non-production universe (credit, EM, commodity) returns
   `ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT`. §22.12's rule.
3. **Executable** — a valid route plus a direction yields a **dict**
   (`instrument`, `universe_category`, `executable`, `rationale`,
   `direction_word`), and `universe.category_for()` must **agree** with the
   route's own declared category or the function refuses.

The two result shapes are deliberately different — a **dict** on executable
branches, a **bare string** on sentinel branches — so a consumer cannot mistake
"here is your instrument" for "there is none". (O-53 records that this is
convention, not contract.)

### The architectural collision, and how it was resolved

`select_instrument` lives in `models/`; the vocabulary that decides what the
production universe contains (`ProductionUniverse`) lives in `thesis_layer/`.
The layering rule forbids `models/` importing `thesis_layer/`. Two repair paths
existed — move the vocabulary down, or receive it as a required argument. This
increment took the **second** (the D-046 pattern): `universe` is a **required
argument**, typed by a module-level `InstrumentUniverse` `Protocol` declared
*inside* `models/instrument_selection.py` so `models/` can annotate without a
circular import, and `thesis_layer` remains the owner and the supplier.

The cost of that choice is recorded as **O-54**: a `Protocol` is a *static*
promise, so at runtime nothing validates that the object handed in conforms.

### The eleven probe findings — two were latent defects in shipped code

The probe (before any code was written) is what turned this from a one-function
increment into a three-file one. Findings that changed the design:

- **P1 — §22.3.1's own worked example is not admitted by §16.4's vocabulary.**
  The spec's literal curve instrument (`"2y10y US Treasury steepener"`) failed
  `ProductionUniverse.category_for()` because the class had **no curve
  vocabulary** — the rates keyword set contained no `steepener`/`flattener` and
  no bare-tenor handling. **This was a real defect in already-shipped code**, in
  a class that had never had a test (probe P8).
- **P2 — the currency matcher is a false-positive machine.** `_keyword_match`
  admitted a 6-character token as an FX pair if its **first three** characters
  were a G10 code. `"europe equity"` — whose first three letters are `eur` —
  therefore matched the FX family. Fixed to require **both** halves to be G10
  codes, with `/`-pair normalisation.
- **P3 — the sentinel was matched case-sensitively** in `permits()` and
  `category_for()`, so a lowercased `"none"` fell through to the keyword
  matcher and was rejected as out-of-universe rather than recognised as the
  sentinel. Fixed with `.strip().upper()` on both paths.
- **P4/P5 — three of the seven `ThesisType` members route to sentinels by
  construction.** Recorded as **O-53**, not repaired: an explicit member
  returning an explicit sentinel is the honest contract for an
  analytical-only thesis.
- **P6/P7 — the result shape is heterogeneous** (dict vs bare string) and
  `gap_direction` was declared but unread. Repaired: `gap_direction` is a
  validated `GapDirection` enum and it is **consumed** — it selects the
  published `direction_word` (`POSITIVE → "steepener"`,
  `NEGATIVE → "flattener"`), so the field now has a consumer and not merely a
  reader (the D-037 class).
- **P9/P10/P11** — curve legs default from config, the degenerate-pair guard
  names its failure, and the confidence is **computed** (`compute_confidence`,
  §22.8) at `0.5` for both sentinel branches — a hardcoded `0.5` was
  deliberately **not** shipped.

### The six genuine test gaps the sweep found

The first sweep run left **6 survivors, all test defects** — the single most
useful output of the increment:

1. **M2.1** — a `("10y","2y")` pair fails *both* the ordering guard and the
   gap guard, so asserting the exception *type* cannot tell which fired.
   Fixed by asserting the exception **message** (lesson 68).
2. **M8.5** — the curve-vocabulary ordering could not be observed because the
   fixture's comment contained `"US HY credit index"`, which does not contain
   the phrase `"equity index"`. Replaced with `"commodity index futures"`.
3. **M8.3** — `permits()`'s fast path is rescued by its own delegate, so the
   mutation is **INERT BY REDUNDANCY** (M8.4, mutating the delegate, *is*
   killed). Proven, not asserted.
4. **CX1 / CX2** — the mutations replaced the config lookup with the literal
   `"2y"` / `"10y"`, which **equalled the config values**, so nothing could
   falsify them. Fixed by moving the config leaf to `3y` / `7y` in the test
   (lesson 71 — a boundary is only as real as the layer that enforces it, and
   lesson 63 — a value equal to the config default cannot falsify a literal).
5. **M6.4** — the published `universe_category` on the executable branch is
   **unobservable** because the agreement guard raises before the mutated line
   runs. Reclassified **INERT BY INVARIANT** with an executed proof; the
   mutation was replaced by one that pins the **guard** instead.

### The three-deep inert taxonomy

`_INERT_PROOFS` for this increment carries **four** entries across **three**
classes, which is the increment's contribution to the harness (recorded as
**O-55**):

| Class | Entries | Why it is inert | Can it expire? |
|---|---|---|---|
| **Unreachability** | `M3.3`, `M6.5` | No admissible input reaches the line | **Yes** — bound/config dependent |
| **Redundancy** | `M8.3` | A delegate performs the same check | Only if the delegate is removed |
| **Invariant** | `M6.4` | An earlier guard raises before the line | Only if the guard is removed |

The previous increments had the first two. The third is new, and the taxonomy
is still reported to the reader as a single undifferentiated column.

### New configuration

`config/settings.yaml` → `instrument_selection:` (line 1488), 7
`CalibratedValue` leaves:

- `thesis_type_routes` — an **envelope** carrying `routes`, one entry per
  `ThesisType` member.
- `curve_default_short_tenor: "2y"`, `curve_default_long_tenor: "10y"`.
- `curve_minimum_leg_gap_years: 1.0`, `curve_maximum_leg_years: 30.0`.
- `is_heuristic_not_calibrated: true`, `source_independence_count: 0` (the
  O-25 literal — this function consumes no independent series).

`settings.instrument_selection` exposes typed accessors; `routes` **validates
the envelope** rather than trusting its shape (the D-048 gate's job).

### The sweep — 31 mutations, 7 groups, three files

`scripts/mutation_instrument_selection.py`:

- **31 / 31 applied, 27 killed, 4 survivors, 0 unexplained.**
- Two harness features were added in this increment:
  `check_tests_collect` (assert the pytest targets actually *collect*, not
  merely exit 0) and a third inert class.
- `check_targets` refused **once** (`CX4`): the anchor I wrote was the
  accessor's **docstring** line rather than the real
  `return {str(key): dict(value) for key, value in raw.items()}`. The D-048
  gate doing its job on its author.
- The honesty control (`M9.1`) is among the **killed**, as it must be.

### The live cross-check

`scripts/live_instrument_selection.py` — **offline by design**, because the
function's inputs are a thesis *label* and a *direction*, not a series; there
is no series that could falsify it. The honest check is therefore a
**cross-check against the real `ProductionUniverse`**, not a re-implementation
(O-43's lesson):

1. Every **8** executable `(thesis_type, direction)` pairs is routed and the
   instrument is submitted to the **real** `ProductionUniverse.permits()`.
2. §22.3.1's curve literal is **re-derived** from the shipped config legs
   (P1's regression guard).
3. Both sentinel branches are confirmed to carry a **computed** confidence of
   `0.5`, not a literal.
4. The default curve legs are asserted to come **from config**, so a
   hardcoded literal would fail here as well as in the unit test.

Print: `LIVE CHECK PASSED`.

### What shipped, and the failure direction

The failure direction of this increment is **false executability** — a
permissive universe check that lets a thesis claim an instrument the production
universe does not contain. It is the fifth distinct direction the project has
named (D-054 → silence, D-056 → false confidence, D-057 → prudence, D-058 →
false executability), and it is guarded on the executable side by the
**agreement guard** and on the sentinel side by the two sentinel constants.

### Carry-overs opened / closed

| ID | Item |
|---|---|
| **O-53** | **NEW (severity 2).** Two `ThesisType` members (`CROSS_COUNTRY_DIVERGENCE`, `EM_VULNERABILITY`) are declared and routable but return a sentinel by construction. **CORRECTED (D-071):** the row originally added *"and `"NONE"` is a legal `TradeIdea.instrument` value, so the sentinel is confusable with an instrument"* — the sentinel is **not** `"NONE"` in the shipped code and never was, and the corrected fact is worse: `is_trade` returns `True` for it, so the sentinel reads as a **live trade in an unexecutable instrument**. See **O-93**. |
| **O-54** | **NEW (severity 1).** The `InstrumentUniverse` `Protocol` is not runtime-enforced; conformance is demonstrated by hand-written test stand-ins, not validated. |
| **O-55** | **NEW (severity 1).** A third inert-proof flavour (**invariant**) now exists across four exemptions in three classes, and the harness reports presence, not class. |
| **O-52** | Sharpened: three flavours now, and the taxonomy is still a single boolean in the summary. |
| **O-25** | Unchanged, one site closer: this function's `source_independence_count` is `0` **because it consumes no series** — an honest zero, not a placeholder. |
| **O-42 / O-44** | Both unchanged. |

---

## Module 15.1 — `construct_duration_weighted_curve_trade` (D-059)

**Second function of Tier 4.** In `models/yield_curve.py`, which is where §15.1b
places it — so this increment had **no layering collision**, unlike D-058's.

### Function

`construct_duration_weighted_curve_trade(inputs: CurveTradeConstructor) ->
ModelResult`. Notional-weights a two-leg curve trade so net duration cancels:
`N_long = N_short · (D_short / D_long)`. This is what actually cancels level
(PC1) exposure, leaving P&L driven by the spread change (PC2). **Equal-notional is
explicitly wrong**, and the function exists so nothing downstream builds one by
mistake. `construct_breakeven_trade` is deliberately a **separate increment**.

Published keys: `notional_short`, `notional_long`, `notional_long_to_short_ratio`,
`duration_dollars_short`, `duration_dollars_long`, `net_duration_residual`,
`net_duration_residual_is_definitional`, `short_tenor`, `long_tenor`,
`short_duration_years`, `long_duration_years`, `direction`.

### What it computes, and the specification's only guard cannot do

§15.1b publishes `net_duration_residual` and warns when `abs(residual) >= 0.01`,
described as *"check duration inputs"*. **That guard is a tautology** — the
residual is the notional's own definition algebraically simplified:

```
residual = (N_s·D_s) − (N_l·D_l)     where  N_l := N_s·(D_s/D_l)
         = (N_s·D_s) − (N_s·(D_s/D_l)·D_l)
         = 0    for every input, correct or not
```

A duration wrong by **ten times** gives an identical result (probe P14), except
for a 2dp rounding artefact of `-0.03726` that the specification's own rounding
introduces and the shipped form avoids by computing the residual **unrounded from
both legs**.

### The measurement: the guard is unreachable, by a 10× margin, under a scale condition

Probe P16 executed a **1377-case** grid (notionals $1e3–$1e12 × duration pairs
0.08y–30y):

| Quantity | Measured |
|---|---|
| residual exactly `0.0` | **1185** (86.1%) |
| residual nonzero (float noise) | **192** (13.9%) |
| worst \|residual\| | **9.766e-04** |
| worst ÷ tolerance (`0.01`) | **0.0977** — a **10×** margin |
| notional at which the guard becomes reachable | ~**$2–5tn** (4 of 144 pairs fire at $5e12) |

**So the proof is scale-conditional, and that condition is O-56.** An exemption
whose argument is "always" and whose truth is "below $2tn" is the overclaim class
this project keeps finding in the specification. The first draft of the proof said
"always 0.0", was not executed, and was wrong.

### The replacement check: a real duration/tenor plausibility band

`CurveTradeConstructor` carries two validators:

* `_legs_must_be_distinct_and_ordered` — short < long, both parsed by
  `_tenor_years`.
* `_durations_must_be_plausible_for_their_tenors` — each leg's
  `duration / tenor` must lie in the configured band. **Measured provenance: the
  floor across 1y–30y and coupons 1e-6–10% is `0.1740`; the zero-coupon limit is
  `1.0000`; the shipped band is `[0.15, 1.05]`.** It catches decimal-vs-percent
  slips, unit mismatches and order-of-magnitude transcription errors, and it is
  **honest about its own strength** in the docstring: it does *not* catch a 2×
  error at short maturities.

### The attestation for the error the band cannot see

`bond_math.macaulay_duration` returns **PERIODS** of **Macaulay** duration; this
contract wants **YEARS** of **Modified** duration. The ratio `D_s/D_l` is
unit-free, so a substitution leaves the notional arithmetically **correct in form**
and the error is **arithmetically invisible** — it shifts the notional by
`(1 + y/f)`, measured at **2.10%** at 2y. `duration_is_modified: bool = True` is a
required attestation; `False` emits a warning that **states the magnitude**,
because a warning that does not say how big the error is cannot be acted on.

### `_tenor_years` — a narrow parser, deliberately

Lower-cases and strips, requires a `y` suffix and a positive number, and
**refuses** `"2yr"` / `"6m"` / `"2w"` / `""` / `"abc"`. `"2yr"` is the spelling
`CurveSlopeInputs` uses and is refused **here on purpose**: this contract reads
*years* for an arithmetic check, and silently normalising a different unit suffix
would hide a unit mismatch.

### The centrepiece: the sweep's first run reported a perfect score, and it was false

| Run | Reported | Truth |
|---|---|---|
| 1st | `31/31 applied, 31 killed, 0 survived` | **FALSE** — a test failed unmutated |
| after repair | `31/31 applied, 26 killed, 5 survived` | all 5 expected and proven |

Almost every 1st-run "kill" named the **same** test
(`test_a_missing_long_leg_tenor_is_refused_before_arithmetic`), which is only
possible if it fails on **shipped** source. It did: it asserted
``implausible for '2y'`` against a validator message naming the **long** leg
(`'3y'`). **The honesty control is what caught it** — a semantically identical
program cannot be killed, so a killed control proves the harness is reporting
kills it cannot justify. D-051 built the control for exactly this; D-059 is the
first time it *fired*.

Diagnosis of the five survivors after the baseline was repaired:

| Mutation | Class | Resolution |
|---|---|---|
| `M6.3` steepener default flips | **real test gap** | the direction test passed `is_steepener` explicitly in both states, so the default was never tested. Two tests added. |
| `M4.5` only the short leg band-checked | **real test gap** | every band fixture used a bad **short** duration. Three tests added (long-leg, long-alone, loop order). |
| `M6.2` unit warning drops the magnitude | **wrong mutation** | the anchor replaced only the first of four concatenated string lines; the asserted phrase lives on the third. Anchor now **slices its target from the source file at import time**, so it cannot drift. |
| `M5.1` residual hardcoded to zero | inert by **construction** | the two programs are identical on the whole input domain. |
| `M3.2` / `M8.3` tolerance leaf | inert by **unreachability** | both substitute `1.05` for `0.01`; the predicate agrees on 153/153 duration pairs at $1e6/$1e9/$1e12. |
| `M9.1` control | **control** | survived, as required. |

### The live cross-check, and the specification finding

`scripts/live_curve_trade.py`, **offline by design** (inputs are durations and
tenors, not series). It validates against **`bond_math`** — a genuinely different
code path — rather than an analytic oracle.

**The cross-check asserts the exact relation, not a convenient equality.**
§15.1b says duration-weighting *"cancels level (PC1) exposure"*. Level
cancellation requires equal **dollar** duration:

```
N_s·P_s·D_s = N_l·P_l·D_l   ⟹   N_l = [N_s·D_s/D_l] · (P_s/P_l)
```

so the shipped rule is exact **only when `P_s = P_l`**. Feet-on-the-ground: a 4.5%
coupon at a 4.3% yield prices the legs at **100.38** and **101.61**, so
duration-weighting is off true level-cancellation by **1.23%** (`P_l/P_s`). The
check confirms the emitted notional equals `N_l(dollardur) · P_l/P_s` to
**0.0004**. For 2y/10y **futures** (both near par) the gap is negligible; for
**cash bonds** it is not. **Recorded as O-57.**

The check also: sweeps **32 real Treasury duration pairs** (8 tenors × 4 coupons)
and confirms all are inside the band; shows the decimal/percent slip is **caught**
and the Macaulay-for-Modified substitution **cannot be**; and closes the
**D-058/D-059 seam** by confirming `select_instrument`'s curve instrument
(`'Duration-weighted 2y/10y UST steepener'`) is admitted by the production
universe as `rates`.

### Two shipped defects found while building the cross-check

* **`price_bond`'s `coupon_rate` docstring says "ANNUAL" while the behaviour is
  per-period.** A par bond requires `coupon_rate == yield_rate`. A caller
  following the docstring gets a bond that is not near par, with no error.
  **O-58.**
* **My own first draft of the cross-check reproduced exactly that error**, and the
  resulting 26% disagreement was initially read as a finding about the
  specification. It was my probe's unit error, **withdrawn before it reached the
  record.** A surprising cross-check result must be attributed before it is
  reported; the cheapest attribution is to check the *inputs* first.

### New configuration

`config/settings.yaml` gains `curve_trade:` — three `mechanical_rule` leaves:

| Leaf | Value | Provenance recorded |
|---|---|---|
| `duration_to_tenor_min` | `0.15` | measured floor **0.1740** across 1y–30y, coupons 1e-6–10% |
| `duration_to_tenor_max` | `1.05` | zero-coupon limit **1.0000**, plus headroom |
| `net_duration_display_pct` | `0.01` | §15.1b's literal, **re-purposed** as display precision — it is no longer presented as a test of the inputs, because it never was one |

**No registry change** — the inputs are durations and tenors, not series. The
confidence is `compute_confidence(ConfidenceInputs(is_heuristic_not_calibrated=
not root_settings.is_calibrated(...), source_independence_count=0))` → **0.7**;
the `0` is an honest zero (§15.19-D applies to series, and this consumes none).

### The sweep

31 mutations, 9 groups, two files (`models/yield_curve.py`, `config.py`).
`check_targets`: **0 problems**, at authoring and again at the close-out re-run
(after `ruff format` touched both new files — the D-058 `CX4` trap).

### Carry-overs

| Issue | State |
|---|---|
| **O-56** | **NEW (severity 2).** The unreachability exemption is a **scale condition** the harness cannot express; it would lapse above ~$2tn notional. |
| **O-57** | **NEW (severity 3).** §15.1b's level-cancellation claim holds only when both legs price alike; whether to weight by dollar duration is a §20.11 interface change. |
| **O-58** | **NEW (severity 2).** `price_bond`'s `coupon_rate` docstring contradicts its behaviour; the fix direction is a breaking change either way. |
| **O-55 / O-52** | Sharpened: a fourth unreachability-flavoured proof now exists, and five exemptions can span four classes with the summary still reporting one column. |
| **O-25** | Unchanged, one site closer: this function's `source_independence_count` is `0` because it consumes no series. |

---

## Module 15.2 — `construct_breakeven_trade` (D-060)

**Placement:** `src/macro_engine/models/yield_curve.py`, immediately after
`construct_duration_weighted_curve_trade` (D-059) and before `_inversion_warnings`.
§15.1b names the module; the two constructors share `CurveTradeSettings`.

**Status:** Implemented. 31 unit tests · 26-mutation sweep (**23 killed, 3
classified survivors**) · offline `bond_math` cross-check **PASSED** · Tier 4
**3 / 11**.

### The specification defect this increment exists for

§15.1b's breakeven constructor publishes **no residual and no `warnings` list** —
no guard of any kind. D-059's sibling at least had one (a tautology, but
observable). So a duration wrong by 10×, a swapped TIPS/nominal pair, or a
`tenor` of `"2yr"` all produced a silent, wrong notional with **no trace**.

### The substantive finding

The rule matches **duration**; the level exposure it claims to cancel cancels on
**dollar** duration. Exact closed form, asserted in the live check to `1e-6`:

```
shipped = N_t·D_t/D_n    exact = N_t·P_t·D_t/(P_n·D_n)
shipped/exact = P_n/P_t  ⟹  exact = shipped · P_tips/P_nom
```

| 48 real configurations, 10y, shipped `bond_math` | |
|---|---|
| correction range | **−56.38% .. +98.72%** |
| sign | **flips** at the TIPS leg's par price (20 over / 28 under) |
| worst case at $10mm TIPS | misstates the nominal leg by **~$5.6mm** |

**Two-signed**, so no constant adjustment hedges it. **O-59**, fix direction a
§20.11 contract change (the contract carries no prices).

### The two corrections to my own work

* The shortfall is **two-signed**, not the one-signed claim my first live-check
  draft asserted. With a par nominal the identity reduces to `100/P_tips − 1`,
  positive exactly when the TIPS is below par.
* The config band note's range `0.7624 .. 1.3790` came from a **simplified probe
  pricer**, not shipped code. Re-measured: `0.6820 .. 1.5528`. The *count*
  (72 of 192) reproduced exactly, the *range* did not — and the ceiling's
  headroom narrowed from a claimed 14% to a real **3%**. **O-60.**

### What the contract validates

`extra="forbid"`; `tenor: str`, `tips_duration`/`nominal_duration` (`gt=0`),
`target_notional_tips` (`gt=0`), `duration_is_modified: bool = True`. Two
validators: per-leg duration/tenor band `[0.15, 1.05]`, and the **ratio** band
`[0.5, 1.6]` plus a refusal of identical legs. The `9.0/10y` vs `2.0/10y` test
pair passes the per-leg band on both legs and fails only the ratio check — so the
two validators are demonstrably not one predicate.

### The twelve published keys

`notional_tips_long` · `notional_nominal_short` · `nominal_to_tips_notional_ratio`
· `duration_ratio_tips_to_nominal` · `duration_dollars_tips` ·
`duration_dollars_nominal` · `net_duration_residual` ·
`net_duration_residual_is_definitional` · `tenor` · `tips_duration_years` ·
`nominal_duration_years` · `duration_direction`.

The residual is definitional (exactly `0.0`), which is why it ships with its
`_is_definitional` flag **beside** it rather than as a check.

### New configuration

| leaf | value | basis |
|---|---|---|
| `curve_trade.breakeven_duration_ratio_min` | `0.5` | measured floor **0.6820** over 192 cases via shipped `bond_math` |
| `curve_trade.breakeven_duration_ratio_max` | `1.6` | measured max **1.5528** — only **3%** headroom, not the 14% an earlier note claimed |

`CurveTradeSettings` gains both `CalibratedValue` fields and their properties.
The confidence is
`compute_confidence(ConfidenceInputs(is_heuristic_not_calibrated=not
root_settings.is_calibrated("curve_trade.breakeven_duration_ratio_min"),
source_independence_count=0))` → **0.7**; the `0` is an honest zero.

### The sweep

26 mutations, 9 groups, two files. `check_targets`: **0 problems**, at authoring
and again at close. **First run: `23 killed / 3 survived`, two unproven — the
harness refused to certify (exit 2).** Resolved rather than excused:

| mutant | classification | resolution |
|---|---|---|
| `M6.1` invert the residual guard | **genuine test gap** | added `test_no_residual_warning_is_ever_published` (D-038's "absence half") → now **killed** |
| `M2.1` publish the notional ratio under the duration key | **name-not-value** | same expression, **byte-identical** output (`1.125481`, executed by hand) → `_EXPECTED_INERT` with the proof |
| `M1.3` residual adds instead of subtracting | exemption **stale** | the new absence test kills it → **removed** from `_EXPECTED_INERT` |

Six anchors are **sliced** from source, because D-059's `CurveTradeConstructor`
sits in the same file with byte-identical validator text — the D-051
sibling-class trap, which fired on six targets during authoring and was fixed by
extending every anchor past the shared prefix.

### Carry-overs

| Issue | State |
|---|---|
| **O-59** | **NEW (severity 3).** The breakeven rule hedges duration, not dollar duration; the correction is two-signed and needs the legs' prices. §20.11 contract change. |
| **O-60** | **NEW (severity 2).** A config note computed by a simplified probe pricer is not reproducible from shipped code; the *count* can reproduce while the *range* does not. O-38's remedy (population **and** producer as data). |
| **O-56** | Reused: the unreachability exemption for `M8.3` carries the same 10× float-noise margin as D-059 — the **second** increment where the same condition justifies the same exemption, which is evidence it is economic rather than a one-off. |
| **O-61** | **NEW (severity 3, incident).** A sweep killed mid-run left `inflation_nowcast.py` and `convergence.py` holding **falsified copies**. The leak was **silent** because a sweep whose anchor no longer matches takes the *pattern-not-found* path and reports a **survivor**, not an error. It surfaced only as 8 failures in the full suite, in modules D-060 never touched — and the first hypothesis ("stale anchor") produced **edits to the anchor and a new test** that both had to be reverted. **Binding interim rule:** never run a sweep in the **background**; never run a **batch** of sweeps while doing anything else. Open remedy: a **clean-tree precondition** (refuse on a dirty tree rather than certify it). **IMPLEMENTED at D-087.27** — and it **reports** rather than refuses, which is a deliberate change of shape from the wording above: a legitimate increment *is* a dirty tree (the operator edits `src/` and then sweeps it), so a veto would forbid the normal workflow and the guard would be deleted rather than obeyed. `scripts/_sweep_gate.py` now exposes `describe_dirty_targets()`, which `sweep_lifecycle` prints **before** it heals — so the warning describes the operator's tree, not the sidecar this run is about to write. The **binding rule is unchanged**: never run a sweep in the background; never run a batch of sweeps while doing anything else. |
| **O-62** | **NEW (severity 2).** A full audit of `scripts/` found **three** broken sweeps: `mutation_drawdown.py` (exit 2, four AMBIGUOUS anchors in `risk_budget.py`, the **D-055** class), `mutation_credit_spread.py` (exit 1, unexplained survivor `C1d` — a hardcoded `0` nothing asserts, the **D-046** shape), and `mutation_convergence.py` (exit 2 *only* because of O-61's leftover — **CLOSED** at `56/53/3` once the tree was restored). `mutation_curve_trade.py` was broken by **D-060's own sibling class** in the same file — the **D-051** trap. Open remedy: a **sweep-health check** that runs every sweep and fails on exit 2/4, on an unexplained survivor, or on a count differing from the recorded baseline. Recorded, not fixed: neither broken sweep is D-060's module. |
| **O-30 / O-38** | Sharpened: O-60 is O-30's class reached from a new direction, and partial numeric agreement is what makes it treacherous. |
| **O-63** | **NEW (severity 2).** A bare `ruff check` reports **1703 errors** and a bare `ruff format --check` reports **36 files to reformat**, because ruff has **no `files` key** in `pyproject.toml` (mypy does — §10.2, D-035) and therefore walks `.probe/` and the scratch trees. The **documented** gate ("`ruff check` clean") is not the **reproducible** one (`ruff check src tests tools scripts` → All checks passed; format → 145 already formatted). Remedy committed as a `pyproject.toml` comment; the open remedy is a single gate script. Same shape as **O-62**: the project's gates are run by hand from prose, and prose cannot refuse. |
| **O-25** | Unchanged, one site closer: this function's `source_independence_count` is `0` because it consumes no series. |

---

## Module 15.3 — `construct_cross_market_rv` (D-062) — **MODULE 15 COMPLETE**

**Placement:** `src/macro_engine/models/yield_curve.py`, after
`construct_breakeven_trade` (D-060) and before `_inversion_warnings`. §20.12 names
no module; the module that already holds the other two constructors is the one its
siblings live in, and all three share the `N·D` convention.

**Status:** Implemented. **50 unit tests** · **41-mutation sweep (40 killed, 1
survivor = the honesty control)** · **pulled** live check **PASSED** · Tier 4
**4 / 11**.

**Signature:** `construct_cross_market_rv(inputs: CrossMarketRVInputs) -> ModelResult`

**Input model:** `market_a`, `market_b` (descriptive labels), `duration_a`,
`duration_b` (MODIFIED years), `target_notional_a` (currency), `correlation_normal`
(`[-1, 1]`), `correlation_stressed` (`[-1, 1]`, **optional** → config),
`duration_is_modified` (attestation, default `True`). `extra="forbid"`, plus two
validators: the two markets must be **distinct** (case- and whitespace-insensitive)
and non-empty, and each duration must sit inside the measured absolute band
`[0.25, 30.0]` years.

**`value` keys (17):** `market_a_long` · `market_b_short` · `notional_a_long` ·
`notional_b_short` · `duration_a_years` · `duration_b_years` ·
`duration_ratio_a_to_b` · `duration_dollars_a` · `duration_dollars_b` ·
`net_duration_residual` · `net_duration_residual_is_definitional` ·
`correlation_normal` · `correlation_stressed` · `correlation_stressed_source` ·
`hedge_degradation` · `hedge_direction` ·
`hedge_degradation_exceeds_plausible_bound`

**Config:** `cross_market_rv:` — `minimum_duration_years 0.25`,
`maximum_duration_years 30.0` (`mechanical_rule`), `max_abs_hedge_degradation 0.5`
(`fitted_assumption`). Three accessors on `CrossMarketRVSettings`. The function is
also the **first consumer** of `RiskSettings.stress_corr`, which had zero callers
anywhere in the tree.

### The specification defect this increment exists for

§20.12 computes `degradation = correlation_normal − correlation_stressed` and
**defaults `correlation_stressed` to the literal `0.9` in the model body**. Over
eight real US cross-market pairs, measured on daily changes in two independent
stress states:

| quantity | measured |
|---|---|
| normal correlation | **−0.623 .. 0.820** |
| stressed correlation, S&P worst decile (n=248) | 0.394 .. 0.858 |
| stressed correlation, VIX ≥ 90th pct (n=928) | 0.262 .. 0.805 |

Every normal correlation is **below** the default, so `hedge_degradation` is
**negative for 8 of 8 pairs**. The specification asserts, universally and
silently, that the hedge **improves** in a crisis — the opposite of the premise
its own docstring states, and the LTCM leverage trap rather than good news.

**The arithmetic is right. The sign is never checked.** This is a **new failure
direction**: *false reassurance* — the number says the risk fell when the risk
rose (after D-054 silence, D-056 false confidence, D-057 prudence, D-058 false
executability).

### The other six specification defects

| # | defect | repair |
|---|---|---|
| 1 | `country="global"` | `ModelResult.country`'s own description says *'"us" only through Phase 4'*; now `"us"` + a mandatory SCOPE warning naming §22.3 and §22.3.1's refusal |
| 2 | **no input contract at all** | `duration_b = 0` divided by zero; one market on both legs priced no trade; correlations unbounded — all refused |
| 3 | the per-leg band cannot be a duration/tenor ratio | a cross-market pair has no shared maturity, and the pairwise ratio is legitimately **0.0161 .. 62.21** — the **absolute** band is the guard |
| 4 | `inputs_used` listed 4 of 7 fields | omits `correlation_stressed`, which the *published value contains*; now all 8 |
| 5 | `confidence=0.5` hardcoded | `compute_confidence`; 0.7 on the shipped config |
| 6 | `hedge_effectiveness_*` were re-exports | two names for one number, published under neither |

### The cross-check, and the seam that CANNOT be closed

`scripts/live_cross_market_rv.py` **calls** `construct_duration_weighted_curve_trade`
(a real call — O-43's lesson) and asserts the shared `N·D` rule agrees exactly on
the same legs, then derives the exact relation through shipped `bond_math`:

```
price of the long leg  = 95.2700    shipped notional         = 2,521,437.45
price of the short leg = 111.9700   dollar-duration notional = 2,145,372.39
ratio shipped/exact    = 1.175291 = P_b/P_a exactly   ->  under-hedges by +17.53%
```

**D-059 and D-060 each closed a round-trip with `select_instrument`. This one
cannot** (**O-66**): §22.3.1's `ThesisType` has **7** members and the routing table
**4** routes, none of them a cross-market relative value; the only member naming
one, `CROSS_COUNTRY_DIVERGENCE`, is blocked precisely because it needs a second
country's rates system — the same reason §22.3 forbids calling this output
`global`. The live check **enumerates the vocabulary and demonstrates the
absence**, so a future route makes the finding fail loudly.

The measured `|degradation|` is **two-signed** (3 of 8 negative on the S&P tail,
4 of 8 on the VIX tail), so no constant adjustment hedges it — **O-59's shape**,
independently reproduced in a third constructor.

### The live check corrected this increment's own config note

The `max_abs_hedge_degradation` note claimed **"about 3x headroom"**, from the S&P
tail alone. The check's headroom assertion counted the VIX tail too and reported
**1.56x**; the note is corrected. **The first time in this project a live check has
corrected a config leaf before the record set was written rather than after.**

### The sweep, and the gate it forced into existence

| run | result |
|---|---|
| 1st | **41 applied / 38 killed / 3 survivors** — harness **REFUSED TO CERTIFY** (two survivors with no proof) |
| after closing the two gaps | **41 applied / 40 killed / 1 survivor (the control), exit 0** |

`M5.5` (the long leg publishing the short market's label) was a **real coverage
gap**: the key-set test cannot see it and the interpretation test reads a
different string. `M8.1` (`confidence=0.5`) **was not a gap at all** — its anchor
occurs **first in `curve_slope`**, so the mutant rewrote a neighbour whose tests
are not in the selection.

An audit of all 41 anchors found **three** mis-targets (`M5.3`, `M6.7`, `M8.1`).
`_slice_source` gained an **`after=`** scope parameter, and the sweep gained
**`check_anchor_landings`** — a gate that refuses to run when an anchor lands in a
symbol the increment does not own. This is the **second mis-target in one
session** (`C1d`, D-061) and it is **O-67**.

Both sibling sweeps were re-run and reproduce their original counts **exactly** —
`mutation_curve_trade.py` **31/26/5**, `mutation_breakeven_trade.py` **26/23/3** —
which is what proves a third constructor in the file did not break them.

### Gates at close

| Gate | Result |
|---|---|
| `uv run ruff check src tests tools scripts` | All checks passed (**149** files) |
| `uv run ruff format --check src tests tools scripts` | **149 files already formatted** |
| `uv run mypy --strict src tests tools scripts` | no issues in **149** source files |
| `uv run pytest -q` | **1633 passed, 1 skipped, 0 failed** (was 1583/1) |
| `uv run python scripts/mutation_cross_market_rv.py` | **41 applied / 40 killed / 1 survivor (the control)**, exit 0; re-run at close identical |
| `uv run python scripts/live_cross_market_rv.py` | **LIVE CHECK PASSED** (pulled: 8 pairs, two stress states) |
| `uv run python tools/sweep_health.py` | **OK — 30 sweeps, 0 failures, 0 leftovers** |
| `mutation_curve_trade.py` / `mutation_breakeven_trade.py` | **31/26/5** and **26/23/3** — reproduced exactly |
| `mutation_credit_spread.py` / `mutation_drawdown.py` | **34/33/1** and **47/46/1** — both repaired (D-061) |

### Carry-overs

| Issue | State |
|---|---|
| **O-64** | **NEW (severity 2).** §20.12's own text still says `country="global"`. The code publishes `"us"`; the specification needs the amendment. |
| **O-65** | **NEW (severity 2).** `risk.stress_correlation = 0.9` is not reproducible from any measured pair (worst 0.858 / 0.736) and, as §20.12's default, makes the published degradation negative on every real pair. |
| **O-66** | **NEW (severity 2).** No `ThesisType` names a cross-market RV, so the `select_instrument` seam cannot be closed. |
| **O-67** | **NEW (severity 2).** `check_targets` proves uniqueness, not landing site; only this sweep has `check_anchor_landings`. |
| **O-62** | **Discharged.** All three broken sweeps repaired; `tools/sweep_health.py` now exists and reports 0 failures. Still run by hand, not CI (which is itself **O-62**'s residual half). |
| **O-57 / O-59** | **Extended, not resolved.** The `N·D`-vs-`N·P·D` gap is now reproduced in a **third** constructor, and the correction remains two-signed. |
| **O-61** | **Recurred live and was caught.** An interrupted legacy sweep left `MX3d` applied in `yield_curve.py`; the sweep-health leftover scan found it. |
| **O-56** | Unchanged. The definitional residual's float-noise margin is **2.6×** here (worst 3.906e-03 against a 0.01 tolerance), tighter than D-059's 10× because this contract's duration pairs are longer. |
| **O-25** | Unchanged: `source_independence_count=0` is an **honest zero** — the inputs are caller-supplied correlations and durations, not series. |

---

## Module 14 — `derive_invalidation_conditions` (D-063)

**Placement:** `src/macro_engine/thesis_layer/invalidation.py` — a **new module**,
and the first Tier 4 function to live in `thesis_layer/`. §16.4 declares it beside
`build_us_macro_thesis`; the builder does not exist yet, so this ships in its own
module rather than a half-built `builder.py`.

**Status:** Implemented. **37 unit tests** · **24-mutation sweep (23 killed, 1
survivor = the honesty control)** · **pulled** live check **PASSED** · Tier 4
**5 / 11**.

**Signature (DIVERGES from §16.4):**
`derive_invalidation_conditions(growth, inflation, labor) -> InvalidationAssessment`

§16.4 declares `-> str`. The divergence is deliberate and is the increment's
central repair: a bare `str` **cannot represent "no falsifier was found"** in a
way the LTCM gate can consume, because both states are non-empty strings. The
schema field stays `str` and the builder passes `.text`.

**Published models:** `InvalidationCondition` (`model_name`, `trigger`,
`observed_value`, `threshold`, `statement`) · `UnreadableInput` (`model_name`,
`value_type`, `reason`) · `InvalidationAssessment` (`conditions`, `unreadable`,
`neutral`, `text`, `identified`, `reason`, `as_of`) — all `frozen=True,
extra="forbid"`.

**`InvalidationTrigger`:** `crosses_back_positive` | `crosses_back_negative` |
`agreement_collapses`.

**Config:** `invalidation:` — `zero_crossing_threshold 0.0` and
`supporting_agreement_class "HIGH"`, both `mechanical_rule`. Two accessors on
`InvalidationSettings`.

### The specification defect this increment exists for

§20.15's `derive_invalidation_conditions` **cannot execute against the output of
the model its own docstring names**:

```python
if inflation.value < 0:   # inflation_convergence_classifier publishes a DICT
```

`TypeError: '<' not supported between instances of 'dict' and 'int'`.

**Reproduced on real data** — 8 live FRED series driving the real
`inflation_convergence_classifier`, whose verdict is
`InflationConvergenceVerdict(...).model_dump()`. The crash is **latent** rather
than immediate: §16.2's Q1 passes `inflation_breadth_score` (a float), so the
builder's current call path survives — while §20.15's docstring names the
dict-valued model. The same section's `build_confirmation_signals` guards its
comparisons with `isinstance(result.value, (int, float))`.

### The other three defects

| # | defect | class | repair |
|---|---|---|---|
| 2 | **`growth` is declared and never read** | D-037 | read symmetrically; `test_the_growth_leg_changes_the_output` is the pin |
| 3 | **the fallback sentence SATISFIES the LTCM gate it says is unmet** | D-052 | `text` is **empty** when nothing was identified, so the gate fires |
| 4 | **the model §20.15 names is direction-blind** | D-063 | an agreement classifier gets an **agreement-collapse** falsifier, never a reversal |

Defect 3 measured: `TradeIdea(instrument="UST 2yr note futures", direction="long",
stop_or_invalidation=<the fallback>)` is **accepted**, `is_trade=True`.

Defect 4 measured: `InflationConvergenceVerdict.model_fields` contains **no**
direction or sign field, and `classification` ∈ `HIGH / MEDIUM / LOW /
CONFLICTED` — agreement **strength**, with `agreeing` the majority **count**, not
the majority **side**.

### The narrowing, and why it is the contract

`ModelResult.value` is a union, so this function's real subject is *which shapes
it can read*:

| shape | read as | else |
|---|---|---|
| `int`/`float`, **excluding `bool`** | a signed scalar → a reversal falsifier | — |
| `dict` whose `classification` ∈ the classifier's own `CONVERGENCE_CLASSES` | a verdict → an agreement-collapse falsifier | — |
| anything else | — | **reported** in `unreadable`, with its type |

`bool` is excluded **first** because `isinstance(True, int)` is `True`, so a flag
would otherwise read as a score of `1.0`. The verdict membership test is against
the classifier's **published** vocabulary rather than a re-typed list, so a member
added without this function learning about it is reported rather than accepted.

A signal sitting **exactly on** the crossing produces **no** condition and is
listed in `neutral`: absence of direction is not evidence, the principle the
classifier states for its own flat readings.

### The cross-check

The gate, exercised end to end on real output: a real falsifier is **accepted** by
`TradeIdea`; the specification's fallback is **also accepted** (the defect); and
the shipped assessment's empty `text` is **refused** with
*"A live trade idea must carry a non-empty stop_or_invalidation"*. That is the
LTCM hard gate becoming load-bearing rather than satisfiable by a sentence.

### Gates at close

| Gate | Result |
|---|---|
| `uv run ruff check src tests tools scripts` | All checks passed (**153** files) |
| `uv run ruff format --check src tests tools scripts` | **153 files already formatted** |
| `uv run mypy --strict src tests tools scripts` | no issues in **153** source files |
| `uv run pytest -q` | **1670 passed, 1 skipped, 0 failed** (was 1633/1) |
| `uv run python scripts/mutation_invalidation.py` | **24 applied / 23 killed / 1 survivor (the control)**, exit 0; re-run at close identical |
| `uv run python scripts/live_invalidation_check.py` | **LIVE CHECK PASSED** (8 real series, 4 real upstream models) |
| `uv run python tools/sweep_health.py` | **OK — 31 sweeps, 0 failures, 0 leftovers** |

### Carry-overs

| Issue | State |
|---|---|
| **O-68** | **NEW (severity 3).** The LTCM hard gate is a **presence** check on a field whose sentinel value is a valid presence. Repaired for this caller; any other caller can still pass the fallback sentence. |
| **O-69** | **NEW (severity 2).** §16 names three different inflation models for one argument slot. |
| **O-70** | **NEW (severity 2).** The Q8 round-trip is asserted against a hand-built `TradeIdea`; `build_us_macro_thesis` does not exist, so the caller's seam is untested. |
| **§16.4 divergence** | **Recorded in D-063.** The return type is `InvalidationAssessment`, not the declared `str`. |
| **O-25** | Unchanged: this function consumes no series, so it has no `source_independence_count` to report — the honest zero is structural. |
| **O-29** | Unchanged: 14 sweeps still carry no `check_targets`; this one carries **both** gates. |

---

## Module 12 — `build_scenario_distribution` (D-064)

**Tier 4 · 6 / 11.** §16.4's outcome set: a `MarketPricingGap` plus a
`ConvergenceClassification` become four `ScenarioOutcome`s that the payoff
contract can consume. **This increment was RECOVERED rather than started** — an
interrupted session had left the function, its 38 tests, its config block and
`tools/sweep_health.py`'s extension on disk, with **no record of any kind**. Every
gate passed on the code as found, which is why "it passes" is not this project's
standard: the gates answer *does the code behave?*, not *is the increment
complete?* (lesson 92).

### The headline finding — a "validated" declaration that validates nothing

§16.4 declares the payoff unit as
`payoff_unit: Literal["fraction_of_capital"] = Field(description=...)`. A
**one-member `Literal` with a description and no `default=`** is still
**optional** to pydantic. Measured both ways:

| | old declaration | shipped declaration |
|---|---|---|
| `KellyInputs(scenarios=<bp distribution>, limits=..., payoff_unit="bp_pnl_proxy")` | `literal_error` (the value is not in the one-member set) | **`ValidationError` naming the unit** |
| `KellyInputs(scenarios=<bp distribution>, limits=...)` | **accepted**, labelled `fraction_of_capital` | **`missing`** |

So a basis-point payoff entered the Kelly arithmetic as a fraction of capital,
with **no error**, producing the *smaller* and cap-slipping number O-50 predicted
— toward **prudence**, the D-057 failure direction. **The defect is not that the
value was wrong; it is that the vocabulary had one member, so there was no wrong
value to pass.** The repair has two halves and neither alone suffices:

1. the vocabulary is **widened** to `KellyPayoffUnit = Literal["bp_pnl_proxy",
   "fraction_of_capital"]`, so the wrong unit is **nameable**; and
2. the field is made **required**, with an explicit **named refusal** in
   `_reject_units_the_arithmetic_cannot_use`, so naming it is what fails.

### Three further §16.4 defects, and a fifth found only live

| # | Defect | Where | How it shows |
|---|---|---|---|
| 1 | Four hardcoded probabilities **and** four payoff multipliers as literals | §16.4 | they are the config leaves (§21) — and `ScenarioOutcome` validates they **sum to 1**, so the leaves are **not independently settable** (O-41's shape) |
| 2 | An unconvertible `gap.unit` | the function | refused by name rather than coerced — the arithmetic has no meaning for it |
| 3 | `not gap.is_meaningful` / `magnitude_bp == 0.0` | the function | **raise** rather than distribute a zero-magnitude gap — Q6 should have routed it to no-trade |
| 4 | `ConvergenceClassification` boundary parse | the function | the verdict is re-parsed at the boundary so a `dict` from the classifier is read against its **own** vocabulary |
| 5 | **The distribution is DIRECTION-BLIND** | **found live** | a **+1.0%** and a **−1.0%** gap produce **byte-identical payoffs and probabilities** |

Defect 5 was invisible to all 38 unit fixtures because **every one of them used
`+1.0`**, while the live gap is **negative** (`model_below_market`, **−1.00%**).
Recorded as **O-71**; it is a **modelling** decision (relabel sign-symmetrically,
or branch directionally), so it is disclosed rather than guessed. Lesson 91: *a
fixture that holds a variable constant cannot falsify dependence on that
variable, however many fixtures you write.*

### The sweep, and the two harness defects it exposed

`scripts/mutation_scenario_distribution.py` — **23 mutations in 8 groups across
five files** (`thesis_layer/scenarios.py`, `models/probability.py`, `config.py`,
`portfolio/risk_budget.py`, `thesis_layer/schemas.py`).

| Gate | Result |
|---|---|
| `check_targets` | **0 problems** after one correct AMBIGUOUS refusal (`unit="bp_pnl_proxy",` occurs **4×**; re-anchored through the base branch) |
| `check_anchor_landings` | **refused 4 false mis-targets on first run** — the gate was itself defective (see below) |
| final | **23 applied / 22 killed / 1 survivor (the control)**, exit 0 |

**The shared landed-checker was manufacturing findings.** `check_anchor_landings`
resolved an anchor's owning symbol by walking backwards to a line beginning
`def ` or `class ` — which is **also true of a prose comment** (lesson 88). It
therefore attributed `KellyPayoffUnit` to `volatility_target_scaling`, **150 lines
away**, and refused four sweeps over a mis-target that did not exist. Fixed by
resolving the owner through **`ast.parse`**, with `end_lineno` bounding each
symbol, in `tools/sweep_health.py` and inlined into the new sweep (`tools/` has no
`__init__.py`, so importing it made one file **two** modules under `mypy`).

**The honesty control was a no-op.** Its first draft was `old == new`, so it was
never APPLIED and could be **neither killed nor survived** — and the harness
**refused to certify** on exactly that ground. Replaced with a real rewrite that
re-wraps the same three string literals across three lines into a
**byte-identical** value: the source changes, the program does not (lesson 89).

**The repaired control then killed a stale test** —
`test_the_distribution_is_consumable_by_the_kelly_contract` asserted
`literal_error` while **omitting `limits`**, which **could not pass unless
`payoff_unit` was optional**. The test's own shape was the independent proof that
the default was load-bearing, and it had been written by the session that was
about to certify the opposite (lesson 90). Rewritten to pin both directions:
supply `limits` → `value_error`; omit the unit → `{"missing"}`.

### The `KellyPayoffUnit` type, and why the derivation is a test

`KellyPayoffUnit = Literal[*get_args(PayoffUnit)]` is **runtime-correct** and
`mypy --strict` rejects it (*"Invalid type alias: expression is not a valid
type"*). The literal is written out and the derivation is enforced by
`test_the_consumer_vocabulary_is_derived_from_the_producers` — a **set-equality
assertion over `typing.get_args`**: strictly **weaker** as a type, **louder**
than a silent drift. Recorded as **O-73** so the trade-off is deliberate.

### The live check

`scripts/live_scenario_check.py` — **pulled, not offline**: three real upstream
rule models (`taylor_rule`, `balanced_approach_rule`, `first_difference_rule`)
over live FRED series → `canonical_policy_gap` → the shipped function. Real values
at close:

| Quantity | Live value |
|---|---|
| core PCE | **+2.1676%** |
| output gap | **−0.2497%** |
| fed funds | **3.6300%** |
| gap | **−1.00%** |
| dispersion | **0.67** |
| `is_meaningful` | `True` |
| direction | `model_below_market` |

Ten numbered assertions, all CONFIRMED — and the negative live gap is what
exposed defect 5.

### Gates at close

| Gate | Result |
|---|---|
| `uv run ruff check src tests tools scripts` | All checks passed (**157** files) |
| `uv run ruff format --check src tests tools scripts` | **157 files already formatted** |
| `uv run mypy --strict src tests tools scripts` | no issues in **157** source files |
| `uv run pytest -q -m "not live"` | **1705 passed, 1 skipped, 5 deselected, 0 failed** (was 1670/1) |
| `uv run python scripts/mutation_scenario_distribution.py` | **23 applied / 22 killed / 1 survivor (the control)**, exit 0 |
| `uv run python scripts/mutation_kelly.py` | **27 / 27 killed, 0 survivors** — extended from 25 so the seam is covered from both sides |
| `uv run python scripts/live_scenario_check.py` | **LIVE CHECK PASSED** (3 real rule models, live FRED) |
| `uv run python tools/sweep_health.py` | **OK — 32 sweeps, 0 failures, 0 leftovers** |

### O-61 recurred live — FOUR TIMES in this increment, and the last one was the worst

A `SIGTERM` on the kelly sweep **bypassed the `finally` restore** and left `M9.1`
applied in `risk_budget.py` (`clipped = bool(final_fraction < requested) is
True`). It also **corrupted two unrelated anchors** whose text the leftover had
destroyed, so `check_targets` then reported them **ABSENT** — a **manufactured**
finding, lesson 88's shape again. An earlier restore repaired the anchors but
**left the `clipped` line mutated**, and a later `ruff format` run then **baked the
residue into the record set**.

**It was caught at close-out, by an accident of arithmetic.** `mutation_kelly.py`
reported **25 applied / 27** with `M5.5` and `M9.1` as **"NOT APPLIED (no-op)"** —
their shared anchor `_M5_CLIPPED_FLAG` (`    clipped = final_fraction <
requested`) no longer matched. Three things make this the worst instance:

1. **`tools/sweep_health.py` reported 0 leftovers BOTH before and after the fix.**
   Its detector searches for the mutation's *replacement* string, and `M9.1`'s
   replacement was already in the source — which is the corruption. That is
   **O-72**'s blind spot demonstrated rather than theorised.
2. **The sweep still CERTIFIED.** `25/27`, 0 survivors, and the summary line read
   *"every survivor is either expected or proven inert"* — a **no-op is not a
   survivor**, and the denominator silently shrank. A narrowed run read as a pass.
3. **Every gate the project runs was green on the corrupted tree** — ruff, format,
   mypy, and **1705 passing tests**. The mutation is semantically identical
   (`bool(x) is True` equals `x` for a `bool`), so **no test could fail**. Only a
   semantic diff against the shipped baseline would have caught it.

Restored to `clipped = final_fraction < requested`; `mutation_kelly.py` then
reproduced **27/27 killed, 0 survivors** exactly, which is what confirms the
restore. **O-61's binding rule was violated again and this increment is the
argument that ends the debate: the clean-tree precondition is no longer a
nice-to-have.** A second, cheaper remedy this produced: **a sweep should REFUSE
when any mutation reports `NOT APPLIED`** rather than dropping it from the
denominator and certifying — a no-op means the anchor no longer describes the
code, which is exactly the state a leftover produces.

### Carry-overs

| Issue | State |
|---|---|
| **O-50** | **CLOSED.** The `payoff_unit` seam is fixed on both halves; the *class* (any one-member `Literal` whose producer can emit a member it excludes) remains open. |
| **O-51** | **CLOSED.** `ScenarioOutcome` / `MarketPricingGap` are now re-exported from the models layer, so the layers cannot drift. |
| **O-71** | **NEW (severity 3).** The distribution is **direction-blind**; a modelling decision, disclosed meanwhile. |
| **O-72** | **NEW (severity 2).** `sweep_health.py` cannot see a **stale kill**, and runs by hand rather than in CI. |
| **O-73** | **NEW (severity 2).** A derived type alias cannot be expressed in the type system; the derivation is enforced by a test. |
| **O-61** | **Re-confirmed incident.** Third recurrence; caught by the tool. Clean-tree precondition still the remedy. |
| **O-67** | **Sharper.** `check_anchor_landings` now exists in **two** sweeps and its **first version was itself a defect**; back-port the **fixed** version. |
| **O-29 / O-25** | Unchanged. 14 sweeps still carry no `check_targets`; this one carries **both** gates. |

---

## Module 13-adjacent — `next_catalyst_calendar` (D-065)

**Function:** `next_catalyst_calendar(as_of=None) -> list[str]`
**Location:** `src/macro_engine/thesis_layer/catalysts.py` (new module)
**Config:** `config/settings.yaml` → `catalyst_calendar:` +
`CatalystCalendarSettings` in `src/macro_engine/config.py`
**Spec:** §16.4, AGENTS.md:3631 (stub) and :3304 (the `TradeIdea.catalysts=`
call site)
**Tier:** 4 #7 · **Phase 2** at **82/98 (84%)** · **Tier 4** at **7/11**

### Why this is a source probe, not a code change

The stub returns three hardcoded strings that **name a source and carry no
date**. §16.4 requires FRED `release/dates` + `federalreserve.gov` and forbids
third-party calendars. So the work was to determine what those two endpoints
actually return — and they turned out to be wrong in five distinct ways, none
discoverable from a fixture.

### The five source defects, all measured live

| # | Defect | Measurement | Consequence if ignored |
|---|---|---|---|
| 1 | `ptic` is a **pagination total**, not an event count | `ptic=2806`; page 1 holds **50** rows | A "count of catalysts" is wrong by **56x**, silently |
| 2 | The **unfiltered** FRED path is **one request per calendar day** | 90-day window → **90** requests (`economic_calendar.py:188-192`) | Reliable `TimeoutError` on any real window |
| 3 | FRED release **101** `"FOMC Press Release"` answers for **EVERY calendar day** | **41 / 41** days in a 40-day window | "Next FOMC" = **tomorrow, every day, forever** |
| 4 | **Flattening the Fed's HTML to text invents meetings** | real trailing note `"Note: A two-day meeting is scheduled for January 25-26, 2028."` → flat parse emits a phantom 2027 January; **55 hits vs 53 structured** | A calendar with a meeting that does not exist |
| 5 | The endpoint **drops `urllib` and `aiohttp`** by TLS/HTTP fingerprint | `urllib` → `RemoteDisconnected`; `aiohttp` → `TimeoutError`; `curl` → 200; `httpx`/HTTP-1.1 → 200 | This is *why* `obb.economy.calendar` times out for this project — OpenBB's FRED provider is `aiohttp` |

Defect 3 is the dangerous one: it **returns plausible, dated, wrong data every
day** rather than failing. Defect 5 explains a symptom recorded in an earlier
probe but never diagnosed.

### What the implementation does about each

| Defect | Handling |
|---|---|
| 1 | `ptic` is **never read**. Only the `release_id`-filtered path is used. Pinned by `test_ptic_is_never_read_as_a_count` (a `ptic` of 2806 against a 3-event pager must not change the output) |
| 2 | Every FRED request goes through `_FRED_CALENDAR_URL` with `rid` set — one paginated call per release |
| 3 | The FOMC catalyst is read from **`federalreserve.gov`**, which is what §16.4 names. Pinned by `test_fomc_dates_come_from_the_fed_not_fred` (kills FRED and requires FOMC to survive) and `test_a_daily_feed_would_be_rejected_as_a_meeting_calendar` |
| 4 | The Fed page is parsed through the **structured** `fomc-meeting__month` / `fomc-meeting__date` pair, never flattened text. Pinned by `test_the_structured_markup_is_read_not_the_flat_text`, whose fixture carries the page's **real** 2028 note verbatim |
| 5 | Transport is **`httpx` with `http2=False`** — already a project dependency (`data_layer/openbb_client.py`) |

### Three defects found in the increment's own code

1. **A warning that fired on correct data.** The release-id/name guard compared
   `"CPI"` against `"Consumer Price Index"`, so it warned on **every healthy
   call**. Fixed to compare the full release name; pinned by
   `test_a_correctly_labelled_calendar_is_silent` — a guard needs a test that it
   does **not** fire.
2. **The horizon bounded the request but not the result.** A **1-day horizon
   still returned a 60-day event**, because a query parameter cannot *un-return*
   a row. The bound is now applied **locally** as well. Found by a test written
   to kill `M1.3`, which killed a real defect instead.
3. **A fixture that could not reproduce its own defect.** The synthetic FOMC note
   had no year, so the flat-text mutant produced no phantom and `M4.1`
   **survived**. Fixed by copying the real note; the live check now measures the
   phantom on the live page.

### Config — `catalyst_calendar`

| Leaf | Value | Status | Note |
|---|---|---|---|
| `cpi_release_id` | `10` | `institutional_convention` | FRED's identifier, not a choice. Live-verified to return "Consumer Price Index" |
| `nfp_release_id` | `50` | `institutional_convention` | Live-verified: "Employment Situation" |
| `pce_release_id` | `54` | `institutional_convention` | Live-verified: "Personal Income and Outlays" |
| `horizon_days` | `120` | `uncalibrated_illustrative` | Covers ≥1 of each monthly catalyst plus 2–3 FOMC meetings (**O-75**) |
| `http_timeout_seconds` | `30.0` | `institutional_convention` | ~30x the measured response time (~1.0s FRED / ~0.6s Fed) |

The block carries **one cross-leaf assertion**: the three release ids must be
**distinct** (`_release_ids_must_be_distinct`), because two catalysts sharing an
id publish it twice and drop a catalyst, and no single leaf shows which moved.
Killed by `M8.1` / pinned by `test_release_ids_are_distinct`.

### Gates at close

| Gate | Result |
|---|---|
| `ruff check src tests tools scripts` | **All checks passed** (161 files) |
| `ruff format --check src tests tools scripts` | **161 files already formatted** |
| `mypy --strict src tests tools scripts` | **no issues in 161 source files** |
| `pytest -q -m "not live"` | **1722 passed, 1 skipped, 6 deselected** (+17 new) |
| `pytest -m live -k catalyst` | **1 passed** |
| `scripts/mutation_catalyst_calendar.py` | **10 applied / 8 killed / 2 survivors (1 control, 1 inert), exit 0** |
| `scripts/live_catalyst_calendar_check.py` | **passes end to end** |
| `tools/sweep_health.py` | **33 sweeps, 0 failures, 0 leftovers** |

### The sweep, in full

```
applied 10 / 10
killed  8
survived 2
  [inert]   M2.1 ptic is read as the event count   (dead assignment; proves nothing)
  [control] M7.1 the FOMC entry string is rebuilt with the same parts
RESULT: every survivor is either expected or proven inert.
```

**The first full run REFUSED TO CERTIFY** with four survivors — `M1.3` and
`M4.1` carried no proof and were **real test gaps**. Chasing them produced two of
the three self-defects above. The harness also **caught its own anchors moving**
when the horizon fix rewrote them, refusing rather than mutating a stale site.
**`refuse_on_noop` is on**: an unapplied mutation is a **refusal**, not a note —
D-064's lesson 93 implemented rather than remembered.

### The live check, in full

1. Both hosts answer over **httpx/HTTP-1.1** (FRED 2266 chars, Fed 167 489).
2. All three release ids **still name** their expected releases.
3. Four dated catalysts, ordered, all within the horizon:
   PCE 2026-09-30 · NFP 2026-10-02 · CPI 2026-10-14 · FOMC 2026-10-28.
4. **FRED `rid=101` covers 41 of 41 days (100%)** — "the next FOMC" = *today*.
5. The **flat parse invents 2 phantom meetings** (55 vs 53) on the real page.
6. A **1-day horizon returns 0** entries, proving the local bound applies.

### Carry-overs

| Issue | Status |
|---|---|
| **O-74** | **NEW (severity 2).** Two live hosts at thesis-build time, up to four requests, **no cache**. Failure direction is a silently shorter calendar (D-054 one layer up). |
| **O-75** | **NEW (severity 2).** `horizon_days` is uncalibrated and its failure is **asymmetric**: short = silence, long = noise. |
| **O-76** | **NEW (severity 1).** The projections marker is **prose in a string**, so branching on "is this a SEP meeting" means re-parsing our text. Fix is a typed catalyst object — a schema change, hence its own increment (§22.13). |
| **O-72** | **Partially addressed** — `refuse_on_noop` written into this sweep only; 32 others still certify with a narrowed denominator. `sweep_health.py`'s stale-kill blind spot and manual invocation remain. |
| **O-29** | Unchanged — 14 sweeps still carry no sweep-owned gate; this one carries both. |
| **O-70** | Unchanged and closer — `build_us_macro_thesis` must still pass `invalidation.text`, route to `no_trade_thesis`, **and** supply a real `catalysts=` from this function. |

---

## Module 14 — `build_confirmation_signals` (D-066)

**Function:** `build_confirmation_signals(growth, inflation, labor, gap) -> ConfirmationSignalAssessment`
**Location:** `src/macro_engine/thesis_layer/signals.py` (new module)
**Config:** **none** — the increment attempted a `confirmation_signals:` block and
the infrastructure gate correctly refused it (see below)
**Spec:** §16.4 Q7, AGENTS.md §16.4 / §16.2 Q7, and §22.10-Finding #10 (the
`direction` vocabulary)
**Tier:** 4 #8 · **Phase 2** at **83/98 (85%)** · **Tier 4** at **8/11**

### What exists now

| Symbol | Kind | Purpose |
|---|---|---|
| `build_confirmation_signals` | function | Q7: one signal per model, labelled by the model actually read |
| `ConfirmationSignalAssessment` | frozen model | `signals` + `unreadable` + `agreeing`/`disagreeing`/`neutral` census |
| `UnreadableConfirmationInput` | frozen model | `source_model`, `value_type`, `reason` — the typed bucket a bare list could not hold |
| `_signed_scalar(value)` | helper | Narrows `ModelResult.value` to a usable number, **excluding `bool` first** |
| `_direction_for(value, gap_sign)` | helper | The three-outcome branch: zero → `neutral`, zero gap → `neutral`, else signed comparison |
| `_gap_sign`, `_family_of`, `_detail_for` | helpers | Gap sign, provenance pass-through, interpretation + warning token |
| `_SLOT_FALLBACK_NAMES`, `_WARNING_MARKER` | module constants | Slot fallbacks and the display token — deliberately **not** config leaves |

`ConfirmationSignal` itself is unchanged (it is §7's schema, owned by
`thesis_layer/schemas.py`). This module **produces** it.

### The headline — a bare `else` claims every case the author did not enumerate

§16.4 derives `direction` from a single condition and a bare `else`:

```python
direction = "confirms" if (isinstance(result.value, (int, float)) and
                            ((result.value < 0 and gap.raw_gap < 0) or
                             (result.value > 0 and gap.raw_gap > 0))) else "contradicts"
```

Two branches for **three** schema members (`confirms`, `contradicts`, `neutral`;
§22.10 / Finding #10). The `else` is not "otherwise nothing" — it is everything the
condition did not enumerate, and four such outcomes were **measured**:

| input | §16.4 says | what it is | shipped |
|---|---|---|---|
| `{"classification": "HIGH"}` | `contradicts` | a **dict**; published by `four_pillar_scorecard` and `inflation_convergence_classifier` | `neutral` |
| `0.0` | `contradicts` | the balance point — no sign to agree or disagree with | `neutral` |
| `True` | `contradicts` | a flag; **passes** `isinstance(x, (int, float))` | `neutral` |
| `0.5` vs a **zero** gap | `contradicts` | non-zero value, no reference direction | `neutral` |

**The defect is not a wrong direction; it is a direction that was never derived** —
D-056's false-confidence direction. The repair is not a better `else`; it is to make
the unrepresentable case **representable**: a third branch for `neutral`, plus a
typed `unreadable` bucket on the return so "I could not read this" is a value rather
than a mislabelled `contradicts`.

### O-69's full extent, measured

| location | the three labels |
|---|---|
| §16.4 `build_confirmation_signals()` | `output_gap`, **`inflation_convergence`**, `labor_tightness_score` |
| §7.1 golden JSON sample | `labor_tightness_score`, **`inflation_breadth_simple`**, **`curve_slope`** |
| §16.2 Q1 actual calls | `output_gap`, **`inflation_breadth_score`**, `labor_tightness_score` |

**Six distinct labels, three slots, one in common — and `curve_slope` is not a
parameter of this function at all.** A `source_model` is how a reader finds the
model that made a claim, so a label naming a model the builder never called is
**worse than a missing one**. The shipped function derives each label from
`result.model_name`; the slot name is a fallback for an empty `model_name` only.

### Three further §16.4 defects

1. **`source_family` never populated** — §6.6b requires it for the independence
   classification, the field exists for it, and the sample leaves it `None` on every
   entry. The count is **unreachable**, not wrong. Now carried from
   `result.source_family`.
2. **`detail` = raw `interpretation`** — a signal can undercut itself unflagged,
   because sub-measure disagreement and a signed average are different questions.
   Interpretation kept verbatim; the model's warning count appended under a stable
   token, so the caveat is a field rather than a phrase.
3. **The return type cannot carry Q7's second half** — `list[ConfirmationSignal]`
   has nowhere to put "could not be read", which is *why* the fall-through happened.
   Return is now `ConfirmationSignalAssessment`.

### The refused config leaf, and why the refusal was right

The first draft declared

```yaml
confirmation_signals:
  disagreement_marker:
    value: "model_warnings"
    status: uncalibrated_illustrative
```

and a `ConfirmationSignalSettings` root registration with a `marker` property.
`test_every_calibrated_leaf_has_a_numeric_property_accessor` **failed it**: the
guard's accepted routes are a **numeric** `.property` or `Settings.scalar()`, and
`scalar()` returns `float`. **The envelope was the wrong shape, not the accessor.**
A display token is not a fact about the economy, a convention, or an uncalibrated
placeholder — which is all §10.4 scopes `settings.yaml` to. Both edits were reverted;
`_WARNING_MARKER` is a module constant beside `_SLOT_FALLBACK_NAMES`.
`test_the_marker_is_a_module_constant_not_a_config_leaf` pins the decision **and**
asserts no `confirmation_signals` block exists, so the wrong shape cannot quietly
return.

### The live-check defect found in this increment's own probe

The first live check hand-rolled the growth leg (`.iloc[-1]` on `GDPC1` and
`GDPPOT`) and returned an output gap of **−17.57%**. `GDPPOT` is a **CBO projection
series** whose last observation is **2036-10-01** — comparing 2026 actual output to
2036 projected capacity, with **no error raised**, because the arithmetic is valid.

| path | result | withheld |
|---|---|---|
| hand-rolled `.iloc[-1]` per series | **−17.57%** | — |
| `output_gap_from_snapshot` | **+0.83%** | **42** forward points |

Only **plausibility** exposed it. Both the check and the live test now go through the
real plumbing and assert `|gap| <= 15%`.

### Gates at close

| Gate | Result |
|---|---|
| `ruff check` / `format --check src tests tools scripts` | clean, **165 files** |
| `mypy --strict src tests tools scripts` | no issues, **165 source files** |
| `pytest -q -m "not live"` | **1754 passed, 1 skipped, 7 deselected** |
| `mutation_confirmation_signals.py` | **9 applied / 8 killed / 1 survivor (control)**, exit 0 |
| `live_confirmation_signals_check.py` | **passes** (5 checks) |
| `tools/sweep_health.py` | **34 sweeps, 0 failures, 0 leftovers** |

### The sweep, in full

9 mutations in **8 groups** across **two** files, with `check_targets`,
`check_anchor_landings`, `check_tests_collect` and **`refuse_on_noop`** all on.

| Group | Mutation | Killed by |
|---|---|---|
| M1 | unreadable value → `contradicts` (the §16.4 behaviour) | the `dict`/`neutral` test |
| M2 | zero value → `contradicts` | the zero-is-neutral test |
| M3 | the three labels hardcoded as §16.4 writes them | the derived-label test |
| M4 | `source_family` dropped (both branches) | the family pass-through test |
| M5 | a zero gap yields `confirms` | the zero-gap test |
| M6 | a `bool` read as a number | the bool-exclusion test |
| M7 | the warning marker dropped | the marker test |
| M8 | **honesty control** — the same three-way branch re-wrapped across lines | **survives, as required** |

`check_targets` refused the **first draft** of M4.1/M4.2 as **AMBIGUOUS**: the two
`source_family=_family_of(result),` anchors are byte-identical apart from
indentation, so each is a substring of the other. Fixed by widening each anchor to
span its own `direction=` line — D-048 working as designed, not a false finding.

### The live check, in full

1. The three Q1 models exist, are callable, and report their own names.
2. The live growth leg is **readable and plausible** (`|gap| <= 15%`).
3. The **label disagreement is real** — the spec's `"inflation_convergence"` is not
   the model Q1 passes.
4. A **dict-valued** real model reads `neutral`, not `contradicts`.
5. The census total equals the list length.

### Carry-overs

| Issue | Status |
|---|---|
| **O-69** | **Substantially closed for the code** — labels are derived from the model read; the full extent (six labels / three locations / one common / `curve_slope` never a parameter) is measured. **Open for the specification's text.** |
| **O-77** | **NEW (severity 2).** `direction` has no `unreadable` member, so "could not read" and "read and balanced" are the same value; the distinction survives only in `unreadable`, which a caller can drop. A fourth member is a `MacroThesis` schema change (§22.13). |
| **O-78** | **NEW (severity 1).** The warning count is **prose in `detail`** — **O-76's shape in a second field**. `ConfirmationSignal` has no `warnings` field. |
| **O-79** | **NEW (severity 2).** The Q6/Q7 ordering is unenforced — the function **recovers** (all-neutral) rather than **detects**. Same class as **O-70**; must close in `build_us_macro_thesis`. |
| **O-80** | **NEW (severity 2).** While recording this increment the suite was backgrounded **while the sweep was still mutating `signals.py`**, and it reported **2 failed / 1752 passed** on exactly the two tests `M2` rewrites — **1754 passed** five times once the sweep finished. **O-61's clean-tree precondition, turned on the recording step.** No `pytest-randomly` exists, so a moving failure means a **concurrent writer**. Nothing enforces serialisation. |
| **O-67 / O-72** | Unchanged — this sweep carries the **fixed** `check_anchor_landings` and `refuse_on_noop`, now **3 of 34** sweeps rather than 2. |
| **O-70** | Unchanged and **wider** — `build_us_macro_thesis` must also **unpack `ConfirmationSignalAssessment.signals`** rather than taking Q7's return as a list. §16.2's Q1–Q8 sample now diverges from the shipped contracts in **four** places. |

---

## Module 14 — `collect_all_warnings` (D-067, Tier 4 #9)

**Location:** `src/macro_engine/thesis_layer/warnings.py` ·
**Tests:** `tests/thesis_layer/test_warnings.py` (28 offline + 1 live) and
`tests/thesis_layer/test_warnings_strictness.py` (5 static guards) ·
**Sweep:** `scripts/mutation_warnings.py` ·
**Live check:** `scripts/live_warnings_check.py`.

### Symbols

| symbol | kind | what it is |
|---|---|---|
| `collect_all_warnings(*model_results, unattributed=())` | function | §16.4's aggregate, returning a `WarningSummary` |
| `WarningSummary` | record (frozen) | `warnings`, `sources`, `unattributed`, `model_warnings`, `contributing_models`, `models_with_warnings`, plus `all_texts` and `shared_warnings` properties |
| `WarningSource` | record (frozen) | `text` + `model_names: tuple[str, ...]`, plus `raised_by_multiple_models` |
| `UnattributedWarning` | record (frozen) | `text`, `origin`, `detail` |
| `WarningOrigin` | type alias | `Literal["blocked_input", "data_quality_flag", "caller"]` |

### The headline, with its measurements

§16.4's sample is a `dict.fromkeys` de-duplication over a flat `list[str]`, and it
fills a field §7.2 step 9 calls **"never dropped"** while §21.4 makes two more
classes mandatory. Seven defects, all measured before the implementation:

| # | defect | measurement |
|---|---|---|
| 1 | de-dup destroys the count, and the count is the signal | 4 models raising one identical string → **1 entry** |
| 2 | the output cannot attribute a warning to its source | two byte-identical warnings → one-element list, **no trace of the second** |
| 3 | de-dup firing depends on an unstated producer convention | **0 of 8** live warnings name their own model |
| 4 | "no warnings" and "not passed" are the same value | `collect_all_warnings(quiet) == collect_all_warnings()` |
| 5 | §21.4's blocked class has no route in | **5** registry members, **0** routes (a blocked input is not a `ModelResult`) |
| 6 | §5.4's flags do not reach it either | **5 of 5** snapshot flags absent |
| 7 | **defects 1 and 6 are COUPLED** | routing one flag into five models → §16.4's list shows it **1×**, `WarningSource` records **5** raisers |

### What the sweep proved about the increment's own tests

`M5.1` reverses `all_texts`' two halves. **It survived the entire selection on the
first run and is not inert.** Cause: `test_unattributed_order_is_preserved`
passes **only** unattributed warnings, so the two halves can never interleave and
a reversal is invisible; every other `all_texts` assertion is a membership test or
a case with one half empty. **Closed by adding a test, not by exempting the
mutant** — `test_all_texts_puts_the_models_warnings_first`. This is **lesson 65's
flag**: a survivor is a claim about the tests until proven otherwise.

`M2` and `M4` cannot be killed by the behavioural selection at all:

| mutant | why behavioural tests cannot kill it | how it IS killed |
|---|---|---|
| `M2` `raisers: dict[str, list[str]]` → `dict[str, str]` | the mutant dies with an `AttributeError` raised **inside the function under test**, so pytest reports a failure but no assertion caught it; a re-spelled `.append` would leave nothing | `test_the_raiser_map_keeps_one_entry_per_model_not_per_text` — reads the annotation **statically** |
| `M4` the raiser census `if total_raisers != total_own:` | **unreachable by construction** — every input warning appends exactly one raiser, so the guard cannot fire | **exempted by argument** (`inert_proof` states the construction) and its presence pinned by `test_the_internal_guards_are_unreachable_by_design` |

That is why `test_warnings_strictness.py` exists: **a mutation changing a type
annotation, or removing a line whose effect no value can express, is killed by a
different gate than the one the sweep runs.**

### The sweep, in full

| group | mutation | killed by |
|---|---|---|
| M1 | `sources` keeps only the first raiser | `test_the_count_of_raisers_survives_de_duplication` |
| M2 | `raisers` is a text→single-model map | the **static** annotation test |
| M3 | `warnings` is sorted, not first-seen | `test_shared_warnings_exposes_only_the_multiply_raised` |
| M4 | the raiser census deleted | **survives — unreachable by construction, exempted** |
| M5 | `all_texts` reverses the two halves | `test_all_texts_puts_the_models_warnings_first` (**added by this sweep**) |
| M6 | a warning-free model counted as having warned | `test_a_warning_free_model_is_distinguishable_from_a_missing_one` |
| M7 | `shared_warnings` returns every source | `test_shared_warnings_exposes_only_the_multiply_raised` |
| M8 | `WarningSummary` is no longer frozen | `test_the_summary_is_frozen` |
| M9 | **honesty control** — the loop re-spelled as `enumerate` | **survives, as required** |

**9 applied / 7 killed / 2 survivors, both proven.**

### The live check, in full

Measured 2026-09-19 against a live snapshot and the live registry:

| # | measurement |
|---|---|
| 1 | **5 of 5** models warned; **8** de-duplicated texts; **0** shared |
| 2 | **8 raisers recorded against 8 input warnings** — attribution total |
| 3 | **0 of 8** collapsed on today's data (a fact about the data, never asserted) |
| 4 | **0 of 8** warnings name their own model — defect 3, live |
| 5 | **5** blocked registry entries, **0** arriving as a `ModelResult` (defect 5 / **O-81**) |
| 6 | **5** snapshot flags, **0** reaching the aggregate (defect 6 / **O-82**) |
| 7 | routing flag 1 into all five models → list shows it **1×**, `WarningSource` records **5** raisers (defect 7) |

### Carry-overs

| Issue | Status |
|---|---|
| **O-81** | **NEW (severity 2).** §21.4's blocked class has a **route** but **no call site** — `build_us_macro_thesis` does not exist, so the obligation is **not met** even though the mechanism is built and tested. |
| **O-82** | **NEW (severity 2).** §5.4's flags still do not reach any model's own `warnings`; the wiring is in the **models layer**, so no change here closes it. |
| **O-83** | **NEW (severity 3, incident).** `tools/sweep_health.py`'s leftover scan is **per-sweep**, so a mutation left applied in a **file shared between increments** is invisible. Measured live: D-064's `M6.3` (`if False:` in `config.py`) was still on disk with the tool reporting **0 leftovers** — because that file belongs to the scenario sweep, which was target-clean *only because the mutation had already fired*. Restored by hand; the scenario sweep then ran **23 applied / 22 killed**. Remedy (a whole-tree `if False:` scan) not yet implemented. |
| **O-84** | **NEW (severity 2).** `iorb`'s `future_date_tolerance_days: 1` is checked against the snapshot's **frozen** `retrieved_at`, so it decays with the age of the cache — measured 2 and 3 days over, failing the live data-layer test. **O-80's class one layer down.** |
| **O-67 / O-72** | Unchanged — this sweep carries `check_anchor_landings` and `refuse_on_noop`, now **4 of 35** sweeps. |
| **O-70** | **Wider.** `build_us_macro_thesis` must also pass `collect_all_warnings(...)`'s `unattributed=` with the registry's blocked entries and the snapshot's flags (**O-81**/**O-82**). §16.2's Q1–Q8 sample now diverges from the shipped contracts in **six** places. |



---

## Module 14 — `no_trade_thesis` (D-068, Tier 4 #10)

**File:** `src/macro_engine/thesis_layer/no_trade.py` (new). **Function:**
`no_trade_thesis` — Section 16.3's first-class stand-down, routed to from Section 16.2's
**Q6** (gap inside the rules' own dispersion), **Q7** (`CONFLICTED`), and **Q8** (no
falsifier could be derived, which D-063 added). **No config leaf** — every threshold it
touches belongs to the gate that fired.

### The finding

Section 16.4's sample is nine lines, takes `reason: str`, and returns a `MacroThesis`.
**Five defects, all measured before the implementation was written.**

| # | Defect | Measured |
|---|---|---|
| 1 | **The sample body does not run** — `MacroThesis` requires six fields with no defaults | `.probe/p_d068_1.py`: `ValidationError` naming all six; the `# other fields populated with whatever partial view was formed` comment is the requirement left as prose |
| 2 | **One string slot for three triggers** — identical sentences make the three paths the **same object**, and nothing records which Q fired | `.probe/p_d068_1.py` sections 6-9 |
| 3 | **Each trigger holds a rich object and all three are discarded** | `.probe/p_d068_2.py`: Q6 → a `MarketPricingGap` (`raw_gap=+0.77`, `dispersion=0.42`); Q7 → the per-model direction table (`['confirms','confirms','confirms']`); Q8 → an `InvalidationAssessment` with per-input reasons |
| 4 | **`warnings=[""]` and `warnings=[]` are both ACCEPTED**, so "stood down" and "stood down and cannot say why" are the same object | `.probe/p_d068_1.py` sections 7-8 |
| 5 | **`stop_or_invalidation="n/a"` satisfies the LTCM gate it stands down from** — `bool("n/a".strip()) is True` and `TradeIdea(stop="n/a").is_trade is True` | `.probe/p_d068_1.py` section 8c; confirmed live |

Defect 3 is **D-067's defect 2 one function on, and worse**: the dropped object is the
only record of *which of three very different things happened*. Defect 4 is **D-066's
shape** from a third direction (one slot, three states).

### The design

`no_trade_thesis(reason, *, trigger, evidence=None, gap=None) -> NoTradeDecision`.

- **`trigger`** — a closed `Literal`: `gap_below_dispersion` / `conflicted_signals` /
  `no_falsifier` / **`caller`**. `caller` makes a stand-down outside the three documented
  gates **sayable**, rather than forcing a false label. A `Literal` rather than a `str`
  so an unlisted trigger is a type error at the call site (O-29).
- **`evidence`** — a typed union of the three gate objects, or `None` for `caller`.
- **`elapsed`** — `dispersion - abs(raw_gap)`, only for Q6. A gap 1bp short of meaningful
  and one 200bp short are both "not meaningful" and are **not the same call**.
- **`reason`** is **refused** when empty or whitespace-only — the only place defect 4 can
  be caught, since a `MacroThesis` cannot distinguish blank from short.
- **Q6 without `gap`** raises; the one trigger with a magnitude cannot silently lose it.
- **`render_no_trade_thesis(decision, **thesis_fields)`** builds the published thesis from
  the caller's six required fields. It **refuses** `trade_idea` / `status` / `warnings`
  overrides, writes `No trade [<trigger>] (<label>): <reason>` into `warnings` so the
  trigger survives publication, and writes `stop_or_invalidation=""` rather than
  Section 16.4's `"n/a"`.

**It does not re-derive the trigger from the sentence** — the caller states it.

### Verification

| Gate | Result |
|---|---|
| `ruff check` + `ruff format --check` + `mypy --strict` | clean, **176 files** — ⚠️ **the mypy half of this row was FALSE.** D-069 found **29 `mypy --strict` errors** in this increment's own files (13 + 1 + 1 in the three `test_no_trade*` files, 15 in `scripts/live_no_trade_check.py`), all fixed there. **O-88.** The counts below are as-published and are retained rather than silently corrected, because the **falsity is the finding** |
| `pytest -m "not live"` | **1829 passed / 1 skipped / 10 deselected** |
| `scripts/mutation_no_trade.py` | **14 applied / 13 killed / 1 survivor (the control), exit 0** |
| `scripts/live_no_trade_check.py` | **PASSED** |
| `tools/sweep_health.py` | **36 sweeps, 0 failures, 0 leftovers** |

**The sweep had NO gaps to close on its first run** — unlike D-067's, whose `M5.1`
survived and forced a new test. The structural reason: every defect here is a
**presence** defect (a field, a guard, a label), which has a fixture that names it;
D-067's survivor was an **interaction** defect (`all_texts`' two halves could never
interleave) that no single-field test could see. **Lesson 102.**

`check_targets` refused the **first draft of the control** (`old == new`, INERT BY
CONSTRUCTION) — the gate catching the harness author's own mistake. **M2's kill is
doubly attested**: the sweep reports a behavioural symptom
(`test_every_trigger_has_a_label` raises because `str` has no `__args__`), and the static
guard `test_the_trigger_vocabulary_is_closed` in `test_no_trade_strictness.py` was
verified to kill it **independently** (the strictness file alone fails two tests).

### Live measurement (2026-09-19)

| Check | Result |
|---|---|
| Q6 | **does not fire** — `|raw_gap=+0.77| > dispersion=0.42`. The no-trade path is **not** the common case |
| Q7 | **does not fire** — 3 agreeing / 0 disagreeing / 0 unreadable |
| Q8 | **does not fire** — 3 conditions identified |
| The rendered thesis | passes the live schema: `instrument='NONE'`, `status=WATCH`, `stop=''`, warning `No trade [caller] (...)`. |
| The sentinel | `TradeIdea(stop_or_invalidation="n/a")` returns **`is_trade is True`** live — the schema accepts `"n/a"` as a stated falsifier |

### Carry-overs

| Issue | Status |
|---|---|
| **O-85** | **NEW (severity 2).** The `trigger` is an **unchecked claim by the caller**; no callee test can verify that the right trigger and the right `evidence` object were passed. **O-70/O-79's class** — closed by `build_us_macro_thesis` deriving the trigger from the gate it observed. |
| **O-86** | **NEW (severity 1).** `status=WATCH` cannot distinguish "no edge" from "waiting" to a consumer reading only `status`. The `trigger` field and the labelled warning mitigate it; the full fix is a schema change. |
| **O-70** | **Narrower by one.** The builder must now also derive the trigger and hand over the gate object (**O-85**). Section 16.2's Q1-Q8 sample diverges from the shipped contracts in **seven** places. |
| **O-79 / O-68** | Unchanged. |

---

## Module 14 — `build_us_macro_thesis` (D-069, Tier 4 #11) — TIER 4 COMPLETE

**File:** `src/macro_engine/thesis_layer/builder.py` (new, 1174 lines).
**Function:** `build_us_macro_thesis` — Section 7.2 / 16.2. **TIER 4 IS COMPLETE
(11 / 11).** **No config leaf** — every threshold belongs to a model it calls, so a
block here would have been a second source of truth for numbers the models own.

### The seam

The function appears on **both** the Tier 4 and the Phase 3 checklists. That overlap
is not an inconsistency: it **is** the phase seam — the models layer stops producing
numbers and the thesis layer starts making claims. With it implemented, **Phase 3's
blocker is cleared**. Phase 2's 13 outstanding items are **all Tier 5** (§22.3's
US-only scoping), so no Phase-2 work blocks Phase 3.

### The divergences

**Nine measured divergences from Section 16.2's sample**, including a correction of
my own carried-in premise — the sample omits **zero** required `MacroThesis` fields.
The "six missing fields" belonged to Section 16.4's `no_trade_thesis` sample, which
is D-068's finding, and I had carried it into the wrong section.

**Two boundaries, measured rather than assumed:**

| Boundary | Measurement |
|---|---|
| Q1's three economy reads | **No snapshot-fed helper exists.** The census of snapshot-taking helpers is **`[]`** for `inflation_nowcast`, `labor_synthesis`, `regime` and `national_accounts` — there is no `inflation_breadth_score(snapshot)` to call. So the reads became a **PARAMETER** (`EconomyReads`, a frozen dataclass). Manufacturing a transform would have **hidden the gap**. |
| The gap as a signal | **`MarketPricingGap` is not a `ModelResult`** — a plain `BaseModel` whose `value` is `raw_gap` — so Section 16.2's sample fails pydantic validation against the aggregate's signature. An explicit `_as_signal` adapter bridges it rather than loosening the contract. |

**The three gates fire in order Q6 → Q7 → Q8**, each routing to a dedicated helper
(`_q6_decision` / `_q7_decision` / `_q8_decision`) that **owns its own trigger
literal in its own body**, so the trigger is produced beside the condition that
justifies it and every deviation is unrepresentable at the call site (D-068's O-85).

### The defect — an INTERACTION defect, found only by the live run

`_render` collected **no warnings at all**. Every stand-down therefore **silently
dropped the model warnings and Section 22.5's market-path contamination
disclosure**. Measured before the fix:

```
contaminated=0 proxy=0     # on a run where the contaminated branch was taken
warnings=1                 # the trigger line ALONE
```

**No offline test could see this.** Every test asserted the trigger line was
**present**, and it was; the defect was that it was **alone**. The repair renders
first and **appends** the warnings behind the trigger line — because
`render_no_trade_thesis` **owns** `warnings` and raises rather than accept an
override, so the increment respected D-068's contract instead of relaxing it.
Measured after:

```
warnings=13    contaminated=1 proxy=1
```

### Verification

| Gate | Result |
|---|---|
| `ruff check src tests tools scripts` | **All checks passed** (182 files) |
| `ruff format --check src tests tools scripts` | **182 files already formatted** |
| `mypy --strict src tests tools scripts` | **no issues in 182 source files** |
| `pytest -q -m "not live"` | **1901 passed / 1 skipped / 16 deselected**, x5 consecutive |
| `tests/thesis_layer/` | **299 passed, 11 deselected** |
| `scripts/mutation_builder.py` | **18 applied / 17 killed / 1 survivor (the control)**, exit 0 |
| `scripts/live_builder_check.py` | **PASSED** |
| `tools/sweep_health.py` | **37 sweeps, 0 failures, 0 leftovers** |
| O-83 manual probe | `grep -rn "if False:/|if True:" src/macro_engine/` → **nothing** (exit 1) |
| `pytest -m live -k coherent_economic_picture` | **1 failed** — the pre-existing `iorb` finding (O-84), **diagnosis corrected**; not a D-069 defect |

**Tests:** 78 new — 51 behaviour (`test_builder.py`), 21 static guards
(`test_builder_strictness.py`), 6 live (`test_builder_live.py`).

### The sweep refused to certify — twice

**First run: SIX survivors, every one a REAL test gap.**

| Mutant | Why it survived | Fix |
|---|---|---|
| **M8** — **the defect just fixed** | Its regression test lived **only in `test_builder_live.py`**, which `-m "not live"` **deselects** | Three offline tests added |
| M9 | Assertion was a **disjunction** any sentinel satisfies | Pinned the exact sentinel |
| M10 / M11 | The instrument reader had no test driving it directly | `read()` helper drives `_instrument_from` on sentinel / dict / empty / int |
| M12 | Direction pinned only as a **relation**, never against a disagreeing fixture | Fixture where selector and gap-rule **disagree** |
| M13 | Scenarios checked **only on the live path** | Offline assertions on both tails |

All six closed by **ADDING tests** (40 → 51), never by exempting a mutant.
**Lesson 5be.**

**Second run: the HONESTY CONTROL was killed.** `M18` is semantically inert
(`x < 0` rewritten as its De Morgan negation), so survival is required. It died
because `test_the_sample_s_gap_only_direction_rule_survives_only_as_a_fallback`
asserted the fallback's **literal source text** — a test pinning **spelling rather
than meaning**. Rewritten to pin **order and structure via `ast.parse`**, leaving
behaviour to the test that drives the function. **Lesson 5bf.**

Two mutants were also **mis-aimed** and retargeted: `M12`'s anchor sat in
`_render` rather than `_direction_for`, and `M13`'s replacement was a behavioural
no-op. Both caught by `check_anchor_landings` / inspection.

### Tier 4 status

| # | Function | Decision | Module |
|---|---|---|---|
| 1 | `select_instrument` | D-058 | 15 |
| 2 | `construct_duration_weighted_curve_trade` | D-059 | 15.1 |
| 3 | `construct_breakeven_trade` | D-060 | 15.2 |
| 4 | `construct_cross_market_rv` | D-062 | 15.3 |
| 5 | `derive_invalidation_conditions` | D-063 | 14 |
| 6 | `build_scenario_distribution` | D-064 | 12 |
| 7 | `next_catalyst_calendar` | D-065 | 13 |
| 8 | `build_confirmation_signals` | D-066 | 14 |
| 9 | `collect_all_warnings` | D-067 | 14 |
| 10 | `no_trade_thesis` | D-068 | 14 |
| 11 | **`build_us_macro_thesis`** | **D-069** | **7.2 / 16.2** |

### Carry-overs

| Issue | Status |
|---|---|
| **O-87** | **NEW (severity 2).** `select_instrument` publishes **two value shapes** — a dict on the executable routes, a bare **sentinel string** on the refused ones — while its own `_selection_value` declares *"always returns a dict value"*. **That sibling claim is wrong.** Read defensively on both shapes (`_instrument_from`). |
| **O-88** | **NEW (severity 2), CLOSED.** The D-068 gate row claimed `mypy --strict` was clean at **176 files** while **29 errors** sat in D-068's own files. All 29 fixed; the gate is now **true at 182**. |
| **O-89** | **NEW (severity 3).** The residual mypy/robustness debt, recorded so the fix is auditable — four classes (fixtures that lie about a field's type; deliberately-invalid constructions; assertions mypy cannot see the value of; ad-hoc tuples used as records). |
| **O-84** | **DIAGNOSIS CORRECTED.** Not a frozen clock. The failure text names its own comparison — *"after retrieval date 2026-09-19 by 2 day(s)"* — so the check **is** evaluated against the current date. **FRED publishes `iorb` 2–3 days ahead** of the calendar while the series declares a tolerance of `1` (sized for the documented 1-day UTC-boundary case). **The ERROR path is armed and firing correctly.** Fix is a **data-layer** decision. |
| **O-70** | **DISCHARGED — closable.** The builder passes `unattributed` through to `collect_all_warnings` on **every** return path, including all three stand-downs. Live: `warnings=13`. |
| **O-81** | **Partly discharged.** The mechanism the builder was created to wire is now wired; what remains is that the builder does not walk the registry itself (deliberately, lesson 99) — so the §8 API layer must populate the argument. |
| **O-85** | **Reduced.** The builder derives the trigger from the gate it actually observed, so the one existing call site cannot misdescribe a stand-down. `no_trade_thesis` itself still accepts a caller-supplied trigger. |
| **O-83** | **Remedy still not implemented.** The whole-tree `if False:` / `if True:` scan is still a manual Step-0 grep. At this close it reports **nothing**. |

---

## Module 16 — the §8 API layer (`api_layer/`, D-070) — PHASE 3 COMPLETE

**Files:** eight new modules under `src/macro_engine/api_layer/` — 3383 lines
total. `orchestration.py` (1043), `snapshot_provider.py` (369),
`reasoning_stream.py` (279), `routes_query.py` (269), `routes_thesis.py` (245),
`routes_dashboard.py` (226), `routes_health.py` (169), `app.py` (92).

**Spec:** §8.1–§8.4, §22.2, §22.3, §16.3.
**Config:** the `api:` block in `config/settings.yaml` — 9 leaves, every one a
`{value, calibration_status, note}` envelope.

### The orchestration gap — why this increment needed a new module

`build_us_macro_thesis` takes **six required arguments**, and §8.2's sample calls
it with a snapshot alone:

```
TypeError: build_us_macro_thesis() missing 6 required positional argument(s)
```

| Argument | Kind | Why it cannot be defaulted |
|---|---|---|
| `reads` | positional | `EconomyReads` — the three economy scores §16.2's Q1 needs, which **no snapshot-fed helper computes** (D-069 measured the census as `[]`) |
| `taylor_inputs` | positional | Module 4's own input object |
| `first_difference_inputs` | positional | Module 4's change-form input object |
| `thesis_type` | kw-only | an **analytical choice among seven families**; a gap says nothing about which |
| `universe` | kw-only | the instrument universe to select from |
| `short_yield` | kw-only | a `ModelResult`, not a float |

The derivation lives in **`orchestration.py` alone** (the user's decision), so the
API layer stays thin and the gap becomes one auditable file. The strictness suite
asserts this structurally: **no router may read a guarded snapshot field directly**,
because the three labor-leg unit traps would then be re-opened one endpoint at a
time.

### The status contract

| Condition | Status | Why |
|---|---|---|
| Completed analysis, stand-down | **200** | §16.3: a no-trade is a *result*, not a failure. A fabricated `WATCH` would be indistinguishable from a genuine "no edge" verdict. |
| Unimplemented country | **501** | `NotImplementedError`, the same class every US-only function raises (§22.3). A 502 would suggest a retry might succeed. |
| Missing/unusable data | **502** | `OrchestrationError` — **refusal, not defaulting**. Names the fields that failed. |
| Bad `thesis_type` | **422** | A malformed *request*, not a data problem. |
| Real bug | **500** | Reserved; deliberately not used for any of the above. |

### Three measured unit traps, all in the labor leg

| Series | Real value | Naive reading | What the model needs |
|---|---|---|---|
| `jolts_openings` | `7271.0` | a level in **thousands** | a **YoY percent** |
| `jolts_quits` | `1.9` | a **rate in percent** — **accepted by `ge=0, le=100`** | a **percentile** of its trailing range |
| `initial_claims` | persons | a level | a **4-week-average percent change**, POSITIVE = loosening |

The middle row is the dangerous one: the wrong number **passes the model's own
validator**, so nothing downstream can notice. D-064's lesson (a value inside the
valid range and outside the true range) in a new position.

### The increment's own defect — a lookup that succeeded when it should have failed

`_yoy_percent` took "the latest observation at or before the anniversary". That
lookup **succeeds** for a point **31 days away** — the adjacent month — and the
ratio was published under the words **"year-over-year"**. Repaired with
`api.yoy_match_tolerance_days` (default **5**), and the **exclusion of the
adjacent month is the entire purpose of the value**: a tolerance of 28 would admit
the neighbouring month and silently restore the defect. The sweep mutates both the
tolerance (M2.1) and the config read (M2.2).

### §8.4 — the pairing, enforced rather than documented

`ApiSettings._permissive_cors_requires_loopback_bind` **refuses the object** when a
permissive `cors_origins` list meets a non-loopback host, and `loopback_only`
**publishes** the posture as a value. The service has no authentication anywhere,
so the bind address *is* the access control. The shipped config enumerates two
origins rather than using `["*"]`, so the wildcard is a deliberate edit that trips
the validator rather than a default nobody looked at.

### Verification

| Gate | Result |
|---|---|
| `ruff check` | **All checks passed** |
| `ruff format --check` | **196 files already formatted** |
| `mypy --strict` | **no issues in 196 source files** |
| `pytest -q` | **2043 passed / 1 skipped / 1 failed** — the failure is **O-84** (the data-layer `iorb` decision), not a D-070 defect |
| `tests/api_layer/` | **127 passed** (was 125 before the two proxy guards were added) |
| `scripts/mutation_api_layer.py` | **42 applied / 39 killed / 3 survived** — 2 measured-inert (`M1.5`, `M4.3`), 1 control (`M10.1`); **certifies** |
| `scripts/live_api_check.py` | **PASSED (exit 0)** — a real uvicorn server, all five surfaces, after three defects were found and fixed *in the check itself* (see below) |
| `tools/sweep_health.py` | **38 sweeps, 0 failures, 0 leftovers, 0 mutant shapes on disk** (O-83's remedy, verified live) |
| O-83 whole-tree probe | **clean** |

**Tests:** 127 — 49 orchestration, 43 routes, 15 provider, 17 strictness, **2 proxy
guards in `test_strictness.py`**, 1 other added by this increment.

### The sweep refused to certify three times

**First run: 42 applied / 31 killed / 11 survived**, ten with no proof. Every
survivor was diagnosed by **applying it and measuring the behaviour** (O-42),
never by labelling it:

| Survivor | Class | Resolution |
|---|---|---|
| **M8.6** | **a real lie the tests missed** — the stream named three gates when one fired | Test strengthened to assert the **fired set exactly** |
| **M10.2** | an **independent source** was needed — the guard compared the constant to itself | Re-pinned against `pyproject.toml` |
| **M9.5** | a **tautology** — the shipped host is loopback, so `True == True` | A legal **non-loopback** bind that requires `False` |
| **M9.1 / M9.2 / M9.3** | **genuine coverage gaps** — the route tests seeded `_CACHE` by hand | `test_snapshot_provider.py`, 15 tests |
| **M7.1** | the default is **unreachable**, but its *value* is a safety property | Guard reads `QueryResponse.model_fields` |
| **M7.3** | **my own malformed mutant** — a comment-only edit | Replaced with `if not matched:` → `if False:` |
| **M1.5** | **a second, overlapping guard** returns the same `0.0` with an equally honest note | `inert_proof`, mechanism named |
| **M4.3** | **a second, independent guard** — traced to `gdp_nowcast.py:442` | `inert_proof`, site and message named |

**Second run: 42 applied / 36 killed / 6 survived — M9.1/M9.2/M9.3 survived AGAIN**,
on a tree where each is measurably killed by hand. **The contradiction was the
defect:**

> `PYTEST_TARGETS` declared **four** test files. `run_pytest` ran **three**.
> `check_tests_collect` validated the declaration the run never used.

The three provider mutants' tests live in `test_snapshot_provider.py`, the file
that was declared and **never selected**. **A green gate certified a selection
nobody executed**, and the resulting survivors were indistinguishable from inert
mutants. Fixed structurally: both functions now splat **one** constant, and a new
gate (`check_the_run_and_the_declaration_agree`) parses the source and refuses to
run if either re-inlines a literal path — verified by planting the regression.

### Carry-overs

| Issue | Status |
|---|---|
| **O-90** | **NEW (severity 2).** `snapshot_provider._CACHE` is **process-global**, so `--workers N` silently multiplies the build cost (measured **223.6s** live vs **9.5s** in-process) while the response still discloses a correct age. Needs a `workers=1` contract or a shared store. |
| **O-91** | **NEW (severity 2).** The SSE generator is `async` but awaits a **synchronous** build, so it blocks the event loop and `/health` goes unanswered during a slow build. Needs `to_thread`/executor. Not fixed here — it would invalidate the provider mutants that certify the current behaviour. |
| **O-81** | **DISCHARGED at the API layer.** `EconomyReads` now has a producer. |
| **O-83** | **Remedy IMPLEMENTED.** `sweep_health.py` scans the whole tree for mutant shapes with no catalogue; verified live against an in-flight `# MUTANT`. Known limit recorded: a deletion mutation carries no shape. |
| **O-84** | **Unmoved.** The `iorb` future-date tolerance is a **data-layer** decision; the pre-existing live test still fails. |
| **O-92** | **NEW (severity 2).** Both production HTTP clients default to `trust_env=True`, so loopback OpenBB traffic and FRED calls honour `HTTP_PROXY`. The provider works here (21/21 fields) but that is the proxy forwarding loopback, not design. Mitigated **for the live check only** (`trust_env=False` + the new guard); the data-layer fix is deferred. |
| **O-87** | Unmoved (a `select_instrument` contract question). |
| **O-85 / O-86** | Unmoved, with D-069's reductions still in force. |

---

## Module 17.1 / 17.4 — the risk-budget seam (`D-071`, `D-072`) — **PHASE 4, 2 of 4**

**Files:** `src/macro_engine/portfolio/risk_budget.py` (the file both functions
live in — Module 17 has been one file since D-054) plus two new scripts and one
new test module.

**Spec:** §9.2 (`compute_risk_parity_weights`), §9.3 (`translate_thesis_to_position`),
§17.1 (the risk-share identity), §17.4 (the hook), §20.12C (the two-asset
helpers this builds on), §21.0 (the no-prototyping rule), §22.6 (the Kelly cap it
composes with).

### D-071 — `compute_risk_parity_weights`, and the identity it does *not* give you

`compute_risk_parity_weights` solves `w_i (Σw)_i = w_j (Σw)_j` by iteration, so
that every asset contributes **equal risk** rather than equal notional. It is
correct, and on its own it is useless to the thing that wanted it.

**The finding is the gap between §17.1's two quantities.** Module 17.1 defines the
risk contribution `RC_i = w_i (Σw)_i / σ_p²`. §9.3's job is to turn a
**risk-budget share** into a **notional fraction**. Those are not the same
number and the conversion is *not* the identity — it needs a covariance matrix,
and **§9.3's signature does not supply one** (it takes a `MacroThesis` and a
portfolio risk budget, nothing else). The naive conversion — using the risk share
directly as the notional share — was measured **6.7x wrong** on a real two-asset
book: it returned **0.018** where the correct answer was **0.12**. This is the
increment's headline number, and it is why §9.3's output is a *proposed* size
that a human signs off, never a sized order.

### D-072 — `translate_thesis_to_position`: four gates, and a meta-gate

`translate_thesis_to_position` takes a `MacroThesis` and one instrument's budgeted
risk share and returns a `ProposedPosition` — or, more often, a refusal. The
docstring's own framing, which the sweep now pins: **"There are four, not five:
a gate that cannot stop a proposal is not a gate."**

| # | Gate | Outcome member | Condition |
|---|---|---|---|
| 1 | sentinel / no production instrument | `refused_no_trade_thesis` | the thesis carries `NO_PRODUCTION_INSTRUMENT` or status `empty_no_trade` |
| 2 | scenario distribution uncalibrated | `refused_scenarios_uncalibrated` | `scenario_sizing_permitted` is `False` |
| 3 | universe does not permit the instrument | `refused_instrument_out_of_universe` | `ProductionUniverse().permits(...)` is `False` |
| 4 | budget below the minimum | `refused_budget_too_small` | the share (or its implied size) is below the configured floor |

**The declared member set is now pinned against the code.** `PositionTranslationOutcome`
is a six-member `Literal` and the file's docstring makes a *counting* claim about
it ("The six members are exhaustive"). The sweep proved that claim **was changeable
to any number with every test green** — because `get_args` reads the type and a
docstring is a string (mutants **M10.2**, **M10.3** both SURVIVED the first run).
That is not hypothetical: the type docstring **shipped saying "nine members" for a
`Literal` that had six**. Repaired by
`test_the_docstrings_agree_with_the_literal_they_describe`, which recounts the
members and the gates from the docstring itself.

**The meta-gate finding — the right outcome with the wrong reason.** Several
refusals returned the *correct* `outcome` while naming a *different* gate's reason
in the `reason` phrase. No numeric assertion can see this; only the reason string
can. The sweep's M2 group exists for exactly this and is the reason the live check
re-reads the reason on **all seven** paths rather than only the outcome.

**`binding_constraint` must track its producer.** Gate 4 carries a published bound
(`max_position_pct_of_portfolio`, **0.15**, a *fraction* despite `_pct`) and a
divisor (**2.0**). The live check drives **eight** budgets from 0.01 to 1.00 and
asserts the returned `binding_constraint` changes with the input that produced it,
rather than printing a constant.

### Verification — all gates green at **215 files**

| Gate | Result |
|---|---|
| `ruff check` | **All checks passed** |
| `ruff format --check` | **215 files already formatted** |
| `mypy --strict` | **no issues in 215 source files** (D-035: matches the line above) |
| `pytest -m "not live"` | **2295 passed / 1 skipped / 0 failed** |
| `tests/portfolio/test_thesis_position.py` | **45 passed** (was 44) |
| `scripts/mutation_thesis_position.py` | **22 applied / 21 killed / 1 survived (the control)** — **CERTIFIES** |
| `scripts/live_thesis_position_check.py` | **PASSED (exit 0)** over the **real** pipeline, all four US families |
| Reachability audit `--check-baseline` | **PASS — 59 = 59, no regressions** |
| `tools/sweep_health.py` | **0 leftovers, 0 mutant shapes** — the 2 failures recorded here as *"inherited"* were **STALE ANCHORS**, cured at **D-075**; both sweeps now certify (see the header block) |

### Why no API path supplies a book — checked, and it is spec-conformant

**Measured:** none of the three production call sites passes `risk_budget_target` —
`routes_thesis.py:200`, `routes_query.py:213`, `reasoning_stream.py:210` all rely on
the default. So **every API path reaches §17.4 with `target is None`** and the axis
publishes *"DID NOT RUN"*.

**This was verified against §17.4's own text rather than assumed, and it is
correct:**

1. **The rule is explicitly conditional.** `AGENTS.md:3836` scopes it to *"once
   Phase 4+ auto-sizing exists"* — and supplies one. §17.4 is written for a system
   that has auto-sizing, and this build has a **proposal** path, not an auto-sizing
   one.
2. **It requires `RiskLimits`**, a portfolio-level object §17.4's own second bullet
   assigns to **Phase 5+** (Module 18.3). The book does not exist yet.
3. **No honest source exists for a book.** §21.1's five source types are LIVE /
   DERIVED / CONFIG / MANUAL / BLOCKED; a portfolio holding is **none of them**, and
   §21.0 rule 3 forbids inventing an input. So the correct behaviour is the
   **disclosed absence** the axis already produces.

**The disclosure was then checked to reach a consumer, not merely to exist.**
Verified four properties by inspection of the live modules: the route returns the
**thesis object itself** (`thesis=thesis`); `MacroThesis.warnings` is a first-class
schema field; the axis writes into `thesis.warnings` rather than returning a sibling
value; and `_apply_risk_axis` returns a `MacroThesis`. **A consumer that reads only
`status` sees `DRAFT` and cannot tell "unsized" from "sized and clear" — which is
exactly why the warning exists, and why it travels inside the object rather than
beside it.**

**What this leaves open is O-97:** the wiring is complete at the builder and absent
at the API, by design. The open part is **enforcement, not behaviour** — when
Phase 5 supplies a book, these three call sites are where it must be passed, and
`risk_budget_target` is **optional**, so a future caller who forgets it gets the
same "DID NOT RUN" path rather than an error. Closing it needs the object that does
not exist, so it is recorded rather than fixed.

### The increment's highest-value defect — the gate was reading its sources differently from every sweep

`tools/sweep_health.py` reported **13 `[FAIL]` sweeps**. Ten of them targeted
`src/macro_engine/config.py`. Every one of those 13 sweeps was *correct*;
`sweep_health.py` was wrong.

> `_own_target_check` and the leftover scan both used
> `Path.read_bytes().decode("utf-8")`. Every sweep anchors with bare `\n` and
> reads with `Path.read_text()`. `read_text` applies **universal-newline
> translation**; `read_bytes().decode()` does **not**.

`config.py` is the **only CRLF file among the 69 under `src/`** (4292 CRLF, 0 bare
LF), and it is the target of all 13 failures. Reproduced on the same file with both
readers: **bytes form → 45 problems; translated form → 6**. **87% of the report was
line-ending artefact.**

**And the noise was masking a real defect.** With the reader fixed, the scan
immediately surfaced **`MX3c`** — a leftover mutant in
`src/macro_engine/models/yield_curve.py`, **O-61's fifth recurrence**. The working
tree held `adjusted = base_rate + min(adjustment, settings.ceiling)` where `HEAD`
has `adjusted = min(uncapped, settings.ceiling)`. The false positive and the true
positive were **the same line**. Three tests caught it
(`test_inversion_adjustment_ceiling_binds_at_the_shipping_base_rate` + 2 siblings);
it was also **destroying the anchors of its own sweep's `MX3a`–`MX3d` mutants**,
which had been reporting "target ABSENT" — a symptom that had been read as stale
anchors. Restored from `HEAD`; line endings verified preserved (1748 bare LF, 0
CRLF); the suite returned to **2295 passed**. Filed as **O-95**.

### The second finding — two sentinels, documented as one

The increment's live check had to distinguish "no instrument" from "instrument not
in the universe". They are **two different strings**; **four documentation sites**
asserted they were the same. Corrected in place with `**CORRECTED (D-071/D-072)**`
markers. Filed as **O-93**, with the sharper consequence the correction exposed:
`is_trade` returns `True` for the sentinel, so it reads as a **live trade in an
unexecutable instrument**.

### The remaining Phase 4 item — **not** in this increment

The **risk-axis hook** (§17.4, handoff §3b item 4): `thesis_layer/builder.py` must
gain a risk-budget parameter **whose default preserves today's behaviour**, and the
orchestrator must supply a **real book**. It is deliberately separate — it changes
the builder's signature, which every builder test and D-069's sweep anchor read.
Also outstanding from the same section: **O-94** — §16.2 Q12's exposure half is
computed nowhere and needs Module 18.

---

## Module 17.4 (§17.4) — the risk-axis hook, and a bound that could never fire (`D-073`) — **PHASE 4 COMPLETE, 4 of 4**

**Files:** `src/macro_engine/thesis_layer/builder.py` (`_apply_risk_axis`, the
`risk_budget_target` parameter, the live-path restructuring), `config/settings.yaml`
(`thesis_demotion_fraction_value`, **0.02 → 0.03**), `src/macro_engine/config.py`
(the accessor's docstring), plus one new test module, one new sweep and one new
live check.

**Spec:** §17.4 (*"feedback into thesis validity"*), §21.0 (the no-prototyping
rule), §21.1 (the source-type vocabulary), §21.4 (a gap must be stated, not
papered over), §25 (the scenario-probability gate), §22.13 (a schema change is its
own increment).

### The wiring — three outcomes, and none of them is silent

`build_us_macro_thesis` gained `risk_budget_target: RiskBudgetTarget | None = None`.
The live path now constructs the thesis first and returns
`_apply_risk_axis(thesis, target)`; the **stand-down path returns before the axis**,
which was **measured** correct rather than assumed — §17.4 governs only theses that
reach sizing, and a stand-down has no size to demote.

| Situation | `status` after | What the warning says |
|---|---|---|
| no budget supplied (`target is None`) | `DRAFT` (unchanged) | *"§17.4's sizing feedback **DID NOT RUN**. A `DRAFT` here means 'not yet sized against a book', NOT 'sized and verified'."* — **§21.1 defines no source for portfolio holdings**, so no honest book exists and §21.0 rule 3 forbids inventing one |
| the translator **refused** | `DRAFT` (unchanged) | *"This is a **REFUSAL**, not a demotion: §17.4 demotes a thesis whose size is **too small**, and this is a different finding."* |
| sized at or below `risk.thesis_demotion_fraction` | **`WATCH`** | *"**DEMOTED to `WATCH`** by §17.4: … (binding constraint: …)"* |
| sized above the bound | `DRAFT` | *"Sized by §17.4: …"* |

**The refusal/demotion split is the design point.** Collapsing them would publish a
*refusal* (no position exists) as a *risk verdict* (a position was measured and
found too small) — and §17.4's whole content is the *second* statement, so a fused
warning would attribute a finding to the rule that the rule did not make.

### THE FINDING — the near-zero bound shipped at a value no input could reach

**`thesis_demotion_fraction` was `0.02`. The smallest published
`fraction_of_capital` any input can produce is `0.02941`.** So §17.4 — the single
place the risk layer writes back into the thesis lifecycle, the rule that encodes
the LTCM lesson — was **declared, consumed, and structurally incapable of firing**.

**How it surfaced: a test that SKIPPED.** `test_a_demoted_thesis_moves_to_watch_and_says_why`
ran, skipped, and was reported as a **green tick**.

**The reachable set is six discrete values, not an interval — measured:

```
0.02941 · 0.03472 · 0.042735 · 0.069445 · 0.125 · 0.15
```

`0.02941` is full `f*` `0.05882` divided by `kelly.fractional_divisor` `2.0`.

**Why discrete.** Full Kelly is the argmax of expected log growth. For a
**two-branch** distribution with a positive edge that objective is **monotone in
`f`**, so `f*` pins at the edge of the search domain and the *position cap*
(`max_position_fraction` `0.15`) produces the published number rather than the
Kelly fraction. Only **asymmetric** branch sets land strictly inside the domain —
six such pairs were measured and are the six values above.

**The bound now carries three constraints, and the third is the find:**

1. `> 0` — a zero bound demotes every sized thesis.
2. `< max_position_fraction` (`0.15`) — a bound above the cap can never bind.
3. **`>= the smallest reachable size` (`0.02941`)** — a bound below it is
   **unreachable**, which is the state this increment found `0.02` in.

`0.03` satisfies all three (inside `[0.02941, 0.15)`). **The remedy is not a better
number**: `scripts/live_risk_axis_check.py` **recomputes the reachable set** and
fails if the bound stops splitting it, because a config bound whose validity
depends on the model's output is only safe if something re-derives that output.

**This is the ninth instance of the project's declared-consumed-unreachable class**
(D-045/046/048, O-53, O-27, twice inside D-072) and the **third distinct
vocabulary** it has appeared in — a **lifecycle state**, after a guard and an
instrument sentinel.

### O-96 — §17.4's literal `CANDIDATE → WATCH` names an unreachable transition

§17.4 reads *"demoted from `CANDIDATE` back to `WATCH`."* **Measured: nothing in the
tree produces `CANDIDATE`.** `build_us_macro_thesis` assigns `DRAFT` to a thesis
that reaches sizing and `WATCH` on all three stand-down paths; promotion to
`CANDIDATE`/`ACTIVE` is a **human** act by design, so it has no producer in an
automated build. The axis therefore operates on **`DRAFT`**, the state that actually
reaches sizing, and its warning **names both the state it demoted from and the
state it demoted to verbatim** so no consumer must infer the lifecycle point.
Recorded as **O-96** rather than reinterpreted silently: the two readings differ
downstream, and an implementer's choice between two lifecycle points is exactly
what this ledger exists to record (cf. **O-86**, where `WATCH` already carries two
meanings).

### Verification — all gates green at **218 files**

| Gate | Result |
|---|---|
| `ruff check src tests tools scripts` | **All checks passed** |
| `ruff format --check src tests tools scripts` | **218 files already formatted** |
| `mypy --strict src tests tools scripts` | **no issues in 218 source files** (D-035: matches the line above) |
| `pytest -q` | **2329 passed / 1 skipped / 0 failed** (the skip is the pre-existing Phase-5-gated `test_output_gap.py:255`) |
| `tests/thesis_layer/test_risk_axis.py` | **17 passed, 0 skipped** — run 1 was **14 passed / 3 failed / 1 skipped** |
| `scripts/mutation_risk_axis.py` | **9 applied / 8 killed / 1 survived (the honesty control)** — **CERTIFIES**. Run 1 was **8/6/2**, both survivors **real test gaps** |
| `scripts/live_risk_axis_check.py` | **PASSED (exit 0)** — reproduces the six reachable sizes and confirms a 0.03 bound demotes **1 of 6** |
| `tools/sweep_health.py` | **38 sweeps, 0 failures, 0 leftovers, 0 mutant shapes** |

### The sweep refused to certify on its first run — two survivors, both real gaps

| Mutant | What it changed | Why it survived | Killer added |
|---|---|---|---|
| **M1.2** | the axis's **local** bound → `1.0` | the bound tests read the **config leaf**; the mutation changed the **local variable**. Both were "the bound" and neither test touched the other — **O-29's mis-target class one level up: not a mutation aimed at the wrong function, but tests asserting on the wrong copy of the same value** | `test_the_bound_the_axis_actually_uses_splits_the_reachable_set` — drives the axis and reads the **outcome**, never re-reads the setting |
| **M4.1** | `<=` → `<` on the demotion comparison | every demotion test landed a size **below** the bound, and `<=`/`<` differ on **exactly one value** — if no input produces it, the two operators are the same function and no test can tell them apart | `test_the_demotion_fires_at_the_boundary_not_only_below_it` — plants a size **exactly on** the bound (via `monkeypatch` on the `thesis_demotion_fraction_value` **leaf**, since the property is read-only) |

Both closed by **adding tests, never by exempting a mutant**. Second run
**9 / 8 / 1** with the survivor being the M5 honesty control → **CERTIFIES**.

### Two guards amended, not deleted (D-067), each with a written reason

- **`test_integrity_gates.py`'s Kelly guard — STRENGTHENED.** It now **forbids raw
  primitives**, **enumerates the permitted surface**
  (`translate_thesis_to_position` is the one sanctioned consumer per §25), and adds
  a **behavioural receipt**
  (`test_section_25_gate_precedes_kelly_on_the_translation_path`). Re-checking §25
  showed the original guard was narrower than the section: it tested *where Kelly
  is called*, not *what the gate order guarantees*.
- **`test_builder_strictness.py`'s `macro_engine.portfolio` prohibition — REMOVED.**
  The §17.4 hook **requires** that import from `thesis_layer/builder.py`. **A guard
  forbidding the wiring the specification mandates is a guard against the
  specification.** The removal carries its reason in the test's own docstring, so a
  later reader does not restore it as an obvious tidy-up.

### Where this increment leaves Phase 4

**Phase 4 is COMPLETE (4 of 4).** Items 1–2 closed at D-071/D-072; item 3
(`portfolio_volatility_two_asset` / `marginal_risk_contributions`, §20.12C) closed
at D-072; **item 4 — this hook — closed here.** The Phase-4 instrument functions
themselves (`evaluate_drawdown_rules`, `check_rebalancing_drift`,
`volatility_target_scaling`, `kelly_position_size`) shipped earlier under Tier 4
(D-058–D-062) and are counted there.

**Phase 5 is NOT started, by explicit instruction.** Its entry point is the **13
Tier-5 deferrals**, each of which §22.3 requires to bring **its own verified
data-source registry, its own central-bank reaction function** (the ECB's 20-country
compromise, the BoJ's deflation-scar bias and the PBoC's non-Western rule are
genuinely different logic, not the Fed's Taylor Rule relabelled), and **its own
instrument set**.

**Carried into Phase 5:** **O-96** (above), **O-94** (Q12's exposure half — needs
Module 18, which Phase 5 builds), **O-95** (the `sweep_health.py` reader mismatch is
fixed; the residual question is whether any *other* tool compares source text
against anchors with a different reader — `tools/reachability_audit.py` is the next
one to check), **O-93**, **O-92 · O-90 · O-91 · O-87 · O-86 · O-84**, and **O-101**
(the `M8g` latent silence — armed only if a projection series ever opts into a
tolerance).

**The sweep-failure carry-over is CLOSED, and the do-not-fix list is now EMPTY.**
Every entry that was carried as *"inherited / target absent / DO NOT FIX"* has been
run in full and **every one is KILLED** — `CX5` and `M8d` were stale anchors
(D-075), and `M8e` was never a limitation at all (D-080). **The label was wrong 3
times out of 3.** Running `mutation_lei_proxy.py` to settle it also surfaced a
**real** surviving mutant (`M8g`) that the do-not-fix noise had been adjacent to
for two sessions — see the section above and O-101.


---

## The sweep-leftover detector and the committed-mutant scan (`D-087`) — infrastructure, not a numbered module

**`AGENTS.md` unchanged. No Phase 5 work. No new module.** D-087 repairs two
defects in the **verification infrastructure itself** — the machinery that decides
whether a mutation is left applied (`scripts/_sweep_gate.py`, `tools/sweep_health.py`),
and the committed baseline it must be checked against.

### What was broken

**Defect 1 (O-108) — the discriminator was a false-positive machine.** The
predicate answering *"is this mutation applied, or is the anchor merely absent?"*
was `old not in text and new in text`. `M7b` replaces the *value* of a branch
assignment, and its replacement text (`lead_direction = "broad_based_advance"`) is
**also the legitimate neighbouring branch's own assignment** — so the predicate
fires on a pristine file. Measured against `git show HEAD:` ground truth over the
**622** reachable catalogue entries: **52 false positives, 0 misses.**

**Defect 2 (O-109) — the mutant was committed.** `src/macro_engine/models/lei_proxy.py`
carried `else: lead_direction = "broad_based_advance"` where `"mixed"` belongs, and
the corruption was in **`HEAD` (`5d4c1da`)**. Verified by occurrence count:
`f740d2a` had **1**, `5d4c1da` had **2**. Every prior check was **dirty-relative**,
so none could see it — **including `git diff HEAD`**.

The two masked each other: the false positive made the (true) `M7b` finding look
like noise, and once it was dismissed there was nothing left that could see the
committed corruption.

### What was built

| artefact | role |
| --- | --- |
| `_is_applied(text, old, new)` in `_sweep_gate.py` | exact left-over discriminator: **applied ⟺ `old` absent AND re-applying does not raise `new`'s count**. Measured **0 false positives / 0 misses** over the 622 entries. |
| the same in `tools/sweep_health.py` | duplicated, not imported: `mypy --strict` cannot span `tools/` and `scripts/` — neither is a package. |
| `_committed_blob(rel)` + `_committed_mutant_scan(catalogue)` in `tools/sweep_health.py` | the O-109 remedy — reads each target's committed text via `git show HEAD:` and flags a catalogue entry whose replacement is **already in HEAD** with its anchor absent. |
| new summary line `committed mutants (O-109, vs HEAD)` | the reach the old report had no row for. |
| `tests/test_sweep_health_leftover_predicate.py` | **15** guards — 4 behavioural, 3 structural, 2 for the committed scan. |
| `models/lei_proxy.py` | `else: lead_direction = "mixed"` restored (the actual source defect). |

### Why the count-stable predicate is exact, not heuristic

A mutation is a **text substitution**. A genuine left-over **already contains** the
replacement, so applying `old→new` *again* would **duplicate** it — the count rises.
A **drifted anchor** leaves the count unchanged. So *"re-applying does not raise the
count"* separates the two cases exactly. Three other candidates were scored against
ground truth first; the **first attempt passed the reported case but failed 9 real
entries** (prefix-extensions where `new` contains `old`, and wrong-occurrence
`find`), which is why the score table exists.

### Proof (RED → GREEN, both fixes)

- **Detector:** re-inject the old predicate into both files → **2 guards FAIL**
  (measured on the shipped, corrected loader — an earlier figure of 7 was taken
  under a broken loader and is retracted; see `DECISIONS.md` D-087.5);
  restore (byte-identical verified) → **all pass**.
- **Source:** re-apply the `M7b` mutant → the demanding test
  `test_a_broad_advance_requires_the_composite_to_agree` **FAILS** plus 2 siblings;
  restore (byte-identical) → **55 pass**.
- **Committed scan:** fires on `5d4c1da`'s blob, silent on the repaired tree. (Reads
  **0** once this increment is committed — the repair is in the working tree, `HEAD`
  still carries the mutant until then.)

### Gates at close (re-derived by execution — O-88; a row is a claim, not a receipt)

| gate | value |
| --- | --- |
| `ruff check` | **All checks passed** |
| `ruff format --check` | **231** files |
| `mypy --strict` | **231** files (D-035 parity: counts must match) |
| `pytest -q` (default, `not live and not slow`) | **2536 passed / 4 skipped / 0 failed** in **113.8 s** |
| `pytest -q -m slow` | **1 passed** in **230.8 s** |
| `tools/reachability_audit.py --check-baseline` | **PASS** — baseline 58 = measured 58, no regressions |
| `tools/sweep_health.py` | 40 sweeps, 0 leftovers, 0 mutant shapes, 1 committed (pre-fix `HEAD`) |

**D-087.6 — the default run no longer includes live tests.** `addopts` was
`-ra --strict-markers --strict-config` with **no `-m` filter**, so a plain
`uv run pytest` ran the `@pytest.mark.live` tests even though the marker's own text
says *"excluded from default CI runs"*. The worst builds a **~21-series** live
snapshot; at **3 retries × 15 s + backoff** per series (~49.5 s worst case, then the
other path once) that is **~17 min for one test** — measured at **40+ min** stuck.
`addopts` now carries **`-m 'not live and not slow'`**: a default run is **~114 s**.
Live runs are explicit (`-m live`). **Opens O-110.**

### Also removed

`docs/MODULE_MAPPING.md` carried the entire **D-082 addendum section duplicated
verbatim** (73-line body, twice, second to EOF). Second copy removed after the
bodies were verified byte-identical — **76 deletions, 0 additions**.

**Not committed.** The tree is left dirty with this fix; the user pushes.

---

## Module 18 — `run_regression`, with a mandatory mechanism gate (`D-092`) — **PHASE 5, 1 of 13+**

**Files:** `src/macro_engine/models/econometrics.py` (**NEW**),
`config/settings.yaml` (the `econometrics:` section), `src/macro_engine/config.py`
(`EconometricsSettings` + the `Settings` field), `tests/models/test_econometrics.py`,
`scripts/live_econometrics_check.py`, `scripts/mutation_econometrics.py`, plus the
three-place sweep-census bump.

**Spec:** §15 Module 18 (Module 18 — *"Regression requires an economic mechanism BEFORE
statistical significance is trusted (never data-mine)"*; *"low R² = genuine
humility signal, not failure"*; *"non-stationary level regression is spurious"*;
*"PCA on daily changes, never levels"*), §15.20-F (the prose-only function block),
§21.0 (the no-prototyping rule), §21.2 Steps 4-5 (hand-verified values; warning
paths), §22.1 (stub-then-implement), §22.3 (US-only through Phase 4), §22.8
(confidence is computed, never asserted), §3 (the reasoning-object contract).

### Completion checklist (§21.0 / §21.2 Step 9)

- [x] **Implemented exactly as specified** — `run_regression(y, X, require_mechanism)`
      with the §F signature, returning `RegressionResult` carrying `beta`,
      `r_squared`, `adj_r_squared`, `p_values`, `n_obs`, `multicollinearity_vif`.
- [x] **Unit test with hand-verified expected values passes** — 36 tests; the golden
      case is derived by **exact rational arithmetic** in the test file's header
      (`beta = {const: 12/5, x: 5}`, `R² = 625/729`, `adj R² = 68/81`).
- [x] **Executed against real data from its documented source** — `FEDFUNDS` and
      `CPILFESL`, transcribed from `config/series_registry.yaml` and re-asserted
      against it at run time so a re-pointed registry cannot go unnoticed.
- [x] **The real-data output is economically plausible, and that assessment is
      written down** — see below.
- [x] **Every `warnings` condition triggered at least once** — three warnings, each
      with a test that it fires **and a negative control** that it does not fire on
      a fit that lacks the condition.
- [x] **`ruff` and `mypy --strict` clean** — and the whole-tree parity holds,
      247 = 247.
- [x] **Documented with its real-data validation record** — this section.

### Real-data validation record

**Source:** FRED, through the registry's own provider route (`economy.fred_series`).
**Run:** `uv run python scripts/live_econometrics_check.py` → **LIVE CHECK PASSED**.
**Service state at the time:** the OpenBB API was serving (it later degraded to the
O-111 bound-but-502 state, which is unrelated to this module).

| Check | Observed | Assessment |
|---|---|---|
| Fisher relation: policy rate on YoY **core** inflation | slope **+1.0972**, R² **0.5688**, **823** months, 1957-01..2026-08 | **Plausible.** The sign is what the mechanism predicts, and the *magnitude* read against 1.0 is **above** full compensation over this window — a property of this sample and this inflation measure, not a structural claim. The fit is loose (R² ≈ 0.57), which is a real finding about the relation rather than a defect: the policy rate responds to *expected* inflation and to growth, and this regression has only realised inflation. |
| Mechanism gate on the same real frame | **3/3** insubstantial mechanisms refused | The gate is not a synthetic-only path: the identical frame that produced the fit above refuses a blank, whitespace and placeholder mechanism. |
| Spurious level regression: core-CPI **level** on retail-sales **level** | coefficient **+0.000310**, R² **0.9854**, p **0.00e+00**, **415** months | **This is the hazard, reproduced.** No mechanism links the two *levels*; both simply trend, and the fit reports a "highly significant" coefficient anyway. That is exactly what `limitations` warns about, measured rather than quoted. |

**Two defects this increment found in itself, both recorded in D-092:**

1. **Perfect collinearity was not refused.** Detection was a finiteness test on the
   variance inflation factors — but for a singular design
   `variance_inflation_factor` returns a **large FINITE number** and only warns, so
   the guard passed exactly the case it existed to catch. Replaced with an exact
   `np.linalg.matrix_rank` check; the now-unreachable finiteness branch was deleted.
2. **A weak test, found by the new sweep.** M15 turned a `decision_prohibition`
   into a *permission* and **survived**, because the test asserted only that the
   word `"causal"` appeared. The test now asserts the property — every prohibition
   must contain a negation. Re-run: **19/19 killed**.

### Sweep

`scripts/mutation_econometrics.py` — **19 mutations, 19/19 killed**, CANARY1
required-killed and confirmed killed (so the selection demonstrably reaches the
mutated module). Covers the mechanism gate, the confidence derivation, the three
warnings, all six refusals, the VIF intercept exclusion, the `None`-vs-`{}`
contract, `adj_r_squared`, the stationarity caveat, the causal prohibition, and
`value == beta`.

### Not done here, and named rather than left silent

- **`test_stationarity` does not exist.** `run_regression` therefore cannot test
  what §15 Module 18 tells it to test first, and says so in `limitations` on every call.
  It is the next sub-increment.
- **`compute_pca` needs `scikit-learn`, which is not a dependency.** Measured:
  `import sklearn` → `ModuleNotFoundError`. §4 requires a recorded decision before
  adding one — and `numpy.linalg.eigh` may make the dependency unnecessary. That
  decision belongs to its own increment.
- **`O-94` is not closed by this.** It needs the Module 18 tooling; this is the
  first of the six functions it will use.

---

## Module 18 — `test_stationarity`, and the tie neither test may break (`D-094`) — **PHASE 5, 2 of 13+**

**Files:** `src/macro_engine/models/econometrics.py` (`test_stationarity` + four
helpers), `config/settings.yaml` (+6 leaves), `src/macro_engine/config.py`,
`tests/models/test_econometrics.py` (+23 tests), `scripts/live_econometrics_check.py`
(§4), `scripts/mutation_econometrics.py` (+12 mutations).

**Spec:** §15 Module 18 (Module 18 — *"non-stationary level regression is spurious (test
stationarity first)"*), §15.20-F (the function's own block: ADF **and** KPSS, nulls
**inverted**, disagreement *"itself informative (inconclusive), not something to
resolve by picking the convenient one"*), §21.0, §21.2 Steps 4-5, §22.8, §3.

### Completion checklist (§21.0 / §21.2 Step 9)

- [x] **Implemented exactly as specified** — `test_stationarity(series) -> ModelResult`
      with the §F signature, running **both** tests and publishing each statistic,
      each p-value, each rejection boolean, and the verdict.
- [x] **Unit test with hand-verified expected values passes** — 61 tests in the file.
      The fixtures are **seeded and found by sweeping**, not taken from the first
      candidate: a genuine random walk at n=200 gave ADF p = 0.037 (a rejection),
      so "random walk" is not reliably a clean non-stationary case.
- [x] **Executed against real data from its documented source** — FRED, through the
      registry's provider route; the live check re-asserts the transcribed symbols
      against `series_registry.yaml` at run time.
- [x] **The real-data output is economically plausible, and that assessment is
      written down** — see below.
- [x] **Every `warnings` condition triggered at least once** — four disclosures
      (KPSS clipping, conflict, low power, rank-deficient ADF design), each with a
      test that it fires **and** a negative control that it does not.
- [x] **`ruff` and `mypy --strict` clean** — whole-tree parity, 247 = 247.
- [x] **Documented with its real-data validation record** — this section.

### Real-data validation record

**Source:** FRED (`CPILFESL`, `RSAFS`, `FEDFUNDS`) through the registry's own route.
**Run:** `uv run python scripts/live_econometrics_check.py` → **LIVE CHECK PASSED**.
**Service:** the OpenBB API was serving (278 paths).

| Series | Verdict | ADF p | KPSS p | Assessment |
|---|---|---|---|---|
| core CPI, **LEVEL** | `non_stationary` | 0.9991 | 0.0100 (clipped) | **Plausible.** A price index is the textbook I(1) series; both tests agree. |
| retail sales, **LEVEL** | `non_stationary` | 0.9987 | 0.0100 (clipped) | **Plausible.** Nominal retail sales trend strongly; both agree. |
| core CPI, **first difference** | `non_stationary` | 0.1558 | 0.0100 (clipped) | **A second finding, and the reason the first draft of this check was wrong.** The *growth rate* itself shifted across 1957–2026 (double-digit inflation in the 1970s against roughly 2% recently), and KPSS's null is stationarity around a **constant** — which a change series with a moving mean does not satisfy. This is the Great Moderation visible in a stationarity test. |

**The payoff:** D-092 reproduced a spurious fit (core-CPI level on retail-sales
level, R² 0.9854, p 0.00e+00) and stated plainly that it **could not diagnose** it
because `test_stationarity` did not exist. It exists now, and both levels reading
`non_stationary` is the missing half of that argument: two I(1) series regressed on
each other produce a significant coefficient from their shared trend.

### Two defects this increment found in itself

1. **The live check's assertion was an over-claim about real data**, and the live
   run **failed** on it. Requiring the first difference to be stationary was an
   assumption, not a property of the method. The assertion now requires only the
   necessary condition and *reports* the difference.
2. **Two weak tests, both mutation survivors.** M28 (a hardcoded
   `significance_level`) survived because the config *is* 0.05 — fixed by moving the
   config and requiring the verdict to follow. M30 (the constant-series guard
   deleted) survived because statsmodels raises its own `Invalid input, x is
   constant`, which the test's bare-word match accepted — **the test was passing on
   the library's error rather than on our refusal.**

### Sweep

`scripts/mutation_econometrics.py` — **33/33 killed** (was 21/21). Twelve new
mutations, of which **M21 is the one that matters**: swapping the two inverted-null
booleans transposes **every verdict the function ever produces**, while both tests
still run and still return numbers.

### Not done here, and named rather than left silent

- **`test_cointegration` is now UNBLOCKED** — both of its dependencies exist. It is
  the next increment, and §15.20-F requires more of it than of either predecessor:
  the spread series, its half-life, a regime-stability check, and two mandatory
  warnings (backward-looking estimates break in regime change; multiple pairwise
  tests without a correction inflate false positives).
- **`compute_pca` still needs a §4 `scikit-learn` decision** — not a dependency, not
  installed, and `numpy.linalg.eigh` may make it unnecessary.
- **`O-94` is not closed by this.** It needs the Module 18 tooling; two of the six
  functions now exist.

## Module 18 — `test_cointegration`, and a fourth silent failure in `coint_johansen` (`D-097`) — **PHASE 5, 3 of 6 in Module 18**

**Files:** `src/macro_engine/models/econometrics.py` (`test_cointegration` + ~14
helpers), `config/settings.yaml` (+4 leaves), `src/macro_engine/config.py`,
`tests/models/test_econometrics.py` (+~45 tests, **and 5 renamed**),
`scripts/mutation_econometrics.py` (**33 -> 56 mutations**),
`scripts/live_econometrics_check.py` (§§5-7 + assessment).

**Spec:** §15.20 **block F** (the function's own signature block — **not**
"§15.18-F", which §15.18's narrative was mis-cited as for three increments; fixed in
30 places at **D-095**), §15.18-F (the narrative: the spread, the half-life, the
regime check, and the two mandatory warnings), §21.0, §21.2 Steps 4-5, §22.8, §22.3
(US-only), §9 (the shared-basis requirement).

### Completion checklist (§21.0 / §21.2 Step 9)

- [x] **Implemented exactly as specified** — `test_cointegration(y, x, method="engle_granger") -> ModelResult`
      with §F's verbatim signature, publishing the statistic, the p-value, the
      critical triple, the rejection boolean, **the spread series**, **the
      half-life**, **the regime-stability verdict** and **both mandatory warnings**.
- [x] **Unit test with hand-verified expected values passes** — the half-life is
      asserted against the **closed form** (`phi = -0.5 -> H = 1.3863`, `rho = 0.5`),
      not against a recorded float.
- [x] **Executed against real data from its documented source** — FRED through the
      registry's provider route, with every transcribed symbol re-asserted at run
      time.
- [x] **The real-data output is economically plausible, and that assessment is
      written down** — see below. **The narrative lost on the term-structure pairs
      and the check reports that rather than asserting around it.**
- [x] **Every `warnings` condition triggered at least once** — the two mandatory
      warnings, the shared-basis disclosure, the no-cointegration disclosure, the
      not-reproduced-by-either-half contradiction, the half-life disclosure tiers,
      the multiple-testing counts, and the `discarded_imaginary_warnings` notice.
- [x] **`ruff` and `mypy --strict` clean** — whole-tree parity, **247 = 247**.
- [x] **Documented with its real-data validation record** — this section.

### Real-data validation record

**Source:** FRED (`FEDFUNDS`, `DFF`, `DFII5`, `DFII10`, `DFII30`, `DGS10`) through
`economy.fred_series`. **Run:** `uv run python scripts/live_econometrics_check.py`
→ **LIVE CHECK PASSED**. **Service:** `:6900` serving, **200, 278 paths, 0.18 s**
(`:6901` answers **502** — the known dead port).

| Pair | n | stat | p | cointegrated | hedge | half-life | regime | Assessment |
|---|---|---|---|---|---|---|---|---|
| **`FEDFUNDS ~ DFF`** (positive control) | 866 | −5.3276 | 0.0000 | **True** | 0.9485 | **0.7324** | **stable** | **Plausible and reassuring.** The same policy rate at two frequencies; a non-rejection would have been a wiring fault. The hedge ratio near 1 is the arithmetic identity showing through. **This is what makes the three rows below informative.** |
| `DFII5 ~ DFII10` | 285 | −2.8848 | 0.1402 | False | 1.0743 | 9.0578 | absent_in_both_halves | **Plausible, and against the story.** See below. |
| `DFII10 ~ DFII30` | 200 | −1.8957 | 0.5822 | False | 1.0645 | 12.1212 | absent_in_both_halves | **Plausible.** The weakest of the three; the shortest sample. |
| `DFII10 ~ DGS10` | 285 | −3.1757 | 0.0741 | False | 0.8307 | 7.2508 | **unstable** | **The LTCM shape, in real data.** The two sub-periods disagree. Note p = 0.0741 — *close*, and close is exactly where the multiple-testing warning matters: one of these four pairs clearing at 0.07 out of an assumed family of 10 is unremarkable. |

**THE NARRATIVE LOST.** The tempting claim — that yields on one curve sharing a
policy-rate trend must cointegrate — is **false on this data**, and the check asserts
nothing about it. The expectations hypothesis is a statement about **ex-ante** yields;
the realised TIPS spreads over 2003–2026 are wide and persistent (2013's taper
episode and the 2022-23 inversion both sit inside the window), which is exactly what
makes them fail a stationarity test. **Asserting cointegration would have repeated
D-094's failure** — a live check that asserted the data into agreement — so section 7
**reports** and the plausibility paragraph says plainly that the story lost.

**The counting obligation reproduces on live settings:** at `alpha = 0.05` and an
assumed family of 10, family-wise error rate **0.4013**, corrected per-test size
**0.00511620** — recomputed from the configured values and compared exactly.

### The fourth silent failure, on the operator's explicit instruction to assume one

**`coint_johansen` emitted 4 `ComplexWarning`s on EVERY call and they escaped the
function.** `np.linalg.eig` returns complex eigenvectors cast to real; uncaptured,
statsmodels' internals reached the caller's output and **`-W error` raised on every
Johansen test** — a correct function unusable in a strict environment, with every
published field still correct. **Measured across 40 seeds and n = 60…1600: the
warnings are unconditional and none correlated with a non-finite statistic**, so they
carry no information about the fit. **Fixed** by `catch_warnings(record=True)`,
publishing `discarded_imaginary_warnings`, and appending a disclosure that states
this is library behaviour and **must not be read as a signal**. Swept as **M49**
(leak restored) and **M50** (disclosure dropped), both killed.

### Four defects this increment found in itself

1. **FIVE TESTS WERE SHADOWED BY NAME AND SILENTLY ABSENT FROM THE RUN.** Four new
   refusal tests reused `test_stationarity`'s names; one collided with
   `run_regression`'s. Python keeps the **last** definition, so five earlier guards
   vanished while pytest stayed green. **Only `ruff`'s F811 saw it.** Fixed by
   qualifying the names; the count moved **2872 -> 2923 passed**, which is the
   evidence rather than the claim. **D-093's lesson, one level up: identifiers, not
   arithmetic — and here the identifier is a test name.**
2. **M52 proved `is_cointegrated` was never asserted to a specific value anywhere.**
   The suite checked the statistic, the p-value, the spread and the warnings, and
   never once that the verdict was `True` or `False`. A mutation inverting the
   comparison survived. Closed with both directions.
3. **M53 proved the Johansen `n_obs` was never checked** — and it was a **real
   defect** (it read the *spread*'s length, which is zero on that path, publishing
   `n_obs = 0` beside a statistic computed from hundreds of rows). Fixed, then
   tested.
4. **Two arity defects in my own new guard code** (`for name, _ in _iter_mutations()`
   and `for name, _, _, _ in MUTATIONS`). Each raised **after the sweep had finished
   but before it certified** — a run that measured everything could not say what it
   found. Both fixed, and the branches are now exercised by hand-built tables. **The
   first harness "passed" while the real code raised, because it reproduced my own
   assumption (4-tuples for both operands) rather than the code's data.**

### Sweep record

`scripts/mutation_econometrics.py` **33 -> 56 mutations** — **extended, not added
to**, so the census stays **43** (`sweep_health`: 43 sweeps, 0 leftovers, 0
failures). **Final 55/56 killed** (the one survivor is M34, inert-by-route). First pass
was **46/56**; every survivor it exposed was closed — five were holes in this
increment's own tests, and three (M2/M30/M32) were **corrupted verdicts** caused by the
shadowed names.

**New mechanism: `INERT_BY_ROUTE`.** A survivor that is merely "expected" is
indistinguishable from a dead gate, so the register demands a **stated, measured**
reason and **refuses to certify (exit 5)** on a stale, dangling or unexplained entry.
One entry: **M34**, measured over **93 (configuration × trend) combinations** with
**31 non-finite critical-value cases and ZERO non-finite p-values** — `coint` trips
the critical-value guard first on every input, so M34's branch is never evaluated.
The guard is kept as defence against a future statsmodels release, and the route
**is** reached directly by `test_the_non_finite_guards_fire_when_the_route_is_reached`
(which kills **M35**).

**M2 / M30 / M32 read as surviving and were NOT holes — they were CORRUPTED VERDICTS.**
The rename that fixed defect 1 below took the sweep from **52/56 to 55/56 with no
mutation changed**, which falsified the earlier reading. The shadowed test names meant
the sweep was killing those three with the **wrong tests** — `M30`/`M32` were "saved" by
`test_cointegration`'s refusals (different messages, different function) and `M2` by
nothing at all, because its covering test had been deleted from the run. **Proven by
applying each mutation with the sweep's OWN anchors:** each swap compiles OK and the
suite fails (`1 failed, 111 passed`). **O-117 is CLOSED.** The one remaining survivor is
**M34**, inert-by-route. *A mutation sweep's verdict is only as trustworthy as its test
SELECTION, and a duplicated test name changes that selection silently.*

---

## D-100 — `compute_pca` (Module 18 #4)

**Sweep:** `mutation_econometrics.py` **77 mutations, 76/77 killed.** The one survivor
is **M34** (`non-finite p-value refusal`), **INERT_BY_CONSTRUCTION** and registered
with a re-measurement across **93** (configuration × trend) combinations: **31**
returned non-finite critical values, **ZERO** returned a non-finite p-value, because
`coint` raises on the NaN critical values (M35) before M34's branch is reached. The
route *is* reached directly by
`test_the_non_finite_guards_fire_when_the_route_is_reached`, so the family is proven
live even though this member is not.

**M66 is now KILLED, and how it was killed is the finding.** M66 replaced the
constant-series guard's **relative** tolerance with a fixed `eps * 100 = 2.22e-14`
and **SURVIVED** the first run of the suite, because every constant the tests then
used (`4.2`, `0.0`, `-3.0`) leaves a floating-point residue small enough that a
fixed epsilon also catches it — so **no test could tell the two guards apart**.

**Measured 2026-09-23: the residue is NOT monotone in magnitude.** It depends on how
`c - mean` rounds at that scale:

| constant | residue | defeats a fixed `2.22e-14`? |
| --- | --- | --- |
| `4.2` | `7.1e-14` | yes (near-miss, 3.2×) |
| `271.83` | `1.1e-13` | **yes** |
| `314.16` | `4.3e-14` | **yes** |
| `1e6` | exactly `0.0` | no |

So the magnitudes that defeat a fixed epsilon are **specific ones and had to be found
by measurement**, not chosen as "large". `test_the_constant_refusal_is_scale_relative_not_absolute`
now carries `271.83` and `314.16`, **verified to kill M66 by applying the mutant by
hand and watching the test fail**. The sweep moved **74/77 → 76/77**.

**The generalisable rule:** *a guard whose tolerance is RELATIVE can only be proven
relative by a case where the relative and absolute answers DIVERGE. Agreeing on the
easy magnitudes proves nothing.*

**⚠️ O-117 RECURRED here, one increment after it was diagnosed.** Two `compute_pca`
refusal tests were written with names already owned by `test_stationarity`
(`test_a_constant_series_is_refused`, `test_a_non_numeric_series_is_refused`), so
Python bound each module-level name to its **last** definition and **two stationarity
guards were silently DEAD** — the stationarity constant-series and non-numeric guards
had **no coverage at all** while appearing present. `pytest` collected **176** tests
where **178** existed. `ruff check tests/models/test_econometrics.py` reported
**F811 twice** — exactly the standing guard O-117 names. Fixed by suffixing the
`compute_pca` copies `_by_pca` (matching the file's existing `_by_cointegration`
convention); the collected count rose **176 → 182** and `ruff` is clean. **The count
movement IS the evidence** that two tests had been silently absent. O-117's row in
`docs/OPEN_ISSUES.md` now carries this recurrence.

**⚠️ O-118 — the `.git` object store and `refs/` were WIPED mid-increment.** `git
status` returned `fatal: not a git repository` while `.git/` was present: `refs/` was
**absent entirely**, the pack file was **gone** (only its `.idx` remained), and loose
objects were **0**. The **working tree was untouched** — no engineering work was lost.
Recovered from the surviving **reflogs** plus the remote. **One commit was genuinely
lost: `2027b6c`, which had never been pushed.** Final state: `git fsck --no-progress`
returns **completely clean**, `HEAD` = `6d5f253` = `origin/main`. **The durable habits:
run `git fsck` (not `git log`) to prove integrity, and PUSH IMMEDIATELY AFTER
COMMITTING — an unpushed commit is a single point of failure.**

**Gate baseline after D-100 (measured):** ruff clean · `ruff format --check` **247
files** · `mypy --strict` no issues in **247 files** · **2993 passed / 1 skipped / 17
deselected / 0 failed** · sweep **76/77** (77 declared) · **43 sweeps, 0 leftovers,
0 mutant shapes** · reachability **58 = 58** · live check **PASSED** (680 real
Treasury observations).

---

## D-101 — Module 18 #5: `kalman_latent_state` (2026-09-23)

**Tier 5 = 5/23. Module 18 = 5 of 6.** Spec §15.20 block F (AGENTS.md:3187).
**Block F holds FIVE signatures, not four** — D-100's count was taken from the
implemented functions rather than from the block.

`kalman_latent_state(observations, state_dim=1) -> ModelResult` estimates an
**unobservable** state from a noisy series, built from **explicit state-space
matrices** with three specifications selected by `(n_columns, state_dim)` and
published as `model_spec`. Every result carries the **filtered path with its
uncertainty band**, the smoothed path's endpoint, and the measured revision between
them. `direction` is `None` (a level is not a directional signal) and confidence is
priced with `depends_on_unobservable=True` — §21.4 item 13's literal case.

### The four silent failures, each found by probing BEFORE the function existed

| Route | What it actually did |
| --- | --- |
| `UnobservedComponents(y, level=True)` | A **deterministic constant** (`stochastic_level` defaults to `False`): reported `102.33 ± 0.18` on a random walk whose level moved several units. `level='rwalk'` drops the irregular, collapsing the band to **exactly `0.0`**. |
| `mle_regression=False` | State covariance `[[0.]]` → a **recursive OLS** estimate converging to the full-sample constant: `0.4793` against a true `0.4267`, and `0.4793` **is** the OLS value, with a standard error of `0.0023` that makes the wrong answer look precise. |
| A missing parameter transform | **Negative variances** and `nan` bands (`sigma2.slope = -3.24`) with every published field `nan`. |
| **`initialization='diffuse'`** | **A standard error of exactly `0.0`** for a state the first observation does not identify (a trend's slope, design `[1, 0]`). The filtered **states** were identical across all three initializations; only the published **uncertainty** differed. This decided the design. |

### Two measured defects in the fit itself

**Unit-dependence.** The model is scale-invariant; the **optimizer** is not. One
local level at six scales gave `sigma2.level / scale**2` of **0.3139** (scale 1),
**0.3238** (1e-3), **46.16** (1e3), **2.663** (1e6), **0.02625** (1e9) — a **147×
spread on identical data**, so the band and every warning reading it depended on the
caller's **units**. Fixed by normalising each series before fitting and converting
back, with the scales published. **After: `0.313922` at every scale from 1e-9 to
1e9.**

**The wrong optimizer family.** Over 20 simulated pairs, non-converged fits:
**`lbfgs` 4/20, `bfgs` 12/20, Nelder-Mead 0/20, Powell 0/20** — with Nelder-Mead at
the **same** optimum. The iteration cap did not matter, which identifies the stopping
*rule*; the likelihood is flat in the variance parameters, so gradient information is
unreliable. `kalman_optimizer` defaults to `"nm"`.

### A warning REMOVED, and a design decision FALSIFIED by the live check

A relative "degenerate band" warning was deleted because **no threshold separates the
collapsed-band case from a well-specified one** — `median(se)/median|state|` spanned
`3.1e-8`–`1.8e-3` for noise-free samples. It is a **limitation** now, with
`sigma2.irregular` published so a reader can judge.

**Then the live check FAILED its own control**, and that failure was the increment's
most useful event: the control expected a *warning* on a constant series, but the
state variance collapses to `1e-12` while the **band collapses further**
(`1.65e-09`), so the drift-to-band ratio came back as **6055** and nothing fired. The
stated rationale for NOT refusing a constant series was **false**, so a series with
no variation is now **refused**, as `compute_pca` refuses one, and the control asserts
the refusal. **A control that can only pass is not a control**, and **the unit test had
chosen the case that worked** (a constant *beta*, where the drift is exactly `0`).

### Harness findings

* **Adding a function made a NEIGHBOUR's anchor ambiguous** — `M69`'s guard line
  gained a second occurrence (the D-055 trap). `tools/sweep_health.py` caught it; the
  anchor was widened by its distinguishing neighbour. **This is why the rule is
  "re-run every sweep whose path touches the file you added to".**
* **A redirected sweep's log is BLOCK-BUFFERED.** A sweep SIGTERM'd after ~36
  mutations left a **zero-byte log** while the sidecar correctly preserved the tree.
  The tree was restored from the sidecar and verified byte-identical (0 mutants), and
  the progress prints now carry `flush=True`. **O-120** records that a 109-mutation
  sweep no longer fits the foreground window.
* **The first full sweep found two REAL gaps** — `M94` (the non-finite output guard
  was reached by no test, though a `1e300`-scale series reaches it) and `M105` (a
  partial-message mutation whose asserted word sat on the second line of a
  concatenated string). Both fixed and both now **KILLED**.
* **A typo'd anchor and a leftover are indistinguishable** to the leftover predicate
  (**O-119**).

**Gate baseline after D-101 (measured 2026-09-24):** ruff clean · `ruff format --check`
**247 files** · `mypy --strict` no issues in **247 files** · **3068 passed / 1 skipped /
17 deselected / 0 failed** · sweep **108/109** (109 declared; M34 inert-by-route) ·
**43 sweeps, 0 leftovers, 0 mutant shapes** · reachability **58 = 58** · live check
**PASSED** (319 real monthly CPIAUCSL observations, 680 common daily DGS10/DGS2
observations).

**⚠️ `EXIT=1` FROM A SWEEP IS NOT EVIDENCE OF A SURVIVOR.** The final run exited 1 on a
sweep that had **completed at 108/109**, because the sandbox's per-turn bulk-delete
counter (`count: 167` against a threshold of 50) **refused the sweep's own sidecar
cleanup**. The certification block must be read and the tree checked independently; a
stale sidecar was left behind, verified **byte-identical to the live file**, and
removed. Same counter that makes test counts non-reproducible — here it reached the
sweep's *cleanup* rather than its tests.

---

## D-102 — Module 8's `yield_curve_pca` (2026-09-24)

**Tier 5 = 6/23.** §6.6, Module 8, `models/yield_curve.py`.
`yield_curve_pca(daily_changes) -> ModelResult` — §6.6's signature, **no
`n_components`**.

It consumes `compute_pca` and adds the **maturity ordering** (the axis a component's
shape is read across), **`sign_changes`** (a DESCRIPTIVE count — measured on five real
Treasury tenors: PC1 0, PC2 1, PC3 2), and §6.6's three-component scope. It publishes
the loadings keyed in maturity order, with `tenor_years` beside them so the ordering is
checkable rather than asserted.

**It never names a component.** §15.20-F forbids level/slope/curvature, and a test
scans every published string and every loadings key for the forbidden phrases — the
curve context is where the temptation is strongest and the prohibition therefore
matters most.

**Findings:** `_tenor_years` refuses all eleven registry tenor labels, so a second
parser was required (**O-123**); the D-055 trap fired in `mutation_curve_trade.py`'s
M7.4, a sweep for a *different* function, because the new parser duplicated
`_tenor_years`'s opening line; **MX8b survived the first sweep because `dict == dict`
ignores key order**; and the sweep-log buffering hole was general — **42 of 43 sweeps**
had no `flush`, fixed once in the shared `_sweep_gate.line_buffer_stdout()` (**O-124**
covers the two that bypass it).

**⚠️ `EXIT=1` FROM A SWEEP IS NOT EVIDENCE OF A SURVIVOR (O-122).** The D-101 certified
run exited 1 on a sweep that had **completed at 108/109**: the sandbox's per-turn
bulk-delete counter refused the sweep's **own sidecar cleanup**, leaving a stale
sidecar. Read the certification block and check the tree independently.

**D-103 (2026-09-24) — a harness increment, no model function (Tier 5 stays 6/23).**

* **`EXIT=1` from a sweep now means what it says (O-122, CLOSED).** The cleanup was a bare
  `unlink` inside `sweep_lifecycle`'s `finally`; the sandbox's per-turn bulk-delete counter
  refuses deletes past 50, so on a 109-mutation run the cleanup raised **out of the context
  manager** and the sweep exited **1** after printing a clean **108/109**. `remove_sidecars()`
  reports the refusal, returns the paths, and does not raise. Tested with a directory where
  the sidecar belongs.
* **The sweep owns the MACHINE.** Competing gates measured a **10× slowdown** (12 s → 2 min
  per mutation), and `mypy --strict` on a file that *imports* the swept module type-checks the
  **mutated** source. The banner now prints at every sweep's start.
* **`sweep_health` gained a GATE (O-124, CLOSED):** a sweep with neither `sweep_lifecycle` nor
  `line_buffer_stdout` is a FAILURE. Measured: **0 sweeps** lack it.
* **O-117 recurred** — a duplicated append defined a test name twice, and a duplicate name
  **silently DELETES a test**. mypy `no-redef` caught it. **A LF anchor against a CRLF file
  matches nothing, silently** — it bit three times in one session.

**D-104 (2026-09-24) — two repo-wide GATES, no model function (Tier 5 stays 6/23).**

`tests/test_source_hygiene.py` asserts the two invariants that recurred most often and that no
existing gate could see:

* **No module defines a top-level name twice** (O-117, recurred ×3). Python binds the LAST
  definition, so a duplicate `test_*` silently deletes a test while `pytest` reports a healthy
  count. Asserted directly rather than left to `ruff` F811 / mypy `no-redef`, because a
  per-file lint of the file you just edited is exactly where a duplicate hides.
* **No source file contains a carriage return.** An anchor written with `\n` matches ZERO times
  in a CRLF file — the edit looks applied and changes nothing. **`git` cannot detect this:**
  `git status` was clean and `git add --renormalize` staged **nothing**, because the stored form
  was already LF. **21 working-tree files** were CRLF and are now LF.

**The CRLF gate found a live defect on its first run:** `tools/reachability_audit.py:133` called
`write_text` without `newline=""`, writing the reachability baseline as **78 CRLF / 0 LF** — the
exact D-061 defect class. Fixed at the root; the regenerated baseline is content-identical under
a CR-insensitive comparison. **18 `write_text` calls lack `newline=""`**; 17 are `tmp_path`
fixtures (**O-125**).

Both gates carry a divergent-case test, and the walk carries a >200-file control, because both
are vacuously true on an empty list.

---

## D-105 — Module 3's `classify_regime_markov_switching` (2026-09-24)

**Tier 5 = 7/23.** §6.2, Module 3, `models/regime.py`. The Tier-5 REPLACEMENT for
`classify_regime_rule_based` (§21.3, D-096): Phase 5+ builds the sophisticated
version and **deletes nothing**, so both classifiers ship.

### What is NEW in the tree

* `src/macro_engine/models/regime.py` — `classify_regime_markov_switching`, the
  `MARKOV_REGIME_ORDERING_RULE` / `MARKOV_TRANSITION_ORIENTATION` constants, the
  `_relative_span` / `_canonical_regime_order` / `_canonicalise_fit` /
  `_require_markov_series` helpers. It is the **first `statsmodels` import in this
  module** (the sibling `econometrics.py` already imported it at module level).
* `src/macro_engine/config.py` — a new `MarkovRegimeSettings` model and a
  **required** `markov` field on `RegimeSettings`. Six numeric leaves (five
  positive, one a share strictly inside `(0,1)`) and three choices as **plain
  leaves** (`switching_variance`, `markov_trend`, `markov_optimizer`) — Section 4a:
  the `CalibratedValue` envelope is for NUMBERS, and a selection has no such
  question. `markov_trend` is restricted to `{"c", "ct"}` because `"n"` and `"t"`
  produce **no regime intercept** (probed), which would leave the canonical
  ordering with nothing to sort on.
* `config/settings.yaml` — the `regime.markov` block, every note carrying its
  measurement.
* `scripts/live_regime_check.py` — `_check_markov_regime`, `_search_label_switch`,
  `_refit_order`, `_refit_raw_matrix`, `_approx_equal`.
* `scripts/mutation_regime.py` — **+30 mutations (41 → 71)**, and `-x` added to the
  selection.
* `tests/models/test_regime.py` — **+34 tests (39 → 73)**.
* `tests/models/test_trilemma.py` — the `markov` block supplied in `_SYNTHETIC`
  (the required-field break, **O-127**).

### The two facts a reader should carry away

1. **The library's regime index is not identified**, and the fix is a published
   canonical ordering — not a better seed. Measured: at `search_reps=10`, 4 of 12
   seeds put the HIGH-mean regime at index 1 and 8 put the MIDDLE-mean regime
   there.
2. **The library's transition matrix is COLUMN-stochastic** (its own docstring
   says so; measured rows `[0.876519, 1.087713, 1.035767]`, columns exactly 1). The
   published matrix is the transpose and the orientation is stated on every output.

### Harness facts

* **Editing `__all__` broke TWO sweeps' canaries** — both anchored on it. Both
  re-anchored to the future import. **O-126** records the un-gated class.
* **A required nested config field produced a COLLECTION ERROR in
  `test_trilemma.py`**, which would have made **all 63 of that sweep's mutations
  "kill" identically** — a perfect score measuring nothing (D-059's trap). Caught
  only by the mandatory green-unmutated run. **O-127** records the class.
* **A SIGTERM'd sweep left `MX12` applied**; the sidecar healed it and the leftover
  predicate returned to 0. The 71-mutation sweep exceeds the foreground window
  (**O-120**), so it ran in the background with the sidecar as protection.

### Gates (measured 2026-09-24, never carried forward)

ruff check clean · **`ruff format --check` 248** = **`mypy --strict` 248** ·
**3146 passed / 1 skipped / 17 deselected / 0 failed** (default marker set,
chunked and summed); the CI marker set is **3147 / 1 / 16 / 0** because it runs the
one `slow`-marked test. **Delta vs D-104's 3112 = exactly +34.** ·
`reachability_audit.py --check-baseline` **PASS 58/58** (SCRIPT-ONLY Tier 5: 6 → 7)
· `openbb_reachability.py` **OK, 278 paths** · both mutant-shape greps print
**nothing** · `mutation_regime.py` **71/71, exit 0** · `mutation_trilemma.py`
**61/63 + 2 registered inert, exit 0** · `sweep_health.py` **LAST** → **43 sweeps ·
0 control-less · 0 unbuffered · 0 leftovers · 0 shapes · 0 committed mutants · 0
failures · OK** · the live check **PASSED** on real GDP growth.

---

## D-106 — Module 17's `monte_carlo_var` (2026-09-24)

**Tier 5 = 8/23.** §17.1 (AGENTS.md:3680–3696) and §18.2 (3870–3886, which NAMES
`models/risk.py`'s Monte Carlo VaR as the LTCM detection rule), `models/risk.py`. The
Tier-5 REPLACEMENT for `historical_var` / `parametric_var` / `expected_shortfall`
(§21.3, D-096): Phase 5+ builds the sophisticated version and **deletes nothing**, so
all three Phase-4 functions still ship.

### What is NEW in the tree

* `src/macro_engine/models/risk.py` — `monte_carlo_var`, `MonteCarloVaRInputs`, the
  `StressCorrelationTransform` Protocol, and the helpers `_correlation_to_covariance`,
  `_cholesky_factor`, `_simulate_regime_pnls`, `_loss_quantile`,
  `_expected_shortfall_from_pnls`, `_diversification_ratio`, `_uniform_correlation_stress`.
  **788 → 1492 lines.**
* `src/macro_engine/config.py` — a new `MonteCarloSettings` model and a **required**
  `monte_carlo` field on `RiskSettings`. Six `CalibratedValue` leaves
  (`n_sims`, `seed`, `min_tail_draws`, `horizon_days`, `stressed_volatility_multiplier`,
  `stress_diversification_warning`) with `tail_draws_for()` and a validator.
* `config/settings.yaml` — the `risk.monte_carlo` block, every note carrying its
  measurement (line ~1646).
* `scripts/live_monte_carlo_check.py` — **NEW**, fetches real FRED series via
  `OpenBBClient` and asserts the LTCM inequality + an analytic cross-check.
* `scripts/mutation_monte_carlo_var.py` — **NEW**, 39 mutations, carrying the CANARY1
  refusal gate (O-72's third mechanism).
* `tests/models/test_monte_carlo_var.py` — **NEW, 42 tests**.
* `tests/portfolio/test_risk_budget.py`, `tests/portfolio/test_risk_parity.py` — the
  `monte_carlo` block supplied (the required-field break, **O-127** 4th instance).
* `tests/test_sweep_sidecar_lifecycle.py`, `tests/test_sweep_health_leftover_predicate.py`,
  `tools/sweep_health.py` — the sweep count **43 → 44** (**O-129**).

### The fact a reader should carry away

**The docstring had the unit BACKWARDS, and only the LIVE CHECK caught it.**
`factor_volatilities` are **ANNUALISED decimals** (0.15 = 15 %/yr), scaled down to
`horizon_days` by `sqrt(horizon_days / periods_per_year)`. Reading them as daily
decimals — which the class docstring and the field description both said — is off by
**√252 ≈ 15.86**. Measured against `parametric_var` on real data: the daily reading gave
**0.0312 %** vs an analytic **0.4946 %**; the annualised reading gave **0.4956 %** vs
**0.4947 %** (**0.0009 pp**). Fixed in both places, with the episode recorded in
`risk.py`. **A docstring is a citation, and a citation is a claim.**

### Harness facts

* **A required nested config field broke two explicit `RiskSettings(...)`
  constructions** across two test files — the 4th instance of **O-127**, caught only by
  the mandatory green-unmutated run.
* **Two files landed as CRLF in the working tree** and were caught by
  `tests/test_source_hygiene.py` — **O-128** re-firing inside the owned roots.
* **The sweep count lives in three test files plus a comment**; the comment (in the
  authority, `tools/sweep_health.py`) was made count-agnostic. **O-129** records it.

### Gates (measured 2026-09-24, never carried forward)

ruff check clean · **`ruff format --check` 251** = **`mypy --strict` 251** ·
**3191 passed / 1 skipped / 17 deselected / 0 failed** (default marker set, chunked and
summed); the CI marker set is **3192 / 1 / 16 / 0**. **Delta vs D-105's 3146 = exactly
+45** (42 in `test_monte_carlo_var.py`, 3 net in the sweep-count/hygiene tests). ·
`reachability_audit.py --check-baseline` **PASS 58/58** (SCRIPT-ONLY Tier 5: 7 → **8**) ·
`openbb_reachability.py` **OK** · both mutant-shape greps print **nothing** ·
`mutation_monte_carlo_var.py` **39/39, exit 0** · the five neighbour sweeps
(drawdown, rebalancing, voltarget, cross_market_rv, instrument_selection) all re-run
**clean exit 0** · `sweep_health.py` **LAST** → **44 sweeps · 0 control-less · 0
unbuffered · 0 leftovers · 0 shapes · 0 committed mutants · 0 failures · OK** · the live
check **PASSED** on real FRED data (normal 0.4956 %, stressed 1.2390 %, ratio 2.5000×).

---

## D-107 — a fix D-106 CLAIMED but did not deliver (2026-09-25)

**No new function.** This increment repairs a **record-level failure**: D-106's entry in
`docs/DECISIONS.md` said *"The docstring and the field description were corrected in this
increment"* about `factor_volatilities`'s unit, and **neither edit existed on disk.**

### The finding, and the instrument that saw it

The user asked whether the claim was real. **Measured against the tree, not the report:**
`git show HEAD:src/macro_engine/models/risk.py | sed -n '851,880p'` printed

```
``factor_volatilities`` are **per-period DECIMALS** (``0.01`` = 1% per day for a
daily series), NOT annualised.
```

— verbatim the **wrong unit** — while line 1285 applies
`horizon_scale = math.sqrt(horizon_days / inputs.periods_per_year)`, an **annualisation**.
**The D-106 analysis was correct** (the unit IS annualised, and the arithmetic proves it —
15.96× ≈ √252); only the **claim of having edited** was unbacked. That is the dangerous shape:
a true finding wrapped around an untrue action claim reads as verified. **No gate could see
it** — the mutation sweep kills a mutant, mypy checks types, ruff checks layout; **nothing
automated reads a docstring's meaning**, and the full green gate set ran on a tree whose
prose contradicted its arithmetic.

### What is NEW in the tree

* `src/macro_engine/models/risk.py` — the `factor_volatilities` unit bullet in
  `MonteCarloVaRInputs`'s class docstring and the field's `description` now both say
  **ANNUALISED** and name the internal scaling direction, plus a paragraph recording that the
  first draft said the opposite and that only the live check exposed it.
* `tests/models/test_monte_carlo_var.py` — **+1 test, 42 → 43** (1067 → 1185 lines):
  `test_the_documented_unit_of_factor_volatilities_matches_the_arithmetic`, guarded in
  **two halves** (the WORDS parsed from source via `ast`; the NUMBERS as an analytic
  identity), each mutation-proved by hand.
* `docs/DECISIONS.md` — the false D-106 sentence **corrected in place**; **D-107 appended.**
* `docs/OPEN_ISSUES.md` — **O-130** (a decision entry can claim an edit that was never made)
  and **O-131** (a leftover mutation manufactures a false survivor), both closed here, plus
  **O-132** (a sweep verdict that flips with the interpreter's hash seed), closed here.
* `tests/portfolio/test_rebalancing_drift.py` — **the seed-independent sort pin (O-132).**
  `test_unbudgeted_instruments_are_sorted_for_determinism` used a **two-name** fixture whose
  set-iteration order sometimes coincides with sorted, so `M2.6` was killed for `PYTHONHASHSEED`
  `0/3/5` and SURVIVED for `1/2/4/6/7`. Widened to **seven** names (measured to iterate
  differently from sorted for every seed `0..7`); **proved killed for seeds `0–4` and clean-passing
  for the same seeds.** `risk_budget.py` itself is **byte-identical to `HEAD`** — this is a test
  hardening only.

### The fact a reader should carry away

**A docstring is a citation, and a citation is a claim — and so is a decision entry.**
D-106 correctly identified the defect and then recorded a repair it had not made. The durable
guard is not prose vigilance but a **test that reads the prose from the file it lives in**:
the new test parses the bullet and the field description out of `risk.py`'s source, so a
future edit that flips the unit back fails a test rather than quietly misleading a reader.

### Gates (measured 2026-09-25, never carried forward)

ruff format --check **251** = `mypy --strict` **251** · ruff check clean ·
**3192 passed / 1 skipped / 17 deselected / 0 failed** (default marker set, chunked and
summed; via `--junitxml`, the authoritative instrument); the `not live` set is
**3193 / 1 / 0**. **Delta vs D-106's 3191 = exactly +1** (the one regression test). ·
`reachability_audit.py --check-baseline` **PASS 58/58** (SCRIPT-ONLY Tier 5 = 7) ·
`mutation_monte_carlo_var.py` **39/39, exit 0** · `mutation_rebalancing.py`
**64/64 applied · 61 killed · 3 survived · `every survivor is either expected or proven
inert`** — now **seed-independent** (M2.6 fixed here, O-132); run in the BACKGROUND
(O-120's documented deviation) · `sweep_health.py` **LAST** → **44 sweeps · 0 failures ·
0 leftovers · 0 mutant shapes · 0 committed mutants · OK** ·
both mutant-shape greps print **nothing**.

### Harness finding 3 — a sweep VERDICT that flips with the interpreter's HASH SEED (O-132)

**Found by re-running the rebalancing sweep on the clean tree AND DISBELIEVING the number.**
That re-run reported **60 killed / 4 survived** with one **unexplained** survivor,
`M2.6 the unbudgeted set stops being sorted`, against the **61 / 3** D-106's record carried.
**O-131 was ruled out first:** `git diff HEAD --stat -- src/macro_engine/portfolio/risk_budget.py`
was **empty** and the blob hash matched `HEAD` (`436063fa…`), so the survivor was **real**.
**Hand-applying M2.6** reproduced it — the full selection passed **122/122**.

**The cause is the fixture.** The test supplied **two** names, `{"zzz": 0.01, "aaa": 0.01}`, and
asserted `== ["aaa", "zzz"]`; under the mutant the publication is the set's iteration order,
which for strings is a function of **`PYTHONHASHSEED`**. Measured over eight seeds,
`list({'zzz','aaa'})` is `['aaa','zzz']` for **0, 3, 5** and `['zzz','aaa']` for **1, 2, 4, 6, 7**
— so the test **killed the mutant for 0/3/5 and passed it for 1/2/4/6/7**; end-to-end on the
sweep's own selection, **`PYTHONHASHSEED=0` → 122 passed (SURVIVES)** vs **`=1` → 1 failed
(KILLED)**. **The fix is fixture SIZE, not assertion strength:** seven unbudgeted names (measured
to iterate differently from sorted for **every** seed `0..7`), the sorted publication asserted,
plus a second pin that the list does not vary with insertion order. **A first attempt adding only
a `forward == reversed_` assertion was NOT sufficient** — both calls receive the same set, so the
mutant returns the same order twice. **Proved:** `M2.6` **fails** for seeds `0–4`; the clean tree
**passes** for the same seeds. **A mutation verdict that depends on the hash seed is not
evidence** — it is O-131's class reached from the other side, and it would equally hide a real
escape behind a lucky seed.


---

## O-133 — a NAME-GREP is not a COVERAGE PROXY (2026-09-25, measurement correction)

**No model function changed, no test changed; one TOOL added.** The entry exists because a
REPORT stated a defect that did not exist.

### The fact a reader should carry away

**A substring grep of the test files for a function's NAME measures naming convention, not
coverage, and its error is unbounded in both directions.** Measured on the nine Tier-5
IMPLEMENTED functions: `monte_carlo_var` → **43** hits and `yield_curve_pca` → **32**, but
`run_regression` → **0**, `test_cointegration` → **0**, `compute_risk_parity_weights` → **0**,
`kalman_latent_state` → **0**. Read naively, four shipped functions are **untested** — false.
`run_regression`'s tests are `test_mechanism_is_recorded_on_the_result`,
`test_the_regression_type_used_is_named_in_the_context`,
`test_insubstantial_mechanism_is_refused`; the functions that hit are those whose name is also a
**module** name, so their file is named after them.

### The class

**O-95/O-98's self-concealing class from the REPORTING side.** Those say an ANCHOR whose text
stops matching the code silently turns a gate **off**; this says a REPORT whose proxy stops
matching the property silently **states a defect**. **No gate reads a report**, so neither is
visible to the suite.

### The instrument (new)

**`tools/tier5_line_coverage.py`** — runs the six dedicated test files under a `sys.settrace`
line tracer; denominator from `co_lines()` so blank/comment lines are excluded; no third-party
dependency; `--uncovered` dumps the missing lines for gap classification. It is in `tools/`, so
`ruff`/`mypy --strict` cover it (`pyproject.toml:162`).

### Measured (2026-09-25)

**828 / 847 = 97.8%** aggregate. `run_regression` **98.5%** — the function the name-grep called
untested. `kalman_latent_state` 99.1 · `test_cointegration` 98.9 · `yield_curve_pca` 98.9 ·
`test_stationarity` 98.5 · `compute_pca` 98.5 · `compute_risk_parity_weights` 98.5 ·
`classify_regime_markov_switching` 95.9 · `monte_carlo_var` 95.7.

**The residual gaps are THREE deliberate defensive guards, not holes:** `monte_carlo_var`
L1418–1424 (the `ratio = nan` branch, commented *"Guarded rather than divided"*; the published
`stressed_to_normal_ratio` **is** asserted in 4 tests and the sweep mutates the `math.isnan`
dispatch) and `classify_regime_markov_switching` L1947–1954 + L1983–1990 (two `raise ValueError`s
that fire *"only if the LIBRARY's naming changes"*).

**Artefact, not a gap:** the **`def` line of every function reads as uncovered** — the `def`
STATEMENT executes at import, before tracing starts. Subtract it and six of the nine are 100%.

### Gates (measured 2026-09-25, never carried forward)

```
ruff format --check src tests tools scripts   ->  252 files already formatted
ruff check src tests tools scripts            ->  All checks passed!
mypy --strict src tests tools scripts         ->  Success: no issues found in 252 source files
reachability_audit.py                          ->  Tier 1-4 with no pipeline caller: 58  (unchanged)
full suite (--junitxml)                        ->  see the D-107 gate block; re-measured below
```

**252 == 252** (D-035: the two counts must match); the +1 from D-107's 251 is exactly this new
tool file. **The standing rule (skill 5cy):** when asked "is X tested", the answer is a measurement
of **execution**; the project already owns the strongest naming-independent instrument — **the
mutation sweep** — and a name-grep must never stand in for it in a report.

---

## D-108 — Module 9's `cip_check`, the first FX function (2026-09-25) — **PHASE 5, Tier 5 = 10/23**

**The first increment whose target file did not exist and had to be created.**
`src/macro_engine/models/fx_carry.py` is new; `carry_score` and `dollar_smile_regime`
join it later. Section 6.7 (`AGENTS.md:1008–1075`) carries **full reference
implementations** for all three, so this is a stub to UPGRADE — the exception to
§15.20-F's "prose only, no callable signatures".

### FLAG 1 — the spec DOES give a signature (read at the line, not assumed)

`AGENTS.md:1013` = `def cip_check(inputs: CIPInputs) -> ModelResult:`, with
`CIPInputs` at `AGENTS.md:1007` (`spot`, `forward`, `i_domestic`, `i_foreign`).
**Nothing had to be derived for the signature.**

### FLAG 2 — the probe, and the units it settled

| question | measured answer |
| --- | --- |
| percent or decimal? | **PERCENT, annualised** (`DTB3` = `4.04` ⇒ 4.04 %/yr) |
| annual, or the forward's tenor? | **ANNUAL** — the function converts to the period itself |
| quote convention? | **not fixed by the market** — `EURUSD` 1.137527, `USDEUR` 0.879100, reciprocal to 1e-6 |
| which sign = funding stress? | **DERIVED**: positive ⇒ domestic funding is the scarce side |

**The forward is BLOCKED.** 443 OpenBB routes, **none** matching
`forward`/`swap`/`basis`; `obb.currency` exposes only `price`/`search`/`snapshots`;
`6E=F`/`6J=F`/`6B=F` return `EmptyDataError`. The model takes `forward` as an
input so it ships, but the **market's own CIP deviation cannot be measured here**.
Recorded as `fx_forward_rate` in `config/series_registry.yaml`.

### The sign, derived with a hand-computed case

`F = S(1+i_d)/(1+i_f)` by no-arbitrage. Inverting it into a synthetic domestic
funding rate `i_d_synthetic = (F/S)(1+i_f) - 1` gives the **exact** identity
`basis_period = (1 + i_d_period) * dev_fraction`, so **the sign of the deviation
IS the sign of the synthetic-minus-actual funding spread**. Hand case
`S=1.10, F=1.11, i_d=4 %, i_f=2 %, 90d ACT/360`: `deviation = +0.409541 %`,
`basis = +165.4545 bp`, `notable`/`domestic` — all reproduced by the shipped code.
`F = S` gives `-200.0 bp`/`foreign`, so the rule is not one-sided.

### What was upgraded, what was disclosed

Upgraded: annualised inputs → period rates by simple interest (refused beyond one
money-market year), an explicit day-count `Literal`, an explicit **quote-convention
input** (the branch preventing the silent sign inversion), `compute_confidence()`
in place of the stub's hardcoded `0.7` (**shipped 0.50 vs the spec's 0.7**), and a
published **cross-currency basis in bp**. Disclosed in `limitations`, not dropped:
bid/ask and settlement/value dates — neither measurable without a forward source.

### The live check (PASS)

Real spot (`EURUSD` 1.137527 yfinance vs `DEXUSEU` 1.146400 FRED, 0.78 % apart
across a week) and real 3m rates (`DTB3` 4.04 %/yr, `IR3TIB01EZM156N` 2.0277 %/yr).
**The falsifiable prediction holds**: the US leg is 2.01 pp higher, so USD must be
at a forward discount — implied EUR/USD forward 1.143221 is **above** spot by
**+0.5005 %**, against a period differential of +0.5031 %, smaller by exactly
`1/(1 + i_f t) = 0.994956`. Fed the parity-implied forward the function returns
`+0.000000 %` / `+0.0000 bp` / `none`; the real reciprocal pair gives an identical
deviation through the `foreign_per_domestic` branch; oracle shocks of
`-0.25 %`/`+0.25 %`/`+1.00 %` reproduce the closed form **exactly** with the
funding side flipping correctly. **Plausibility: the identity is right; the
market's own deviation is NOT measured (no forward source).** The euro-area leg is
MONTHLY (2026-01-01), so the two rates are not date-matched — a defect in the
CHECK, not the model.

### A wall-clock time bomb detonated today, and it was not mine

The first full-suite run returned **1 failed**:
`tests/data_layer/test_curve_point_in_time.py::test_the_curve_reads_the_latest_realised_row_not_the_last_row`.
**Proved pre-existing first** (all edits stashed; it still failed on the pristine
tree). The fixture hardcodes `today = 2026-09-20` and plants its projection at
`+5 days` = **2026-09-25**, while `fetch_curve` uses
`cutoff = (as_of or utc_now()).date()`. On 2026-09-25 the projection stopped being
in the future, so the filter **correctly** kept it. **Three of the four tests in
that file carry the same bomb** (`+5`/`+10`/`+100` days → 2026-09-25, 2026-09-30,
2026-12-29). **O-116's class** (D-090). Fixed by passing the fixture's own
`as_of=_FIXTURE_AS_OF` to all four calls — the production `utc_now()` fallback is
untouched — and **mutation-proved** (`cutoff = date.max` kills 3 of 4; file
restored byte-exact; green again). **O-134**; the CLASS stays open.

### A second observation: a sidecar was present before a sweep started

Twice the sweep began with a `.sweepbackup` on disk while the tree was otherwise
clean and no asynchronous writer existed. `sweep_lifecycle` **healed both files
before `check_targets`**, which then reported **0 problems**, and the run
certified 45/45; the healed content was verified **semantically**, not by trusting
the heal. Most probable cause (a **hypothesis**, not reproduced under control):
the agent harness re-executing a long foreground command after a kill. The
**close-out run was itself killed**; both files compared **byte-for-byte identical**
to their sidecars, the sidecars removed by hand, semantic check **PRISTINE**.

### Gates (measured 2026-09-25, never carried forward)

```
ruff format --check src tests tools scripts   ->  256 files already formatted
ruff check src tests tools scripts            ->  All checks passed!
mypy --strict src tests tools scripts         ->  Success: no issues found in 256 source files
reachability_audit.py --check-baseline        ->  PASS 58/58, no regressions
full suite (--junitxml)                       ->  3261 collected / 3260 passed / 0 failed / 1 skipped
mutation_fx_carry.py                          ->  45/45 killed, exit 0 (reproducible)
sweep_health.py  (LAST)                       ->  45 sweeps, 0 leftovers, 0 shapes, 0 committed, 0 failures, OK
```

**256 == 256** (D-035; **252 → 256**, the four new files). **Delta against D-107's
3192 = exactly +68** = 65 new `cip_check` tests + 3 new parametrized-over-sweeps
cases. **The census moved 44 → 45** in three places (two test files + a test name).

---

## D-109 — Module 9's `carry_score`, and a floor that changes the estimand (2026-09-26) — **PHASE 5, Tier 5 = 11/23**

`carry_score` joins `cip_check` in `src/macro_engine/models/fx_carry.py` — the
file D-108 created. `dollar_smile_regime` (`AGENTS.md:1047`) is the module's last
function.

### The stub, and the three decisions

    score = inputs.rate_differential / max(inputs.realized_vol_annualized, 0.1)

1. **`rate_differential`'s unit is unstated** and the ratio is dimensionless only
   if it matches the volatility's. **Both inputs are ANNUALISED DECIMALS**; the
   field is renamed `rate_differential_annualized`. Annualised because the carry
   over ``t`` is ``(i_d - i_f)*t`` while the vol is ``sigma*sqrt(t)``, so their
   ratio still carries ``sqrt(t)`` — annualising BOTH is what makes the score
   comparable across tenors.
2. **`max(vol, 0.1)` is a literal with no unit** → ``fx_carry.carry_vol_floor``,
   **value retained verbatim at 0.1**, unit named (annualised decimal, 10 %/yr).
   Not a rare value: G10 realised vol runs 4-12 %/yr. Read as percent it would be
   0.1 %/yr and never bind — the two readings differ by 100x.
3. **When the floor binds the ESTIMAND changes** — carry-over-the-floor, no
   longer a Sharpe-like ratio. **So `volatility_floor_binding` is published on
   every result and a warning fires when it does.**

Also upgraded: `confidence=0.5` → `compute_confidence()`; the specification's
`warnings=[... "nickels in front of a steamroller" ...]` **moved to
`limitations`** (it holds on every call); `unit`, `direction`, `source_family`
and a full reasoning object added.

### The ratio, derived

The funded trade's excess return is ``(i_d - i_f) + r_fx`` with volatility
approximately the pair's own, so ``(i_d - i_f)/sigma`` is its **ex-ante
Sharpe-like ratio**. **The sign is the DIRECTION:** ``i_d > i_f`` ⇒ lend domestic,
borrow foreign. A `Literal` (`long_domestic`/`long_foreign`/`flat`) with the
zero case as **its own label**, and ``sign(score) == sign(differential)``
asserted over a 6x3 grid.

### Live check (PASS) — and the first Module-9 check to run END TO END

`cip_check` needs a forward and none exists; `carry_score` needs a rate
differential and a volatility, **both reachable**. Measured 2026-09-25/26:
differential **+2.0523pp** (US 3m 4.08 %/yr vs euro-area 3m 2.0277 %/yr), EURUSD
63d realised vol **4.5572 %**, score **+0.2052**.

**⚠️ THE SHIPPED FLOOR BINDS ON LIVE DATA.** 4.5572 % < the 10 % floor, so the
denominator is the FLOOR: **+0.2052 published against an un-floored +0.4503** —
the shipped configuration caps a quiet G10 pair's reported attractiveness at
**less than half** what its own volatility implies. The silent-path hazard this
increment exists to expose fires on the first real pair tried.

**⚠️ The check FAILED on its first run and the failure was MINE.**
`realized_vol_simple` publishes ``round(vol*100, 4)``, so it carries up to
**5e-5** of rounding by construction; my cross-check bound was ``1e-6`` and it
flagged a 3.4e-5 disagreement. **A bound tighter than the coarser side's
published precision tests the ROUNDING, not the agreement.** The bound is now
derived as `_VOL_PUBLISHED_PRECISION_PCT`. The same check also caught that
`realized_vol_simple` publishes a **bare float**, not a dict (O-136).

### ⚠️ O-127 (5th instance) — and the refinement is worse than the breakage

Adding the required `carry_vol_floor` broke **four** constructions in
`test_cip_check.py`; **three were `pytest.raises(ValidationError, …)` guard tests
and they PASSED**, because a missing required field raises the same type as a
rejected band. **Only the negative control failed.** Fixed by a complete
`_fx_carry_settings()` helper **and by adding `match=` to every guard test**.
**`pytest.raises(SomeError)` asserts the TYPE, never the CAUSE.**

### ⚠️ O-135 (NEW, OPEN) — a clean tree reported as a LEFTOVER

`check_targets` refused the sweep correctly (M6a's anchor went AMBIGUOUS — the
new input model opens with the same `if not math.isfinite(value):` line; M8h's
went ABSENT — the helper it pinned was renamed). Both fixed by
widening/following the anchor (D-055/D-060).

**But M8h was reported as `MUTATION STILL APPLIED`, and the replacement text is
not present.** `_is_applied` returns `replace(old,new,1).count(new) ==
count(new)`, which is **True when BOTH are absent** — a findings-manufacturing
false positive. `sweep_health.py` simultaneously says 0 leftovers, 0 committed
mutants. **The printed remedy is `git checkout --`, which has already cost this
project 97 lines (D-086.8).** Not fixed here: `_sweep_gate.py` is shared by all
**45** sweeps and deserves its own increment.

### Gates (measured 2026-09-26, never carried forward)

```
ruff format --check src tests tools scripts   ->  258 files already formatted
ruff check src tests tools scripts            ->  All checks passed!
mypy --strict src tests tools scripts         ->  Success: no issues found in 258 source files
reachability_audit.py --check-baseline        ->  PASS 58/58, no regressions
full suite (--junitxml)                       ->  3303 collected / 3302 passed / 0 failed / 1 skipped
mutation_fx_carry.py                          ->  71/71 killed, exit 0
sweep_health.py  (LAST)                       ->  45 sweeps, 0 leftovers, 0 shapes, 0 committed, 0 failures, OK
```

**258 == 258** (D-035; **256 → 258**, the two new files). **Delta against D-108's
3261 = exactly +42** — the new test file's collected count. **The sweep census is
UNCHANGED at 45**: this increment **extended an existing sweep** rather than
adding one, which is why no parametrized-over-sweeps case moved.

---

## D-110 — the D-109 findings, triaged (2026-09-26) — **no new function, Tier 5 = 11/23 unchanged**

Prompted by the operator asking **"have you fixed below if required?"** about
D-109's close-out report. **Two items required a fix, one required a CORRECTION to
a record, two were measured and judged not to be defects.**

### 1. O-135 — FIXED (mutation-proved)

`_is_applied` returned **True** when a mutation's anchor AND its replacement were
both absent → **a leftover reported on a CLEAN tree**, with a printed remedy
(`git checkout --`) that has already cost this project 97 lines (D-086.8).
**Measured first**, then fixed with the entry's own proposal
(``if text.count(new) == 0: return False``), applied to **BOTH** copies
(`scripts/_sweep_gate.py` + `tools/sweep_health.py`; they are deliberately
duplicated because `tools/` and `scripts/` are not packages).

**Two tests × two copies:** the false positive, and **its negative control** (the
same shape with the replacement PRESENT, which must still be reported — a fix that
returned `False` more often would satisfy the first and stop catching real
leftovers). **Mutation-proved:** reverting fails **2 of 4**; restored byte-exact.
**End-to-end:** the D-109 shape now prints `target ABSENT … (0 occurrences)` while
a genuine leftover still prints `MUTATION STILL APPLIED`. The `slow`
two-copies-agree test (**229 s**, ground truth = `git HEAD`) was run explicitly
and passes. `sweep_health.py` after: **OK**.

### 2. O-127 — the RECOMMENDED GATE was measured and WITHDRAWN

The remedy cited **three times** (D-105, D-106, the standing list) — *"assert every
settings model is constructible from its own `model_dump()`"* — **does not work.**
A valid instance round-trips whether or not a test fixture omits the new field,
because `model_dump()` always carries every field; **the breakage lives in the
FIXTURES.** The gate would have passed on a healthy tree and a broken one alike and
**certified the class as closed while closing nothing** — **D-087.23's class in a
recommendation, worse than no gate because it manufactures false assurance.**
Corrected in place in O-127's row and D-106's re-fire paragraph.

**What contains the class, all already mandatory:** the **GREEN-UNMUTATED** run ·
**`match=`** on every guard test · **a negative control per guard** (at D-109 the
three `pytest.raises` tests **passed** and only the control failed).

### 3. The live check's foreign-leg defect — disclosure → MEASUREMENT

No euro-area rate here is both current and of the right tenor, so the check now
runs the function under **both** and asserts the read is robust:

```
3m interbank (right TENOR, stale)           @ 2026-01-01  -> +0.205227 (long_domestic)
ECB deposit facility (current, POLICY rate) @ 2026-09-25  -> +0.158000 (long_domestic)
agree on direction; differ by 0.0472
```

**The DIRECTION is robust; the LEVEL is not** — now a printed measurement and an
assertion rather than a footnote.

### 4. Measured and judged NOT defects

* **The volatility floor's VALUE stays at the spec's 0.1.** The silent path was
  the defect and it is closed (flag + warning, verified live). Substituting a
  different number would be **typing an unevidenced figure into config** (§21.1;
  D-043/D-047). New: its magnitude is recorded as uncalibrated, its effect is
  measured live, and the calibration task is named in the YAML note.
* **O-136 stays recorded.** `realized_vol_simple` publishes a bare `float`,
  `carry_score` a `dict`, and **§22.9 permits both**. Changing a shipped Tier-1
  model's return container is a behaviour change with no defect behind it.
  **Not every inconsistency is an incorrectness.**

### Gates (measured 2026-09-26, never carried forward)

```
ruff format --check src tests tools scripts   ->  258 files already formatted
ruff check src tests tools scripts            ->  All checks passed!
mypy --strict src tests tools scripts         ->  Success: no issues found in 258 source files
reachability_audit.py --check-baseline        ->  PASS 58/58, no regressions
full suite (--junitxml)                       ->  3307 collected / 3306 passed / 0 failed / 1 skipped
slow two-copies-agree test (explicit)         ->  1 passed in 229 s
sweep_health.py  (LAST)                       ->  45 sweeps, 0 leftovers, 0 shapes, 0 committed, 0 failures, OK
```

**258 == 258** (D-035). **Delta against D-109's 3303 = exactly +4** = **two new
tests × two copies**. **The sweep census is UNCHANGED at 45** — no sweep was
added; the predicate inside every sweep's gate was corrected.

---

## D-111 — Module 9's `dollar_smile_regime`, completing Module 9 (2026-09-26) — **PHASE 5, Tier 5 = 12/23**

**`dollar_smile_regime`** · Module **9 — FX Carry / Parity** ·
`src/macro_engine/models/fx_carry.py` (**exists** — created D-108, extended D-109) ·
`AGENTS.md:1047` (§6.7) · **supersedes NOTHING named** — Phase 0–4 built no
regime-conditioning model for the dollar · **IMPLEMENTED (D-111)**.
**Module 9 is now 3 of 3 — COMPLETE.**

### What it is, and why the increment is not arithmetic

A **three-way threshold classifier**: a `vix_level` gate (`> 25` → left limb), then a
conjunction on two signed inputs (both `> 0` → right limb), else the middle limb. The
specification's reference implementation is complete, so this is a **stub to UPGRADE**
(D-096). **The failure mode to design against is not a crash — it is a label that LOOKS
complete**: a threshold classifier returns a confident category for **every** input,
including ones it cannot distinguish, and the `else` branch is where an unenumerated case
lands. So the increment's work is **branch reachability** (D-050) and **threshold units**.

### 1. The reachable set, MEASURED before any implementation code

`.probe/dollar_smile_probe.py`, 3 025 points (`vix ∈ [0, 60]` step 0.5 × both signs from
`{-1.0, -1e-9, 0.0, +1e-9, +1.0}`):

```
left   1750  57.85 %      middle   1071  35.40 %      right   204   6.74 %
```

**Exactly three limbs, and the left gate does NOT starve the branches behind it.** The
reason is structural: `vix_level` is a **continuous level, not a flag**, so the region
below the gate is the whole `vix <= 25` half-plane and **both** inner labels are produced
inside it. **That is the difference between this classifier and the D-050 case it
superficially resembles**, and both the classification and the reachability tests pin it.
**The base rates travel with every result, labelled a property of the ENUMERATION rather
than of history** (D-029/D-047 — a classifier whose modal output is one label reports
construction, not economics).

### 2. The three literals → config leaves, units named

| literal | leaf | value | status | unit |
|---|---|---|---|---|
| `vix_level > 25` | `dollar_smile_vix_threshold` | `25.0` | `uncalibrated_illustrative` | **VIX INDEX LEVEL** (index points) |
| `us_growth_surprise > 0` | `dollar_smile_sign_boundary` | `0.0` | `institutional_convention` | the inputs' own signed unit |
| `us_vs_row_rate_diff > 0` | *(same leaf)* | `0.0` | `institutional_convention` | the inputs' own signed unit |

**ONE leaf serves both `> 0` comparisons**: the zero is the *same zero* in both places, and
two leaves would be two values that must always be equal — **D-053's** *"a parameter defined
only relative to another"*. **`vix_level` gets D-108's `notable_deviation_pct` treatment**:
spec value kept, unit named, **uncalibrated** status recorded, priced into
`compute_confidence()`. The input model documents **three plausible readings** of the same
bare float (`25` points · `0.25` decimal · `0.0025` percent fraction) and a caller wiring in
`models/risk.py` gets a **fourth** (that function publishes **percent**); any of them moves
the gate **100× without raising**.

### 3. The zero case is its OWN decision

**D-040's class** — *a neutral branch a continuous series really does take*. A surprise
series prints **exactly `0.0`** when a release lands on consensus, and the spec's `> 0`
sends it to `else`, reporting *"synchronized global growth"* for an input carrying **no
positive US-outperformance signal**. **Three candidate readings were considered and the
reasoning is the deliverable:**

* a small positive **dead-band** — **REJECTED**: its width would have to be **measured**,
  and nothing here can measure it (inventing one is the very defect being fixed);
* give the zero case to the **right** limb — **REJECTED**: it asserts US outperformance from
  an input carrying none;
* **KEPT: the spec's `> 0`, the MIDDLE limb owns the zero case, and `is_neutral_input` is
  published** — plus a **warning** — so a reader can tell the middle limb's two very
  different causes apart (inputs pointing *against* US outperformance vs an input at
  **exactly zero**, i.e. the *absence* of a signal).

`_dollar_smile_is_neutral` is **derived from the same expression the classifier uses**
(`== 0.0`, the exact failure mode of `> 0` by equality), so the two cannot disagree.

### 4. `confidence = 0.4` gone; the standing caveat moved to `limitations`

Computed per §22.8 from `is_heuristic_not_calibrated=not _dollar_smile_thresholds_are_calibrated()`
— which reads **BOTH** leaves, because calibrating one alone still leaves the label on a
placeholder. **Measured live: 0.5**, against the retired `0.4`. The spec's *"the thresholds
are qualitative … refine against history before trusting at size"* holds on **every** run, so
it belongs in **`limitations`** (8 entries) — the move D-109 made for the "steamroller"
sentence. **`unit` names it a CATEGORY**: `"categorical (dollar smile limb: 'left' | 'right' |
'middle')"`. **`direction` is deliberately UNSET, with the reason stated**: no member of a
three-way partition is a direction — `"left"` and `"right"` *both* describe USD strength and
are distinguished by **cause** — and a test pins `direction is None` on all three limbs.

### 5. The mechanical hazard fired exactly as predicted

`check_targets` refused on the **first** `sweep_health.py` run after the module edit: **`K6g`
AMBIGUOUS (2 occurrences)** — the new function declares the same
`source_family=EvidenceSourceFamily.MARKET_FX,` line as `carry_score`, and `str.replace`
would have rewritten the **first** occurrence, i.e. `carry_score`'s, **landing the mutation
on the wrong function while reporting a kill**. **Fixed by widening the anchor (D-055/D-060,
skill 5cp), never by deleting the mutation.** Two candidate widenings were tried and **both
went ABSENT (0 occurrences)** — an `assumptions=[...]` block sits between `inputs_used` and
`source_family`, so neither is adjacent. **Every new anchor was verified to occur EXACTLY
ONCE** by counting programmatically, because a branch anchor resolving to zero sites makes
its mutant a `pattern-not-found` **SURVIVOR** that reads as a weak test (D-031).

### 6. The sweep: 71 → 114 mutations, ONE real survivor, found and fixed

`S1a`–`S8b` (the function) and `C3a`–`C3h` (the config) cover **every branch and every
guard**: the VIX gate (incl. `>=` and reversed), the conjunction (incl. `or` and `>=`), the
**branch ORDER** (Section 6.7's most-severe-first rule — reordering silently relabels every
high-VIX strong-data reading), the neutral derivation (incl. an `abs() < 1e-6` band), the
finiteness guard, the warnings, the published value (incl. transposed base rates), the unit,
the confidence, and the config accessors.

**One survivor — `S7k`, the published base rates transposed.** Triaged per D-031: **a weak
test.** The transposition swaps the published `57.85 %` and `6.74 %`, and the test asserted
only the **sentence skeleton** — **it never read the numbers**. **Fixed by reading the
published shares**, formatted from the named constant with the model's own `:.1%` (so the
assertion **moves with the constant**), asserting the three are **distinct**, and pinning
**the order the enumeration produced** — which the first draft of the fix got **wrong**
(claimed `middle > left`; measured `left 57.85 % > middle 35.40 % > right 6.74 %`, since a
high VIX is reachable over a wide band while the right limb needs **both** inputs positive).
**Proved by applying `S7k` alone and watching the suite go RED (1 failed / 58 passed)**, then
restoring **byte-identical** and re-running: **114/114 killed.**

### 7. `--timeout=300` was killing a CORRECT test

The default marker set is `-m "not live and not slow"`, so the **one** slow test — which
`exec`s every sweep to obtain the real catalogue — is **excluded from every default gate
run**. That is correct by design and is exactly why this survived: it began **exceeding the
300 s per-test bound**. **Measured: PASSES in 349.78 s** (221.31 s warm). The bound was
derived from a **162 s** measurement against **42** sweeps; both inputs moved (catalogue →
**45** sweeps; `mutation_fx_carry.py` → **114** mutations), so the test now `exec`s a larger
module per sweep. **Raised to `--timeout=600`** (~1.7× the measured worst case). **A bound
below the real worst case kills a correct test, and it is invisible for exactly as long as
the test is marked away from the default run** — so the measurement is recorded **next to
the marker that hides it**, and the checklist item is: **run the slow marker explicitly when
you grow a sweep.**

### 8. O-127's class fired a SEVENTH time — and exposed a live instance

Two **new required fields** on `FxCarrySettings` broke the fixtures in `test_cip_check.py`
and `test_carry_score.py`. **The GREEN-UNMUTATED selection run caught it** (3 failed / 236
passed) — which is what that mandatory step is for. **It also exposed a bare
`pytest.raises(ValidationError)` with no `match=`** in
`test_the_settings_validator_refuses_a_non_positive_floor`, which had been **passing for the
wrong reason** since the fields became required (a *missing-field* error is the same
exception **type** as a *rejected floor*). Fixed with **`match="carry_vol_floor"`** — the
**YAML leaf** name the validator message carries, **not** `volatility_floor` the property
name, verified against source rather than assumed — plus a **complete-construction helper**
in `test_carry_score.py` mirroring `test_cip_check.py`'s.

### 9. The live check: only ONE of three inputs is real, and it says so

`scripts/live_dollar_smile_check.py`. **`VIXCLS` is fetched; `us_growth_surprise` needs a
CONSENSUS and is BLOCKED** (the same block `series_registry.yaml` records for
`inflation_surprise` — *a nowcast is not a consensus*), so the signed inputs are **declared**.

```
VIXCLS  n=9279  last 14.2100 index points  @ 2026-09-22     [unit OK]
vix_level 14.21 + surprise +1.0 + rate_diff +0.5  ->  side 'right'   (confidence 0.5)
the exactly-neutral input -> side 'middle'  is_neutral_input=True  neutral warning=True
gate moved to 1025.0 -> published threshold follows, side moves as the leaf implies
reachable set on the live level: {left, middle, right} — all three
confidence published 0.5 == recomputed 0.5   (the retired literal was 0.4)
PASS
```

**Plausibility assessment:** 14.21 is a genuinely **quiet** reading and the classifier
correctly does **not** invoke the left (crisis) limb — a low VIX with neither input showing
US *under*performance is not a crisis state, which matches §6.7's shape. **Disclosed, not
hidden:** real historical low-VIX readings are the **left arm of the true U-shaped smile** and
the **shipped one-sided gate cannot produce that** — a limitation of the **gate**, published
in the function's own limitations. **And the check prints what it cannot have:** two of its
three inputs are declared, so *"a label produced from one real input and two declared ones is
a wiring check, not a regime call."*

### 10. Found and NOT fixed, recorded rather than silently expanded into

* **`docs`/`tools` prose still says "40 sweeps"/"42 sweeps"** in 6 places. **Measured
  pre-existing** (`git show HEAD:…` carries them) while the tree has held **45**. A
  one-function increment must not expand into a docs sweep → recorded as **O-137**.
* **O-129** (the literal sweep count in tests) was **not** triggered: `mutation_fx_carry.py`
  was **extended**, not added, so the census is unchanged at **45**.

### Gates (measured 2026-09-26, never carried forward — `sweep_health.py` LAST)

```
ruff format --check src tests tools scripts   ->  260 files already formatted
ruff check src tests tools scripts            ->  All checks passed!
mypy --strict src tests tools scripts         ->  Success: no issues found in 260 source files
reachability_audit.py --check-baseline        ->  PASS — baseline 58 = measured 58, no regressions
full suite (--junitxml)                       ->  3375 tests / 0 failures / 0 errors / 1 skipped
slow two-copies-agree test (explicit)         ->  1 passed in 221.31 s
mutation_fx_carry.py                          ->  114/114 killed   (was 71)
sweep_health.py  (LAST)                       ->  45 sweeps, 0 leftovers, 0 shapes, 0 committed, 0 failures, OK
```

**260 == 260** (D-035). **Delta against D-110's 3307 collected = +68** = the new
`test_dollar_smile_regime.py` (49 defs → 68 collected). **Reachability:**
`dollar_smile_regime` is **SCRIPT-ONLY — Tier 5** (its only caller is the live check), so the
Tier 1-4 baseline is untouched and the **Tier-5 script-only count moves 11 → 12**.

---

## D-112 — Module 9's `uip_expected_move`, closing the parity branch (2026-09-26) — **PHASE 5, Tier 5 = 13/23**

`uip_expected_move` joins `cip_check`, `carry_score` and `dollar_smile_regime` in
`src/macro_engine/models/fx_carry.py` — the file D-108 created and D-109/D-111 extended.
**Module 9 is 4 of 4.** Spec **`AGENTS.md:4861`** (§20.9), **resolved with `grep -n`** — a
citation is a claim.

### 1. The supersession question was the FIRST deliverable, not a by-product

`uip_expected_move` and `cip_check` read the **same two rates** and rest on the **same
no-arbitrage family**, so "different function or the same relation read forward?" is a real
question and it was answered **before** any arithmetic was written:

* `cip_check` consumes a **TRADED FORWARD** and publishes a **DEVIATION** (a dislocation).
* `uip_expected_move` consults **no forward** and publishes a **PREDICTION** (the expected
  spot move — the benchmark a carry trade bets against).

**Different functions, same parity family**, tied by the **exact identity**

```
UIP's one-year expected move  ==  CIP's forward premium  ==  (i_d - i_f) / (1 + i_f)
```

Verified numerically at `i_d = 4.25 %`, `i_f = 1.00 %`: **3.217822 %** both ways; the
spec's first-order `i_d - i_f` = 3.25 %, a **3.2 bp** second-order gap. "Supersedes NOTHING
and is not superseded" is printed in `decision_relevance`.

### 2. `confidence` is a model-specific CAP — the increment's central design decision

§22.8 forbids a bare literal. The standard remedy is `compute_confidence()`, and this
function **deliberately does not use it**: UIP's inputs are observable and its arithmetic is
exact, so **no reliability factor is impaired**; what is nearly worthless is that the
**hypothesis fails empirically**, and `compute_confidence()` has no factor for *"the method
is known to be false."* So the value is a **reliability CEILING** read from a new leaf
`fx_carry.uip_reliability_cap` (**0.15**, `uncalibrated_illustrative`) — following the
`policy_rules.py` precedent for a model-specific config-leaf confidence. The cap sits **below
every other Module 9 confidence**, and that is **asserted** (a test and the live check).

| literal | leaf | value | status | meaning |
|---|---|---|---|---|
| `confidence = 0.15` | `fx_carry.uip_reliability_cap` | `0.15` | `uncalibrated_illustrative` | a reliability **CEILING**, NOT a `compute_confidence()` penalty |

### 3. Both forms published; the horizon conversion is a HYPERBOLA

`value` carries the **exact** `expected_move_pct` **and** the spec's first-order
`expected_move_simple_pct` side by side, so the approximation's size is **visible**. The
horizon conversion is the money-market convention (`tenor_days / basis_days`, refused beyond
one year), and **the exact ratio is a hyperbola in `t`**, so scaling is only *approximately*
linear — asserted with a `rel=1e-2` bound plus a curvature guard, **not** exact proportionality.

### 4. THE MECHANICAL HAZARD fired exactly as predicted, with the predicted victim

`uip_expected_move` **reuses `cip_check`'s conventions BY DESIGN**, so **seven OLD `cip_check`
anchors went AMBIGUOUS** (`M2a`–`M2d`, `M6c`, `M6d`, `M8b`) — `check_targets` caught all
seven **before any mutant ran**. Fixed by **widening each anchor with a cip-only neighbour,
never deleting a mutation** (D-055/D-060), each widening **byte-verified** after two failed
attempts (the guard block is byte-identical across **22 lines**; only the exchange-rate
positivity loop above it discriminates).

### 5. O-138 opened

`--check-targets` prints its verdict **and then RUNS**, so the "safe" pre-flight was
SIGTERM'd mid-mutation and left **`M4a`'s residue** on disk (`"normalized_to":
"foreign_per_domestic"` vs `HEAD`'s `"domestic_per_foreign"`) with both sidecars present.
`git status --short` could **not** tell the mutant from an edit — O-131's point exactly; the
diff against `HEAD` exposed it and the sidecar repaired it.

### 6. O-127's class fired again

Adding the required `uip_reliability_cap` broke **three** `_fx_carry_settings` helpers
(`test_cip_check.py`, `test_carry_score.py`, `test_dollar_smile_regime.py`) — the mechanical
break `test_cip_check.py` had already predicted. Caught by the GREEN-UNMUTATED run.

### Gates (measured 2026-09-26, never carried forward — `sweep_health.py` LAST)

```
ruff format --check src tests tools scripts   ->  262 files already formatted
ruff check src tests tools scripts            ->  All checks passed!
mypy --strict src tests tools scripts         ->  Success: no issues found in 262 source files
reachability_audit.py --check-baseline        ->  PASS — baseline 58 = measured 58, no regressions
full suite (--junitxml)                       ->  3429 tests / 0 failures / 0 errors / 1 skipped
mutation_fx_carry.py                          ->  143/143 killed   (was 114)
sweep_health.py  (LAST)                       ->  45 sweeps, 0 leftovers, 0 shapes, 0 committed, 0 failures, OK
```

**262 == 262** (D-035). **Delta against D-111's 3375 collected = +54** = the new
`test_uip_expected_move.py`. **Reachability:** `uip_expected_move` is **SCRIPT-ONLY —
Tier 5** (its only caller is `scripts/live_uip_expected_move_check.py`), so the Tier 1-4
baseline is untouched and the **Tier-5 script-only count moves 12 → 13**.

**Two late gate failures, both in the new files, both fixed rather than waived.** (i) The
`--check` run refused `scripts/live_uip_expected_move_check.py` (unformatted) and flagged
`tests/models/test_uip_expected_move.py:635` — `decision_relevance` is `str | None`, so
`.lower()` was a `union-attr` error; the fix adds an `is not None` assertion, which is also
the **stronger** test (it proves the field is published). (ii) The first full-suite run
counted **3429**, not the pre-written 3427 — the two extra are the `test_the_day_count_basis_
selects_the_scaling_map` / `test_the_simple_form_carries_the_tenor_scaling` additions, so the
doc was corrected to the **measurement**. **The counts in this block are the re-run values;
the pre-written figures were superseded.**

**The live check FAILED on its first run — and the defect was in the CHECK, not the model.**
Section (5) compared a **bare ratio deviation** `(4 − ratio)` = `0.059620` against `bound =
i_foreign` = `0.020277`, reporting OVER-BOUND. That is a **unit mismatch**: the left side is a
dimensionless ratio-deviation, the right side a rate. Re-derived from the exact algebra with
`a = i_d − i_f`, `u = i_f`: `4·m(¼) − m(1) = a·u·0.75 / ((1 + u/4)(1 + u))`, which is strictly
below `u` because the denominator exceeds 1. Expressed **as a fraction of the longer move**,
the live shortfall is **`0.015131`** — inside the `i_f` bound, as the model promises. Section
(5) and its docstring were corrected to the fraction-of-move form, and the check now PASSES.
**This is D-109's lesson firing again: a cross-check's two sides must share a unit** — and it
is why the check is run rather than assumed.

---

## D-113 — O-138 closed: `--check-targets` was NEVER A FLAG

**A tool fix, not a function increment.** No model code changed; Tier 5 stays **13/23**.

### The root cause was worse than the report

O-138 described *"`check_targets` prints its verdict and then RUNS"* — implying a flag that
existed and merely failed to stop. **Measured: it did not exist.** No sweep in `scripts/`
parses `sys.argv`; every `main()` takes no arguments and every `__main__` is a bare
`sys.exit(main())`. So `--check-targets` was a token **nothing read**, and the sweep fell
through to its full mutation loop. **A flag that is silently ignored is worse than one that
does not exist**, because the operator's belief that they only checked is what stops them
inspecting the tree.

**The suggested fix would not have worked as written.** An `sys.exit(0)` where the report
imagined the flag handling would have been unreachable code. **A suggested fix is a claim
about the code it names** — the first move was to `grep` for `argv` and find none.

### The fix

`scripts/_sweep_gate.py` now exports `CHECK_ONLY_FLAG = "--check-targets"` and
`check_only_requested(argv=None)` (an **exact** match; the `--check-target` typo is NOT
honoured). `scripts/mutation_fx_carry.py` gains `_check_targets_only()` and answers the flag
in `main()` **before `sweep_lifecycle`** — the ordering is the fix, because the lifecycle is
what writes the sidecar. Exit **0 clean / 4 unsound**.

**Measured:** `143 mutations, 0 problem(s)`, exit **0**, **1.6 s** (was a 12-minute sweep),
**no sidecar**, tree untouched.

### Five tests, both defects proved caught by mutation

New section 7 in `tests/test_sweep_sidecar_lifecycle.py`: constant exported · predicate incl.
near-miss rejection · **per-sweep structural ordering** · no-sidecar behavioural · a refusing
**negative control**. Proved: moving the ask after the lifecycle → ordering test RED; making
the predicate `return False` → predicate test RED.

### Gates (measured 2026-09-26, `sweep_health.py` LAST)

```
ruff format --check src tests tools scripts   ->  262 files already formatted
ruff check src tests tools scripts            ->  All checks passed!
mypy --strict src tests tools scripts         ->  Success: no issues found in 262 source files
full suite (--junitxml)                       ->  3478 tests / 0 failures / 0 errors / 1 skipped
sweep_health.py  (LAST)                       ->  45 sweeps, 0 leftovers, 0 shapes, 0 committed, 0 failures, OK
```

**262 == 262** (D-035). **+49 against D-112's 3429** = the new section-7 tests. **No sweep
was re-run** — no anchor changed, so D-112's **143/143** stands.

### Not done

O-138's **second** suggestion — a refusing `DIRTY TARGET` banner unless `--allow-dirty` — is
**NOT** done. It is a separate change whose report-not-refuse behaviour is deliberate
(`describe_dirty_targets`: "a legitimate increment *is* a dirty tree"). **An implied fix is a
disclosure, and a disclosure is not a measurement.**
