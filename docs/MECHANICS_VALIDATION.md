# External Mechanics Validation — Phase 0–4

**Written:** 2026-09-20 · **Scope:** the macro mechanics Phases 0–4 implement, checked
against published sources rather than against the specification's own prose.

**Why this file exists.** An AGENTS.md instruction and the Phase 0–4 audit brief both
called for *"web research on macro trading logic mechanics, flow mechanics, and
execution patterns up to Phase 4 to validate expected behavior."* No session had done
it. This is that research, and it is deliberately **narrow**: it validates the four
mechanics where a plausible-looking implementation can be *quietly wrong* — the policy
rule, the output gap, the breakeven, and vintage/PIT handling. It is not a survey.

**Reading rule.** Each section states what the external source says, then what this
code does, then the verdict. **A verdict of AGREE means the code matches the source.**
Where the code *exceeds* the source it is marked so, because that is where the
project's own defects have historically lived (a guard that looks right and is
unreachable — O-101, D-080).

---

## 1. The policy rule — coefficients are correct, and the Taylor principle is enforced

**Source.** Taylor (1993), as summarised at
`centralbank.watch/general-models/taylor-rule-methodology` (fetched 2026-09-20):

> `Interest Rate = Neutral Rate + Current Inflation + ½(Inflation Gap) + ½(Output Gap)`

and on the balanced-approach variant: *"Federal Reserve staff often use this version…
puts more weight on jobs and unemployment."* Crucially, the same source states the
**Taylor principle** — *"real rates must rise when inflation rises"*, so the inflation
coefficient must exceed zero in gap terms (total response > 1:1).

**Code.** `config/settings.yaml` lines 89–107:

| quantity | value | recorded basis |
| --- | --- | --- |
| `taylor_output_gap_coefficient` | **0.5** | Taylor (1993) original |
| `inflation_gap_coefficient` | **0.5** | Taylor (1993) original; note records the Taylor principle |
| `balanced_approach_output_gap_coefficient` | **1.0** | Fed's balanced-approach rule weights the gap 2× classic Taylor |
| `pi_target` | **2.0** | FOMC longer-run objective, PCE |

**Verdict: AGREE, with the principle recorded as a rule not a comment.** The
`inflation_gap_coefficient` note states *"a nominal rate response below 1:1 to inflation
is destabilising"* — the Taylor principle, attached to the coefficient that enforces it.
The balanced-approach 1.0 is **exactly** the 2× weight the source describes, and it is
carried as a **distinct coefficient** rather than folding into one `output_gap_k`, which
is what makes the two variants auditable side by side.

**The limitation the source names, and the code's answer.** The source is unambiguous
that the rule *"cannot be applied mechanically"* because the neutral rate and potential
output are unobservable, and that *"an error of just 0.5% in the neutral rate shifts the
policy recommendation by the same amount."* This code already encodes that:

- `r_star` is `value: 0.5` with `calibration_status: uncalibrated_illustrative` and a
  note naming the NY Fed Holston–Laubach–Williams series as the tracked estimate,
  plus *"Section 21.4 item 13: unobservable by nature."*
- `pi_target` is `institutional_fact` — correctly a different status, because it **is**
  knowable.

That distinction between *uncalibrated_illustrative* and *institutional_fact* is the
project's own mechanism for the source's warning, and it is applied in the right
direction.

---

## 2. The output gap — the literature says revisions are enormous; the spec already says so

**Source.** Orphanides & van Norden, *The Reliability of Output Gap Estimates in Real
Time* (Board of Governors, August 1999 — fetched and text-extracted). The abstract:

> *"ex post revisions of the output gap are of the same order of magnitude as the output
> gap itself, that these ex post revisions are highly persistent and that real-time
> estimates tend to be severely biased around business cycle turning points, when the
> cost of policy induced errors due to incorrect measurement is at its greatest."*

And the causal decomposition, which is the part that matters most:

> *"although important, the ex post revision of published data is not the primary source
> of revisions in output gap measurements. The bulk of the problem is due to the
> pervasive unreliability of **end-of-sample estimates of the trend** in output."*

**Why this is the single most important external finding for this project.** The paper
separates two causes that are easy to conflate:

1. **data revision** — the published number changes (a vintage problem);
2. **end-of-sample trend unreliability** — the *filter* is unstable at the edge
   (an estimation problem).

Cause 2 dominates. **A system that fixed only vintage handling and believed the output
gap was then trustworthy would have fixed the smaller half of the problem** — and this
is precisely the class of error this project has repeatedly found (D-080: a mechanism
that looks correct and does not reach the branch that matters).

**Code.** The project does not estimate a trend; it **consumes** a published potential
(`gdp_potential`) and — this is the relevant part — documents the hazard in the same
terms. `AGENTS.md` §1.1 and §6.2 carry the lagging-data point, and the regime
classifier's recession warning text (the string a D-082 mutant was rewriting) reads:

> *"RECESSION is a severe label returned by a threshold comparison on a REVISED,
> model-dependent output gap that is itself measured against an unobservable potential.
> …the official dating of a recession arrives long after it begins"*

**Verdict: AGREE, and the disclosure names the dominant cause.** The warning attributes
the unreliability to the *revised, model-dependent* gap measured *against an
unobservable potential* — i.e. causes 1 and 2 both, with the emphasis on the gap being
model-dependent, which is cause 2. A system that disclosed only "data may be revised"
would be under-disclosing; this one does not.

**The residual risk, stated honestly.** The project is **US-only through Phase 4**
(§22.3) and consumes a *published* potential rather than filtering its own. So the
end-of-sample instability is inherited from the publisher rather than introduced here —
which is the right trade at this phase, but it means **the number's reliability is not
established by this codebase.** The mitigation is the disclosure above; the remedy
(own Kalman-filtered potential) is a Phase 5 item. This is consistent with
`config/settings.yaml`'s own note that *"Phase 5+ replaces this constant with a
Kalman-filtered estimate."*

---

## 3. The breakeven — implemented as *compensation*, and the risk premium is disclosed

**Source.** Standard TIPS mechanics: breakeven inflation = nominal yield − TIPS real
yield at the **same maturity**, and the difference is *inflation compensation*, not pure
expected inflation — it contains an inflation risk premium and a TIPS liquidity premium.
The two failure modes: (a) mismatched maturities, so the difference also prices curve
slope; (b) reading the number as an expectation, which inverts the policy inference
(a risk-premium-driven rise is not a hawkish signal).

**Code.** `models/yield_curve.py::breakeven_inflation`:

```python
breakeven = inputs.nominal - inputs.tips_real
```

with the docstring stating the compensation-vs-expectation distinction *"has a practical
consequence: a rising breakeven can mean the market expects more inflation OR that it
demands more compensation for uncertainty, and the two call for opposite policy
readings"*, a `warnings` entry naming **both** premia, and an assumption recording that
*"the orchestrator forms breakevens only at tenors present in BOTH curves."*

**Verdict: AGREE on both failure modes.** Mismatched maturities are prevented
structurally (the orchestrator forms breakevens only at common tenors) rather than left
to the caller, and the expectation misreading is disclosed in both the docstring and a
machine-readable warning. **The unit contract is also correct**: the result is `percent`
and both legs are observed yields, so no estimation step is hidden inside a subtraction.

---

## 4. Vintage / point-in-time — the strongest section, and it refuses a tempting substitution

**Source.** ALFRED (`alfred.stlouisfed.org`) exists precisely because FRED's default
view is the *current* vintage: *"ALFRED allows you to retrieve each economic data
release (vintage) that was available on a specific date in history."* Using the current
vintage in a backtest is textbook **look-ahead bias** — the number was not knowable at
the time, so any signal computed from it is not reproducible live.

**Code — and this is the part worth reading twice.** `data_layer/publication_dates.py`
lines 31–45 documents a trap the sources do **not** generally warn about:

> *"``fred_search`` also returns ``realtime_start`` and ``realtime_end``, which look like
> ALFRED's vintage bounds. They are not: for every series both equal **today**, because
> they describe the vintage window in force **now**, not the revisions that existed in
> the past. Passing ``realtime_start`` as a query parameter is silently ignored —
> **A/B tested**, and the two responses differed only in request
> ``timestamp``/``duration`` metadata."*

and then refuses the substitution:

> *"So this module can populate ``release_datetime`` and cannot populate
> ``vintage_datetime``. Those are different questions — 'when did this become public'
> versus 'which revision is this' — and only the first is answerable here. Reporting a
> current-vintage window as a revision identity would be the exact substitution
> Section 6 prohibits, so it is not done."*

**Verdict: AGREE, and this exceeds what the sources say.** The published guidance is
"use ALFRED, not FRED". The code goes further: it identifies a field on the **FRED**
endpoint that *masquerades* as an ALFRED vintage bound, **A/B tests** that it is inert,
and then declines to populate `vintage_datetime` at all rather than fill it with a
wrong-but-plausible value. That is §21.0 rule 4 (no silent substitution) applied to the
exact field where the temptation is strongest.

**Corroborating discipline in the same file.** The `search_type=series_id` prefix trap
is handled the same way: an **exact** `series_id` equality is required, because a prefix
sibling's `last_updated` *"would attach one series' publication time to another, which is
a wrong fact rather than a missing one. **Missing is recoverable; wrong is not.**"*

**Corroborating discipline in the orchestration layer.** The GDP/GDI divergence
abstains with `None` on a *"BEA revision vintage gap, not an error"*, and the year-ago
lookup is `_value_on_or_before` on the **common** quarter rather than calendar
arithmetic, because *"a divergence computed from mismatched quarters would be a
discrepancy plus one quarter of growth."*

---

## 5. What this research did NOT find

Stated plainly, because an audit that reports only agreements is not an audit.

1. **The end-of-sample trend instability (§2) is inherited, not solved.** The system
   consumes a published `gdp_potential`. Orphanides & van Norden's *dominant* cause of
   output-gap error is therefore outside this codebase's control. It is disclosed; it is
   not mitigated. The Phase 5 Kalman-filter item is the remedy and is already recorded.
2. **No source was found validating the specific *thresholds* in config.**
   `convergence_threshold_bp: 50` and `uncertainty_threshold_bp: 100` are marked
   `uncalibrated_illustrative`, which is honest, but the research confirms only that
   they are conventions — it does not establish them. They remain judgement values.
3. **The macro→instrument translation is not externally validated.** Modules 9–11 (FX,
   commodities, equity macro) are Phase 4+ and the research did not attempt to validate
   an execution-pattern mapping, because §22.3 scopes the system to **US-only through
   Phase 4** and no execution path is implemented (the system **never trades**).

---

## 6. Verdict

| mechanic | external source | code | verdict |
| --- | --- | --- | --- |
| Taylor rule coefficients | Taylor (1993) / balanced approach | 0.5 / 0.5; balanced gap 1.0 | **AGREE** |
| Taylor principle | "real rates must rise when inflation rises" | recorded on the coefficient, not just in prose | **AGREE** |
| unobservable r\* and π\* status | "highly sensitive… every estimate is uncertain" | `uncalibrated_illustrative` vs `institutional_fact` | **AGREE** |
| output-gap revision hazard | Orphanides & van Norden (1999) | disclosure names the *revised, model-dependent* gap | **AGREE** |
| output-gap *dominant* cause | end-of-sample trend unreliability | inherited from a published series; disclosed, not mitigated | **ACCEPTED GAP** |
| breakeven = compensation | risk + liquidity premium | named in docstring **and** a warning | **AGREE** |
| breakeven maturity matching | must be same tenor | enforced structurally in the orchestrator | **AGREE** |
| vintage / look-ahead bias | ALFRED vs FRED | refuses to populate `vintage_datetime`; A/B-tested the decoy field | **AGREE, exceeds source** |

**Bottom line.** On the four mechanics where a plausible implementation can be quietly
wrong, the code matches the published sources — and on vintage handling it is *more*
careful than the general guidance, having detected and documented a decoy field on the
FRED endpoint that looks like an ALFRED vintage bound but is not. **The one accepted
gap is structural, not a defect:** the dominant source of output-gap error is inherited
from the published potential series, is disclosed in the output, and its remedy is
already scheduled for Phase 5.

**No code was changed as a result of this research.** It is validation, and it produced
no finding that required a fix — which is itself a result worth recording, because it
is the first research pass in this audit to come back clean.
