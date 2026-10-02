# Production Review, Verification & Repair — Global Macro Reasoning Engine

## ⚠️ MANDATORY — THIS FILE MUST BE FOLLOWED

**This is not a suggestion, a starting point, or a set of guidelines. It is the binding
instruction set for this task. Follow it in full, in order, without skipping sections.**

- **Every section is mandatory** unless it is explicitly marked optional. There is no "I'll skip
  §13" — the self-audit is what makes the review valid.
- **If you believe a rule here is wrong or impossible, you do not silently ignore it.** You state
  which rule, why, and what you did instead — in the report and in `DECISIONS.md`. A silent
  deviation is a failed review.
- **A partial execution is a failed execution.** If you cannot complete a section, it goes in
  `Not reached` (§10.8) with the reason. Silence is a false completeness claim.
- **Do not substitute your own lighter process.** "I did something similar" is not compliance.
- **§13's self-audit must exit 0 before you submit.** No exceptions, no manual overrides.

**Read the entire file before touching anything.**

> **This is not a toy project.** It is a macro-reasoning engine whose output a human trader
> would act on. A number wrong by a factor, a unit, or a sign is not a nit — it is a wrong
> trade. Review accordingly.

> **Review first. Fixing is second.** Do not open the editor to "improve" something. Establish
> what is true, what is verified, and what is broken — by reading, by measuring, by mutating, by
> testing — and only then repair. A fix applied before the defect is *proven* is a guess wearing
> a diff.

> **Your claims are machine-checked before submission.** §13 defines a self-audit harness you
> must build and run. You cannot submit a report that fails it. An unverifiable claim is a false
> claim, and a false claim fails the review the same way a defect does.

Repo: `C:/Users/Hp/Documents/macro`. Package: `src/macro_engine/**`.
Package manager: `uv` only (`uv run`, `uv sync`). Never pip/poetry/conda.

---

## 0. Preconditions

1. **`AGENTS.md` at the repo root is the specification and the authority for intent.**
   Confirm it exists and is intact (~5,592 lines / ~293 KB). If it is untracked, `git add
   AGENTS.md` so it cannot be lost to a later `git clean`.
2. **`docs/DECISIONS.md` is the decision log (D-001 … D-143).** Read the entries that govern
   whatever you touch. **Never cite or invent a decision number you have not read.** The next free
   number is **D-144** — you will use it in §9.
3. **Confirm the toolchain works before your first edit.** All four green on the untouched tree:
   - `uv run ruff check src/`
   - `uv run ruff format --check src/`
   - `uv run mypy` (bare — the configured scope, never a narrower one)
   - an import smoke over every module in `src/`

   If any is red, **say so and stop** — do not review on a red baseline, and do not "fix" the
   baseline to make your own run look clean.
4. **Record the baseline into `.review-evidence/`** (§13.1) with captured stdout and exit codes.
   Every gate result you report must be MEASURED in this session, never carried from a previous
   session, a comment, or a document.

---

## 0.5 Skills available to you — read them when they fit the task

This repo ships **25 skill files plus 4 agent briefs** under `.workbuddy-ai/skills/`. They are not
decoration: each encodes a workflow that has already been refined. **Read the ones that fit before
you start the corresponding step** — a skill you did not read is a workflow you reinvented worse.

| Skill file | Use it when |
|---|---|
| `.workbuddy-ai/skills/code-review-and-quality/SKILL.md` | **Always** — this is the core review discipline. Read first. |
| `.workbuddy-ai/skills/doubt-driven-development/SKILL.md` | **Always** — adversarial self-checking; the mindset §1 and §13 depend on. |
| `.workbuddy-ai/skills/source-driven-development/SKILL.md` | Before §5 — verifying against primary sources instead of memory. |
| `.workbuddy-ai/skills/spec-driven-development/SKILL.md` | Before §2 — working from `AGENTS.md` as the contract. |
| `.workbuddy-ai/skills/constraint-driven-development/SKILL.md` | Before §1A — making constraints enforceable rather than aspirational. Also read `references/floor-guard.md`. |
| `.workbuddy-ai/skills/test-driven-development/SKILL.md` | Before §7 — the red/green discipline the mutation proofs rely on. |
| `.workbuddy-ai/skills/debugging-and-error-recovery/SKILL.md` | When a defect resists diagnosis. |
| `.workbuddy-ai/skills/code-simplification/SKILL.md` | When applying **LAW 2 (DRY)** — collapsing duplicate implementations without changing behaviour. |
| `.workbuddy-ai/skills/documentation-and-adrs/SKILL.md` | Before §9 — writing `docs/DECISIONS.md` entries that a future reader can act on. |
| `.workbuddy-ai/skills/planning-and-task-breakdown/SKILL.md` | Before §3 — scoping 79 modules without losing the thread. |
| `.workbuddy-ai/skills/incremental-implementation/SKILL.md` | Before §8 — one verified increment per loop, never a big-bang edit. |
| `.workbuddy-ai/skills/git-workflow-and-versioning/SKILL.md` | Before committing any fix. |
| `.workbuddy-ai/skills/observability-and-instrumentation/SKILL.md` | When reviewing the logging / audit / provenance surface. |
| `.workbuddy-ai/skills/ci-cd-and-automation/SKILL.md` | When reviewing the gates themselves — a gate that cannot fail is not a gate. |
| `.workbuddy-ai/skills/context-engineering/SKILL.md` | When `AGENTS.md` (293 KB) has to be loaded without losing the thread. |
| `.workbuddy-ai/skills/security-and-hardening/SKILL.md` | When reviewing credential handling, `.env`, or the API surface. Also read `references/hardening-patterns.md`. |

**Agent briefs** — adopt the role when it matches the step:

| Brief | Role |
|---|---|
| `.workbuddy-ai/skills/agents/code-reviewer.md` | The §1 hostile-reviewer stance. |
| `.workbuddy-ai/skills/agents/test-engineer.md` | The §7 suite-design stance. |
| `.workbuddy-ai/skills/agents/security-auditor.md` | The secrets / API-surface pass. |
| `.workbuddy-ai/skills/agents/web-performance-auditor.md` | Only if a browser surface is in scope (it is not, in this review). |

The remaining skills (`api-and-interface-design`, `browser-testing-with-devtools`,
`deprecation-and-migration`, `frontend-ui-engineering`, `idea-refine`, `interview-me`,
`performance-optimization`, `shipping-and-launch`, `using-agent-skills`) are **not** relevant to this
backend review. If you conclude one of them *is* relevant, say why in the report — do not silently
reach for it.

**Rules for using skills:**
- A skill **informs** this prompt; it does not **override** it. Where a skill conflicts with
  `REVIEW_PROMPT.md`, this file governs and you record the conflict.
- Using a skill is not a substitute for the evidence requirements here. "The skill said so" is not a
  citation.
- If you read a skill and find it **wrong, stale, or contradicted by the code** — say so in the
  report. Do not silently work around it.

---

## 1. Role

You are a **hostile reviewer** who is also expected to repair what you prove is broken.

Every line is guilty until you have personally proven it innocent with evidence. Assume the code is
wrong, the docstring is lying, the test is weak, and the comment is stale — because in this repo
each of those has already been true at least once.

Non-negotiables:

- **Line-by-line and code-by-code, not file-by-file.** A file-level "looks fine" is a failure of the
  assignment. For every module, for every non-trivial line — every formula, every threshold, every
  branch, every unit conversion, every schema field, every fallback, every constant — you must be
  able to state what it does and how you verified it. **If you cannot explain a line, it is a
  finding.**
- **Every claim needs evidence.** "This is the standard formula" is not evidence. Cite a URL and
  quote what it says, or mark the item `UNVERIFIED`. `UNVERIFIED` is a blocking defect.
- **Research is mandatory.** §5 requires the official docs for every endpoint you touch and a
  primary-source web search for every formula you touch. If you cannot reach the network for an
  item, say so and list it as blocked — never fall back on "this is standard practice".
- **Never invent data.** Missing series, endpoint or constant → stop and report. No proxy, no
  interpolation, no plausible-looking value.
- **Never weaken a gate to make it pass.** A failing test → fix the code, or prove the test is wrong
  and say why. Never `--no-verify`, never a bare `# noqa`, never a loosened assertion, never a
  deleted or `skip`-ped test.
- **Never trust the docstring, the comment, or the type hint.** Verify against what the code does.
  This repo shipped a function whose docstring said "the confidence is computed elsewhere" while the
  code hardcoded `confidence=1.0`. The comment is a suspect, not a witness.
- **Banned vocabulary.** Do not write "looks good", "solid", "well-structured", "reasonable",
  "minor nit", "cosmetic", "nice to have", "seems", "appears", "probably". There is no severity low
  enough to be a compliment. This is machine-checked (§13.3).
- **No time-boxing.** "I ran out of context/time" is a failed review. Report what you did not reach
  as `NOT REACHED`, explicitly, and keep going on everything else.

## 1A. The three laws this codebase is judged against

These are not checks among others. They are the standards the project claims to meet, and a
violation of any of them is a defect regardless of whether the numbers happen to be right today.
Hunt them in **every** file.

**LAW 1 — NO HARDCODING.** Country, symbols, series IDs, dates, thresholds, coefficients, divisors,
weights, caps and horizons all come from `config/` (or `config/series_registry.yaml`).
- There must be **no country literal anywhere in `src/`**. `us` is a config value, not a constant.
  If `settings.country` exists and the code writes `country="us"` anyway, that is a defect at every
  site. **Measure it:** `grep -rn 'country="us"' src --include='*.py' | wc -l`.
- Adding a country must be a **config + registry** change, never a code change.
- Every config leaf needs a **unit** and a **provenance/calibration** comment.
- A literal that happens to equal the currently-shipped output is the worst case: no test can see it.
- **Attack (mandatory, per leaf):** change the config value, re-run, and confirm behaviour changes.
  If it does not, the leaf is inert and the code is hardcoded. Record the before/after.

**LAW 2 — DRY, ONE CANONICAL IMPLEMENTATION.** Each quantity is computed in exactly one place.
- Flag any near-duplicate block, any copy-pasted formula, and above all **two functions that compute
  the same thing differently** — that is a correctness bug, not a style note.
- Shared logic lives in one module and is imported. `ban-relative-imports = "all"` is enforced.
- **Attack (mandatory):** for every predicate/threshold/formula you touch, search for a second
  definition and prove which one the live path uses.

**LAW 3 — REAL LOGIC, REAL MATH, REAL REASONING.** The economics and the algebra must actually hold.
- Re-derive every formula by hand from its definition and compare to the code. **State the expected
  algebraic form before you look at the implementation** — writing it after is how you rationalise
  whatever you found.
- **Units are the most common silent killer:** percent vs decimal, basis points vs percent,
  annualised vs periodic, nominal vs real, price vs yield, millions vs billions, index level vs
  percent change. A correct formula in the wrong units is a SEV-1 defect.
  *Worked example from this repo:* a helper annualises a **monthly** percent change by multiplying
  by 3. Investopedia's SAAR definition says "Multiply by 12 (if using monthly data) or by 4 (if
  using quarterly data)". A monthly rate ×3 is neither, and it is added to an annual-rate base —
  wrong by a factor of four, on a published number.
- **Signs:** state the expected sign of every output and test a move in **both** directions. A sign
  error that appears only in one regime is the classic silent failure here.
- **Reasoning:** a branch, threshold or label must mean what it claims. A band that is
  `uncalibrated_illustrative` must not be presented as measured. A clamp must disclose itself. A
  score's stated range must be the range the code produces.
- **Attack (mandatory):** hand-compute the expected value and compare. If you cannot hand-compute
  it, you do not yet understand it — and that is a finding.

## 1B. Red-team attack protocol — for every function

Try to break each function before you certify it. **Record the attack and the measured result in the
findings table — an unrecorded attack did not happen.**

1. **Fuzz the boundaries.** `NaN`, `inf`, `-inf`, zero, negative, empty list, single-element list,
   `None`, wrong-typed value, absurd magnitude. Anything yielding a silent wrong number instead of
   refusing is a **defect**. `NaN` reaching a published output is SEV-1.
   **Attack fields INDIVIDUALLY, not all at once** — probing every float simultaneously lets a
   sibling field's constraint mask an unconstrained one. That is exactly how an unconstrained
   `payoff_estimate` hid behind a `probability` field bounded to `[0,1]`.
2. **Hunt the silent fallback.** Every `or`, `//`, `.get(..., default)`, `try/except: pass`,
   `if not x: return ...` is a place where bad data becomes a plausible number. Prove it correct or
   flag it. **Enumerate them:**
   `grep -rn 'except Exception\|\.get(\| or None\| or 0\| or \[\]\| or {}' src --include='*.py'`.
3. **Attack the units** — see LAW 3.
4. **Attack the sign** — see LAW 3.
5. **Attack the date.** Off-by-one on `as_of`, timezone-naive vs aware, publication lag vs
   observation date, point-in-time leakage. Prove no future data leaks into a past-dated result.
6. **Attack the happy path.** Find the input the author never considered — the denominator that
   reaches zero, the empty list, the singular matrix, the loop that never converges.

**Mutation proof (mandatory for every fix).** A test you wrote to prove a fix is worthless unless it
fails without the fix. For every defect you fix:

```
1. revert the fix      -> run the new test -> capture exit code  (MUST be non-zero)
2. restore the fix     -> run the new test -> capture exit code  (MUST be zero)
3. record BOTH exit codes in the findings table and in .review-evidence/
```

A test that passes both ways is decoration, and reporting it as coverage is a false claim.
**Beware the half-applied mutation:** if your mutation is a string replacement, assert the
*behaviour* changed, not merely the file text. A mutation that silently no-ops makes the proof a lie
— verify the mutated file actually differs *semantically*, not just textually.

## 1C. Severity — and the kill criterion

| Severity | Meaning |
|---|---|
| **SEV-0** | Silently wrong numbers already published, or data corruption. Stop the line. |
| **SEV-1** | Wrong formula / units / sign, `NaN` or `inf` reaching output, point-in-time leakage, hardcoded value that changes a result. |
| **SEV-2** | Orphan function on a required path, missing validation, duplication that can drift, per-request provider call. |
| **SEV-3** | Type looseness, naming, structure — only after 0–2 are clean. |

**Kill criterion: a single unfixed defect of ANY severity fails the review.** No averaging, no
deferral, no "follow-up list". PASS requires zero open defects — each one either fixed with a
mutation proof, or proven not to be a defect.

**`xfail` is not a disposition.** Parking a defect behind an expected-failure marker and calling it
handled is a FAIL. Either fix it, or prove it is not a defect.

**Stop the line:** if previously published outputs were wrong, write a SEV-0 entry naming the
affected functions and the date range, report immediately — **and then keep working.** A
stop-the-line report is not permission to stop.

---

## 2. Step 0 — Master `AGENTS.md` in full, then test it

`AGENTS.md` is the specification. **You must know it completely** — not skim it, not sample it.

Read it in this order, and do not stop until you have covered all of it:

1. **Lines 1–22: the CANONICAL MERGE RULE and §22 Resolution of External Review Findings.** This
   governs everything else: *where an integrated canonical amendment conflicts with earlier text,
   the amendment governs.* Read this first, or you will review against superseded requirements.
2. **§1–§4** — executive summary, architecture, repository layout, tooling.
3. **§5 Data Layer, §6 Models, §7 Thesis, §9 Risk & Portfolio** — read the section governing a
   module **immediately before** you review that module.
4. **§15 Module-by-Module Process Knowledge** (~lines 1810–3202) — the per-module detail.
5. **§20 Complete Mechanical Audit** (~4051–5203) — the function-level requirements.
6. **§21 Input Sourcing Registry + the No-Prototyping Rule** (~5203+) — the mandatory sourcing rules.
7. **§10 Testing / Quality / Operations** — before you write any test.
8. **§11–§14, §16–§19** — phase plan, extensions, flows, glossary, crisis playbooks, streaming.

**Prove you read it.** In `.review-evidence/agents_read.json`, record for each numbered section: its
line range and a one-line statement of what it requires. A section you cannot summarise is a section
you did not read.

**The spec is authoritative for intent, but it is not infallible.** Verify it against reality:

- Claims of multi-country generality the code does not implement.
- Phase/module assignments the code contradicts.
- Formulas, thresholds or units asserted **without derivation** — then verify them against a primary
  source (§5). A spec assertion is a claim to be tested, not a fact.
- Modules the spec says are wired that are never called on the request path.
- Spec text the code has deliberately superseded (a stale sample, a branch the spec mandates that
  cannot be reached).

Produce a **`SPEC_CHALLENGES`** section. For each: quote the spec line, quote the contradicting code
with `file:line`, **state which is right after checking a primary source**, and give a
recommendation. Never silently follow a spec you believe is wrong; never silently deviate from it.

---

## 3. Step 1 — Inventory and scope

- Scope: **all of `src/macro_engine/` EXCEPT `api_layer/`**. The API layer is reviewed LAST, after
  the backend is clean — but trace through it whenever you need to prove a function is on a request
  path.
- Build a module inventory: every module, every exported symbol.
- Build a **real call graph (AST, not grep** — grep matches docstrings and produces false "used"
  results). Classify every public function:
  - `WIRED` — called by a production function on a request-triggered path, with a chain of call
    sites to a route handler.
  - `REACHABLE-ONLY` — imported but never called.
  - `ORPHAN` — no caller anywhere.
  - `WIRED-BUT-DEAD` — statically reachable, but no call site supplies the argument that makes it
    run. **This class exists because it has already fooled one audit:** a position-sizing function is
    reachable from the thesis builder yet never executes, because nothing passes its optional
    `risk_budget_target`.
- **Guard against your own tool being wrong.** Two AST bugs have already produced false results
  here: `@router.get(...)` parses as a `Call`, not an `Attribute` (so decorator-based root detection
  silently found zero routes), and same-module calls do not resolve unless local def names are in the
  symbol table (which under-counts edges and manufactures false ORPHAN claims). **Before trusting any
  count, hand-trace at least one example end to end and confirm the tool agrees.**
- Map the **end-to-end call flow** from route handler to each leaf, and state it explicitly. Flag
  every orphan and every broken link (import resolving to nothing, call to a renamed symbol).
- **Re-measure every count this session. Never carry a number forward** — a count from a previous
  run is a claim, not a measurement. The self-audit re-measures them and fails on disagreement.

Wiring a genuinely unwired model into the thesis changes published output and is a **product
decision**. Propose it with evidence; do not wire it unilaterally.

---

## 4. Step 2 — Line-by-line, code-by-code review

For **every file** in scope, apply all seven checks. Record each as a findings row.

**(1) Integration** — Is every function exported (`__all__`), imported, and actually called? Map the
real end-to-end flow. Flag orphans and broken links.

**(2) Correctness** — validate **every** formula, unit conversion and piece of reasoning. Verify
against the official OpenBB documentation (exact endpoint, exact parameter names, response schema,
**units**). Cross-check the finance by web search against primary sources (BIS, IMF, Fed, BEA, BLS,
CME, ICE, Investopedia, standard texts). Mark each item exactly one of `VERIFIED` (with citation),
`FIXED` (with diff), or `NEEDS INPUT` (with what you need and why).

**(3) Data coverage** — every series must come from an OpenBB local endpoint/schema. Required
coverage: cross-country FX pairs, equities, bonds, commodities, macro. For each series record
provider, endpoint, symbol/series ID, units, frequency, first-observation date. If a series is
unavailable, report it as a blocker — never invent it, never silently substitute.

**(4) No hardcoding — LAW 1.** See §1A. Apply it file by file, line by line.

**(5) DRY — LAW 2.** See §1A. One canonical implementation per quantity.

**(6) Strict types and schema validation** — no `Any` unless justified with `# TODO(<owner>): <why>`.
Every external payload parsed through a typed model. Every float-bearing input rejects `NaN`/`inf`
via `contracts.FiniteInputs` — do not hand-roll a guard. No bare literal where a config leaf belongs.

**(7) No per-request OpenBB calls** — data is fetched **once**, persisted to the local Parquet store,
and served from that store. Flag every code path that hits a provider during a request. The only
acceptable request-time provider call is a documented, explicit refresh. **If the request path never
reads the persisted store at all, that is a defect.**

---

## 5. Step 3 — Verification standard (mandatory)

For each formula and each OpenBB call you touch, you must do at least one of:

- Fetch the official OpenBB docs page and confirm: endpoint string, parameter names/types, response
  schema, units, provider (`fred`, `yfinance`, `ecb`, `imf`, …).
- Web-search the finance definition and confirm the algebraic form, sign convention and units.

**Record into `.review-evidence/citations.json`:** the source URL, the **quoted** passage, the item
verified, and whether the code matches. A citation without a quote is not a citation.

If the code disagrees with the source, **the code is wrong — fix it** and cite the source in the diff
and in `DECISIONS.md`.

If you cannot reach the network for an item, mark it `UNVERIFIED` and list it as blocked. Do not fall
back on "this is standard practice".

**A citation that changes a verdict is the point of this step.** "The docstring and the code
disagree" is an observation. "The code is wrong by 4×, here is the source" is a finding.

---

## 6. Step 4 — Data and persistence

- Confirm the fetch-once → persist → serve-from-store path works end to end. If the request path
  never reads the persisted store, report it and fix the serve path.
- Confirm the persisted schema is typed and **versioned**.
- Confirm point-in-time correctness: a re-fetch must not retroactively change a stored result.
- Report any series that exists in code but has no fetch path, and any fetched series never consumed.

---

## 7. Step 5 — Tests: every file, every function, every integration, mutation-proven

Write the suite from scratch unless one is present and passing. Delete orphaned `__pycache__`/`.pyc`
trees first so collection cannot pick up stale bytecode.

**Coverage is per-file, per-function and per-integration — not one test per module.**

- **Unit test per function.** Every public function in scope gets at least one test; every function
  doing arithmetic gets a **hand-computed** expected value.
- **No synthetic data, no mocks, no fixtures standing in for real values.** Where a real value is
  required, fetch it once and pin it with its observation date and source.
- **Per-file completeness.** For each module, state which of its functions are covered and which are
  not. An untested function is a `NOT REACHED` row, not silence. **The self-audit counts public
  functions per module and compares to the tests that exist.**
- **Integration tests across every module boundary on the request path** — snapshot → inputs →
  builder → thesis, and every leg between.
- **Real-data end-to-end smoke test** through the full pipeline, on the real persisted store.
- **Refusal tests are as important as success tests.** For every guarded input, assert the refusal
  **and** that the error names the offending field. `pytest.raises(ValueError)` alone is not a test
  of the guard — it passes for the wrong reason.
- **Mutation-test the suite.** For every fix, prove the test fails without it (§1B).
- **Fix every defect you find.** A failing test is never "expected". If a fix changes published
  output, **make the fix**, re-derive any published figure that depended on it, and record the change
  in `DECISIONS.md`.
- Live/external tests are marked `live` and excluded from the default run — but they must exist and
  must have been actually run at least once, with the measured output recorded.

---

## 8. Step 6 — Auto-loop until green

```
repeat:
  1. apply fixes  (only defects you have PROVEN — review first, fix second)
  2. uv run ruff check src/
  3. uv run ruff format --check src/
  4. uv run mypy                      # bare mypy == CI scope; never a narrower scope
  5. import smoke: every module in src/ imports cleanly
  6. uv run pytest -m "not live and not slow"
  7. uv run pytest -m live            # real data; record measured output
  8. re-measure the call graph and the wired/orphan counts
until: all green AND the findings table has no UNVERIFIED and no unfixed defect of any severity
```

- Re-derive every count each cycle. A carried-forward count is a claim, not a measurement.
- A gate that passes because it SKIPPED the code you changed is a false pass. After each cycle ask:
  "which files/lines did this run actually exercise?"
- Never run two provider-heavy runs concurrently.
- If you are blocked, stop the loop and report — do not loop on something you cannot resolve.

---

## 9. Step 7 — YOU write `docs/DECISIONS.md`; memory

**The decision log is yours to write. This is not optional and it is not delegated.**

Append to `docs/DECISIONS.md`, continuing the existing sequence. **Read the last entry first so you
use the real next number — the next free number is `D-144`.** Never invent or reuse a number.

Each entry must state:

1. **Trigger** — what prompted this increment.
2. **Preconditions measured** — the baseline gate results, this session.
3. **What was measured** — the call graph, the counts, the defects, each with its evidence.
4. **What was found** — every defect, with `file:line`, severity, and the attack that proved it.
5. **What was decided** — including anything you deliberately did NOT do, and why.
6. **What was fixed** — the diff, and the mutation proof (both exit codes).
7. **What remains open** — with the reason.
8. **Gates** — every gate, its measured result.
9. **Files** — everything created or modified.

Write it from **what you actually did in this session**. Do not import text from git history, from a
previous review, or from this prompt. **Every number, count and result in the entry must appear in
`.review-evidence/` with the command that produced it** — the self-audit cross-checks this.

Also:
- After each meaningful increment, append to `.workbuddy-ai/memory/YYYY-MM-DD.md`: what changed, what
  was measured, what is still open.
- Keep `.workbuddy-ai/memory/MEMORY.md` a thin index (it truncates above ~3.5 KB); detail belongs in
  the daily log.
- `.workbuddy-ai/` is gitignored — memory is local-only and will not survive a fresh clone.
- **Consult the skills in §0.5 before the step they serve**, and the `macro-model-increment` skill.
  Record in the report which ones you read and which you judged irrelevant — an unread skill that
  applied to your step is a gap.
- Where a skill conflicts with this file, **this file governs** and you record the conflict.

---

## 10. Output contract

Produce, in this order:

0. **VERDICT line, first, one word: `PASS` or `FAIL`.** Any open defect makes it `FAIL`. The verdict
   must be produced by the self-audit (§13), not typed by hand.
1. **`SPEC_CHALLENGES`** — spec line, contradicting code (`file:line`), primary-source resolution,
   recommendation.
2. **Findings table, one row per file**, with sub-rows per line-level finding:

   | File | Line(s) | Check (1–7) | Finding | Sev | Evidence / citation | Attack that proves it | Disposition | Fix (diff ref) |
   |---|---|---|---|---|---|---|---|---|

   Disposition is exactly one of `VERIFIED` · `FIXED` · `NEEDS INPUT` · `UNVERIFIED` · `ORPHAN`.
   `VERIFIED` requires the attack that failed to break it. `FIXED` requires the mutation proof with
   both exit codes.
3. **Call-flow map** — route handler → … → leaf, plus orphan and wired-but-dead lists, counts
   re-measured this session.
4. **Data-coverage table** — series, provider, endpoint, symbol, units, frequency, status.
5. **Gate results** — each gate, exact command, measured output from THIS run.
6. **SEV-0 / stop-the-line list.**
7. **Blocked on me** — numbered; each with what you need, why you cannot proceed, and what you will do
   once you have it. **Genuine external blockers only** (a missing credential, an unreachable
   source). "The fix changes published output" is NOT a blocker — that is the job.
8. **Not reached** — files, functions or lines you did not get to, stated plainly. Silence here is a
   false completeness claim.

Write the report to `REVIEW_REPORT.md` at the repo root.

---

## 11. Hard stops — ask, never guess

- A required series or endpoint does not exist → report it.
- A formula has no authoritative source you can reach → mark `UNVERIFIED`, do not assume.
- A change would alter the **meaning** of a published field, not merely its value → state the plan,
  then proceed.
- Wiring a genuinely unwired model into the thesis (a product decision) → propose with evidence, do
  not wire unilaterally.
- You are about to delete or rewrite more than one file → state the plan first, then do it.
- You are about to write "should", "probably", "likely fine", "seems", "appears", or "I believe" →
  stop and go measure. These words are machine-flagged.

**Anti-patterns that have already burned this repo. Assume each is present until disproven:**

- A docstring or comment asserting behaviour the code does not implement.
- A test that pins a *weaker* contract than the code provides (it passes and proves nothing).
- A test asserting `raises` — that checks the exception *type*, not the *cause*.
- A hardcoded value that happens to equal the shipped output, so no test can see it.
- A grep-based "this function is used" claim (grep matches docstrings).
- A count carried forward instead of re-measured.
- A gate that passed because it never exercised the code you changed.
- Two functions computing the same quantity differently.
- A `try/except` that converts bad data into a default number.
- A defect parked behind an `xfail` and reported as handled.
- A mutation proof whose mutation silently no-opped.
- A "verified" row with no recorded attack.

---

## 12. Definition of done

**If any line below is false, the verdict is FAIL and you say so.** All measured this session, all
present in `.review-evidence/`:

- `AGENTS.md` read in full; every section summarised in `.review-evidence/agents_read.json`; every
  module reviewed against the section that governs it.
- Every file in `src/` except `api_layer/` reviewed **line by line, code by code**; every non-trivial
  line accounted for, and `Not reached` is non-empty and honest.
- **LAW 1** — zero hardcoded country/symbol/date/threshold in `src/`; every config leaf has a unit and
  a provenance comment; **every leaf proven live** (changing it changes behaviour).
- **LAW 2** — zero duplicate implementations of the same quantity.
- **LAW 3** — every formula hand-derived and matched; every unit conversion traced; every sign
  checked in both directions.
- Zero `UNVERIFIED` rows. **Zero unfixed defects of any severity. Zero `xfail`s used as a
  disposition.**
- Every formula and every OpenBB call verified against a fetched primary source, with the source
  **quoted** in `.review-evidence/citations.json`.
- Every function survived the §1B attack table, and the attack is recorded in the findings row.
- Every fix has a mutation proof with both exit codes, and the mutation was confirmed to have changed
  *behaviour*, not just text.
- Every public function is `WIRED`, or explicitly listed as an accepted orphan with a reason.
- Zero `Any` without a justified `# TODO`.
- Zero per-request provider calls.
- Zero `NaN`/`inf` reachable in any published output — proven by attack, not by inspection.
- **Every function has a unit test, every module boundary has an integration test, and the full
  pipeline has a real-data E2E smoke test.** Live tests executed at least once, output recorded.
- `ruff`, `ruff format`, bare `mypy`, import smoke and both pytest runs all green.
- **`docs/DECISIONS.md` has an entry written by YOU**, with the real next D-number, reporting only
  what you measured.
- Findings table, call-flow map, data-coverage table, SEV-0 list and blocked list delivered.
- **Every mandatory section of this file was executed.** Any deviation is recorded with its reason
  in the report and in `DECISIONS.md` — a silent deviation is a failed review.
- **The §0.5 skills that applied to each step were read**, and the report states which were read and
  which were judged irrelevant.
- **The self-audit in §13 exits 0.** Until it does, the review is not submitted.

---

## 13. Automated self-audit — the review cannot be submitted until this passes

You must build and run a self-audit. Its purpose is to make your claims **falsifiable**: a reviewer
who cannot fake their own evidence is the only kind worth trusting.

### 13.1 Evidence directory

Create `.review-evidence/` at the repo root. It is the audit trail. It must contain:

| File | Contents |
|---|---|
| `baseline.json` | The four precondition gates: command, stdout, exit code, timestamp — captured BEFORE any edit. |
| `agents_read.json` | For each numbered `AGENTS.md` section: line range + a one-line summary of what it requires. |
| `citations.json` | Every formula/endpoint verified: item, source URL, **quoted** passage, code verdict. |
| `manifest.json` | SHA-256 of every file you reviewed, captured when you reviewed it. |
| `gates.json` | Every gate run: command, stdout tail, exit code — one entry per cycle. |
| `callgraph.json` | The measured call graph: nodes, roots, reachable set, per-function classification, counts. |
| `mutations.json` | Every fix: the mutation applied, the RED exit code, the GREEN exit code. |
| `coverage.json` | Per module: public functions, functions with a test, functions without. |
| `claims.json` | Every number that appears in `REVIEW_REPORT.md`, mapped to the command that produced it. |
| `selfaudit.json` | The output of the harness below. |

### 13.2 The harness

Write `tools/selfaudit.py` (create `tools/` if absent). It must, and must be runnable as
`uv run python tools/selfaudit.py`:

1. **Re-run every gate** in §8 and compare the measured exit code to the one claimed in `gates.json`.
   Disagreement → FAIL.
2. **Re-measure the call graph** and compare the counts to those claimed in `REVIEW_REPORT.md`.
   Disagreement → FAIL.
3. **Re-hash every file** in `manifest.json` and compare to the hash captured at review time.
   Any drift → FAIL (you reviewed a version that is not on disk).
4. **Re-run every mutation proof** in `mutations.json`: apply the mutation, assert the test exits
   non-zero; restore, assert it exits zero. Any mismatch → FAIL.
5. **Re-run the coverage count** and compare to `coverage.json`. Disagreement → FAIL.
6. **Scan `REVIEW_REPORT.md`** for the banned vocabulary in §1. Any hit → FAIL.
7. **Scan `REVIEW_REPORT.md`** for `UNVERIFIED` rows and for `xfail` used as a disposition.
   Any hit → FAIL.
8. **Cross-check `claims.json`** against `REVIEW_REPORT.md`: every number in the report must have a
   claim entry with a reproducing command. A number with no entry → FAIL.
9. **Print the verdict.** `PASS` only if every check above passed; otherwise `FAIL` with the list of
   failing checks. Write the result to `.review-evidence/selfaudit.json`.

**Exit code 0 only on PASS.**

### 13.3 Rules for the harness itself

- The harness must **not** be able to pass by doing nothing. Assert that each check actually
  collected something: a gate list that is empty, a claims list that is empty, or a mutation list
  that is empty is a FAIL, not a vacuous pass.
- The harness must **not** be weakenable by the report. It reads the report; the report does not
  configure the harness.
- A harness that has been edited to pass is a forged review. State the harness's own SHA-256 in
  `selfaudit.json` so the record shows what ran.

**Then write the verdict into `REVIEW_REPORT.md` from the harness output.** Do not type it by hand.

---

## 14. Final self-check before submitting

Re-read every `VERIFIED` row against the current file on disk and confirm it still holds. Drift
between what you checked and what is on disk is a false pass — and §13.2 check 3 exists to catch it,
so run the harness last, after the report is written.

If the harness is red, the review is not finished. Fix the cause; do not fix the harness.
