# Phase 0 — Production-Grade Review (D-136)

**Scope of this phase.** The operator-authorized full review (Phase 0 → Phase 5) begins
with the system's *foundations*: the mutation/sweep safety apparatus, the CI gate scope,
and the observed slowness during runs/mutations/sweeps. This document records every finding,
its root cause, the measurement behind it, the fix, the guarding tests, the re-derived gates,
remaining risks, and why Phase 0 is complete.

This is **not** a code change to `src/`. Phase 0 of the review touched `scripts/`, `tools/`,
`tests/`, CI, and `pyproject.toml` only — the skeleton the engine's correctness checks ride on.

---

## 1. Performance: the actual bottleneck (measured, not guessed)

The operator's explicit instruction: *identify the real bottleneck rather than masking it with
arbitrary optimizations.* Every candidate was timed, not assumed.

| Candidate | Measurement | Verdict |
|---|---|---|
| OpenBB import (`import openbb`) | 30.5 s | **Not on the path.** Only 2 lazy `from openbb ...` imports exist, both *inside* functions in `src/`; **zero** in `tests/`. The sweep/test path never imports it. Rejected as the cause. |
| `PYTHONPATH` WorkBuddyAI shim | `python -c "pass"` = 0.995 / 0.859 / 0.942 s with it; **0.514 s** with `env -u PYTHONPATH`; 0.553 s with `-S` | Environment overhead, **~0.5 s per Python spawn**. Documented; not a repo defect and not the sweep bottleneck. |
| pytest collection (4264 tests) | cProfile: 30.7 s of 33.5 s in module imports during `genitems`; largest single contributor `macro_engine.data_layer.schemas` ~943 ms (pydantic ~223 ms) × 98 test modules | Real, but **fixed cost paid once per run**, not per mutation. |
| Per-mutation wall time | `tests/models/test_as_of.py`: 16 tests in **0.14 s** of test body but **3.83 s** total wall | **This is the bottleneck.** |
| pytest flags (masks, not fixes) | baseline 3831 ms · `+no:cacheprovider` 3712 · `+disable-warnings` 4232 · `--assert=plain` 3889 | **No flag moves the needle.** Confirms the cost is interpreter + pytest import startup (~3.7 s), not the test logic. |

**Root cause:** the mutation suite runs **one process per mutation** (≈1000 catalogue
entries across the 52 sweeps). Each process pays ~3.8 s of startup for ~0.14 s of work.
Total measured: **52 sweeps in ~6 m 43 s**, i.e. ~1.4–11 s each (catalogues of 6…176).

**Honest conclusion (and the part that is *not* fixed):** the slowness is the
spawn-per-mutation topology, not any single slow function, not OpenBB, not pydantic alone.
Masking it (—cacheprovider, —assert=plain, a faster formatter) shaves nothing material.
The real fix is a single long-lived worker that applies all mutations **in one interpreter**
and re-spawns only to report — a structural refactor that is **out of Phase 0 scope** and is
recorded as the Phase 1+ performance work item. We measured and documented rather than
shipped a cosmetic patch.

**Local API health (bonus measurement).** With the operator's local OpenBB server now up on
`:6900`: warm `/api/v1/economy/fred_series` calls are **0.02–0.05 s** (cold first call 16 s
= one-time route compile). Real data confirmed: `DGS10 = 3.95` (2024-01-02), `CPIAUCSL =
309.698`. The API is **not** a contributor to slowness and **does** serve real data, so
Phase 1+ live-data steps are unblocked.

---

## 2. O-138 — `--check-targets` was silently ignored by 46 of 52 sweeps

**Defect.** `check_only_requested()` existed, but 24 sweeps had *no argument parsing at all*
and 22 had a flag that was never wired into `main()`. So the "safe pre-flight" that is
supposed to print the anchor verdict and touch nothing **ran the full sweep** — which writes
to `src/`, can be interrupted, and can leave a mutant on disk. The safe mode was unsafe by
default.

**Fix (root, not symptom).** A one-shot adoption pass (deleted afterward) patched all 52
`scripts/mutation_*.py`:
- No-flag sweeps: a `_check_targets_only()` helper + a guard at the **top of `main()`**,
  *before* any file is read or written, branching on `check_only_requested()` → `check_only(...)`.
- argparse sweeps: `--check-targets` added as an alias for `--list`, honored early.
- 4 files needed `check_only`/`check_only_requested` added to their `_sweep_gate` import.

**Verification (not assumed).** Ran all 52 sweeps with `--check-targets`: **52/52 reported
`SRC TREE UNCHANGED: YES`**, 51 rc=0, 1 rc=4 (the two genuinely drifted anchors — see §5).
Total ~6 m 43 s.

**Guard tests.** `tests/test_sweep_check_only_flag.py` (new, 106 tests): census `>= 50`,
per-sweep static flag declaration (parametrised over 52), per-sweep *ordering* check scoped to
`main()` via an AST helper (so an apply/revert helper above `main()` cannot trip it), and a
behavioural run of `mutation_as_of.py --check-targets` asserting rc=0, verdict printed, no
`KILLED`/`SURVIVED`, no sidecars left.

---

## 3. D-136 — `_is_applied` was a tautology (destroyed-work hazard)

The leftover discriminator in BOTH `scripts/_sweep_gate.py` and `tools/sweep_health.py` had
collapsed to "is `new` present in the text?" after an earlier "fix".

**Why it was false.** This branch is reached only when `text.count(old) == 0` — the anchor is
*already* absent. `str.replace` with an absent needle returns the text unchanged, so
"re-applying does not raise `new`'s count" was true for **every** text in which `new` merely
appeared. The predicate reduced to `new in text`.

**Measured failure.** `_is_applied("| a | b |", "ANCHOR_THAT_NEVER_EXISTED", " |") == True`.
In `mutation_command_inventory.py`'s `M5` the replacement is the two-byte `" |"`, present in
every markdown table — so a **drifted** anchor was reported `MUTATION STILL APPLIED … this is a
LEFTOVER` on a tree `git status` called clean. The printed remedy is *"restore the file before
sweeping"* → natural reading `git checkout --` → **discards uncommitted work**. That cost this
project 97 lines once (D-086.8). **A gate whose remedy destroys work must not fire on a
predicate that cannot be false.**

**Fix (both copies).** The discriminator now **requires the pristine text** (`pristine`, the
`git show HEAD:<file>` blob) and proves application:

```python
if not new.strip():                 return False      # deletion = unverifiable, never a leftover
if text.count(old) != 0:           return False      # anchor present → not our question
if text.count(new) == 0:           return False      # both absent → drifted, not applied
if pristine is None:               return False      # unanswered question = no finding (D-062)
if pristine.count(old) == 0:       return False      # HEAD lacks anchor → compare was a no-op
return _fold(text) == _fold(pristine.replace(old, new, 1))
```

The decisive change: a mutation is reported applied **only** when
`text == pristine.replace(old, new, 1)` AND HEAD actually carries the anchor. Anything else is
"anchor absent" — the non-destructive error — which is the right call: a drifted anchor makes
the sweep refuse with "target ABSENT"; a false "leftover" invites a destructive restore.

**Guard tests.** `tests/test_sweep_health_leftover_predicate.py` rewritten: every behavioural
case now supplies its own `pristine` (the D-136 requirement that the question is undecidable
without HEAD). Cases: pristine file, genuinely-applied mutant, deletion, vanished-anchor+vanished-
replacement, the both-absent true-positive, the non-idempotent mutant, and a new
`test_a_drifted_anchor_is_not_reported_as_a_leftover` that builds **two different anchors** (a
drifted one HEAD never carried → not applied; a live one HEAD carries and the text mutated →
detected) plus an uncommitted edit at the site → not applied. The structural guard now asserts
the decisive `return` references **both** `pristine` and `replace`, and that an `if` guard
checks `pristine.count(old)`. Result: **57 passed, 1 deselected** (was 16 red).

---

## 4. `sweep_health.py` blind spot — a sweep reported `[ok]` while its own gate refused

**Defect.** `sweep_health.py` reported `mutation_command_inventory.py` as `[ok] … every anchor
resolves`, yet that sweep's own `check_targets` *refused* on 2 unsound anchors. Root cause:
`_legacy_targets` could not resolve module-level `Path` constants `PROGRESS`/`REGISTRY`/`GUARD`
(nor `SETTINGS` in `mutation_performance_record.py`) — they fell back to `Path("<unknown>")`,
every check was skipped, and the sweep was silently pronounced healthy.

**Fix (root).** `_legacy_targets` generalised to "any module-level `Path` that exists on disk"
(two loops, non-underscore then underscore). The sweep's own `_TARGETS` map is now honoured by
`_native()`. And an **unreadable target is now a loud FINDING** instead of a silent `continue`:

```python
problems.append(
    f"{name}: TARGET UNRESOLVABLE — {target} cannot be read, so this check "
    "did not look at the anchor it is named for ..."
)
```

---

## 5. Two genuinely drifted anchors repaired (not masked)

`mutation_command_inventory.py`'s `M5` / `M5`-adjacent anchors had drifted from the live
`docs/PROGRESS.md` census row (`**6 of 201**`). Regenerated `_CORRECTED_ROW` / `_M5_OLD` byte-
exactly from the live row. `check_targets` now reports `6 mutations, 0 problem(s)` — the single
`rc=4` in the §2 sweep run.

---

## 6. CI scope asymmetry (D-133a, the other direction)

`mypy`'s configured `files` includes `scripts/` (so it saw the 52 sweeps — real logic, ~40 k
LOC, the only code that rewrites `src/` at runtime), but CI's two `ruff` steps did **not**. So
`scripts/` was linted by nobody. Fixed: added `scripts/` to both `Lint (ruff check)` and
`Format check (ruff format)` in `.github/workflows/quality-gates.yml`, with the justification
inline.

Also in `pyproject.toml`: replaced a stale `slow` marker string (`"loads all 45 mutation
sweeps"` — the catalogue is 52) with the correct count, so a reader sizing the run is not
mis-sized by ~16%.

---

## 7. Gates re-derived at CI scope (all green)

| Gate | Result |
|---|---|
| `ruff check src/ tools/ tests/ scripts/` | **All checks passed** |
| `ruff format --check src/ tools/ tests/ scripts/` | **294 files** already formatted |
| bare `mypy` (CI scope) | **Success, 294 source files, no issues** |
| D-035 equality `format == mypy` | **294 == 294** (re-derived; was 293 == 293 — the +1 is the new test file) |
| `reachability_audit.py --check-baseline` | **PASS 58/58, no regressions** |
| Full suite (`--junitxml`, authoritative) | **4264 tests / 0 failures / 0 errors / 23 skipped** (vs 4156/0/0/4) |
| `sweep_health.py` (LAST) | **OK — 52 sweeps, 0 leftovers, 0 mutant shapes, 0 committed mutants, 0 failures** |

`src/` was **not** modified in Phase 0; verified `git diff --stat HEAD -- src/` is empty and
there are **no** `.sweepbackup` sidecars after every run (O-157/O-158/O-159 probe).

---

## 8. Remaining risks (explicitly not closed)

1. **Per-mutation spawn cost (§1) is measured and documented, not fixed.** A single-interpreter
   worker that applies all mutations in-process is the real fix; deferred to Phase 1+ performance
   work. Do not close this by adding a "faster" flag.
2. **`mutation_econometrics.py` still at 48/109** (M34 = measured INERT-BY-ROUTE). Pre-existing,
   not introduced by D-136; belongs to the sweep-reachability follow-up, not Phase 0.
3. The `PYTHONPATH` shim (~0.5 s/spawn) is an environment artifact. If CI ever shows spurious
   slowness, re-measure before blaming repo code.

## 9. Why Phase 0 is complete

Every defect found was fixed **at root**, not masked: the safe pre-flight is now actually safe
(52/52), the destructive-remedy tautology is replaced by a proof against HEAD (both copies,
guarded), the health tool can no longer pronounce a broken sweep healthy, the CI scope is
symmetric, and the one real data drift was repaired from source. All gates are green at CI's
own scope. The only item carried forward is the spawn-topology performance refactor, which is a
named Phase 1+ work item — and even that was *explained*, not papered over.
