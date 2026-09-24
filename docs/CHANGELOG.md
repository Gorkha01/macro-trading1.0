# Changelog

Notable changes to the Global Macro Reasoning Engine. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entry dates are the date of the change, not the release.

---

## [Unreleased]

### D-105 — `classify_regime_markov_switching`: the regime index is not identified

**Added**

- **`classify_regime_markov_switching`** (§6.2, Module 3) — the Tier-5 REPLACEMENT for
  `classify_regime_rule_based` (§21.3, D-096). Phase 5+ builds the sophisticated version and
  **deletes nothing**, so the rule-based classifier still ships. **Tier 5 = 7/23.** It publishes
  the **smoothed probability path per period** (the primary output — §6.2 asks for probabilities,
  "not a hard label"), the real-time current read from the **filtered** path, the transition
  matrix, expected durations, per-regime shares **and integer counts**, the parameter count, the
  log-likelihood, and the library's own warning count.
- **`MarkovRegimeSettings`** in `config.py` plus a required `regime.markov` block in
  `settings.yaml`: six numeric leaves and three choices as **plain leaves** (`switching_variance`,
  `markov_trend`, `markov_optimizer`) — Section 4a's rule that the `CalibratedValue` envelope is
  for NUMBERS and a selection has no such question.
- **`scripts/live_regime_check.py::_check_markov_regime`** — real GDPC1 year-over-year growth
  (314 observations, 1948 → 2026), asserting the published identities, recomputing the library's
  own matrix to prove the transposition, and checking the ordering rule **against the raw series**.

**Changed**

- **`models/regime.py` now imports `statsmodels`** (the sibling `econometrics.py` already did at
  module level).
- **`mutation_regime.py`: 41 → 71 mutations**, and `-x` added to the selection (D-057 — the
  selection is ~28 s, so 71 mutations without it is ~34 minutes of foreground). Measured: `-x`
  changed no mutation's outcome.
- **`tests/models/test_regime.py`: 39 → 73 tests.** The suite goes **3112 → 3146** passed
  (default marker set), a delta of exactly the 34 new tests.

**Fixed**

- **Two sweeps' honesty canaries were anchored on `__all__`** — a line every increment that
  exports a function edits. Both moved to the module's first statement (**O-126**).
- **`tests/models/test_trilemma.py` could not COLLECT** after the required `markov` field was
  added, which would have made **all 63 of that sweep's mutations "kill" identically** — a perfect
  score measuring nothing (**D-059's trap**). Caught only by the mandatory green-unmutated run
  (**O-127**).

**Notes**

- **The library's regime index is NOT identified.** Measured at `search_reps=10`: over 12 rng
  seeds, **4** put the HIGH-mean regime at index 1 and **8** put the MIDDLE-mean regime there.
  The restarts *improve* the likelihood and make the labelling *less* stable, so the fix is a
  published **canonical ordering by estimated mean** — with the permutation *and* the raw-index
  means published, so the ordering is checkable from the output alone.
- **The library's transition matrix is COLUMN-stochastic** — its own docstring says element (i,j)
  is P(from j to i). Measured: rows `[0.876519, 1.087713, 1.035767]`, columns exactly 1. The
  published matrix is the **transpose** and the orientation is stated on every output.
- **The smoothed path is retrospective** — `|smoothed − filtered|` reaches **0.630416** and is
  **exactly 0.0** at the endpoint, so the current read comes from the filtered path.
- **Six library behaviours were found by PROBING, none by reading** — including that
  `fitted.params` is a Series for a Series endog and an ndarray for an array (so the return
  container mirrors the *input* container), and that `trend="n"`/`"t"` leave the ordering key with
  nothing to sort on.
- **Nothing numeric is rounded**, because every probability here carries a stated identity and
  rounding to 6 dp broke each of them (measured: rows summed to 0.999999, durations drifted by
  0.0035).

### D-104 — the two most frequent defects, made into GATES

**Added**

- **`tests/test_source_hygiene.py`** — repo-wide invariants that no single module owns, both
  of which recurred often enough to stop being accidents and were invisible to every existing
  gate.
- **A duplicate-name gate (O-117, recurred ×3).** Python binds a module-level name to the
  **last** definition, so two `def test_x()` leave ONE test and `pytest` reports **nothing**.
  The gate parses every module under the owned roots and fails on any top-level
  function/class name defined twice — asserted directly rather than left to a linter's scope,
  because a per-file lint of the file you just edited is exactly where a duplicate hides.
- **A carriage-return gate (D-061's defect class, still live).** An anchor written with `\n`
  matches **zero** times in a CRLF file: the edit looks applied and changes nothing. **`git`
  cannot see this** — `git status` reported clean and `git add --renormalize` staged
  **nothing**, because the stored form was already LF and git normalises for comparison. So
  the gate reads the **working tree**, which is what the sweeps read.
- **Two divergent-case tests and a walk control.** Each detector is run against a
  deliberately-broken fixture, and the file walk is asserted to find >200 files, because both
  gates are vacuously true on an empty list.

**Fixed**

- **21 source files were CRLF in the working tree** — `risk.py`, `catalysts.py`, 14 test
  files, 4 live checks, `mutation_api_layer.py` — normalised to LF. The exposure was
  **21 files, not one**.
- **`tools/reachability_audit.py:133` wrote the baseline as CRLF** — `write_text` without
  `newline=""`, the exact D-061 defect. Found **by the new gate, immediately**:
  `config/reachability_baseline.txt` was **78 CRLF / 0 LF**. Fixed at the root and regenerated;
  the result is **content-identical** under a CR-insensitive comparison.

**Findings**

- **The gate paid for itself on its first run** — it found a live writer that had been
  corrupting a tracked file, which no git-level check could have seen.
- **18 `write_text` calls lack `newline=""`**; 17 are `tmp_path` fixtures (harmless, **O-125**)
  and the one that mattered was the baseline.

**Documented**

- `docs/DECISIONS.md` **D-104**; `docs/OPEN_ISSUES.md` **O-125**.

### D-103 — a harness increment: the sweep's exit code, and the machine it owns

**Fixed**

- **`EXIT=1` from a mutation sweep no longer means nothing (O-122, CLOSED).**
  `sweep_lifecycle`'s cleanup was a bare `unlink` inside a `finally`; the sandbox's
  per-turn bulk-delete counter refuses deletes past a threshold (measured `count: 167`
  against 50), so on a 109-mutation run the cleanup raised `PermissionError` **out of the
  context manager** and the sweep exited **1** after printing a clean **108/109**. The
  new `remove_sidecars()` reports a refused delete loudly, **returns** the paths, and
  does not raise — the exit code now reports the mutation verdict and nothing else.
- **Two sweeps could still lose their whole log (O-124, CLOSED).**
  `mutation_api_layer.py` and `mutation_regime.py` do not use `sweep_lifecycle`, so they
  did not inherit `line_buffer_stdout()`. Both now call it first in `main()`.
  **`mutation_api_layer.py` is CRLF** while its siblings are LF, so its anchors needed
  `\r\n` and a naive LF anchor matched nothing.

**Added**

- **`tools/sweep_health.py` gained a gate**: a sweep with neither `sweep_lifecycle` nor
  `line_buffer_stdout` is a **FAILURE**, reported per-sweep *and* in the summary, because
  a convention that is only documented is exactly what failed the first time. Measured:
  **0 sweeps** lack it. The per-sweep line was also made consistent, so it can no longer
  print `[ok]` beside a failure count.
- **`sweep_lifecycle` now opens with an ownership banner** naming the measured cost of
  running gates alongside a sweep: **10× slower** (12 s → 2 min per mutation), plus the
  `mypy --strict` hazard where a file that *imports* the swept module type-checks the
  **mutated** source. The rule existed only in a skill and a decision record.
- Three regression tests in `tests/test_sweep_sidecar_lifecycle.py`, including one that
  reproduces the refused delete with a **directory** where the sidecar belongs.

**Findings**

- **The O-117 hazard recurred (third time), caught in the act.** Appending the regression
  tests wrote the block **twice**, so `test_the_ownership_banner_is_printed` was defined
  twice — and a duplicate test name **silently DELETES a test**, so three tests would have
  vanished while `pytest` reported a healthy count. mypy's `no-redef` caught it;
  `ruff`'s F811 is the other instrument. **Run both over the whole tree.**
- **Line-ending mismatches bit three times in one session.** A LF anchor against a CRLF
  file matches **nothing**, silently — the same class as a typo'd anchor, and it is why
  `mutation_api_layer.py`'s first edit appeared to succeed while changing nothing.

**Documented**

- `docs/DECISIONS.md` **D-103**; `docs/OPEN_ISSUES.md` **O-122** and **O-124** both
  **CLOSED**.

### D-102 — Module 8's `yield_curve_pca`; the maturity order IS the analysis; a general sweep-log hole

**Added**

- `yield_curve_pca(daily_changes: pd.DataFrame) -> ModelResult` in
  `src/macro_engine/models/yield_curve.py` (§6.6's verbatim signature — **no
  `n_components`**), Module 8's consumer of Module 18's `compute_pca`. It publishes the
  **loadings keyed in MATURITY order** with `tenor_years` beside them, the
  explained-variance ratios and their cumulative, and **`sign_changes`** — the count of
  adjacent maturity-ordered loadings with different signs, per component.
- `_curve_tenor_years`, a parser for the label shapes the series registry writes
  (`3mo`/`1yr`/`30yr`), and `_sign_changes` / `_sign`, whose zero-handling is
  documented because a zero loading breaks a run rather than agreeing with a neighbour.

**Fixed**

- **`_sweep_gate.line_buffer_stdout()`** — the sweep-log buffering hole was GENERAL,
  not one sweep's. D-101 fixed `mutation_econometrics.py` with `flush=True` on its
  progress prints; a census found **42 of the 43 sweeps had no `flush` anywhere**, so
  every one of them lost its entire log to a kill while the sidecar correctly preserved
  the tree. The fix is one `reconfigure` in the shared helper `sweep_lifecycle` calls
  first, covering the whole catalogue including sweeps written later.
- **`mutation_curve_trade.py`'s M7.4 anchor was WIDENED** — adding `yield_curve_pca`
  gave `_tenor_years`'s opening line a second occurrence, making M7.4 two-site (the
  D-055 trap, in a sweep for a *different* function). `sweep_health.py` caught it.

**Changed**

- `scripts/mutation_yield_curve.py` grew **69 → 90** mutations (the MX8 group).
- `tests/models/test_yield_curve.py` collects **41 → 78** tests (+37).

**Findings**

- **`_tenor_years` refuses every tenor label the series registry writes** — all eleven
  of `1mo`/`3mo`/`6mo`/`1yr`/…/`30yr` raise, while `2y`/`10y`/`30y` parse. So the
  module's own parser could not be reused for a registry-built panel, and the project
  has **two incompatible tenor vocabularies** (**O-123**).
- **`MX8b SURVIVED the first sweep because `dict == dict` ignores KEY ORDER.** It keys
  the loadings in the caller's column order — every value correct, the shape unreadable
  — and the invariance test compares two dicts, which cannot observe order. Closed by a
  test asserting the key order directly.
- **A component's shape is only known if the panel was BUILT to give it one.** The first
  synthetic fixture left the third component to the noise, so PC3's sign pattern was
  arbitrary and "2 changes" failed with **3**.
- **The eigendecomposition is order-invariant; the floating-point arithmetic is not** —
  measured `~1e-11` relative drift from reordering the columns, because LAPACK's
  blocking depends on the memory layout.

**Disclosed**

- `sign_changes` is a DESCRIPTION of a loading vector, **not a label**: §15.20-F forbids
  naming the components and §6.6's stub repeats it. A test scans every published string
  and every loadings key for the forbidden phrases.
- A component's shape is a property of the **tenor set**, not of the curve in general;
  three components are §6.6's choice, not a finding; and the panel's remaining
  components carry real variance when it is wider.

**Documented**

- `docs/DECISIONS.md` **D-102**; `docs/OPEN_ISSUES.md` **O-123** (two tenor
  vocabularies) and **O-124** (two sweeps bypass the shared lifecycle and so the
  buffering fix); `docs/PROGRESS.md`, `docs/BUILD_STATE.md`.

### D-101 — Module 18 #5: `kalman_latent_state`; four silent failures in a Kalman filter; the fit was unit-dependent

**Added**

- `kalman_latent_state(observations: pd.DataFrame, state_dim: int = 1) -> ModelResult`
  in `src/macro_engine/models/econometrics.py` (§15.20-F's verbatim signature), the
  module's unobservable-state estimator. Three state-space specifications, selected
  by `(n_columns, state_dim)` and **published** as `model_spec`: `local_level`
  (`r*`), `local_linear_trend` (potential GDP) and `time_varying_hedge_ratio`. Any
  other combination is refused with the admissible set enumerated from the same
  table the constructor reads.
- The **filtered path with its uncertainty band** on every result — the state, its
  standard error, the band's bounds and coverage, and the latest estimate with its
  band — plus the **smoothed** path's endpoint and the measured revision between
  them, because the difference IS the look-ahead bias a real-time reader must not
  import.
- Seven config leaves under `econometrics:`: `kalman_min_observations`,
  `kalman_band_coverage`, `kalman_diffuse_scale`, `kalman_max_iterations`,
  `kalman_min_state_drift_ratio`, `kalman_max_revision_ratio`, and the choice leaf
  `kalman_optimizer`. `config._KALMAN_MAX_PARAMETERS` pins the observation floor
  against the parameter count, and a test recounts it from the model's own table.

**Fixed**

- **The fitted band depended on the caller's choice of UNITS.** The model is
  scale-invariant and the optimizer is not: measured on ONE local level at six
  scales, `sigma2.level / scale**2` ran **0.3139** at scale 1, **0.3238** at 1e-3,
  **46.16** at 1e3, **2.663** at 1e6 and **0.02625** at 1e9 — a **147× spread on
  identical data**, because `start_params` is `1.0` while the likelihood is
  evaluated at the series' own magnitude. One degenerate series reported a relative
  band of `2.05e-8` in its own units and `4.89e-2` scaled a hundred-fold. Fixed by
  normalising each series before fitting and converting every published quantity
  back, with `series_scales` / `state_scales` published. **Measured after the fix:
  `0.313922` at every scale from 1e-9 to 1e9.**
- **`sigma2.level` / `sigma2.slope` were weakly identified together** and the
  optimizer was the wrong family for this likelihood: measured over 20 simulated
  pairs, the gradient methods failed their own convergence test on **4/20** (`lbfgs`)
  and **12/20** (`bfgs`) while Nelder-Mead and Powell failed on **none** — and
  Nelder-Mead reached the **same** optimum (`sigma2.beta` 0.00001459 against
  0.00001452). Raising the iteration cap did not help, which identifies the stopping
  *rule* rather than the budget. `kalman_optimizer` defaults to `"nm"`.
- **`config._KALMAN_MAX_PARAMETERS`** and the open-interval validator on
  `kalman_band_coverage`: at 1.0 the normal quantile is infinite, so the band would
  publish `inf`.

**Changed**

- `pyproject.toml` gains a scoped `[[tool.mypy.overrides]]` for
  `macro_engine.models.econometrics` with `disallow_subclassing_any = false`, because
  the model subclasses the untyped `statsmodels.tsa.statespace.MLEModel`. **The
  relaxation must name the module that DECLARES the subclass, not the library** —
  adding it to the `statsmodels.*` override has no effect, which was measured.
- `scripts/mutation_econometrics.py` grew **77 → 109** mutations (M77–M108; **108/109
  killed**, with M34 inert-by-route), and its
  four progress prints now carry `flush=True`: a sweep redirected to a file was
  SIGTERM'd and left an **empty log** while the sidecar correctly preserved the tree.
- `M69`'s anchor was **widened** — adding `_prepare_kalman_observations` gave its
  guard line a second occurrence, the D-055 trap where `str.replace` rewrites a
  neighbour and reports a kill for a change applied elsewhere.
- `scripts/live_econometrics_check.py` gained sections 10–13.

**Findings**

- **Four silent failures, each found by probing BEFORE the function was written**,
  every one returning a complete-looking result describing a different model:
  `UnobservedComponents(y, level=True)` fits a **deterministic constant** (it
  reported `102.33 ± 0.18` on a random walk whose level moved several units);
  `mle_regression=False` gives a **recursive OLS** coefficient, not a time-varying
  one (reported `0.4793` against a true `0.4267`, and `0.4793` **is** the full-sample
  OLS value, with a standard error of `0.0023` that makes the wrong answer look
  precise); a missing `transform_params` yields **negative variances** and `nan`
  bands; and **`initialization='diffuse'` reports a standard error of exactly `0.0`**
  for a state the first observation does not identify.
- **The last one decided the design.** Exact-diffuse removes the diffuse component
  from `filtered_state_cov`, so a local linear trend's slope — design `[1, 0]` —
  came back as `0.0 ± 0.0` where the honest answer is the prior's scale. The
  filtered **states** were identical across all three initializations; only the
  published **uncertainty** differed. Pinned by a test that reproduces the
  measurement.
- **A warning was written, measured, and REMOVED.** A relative "degenerate band"
  warning for the collapsed-band case (`102.8486 ± 0.0000377` from a converged fit)
  was deleted because **no threshold separates it from a well-specified one**:
  `median(se)/median|state|` spanned `3.1e-8` to `1.8e-3` for noise-free samples and
  `sigma2.irregular/var(y)` is specification-dependent. An unreliable warning is
  worse than none, so the behaviour is a **limitation** and `sigma2.irregular` is
  published for the reader to judge.
- **D-100's own record was wrong about the block it cited**: §15.20 block F holds
  **five** signatures, not four. The count was taken from the implemented functions
  rather than from the block — the "a citation is a claim" failure D-100 had just
  recorded, one increment later.

**Disclosed**

- The state is **unobservable**, so no data can confirm the filter's answer; the
  band is model-dependent and understates model disagreement.
- The earliest observations are **prior-dominated**, and a state the first
  observation does not identify carries the prior's scale as its band for one step
  (measured: `1000.0` at `kappa = 1e6`, then `1.42`).
- The state innovation variance is **downward-biased** in small samples (median
  `0.2128` against a true `0.25` at n=60), and the bias is toward **false
  stability**.
- A level-only model **absorbs a deterministic trend into its own variance**
  (measured: `sigma2.level = 1.09` against a true `0.25`).
- The band is a prediction interval for the **state**, not for the series, and the
  filter is **not a forecast**.

**Documented**

- `docs/DECISIONS.md` **D-101**; `docs/OPEN_ISSUES.md` **O-119** (the leftover
  predicate cannot distinguish a typo'd anchor from a leftover) and **O-120** (the
  sweep set has outgrown the foreground window); `docs/MODULE_MAPPING.md` (the
  Module 18 table gains its fifth row and the block-F count is corrected to five).

### D-100 — Module 18 #4: `compute_pca`; a fourth defect class in the constant-series guard; O-117 recurs

**Added**

- `compute_pca(daily_changes: pd.DataFrame, n_components: int = 3) -> ModelResult` in
  `src/macro_engine/models/econometrics.py` (§15.20-F's verbatim signature), running
  PCA on **DAILY CHANGES** and publishing the **eigenvalues**, the
  **explained-variance ratios**, the **cumulative** series, and **LOADINGS** as
  `{component: {series: loading}}` — named on both axes so a transposition is
  unrepresentable rather than silently wrong.
- The decomposition is `numpy.linalg.eigh` on the covariance (**D-099**), measured to
  reproduce scikit-learn's PCA to machine precision (**no `scikit-learn` dependency,
  no `pyproject.toml` change, no `mypy` override**). The two sklearn *conventions*
  sklearn supplies by accident are reproduced **deliberately** and individually
  mutation-tested: the **sign rule** (largest-|loading| element positive, sklearn's
  `svd_flip` convention, published on every result) and the **unbiased `1/(n-1)`**
  variance divisor (what `np.cov` produces — **not** the biased `1/n` sklearn's own
  source suggests).
- **Three silent-failure paths found by PROBING `eigh` before writing any guard:** a
  rank-deficient panel yields a **NEGATIVE eigenvalue** (measured `-1.69e-15`, with
  the published ratio printing `-0.000000000000` while the ratios still summed to
  `1.0`); `n_components` out of range slices silently or cryptically; and a non-finite
  panel propagates NaN into **every** eigenvalue and loading rather than raising.
- **The fourth defect class: `std() == 0.0` does NOT fire on a constant column.** A
  constant column's squared deviations leave a floating-point residue (measured
  `8.9e-16` for `4.2` repeated 200×), which defeated **two** guards at once — the
  correlation route's division (scaling the column to `~1e16`) *and* `matrix_rank`'s
  **relative** tolerance on **both** routes. Refused by a tolerance **relative to each
  series' own scale**, checked **before** standardisation so it governs both routes.
- Config: `pca_min_observations` (60) and `pca_near_zero_tolerance` (`1.0e-8`) as
  `CalibratedValue` envelopes; `pca_standardisation` as a plain `str` leaf
  (`{"covariance", "correlation"}`, default `"correlation"`), refused at config load on
  a third value.
- The **standardisation route is consequential and therefore published**: measured
  2026-09-23 on a five-tenor heteroskedastic panel, the two routes disagree by **0.28**
  on PC1's loadings and **invert their ordering**. Both are legitimate answers to
  different questions, so neither is excluded and the route is on every result.
- A **length-aware** levels-detection boundary, `1 - 2.5/sqrt(n)`, replacing a fixed
  `0.95` that missed **88.6%** of genuine level series at `n = 60` (measured over 500
  walks). Measured **0.00% false positives on changes at every length**.
- A **measured** pure-noise PC1-share table (5 columns, 500 draws per length) for the
  thin-panel disclosure. **Marchenko-Pastur** (overstates the bias by `0.11`) and a
  **least-squares fit** (under-predicts by `~0.03`) were both **REJECTED for being
  wrong**, so the measured table is published with linear interpolation rather than a
  fitted law.

**Fixed**

- **The constant-series guard's own tolerance was relative but not PROVEN relative.**
  Mutation **M66** reverted it to a fixed `eps * 100 = 2.22e-14` and **SURVIVED**: every
  constant the tests then used (`4.2`, `0.0`, `-3.0`) leaves a residue a fixed epsilon
  also catches, so no test could tell the two guards apart. **Measured: the residue is
  NOT monotone in magnitude** (`4.2` → `7.1e-14`, `271.83` → `1.1e-13`, `314.16` →
  `4.3e-14`, but `1e6` → exactly `0.0`), so the defeating magnitudes had to be **found
  by measurement**. New tests carrying `271.83` and `314.16` are **verified to kill M66
  by hand**; the sweep moved **74/77 → 76/77**.
- **O-117 RECURRED:** two `compute_pca` refusal tests were written with names already
  owned by `test_stationarity`, so Python bound those names to their **last**
  definitions and **two stationarity guards were silently DEAD** — the stationarity
  constant-series and non-numeric guards had no coverage while appearing present.
  `pytest` collected **176** tests where **178** existed; `ruff`'s **F811** caught it
  twice. Renamed to `_by_pca` (matching the file's `_by_cointegration` convention); the
  collected count rose **176 → 182**.

**Changed**

- `tools/sweep_health.py` now **prints the sweep census** (`sweep files discovered: 43`)
  as a line of its own output instead of leaving the number to be re-typed by hand.
- `scripts/live_econometrics_check.py` gained sections 8 and 9: the **daily-changes
  requirement demonstrated on real data** (real Treasury **levels** must fire the
  length-aware warning; the **changes** must produce a coherent spectrum with no
  negative ratio, the sign rule applied, and **no auto-labelled** component), and a
  **positive control** (a duplicated real tenor, rank-deficient by construction,
  refused). Measured live: levels lag-1 **0.9975** against the **0.9041** boundary;
  on changes PC1 **0.6759** / PC2 **0.2080** / PC3 **0.0928**, cumulative **0.9767**;
  control refused at *"6 columns but rank 5"*, over **680** common daily observations.

**Disclosed, not fixed (operator decision 2026-09-23)**

- At `pca_min_observations = 60` a 5-column panel has 12 rows per series, so
  `60 < 10 * 5` is false and the thin-panel warning **cannot fire on a yield-curve
  panel**. The operator chose to keep the floor at 60 and warn on the ratio; the gap is
  recorded in `_pca_limitations` ("THE SMALL-SAMPLE DISCLOSURE DOES NOT COVER A NARROW
  PANEL") rather than papered over.

**Documented**

- **O-118:** the `.git` object store and `refs/` were **wiped mid-increment** — `refs/`
  absent, the pack file gone leaving only its `.idx`, loose objects 0 — while the
  working tree stayed intact. Recovered from the surviving **reflogs** plus the remote;
  **one unpushed commit (`2027b6c`) was genuinely lost.** `git fsck` is now
  completely clean and `HEAD` = `origin/main`. Cause **not determined** and stated as
  unknown.

---

### D-097 — Module 18 #3: `test_cointegration`; a fourth silent failure in `coint_johansen`; five tests shadowed by name

**Added**

- `test_cointegration(y, x, method="engle_granger") -> ModelResult` in
  `src/macro_engine/models/econometrics.py` (§15.20-F's verbatim signature), with
  **Engle-Granger** (regress then ADF the residual) and **Johansen**
  (`coint_johansen`, trace statistic) paths. **The two rejection directions are
  opposite** — Engle-Granger rejects on a *more negative* statistic, Johansen on a
  statistic *exceeding* its critical value — so both are explicit indexed lookups.
- The three mandated extras, on every call: the **spread series** (with its
  published-series identity proven against the statistic), the **half-life of mean
  reversion** and a **regime-stability verdict** (`stable` / `unstable` /
  `absent_in_both_halves` / `not_tested`).
- The **half-life is derived, not recalled**: `dz_t = phi * z_{t-1} + eps_t` with
  continuous analogue `dz/dt = -kappa*z` gives `phi = -kappa` and
  `H = -ln(2)/phi`. Sign check, both limits, and a hand-computed case
  (`phi = -0.5 -> H = 1.3863`) are asserted against the closed form rather than
  against recorded floats. **Two refusals** bracket the alias boundary
  (`phi <= -1` gives a half-life below the `ln(2)` floor; `phi >= 0` gives a
  negative one) and **two disclosure tiers** flag a positive-but-unusable half-life.
- The two **mandatory warnings**, first and second on every call:
  backward-looking estimation that breaks in regime change (**LTCM named**), and the
  multiple-testing obligation computed as a **count** — family-wise
  `1 - (1-alpha)**m` and corrected per-test `1 - (1-alpha)**(1/m)`, from config,
  with the family size published as an **ASSUMPTION** the function cannot verify.
- Config: `cointegration_min_observations`, `regime_stability_split_fraction`,
  `assumed_test_family_size`, `cointegration_trend` (a plain `str` leaf, `{"c","ct"}`
  only — `"n"` is refused at load because it produces statsmodels' NaN critical
  values).

**Fixed — the FOURTH silent failure**

- **`coint_johansen` emitted 4 `ComplexWarning`s on every call and they escaped the
  function.** `np.linalg.eig` returns complex eigenvectors that are cast to real;
  uncaptured, statsmodels' internals reached the caller's output and **`-W error`
  raised on every Johansen test**, i.e. a correct function became unusable in a
  strict environment while every published field stayed correct. Measured on 40
  seeds and n = 60…1600: the warnings are unconditional and **none** of them
  correlated with a non-finite statistic. **Fixed** by capturing them, publishing
  `discarded_imaginary_warnings`, and adding a disclosure stating this is library
  behaviour and **must not be read as a signal**. The Engle-Granger path reports `0`.

**Fixed — five tests were silently ABSENT from the run**

- Four new `test_cointegration` refusal tests reused names already owned by
  `test_stationarity`'s guards, and one collided with `run_regression`'s confidence
  test. **Python keeps only the last definition of a duplicated name**, so five
  earlier guards were **deleted from the run while pytest stayed green** — a suite
  that had quietly lost five tests, which is the "looks complete" failure this
  project's gates exist to catch. **Only `ruff`'s F811 surfaced it.** Names now
  carry a qualifier and the suite moved **2872 -> 2923 passed**, so the restoration
  is measurable.

**Changed**

- `scripts/mutation_econometrics.py` **33 -> 56 mutations** (M33–M55 + CANARY1) —
  **extended, not added to**, so the sweep census stays **43**. Final **55/56
  killed**.
- New **`INERT_BY_ROUTE`** register for a survivor whose guard is correct but whose
  route the public API cannot reach. It demands a **stated, measured** reason and
  **refuses to certify** (exit 5) on a stale, dangling or unexplained entry, so an
  exemption cannot outlive its reason. One entry: **M34**, measured across 93
  (configuration × trend) combinations with **31 non-finite critical-value cases and
  zero non-finite p-values** — `coint` always trips the critical-value guard first.
- `scripts/live_econometrics_check.py` now runs the cointegration section: a
  **positive control** (`FEDFUNDS ~ DFF`), the **counting obligation** recomputed
  from live settings, and the real TIPS/nominal term-structure pairs **reported, not
  asserted**. Measured 2026-09-23: the control rejects at **p = 0.0000**, half-life
  **0.73**, regime **stable**; **all three term-structure pairs do NOT cointegrate**,
  one of them `unstable` — the LTCM shape found in real data rather than cited.

**Fixed — and it was worse than a wrong test count**

- **The five shadowed tests had also CORRUPTED the mutation sweep.** Three mutations
  (**M2, M30, M32**) reported as surviving were being killed by the **wrong tests** —
  the sweep asked "does any test fail?" and the only tests left under those names no
  longer covered the mutated code. Restating the names took the sweep from **52/56 to
  55/56 with no mutation changed**, and each mutation was then re-applied in isolation
  using the sweep's **own anchors** (compiles OK; suite fails; `1 failed, 111 passed`).
  **O-117 is therefore CLOSED.** *A sweep's verdict is only as trustworthy as its test
  selection.*

### D-096 — "Phase 5+" is an UPGRADE PASS; §21.3's tags supersede OPEN_ISSUES'

**Changed (docs only — no code)**

- `docs/OPEN_ISSUES.md` **Part 3** now opens with a preamble stating that **Phase 5+
  is an upgrade pass, not a tier of new work**: Phases 0–4 built the *simple* version
  of each item and Phase 5+ builds the sophisticated one. **Nothing from Phases 0–4 is
  deleted** — the simple function keeps working and the advanced one supersedes it.
  That is why the operator calls it *"Phase 5+"* rather than a tier.
- **Five stale phase tags corrected**, because §22.1 says §21.3 *"and only that
  table"* decides when a stub becomes IMPLEMENTED:

  | row | was | now |
  |---|---|---|
  | Markov-switching regime model | `3` | **`5+`** (§21.3 lists it in Tier 5) |
  | GARCH-family volatility | `3` | **`5+`** |
  | `APScheduler` automation | `4+` | **`5+`** (Phase 4 is complete — `4+` was unsatisfiable) |
  | `vectorbt` backtesting | `4+` | **Phase 6** |
  | `NautilusTrader` execution | `5+` | **Phase 7** |

  Corrected rows are marked `(was N)` so the change is **auditable, not silent**. No
  row was deleted.

**Added**

- A **supersedes table** naming the Phase 0–4 function each Phase 5+ upgrade replaces
  — measured: `classify_regime_rule_based` (`regime.py:609`) · `realized_vol_simple`
  (`risk.py:429`) · `historical_var`/`parametric_var`/`expected_shortfall`
  (`risk.py:250/369/310`). **CVaR/ES already ships.**
- `D-096` in `docs/DECISIONS.md`, which also records **my own reasoning error**: I had
  read §1.3's deferred list as separate capabilities, grepped §21.3 for the keyword
  `garch`, and wrongly reported GARCH as *"orphaned"*. For anything whose Tier-5 name
  is an *upgrade*, the name exists but does not contain the old keyword. **A keyword
  grep of a work list is not the right instrument for a capability question** — ask
  *"what does this supersede?"*.

**Not resolved here**

- The **three Tier-5 counts still disagree** — §21.3's **23**, the tier table's **20**,
  Phase 2's **13**. This entry fixes *which list governs*, not *how many there are*.

### D-094 — Module 18 #2: `test_stationarity` (Phase 5, Tier 5 = 2/20)

**Added**

- `test_stationarity(series) -> ModelResult` in
  `src/macro_engine/models/econometrics.py`. Runs **both** ADF and KPSS because
  their nulls are **inverted** (ADF's H0 is a unit root, KPSS's is stationarity),
  so they are two pieces of evidence rather than two opinions — and §15.20-F
  requires disagreement to be reported, *"not resolved by picking the convenient
  one"*. Four verdicts, all reachable: `stationary`, `non_stationary`,
  `inconclusive_conflict` (both reject) and `inconclusive_low_power` (neither
  rejects). The two inconclusive kinds stay **distinct**, because "the tests
  disagree" and "the tests are silent" imply opposite next steps.
- Six config leaves, with validators rejecting a non-positive threshold, a size
  outside `(0, 1)`, a nonsense choice, and an `adf_regression` that disagrees with
  `kpss_regression` (mismatched deterministic terms would make their disagreement a
  property of the mismatch rather than of the data).
- **23 tests** and **12 mutations** (sweep now **33/33 killed**).

**Behaviour**

- **KPSS p-values are CLIPPED to `[0.01, 0.10]`** and statsmodels signals it only
  via an `InterpolationWarning`. A returned `0.01` means *at most* 0.01 and `0.10`
  means *at least* 0.10 — **bounds, not point estimates** — so the result discloses
  it whenever it happens. Detected by capturing the warning, not by guessing the
  table's range.
- **Both `adfuller` and `kpss` are called with `result_object=True`.** statsmodels
  has announced the plain tuple's layout changes in 0.16 (or after July 2027), so
  `result[1]` would work today and break on an upgrade with no test failing. The
  switch carries a trap: the tuple's third element is `usedlag`, the object calls it
  `lags`.
- **A rank-deficient ADF design is disclosed**, not swallowed: on a deterministic
  sine statsmodels' internal lag regression is degenerate and still returns a
  number, which is exactly why the consumer must be told.

**Fixed (found by the live check and the sweep, not by the tests)**

- **The live check's own over-claim.** Its first draft required the first
  difference of core CPI to read `stationary`, and the run **failed** — the
  assertion was wrong, not the data: the growth rate itself shifted across the
  window, so the change is not stationary around a constant. The requirement now
  covers only the necessary condition (both levels non-stationary) and **reports**
  the difference as a second finding.
- **Two weak tests, both survivors on the first sweep run.** M28 replaced the
  published `significance_level` with a literal and survived because the config *is*
  0.05 — fixed by **moving the config** and requiring the value *and the verdict* to
  follow. M30 deleted the constant-series guard and survived because statsmodels
  raises its own `Invalid input, x is constant`, which the test's bare-word match
  accepted — the test was passing on **the library's error rather than our refusal**.

**Changed**

- The four *choice* leaves (`adf_regression`, `adf_autolag`, `kpss_regression`,
  `kpss_nlags`) are plain `str`, not `CalibratedValue`. `tests/test_infrastructure.py`
  requires every envelope to be readable as a plain **number** by a property or
  `Settings.scalar()`, and `scalar()` returns `float`. The envelope asks *"is this
  number a fact, a convention, or a placeholder?"* — a question that does not apply
  to a selection. **The invariant was respected, not weakened.**

**Closes D-092's open thread**

`scripts/live_econometrics_check.py` §4 now **diagnoses** the spurious regression
D-092 could only illustrate: core CPI level `non_stationary` (ADF p 0.9991), retail
sales level `non_stationary` (ADF p 0.9987). D-092 asserted the hazard; it is now
measured. **LIVE CHECK PASSED.**

**Gates:** ruff clean · format **247** = mypy **247** · pytest **2872 passed ·
1 skipped · 17 deselected · 0 failed** · reachability baseline **58**, gate 7/7 ·
`sweep_health.py` **43 sweeps, OK** · sweep **33/33 killed**.

### D-093 — post-commit review of `run_regression`: two silent-failure paths

**Fixed**

- **A regressor column named `const` silently destroyed a coefficient.** The
  function prepends an intercept under that name, so a caller column with the same
  label produced a design matrix with two `const` columns, a params Series with a
  duplicated index, and a `{name: value}` comprehension that **kept only the last**
  — reporting **fewer coefficients than were supplied, with no error at all**. Now
  refused, naming the collision.
- **A duplicated column label escaped as a pandas `AttributeError`.** `X[name]`
  returns a DataFrame when the name is duplicated, so the dtype check raised
  `'DataFrame' object has no attribute 'dtype'` — naming neither the problem nor
  the column. Now refused, naming the duplicates. This also removes the same
  latent hazard from the finiteness and constant-column loops.

**Changed**

- `_thresholds_calibrated()` → **`_r_squared_floor_is_calibrated()`**. The old name
  was plural while the helper read exactly one config leaf; a future reader adding
  a second illustrative threshold would have assumed it was already covered.

**Added**

- Two tests pinning the new guards, and two mutations (**M19**, **M20**) so the
  guards are swept — a guard added in response to a review is exactly the kind that
  is never exercised again. The sweep is now **21/21 killed**.

**Verified after the OpenBB service was restored**

- `tools/openbb_reachability.py` → **OK, serving 278 paths** (was exiting 1 in the
  O-111 bound-but-502 state).
- The live check **re-ran and PASSED with identical numbers** (Fisher slope
  +1.0972, R² 0.5688, 823 months) — the evidence that the two new guards change
  nothing for a valid input.
- **3 conditional skips became 3 passes**: chunk 2 went from *354 passed, 3
  skipped* to **357 passed, 0 skipped**. Those assertions had been silently absent
  from every run made while the service was down.

**Note on `sweep_health`'s "LEFTOVER" report.** Renaming the helper made M2's anchor
absent, and the tool reported `MUTATION STILL APPLIED ... this is a LEFTOVER, not a
drifted anchor`. The tree was **not** mutated. The classifier returns "applied"
whenever the anchor is absent and re-applying is a no-op — which is also true when
an anchor has been renamed out of existence. Recorded as an **observation, not a
defect**: the false positive is in the safe direction (it makes you look, and
looking found the genuinely stale anchor). The *wording* is what misleads.

**Gates:** ruff clean · format **247** = mypy **247** · pytest **2849 passed ·
1 skipped · 17 deselected · 0 failed** · reachability baseline **58**, gate 7/7 ·
`sweep_health.py` **43 sweeps, OK**.

### D-092 — Module 18 begins: `run_regression` with a mandatory mechanism gate

**Phase 5 is STARTED** (operator instruction: sequential, one step at a time).
First sub-increment of the Tier-5 deferrals.

**Added**

- `src/macro_engine/models/econometrics.py` — `RegressionResult(ModelResult)` and
  `run_regression(y, X, require_mechanism)`, a statsmodels OLS wrapper. Section
  §15 Module 18's ordering is enforced by the signature: `require_mechanism` is a required
  argument, so a caller that cannot state the mechanism it is testing cannot call
  the function. An intercept is always added and reported under `'const'`.
- `config/settings.yaml` — an `econometrics:` section with four thresholds
  (`mechanism_min_length`, `min_observations`, `low_r_squared_threshold`,
  `vif_concern_threshold`), each wrapped in the `CalibratedValue` envelope so
  `is_calibrated()` can price them, plus a validator rejecting a non-positive
  threshold (which would make the guard that consumes it unfalsifiable).
- `tests/models/test_econometrics.py` — **36 tests**. The golden case is derived
  by exact rational arithmetic (`R² = 625/729`, `adj R² = 68/81`, `beta = {12/5, 5}`),
  and every warning carries a **negative control** so a warning that always fired
  could not pass.
- `scripts/live_econometrics_check.py` — live check on real FRED data.
- `scripts/mutation_econometrics.py` — **19 mutations, 19/19 killed**, with a
  CANARY1 gate. The sweep census moved **42 → 43** in the three places it is
  pinned by design.

**Fixed**

- **Perfect collinearity was not refused.** Detection was a finiteness test on the
  variance inflation factors, but for a singular design
  `variance_inflation_factor` returns a **large FINITE number** and merely warns —
  so the guard passed exactly the case it was written to catch, and solver
  artefacts were returned as coefficients. Replaced with an exact
  `np.linalg.matrix_rank` check; the finiteness branch was deleted rather than kept
  as unreachable defence in depth.
- **A weak test, found by the new sweep.** M15 replaced a `decision_prohibition`
  with a *permission* ("Coefficients may be read as causal effects") and
  **survived**, because the test asserted only that the word `"causal"` appeared.
  The test now asserts the property — every prohibition must contain a negation.

**Behaviour**

- `run_regression` **reports, never repairs**: mismatched length or index,
  non-numeric or bool columns, non-finite values, a constant regressor, too few
  observations, fewer residual dof than parameters, or a rank-deficient design all
  raise. Dropping a row or column would change `n_obs` and therefore the answer.
- The stationarity caveat is a standing `limitations` entry, not a warning: a
  warning that fires on every call is noise. The live check **reproduced the
  hazard** on real data — core-CPI level on retail-sales level gave R² **0.9854**
  and p **0.00e+00** with no mechanism stated.

**Gates:** ruff clean · format **247** = mypy **247** · pytest **2844 passed ·
4 skipped · 17 deselected · 0 failed** · `sweep_health.py` **43 sweeps, 0
failures, OK**. `openbb_reachability.py` exits **1** — the OpenBB service is bound
but answers HTTP 502 (O-111's state), which is environmental and independent of
this change; it accounts for the 3 extra skips.

### D-090 — O-116: a health test that asserted a wall-clock-decaying property

**Fixed**

- `tests/api_layer/test_routes.py::test_health_reports_the_cached_snapshot_age` asserted
  `cached_is_stale is False`, but the `client` fixture seeds the most recent persisted parquet and
  `cached_snapshot_provenance()` re-ages every snapshot to *now* — so the asserted value was a real
  elapsed age. Measured 2026-09-22: the newest snapshot was **25.56 h** old against
  `api.snapshot_max_age_hours` = **24.0**, so the suite went red **purely because a day had passed**.
  A test whose outcome depends on when it runs is a clock, not a test. Fixed by controlling the input
  time, not by weakening the assertion.

**Added**

- `client_with_fresh_snapshot` fixture — re-stamps only `as_of` to a controlled instant (every series,
  curve and field remains the real persisted data; staleness is still computed by the production
  provenance path). The test stays strict.
- `test_health_reports_a_genuinely_stale_snapshot_as_stale` — the **negative control**, without which
  `is False` would be satisfiable by a route that always answers `False` (the D-051 trap). Seeds
  `as_of = now − (max_age + 1 h)`, requires `is True` and `cached_age_hours ≈ max_age + 1`, and derives
  the age **from config** so raising the threshold moves the test with it. Mutation-proven: hardcoding
  `age_exceeds_max: False` fails the control while the fresh-path test still passes.

### D-089 — O-115: the reachability audit was scanning throwaway temp trees as source

**Fixed**

- `tools/reachability_audit.py` — `_candidate_files()` walked `ROOT.rglob("*.py")` and skipped only
  `.venv/`, `build/`, `dist/`, `node_modules/`. Because this project provisions pytest's basetemp
  **inside the repo root** (`--basetemp=.gate_pt`) and hand-run probes leave `.probe/pt*/`, and because
  those trees hold sandbox **copies of real modules**, the audit was reading copies of the project's
  source as though they were the project's source. Measured: **306 candidates, 63 phantom (21 %)** —
  `.probe` 44, `.gate_pt` 11, `.iso_pt` 8 — including **16 copies of four real files**
  (`src/macro_engine/models/inflation_nowcast.py`, `scripts/_sweep_gate.py` 26 611 B,
  `scripts/mutation_inflation_nowcast.py`, `tests/models/test_inflation_nowcast.py`). A copy carries the
  same function names, so **a rename in the real tree could be satisfied by a stale duplicate** — a false
  negative, the one direction this audit must never fail in. The baseline gate passed **58/58 before and
  after**: the copies happen to match today, so wrong and right coincided; the exposure grew silently
  with every gate run. Fixed by `_TEMP_AND_BUILD_PREFIXES` plus a factored `_is_scannable_relative()`
  predicate. Candidate count **306 → 243**; measured unreachable set unchanged at **58**.

**Added**

- `tests/test_reachability_gate.py::TestAuditInternals::test_a_basetemp_tree_inside_the_repo_is_not_scanned_as_source`
  — asserts **both directions**: basetemp paths must be refused, *and* real source plus
  `.github/workflows/quality.yml` must stay scannable (otherwise the exclusion silently blinds the
  audit), *and* the walk has not drifted from the predicate. Mutation-proven: dropping the temp prefixes
  fails the guard naming `.gate_pt/some_test0/module.py`; restored byte-exact.

### D-088 — `vintage_datetime` becomes reachable: ALFRED via a BORROWED credential

**Added**

- `src/macro_engine/data_layer/alfred_client.py` — the **only route in this engine that can answer a
  vintage question**. `fetch_vintage_observations(series_id, as_of, ...)` sends
  `realtime_start == realtime_end == as_of` to `api.stlouisfed.org/fred/series/observations` over `httpx`
  with the pinned `curl/8.0` UA (D-065/D-087.25). `resolve_fred_api_key()` reads the credential **through
  OpenBB's own public accessor** (`openbb_core.app.service.user_service.UserService`), so the engine holds
  **no key of its own** — Option A, honouring §22.2/22.3 instead of waiving it. No `FRED_API_KEY` env var,
  no `.env` entry, no new dependency.
- `snapshot_builder.fetch_field_vintage(...)` — a **sibling** of `fetch_field`, leaving the existing function
  untouched. Stamps `vintage_datetime` from the as-of date requested; deliberately leaves `release_datetime`
  unknown, because that is a different fact with its own source in `publication_dates`.
- `config.AlfredVintage` + `RegistrySeries.vintage_eligible`, with a validator refusing eligibility on a
  curve entry (its legs revise on different schedules) or a non-FRED provider (ALFRED is FRED's archive).
- `tests/data_layer/test_alfred_client.py` (28 guards, 2 **proved to bite** by injected mutants).

**Changed**

- `config/series_registry.yaml` — new `alfred_vintage` block (`enabled: false`, `require_credential: true`);
  `vintage_eligible: true` on `cpi_headline` and `gdp_real`, both with their vintage evidence recorded.
- `docs/OPEN_ISSUES.md` O-6 — status annotated **PARTIALLY RESOLVED**, with an explicit warning that the
  Limitation heading and §21.4 item 14 still stand: ALFRED supplies FRED's revision history, not this
  process's pre-launch history.
- `.gitignore` — `.gate_pt*` added, so a gate run's pinned-basetemp tree cannot repeat the D-087.27
  committed-copies defect.

**Verified live** — CPIAUCSL 2024-01..03 read at vintage 2024-06-01 returns 309.685/311.054/312.230 against
309.698/310.967/312.345 at the latest vintage; a date before first publication returns an **honest empty
set**; GDP 2013Q1 was published as 16535.3 against 16648.189 today. End-to-end through the real registry:
60 points at as-of 2024-01-15, 59 at as-of 2024-06-01, every point stamped with the requested vintage.

**Does not start a phase.** Phase 5 remains not started — this removes a prerequisite rather than beginning it.

**Known, pre-existing, NOT caused by this change:** `tests/api_layer/test_routes.py::test_health_reports_the_cached_snapshot_age`
fails because the newest snapshot on disk is **24.9 h** old against a **24.0 h** threshold. Proved
pre-existing by stashing every D-088 edit and re-running on clean `HEAD` — identical failure. The test is
wall-clock-dependent on data age, not on code.

### D-087.27 - O-104 and O-110(a) CLOSED; O-112(b) implemented; a BROKEN `HEAD` repaired

**Added**

- `scripts/_sweep_gate.describe_dirty_targets()` and its helpers `_git_root` / `_git_dirty_paths` - **O-61's
  still-open remedy**, and the durable form of **O-112(b)**. `sweep_lifecycle` prints it **before** it heals,
  so the warning describes the operator's tree rather than the sidecar this run is about to write. It
  **reports and never refuses**: a legitimate increment *is* a dirty tree, so a veto would forbid the normal
  workflow and the guard would be deleted rather than obeyed.
- `tests/test_openbb_command_inventory.py` (7 guards) - derives the live OpenBB command set from the parsed
  registry plus the source literals, **excludes** blocks marked `enabled: false`, asserts the set is exactly
  four, and forbids the withdrawn "2 of 201" figures outside a supersession-marked sentence.
- `scripts/mutation_command_inventory.py` (6 mutations, **6/6 killed**) - the second sweep over *prose*.
- `tests/test_live_time_bound.py` (10 guards) - asserts the per-test bound exists, clears the **measured**
  worst case, is **not** pinned to `signal` (which would disable it on win32), and that the plugin is
  declared in **both** dependency tables.
- Two O-62 guards: `test_every_sweep_catalogue_resolves_against_the_shipped_source` and
  `test_no_sweep_catalogue_holds_a_leftover_shaped_anchor` - all 42 catalogues, through the same predicate
  the sweeps use, against the shipped text.
- `.gitignore` now covers `.pytest_*/`; the old `.pytest_tmp/` pattern was **narrower than what
  `--basetemp=.pytest_<name>` actually creates**.

**Fixed**

- **`HEAD` WAS RED, independently of this work, and one line caused all of it.**
  `src/macro_engine/models/inflation_nowcast.py` shipped `data_quality_flags_present=False` on the
  insufficient-data branch while **its own docstring and its own test both require `True`**. With `False`
  the two branches returned an identical confidence (`0.7`), so the value stopped distinguishing "no
  result" from "a result" - the only reason the formula is called there instead of the specification's
  literal `0.0`. Consequences, all re-measured with every edit stashed: **2 failing tests**;
  `mutation_inflation_nowcast.py` **could not start at all** (exit 4, anchors M5/M6 absent);
  `tools/sweep_health.py` **exited 1**. Repaired - 26/26 pass, the sweep runs **20/20 killed**, health is
  **green**.
- `_git_dirty_paths` took no `cwd`, so `git status` always answered about the repository containing the
  *process*. The predicate was **structurally incapable of firing for any target outside the project root**
  and returned `[]` for a sandbox file git itself reported as modified - invisible from inside the project,
  which is why the guard is written against a self-built repository.
- Three stray basetemp trees (`.pytest_dur2`, `.pytest_iso`, `.pytest_g1`) had been **committed**, carrying
  sandbox copies of `scripts/mutation_*.py`; `ruff format --check .` walked them and read **251** instead of
  241. Untracked, deleted, and now ignored.
- The `slow` marker's description said "40 mutation sweeps"; it is **42**.

**Changed**

- `pyproject.toml`: `pytest-timeout>=2.4.0` added to **both** `[project.optional-dependencies].dev` and
  `[dependency-groups].dev`; `addopts` gains `--timeout=300 --session-timeout=5400`. **300 s is derived**
  from the measured **162 s** worst offline test (~1.9x), not chosen.
- `.github/workflows/quality-gates.yml`: the `live-data` job repeats `--timeout=300 --session-timeout=3600`
  **explicitly**, because that job selects a different marker expression and would not inherit `addopts`.
- Corrected the OpenBB command count on the live surfaces (**4 of 201**, not 2), and the O-104/O-110/O-112
  status cells; withdrawn figures survive only inside their own retraction.

**Gates re-derived, never carried forward (D-035):** `ruff check` clean - `ruff format --check` **241** =
`mypy --strict` **241** (parity holds) - pytest **2773 passed / 1 skipped / 17 deselected**, where the 5
reported failures are the **sandbox bulk-delete artefact** (all 5 pass in isolation; each fails inside
`safe-delete`'s per-turn counter during *cleanup*) - `tools/sweep_health.py` run **LAST**: 42 sweeps, 0
control-less, **0 leftovers**, 0 shapes, 0 committed mutants, **0 failures, OK**.

**No `src/` behaviour changed except the one-line `inflation_nowcast.py` repair above. Does not start a
phase.**


### D-087.26 - O-103 CLOSED: all 41/41 sweeps carry sidecar protection, in two equivalent forms

**Changed**

- **Corrected a superseded count on four live surfaces** (`HANDOFF.md`, `BUILD_STATE.md`, `CHANGELOG.md`,
  `DECISIONS.md`) and in the O-112 row's open item (a). The sidecar interrupt defence was still described as
  *"adopted by only 2 of 40 sweeps - 38 to go"*; **the propagation is complete.**
- **Re-measured on the tree, not carried forward (D-035):** `41` sweep files; **39** call `sweep_lifecycle()`;
  the other **2** (`mutation_api_layer.py`, `mutation_regime.py`) assemble the same heal → protect → spend
  sequence **by hand** from `restore_from_sidecar` + `record_pristine`, because they must heal **before**
  `check_targets` (lesson 5co). **Union = 41/41, 0 unprotected.**
- **The durable point:** a bare `grep -l "sweep_lifecycle(" scripts/mutation_*.py | wc -l` reads **39** on a
  fully-protected tree and **under-counts by 2**. Cite the **union**, never the wrapper's call count.
- O-104, O-110 and O-112 tagged **`DEFERRED`** (recorded, not implemented, not deleted). **Phase 5 remains
  NOT STARTED.**

**No source behaviour changed** - documentation only, no `src/` edit, no test edit, no suite run.

### D-087.25 - the FRED timeout is the USER-AGENT, not a fingerprint filter (O-105's cause corrected)

**Added**

- **`tools/fred_calendar_diagnosis.py`** - one command that reproduces the whole diagnosis and prints the
  User-Agent matrix, so the finding is checkable rather than a claim in prose. Probes the seven UAs
  `openbb_core`'s `get_user_agent()` can return, plus the empty UA, plus the two working UAs. **Exit codes
  are the contract (O-88): `0` reproduced, `1` NOT reproduced** (FRED's policy changed - re-measure),
  **`2` inconclusive.** Verified in both directions. It is a tool, not a test: it makes live third-party
  calls, and a test that fails when FRED changes its UA policy would be disabled within a week.

**Corrected**

- **The recorded root cause of O-105 was wrong.** It said *"FRED closes the connection for `aiohttp`'s
  TLS/HTTP fingerprint, and OpenBB's FRED provider is built on `aiohttp`"*. Re-measured 2026-09-21:
  `aiohttp` reaches the endpoint in **~0.1 s** and `urllib` in **~0.15 s** - neither is filtered - and the
  provider's URL is byte-identical to this project's own working URL. **The discriminator is the
  `User-Agent`**: `curl/8.0` and `python-httpx` defaults serve (**200 in ~0.2 s**); **every real browser UA
  HANGS**; **the empty UA HANGS**. `get_user_agent()` returns `random.choice` of seven real browser strings
  and applies it unconditionally with **no supported override**, so every OpenBB FRED call hangs.
- **Proved by patch, not argument:** overriding that one function to return `curl/8.0` makes the
  **unmodified** provider return **3 rows in 0.33 s** (bounded, `release_id=10`) and **106 rows in 3.13 s**
  (default window) - same class, same URL, same key, only the UA changed.
- The false claim is corrected where it was asserted as fact: `catalysts.py`'s module docstring and its
  `_REQUEST_HEADERS` note, and `docs/OPENBB_UTILIZATION_AUDIT.md` (two places), plus a D-087.25 addendum on
  the O-105 row. **`nasdaq` also corrected** - it returns **200 with real rows**; it was never unusable,
  and `tradingeconomics`/`fmp` fail on **missing credentials**, a separate reason.

**Notes**

- **Nothing in the project changed behaviourally.** `catalysts.py` pins `curl/8.0` and never used OpenBB's
  client, so it was never affected. **Per the operator's constraint: no switch to Nasdaq, `§16.4`
  untouched, the FRED URL untouched.** The remedy is upstream (OpenBB's UA choice).
- **A SIXTH instance of the "record never re-measured" family** (D-084, D-087.14, D-087.18, D-087.19,
  D-087.23, now this) and the **second in two sessions** where re-measuring a confident record found it
  false. *A wrong root cause in the record is a wrong instruction* - it points the search at TLS libraries
  while the real one-line cause sits untouched.
- **Gates:** ruff clean - `ruff format --check` **238** - `mypy --strict src tests tools scripts` **238**
  (D-035 parity) - pytest **2748 passed / 1 skipped / 0 failed** (EXIT=0) - `sweep_health.py` clean.

### D-087.24 - the FOMC year-boundary 404 no longer reads as a failure (O-114)

**Fixed**

- **`thesis_layer/catalysts.py::_fetch_fed_fomc_meetings`** no longer reports an *expected absence*
  as a *failure*. It asks for `{as_of.year, as_of.year + 1}`, and the request for an unpublished
  year is a **404**, not an empty set (measured live 2026-09-22: published years -> 200;
  `year=2027` / `year=2030` / `year=notayear` -> **404 `{"detail":"Not Found"}`**, deterministic).
  Since `_http_get` calls `raise_for_status()`, that 404 raised `HTTPStatusError` and was logged at
  **WARNING** - `FOMC documents for 2027 failed` - the same shape as the dead-port outage
  (D-087.10/.13). It is now **INFO** (naming the year), while 5xx / transport / timeout / empty body /
  malformed JSON stay **WARNING**. The JSON parse is separated from the fetch, so an empty body is
  reported as *"returned an empty body"* **before** it can reach `json.loads`.

**Added**

- **Three guards** in `tests/thesis_layer/test_catalysts.py`, all asserting on **log level**
  (`caplog`), not on returned data - the meetings were always correct, only the *reporting* was wrong:
  `test_an_unpublished_year_is_an_expected_absence`, `test_a_genuine_fomc_failure_is_still_loud`
  (**the negative control**: a 503 must still warn, or the fix could be satisfied by silencing
  everything) and `test_an_empty_or_malformed_fomc_body_does_not_crash`.

**Notes**

- **The fixture was the reason it survived.** `_fomc_payload_for_year` returned `{"results": []}` for
  an unknown year - the intended behaviour, not the measured one - so the stub could not fail. The
  same false claim was in the docstring (*"returns an empty set rather than an error"*). Both are
  corrected; `_FOMC_2027` now records that the live response was a 404 at capture time.
- **Mutation-proven, four mutants, each killed by the intended guard:** pre-fix handler restored ->
  killed by the absence test with the exact defect message; `== 404` widened to `>= 400` -> killed by
  the **control**; the empty-body guard dropped -> killed by the empty-body test. Restores byte-exact.
- **Gates:** ruff clean - `ruff format --check` **237** - `mypy --strict` **237** (D-035 parity) -
  pytest **2748 passed / 1 skipped / 17 deselected / 0 failed** - `sweep_health.py` **41 sweeps, 0
  leftovers, 0 shapes, 0 committed mutants, 0 failures, OK**.

### D-087.23 - O-111(b) CLOSED: the corrected performance record is ENFORCED, not just written

**Changed**

- **Six surfaces** that justified the snapshot cache with the withdrawn figures now state the honest
  ones: `config/settings.yaml` (`api.memoize_snapshots_value`), `src/macro_engine/config.py`'s
  fallback note, and the module docstrings of `api_layer/reasoning_stream.py`,
  `api_layer/routes_health.py`, `api_layer/snapshot_provider.py`, plus `tests/api_layer/test_routes.py`.
  Each read *"223.6s over the local OpenBB API and 9.5s in-process"*; each now reads **first build
  ~46-81 s, subsequent ~4 s**, names the thermal dependency, and drops the disproved remedy
  (*"batching the ~24 sequential requests"*). **The withdrawn figures survive only inside their own
  retraction**, so the history is kept without keeping the claim.
- **`tests/test_performance_record.py`** (NEW, 18 guards) and **`scripts/mutation_performance_record.py`**
  (NEW, 6 mutations: CANARY1 + M1-M5, **6/6 killed**) - a sweep over **prose**. Every other sweep here
  mutates `src/` and asks whether the suite notices; this one mutates the recorded explanation and asks
  whether the guard notices.

**Notes**

- **D-087.19 claimed this correction had been made.** It had not: the `settings.yaml` note it names was
  fixed for `use_local_api_first`, and the withdrawn pair was live on four other files. **A recorded
  correction with no reader is a claim, not a fix** - a FIFTH instance of that family (D-084, D-087.14,
  D-087.18, D-087.19).
- **Two findings from the sweep, both real.** (1) The guard was **too BROAD** - `warm` occurs **8x** in
  `settings.yaml`, so a whole-file search passed on a mutant that had deleted the warm half *from the
  note under test*; fixed by scoping to the note. That is **O-107's failure in the previously-unrecorded
  direction** (every prior instance was a predicate too narrow). (2) **One of my own mutants was invalid**
  and the guard was right to pass it - M5 deleted only the honest paragraph while the retraction below it
  still said *"compared a COLD run with a WARM one"*; re-anchored on the full note body (lesson 5cm).
- **The canary is verified structural, not assumed:** the first draft injected its error token *inside a
  folded `>` block scalar*, where it is ordinary text and parses fine - an inert canary. The sweep now
  **refuses to run** unless its canary actually breaks the YAML parse.
- **The O-103 sidecar earned its keep again:** a shell detach killed an early run mid-mutation, leaving
  the canary applied in `settings.yaml`; `restore_from_sidecar()` healed it **byte-exactly**.
- **No source behaviour changed.** Every edit is a docstring, a config note, or a new test/script.

**Issues:** closes **O-111(b)** - so **O-111 is now fully closed** ((a) D-087.15/.17, (b) here, (c) D-087.12).

### D-087.22 - O-112(c) closed: the sweep-driver budget is now DERIVED, not typed

**Added**

- **`tools/sweep_health.py`** - `_sweep_budget(declared) = max(300, declared x 75)`, and a
  **`--budgets`** mode that prints the derived budget for all 40 sweeps plus the serial total.
  The formula lives in the tool that already loads every catalogue, so it cannot drift from the
  work it guards and cannot be lost with a throwaway script.

**Notes**

- **Walking back to close O-112(c) found the sharper problem: the driver was a THROWAWAY.**
  `.probe/run_all_sweeps.sh` is gone and nothing in `scripts/` or `tools/` held the formula - so
  the gap was not a missing test around a live mechanism, but **a mechanism with no durable
  home**. It could be re-invented wrongly from scratch, with a round number, exactly as it was
  the first time.
- **Measured on the real 40 sweeps: 1,286 declared mutations.** The largest derived budget is
  **6,525 s** for `mutation_scorecard.py` (87 mutations) - **10.9x** the old flat 600 s. Every
  sweep above **~8 mutations** was over-budget under that timeout, so the D-087.11 kill was the
  **common case, not an outlier**.
- **The constant is measured, not chosen:** 75 s is ~**1.9x** the one recorded per-mutation cost
  (**39.73 s**). **Erring generous is correct** - the failure guarded against is a **kill**,
  whose cost is source corruption on win32; an over-generous budget only delays noticing a hang.
- **A second defect, in the fix's own first pass:** a bare `75` is indistinguishable from an
  invented round number - the exact class of error being fixed. The constant now carries its
  measurement, multiplier rationale, error direction and the issue it closes, with **a guard
  asserting all four survive**.
- **Seven new guards** (38 -> **45 passed / 1 deselected**). **Mutation-proven:**
  `return 600` (the D-087.11 defect verbatim) fails **all five** budget guards and nothing else.
  Full battery: ruff clean, format **234 files**, mypy **234 source files / 0 errors**, pytest
  **2595 passed / 1 skipped / 0 failed**, `sweep_health.py` **40 sweeps / OK**. `234 = 234`.

### D-087.21 - O-72's first half MEASURED (18/40 sweeps have no honesty control), and a real defect D-087.13 introduced

**Added**

- **`tools/sweep_health.py`** - a reported control-coverage line. `_control_markers()` answers a
  question the tool could not previously ask: *does this sweep have ANY way to notice that its
  own baseline broke?* **Measured: 18 of 40 sweeps carry neither mechanism.** Printed as
  **coverage, never as a failure** - the O-29 discipline. Neither mechanism is required by any
  specification, so inventing a requirement would block legitimate work; the value is that the
  gap is visible rather than folklore.
- **`tests/test_sweep_health_leftover_predicate.py`** - **4 new guards** (34 -> **38 passed /
  1 deselected**).

**Fixed**

- **`scripts/live_catalyst_calendar_check.py`** - two call sites referenced
  `catalysts._FOMC_DOCUMENTS_URL`, a symbol **D-087.13 removed** when it replaced the fixed URL
  with the `_fomc_documents_url()` function. The script would have raised **`AttributeError`**
  on its next live run. Both sites now call `_fomc_documents_url()`.
- **`tests/test_sweep_health_leftover_predicate.py:459`** - a `no-any-return` mypy error.

**Notes**

- **A defect in the new check's OWN first version, caught before it shipped:** it recognised only
  a `.killed` read and reported **six false positives** - `inflation_trajectory`,
  `instrument_selection`, `kelly`, `risk_axis`, `thesis_position`, `voltarget` - every one of
  them a sweep declaring its control with **`expect_killed=False`** instead. **O-107's narrow
  predicate again.** Survey of both mechanisms: **22 of 40 use `expect_killed`, 12 use a
  `.killed` read**; the check now accepts **either**.
- **A second defect, in the predicate itself:** mutation-proving showed a mutant removing **both**
  real uses still matched, because `def killed(self) -> bool` - the mechanism's *implementation*
  - remained. **A definition is not a use.** Measured on `mutation_risk_axis.py`: loose predicate
  survived every real use being removed; tightened one moves **18 -> 19** and names the file.
- **The cross-directory lesson:** D-087.13's fix landed in `src/`, and the O-113(c) scan guards
  `src/` only - so a consumer **outside** that scope was left broken by a change **inside** it.
  No sweep could see it (not a mutation), the host scan could not (wrong scope, and a symbol
  rename is not a literal), and the offline suite does not import the script. **`mypy --strict`
  is the only gate with the reach** - verified by re-introducing the symbol (2 errors, exit 1).
  The `src/` scan boundary **stays**, on purpose; the guard for this class is mypy covering all
  four roots.
- **Mutation-proven, 3 mutants, each killed by the right guard.** Full battery: ruff clean,
  format **234 files**, mypy **234 source files / 0 errors**, pytest **2588 passed / 1 skipped /
  0 failed**, `sweep_health.py` **40 sweeps / 0 leftovers / 0 shapes / 0 committed mutants /
  OK**. `234 = 234` (D-035).

### D-087.20 - `sweep_health.py` now gates CI: O-72's enforcement half closed - `sweep_health.py` now gates CI: O-72's enforcement half closed

**Changed**

- **`.github/workflows/quality-gates.yml`** - the `quality` job gained a
  `Sweep health (no left-on-disk or committed mutants)` step, running **before**
  `Test suite (offline)`. A tree carrying a left-on-disk mutant, a stale mutant shape,
  or a committed mutant must now pass the scan before the suite is allowed to certify
  anything.
- **`tests/test_sweep_health_leftover_predicate.py`** - 3 new workflow-reading guards
  (now **34 passed / 1 deselected**): the step exists **exactly once** and runs
  **before** the suite; it carries no `|| true`, no `continue-on-error`, no `|| exit 0`.

**Notes**

- **Same tool, opposite order in the two contexts, on purpose.** Locally the tool must
  run **LAST** - it is a *photograph* of the tree and cannot see a change made after it
  ran (D-086: clean at 08:33, mutant appeared 08:35). In CI it must run **FIRST**,
  because there its job is to **refuse the run**, not to report on one already done.
- **CI-safety verified, not assumed:** stdlib-only imports, no service, and
  `_committed_blob` **returns `None` instead of raising** when git is absent or `HEAD`
  is missing, so a shallow/detached checkout degrades rather than breaks the build.
- **Mutation-proven, 3 mutants, each killed by the right guard:** step removed -> all
  three fail; neutered with `|| true` -> guard 3 only; moved after the suite -> guard 2
  only. The **selectivity** is the evidence the guards do distinct work.
- The workflow-reading helper **concatenates** `name`, `run` and `uses` - because the
  D-087.17 helper matched `name or run or uses` and reported a **present** step as
  **missing** (O-107's narrow predicate, in a new place). The lesson was carried across,
  not re-learned.
- **Does NOT close:** O-72's **first half**. `sweep_health.py` checks the **gates**, not
  the **killings** - it cannot see a sweep whose anchors resolve but whose selection no
  longer kills anything (the **D-051** trap). D-065 fixed that in **one** sweep only.
  Wiring the tool into CI wires in what the tool can *see*, and no more.

### D-087.19 - `use_local_api_first` A/B re-measured: the 23x was thermal, not transport

**Changed**

- **`config/settings.yaml`** - the `use_local_api_first` note corrected. It recorded
  *"local-first 223.6s vs in-process package 9.5s, a ~23x difference"* (2026-09-16). The
  comparison **did not reproduce**: it pitted a **cold** run against a **warm** one, so most
  of the 23x was **warm-up**, not transport. Corrected figures (3 runs each, one session):
  `package_first` **80.66 / 4.70 / 4.21 s**, `local_first` **46.25 / 3.66 / 3.76 s**; warm
  means **4.46 s** vs **3.71 s**, i.e. **1.20x**, not 23x. The default **stays `false`** - on
  that 1.20x warm margin, not on the withdrawn 23x.

**Notes**

- All 6 runs made **28 fetches**, returned `ok`, and routed **exactly as configured** (0
  local-API calls in package mode, 28/28 local in local-first mode), so the A/B is clean.
- **Cold start dominates a build: run 1 is 12.5-18.1x warm in BOTH modes.** This re-frames
  O-111(b) - the "~56 s" figure was itself cold; warm it is ~4 s. The honest operational
  statement is **first build ~46-81 s, subsequent ~4 s**, and a build time quoted without its
  thermal state is *ambiguous* rather than merely imprecise.

### D-087.18 - O-111(b)'s 83 s figure re-measured: right number, wrong mechanism

**Notes**

- **No code changed.** A measurement correction. `build_snapshot("us")` was instrumented:
  **56.31 s total, 28 fetches, 0 through the local API, 53.91 s (95.7%) in fetch time,
  2.41 s build overhead, 1.93 s average per fetch.** The recorded explanation (*"~24
  sequential requests"*) is **disproved by arithmetic on its own numbers** - the local API
  measures **128.4 ms** fresh, so 24 requests is **3.1 s**, ~27x short of 83 s. The build
  in fact uses the **in-process `openbb` package** (`use_local_api_first: false`), never
  HTTP to `:6900`.
- **The time is provider latency:** `gdp_real` alone **9.305 s** (17% of all fetch time in
  one series); top five **22.0 s (41%)**. **So the recorded remedy - batching/parallelising
  the loop - targets 2.41 s of 56 (4%)** and saves ~2.4 s at most. The real levers are
  provider latency, the `use_local_api_first` A/B, and caching (still declined).
- **O-111(b) stays open** (~56 s/healthy build is real); only its explanation is closed.

### D-087.17 - O-111(a) enforced: the reachability probe now gates the CI job

**Changed**

- **`.github/workflows/quality-gates.yml`** - the `live-data` job gains a
  **reachability step before `pytest -m live`**. The job previously went straight into
  the tests, which **skip** the registry-coverage checks when OpenBB is down - so a
  dead endpoint passed **GREEN while deleting assertions** (the O-111 incident one
  level up; **O-62**). The placement is the point: run after the tests, the job has
  already gone green. A non-zero exit **fails the job** - the one place an unserving
  OpenBB instance is a real failure rather than a reason to skip.

**Added**

- **2 guards** in `tests/test_openbb_reachability_probe.py` that read the workflow:
  the probe step exists **exactly once** and precedes `pytest -m live`, and it is not
  neutered (`|| true` / `continue-on-error` / `|| exit 0`). Mutation-proven with three
  mutants, each killed by the guard meant to catch it (step removed -> both; neutered
  -> guard 2 only; reordered -> guard 1 only).

**Notes**

- **A defect in the guard's own first attempt:** the helper returned
  `name or run or uses`, so a step whose *name* differed from its *run* was matched by
  the wrong field. It failed on first run, correctly. Fix: read **all** the step text
  rather than the field expected to be interesting (**O-107**).

### D-087.16 - O-113(c) closed: the hard-coded-host class is scanned, not inspected

**Added**

- **`tests/test_no_hardcoded_service_hosts.py`** - the whole-tree scan O-113(c) asked
  for. **No module may hard-code the host of a service whose base URL `settings`
  exposes** (today: OpenBB). The exclusion is **structural** - `_executable_strings()`
  walks the AST and keeps string constants in code, so docstrings and comments are
  excluded by construction, including the fix's own comments that name `6901` on
  purpose; it also excludes `description=`/`help=`/`doc=` keywords (documentation that
  happens to live in an expression). **9 guards**, three of which are about the
  allowlist itself: no stale entries, every entry states a reason, and the host set is
  **re-derived from live settings** so a config change forces it to be revisited
  (D-087.14 applied to this scan). Mutation-proven: the original O-113 literal is
  killed by 2 guards, and a literal against the *currently configured* port is killed
  by the main scan.

**Notes**

- **Zero remaining defects.** All 9 URL occurrences in `src/` were read and
  classified: 1 allowlisted (`deployment.py`), 5 docstrings/comments, 1 bind default
  in `config.py`, 1 third-party FRED host, 1 the FOMC path already fixed at D-087.13.
  A blanket *"no absolute URLs in `src/`"* rule was **rejected** - a third-party host
  with no configured counterpart creates no contradiction, and a check that fails on
  legitimate code gets disabled. **The scan guards `src/` only**; `scripts/`, `tools/`
  and `tests/` may legitimately name a host.

### D-087.15 - O-111(a) closed: a command that checks the service actually serves

**Added**

- **`tools/openbb_reachability.py`** - reports whether the configured OpenBB URL
  **serves**, separating **unreachable** (nothing answered) from
  **reachable-but-not-serving** (bound, 502 - the O-111 case that cost hours and
  silently skipped three coverage tests). It reads `settings.openbb.base_url`, not a
  literal, and an AST guard forbids a port in its executable code. Exit codes:
  `0` serving, `1` not serving, `2` probe could not run.
- **11 offline guards** in `tests/test_openbb_reachability_probe.py` (transport
  monkeypatched), covering both directions plus the reachable-but-empty and
  non-JSON-200 cases.

**Changed**

- **`tests/data_layer/test_registry_endpoint_coverage.py`** - the flat *"service not
  reachable"* skip became `_require_service()`, which names the O-62 cost (*this skip
  deletes assertions without failing anything*) and points at the probe. The skip is
  still a skip - an external dependency is not a repo regression - but it is no longer
  **silent**.
- **HANDOFF Step 0** now runs the probe first when a session touches live data.

**Verified**

- Live: `:6900` -> **200 / 278 paths / SERVES**; `:6901` -> **502 / 0 paths / does NOT
  serve** - and **both are reachable**, which is the whole finding.
- Mutation-proven: collapsing `serves` into `reachable` fails **4** guards; a
  hard-coded host fails the AST guard. Restored clean.
- Gates: ruff clean, format **233** = `mypy --strict` **69 source files**, pytest
  **2570 passed / 1 skipped / 0 failed** in 118 s, `sweep_health.py` **OK**.

**Issues:** closes **O-111(a)**. O-111(b) (the 83 s snapshot) stays open; O-113(c) (a
whole-tree scan for hard-coded hosts) stays open.

### D-087.14 - the O-109 guard was broken by its own cure

**Found by running the full suite after the repairs were committed.** No source
behaviour changed.

**Fixed**

- **`test_a_committed_mutant_is_detected_and_the_shipped_tree_is_not` failed on
  success.** With a clean `HEAD` - the *entire point* of O-109's remedy - the
  committed-mutant scan correctly returns `[]`, and the guard's opening
  `assert findings` failed. This was the **third** re-pointing of the same test:
  v1 hard-coded `5d4c1da` (history moved past it), v2 selected its control from
  the **live** scan (so it required `HEAD` to be *currently dirty*), v3 pins it to
  **frozen history**.
- **`_committed_blob(rel, *, rev="HEAD")`** gained an optional `rev` parameter
  (production default unchanged) so the positive control can read a specific,
  immutable commit.
- The **positive** half now reads **`81fd65a`**, verified to carry both mutants
  (`convergence.py:330` = `elif False:  # CONFLICTED removed`;
  `reasoning_stream.py:287` = `"convergence=HIGH",  # MUTANT: ...`).
- The **negative** half is now its own test,
  `test_the_committed_mutant_scan_reports_nothing_on_a_clean_head`, because a clean
  tree is the steady state and must be seen to pass.

**Verified**

- **Mutation-proven:** making `_committed_blob` ignore `rev` and always read `HEAD`
  kills the positive half.
- Gates: ruff clean, format **231** = `mypy --strict` **69** (D-035 parity), full
  suite **2559 passed / 1 skipped / 0 failed** in 128 s,
  `sweep_health.py` **40 sweeps / 0 leftovers / 0 shapes / 0 committed / OK**.

**The rule:** *a test whose fixture is "whatever the system currently reports" is not
a test of the system - it is a restatement of it. Ground truth must be external and
frozen.*

### D-087.12 / D-087.13 - the dead port was hard-coded, and the TEST agreed with the bug

**Two entries, both triggered by questions rather than failing gates.** No Phase 5
work. `AGENTS.md` unchanged.

**Fixed**

- **`catalysts.py` hard-coded the DEAD OpenBB port as the FOMC documents URL**
  (O-113). `_FOMC_DOCUMENTS_URL` held the absolute
  `http://127.0.0.1:6901/api/v1/economy/fomc_documents`, and `:6901` answers
  **502 on every data route** - proved in one run: the literal raises
  `HTTPStatusError: 502 Bad Gateway`, while `get_settings().openbb.base_url`
  returns **200 with 34 rows / 5,358 bytes**. So the FOMC catalyst could **never**
  succeed, on any call, while the thesis still built with a FRED-only calendar and
  **nothing raised**. Replaced with `_FOMC_DOCUMENTS_PATH` plus
  `_fomc_documents_url(base=None)`, which resolves the host from config **at call
  time**; both call sites derive from it.
- **The test was why it survived.** `tests/thesis_layer/test_catalysts.py` defined
  `_FOMC_HOST` as a **copy of the implementation's literal**, so the stub routed
  the 502-producing URL to the happy path and the suite **could not fail** - worse
  than no test, because it converts an outage into a green check. It now
  **derives** the host from `catalysts._fomc_documents_url()`, making agreement
  structural rather than coincidental.
- **A second instance in `deployment.py`.** `OPENBB_API_URL`'s `yaml_default` was
  `:6901` while `settings.yaml` declares `:6900` - **two defaults for one
  setting**, and the operational one handed a clean checkout the broken host.
  That module is deliberately dependency-free, so the value is now the named
  constant `_OPENBB_DEFAULT_BASE_URL`, **pinned to config by a test**.
- Two docstring examples (`openbb_client.py`, `contracts.py`) corrected.

**Added**

- `test_the_fomc_fetch_derives_its_host_from_config` - asserts the URL is a
  function of the configured base, that a rebase is honoured, and that no
  absolute-URL constant survives.
- `test_the_two_openbb_defaults_agree` and
  `test_the_openbb_fallback_port_is_not_the_known_dead_one` in
  `tests/test_infrastructure.py`.

**Verified**

- **Mutation-proven both directions:** dead port back in the deployment default ->
  killed by both guards; helper ignoring config -> killed by the new guard with a
  message naming the defect. Restores verified: no `MUTANT` text in `src/`.
- Gates: `ruff check` clean, `ruff format --check` **231** = `mypy --strict` **69
  source files** (D-035 parity), catalysts + infrastructure **86 passed / 1
  deselected**.

**Also recorded (no source change)**

- **D-087.12 - D-084's vintage conclusion RE-MEASURED against `:6900`** (O-111(c))
  and it **survives**: `fred_search` returns **200**, **278 paths / 0 `vintage`**
  identical, `realtime_*` absorbed, marker-not-selector re-confirmed. **Method
  correction:** the recorded A/B compared the whole JSON envelope and now returns
  `False` because transport metadata differs per call (**61 leaf keys, exactly 3
  differ**) - compare `["results"]`, never the envelope.

**Issues:** opens **O-113**; closes **O-111(c)**. **O-111(a) remains open and is the
root** - nothing still checks that the configured URL **serves**.

### D-087.11 - the FULL 40-sweep run completed: four more defects, three under green gates

**A complete pass over all 40 mutation sweeps (1,286 mutations) was run for the
first time. It found four defects and the committed-mutant count doubled to 2.**
No Phase 5 work. `AGENTS.md` unchanged.

**Fixed**

- **`M8.3` was a SECOND committed mutant, live and reachable** - O-109's class,
  second instance. On the `if fired:` stand-down path, `reasoning_stream.py`
  emitted the **hardcoded** `"convergence=HIGH"` instead of
  `f"convergence={thesis.convergence_classification.value}"`, so **every
  stood-down thesis** reported a fabricated `HIGH` label. The suite **fails** on
  it (`assert 'NO_SIGNAL' in 'convergence=HIGH'`), so it was always killable - it
  was simply **committed**, which is why no dirty-relative check saw it.
  Restored, **RED -> GREEN proved**.
- **`M3.2` was committed too** (`elif False:  # CONFLICTED removed`, draining the
  `CONFLICTED` verdict out of `classify_convergence`) and is restored in the
  working tree. Both mutants remain in `HEAD` (`81fd65a`) until the operator
  commits; `sweep_health.py` reports **2 by design** and **0 after the commit**.
- **`_is_mutant_shape` was blind to `elif`** - `startswith(("if False:",
  "if True:"))` does not match **`elif False:`**, and `mutation_convergence.py`
  writes `M3.2` in exactly that form. **Two gates inherited the gap** (the O-83
  whole-tree scan and the O-109 committed scan), so a committed `elif` mutant was
  invisible to both. Widened; guarded in both directions.
- **The O-109 committed scan shipped with O-108's predicate in it.**
  `old not in committed and new in committed` is the **same trivially-satisfiable
  test** one scope over, and **1 of its 2 findings was a false positive**
  (`M8.3`). Replaced with a **mutant-shape witness at the edit site**, which needs
  no pristine reference and cannot be satisfied by an ordinary line.
- **O-112 - the full-sweep driver sized its timeout to a round number.** A flat
  `timeout 600` against a sweep whose measured floor is **~1,700 s** (42
  mutations x ~40 s) means it was **guaranteed** to be killed, and on win32 a
  killed sweep leaves mutants on disk. The budget now derives from the mutation
  count and **`rc=124` is a hard stop**, not an ordinary row. Re-run alone,
  `mutation_api_layer` **CERTIFIES at 42/42 applied, 41 killed, 1 survivor**
  (`M10.1`, the honesty control) in **1,066 s**.

**Guarded**

- `tests/test_sweep_health_leftover_predicate.py` gains **16** tests (30 total):
  every mutant branch shape including `elif`, the refusal of ordinary neighbour
  lines, and the shape-witness requirement. The committed-mutant control is
  selected from the **live** scan rather than hard-coded, because it was already
  stale once when `HEAD` advanced.

**Found by the run, recovered by the sidecar**

- Two aborted attempts left **8 `.sweepbackup` sidecars**; **one differed from its
  source** - a live mutant in `routes_query.py` (`" ".join(...split())` where the
  `isalnum()` sanitizer belongs), restored **byte-exactly** without any catalogue
  match. The D-086 sidecar mechanism is adopted by only **2 of 40** sweeps (O-103)
  and this is the first time it actually had to heal a file.
  *(superseded: **O-103 CLOSED, D-087.26 — 41/41 sweeps protected**.)*

**Gates:** `ruff check` clean - `format` **231** = `mypy --strict` **231** (D-035)
- `pytest -q` **2555 passed / 1 skipped / 0 failed** in **109.9 s** (was 2539)
- `sweep_health.py` **40 sweeps, 0 leftovers, 0 shapes on disk, 2 committed,
  2 failures** - `mutation_api_layer` **42/42 -> 41 killed - CERTIFIES** -
  `mutation_lei_proxy` **36/36 - CERTIFIES** - the other 38 sweeps **all CERTIFY**.

### D-087 - the leftover detector was a false-positive machine, and a mutant had been COMMITTED

**Two defects, each hiding the other. Both fixed and mutation-proven.** No Phase 5
work. `AGENTS.md` unchanged.

**Fixed**

- **O-108 - a false-positive detector.** `scripts/_sweep_gate.py` and
  `tools/sweep_health.py` decided *"is this mutation applied, or is the anchor
  merely absent?"* with `old not in text and new in text`. A mutation whose
  replacement text is **also a legitimately present string** - `M7b`'s
  `lead_direction = "broad_based_advance"` is the neighbouring branch's own
  assignment - makes that predicate fire on a **pristine** file. Measured against
  ground truth (`git show HEAD:<path>`) over the 622 reachable catalogue entries:
  **52 false positives, 0 misses**. Replaced with a **count-stable** predicate
  (`applied ⟺ old absent AND re-applying does not raise new's count`), measured
  **0 / 0**. Three other candidates were scored before this one was adopted; the
  first attempt passed the reported case but failed **9** real entries.

- **O-109 - a mutant was COMMITTED.** `models/lei_proxy.py` carried
  `else: lead_direction = "broad_based_advance"` where `"mixed"` belongs - and it
  was in **`HEAD` (`5d4c1da`)**, not merely in the working tree. Every prior
  anti-mutant check compared the working tree against the catalogues; **none could
  see a mutant that *is* the baseline**, including `git diff HEAD`. Restored, and
  proven by the test that demands the composite agree (`3` tests fail with the
  mutant, pass without).

**Added**

- `_committed_blob()` / `_committed_mutant_scan()` in `tools/sweep_health.py` -
  compares every catalogue entry against `git show HEAD:<target>` and reports a
  committed mutant as a failure. New summary line: `committed mutants (O-109, vs
  HEAD)`.
- `tests/test_sweep_health_leftover_predicate.py` - **15** guards: 4 behavioural
  (both directions, incl. the exact `M7b` shape), 3 structural (both copies exist,
  not a bare membership test, the two copies agree on the real catalogue), 2 for
  the committed-mutant scan. RED on the old predicate (**2 failed**) → GREEN on the
  new (**14 fast guards passed**, plus 1 `slow` exhaustive-catalogue guard).

**Removed**

- `docs/MODULE_MAPPING.md` carried the **D-082 addendum section duplicated
  verbatim** (a 73-line body, twice, the second running to EOF). Second copy
  removed after the two bodies were verified byte-identical. 76 deletions, 0
  additions.

**Fixed (test configuration and the data-service port)**

- **D-087.10 — the engine was pointed at a dead OpenBB port.** `settings.yaml` carried
  `local_api_base_url = "http://127.0.0.1:6901"`, which is **bound but answers 502 Bad
  Gateway**; the real service is **`:6900`** (200 in 0.12 s). **This was the entire
  cause of the hour-long runs** — a snapshot build retried **42 series × 3 attempts**
  against the 502 and exceeded **400 s**, where the same build on `:6900` finishes in
  **83.2 s with 24/24 succeeded**. **No `429` anywhere: rate limiting was never the
  cause.** It had also been **silently deleting coverage** — three
  `test_registry_endpoint_coverage.py` checks skipped with *"service not reachable"*.
  **One config value; no code changed.** Default suite went **2536 → 2539 passed,
  4 → 1 skipped**. Lesson 5cq: *a port that is BOUND is not a port that SERVES.*
  **Opens O-111.**

- **D-087.6 — the default test run no longer includes live-network tests.** `addopts`
  gained **`-m 'not live and not slow'`**. The `live` marker was always documented as
  *"excluded from default CI runs"* but **nothing enforced it**, so a plain
  `uv run pytest` fanned out ~21 live network calls with 3 retries x 15 s timeout
  each and could sit on a **single test** for **40+ minutes**. A default run is now
  **~113 s**. Live tests are explicit (`-m live`). **Opens O-110** (no per-test
  timeout exists; the live tests are the project's measurement instrument and must
  now be run deliberately).

**Gates** (re-derived by execution, not carried forward - O-88): `ruff check` clean,
`ruff format --check` **231** = `mypy --strict` **231** (D-035 parity; the 230 → 231
step is this increment's new test file). `pytest` (**default**) **2539 passed /
1 skipped / 0 failed** in **112.8 s**; `-m slow` **1 passed** in **230.8 s**;
`scripts/live_api_check.py` **PASSES end to end**; reachability audit **PASS**
(baseline 58 = measured 58).

**Not committed** - the tree is left dirty with the fix; the user pushes.

### D-083 - external mechanics validation: the research the brief asked for, finally done

**No code changed. A documentation deliverable.** No Phase 5 work. `AGENTS.md` unchanged.

The Phase 0-4 audit brief asked for *"web research on macro trading logic mechanics,
flow mechanics, and execution patterns up to Phase 4 to validate expected behavior."*
It had been carried as outstanding across several sessions. **`docs/MECHANICS_VALIDATION.md`**
now records it - deliberately narrow, covering the four mechanics where a
plausible-looking implementation can be *quietly* wrong.

**Checked against published sources:**

| mechanic | source | verdict |
| --- | --- | --- |
| Taylor rule coefficients | Taylor (1993) / balanced approach | **AGREE** - `0.5`/`0.5` original; balanced-approach gap `1.0` (the 2x weight) |
| Taylor principle | *"real rates must rise when inflation rises"* | **AGREE** - recorded on the coefficient itself |
| unobservable `r*`, `pi*` | *"an error of 0.5% shifts the recommendation by the same amount"* | **AGREE** - `uncalibrated_illustrative` vs `institutional_fact` |
| output-gap revision hazard | Orphanides & van Norden (1999) | **AGREE** - disclosure names the gap as *revised, model-dependent* |
| breakeven = compensation | TIPS mechanics | **AGREE** - inflation risk premium **and** liquidity premium disclosed |
| breakeven maturity matching | must be same tenor | **AGREE** - enforced structurally in the orchestrator |
| vintage / look-ahead bias | ALFRED vs FRED | **AGREE, exceeds source** |

**The strongest finding - the code refuses a decoy.** `publication_dates.py` records
that FRED's `realtime_start`/`realtime_end` *look like* ALFRED vintage bounds but **both
equal TODAY for every series**; the module **A/B tested** this and found the parameter
silently ignored (*"the two responses differed only in request timestamp/duration
metadata"*). It therefore declines to populate `vintage_datetime` at all rather than
substitute a plausible wrong value - Section 6's prohibition applied at the exact field
where the temptation is strongest.

**The one accepted gap - structural, not a defect.** Orphanides & van Norden find the
**dominant** source of output-gap error is *"the pervasive unreliability of
end-of-sample estimates of the trend"* - **not** data revision. This system consumes a
published `gdp_potential`, so that cause is **inherited, disclosed, and not mitigated**.
The Phase 5 Kalman-filter item already recorded in `config/settings.yaml` is its remedy.
**A system that fixed only vintage handling and believed the gap was then trustworthy
would have fixed the smaller half of the problem.**

**No code changed as a result of this research** - the first research pass in this audit
to come back clean.


### D-082 - the interrupt-restore handler cannot fire on Windows; a sidecar can

**No production source changed. `src/` is untouched.** No Phase 5 work.
`AGENTS.md` unchanged.

**Retracted - a safety mechanism was credited before it was tested.** After
D-081, the remedy for "a killed sweep leaves mutated source" was assumed to be a
signal handler (`mutation_api_layer.py` already had one). A shared
`install_signal_restore()` was written into `scripts/_sweep_gate.py` and wired
into `mutation_regime.py`, and the record described it as the defence.

**Measured - it never executes on this platform.** Three probes: self-`SIGTERM`
left the file `MUTATED` with the handler body never entered; self-`SIGINT` exited
**2** (`KeyboardInterrupt`), not the handler's `SystemExit(130)`; and a
trace-wrapper probe printed **no trace line at all** while `signal.getsignal`
confirmed the handler installed and `_PENDING[0]` confirmed the payload armed.
On `win32`, `os.kill(pid, SIGTERM)` is `TerminateProcess`; no Python-level
handler runs. **`mutation_api_layer.py`'s `_restore_in_flight` (credited at
D-057/D-062) is inert here** - kept, because it is correct on POSIX, but no
longer counted as protection on Windows.

**Fixed - with a filesystem-based recovery.** `_sweep_gate.record_pristine()`
writes each target's pristine text to a `<name>.sweepbackup` sidecar *before*
the first mutation; `restore_from_sidecar()` restores from it on the next run and
deletes it on success. It needs nothing but the filesystem, so it survives any
kill on any platform, and it is **strictly stronger than
`repair_leftover_mutations`**, which can only heal a mutation the catalogue
still recognises.

Verified end to end: kill with `| head -6` -> `regime.py` left mutated **and both
sidecars written** -> next run prints `RESTORED regime.py from sidecar (previous
run was killed)` and `check_targets: 40 mutations, 0 problem(s)` ->
`REGIME.PY RESTORED`, sidecars `(none - consumed)`.

**Found in the same pass - the health tool could not load its own sweeps.**
Wiring 14 sweeps to `from _sweep_gate import ...` made `sweep_health.py` report
all 14 as `IMPORT FAILED - No module named '_sweep_gate'`: they work standalone
(the script directory is on `sys.path`) but not under `spec_from_file_location`.
That is O-62 exactly - *a sweep that cannot run is indistinguishable from a sweep
nobody ran* - caused by the change meant to strengthen them. **Fixed** in
`_load` by prepending the sweep's parent to `sys.path` for the duration of the
load; `failures: 0` afterwards.

**Also closed - O-29's wiring half.** All 14 previously-ungated sweeps now own a
`check_targets` gate. Measured: `sweeps with NO sweep-owned gate: 0`,
`TOTAL problems: 0` across the 14.

**Open (O-103):** the sidecar recovery is adopted by **one** sweep of 40;
`install_signal_restore()` should be gated on `sys.platform` with a printed
notice, or removed.
*(superseded: **O-103 CLOSED, D-087.26 — 41/41 sweeps protected, 39 via
`sweep_lifecycle()` and 2 via the hand-assembled primitives**.)*


### D-080 - the last do-not-fix entry was not a limitation either, and it hid a real test gap

**No production source changed. The only source-tree edit is a test file.**
No Phase 5 work. `AGENTS.md` unchanged.

**Retracted - `mutation_lei_proxy.py` M8e is KILLED (the third retraction of the
same carried claim).** It had been recorded for two sessions as *"target ABSENT -
do not fix, by design"*. Run in full, the anchor resolves byte-for-byte against
`config.py:965` and the killing test reads `RegistrySeries.model_fields[...].default`
directly. **The do-not-fix list has now been wrong 3 times out of 3** (`CX5`,
`M8d`, `M8e`). The rule recorded: a `target ABSENT` means **the gate is OFF** and
certifies nothing, and a do-not-fix label is an **unverified claim requiring
re-derivation**, never a risk acceptance.

**Found - a real surviving mutant, `M8g` (O-101).** Deleting `and not
forward_looking` from the `SAME_DAY_PUBLICATION_AHEAD_OF_CLOCK` guard
(`validation.py:314`) **survived the entire suite**. The test asserting that
property feeds a point dated **2030** against a tolerance of **1**, so the point
lands in `future_dates` - **not** `tolerated_future_dates` - and **the guard is
never reached**. *A test can assert the right property and still be unable to
reach the branch that enforces it* (lesson **5ce**; O-29's mis-target class).

**What it hid:** a **projection** series carrying a tolerated point would emit
`SAME_DAY_PUBLICATION_AHEAD_OF_CLOCK`, whose own text declares the points
**"realised data"** - false about the object it is attached to, at INFO severity,
with no `FORWARD_LOOKING_HORIZON` line to contradict it.

**Fixed** by adding `test_the_tolerance_is_not_applied_to_a_tolerated_forward_looking_point`
(lead **1**, tolerance **3** - the only shape that populates
`tolerated_future_dates` - plus a **positive control** so the absence assertion
cannot be vacuous). **RED->GREEN verified in both directions**, and the source was
`git diff --quiet` clean afterwards, proving the repair is the test and not a
source edit. The sweep now certifies **36/36 killed**.

**Also measured and recorded, not asserted away:** that cell's behaviour is
**SILENCE** - no finding at all - because `FORWARD_LOOKING_HORIZON` keys on
`future_dates` and the same-day path is correctly suppressed. The cell is
**composite**: two independently-correct branches that jointly suppress, which is
why neither branch's own test notices. **Scope is LATENT, not a live leak** - only
`sofr`/`iorb` declare a non-zero tolerance and both are `forward_looking=False`,
so the cell is unreachable today. The new test **pins the silence** so that arming
it later fails loudly with a pointer to O-101.

**Gates:** ruff + format + `mypy --strict` clean, **all at 224** (D-035) -
`pytest -q` **2432 passed, 1 skipped, 0 failed** - `sweep_health.py` **40 sweeps,
0 failures** - `mutation_lei_proxy.py` **36/36**.


### D-075 / D-078 - Phase 0-4 audit: two sweeps that had stopped gating, and `nan` as a readable value

**No Phase 5 work. No architecture change. `AGENTS.md` unchanged.** An audit of
the shipped Phase 0-4 build, under the standing rule that **missing data must
never become `0`, `False`, neutral, unchanged, empty-but-successful or an
invented default.**

**Two findings, both active, both fixed with RED->GREEN tests.**

**Fixed - two mutation sweeps had silently stopped gating (D-075)**

- **`mutation_drawdown.py` CX5** anchored `raw = self.drawdown_thresholds.get("tiers")`;
  the live accessor reads `get("tiers", [])` - a defensive default added after
  the anchor was written. **0 occurrences**, so CX5 could not be applied and its
  mutants were invisible.
- **`mutation_regime.py` M8d** pinned two lines as **adjacent**; a four-line
  comment block was later inserted between them. **0 occurrences.**
- Neither mutation surface had changed - both were **stale anchors**, not lost
  tests. `tools/sweep_health.py` went from **2 failures to 0**: 40 sweeps,
  0 leftovers, 0 mutant shapes, **0 failures**. The previously documented
  "2 INHERITED failures, do-not-fix (M8d, M8e)" was **stale in both directions**
  (measured: `CX5` + `M8d`; `M8e` never failed; neither was a genuine
  do-not-fix limitation).

**Fixed - `nan` was a READABLE value in all four verdict-producing paths (D-078)**

- **`classify_regime_rule_based(output_gap=nan)`** returned
  `growth_axis='above_trend'`, `state='reflation'` - a **bullish regime invented
  from an absent headline input**, because `_growth_axis` is a fallthrough and
  `nan` satisfies neither threshold test, so it lands in the most expansionary
  bucket.
- **`inflation_trend_3m=nan`** returned `'flat'` - a missing reading published
  as a measurement.
- **`taylor_rule(pi_current=nan)`** returned `value=nan`, which every "is the
  prescribed rate above actual?" test reads as `False` - *"the Fed is not behind
  the curve"*, from a value it could not compute.
- **`MarketPricingGap(raw_gap=nan)`** returned **`direction='aligned'`,
  `is_meaningful=False`** - *"the model and the market agree, insignificantly"*:
  **a silent NO-TRADE manufactured from absent data**, in the one class the
  whole pipeline exists to build a *disagreement* from.
- **`_direction_for(nan, +1)`** returned **`'contradicts'`** - an active
  disagreement, and the exact outcome `test_signals.py`'s documented defects 1
  and 2 exist to prevent, arriving **through the readability gate those fixes
  sit behind**, because `nan` **is** a `float` instance.

**The fix shape: guard the input DOMAIN, not the range.** A `model_validator` on
`RegimeInputs` (on the object, so `regime_tension` and the trilemma check are
covered too) - a shared `_FiniteInputs` base for `TaylorRuleInputs` and
`FirstDifferenceInputs` - `allow_inf_nan=False` on `MarketPricingGap`'s four
numeric fields - and `isfinite` in `_signed_scalar`, so a non-finite signal is
**reported in the `unreadable` census** rather than silently neutralised.

**Also recorded:** three code fixes already on disk cited `(D-076)` and
`(D-077)` while **neither decision entry existed in any record file**; both are
now written at the numbers their docstrings asserted.

**Tests:** +43 this session (36 in the new
`tests/models/test_non_finite_inputs.py`, 11 in `tests/thesis_layer/test_signals.py`),
each parametrized over `nan`/`+inf`/`-inf` with a "finite input unchanged"
control.

**Fixed - a live check tested TODAY'S MARKET and called it the WIRING (D-079)**

- **`scripts/live_labor_check.py`** asserted the credit-spread verdicts *differ*
  across the three `default_rate_trend` values, to prove the input reaches the
  output. On 2026-09-20 the HY OAS **tightened**, and
  `credit_spread_attribution` tests `widening_observed` **first** - so all three
  returned `NO_WIDENING` legitimately, before the trend was read at all. The
  check went red while the model was correct.
- **Fixed** by pinning the wiring claim on a **widening row** (one basis point)
  and printing the live row separately; the check now also asserts the *specific*
  verdict (`rising -> FUNDAMENTAL`), so it is stronger, not weaker.

**Live validation: 28/28.** All `scripts/live_*.py` checks pass, exit 0, against
the live OpenBB deployment on `:6901` with real market data.

**Gates:** `ruff check` clean - `ruff format --check` **224** - `mypy --strict`
**224 source files, no issues** (224 = 224, D-035) - `pytest -q` **2432 passed,
1 skipped, 0 failed** - `sweep_health.py` **0 failures**.

### D-074 - Phase 0-4 final audit: four defects every existing gate could not see

**No Phase 5 work. No architecture change. `AGENTS.md` unchanged.** An external
audit directive asked for a defect hunt across code, logic, economic reasoning,
missing-data handling, PIT discipline, source identity and test assumptions,
under one binding rule: **never convert missing data into `0`, `False`, neutral,
unchanged, empty-but-successful or an invented default.**

**Four defects found, all fixed, each with a RED->GREEN regression test. The
common thread: every one was a MISSING-DATA conversion, and every one was
invisible to the existing gates.**

**Fixed**

- **Non-finite values passed every gate.** `dropna()` removes nulls, not
  `inf`; Pydantic's `float` accepts `nan`/`inf` by default; and the
  plausibility check is **made of comparisons, and every comparison is `False`
  for `NaN`** - so a poisoned series reported **CLEAN**. `+/-inf` was caught
  only when the series carried a `plausible_range`, and **2 of 45 registered
  series carry none**. Fixed at four layers: normalisation drops non-finite
  rows; `ObservationPoint.value` is `allow_inf_nan=False`;
  `MacroDataSnapshot.assert_finite()` runs before persistence; and a
  `NON_FINITE_VALUE` `Severity.ERROR` is now the **first** validation check,
  because every check after it is a comparison.
- **One `NaN` FCI component silently inverted the composite.**
  `sum()` propagates `NaN`; `NaN > 0.0` is `False`; the model then reported
  *"looser than average"* **from absent data**. `std = inf` produced
  `z_score == 0.0`, an invented "exactly average". Fixed in `FCIComponent`
  (`allow_inf_nan=False`, `gt=0.0` on `std`) and at the point of use in
  `compute_fci` (a component may arrive via `model_construct` or a cache and
  never face field validation).
- **Provenance recorded the preference, not the path.** On a cross-path
  fallback the frame was labelled `openbb:http://127.0.0.1:6901` although the
  in-process package served it - a **fabricated transport fact**. Fixed with a
  **mandatory keyword-only** `served_by` on `_normalize`, so the type system
  refuses a call that does not say which path answered.
- **Config pointed at `:6900`** against an explicit "do not use `6900`". Both
  ports served identical live instances - an ambiguity, not an outage, which is
  why nothing had failed. Repinned `config/settings.yaml`,
  `src/macro_engine/deployment.py` and the client docstring to `:6901`.

**Documented (no code change - the code was already correct)**

- **The prescribed vintage route does not exist on this deployment.** Measured
  five ways: 278 live OpenAPI operations, **zero** with `vintage` in any path;
  **zero** with any `realtime*` parameter; sending `realtime_start`/
  `realtime_end` anyway returns **HTTP 200, `warnings: null`, and 1947 data -
  the parameters are silently dropped**; the in-process SDK has no
  `obb.economy.fred` namespace; ALFRED returns 404 and `fredgraph.csv?
  vintage_date=` ignores the parameter. `config.py`, `publication_dates.py`
  and `schemas.py` already document the absence correctly. Evidence appended
  to **O-6**. Also confirmed the engine requires **no `FRED_API_KEY` of its
  own** - it reaches FRED only through OpenBB.

**Verified correct, deliberately unchanged**

`datetime.utcnow()` appears **only in docstrings** (production uses the
timezone-aware `utc_now()`); `raw_kelly = ev / 100` is **not implemented
anywhere** and a test forbids it; `SnapshotStoreEmptyError` distinguishes an
absent store from an empty snapshot; `validate_snapshot` is genuinely
registry-driven; `marginal_risk_contributions` refuses on `variance <= 0`;
Phase 4+ stubs raise rather than returning neutral values; no hidden numeric
defaults, hardcoded scenario probabilities or placeholder arithmetic in
production paths.

**Measured after the fixes**

```
ruff check src tests tools scripts  ->  All checks passed!
ruff format --check                 ->  221 files already formatted
mypy --strict src tests tools scripts -> Success: no issues found in 221 source files
pytest -q                           ->  2358 passed, 1 skipped, 0 failed   (+29 tests)
tools/sweep_health.py               ->  40 sweeps, 0 leftovers, 2 INHERITED failures (unchanged)
grep "if False://|if True:"          ->  nothing (required)
live :6901 snapshot                 ->  22 fields, is_complete=True, assert_finite() PASS
live :6901 thesis                   ->  WATCH / NO_SIGNAL / instrument NONE  (NO TRADE, correct)
```

The live thesis correctly returned **NO TRADE** on real data: gap `0.26` inside
the policy rules' own dispersion `0.86`, so Q6 stands the trade down. That is
the audit's intended result - *real data -> correct calculation -> correct
economic interpretation -> traceable reasoning -> honest uncertainty* -
**including when the honest answer is to do nothing.**

### D-073 - A demotion bound that no input could reach, and a SKIP that hid it

**Phase 4 - COMPLETE (4 of 4 items).** The §17.4 risk-budget hook. `build_us_macro_thesis`
gained `risk_budget_target: RiskBudgetTarget | None = None`, and a new
`_apply_risk_axis(thesis, target)` in `src/macro_engine/thesis_layer/builder.py`
runs it on the live path, after the thesis is constructed and before it is
returned. The stand-down path returns **before** the axis — measured correct rather
than assumed, since §17.4 governs only theses that reach sizing.

**§17.4 is the only rule that carries a risk-layer finding back into the thesis
lifecycle**, and it is the only back-edge in the system. It has **three outcomes,
none of them silent:**

- **No budget supplied** — the thesis keeps `DRAFT` and a warning states *"§17.4's
  sizing feedback **DID NOT RUN**"* and that a `DRAFT` here means *"not yet sized
  against a book"*, **not** *"sized and verified"*. §21.1 defines **no source** for
  portfolio holdings, so no honest book exists and §21.0 rule 3 forbids inventing
  one.
- **The translator refused** — the thesis keeps `DRAFT` and the warning says *"This
  is a **REFUSAL**, not a demotion: §17.4 demotes a thesis whose size is **too
  small**, and this is a different finding."* Fusing the two would publish a
  *refusal* (no position exists) as a *risk verdict* (a position was measured and
  found too small) — attributing to the rule a finding the rule did not make.
- **A size at or below the bound** — **DEMOTED to `WATCH`**, naming the binding
  constraint.

**The finding: `thesis_demotion_fraction` shipped at `0.02`, and the smallest
published `fraction_of_capital` any input can produce is `0.02941`.** §17.4 — the
rule that encodes the LTCM lesson — was therefore **declared, consumed, and
structurally incapable of firing**, and the test that would have caught it
**skipped**, which a suite renders as a green tick.

Measured, the reachable set is **six discrete values**, not an interval:
`0.02941 · 0.03472 · 0.042735 · 0.069445 · 0.125 · 0.15`. It is discrete because
**full Kelly is the argmax of expected log growth** and, for a two-branch
distribution with a positive edge, that objective is **monotone in `f`** — so `f*`
pins at the edge of the search domain and the *position cap* produces the published
number. Only asymmetric branch sets land strictly inside. `0.02941` is full `f*`
`0.05882` over `kelly.fractional_divisor` `2.0`.

The bound is now **`0.03`**, inside `[0.02941, 0.15)`, and carries **three**
constraints where it previously carried one implicitly: `> 0`;
`< max_position_fraction` (`0.15`); and **`>= the smallest reachable size`
(`0.02941`)** — the third being this increment's find. **The remedy is not a better
number:** `scripts/live_risk_axis_check.py` **recomputes the reachable set** and
fails if the bound stops splitting it.

**This is the ninth instance of the project's declared-consumed-unreachable class**
(D-045/D-046/D-048, O-53, O-27, twice inside D-072) and the **third distinct
vocabulary** — a lifecycle state, after a guard and an instrument sentinel.

**O-96 — §17.4's literal `CANDIDATE → WATCH` names an unreachable transition.**
Nothing in the tree produces `CANDIDATE`: the builder assigns `DRAFT` to a thesis
that reaches sizing and `WATCH` on all three stand-down paths, and promotion is a
human act by design. The axis operates on `DRAFT` and its warning names **both the
state demoted from and the state demoted to verbatim**. Recorded rather than
silently reinterpreted, because the two readings differ downstream.

**The mutation sweep refused to certify on its first run — 8 applied / 6 killed / 2
survived, and both survivors were real test gaps.**

- **`M1.2`** moved the axis's **local** bound while the tests asserted on the
  **config leaf** — both were "the bound" and neither test touched the other.
  **O-29's mis-target class one level up: not a mutation aimed at the wrong
  function, but tests asserting on the wrong copy of the same value.** Killed by
  `test_the_bound_the_axis_actually_uses_splits_the_reachable_set`, which drives the
  axis and reads the **outcome** instead of re-reading the setting.
- **`M4.1`** changed `<=` to `<` and survived because every demotion test landed a
  size **below** the bound. `<=` and `<` differ on **exactly one value**; if no
  input produces it they are the same function and no test can separate them.
  Killed by `test_the_demotion_fires_at_the_boundary_not_only_below_it`, which
  plants a size **exactly on** the bound.

Both closed by **adding tests, never by exempting a mutant.** Second run
**9 applied / 8 killed / 1 survived** (the honesty control) — **CERTIFIES**.

**Two guards amended, not deleted (D-067), each with a written reason.** The Kelly
guard in `test_integrity_gates.py` was **strengthened**: it now forbids raw
primitives, **enumerates the permitted consumer surface**
(`translate_thesis_to_position` is the one sanctioned route per §25), and adds a
behavioural receipt. The `macro_engine.portfolio` prohibition in
`test_builder_strictness.py` was **removed**, because the §17.4 hook *requires* that
import — **a guard forbidding the wiring the specification mandates is a guard
against the specification.**

**Gates at close:** `ruff check` clean; `ruff format` **218** = `mypy --strict`
**218** (D-035 parity); `pytest -q` **2329 passed / 1 skipped / 0 failed** (the skip
is the pre-existing Phase-5-gated `test_output_gap.py:255`);
`tests/thesis_layer/test_risk_axis.py` **17 passed, 0 skipped**;
`scripts/mutation_risk_axis.py` **9/8/1 CERTIFIES**;
`scripts/live_risk_axis_check.py` **PASSED, exit 0**;
`tools/sweep_health.py` **38 sweeps, 0 failures, 0 leftovers**.

**Phase 5 is NOT started, by explicit instruction.** Its entry point is the 13
Tier-5 deferrals, each of which §22.3 requires to bring its own verified
data-source registry, its own central-bank reaction function, and its own
instrument set.

### D-072 - A risk budget that is not a notional, and a gate that was reading its sources differently from every sweep

**Phase 4 - 2 of 4 items complete.** Two functions in
`src/macro_engine/portfolio/risk_budget.py`, which has held Module 17 since D-054:
`compute_risk_parity_weights` (§9.2, **D-071**) and `translate_thesis_to_position`
(§9.3, **D-072**). No new module; the file is already the shared home of the
§6.6c ladder, the §15 Module 18 drift check, `volatility_target_scaling` and
`apply_fractional_kelly`.

**A risk share is not a notional share, and §9.3's signature cannot make it one.**
Module 17.1 defines the risk contribution `RC_i = w_i (Σw)_i / σ_p²` — that needs a
covariance matrix. §9.3 takes a `MacroThesis` and a portfolio risk budget and
**nothing else**. The conversion between the two quantities is therefore not
available, and the naive substitution (risk share used directly as notional share)
was measured **6.7x wrong** on a real two-asset book: **0.018** where the correct
answer is **0.12**. This is not a bug to fix — it is the reason §9.3's output is a
**proposed** position carrying `SIGN_OFF_REQUIRED`, never a sized order. Two
specification sections that cannot be composed numerically is the finding.

**Four gates, and the count is now pinned to the type it describes.** Every gate
can only *stop* a proposal: gate 1 the sentinel / no-production-instrument path,
gate 2 an uncalibrated scenario distribution, gate 3 an instrument outside the
universe, gate 4 a budget below the floor. The docstring states the rule the
deletion of the fifth gate established — **"There are four, not five: a gate that
cannot stop a proposal is not a gate."**

**The declared member set shipped a false counting claim.** `PositionTranslationOutcome`
is a six-member `Literal`; the type's docstring said **"nine members"**. The
sweep's first run proved the claim was changeable to *any* number with the entire
suite green (`M10.2`, `M10.3` both **SURVIVED**) — `get_args` reads the type and a
docstring is a string. Repaired with
`test_the_docstrings_agree_with_the_literal_they_describe`, which recounts the
members and the gates from the docstring itself; both mutants are now killed.
**A docstring claim about a type is a claim, and it needs a receipt** — O-88
extended from gate rows to prose.

**The increment's highest-value defect was in the tooling, and it was masking a
live mutant.** `tools/sweep_health.py` reported **13 `[FAIL]` sweeps**; ten of them
targeted `src/macro_engine/config.py`. Every one of those sweeps was right.

> `_own_target_check` and the leftover scan read with
> `Path.read_bytes().decode("utf-8")`. Every sweep anchors with bare `\n` and reads
> with `Path.read_text()`. **`read_text` applies universal-newline translation;
> `read_bytes().decode()` does not.**

`config.py` is the **only CRLF file among the 69 under `src/`** (4292 CRLF, 0 bare
LF) and is the target of all 13 failures. Reproduced with both readers on that same
file: **bytes form -> 45 problems, translated form -> 6**. **87% of the report was
line-ending artefact.** Fixed both readers; 13 failures -> 2, both inherited.

**And the noise was hiding a real leftover mutant.** `src/macro_engine/models/yield_curve.py`
held `adjusted = base_rate + min(adjustment, settings.ceiling)` where `HEAD` has
`adjusted = min(uncapped, settings.ceiling)` — **O-61's fifth recurrence**. It was
also destroying the anchors of its own sweep's `MX3a`-`MX3d` mutants, which had
been reporting "target ABSENT" and were being read as stale anchors. The false
positive and the true positive were the **same line**. Restored from `HEAD` (line
endings verified: 1748 bare LF, 0 CRLF); three tests caught it; the suite returned
to **2295 passed**. Filed as **O-95**.

**Two sentinels documented as one.** Four documentation sites asserted the
no-instrument sentinel and the not-in-universe path were the same string. They are
different, and the corrected fact is worse than the original claim: `is_trade`
returns `True` for the sentinel, so it reads as a **live trade in an unexecutable
instrument**. Filed as **O-93**; four sites corrected in place with
`**CORRECTED (D-071/D-072)**` markers.

**New defect class recorded: "the right outcome with the wrong reason."** Several
refusals returned the correct `outcome` while naming a **different gate's** reason.
No numeric assertion can see it — outcome, size and struct all match. It is why the
live check re-reads the reason on **all seven** paths rather than only the outcome.

**Verification - all gates green at 215 files (D-035 parity):** `ruff check` clean;
`ruff format --check` **215**; `mypy --strict` **215** (matches); `pytest -m "not live"`
**2295 passed / 1 skipped / 0 failed**; `tests/portfolio/test_thesis_position.py`
**45 passed**; the sweep **22 applied / 21 killed / 1 survived (the control) —
CERTIFIES**; `scripts/live_thesis_position_check.py` **PASSED at exit 0** over the
real pipeline; the reachability audit **PASS, 59 = 59**; `tools/sweep_health.py`
**0 leftovers, 0 mutant shapes**, 2 failures both **inherited**.

**The live check's Section 21.0 record, measured not asserted:** all four US thesis
families (`policy_path_gap`, `curve_shape_gap`, `inflation_expectations_gap`,
`equity_macro`) produce `status=WATCH`, `instrument="NONE"`, an empty
`scenario_distribution` and `scenario_sizing_permitted=False` on today's data, so
all four refuse at **gate 1**. The 24-cell census had **8 schema-refused and 16
measured** cells. `ProductionUniverse().permits` returns `True` for `TY futures`,
`EURUSD` and `"NONE"`. **A sweep that only ran green paths would have certified
nothing** — hence the hand-built fixtures for gates 2-4.

**Not in this increment:** the **risk-axis hook** (§17.4, handoff §3b item 4) —
`thesis_layer/builder.py` must gain a risk-budget parameter whose default preserves
today's behaviour, and the orchestrator must supply a real book. It is deliberately
separate: it changes the builder's signature, which every D-069 test and sweep
anchor reads. **O-94** also remains — §16.2 Q12's exposure half is computed nowhere
and needs Module 18.

### D-070 - The API layer, and a mutation sweep that certified a selection it never ran

**Phase 3 - 0/2 -> 2/2. PHASE 3 IS COMPLETE.** Eight new modules under
`src/macro_engine/api_layer/` (3383 lines total) implement the whole of Section 8:
`/health`, `/thesis/{country}`, `/dashboard_data`, `/query`, and an SSE reasoning
stream. Per the user's decision the snapshot-to-builder derivation lives in its own
module so the API layer stays thin and the gap is **one auditable file**.

**The orchestration gap is what this increment exists to close.**
`build_us_macro_thesis` takes **six required arguments** - three positional
(`reads`, `taylor_inputs`, `first_difference_inputs`) and three keyword-only
(`thesis_type`, `universe`, `short_yield`). Section 8.2's sample calls it with a
snapshot alone and gets `TypeError: missing 6 required argument(s)`. None of the six
can be defaulted: `thesis_type` is an **analytical choice among seven families**, and
a gap says nothing about which one the thesis is.

**Refusal, not defaulting.** Section 16.3 forbids mapping missing data onto a
`WATCH` thesis, because a fabricated stand-down is indistinguishable from a genuine
"no edge" verdict. Missing data is a **502**; a real stand-down is **200**.

**Three measured unit traps, all in the labor leg** - and the second is the
dangerous one, because the wrong number **passes the model's own validator**:
`jolts_openings` is in thousands needing a YoY percent; `jolts_quits` is a rate in
percent (`1.9`) that `ge=0, le=100` **accepts**, needing a percentile of its
trailing range; `initial_claims` is persons needing a 4-week-average percent change
with POSITIVE meaning loosening.

**The increment's own defect: the YoY anniversary tolerance.** `_yoy_percent`
accepted "the latest observation at or before the anniversary" - which succeeds for
a point **31 days away**, and published the ratio under the words "year-over-year".
Now a config-driven tolerance (`api.yoy_match_tolerance_days`, default 5), and the
**exclusion of the adjacent month is the entire point** of the value.

**Section 8.4's pairing is enforced, not documented.** A permissive `cors_origins`
list combined with a non-loopback host is **refused at load time**, and
`loopback_only` publishes the posture as a value. The service has no authentication,
so the bind address IS the access control.

**THE SWEEP REFUSED TO CERTIFY THREE TIMES, AND THE THIRD TIME FOUND THE REAL
DEFECT.** First run: 42 applied / 31 killed / **11 survived** - ten with no proof,
each diagnosed by applying it rather than labelling it. Three were **real lies the
tests missed** (M8.6: the stream named three gates when one fired; M10.2: a
self-referential version check; M9.5: a tautological loopback guard). Five were
**genuine coverage gaps** closed by writing `test_snapshot_provider.py`. Two were
**proven inert with a measured mechanism**. Second run: **36 killed / 6 survived** -
and M9.1/M9.2/M9.3 survived *again*, on a tree where each is measurably killed.

> **That contradiction was the defect.** `PYTEST_TARGETS` declared four test files;
> `run_pytest` ran three; `check_tests_collect` validated the declaration the run
> never used. The three provider mutants' tests lived in the file that was declared
> and never selected - so a **green gate certified a selection nobody executed**, and
> the resulting survivors looked exactly like inert mutants.

The fix is structural: both functions now splat the **one** constant, and a new gate
(`check_the_run_and_the_declaration_agree`) parses the source and refuses to run if
either re-inlines a literal path. Verified by planting the regression.

**O-83's remedy is implemented.** `tools/sweep_health.py` gained a whole-tree
mutant-shape scan that consults **no catalogue** - closing the class where a mutant
left in a shared file is invisible because the per-sweep leftover check is scoped.
Verified live: it caught an in-flight `# MUTANT` during the sweep run.

Third run: **42 applied / 39 killed / 3 survived - CERTIFIES**: two mutants proven
inert with a traced mechanism (`M1.5`'s second overlapping guard; `M4.3`'s second
independent guard, traced to `gdp_nowcast.py:442`) and the honesty control.

### The live check found three defects, and all three were in the check

The live check is the increment's proof that the *wiring* works. Its first three
runs failed, and every failure looked like a defect in the service while the service
was correct. The diagnostic shape - **a misleading symptom on a correct component** -
is the reusable part.

**1. `GET /health?deep=true` returned `404 {"detail": "Not Found"}` from a route that
exists.** The route was correct and correctly mounted, returned **200** to
`TestClient`, and returned 200 to a standalone probe - so it presented as
*intermittent*. Tapping the socket and printing the **request line** (not the status
code) found it:

```
wire 0: b'GET /health HTTP/1.1'
wire 1: b'GET http://127.0.0.1:55264/health HTTP/1.1'    <-- absolute URI
```

This environment exports `HTTP_PROXY`/`HTTPS_PROXY`, `httpx` honours them by default
(`trust_env=True`), and a forward proxy **must** receive the absolute-URI request form
(RFC 7230 Section 5.3.2). The proxy forwarded that URI to the origin, uvicorn
unquoted it into the *path*, and no route matched. The intermittency was the trap:
the **first** request on a fresh connection went out origin-form and survived, while
a **reused keep-alive** connection went out absolute-URI and 404'd. Isolated by
measuring all four combinations - reuse alone flips the form, `params` is irrelevant -
and proven by `trust_env=False` sending origin-form on both.

Three hypotheses were tested and discarded first: the `params` encoding, a
router-prefix mismatch, and h11's 16 KiB request-header limit. The last is a
near-miss worth recording: an oversized header block **does** produce a protocol
error (`RemoteProtocolError`, hint 431), but the fresh-connection case returned a
clean `431`, so it was a *different* failure with a superficially similar shape.
**A routing-shaped symptom can have a transport-shaped cause, and the status code
cannot distinguish them. The request line can.**

**2. The CORS preflight returned `400 Disallowed CORS origin`.** The check hardcoded
`http://localhost:3000`; the config allows `:8000`. **Starlette was right and the
check was wrong.** Now derived from `settings.api.cors_origins`, which is the
stronger assertion anyway.

**3. The stream assertion failed on a correct stream.** It searched for
`"gap = +26.0bp"`; the stream emits
`"...: gap = +0.2600pp (+26.0bp), dispersion ..."`. The value was exactly right and
the check had baked in a **spacing** the stream never promised - lesson 5bf applied
to the check itself. It now requires **both** renderings, because a stream that
hardcoded one unit while deriving the other would pass a single-unit check.

**Guard.** `test_the_live_check_does_not_route_its_loopback_traffic_through_a_proxy`
reads the script with `ast` and requires every `httpx.Client(...)` to set
`trust_env=False`; a companion test requires the proxy variables to be *printed* so a
run stays reproducible. Verified red by planting the regression, then restored. It
cannot be behavioural - the unit suite drives `TestClient`, which never opens a
socket - which is exactly why the defect survived 125 green unit tests.

**Production exposure - O-92.** The same root cause is in two production clients:
`openbb_client.py:91` and `catalysts.py:213` both default to `trust_env=True`, and
the OpenBB client's mounts against `http://127.0.0.1:6900` are
`{http://: HTTPProxy, https://: HTTPProxy}`. The provider **works** here (21/21
fields, 62.4-66.1s) - so this environment's proxy is transparently forwarding
loopback, **luck rather than design**. Filed rather than fixed: it changes
data-layer network behaviour this increment did not touch, and altering the
provider's transport would have invalidated the sweep that certifies it.

**Tests:** 125 new (49 orchestration + 43 routes + 15 provider + 17 strictness + 2
added by the live-check guards), a 42-mutation sweep certifying
**39 killed / 2 measured-inert / 1 control**, and a live check driving a real
uvicorn server that now **passes end to end at exit 0**.

### D-069 - The seam function, and the defect only a live run could see, and the defect only a live run could see

**Tier 4 - 10/11 -> 11/11. TIER 4 IS COMPLETE.** One function,
`build_us_macro_thesis` (Section 7.2 / 16.2), shipped in a new
`src/macro_engine/thesis_layer/builder.py` (1174 lines). **No config leaf** - and
that is the first substantive finding: **every threshold this function consults
belongs to a model it calls**, so a config block here would have been a second
source of truth for numbers the models already own.

**This is the seam.** The function appears on **both** the Tier 4 and the Phase 3
checklists, and that overlap is not an inconsistency - it *is* the phase seam: the
models layer stops producing numbers and the thesis layer starts making claims.
With it implemented, **Phase 3's blocker is cleared**.

**Nine measured divergences from Section 16.2's sample**, including a correction
of my own carried-in premise: the sample omits **zero** required `MacroThesis`
fields. (The "six missing fields" belonged to Section 16.4's `no_trade_thesis`
sample - that is D-068's finding, and I had carried it into the wrong section.)

**Two boundaries, both measured rather than assumed:**

- **Q1's three economy reads are a PARAMETER** (`EconomyReads`, a frozen
  dataclass), not something the builder computes. The census of snapshot-taking
  helpers is **`[]`** for `inflation_nowcast`, `labor_synthesis`, `regime` and
  `national_accounts` - there is no `inflation_breadth_score(snapshot)` to call.
  Manufacturing one would have **hidden the gap**; making it a parameter makes the
  gap the caller's visible obligation.
- **`MarketPricingGap` is not a `ModelResult`.** It is a plain `BaseModel` whose
  `value` is `raw_gap`, so Section 16.2's sample fails pydantic validation against
  the aggregate's signature. An explicit `_as_signal` adapter bridges it instead
  of loosening the contract.

**The three no-trade gates fire in order Q6 -> Q7 -> Q8**, and each routes to a
helper that **owns its own trigger literal** rather than re-deriving it from a
sentence (D-068's O-85 constraint, honoured one function on).

**THE DEFECT - an INTERACTION defect, found by the live check and invisible to
every fixture.** `_render` collected **no warnings at all**, so **every stand-down
silently dropped the model warnings and Section 22.5's market-path contamination
disclosure**. The live check printed:

```
contaminated=0 proxy=0        # on a run where the contaminated branch was taken
warnings=1                    # the trigger line alone
```

No offline test could see it: every one asserted the trigger line was **present**,
and it was. **The defect was that it was alone.** The fix renders first and
**appends** the warnings behind the trigger line, because `render_no_trade_thesis`
*owns* `warnings` and **raises** rather than accept an override - so the
increment respected D-068's contract instead of relaxing it. Measured after:

```
warnings=13    contaminated=1 proxy=1
```

**The mutation sweep refused to certify - TWICE.**

- **First run: SIX survivors, every one a REAL test gap.** The headline was
  **M8 - the very defect just fixed** - which survived because its regression
  test had been written **only in `test_builder_live.py`**, and `-m "not live"`
  **deselects** that file. The other five survived on assertions that were too
  weak: a disjunction any sentinel satisfies; a direction pinned only as a
  relation rather than against a disagreeing fixture; scenarios checked only on
  the live path. **All six closed by ADDING tests** (40 -> 51), never by exempting
  a mutant. **Lesson 5be.**
- **Second run: the HONESTY CONTROL was killed.** `M18` is semantically inert
  (`x < 0` rewritten as its De Morgan negation), so its survival is required. It
  died because a strictness guard asserted the fallback's **literal source text**
  rather than its meaning - a test pinning **spelling, not behaviour**. Rewritten
  to pin **order and structure via `ast.parse`**. **Lesson 5bf.**

Two mutants were also **mis-aimed** and retargeted: `M12`'s anchor was in
`_render` rather than `_direction_for`, and `M13`'s replacement was a behavioural
no-op. Both caught by `check_anchor_landings` / inspection.

**A published gate row was FALSE, and running the gate is what showed it.**
D-068's block claimed `mypy --strict` was clean at **176 files**. The tree held
**29 errors**, all in D-068's own files (13 + 1 + 1 in the three
`test_no_trade*` files, 15 in `scripts/live_no_trade_check.py`). All 29 are now
fixed, so the gate is **true at 182**. Recorded as **O-88**; the standing remedy is
that **every gate row is re-derived by executing the command**, and that
**ruff-format and mypy must report the same file count** - a mismatch is the tell
that one did not cover the whole tree.

**Opens O-87** (`select_instrument` publishes **two** value shapes - a dict on the
executable routes, a bare **sentinel string** on the refused ones - while its own
`_selection_value` declares *"always returns a dict value"*; **that sibling claim
is wrong**) and **O-89** (the residual mypy/robustness debt). **Corrects O-84's
diagnosis** (see below) and **advances O-81 / O-85 / O-86**.

**Gate results.**

| Gate | Result |
|---|---|
| `ruff check src tests tools scripts` | **All checks passed** (182 files) |
| `ruff format --check src tests tools scripts` | **182 files already formatted** |
| `mypy --strict src tests tools scripts` | **no issues in 182 source files** (true, after 29 fixes) |
| `pytest -q -m "not live"` | **1901 passed, 1 skipped, 16 deselected** x 5 consecutive |
| `scripts/mutation_builder.py` | **18 applied / 17 killed / 1 survivor (the control)**, exit 0 |
| `scripts/live_builder_check.py` | **passes end to end** |
| `tools/sweep_health.py` | **37 sweeps, 0 failures, 0 leftovers** |

**Tests:** 78 new (51 behaviour + 21 static guards + 6 live).

**Also corrects a diagnosis carried for two increments (O-84).** The `iorb`
live-test failure was recorded as a **frozen clock** compared against a stale
`retrieved_at`. **It is not.** The failure text names its own comparison:
*"observation_date 2026-09-21 is after retrieval date 2026-09-19 by 2 day(s),
beyond this series' declared tolerance of 1"* - the retrieval date is **today**,
so the check does **not** decay with cache age. **The real finding: FRED is
publishing `iorb` 2-3 days ahead of the calendar**, while the series declares
`future_date_tolerance_days: 1` (a tolerance sized for the documented UTC-boundary
case, a 1-day overshoot). **The ERROR path is armed and firing correctly** - this
is the guard working. The fix is a **data-layer** decision, not a thesis-layer one.

### D-068 - A stand-down that cannot say which gate fired

**Tier 4 - 9/11 -> 10/11.** One function, `no_trade_thesis` (Section 16.3/16.4,
Module 14), shipped in a new `src/macro_engine/thesis_layer/no_trade.py`. **No config
leaf** - every threshold it touches belongs to the gate that fired.

**The headline: Section 16.2 routes to `no_trade_thesis` from THREE places, and
Section 16.4 gives it one `reason: str` to say which.** Q6 (the gap is inside the rules'
own disagreement), Q7 (`CONFLICTED`), and Q8 (no falsifier could be derived, which
D-063 added) all arrive as a sentence. Whether two stand-downs are distinguishable is
therefore a property of whoever wrote the sentences, not of the data - and each of the
three callers is holding a **rich object** the sentence throws away.

**Five defects, all measured before the implementation was written** (two probes: one
structural, one live through the real models):

- **The sample body does not run.** `MacroThesis` requires six fields with no defaults
  (`regime`, `growth_view`, `inflation_view`, `policy_view`, `market_pricing_gap`,
  `convergence_classification`). Section 16.4's nine lines raise `ValidationError`
  naming all six, and its `# other fields populated with whatever partial view was
  formed` comment is the author knowing it and leaving the requirement as prose.
- **One string slot for three triggers.** Three identical sentences make three
  different situations the **same object**, and nothing in the output records which Q
  fired, so stand-downs cannot be counted by cause.
- **Each trigger already holds an object and all three are discarded.** Measured live:
  Q6 holds a `MarketPricingGap` (`raw_gap=+0.77`, `dispersion=0.42` - the magnitudes
  that say how close the call was); Q7 holds the full per-model direction table
  (`['confirms','confirms','confirms']`); Q8 holds an `InvalidationAssessment` with the
  per-input reasons it could not be read. **D-067's defect 2 one function on, and
  worse** - the dropped object is the only record of *which of three very different
  things happened*.
- **`warnings=[reason]` accepts `""` and `[]`.** Measured: both build a valid thesis.
  So "we stood down", "we stood down and forgot to say why", and "we stood down because
  of an empty string" are the **same object** - **D-066's shape** from a third
  direction.
- **`stop_or_invalidation="n/a"` satisfies the gate it stands down from.** Measured:
  `bool("n/a".strip())` is `True`, and a `TradeIdea` carrying only that sentinel returns
  `is_trade is True` - the LTCM gate **accepts it as a stated falsifier**. Nothing
  breaks today (a no-trade has `is_trade = False`, so the gate is skipped), but the spec
  writes a sentinel the schema would honour, so the no-trade shape is one field flip
  from asserting a falsifier it does not have.

**The fix.** `no_trade_thesis(reason, *, trigger, evidence=None, gap=None)` returns a
`NoTradeDecision`:

- **`trigger`** - a closed `Literal` with four members: `gap_below_dispersion`,
  `conflicted_signals`, `no_falsifier`, and **`caller`** (so a stand-down outside the
  three documented gates is *sayable* rather than forced into a false label). A
  `Literal` rather than a `str` because an unlisted trigger is then a type error at the
  call site (O-29's lesson).
- **`evidence`** - a typed union of the three gate objects, or `None` for `caller`.
- **`elapsed`** - `dispersion - abs(raw_gap)`, only for Q6: a gap 1bp short of
  meaningful and one 200bp short are both "not meaningful" and are **not the same
  call**. `is_marginal` reads it; `None` returns `False` because "not close" is the safe
  reading when the question does not apply.
- **`reason`** - refused when empty or whitespace-only, with an error that names the
  conflation and suggests `trigger='caller'`. This is the only place defect 4 can be
  caught: once a `MacroThesis` exists, blank and short are indistinguishable.
- **Q6 without `gap`** raises - the one trigger with a magnitude cannot silently lose
  it.
- **`render_no_trade_thesis(decision, **thesis_fields)`** builds the published
  `MacroThesis` from the caller's six required fields (this module has no snapshot, and
  inventing them is exactly what defect 1's comment admits to). It **refuses**
  `trade_idea` / `status` / `warnings` overrides, naming the clash, writes the labelled
  line `No trade [<trigger>] (<label>): <reason>` into `warnings` so the trigger
  survives into the published object, and writes `stop_or_invalidation=""` rather than
  Section 16.4's `"n/a"`.

**It does not re-derive the trigger from the sentence.** The caller states it; a function
that parsed prose to recover a fact the caller had in hand would be guessing.

**Verification.** 35 offline tests plus 7 static guards; a 14-mutation / 14-group sweep
with all three harness gates and a real control - **14 applied / 13 killed / 1 survivor
(the control), and NO gaps to close on the first run**. The structural reason is worth
recording: every defect here is a **presence** defect (a field, a guard, a label), and a
presence defect has a fixture that names it - where D-067's survivor was an
**interaction** defect (`all_texts`' two halves could never interleave) that no
single-field test could see. **M2's kill is doubly attested**: the sweep reports a
behavioural symptom, and the static guard `test_the_trigger_vocabulary_is_closed` was
verified to kill it **independently**. A **pulled** live check passes, measuring that
**none** of the three gates fires on 2026-09-19 (so the no-trade path is not the common
case) and confirming the sentinel danger live.

**Opens O-85** (the trigger is an unchecked caller claim - `build_us_macro_thesis` must
derive it) and **O-86** (`WATCH` cannot distinguish "no edge" from "waiting" to a
consumer reading only `status`). **Lessons 101-103.**

**Gates:** ruff + format + `mypy --strict` clean at **176 files**; `pytest -m "not live"`
**1829 passed / 1 skipped / 10 deselected**; `tools/sweep_health.py` **36 sweeps, 0
failures, 0 leftovers**. `pytest -m live` is **9 passed / 1 failed**, the failure being
the pre-existing **O-84** and not caused by this increment.

---

### D-067 — A summariser that cannot say how many models saw the same thing

**Tier 4 — 8/11 → 9/11.** One function, `collect_all_warnings` (§16.4, Module 14),
shipped in a new `src/macro_engine/thesis_layer/warnings.py`. **No config leaf** —
`unattributed` is a parameter, deliberately (below).

**The headline: §16.4's nine-line sample is a `dict.fromkeys` de-duplication, and it
fills a field the specification calls "never dropped" while §21.4 makes two further
classes mandatory.** `WarningSummary` carries §16.4's `list[str]` **verbatim** in
`warnings` and adds a sibling field for each question the flat list could not answer.

**Seven defects, all measured before the implementation was written** (three probes;
the first four need no data):

- **De-duplication destroys the count, and the count is the signal.** Four models
  raising one identical string aggregate to **one** entry. This is **D-046's "five
  signals are not five votes" inverted** — there, correlated measures were
  *over*-counted as independent votes; here, one fact seen by four models is
  *under*-counted as one.
- **The output cannot attribute a warning to its source.** *"Two models independently
  reported this"* and *"one model said it twice"* are the **same value**. Measured:
  two byte-identical warnings produce a one-element list with no trace of the second.
- **Whether de-dup fires is an unstated producer convention.** Prefixed warnings do
  not collapse; unprefixed ones do. Measured: **0 of 8** live warnings name their own
  model, so the behaviour is undefined-by-accident rather than chosen.
- **"No warnings" and "not passed" are the same value** — `collect_all_warnings(quiet)
  == collect_all_warnings()`. **D-066's shape**, one function over.
- **§21.4's mandatory class has no route in.** A BLOCKED input is one no model could
  run on, so it is **not a `ModelResult`** and §16.4's signature cannot express it.
  Measured against the live registry: **5 blocked members, 0 routes**.
- **§5.4's disclosure class does not reach it either.** Measured on a live snapshot:
  **5 of 5** `data_quality_flags` absent. The flag only *lowers confidence*
  (D-033 / §22.8); it is never surfaced as text.
- **Defects 1 and 6 are COUPLED.** The natural fix for 6 — route the snapshot flag
  into every model's own `warnings` — makes **every** model carry the **same string**,
  which is exactly the collision defect 1 collapses. **Measured live:** routing flag 1
  into all five models makes §16.4's list show it **once** while its `WarningSource`
  records **5 raisers**. A repair treating the two separately reintroduces one while
  fixing the other.

**Added** — `src/macro_engine/thesis_layer/warnings.py`: `collect_all_warnings`,
`WarningSummary` (frozen; `warnings`, `sources`, `unattributed`, `model_warnings`,
`contributing_models`, `models_with_warnings`, `all_texts`, `shared_warnings`),
`WarningSource` (`text` + `model_names`, `raised_by_multiple_models`),
`UnattributedWarning` (`text`, `origin`, `detail`), and the closed `WarningOrigin`
vocabulary (`blocked_input` / `data_quality_flag` / `caller`). Two internal
`AssertionError` censuses assert "never dropped" rather than assuming it.

**It does not decide whether de-duplication should happen** (something a
specification decision, not a code one — D-064's direction-blindness precedent), **it
does not walk the registry or the snapshot itself** (a function that did would make
§21.4 *look* discharged whether or not the caller passed anything), and **it does not
merge `unattributed` into `warnings`** (that hides which class was raised).

**Added** — `tests/thesis_layer/test_warnings.py` (28 offline + 1 live) and
`tests/thesis_layer/test_warnings_strictness.py` (5 static guards).
**Added** — `scripts/mutation_warnings.py` (9 mutations, 9 groups, all three gates,
`refuse_on_noop` on) and `scripts/live_warnings_check.py`.

**The sweep found a real hole in this increment's own tests.** `M5.1` reverses
`all_texts`' two halves and **survived the whole selection**, and it is **not inert**:
the existing order test passes **only** unattributed warnings, so the two halves can
never interleave. **Closed by adding a test, not by exempting the mutant** —
`test_all_texts_puts_the_models_warnings_first`; M5.1 then killed.

**The sweep also proved two mutants cannot be killed behaviourally.**
`M2` (the `raisers` annotation narrowed to `dict[str, str]`) survives because the
mutant dies with an `AttributeError` raised **from inside the function under test** —
pytest reports a failure, but no assertion caught it. `M4` (the raiser census
deleted) survives because the guard is **unreachable by construction** — every input
warning appends exactly one raiser, so it cannot fire. `M2` is now killed by a
**static** test; `M4` is exempted **by argument** (`inert_proof` states the
construction) with its presence pinned. This is why `test_warnings_strictness.py`
exists: **a mutation changing a type annotation, or removing a line whose effect no
value can express, is killed by a different gate than the one the sweep runs.**

**Found at close — O-83, an incident.** D-064's `M6.3` mutant (`if False:` replacing
the sum-to-one constraint in `config.py`'s `_remaining_shares_must_sum_to_one`) was
**still applied on disk**, and `tools/sweep_health.py` reported **0 leftovers** —
because its leftover scan is **per-sweep** and `config.py` belongs to the *scenario*
sweep, which was target-clean *only because the mutation had already fired*. The
corrupted state was invisible **precisely because it had succeeded**. Restored by
hand; the scenario sweep then ran **23 applied / 22 killed** (it had been refusing on
an absent anchor). **O-61's family with a new mechanism: the gate was not blind, it
was scoped.**

**Found at close — O-84.** `iorb`'s `future_date_tolerance_days: 1` is checked against
the snapshot's **persisted** `retrieved_at`, not against now, so the live data-layer
test fails once FRED publishes more than one day ahead of that stamp (measured: 2 and
3 days). **O-80's class one layer down**; pre-existing and not caused by this
increment.

**Fixed** — `pyproject.toml` allows `T20` (print) under `tests/thesis_layer/*.py`, for
the same reason `scripts/*.py` already did: the **live** tests are the project's
measurement instrument (§21.0's real-data execution step) and their value is the
printed census, not only the assertions.

**Gates:** ruff + format + `mypy --strict` clean at **170 files**; pytest **1787
passed / 1 skipped / 8 deselected**; `mutation_warnings.py` **9 applied / 7 killed /
2 survivors, both proven**; `live_warnings_check.py` **passes**;
`tools/sweep_health.py` **35 sweeps, 0 failures, 0 leftover mutations**.

**Carried forward:** **O-81** (§21.4's blocked class has a route but no call site),
**O-82** (§5.4's flags never reach the aggregate), **O-83** (the scoped leftover scan),
**O-84** (the frozen-clock tolerance). **Lessons 98–100.**

### D-066 — A fall-through that invents disagreement, and a label that named a model nobody called

**Tier 4 — 7/11 → 8/11.** One function, `build_confirmation_signals` (§16.4 Q7,
Module 14), shipped in a new `src/macro_engine/thesis_layer/signals.py`. **No config
leaf** — the one that was attempted was correctly refused (below).

**The headline: the sample's `direction` is derived by a bare `else`.** §16.4 writes

```python
direction = "confirms" if (isinstance(result.value, (int, float)) and
                            ((result.value < 0 and gap.raw_gap < 0) or
                             (result.value > 0 and gap.raw_gap > 0))) else "contradicts"
```

— one condition, two branches, and only one of them is derived. Meanwhile
`ConfirmationSignal._validate_direction` (§22.10 / Finding #10) permits **three**
members (`confirms`, `contradicts`, `neutral`). The third is whatever `else` does,
and `else` does not mean "otherwise nothing" — it means **everything the author did
not enumerate**. Measured, four outcomes fall through, and **three are not
disagreement at all**:

| value | §16.4 | shipped |
|---|---|---|
| `{"classification": "HIGH"}` — a **dict**, published by `four_pillar_scorecard` and `inflation_convergence_classifier` | **`"contradicts"`** | `"neutral"` |
| `0.0` — the balance point | **`"contradicts"`** | `"neutral"` |
| `True` — a flag, which passes `isinstance(x, (int, float))` | **`"contradicts"`** | `"neutral"` |
| a non-zero value against a **zero** gap | **`"contradicts"`** | `"neutral"` |

Each was published as an **active claim that the evidence opposes the thesis**. The
defect is not a wrong direction; it is **a direction that was never derived** —
D-056's false-confidence failure direction, one layer in from the arithmetic.

**The second finding: O-69's full extent, measured.** D-063 recorded it as "three
different inflation models for one argument slot"; the surface is **six distinct
`source_model` labels for three slots across three locations**, and only **one**
(`labor_tightness_score`) appears in all three. **`curve_slope`, which §7.1's golden
sample names, is not a parameter of the function at all.** The shipped function
**derives each label from `result.model_name`** — the only source that cannot drift
from what was read — keeping the slot name as a fallback for an empty `model_name`
only.

**Three further §16.4 defects, all measured:**

1. **`source_family` is never populated.** §6.6b requires every signal to document
   enough about its source *"for the convergence logic to correctly classify
   independence"*, and the field exists for exactly that — but the sample constructs
   the signal with three arguments and leaves it `None` on **every** entry. The
   count is therefore not *wrong*, it is **unreachable**. The shipped function
   carries `result.source_family` through.
2. **`detail` is the raw `interpretation`, so a signal can undercut itself
   unflagged** — an `inflation_breadth_score` whose sub-measures disagree says so in
   prose while its **direction** still reads `confirms`, because the divergence is
   about the sub-measures' *agreement* and the direction is about the *sign of their
   average*. The interpretation is kept verbatim (it is the model's own sentence)
   and the warning count is appended under a stable token, so the caveat is a field
   rather than a phrase.
3. **The return type cannot carry Q7's second half.** §16.4 returns
   `list[ConfirmationSignal]`; Q7's real answer has two halves (*what each model
   says* and *whether it could be read*), and a bare list has nowhere to put the
   second — **which is why an unreadable input had to masquerade as a
   contradiction**. The shipped return is `ConfirmationSignalAssessment`, carrying
   the list plus `unreadable` and a census (`agreeing`/`disagreeing`/`neutral`) that
   must total the list length.

**A design decision, recorded because it changes an answer:** a **zero gap** makes
*every* signal neutral. A sign cannot agree with a direction that does not exist, so
publishing any as `confirms` would invent the very reference the comparison was
against. §16.2's Q6 routes a zero-ish gap to `no_trade_thesis` *before* Q7, so
reaching here with one means the caller skipped Q6 — the function is total on its
inputs and states the consequence rather than assuming the guard fired (**O-79**).

**A config leaf the infrastructure gate correctly refused.** The first draft put the
warning token in `settings.yaml` as a `CalibratedValue`.
`test_every_calibrated_leaf_has_a_numeric_property_accessor` **failed it**, and it
was right to: the guard's only accepted routes are a **numeric** `.property` or
`Settings.scalar()` — and `scalar()` returns `float`, which a string token can never
be. **The envelope was the wrong shape, not a missing accessor.** A display token is
not a fact about the economy, a convention, or an uncalibrated placeholder, which is
what §10.4 scopes `settings.yaml` to. It is now a module constant beside
`_SLOT_FALLBACK_NAMES`, pinned by `test_the_marker_is_a_module_constant_not_a_config_leaf`,
which also asserts **no `confirmation_signals` block exists**.

**A live-check defect found in this increment's own probe.** The first live check
built the growth leg by hand — `.iloc[-1]` on `GDPC1` and `GDPPOT` — and returned an
output gap of **−17.57%**. `GDPPOT` is a **CBO projection series** whose last
observation is **2036-10-01**, so the comparison was 2026 actual output against 2036
projected capacity, **with no error raised**. `output_gap_from_snapshot` applies the
**O-7 horizon filter** and the **D-009 same-quarter pairing** and gives **+0.83%**
with **42** forward points withheld. Both the live check and the live test now go
through the real plumbing and assert **plausibility** (`|gap| <= 15%`), not merely
readability.

**Verification.** `mutation_confirmation_signals.py`: **9 mutations in 8 groups
across two files, 8 killed, 1 survivor (the honesty control), exit 0**, with
`check_targets`, `check_anchor_landings`, `check_tests_collect` and `refuse_on_noop`
all on — `check_targets` refused the first draft's M4 anchors as **AMBIGUOUS**
(byte-identical except indentation), which is D-048 working as intended.
`live_confirmation_signals_check.py`: **passes** — five checks over live data,
including that the label disagreement is real and that a dict-valued real model reads
`neutral`. Gates: ruff + format + `mypy --strict` clean at **165 files**; pytest
**1754 passed / 1 skipped / 7 deselected**; `sweep_health.py` **34 sweeps, 0
failures, 0 leftovers**.

**New open issues:** **O-77** (no `unreadable` direction member — the distinction
lives in a sibling field a caller can drop), **O-78** (the warning count is prose in
`detail` — **O-76's shape in a second field**), **O-79** (the Q6/Q7 ordering is
unenforced; the function recovers rather than detects), **O-80** (a suite and a sweep
run **concurrently** produce false failures — found while recording this increment, and
**O-61's clean-tree precondition turned on the recording step itself**). **O-69** is
**substantially closed for the code** and fully characterised for the spec.

### D-065 — A catalyst calendar that names its sources and omits the schedule, and five sources that lie

**Tier 4 — 6/11 → 7/11.** One function, `next_catalyst_calendar` (Module 13-adjacent,
§16.4), shipped in a new `src/macro_engine/thesis_layer/catalysts.py`, with a new
`CatalystCalendarSettings` config block and `config/settings.yaml` leaves.

**The headline: §16.4's sample returns sources instead of dates.**
`["Next CPI release (FRED release/dates)", ...]` names *where* the answer came from
and never says *when* the event is — and a catalyst with no date is not a catalyst.
The shipped function reaches both hosts and returns **dated** entries (measured live:
PCE 2026-09-30, NFP 2026-10-02, CPI 2026-10-14, FOMC 2026-10-28). **This is the
smaller half.** The larger half is that the *sources* were the hazard, in **five
distinct ways**, none of which a fixture could reveal:

1. **`ptic` is a pagination total, not an event count** — `ptic=2806` for a window
   whose first page holds **50** rows: wrong by **56×**, with no error raised.
2. **The unfiltered FRED path costs one request per calendar day** —
   `economic_calendar.py:188-192` issues **90** requests for a 90-day window and
   reliably times out; the `release_id` path is **one** paginated call. This is why
   `obb.economy.calendar` timed out in an earlier probe — a symptom the project had
   already recorded but never diagnosed.
3. **FRED release 101 `"FOMC Press Release"` answers for EVERY calendar day** —
   **41 of 41** days covered in a 40-day window. A reader trusting it reports the
   next FOMC as **tomorrow, every day, forever**: confident, dated, plausible, wrong.
4. **Flattening the Fed's HTML to text invents meetings** — the real page ends
   `"Note: A two-day meeting is scheduled for January 25-26, 2028."`; a flat parse
   attributes that January to **2027** (**55 hits vs 53 structured**).
5. **The endpoint drops `urllib` and `aiohttp` by TLS/HTTP fingerprint** — `urllib` →
   `RemoteDisconnected`, `aiohttp` → `TimeoutError`, but `curl` and `httpx` on
   **HTTP/1.1** → **200**. OpenBB's FRED provider is `aiohttp`-based, so the
   transport choice is load-bearing, not cosmetic.

Because of defect 3, the FOMC is read from `federalreserve.gov` — **which is exactly
what §16.4 names.** The specification was right; the naive implementation (filter
FRED by `rid`) is what would have been wrong.

**Three defects in this increment's own code**, found because the sweep **refused to
certify its first run** (`applied 10 / killed 8 / survived 4`, two of them carrying
no proof) rather than asserting the survivors away:

* **A warning that fired on correct data** — the release-id/name guard compared the
  abbreviation `"CPI"` against the full name `"Consumer Price Index"`, so it warned
  on **every healthy call**. Fixed by comparing full release names and pinned by
  `test_a_correctly_labelled_calendar_is_silent`: **a guard needs a test that it
  does NOT fire.** A guard that cries wolf trains its reader to ignore it.
* **The horizon bounded the request but not the result** — `horizon_days` went out
  as a query parameter and was never applied locally, so a **1-day horizon still
  returned a 60-day event**; a request parameter cannot *un-return* a row. The test
  written to kill `M1.3` killed a real defect instead.
* **A fixture that could not reproduce the defect it existed for** — the synthetic
  FOMC note carried no year, so the flat-text mutant produced no phantom and `M4.1`
  **survived**. Fixed by copying the page's **real** note verbatim; the live check
  now measures the phantom on the real page (55 vs 53) instead of trusting the
  fixture.

**Sweep and gates.** `scripts/mutation_catalyst_calendar.py` — 10 mutations, 8
groups, **`refuse_on_noop` on** (D-064's lesson 93 implemented rather than
remembered: a mutation whose target text produces no change is a **refusal**, not a
printed note). Final: **10 applied / 8 killed / 2 survivors (1 control, 1 inert)**;
`M7.1` is byte-identical and survived as required. `check_targets` also **caught its
own anchors moving** — the horizon fix rewrote the text `M1.1`/`M1.3` anchored on and
the gate refused to mutate a stale site (D-048). `scripts/live_catalyst_calendar_check.py`
— six checks, **passes**. Gates: ruff + format + `mypy --strict` clean at **161
files**; pytest **1722 passed / 1 skipped / 6 deselected**; `tools/sweep_health.py`
**33 sweeps, 0 failures, 0 leftovers**.

**Carry-overs.** **O-74** (new — live third-party dependency at build time, no cache;
the failure direction is a **silently shorter calendar**, the D-054 shape one layer
up) · **O-75** (new — the `120`-day horizon is `uncalibrated_illustrative` and fails
**asymmetrically**: too short is silence, too long is noise) · **O-76** (new — the
`" + projections"` marker is prose, not a datum, so branching on SEP costs a re-parse;
a typed catalyst is a schema change per §22.13) · **O-72** partially addressed,
since `refuse_on_noop` lives in this sweep and not in the shared harness · **O-70**
unchanged and closer: `build_us_macro_thesis` must supply a real `catalysts=` from
this function rather than §16.4's literals.

### D-064 — A "validated" declaration that validated nothing, and a distribution blind to its own sign

**Tier 4 — 5/11 → 6/11.** One function, `build_scenario_distribution` (Module 12,
§16.4), shipped in a new `src/macro_engine/thesis_layer/scenarios.py`. **This
increment was RECOVERED, not started**: an interrupted session had left the
function, its 38 tests, its config block and `tools/sweep_health.py`'s extension
on disk with **no record of any kind**, and every gate passed on the code as found
— which is exactly why "it passes" is not this project's standard (lesson 92).

**The finding: a one-member `Literal` with no `default=` is still OPTIONAL**

§16.4 declares the payoff unit as
`payoff_unit: Literal["fraction_of_capital"] = Field(description=...)`. Measured
both ways:

| call | old | shipped |
|---|---|---|
| `KellyInputs(scenarios=<bp distribution>, limits=..., payoff_unit="bp_pnl_proxy")` | `literal_error` | **`ValidationError` naming the unit** |
| `KellyInputs(scenarios=<bp distribution>, limits=...)` | **accepted**, labelled `fraction_of_capital` | **`missing`** |

A basis-point payoff entered the Kelly arithmetic as a fraction of capital with
**no error**, producing the *smaller*, cap-slipping number O-50 predicted —
toward **prudence** (the D-057 failure direction). **The defect is not that the
value was wrong; it is that the vocabulary had one member, so there was no wrong
value to pass.** The repair has two halves, and neither alone suffices: the
vocabulary is **widened** to `KellyPayoffUnit` so the wrong unit is **nameable**,
and the field is made **required** with a **named refusal** so naming it is what
fails. **O-50 closed**; the *class* remains open.

**O-51 closed in the same seam.** `ScenarioOutcome` and `MarketPricingGap`
existed **twice** — once in `thesis_layer/schemas.py` and once in the models layer
— as two independent definitions wearing one name. The thesis layer now
**re-exports from the models layer**, so a change on one side is visible to the
other. A duplicated class is precisely what would have hidden a unit change at the
seam the headline defect lived on.

**Three further §16.4 defects, all measured.** Four probabilities and four payoff
multipliers are hardcoded literals while `ScenarioOutcome` validates they **sum to
1**, so the config leaves are **not independently settable** (O-41's shape); an
unconvertible `gap.unit` is refused **by name** rather than coerced; and a
non-meaningful or **zero-magnitude** gap **raises** rather than distributing
nothing, because Q6 should have routed it to no-trade.

**A fifth defect found only by the live check — the distribution is
DIRECTION-BLIND (O-71, severity 3).** A gap of **+1.0%** and one of **−1.0%**
produce **byte-identical payoffs *and* probabilities**. All 38 unit fixtures used
`+1.0`, so none of them could see it; the live gap is **negative**
(`model_below_market`, **−1.00%**). The four outcome names therefore promise a
direction the arithmetic does not carry. It is a **modelling** decision (relabel
sign-symmetrically, or branch directionally) so it is **disclosed** rather than
guessed — documented in the module docstring and recorded as an open issue.
Lesson 91: *a fixture that holds a variable constant cannot falsify dependence on
that variable, however many fixtures you write.*

**Two gates had to be repaired to certify this increment.**

- **`check_anchor_landings` was MANUFACTURING FINDINGS.** It resolved an anchor's
  owning symbol by walking backwards to a line beginning `def ` or `class ` —
  which is **also true of a prose comment**. It attributed `KellyPayoffUnit` to
  `volatility_target_scaling`, **150 lines away**, and refused four sweeps over a
  mis-target that did not exist. **A false positive in a gate teaches you to
  ignore the gate** (lesson 88). Fixed by resolving the owner through
  **`ast.parse`**, with `end_lineno` bounding each symbol — in
  `tools/sweep_health.py` and inlined into the new sweep (importing it made one
  file two modules under `mypy`, because `tools/` has no `__init__.py`).
- **The honesty control was a no-op.** Its first draft was `old == new`, so it was
  never APPLIED and could be neither killed nor survived; the harness **refused to
  certify** on exactly that ground. Replaced with a real rewrite that re-wraps the
  same three string literals across three lines into a **byte-identical** value —
  the source changes, the program does not (lesson 89).

**The repaired control then killed a stale test — and that was the control
working.** `test_the_distribution_is_consumable_by_the_kelly_contract` asserted
`literal_error` while **omitting `limits`**, which **could not pass unless
`payoff_unit` was optional**. The test's own shape was the independent proof that
the default was load-bearing, and it had been written by the session that was
about to certify the opposite (lesson 90). Rewritten to pin **both** directions.

**A derived type alias cannot be a mypy type.**
`KellyPayoffUnit = Literal[*get_args(PayoffUnit)]` is runtime-correct and
`mypy --strict` rejects it (*"Invalid type alias: expression is not a valid
type"*). The literal is written out and the derivation is enforced by a
**test** — set equality over `typing.get_args`: strictly weaker as a type, louder
than a silent drift (**O-73**).

**`sweep_health.py` extended, and O-61 recurred for the third time.** Its
`_legacy_targets()` now resolves a **list** of candidate paths (fixing five false
ABSENT reports for `mutation_lei_proxy.py`) and `_own_target_check()` runs the
tool's own uniqueness check on the **14 ungated sweeps** (O-29). Its leftover scan
then caught a **`SIGTERM`** that had left `M9.1` applied in `risk_budget.py` —
which had also **corrupted two unrelated anchors** whose text it destroyed, so
`check_targets` reported them **ABSENT** (a manufactured finding again).

**It recurred FOUR times in this increment, and the last one was the worst.** An
earlier restore repaired the corrupted anchors but **left the `clipped` line
mutated**, and a later `ruff format` call **baked the residue into the record
set**. It was caught only because `mutation_kelly.py` then reported **25 applied /
27** with two mutations **"NOT APPLIED (no-op)"** — their shared anchor no longer
matched. Three things made it severe: **`sweep_health.py` reported 0 leftovers
both before and after** (its detector searches for the *replacement* string, which
**was** the corruption — **O-72**, demonstrated rather than theorised); the sweep
**still certified** at 25/27 with 0 survivors, because a no-op silently left the
denominator; and **every gate was green on the corrupted tree** — ruff, format,
mypy and **1705 passing tests**, since `bool(x) is True` equals `x` for a `bool`.
Restored; `mutation_kelly.py` then reproduced **27/27 killed, 0 survivors**
exactly, which is what confirms the restore.

**O-61's binding rule (never sweep in the background; never batch sweeps) was
violated again and this is the argument that ends the debate: the clean-tree
precondition is no longer a nice-to-have.** A second remedy this produced: **a
sweep should REFUSE when any mutation reports `NOT APPLIED`** rather than dropping
it from the denominator — a no-op means the anchor no longer describes the code.
Two new open issues record what the tool still cannot see: a **stale kill**
(**O-72**) and the fact that it runs **by hand** rather than in CI.

**Added**
- `src/macro_engine/thesis_layer/scenarios.py` — `build_scenario_distribution`,
  its four outcome-branch constants, the distributable-verdict partition, the
  convertible-unit set and the three refusal paths.
- `src/macro_engine/portfolio/risk_budget.py` — `KellyPayoffUnit`, the
  now-**required** `payoff_unit` field, and the named unit refusal.
- `tests/thesis_layer/test_scenario_distribution.py` — **38 tests**.
- `tests/portfolio/test_fractional_kelly.py` —
  `test_the_unit_must_be_declared_at_all` (pins `field.is_required()`) and
  `test_the_consumer_vocabulary_is_derived_from_the_producers`.
- `scripts/mutation_scenario_distribution.py` — **23 mutations, 8 groups, 5
  files**; `scripts/live_scenario_check.py` — **10 assertions on live FRED**.
- **4 lessons (86-92)** and **2 new open issues (O-71, O-72, O-73)**.

**Changed**
- `scripts/mutation_kelly.py` — re-anchored for the required field and **extended
  25 → 27** (`M4.3` the refusal removed, `M4.4` the vocabulary re-narrowed), so
  the unit seam is covered from both sides; **27 / 27 killed, 0 survivors**.
- `tools/sweep_health.py` — AST-based `enclosing_symbol`, `_legacy_targets()`
  returning a list, `_own_target_check()` for the ungated sweeps.

**Gates at close:** ruff + format + `mypy --strict` clean at **157 files**
(was 153); `pytest -m "not live"` **1705 passed / 1 skipped / 5 deselected** (was
1670/1); scenario sweep **23/22/1 (control)**; kelly sweep **27/27**;
`tools/sweep_health.py` **32 sweeps, 0 failures, 0 leftovers**.

### D-063 — The thesis builder cannot execute its own Q8: a `dict` compared with `< 0`, and a gate a sentence could satisfy

**Tier 4 — 4/11 → 5/11.** One function, `derive_invalidation_conditions` (Module
14, §16.2 Q8 / §20.15), shipped in a new
`src/macro_engine/thesis_layer/invalidation.py` — **the first thesis-layer
function in Tier 4**. **37 new tests**, a 24-mutation sweep across **two files**
(**9 groups**) and a **pulled** live check over 8 real series driving **4 real
upstream models**.

**The finding: the specification's `TypeError`, reproduced on real data**

§20.15 writes `if inflation.value < 0`. `ModelResult.value` is a union and
`inflation_convergence_classifier` publishes
`InflationConvergenceVerdict(...).model_dump()` — a **`dict`**:

```
TypeError: '<' not supported between instances of 'dict' and 'int'
```

The crash is **latent**: §16.2's Q1 passes `inflation_breadth_score` (a float), so
the builder's current call path survives — while **§20.15's own docstring names
the dict-valued model**. The same section's `build_confirmation_signals` guards
with `isinstance(result.value, (int, float))`; this function does not. **The two
halves of §16.4 disagree about the contract they share.**

**Three further defects, each a different class**

- **`growth` is declared and never read** (D-037's class, in the function that
  decides what falsifies the whole thesis).
- **The fallback sentence SATISFIES the LTCM gate it says is unmet.** Measured:
  `TradeIdea` **accepts** *"No clear evidence-based invalidation condition
  identified — DO NOT promote this thesis past DRAFT"* as a live trade's
  `stop_or_invalidation`. A presence check on a field whose sentinel value is a
  valid presence — D-052's *"a guard must be a PARTITION, not a HIT"*, through the
  schema.
- **The model §20.15 names is direction-blind.** It attributes *"broad-based
  reacceleration"* to `inflation_convergence_classifier`, whose vocabulary is
  `HIGH / MEDIUM / LOW / CONFLICTED` and whose `agreeing` field is the majority
  **count**, not the majority **side**. Measured: the verdict carries **no**
  direction field, so "reacceleration" is not computable from it.

**Changed**

- **`derive_invalidation_conditions` returns `InvalidationAssessment`, not `str`**
  — a deliberate, recorded divergence from §16.4's declared signature. A bare
  string cannot represent "no falsifier was found" in a way the gate can consume,
  because both states are non-empty. `text` is **empty** when nothing was
  identified, so `TradeIdea` refuses a live trade and the builder must route to
  `no_trade_thesis(...)`: **the LTCM gate becomes load-bearing.**
- The narrowing is explicit and total: signed scalars are read from `int`/`float`
  **excluding `bool`** (`isinstance(True, int)` is `True`); verdicts only from a
  dict whose `classification` is a member of the classifier's **own** vocabulary;
  every other shape is **reported**, never crashed on and never silently skipped.
- Both signs now produce a condition. §20.15's two `< 0` tests could only ever
  describe a thesis leaning on loosening and disinflation, so a thesis leaning on
  tightening had **no falsifier at all**.
- Two falsifier *forms* are distinguished: a signed signal **reverses**
  (`crosses_back_positive` / `crosses_back_negative`); an agreement classifier's
  agreement **collapses**. A signal exactly on the crossing produces none.

**Added**

- `InvalidationCondition`, `UnreadableInput`, `InvalidationAssessment` (all
  `frozen=True, extra="forbid"`), `InvalidationTrigger`, and the
  `invalidation:` config block (`zero_crossing_threshold`,
  `supporting_agreement_class`) with `InvalidationSettings` + 2 accessors.
- `tests/thesis_layer/test_invalidation.py`,
  `scripts/mutation_invalidation.py`,
  `scripts/live_invalidation_check.py`.

**Findings**

- **O-68** (severity 3) — the LTCM hard gate is a presence check any caller can
  satisfy with the fallback sentence.
- **O-69** — §16 names three different inflation models for one argument slot.
- **O-70** — the Q8 round-trip is asserted against a hand-built `TradeIdea`,
  because `build_us_macro_thesis` does not exist; the caller's seam is untested.

**The sweep's own lesson:** `M1.5`'s first draft wrote
`neutral.append(...) or unreadable.append(...)`. `list.append` returns `None`, so
`None or X` **still ran X** — the mutant never changed the program and survived.
**A mutant that does not change the program is not a test gap.**

---

### D-062 — Module 15 complete: a sign the specification never checks, and a gate that had to be invented

**Tier 4 — 3/11 → 4/11.** One function, `construct_cross_market_rv` (Module 15.3,
§20.12), shipped in `models/yield_curve.py` beside its D-059/D-060 siblings — so
**Module 15 is complete, all four of its functions**, and **the instrument half of
Tier 4 is finished**. **50 new tests**, a 41-mutation sweep across **two files**
(**9 groups**) and a **pulled** live check over 8 real US cross-market pairs in two
independent stress states.

**The finding: §20.12 defaults its headline number's sign to the wrong value, and nothing checks it**

`degradation = correlation_normal − correlation_stressed`, with
`correlation_stressed` defaulting to the literal **`0.9`** in the model body. Over
8 real pairs the *normal* correlation runs **−0.623 .. 0.820**, so on the
specification's own default the published `hedge_degradation` is **negative for
8 of 8 pairs**: the specification asserts, universally and silently, that the
hedge **improves** in a crisis — the opposite of the premise its own docstring
states, and the LTCM leverage trap rather than good news. The arithmetic is right;
the sign is never checked.

**A new failure direction: FALSE REASSURANCE.** After D-054 silence · D-056 false
confidence · D-057 prudence · D-058 false executability · **D-062: the number says
the risk fell when the risk rose.**

**Added**

- `CrossMarketRVInputs` and `construct_cross_market_rv` in
  `models/yield_curve.py` — 17 published keys, `country="us"`, confidence via
  `compute_confidence`.
- `cross_market_rv:` config block (3 leaves) + `CrossMarketRVSettings` + 3
  accessors. `max_abs_hedge_degradation` is a `fitted_assumption` measured over 8
  real pairs.
- `tests/models/test_cross_market_rv.py` (50 tests),
  `scripts/mutation_cross_market_rv.py` (41 mutations),
  `scripts/live_cross_market_rv.py`.
- **`tools/sweep_health.py`** — the sweep-health check O-62 asked for. Loads all
  30 sweeps, runs each one's `check_targets` / `check_anchor_landings`, scans for
  a leftover mutation, exits 1 on failure. Reports 30 sweeps / 0 failures /
  0 leftovers, and names the 14 that still carry no gate (O-29).
- `check_anchor_landings` and `_slice_source(..., after=)` in the new sweep — a
  gate that proves an anchor lands in the function it was written for, which
  `check_targets` cannot do.

**Changed**

- `correlation_stressed` is now `float | None`; `None` reads
  `settings.risk.stress_correlation` — §21.1's own assignment, and the **first
  consumer** of `RiskSettings.stress_corr`, which had zero callers anywhere in the
  tree.
- The `N·D`-vs-`N·P·D` gap is now reproduced in a **third** constructor, and the
  measured correction is **two-signed** on both stress definitions.

**Fixed**

- `country="global"` → `"us"`, with a mandatory scope warning naming §22.3 and
  §22.3.1's refusal to fabricate a cross-market RV against an unbuilt country.
- The input contract now refuses: one market on both legs, an empty label, a
  duration outside the measured band `[0.25, 30.0]` years, a correlation outside
  `[−1, 1]`, a non-positive notional.
- `inputs_used` now lists all 8 fields (was 4 of 7).
- `confidence=0.5` → `compute_confidence` (§22.8).

**Findings**

- **O-64** — §20.12's own text still says `country="global"`.
- **O-65** — `risk.stress_correlation = 0.9` is not reproducible from any measured
  pair (worst 0.858 / 0.736) and overstates.
- **O-66** — no `ThesisType` names a cross-market relative-value trade, so the
  `select_instrument` seam **cannot** be closed (unlike D-059/D-060).
- **O-67** — `check_targets` proves an anchor is unique, never that it is in the
  right function. Two mis-targets in one session.
- The live check **corrected this increment's own config note** ("about 3x
  headroom" → **1.56x** once the VIX tail counted) — the first time that has
  happened before the record set rather than after.

---

### D-061 — The O-62 repair: a mis-target, two stale anchors, and a newline-lossy harness

**No function shipped; this is harness work.** `scripts/mutation_credit_spread.py`
rebuilt to the current standard, `tests/models/test_credit_spread.py` +2 tests, all
**96 `write_text` sites** in `scripts/` + `tools/` made newline-faithful, and the
working tree normalised to LF with a new `.gitattributes`.

**The finding: the audit's diagnosis was wrong, in the way that matters**

D-060 recorded this sweep's survivor `C1d` as *"a REAL missing test"*. Executing
the gate the file did not have showed **three** problems instead: `C1d` was
**AMBIGUOUS** (8 occurrences — `str.replace` rewrote `CreditTrendBaseRates` while
the model reads `CreditSpreadBaseRates`), and `M4a`/`M5e` were **ABSENT** because
D-043 had legitimately moved the source. A **mis-target plus two stale anchors**,
not a coverage gap — and a correctly-targeted `C1d` is killed by the test that was
**already there** (measured: exit 1 vs exit 0).

**Fixed**

- `mutation_credit_spread.py`: `check_targets`, `check_tests_collect`, an honesty
  control, `_EXPECTED_INERT`/`_INERT_PROOFS` with exit-2 refusal, `-x` and a
  SIGTERM/SIGINT restore handler. **34 applied / 33 killed / 1 survivor (the
  control), exit 0.**
- Two published keys with **no mutation at all** gained one (`M5g`, `M5h`); `M5g`
  gained the test it was missing.
- **Every sweep in the repo was newline-lossy.** `Path.write_text` translates
  `"\n"` to `os.linesep` while `read_text` normalises, so a sweep's restore was
  stable in memory and **lossy on disk** — the D-060 commit captured a repo that
  was **90 files CRLF / 76 LF**, and `git status` reported whole-file
  modifications with **no content change**, destroying the clean-tree precondition
  the sweep gates depend on. All 96 sites now pass `newline=""`; verified by
  re-running the full sweep and confirming both touched files are **byte-identical
  to HEAD**.

---

### D-060 — Tier 4 continues: a breakeven rule that hedges the wrong quantity, and does so with no guard at all

**Tier 4 — 2/11 → 3/11.** One function, `construct_breakeven_trade` (Module 15.2,
§15.1b), shipped in `models/yield_curve.py` beside its D-059 sibling — so
**Module 15 is now complete**. **31 new tests**, a 26-mutation sweep across **two
files** (**9 groups**) and an **offline** `bond_math` cross-check that **asserts a
disagreement with the shipped rule rather than excusing it**. **The failure
direction is a fifth one: toward a plausible-but-wrong number, in both directions.**

**The finding: the rule matches duration, but the exposure cancels on dollar duration**

§15.1b's rule is `N_nom = N_tips · D_tips / D_nom`, and it reproduces exactly. But
the exposure it claims to cancel — level, PC1 — cancels on **dollar** duration
`N·P·D`. The gap has an exact closed form:

```
shipped = N_t·D_t/D_n    exact = N_t·P_t·D_t/(P_n·D_n)
⟹  shipped/exact = P_n/P_t   ⟹  exact = shipped · P_tips/P_nom
```

Both legs priced through the shipped `bond_math`, over **48 real configurations**
(TIPS coupons 0.125%–8%, real yields 0.5%–3.5%, breakevens 0.5%–2.5%): the
correction runs **−56.38% .. +98.72%**, and it **changes sign at the TIPS leg's own
par price** (20 over-hedge / 28 under-hedge). At $10mm TIPS notional the worst case
misstates the nominal leg by **~$5.6mm**. **Because it is two-signed, no constant
adjustment can hedge it** — the exact rule needs the legs' *prices*, which the
contract does not carry. **Recorded as O-59** (severity 3); the fix direction is a
§20.11 contract change.

D-059 already recorded that this rule is not level-cancellation (O-57, 1.23%, cash
curve legs). What is new is that for a **breakeven** — TIPS against nominal, not two
nominals of one credit — the approximation is the **dominant** error in the model
rather than a footnote.

**The second finding: where the sibling had a dead guard, this one had none**

§15.1b's breakeven constructor publishes **no residual and no `warnings` list at
all** — no validation of any kind. A duration wrong by 10×, a swapped TIPS/nominal
pair, or a `tenor` of `"2yr"` produced a silently wrong notional with no trace.

**Added**

- `construct_breakeven_trade(inputs) -> ModelResult` — duration-matches a two-leg
  breakeven trade. Publishes **twelve** keys: `notional_tips_long`,
  `notional_nominal_short`, `nominal_to_tips_notional_ratio`,
  `duration_ratio_tips_to_nominal`, `duration_dollars_tips`,
  `duration_dollars_nominal`, `net_duration_residual`,
  `net_duration_residual_is_definitional`, `tenor`, `tips_duration_years`,
  `nominal_duration_years`, and `duration_direction`.
- `BreakevenTradeConstructor` — `extra="forbid"`; `tenor: str`,
  `tips_duration`/`nominal_duration` (`gt=0`), `target_notional_tips` (`gt=0`),
  `duration_is_modified: bool = True`. Two `model_validator`s add what the spec
  omits: a per-leg duration/tenor band `[0.15, 1.05]`, and a **ratio** band
  `[0.5, 1.6]` plus a refusal of identical legs.
- A warning on **every** call disclosing the N·D-vs-N·P·D gap and naming the exact
  correction, and a conditional warning when `duration_is_modified=False` — where
  the Macaulay/Modified mismatch is a **relative** error between the legs (their
  yields differ), not the small shared scaling the curve constructor warns about.
- `scripts/live_breakeven_trade.py` — the mandated cross-check. Asserts the closed
  form to `1e-6`, measures the correction over the real configuration space,
  refutes §15.1b's "the TIPS leg is always longer" (the nominal is longer in
  **19 of 48** real pairs), and closes the **D-058/D-060 seam** — a
  **two-keyword** round-trip (`tips` **and** `breakeven` both survive in
  `_RATES_KEYWORDS`, so either keyword breaking fails loudly).
- `scripts/mutation_breakeven_trade.py` — 26 mutations, 9 groups, two files. Six
  anchors are **sliced** from source because D-059's class sits in the same file
  with byte-identical validator text (the D-051 sibling-class trap).
- `tests/models/test_breakeven_trade.py` — 31 tests.

**Changed**

- `config/settings.yaml` — two `mechanical_rule` leaves in `curve_trade:`:
  `breakeven_duration_ratio_min: 0.5` and `breakeven_duration_ratio_max: 1.6`,
  with their measurements on the leaf per O-38.
- `CurveTradeSettings` gains the two `CalibratedValue` fields and the
  `minimum_/maximum_breakeven_duration_ratio` properties; both constructors share
  the class deliberately.

**Fixed**

- **The config band note's range was not reproducible from shipped code (O-60).**
  It recorded `0.7624 .. 1.3790`, measured by a **simplified local pricer inside
  the probe**. Re-measured through the shipped `bond_math`: `0.6820 .. 1.5528`. The
  *count* (72 of 192 below 1.0) reproduced exactly; the *range* did not — partial
  agreement, which is the most treacherous form of O-30's defect because it reads
  as corroboration. **The consequence was material:** against a shipped ceiling of
  `1.6`, headroom narrowed from a claimed 14% to a real **3%**. Corrected in
  `settings.yaml` and the source docstring.
- **A test gap the sweep found, not a defect to excuse.** `M6.1` (invert the
  residual guard) survived because the shipped warning is *absent* for every input
  and nothing asserted the **absence** — D-038's "absence half". Added
  `test_no_residual_warning_is_ever_published`, which also asserts the residual is
  `0.0` so the absence assertion cannot go vacuous.
- **A stale exemption retired.** `M1.3` had been listed inert-by-construction in an
  earlier draft; the new absence test **kills** it, so it was removed from
  `_EXPECTED_INERT` and the harness no longer emits a stale-exemption note.
- **The sign claim in the live check was wrong and was corrected.** The first draft
  asserted the shortfall was one-signed ("always too small"). Tracing the failed
  fixture showed `shipped/exact = P_nom/P_tips`, which with a par nominal reduces
  to `100/P_tips − 1` — positive exactly when the TIPS is **below** par. The check
  now asserts two-sidedness over counts on both sides.

**Gates**

`ruff check src tests tools scripts` clean · `ruff format --check src tests tools
scripts` clean (**145** files) · `mypy --strict` clean (**145** files) · **pytest
1583 passed / 1 skipped** (1552 → 1583) · mutation sweep **26 applied / 23 killed
/ 3 classified survivors** · live cross-check **PASSED** · sweep **re-run at close**.

> **The gate invocation was itself a defect (O-63).** The first pass ran
> `ruff check` **with no path**, which reports **1703 errors** and **36 files to
> reformat** — ruff has **no `files` key** (mypy does; §10.2/D-035), so it walks
> `.probe/` and the scratch trees. The scoped command above is the real gate. A
> comment in `pyproject.toml` now records this; nothing enforces it, so a single
> gate script remains the open remedy.

**Carried out of this increment (all three recorded, none fixed)**

- **O-61 (sev 3, incident).** A sweep run **in batches in the background** was
  killed mid-flight, leaving `inflation_nowcast.py` and `convergence.py` holding
  **falsified copies**. The leak was **silent** — a sweep whose anchor no longer
  matches takes the *pattern-not-found* path and reports a **survivor**, not an
  error — so two corrupted files presented as two weak tests. It surfaced hours
  later as **8 failures in modules D-060 never touched**, and the first
  hypothesis ("stale anchor") produced **wrong edits to an anchor and a new
  test**, both reverted. Tree restored to **1583/1**. **Binding: never sweep in
  the background; never batch sweeps.** Remedy: a clean-tree precondition.
- **O-62 (sev 2).** A full audit of `scripts/` found **three broken sweeps**
  (`mutation_drawdown.py` exit 2, four AMBIGUOUS; `mutation_credit_spread.py`
  exit 1, unexplained survivor `C1d`; `mutation_convergence.py` exit 2 from the
  incident, **CLOSED** at `56/53/3` once restored) and **no sweep-health check**.
  The project's strongest gate is the one nothing gates.
- **O-63 (sev 2).** The documented ruff gate is not the reproducible one.
- **Repaired, not merely recorded:** D-060's new class shares byte-identical
  validator source with D-059's, which turned **eight** of D-059's sweep anchors
  AMBIGUOUS — the **D-051** trap. `mutation_curve_trade.py` was extended past
  each shared prefix and reproduces its original `31 applied / 26 killed / 5
  survived` exactly.

### D-059 — Tier 4 continues: the specification's only guard on a curve trade was a tautology

**Tier 4 — 1/11 → 2/11.** One function,
`construct_duration_weighted_curve_trade` (Module 15.1, §15.1b), shipped in
`models/yield_curve.py` — the module §15.1b names, so this increment had **no
layering collision**. **50 new tests**, a 31-mutation sweep across **two files**
(**9 groups**) and an **offline** `bond_math` cross-check. **The failure
direction is a fourth one: toward an unverifiable claim** — the guard that is
supposed to catch a wrong duration provably cannot.

**The finding: §15.1b's guard is the definition, not a check**

`net_duration_residual = (N_s·D_s) − (N_l·D_l)` where `N_l := N_s·(D_s/D_l)`
algebraically simplifies to **0 for every input**, correct or not. A duration
wrong by a **factor of ten** produces an indistinguishable result. Measured over
a 1377-case grid: **1185 exact zeros**, 192 float-noise values, worst
`9.766e-04` — **9.8% of the 0.01 tolerance**, i.e. a **10× margin, not an
infinite one**. The guard becomes **reachable above ~$2tn notional**, so the
exemption is a **scale condition** and is recorded as **O-56** rather than
silently asserted.

**Added**

- `construct_duration_weighted_curve_trade(inputs) -> ModelResult` — notional
  weights a two-leg curve trade so net duration cancels:
  `N_long = N_short · (D_short / D_long)`. Publishes `notional_short`,
  `notional_long`, `notional_long_to_short_ratio`, `duration_dollars_short`,
  `duration_dollars_long`, `net_duration_residual`,
  `net_duration_residual_is_definitional`, `short_tenor`, `long_tenor`,
  `short_duration_years`, `long_duration_years`, `direction`.
- `CurveTradeConstructor` — the input contract, with `duration_is_modified`
  (required attestation, default `True`) and `is_steepener` (default `True`), and
  **two validators**: `_legs_must_be_distinct_and_ordered` and
  `_durations_must_be_plausible_for_their_tenors`.
- `_tenor_years(tenor)` — a deliberately narrow parser: lower-cases, requires a
  `y` suffix and a positive number, and **refuses** `"2yr"` / `"6m"` / `"2w"` /
  `""` / `"abc"`. `"2yr"` is refused *on purpose* — silently normalising a
  different unit suffix would hide a unit mismatch.
- `tests/models/test_curve_trade.py` — **50 tests**: the hand-computed arithmetic
  (`1_959_157.63`, ratio `0.195916`, duration-dollars `18_420_000`), the
  tautology **pinned as a live fact**, the notional-rounding artefact, the band
  (floor / ceiling / moved leaf / inclusive-ceiling boundary), leg ordering,
  tenor parsing, both warnings, the result contract, and the two defaults.
- `scripts/mutation_curve_trade.py` — **31 mutations, 9 groups, two files**.
- `scripts/live_curve_trade.py` — **offline** cross-check against `bond_math`.

**Fixed — two real test gaps and one wrong mutation, found only by the second sweep run**

- **The sweep's first run reported `31/31 killed, 0 survived` — a perfect score,
  and false.** Almost every "kill" named the **same** test, which is only possible
  if it fails on **unmutated** source: it asserted ``implausible for '2y'``
  against a validator message naming the **long** leg (`'3y'`). The **honesty
  control was killed too**, which cannot happen for a semantically identical
  program — and *that* is what exposed it. D-051 built the control; this is the
  first time it fired.
- **`M6.3` (steepener default flipped)** survived because the direction test
  passed `is_steepener` **explicitly in both states**, so the default was never
  tested. Two tests added.
- **`M4.5` (only the short leg band-checked)** survived because every
  band-failure fixture used a bad **short** duration. Three tests added.
- **`M6.2`'s anchor was wrong, not the test**: it replaced only the first of four
  physically concatenated string lines, and the asserted phrase (`"1-2%"`) lives
  on the third. The anchor now **slices its target from the source file at import
  time**, so it cannot drift — the generalised fix for D-058's `CX4` class.

**Found — a claim in the specification that is true only in a special case (O-57)**

§15.1b says duration-weighting *"cancels level (PC1) exposure"*. Cancellation
requires equal **dollar** duration, giving
`N_l = [N_s·D_s/D_l] · (P_s/P_l)` — so the shipped rule is exact **only when
both legs trade at the same price**. The live cross-check asserts the **exact
relation** and it holds to **0.0004**; for a 4.5%/4.3% pair the two legs price at
`100.38` / `101.61`, so duration-weighting is off true level-cancellation by
**1.23%**. Negligible for near-par **futures**, material for **cash bonds**.

**Found — two defects in already-shipped Tier 1 code and in my own probe**

- **`price_bond`'s `coupon_rate` field documents itself as "ANNUAL" while the
  implementation is per-period** (a par bond needs `coupon_rate == yield_rate`).
  A caller following the docstring prices a bond that is not near par, with **no
  error**. The unit tests miss it because they test the formula, not the
  convention. Recorded as **O-58**.
- My own first draft of the cross-check reproduced exactly that unit error, and
  the resulting 26% disagreement was briefly read as a finding about the
  specification. **It was withdrawn before it reached the record** — the
  attribution step comes before the reporting step.

**Changed**

- `config/settings.yaml` gains a `curve_trade:` block — three `mechanical_rule`
  leaves with their measured provenance recorded in the notes:
  `duration_to_tenor_min: 0.15` (measured floor `0.1740`),
  `duration_to_tenor_max: 1.05` (zero-coupon limit `1.0000`),
  `net_duration_display_pct: 0.01` (§15.1b's literal **re-purposed** as display
  precision, no longer presented as a test of the inputs).
- `config.py` gains `CurveTradeSettings` and `Settings.curve_trade`.
- **No registry change** — the inputs are durations and tenors, not series.

**Opened**

- **O-56** (sev 2) — the unreachability exemption is a **scale condition** the
  harness cannot express; it would lapse above ~$2tn notional.
- **O-57** (sev 3) — §15.1b's level-cancellation claim holds only when both legs
  price alike; whether to weight by **dollar** duration is a §20.11 interface
  change.
- **O-58** (sev 2) — `price_bond`'s `coupon_rate` docstring contradicts its
  behaviour; both fix directions are breaking.

**Gates:** ruff clean · format **142** files · mypy `--strict` **142** files ·
pytest **1552 passed / 1 skipped** · sweep **31 applied / 26 killed / 5
proven-inert** (control survived) · live cross-check **PASSED** · sweep
**re-run at close** after formatting.

### D-058 — Tier 4 begins: the instrument router asks the universe instead of restating it: the instrument router asks the universe instead of restating it

**Tier 4 opens — 0/11 → 1/11.** One function, `select_instrument` (Module 15,
§22.3.1 / §22.12), in a **new module** `models/instrument_selection.py`, with
**two new test files** (**63 + 30 tests**), a mutation sweep across **three
files** (**31 mutations, 7 groups**) and an **offline** live cross-check.
Eleven probe findings, of which **two were latent defects in already-shipped
code** — and **the failure direction is new again: toward false executability.**

**Added**

- `select_instrument(inputs, universe)` — the §22.3.1 router. Maps a
  `ThesisType` + `GapDirection` onto an instrument, and returns a **dict**
  (`instrument`, `universe_category`, `executable`, `rationale`,
  `direction_word`) on executable branches or a **bare sentinel string**
  otherwise.
- `ThesisType` (`str, Enum`, **7** members), `GapDirection` (`str, Enum`),
  `InstrumentSelectionInputs` (with a `_tenors_only_belong_to_curve_trades`
  validator), `InstrumentUniverse` (a module-level `Protocol` so `models/` can
  annotate the universe **without importing `thesis_layer/`**),
  `_parse_tenor_years`, `_build_curve_instrument`, `_sentinel_result`,
  `_selection_value`, the constants `ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT`
  (`"ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT"`) and
  `BLOCKED_MULTI_COUNTRY_NOT_BUILT`.
  **CORRECTED (D-071):** this line claimed the sentinel's value was `"NONE"`.
  Measured against every commit in the history, the constant has *always* been
  the self-naming string above; the parenthetical was wrong in the original
  entry and the error propagated into **O-53**'s statement of the risk. See
  **O-93**.
- `tests/models/test_instrument_selection.py` — **63 tests**: the routing
  contract, the `gap_direction` **consumption** path, config-sourced curve legs
  (including **custom** legs), degenerate leg pairs parameterised on the
  exception **message**, the computed confidence, and two hand-written universe
  stand-ins.
- `tests/thesis_layer/test_production_universe.py` — **30 tests**, the **first
  tests `ProductionUniverse` has ever had** (probe P8 found it had none).
- `scripts/mutation_instrument_selection.py` — **31 mutations, 7 groups**, across
  `instrument_selection.py`, `thesis_layer/schemas.py` and `config.py`.
- `scripts/live_instrument_selection.py` — **offline by design**: the input is a
  label and a direction, so there is no series to pull. It is a **cross-check
  against the real `ProductionUniverse`** — the check O-43's lesson demands.
- `config/settings.yaml`: an `instrument_selection:` block (line 1488), **7**
  `CalibratedValue` leaves — `thesis_type_routes` (an **envelope** carrying
  `routes`), `curve_default_short_tenor: "2y"`, `curve_default_long_tenor:
  "10y"`, `curve_minimum_leg_gap_years: 1.0`, `curve_maximum_leg_years: 30.0`,
  `is_heuristic_not_calibrated: true`, `source_independence_count: 0` (an
  **honest** zero: this function consumes no series).
- `config.py`: `InstrumentSelectionSettings` with a `routes` accessor that
  **validates the envelope** rather than trusting it, plus `Settings.instrument_selection`.

**Fixed — two latent defects in code that had already shipped and passed every gate**

1. **`ProductionUniverse` had no curve vocabulary at all.** §22.3.1's own worked
   example, `"2y10y US Treasury steepener"` (the specification's literal), was
   **inadmissible** by §16.4's keyword sets. `_RATES_KEYWORDS` now carries
   `steepener` / `flattener` / `steepening` / `flattening` / `butterfly` /
   `duration-weighted` / `curve`, with bare-tenor handling tuned to the
   **authoritative** ordering (excluded vocabulary checked **before** the category
   keywords — `"commodity index futures"` must not read as equity).
2. **The FX matcher was a false-positive machine.** `_keyword_match` admitted any
   six-character word whose **first three** letters were a G10 code, so
   `"europe equity"` matched the **FX** family and a US equity thesis would have
   been routed as a currency pair. It now requires **both** halves of a six-char
   token to be G10 codes, with `/`-pair normalisation and a module-level
   `_G10_CURRENCY_CODES`.
3. **The sentinel was matched case-sensitively.** `permits()` and
   `category_for()` compared against `"NONE"` exactly, so a lowercased `"none"`
   fell through to the keyword matcher and was rejected as *out-of-universe*
   rather than recognised as the sentinel — the right answer for the wrong
   reason. Both paths now use `instrument.strip().upper()`.
4. **`gap_direction` was declared and unread.** It is now a validated
   `GapDirection` **enum** *and* it is **consumed**: it selects the published
   `direction_word` (`POSITIVE → "steepener"`, `NEGATIVE → "flattener"`). The
   D-037 "declared, consumed, unreachable" class, repaired at the point of
   declaration rather than at the next increment.

**The architectural collision, and the repair pattern**

`select_instrument` is in `models/`; the vocabulary deciding what the production
universe admits (`ProductionUniverse`) is in `thesis_layer/`, and the layering
rule forbids `models/` importing upward. `universe` is therefore a **required
argument** typed by a `Protocol` declared **inside `models/`** — the D-046
pattern (receive the vocabulary; do not own it). The second-order payoff was the
point of the increment: because the router **asks** rather than **restates**, the
asking immediately **indicted the answerer** — findings 1 and 2 above are defects
in `thesis_layer/schemas.py`, invisible to every gate until something consulted
it.

**The sweep — 31 applied / 27 killed / 4 survivors, 0 unexplained**

The **first** run left **6 survivors, all test defects** — the increment's most
useful output. All closed: `M2.1` (a pair failing *two* guards, so the exception
**message** is the only discriminating assertion), `M8.5` (the fixture's comment
did not contain the phrase the ordering needs), `M8.3` (**inert by redundancy** —
`permits()`'s fast path is rescued by its own delegate, and `M8.4`, mutating the
delegate, *is* killed), `CX1`/`CX2` (the replacement literal **equalled** the
config value; the test now **moves the config leaf** to `3y`/`7y`) and `M6.4`
(unobservable because an **earlier guard raises**).

`_INERT_PROOFS` now carries **four** entries across **three** classes —
**unreachability** (`M3.3`, `M6.5`), **redundancy** (`M8.3`) and **invariant**
(`M6.4`, new this increment). The honesty control `M9.1` is **killed**.
`check_targets` refused **once** (`CX4`: the anchor was the accessor's
**docstring** line, not its `return`), and `check_tests_collect` is a **new**
harness gate added here.

**The live cross-check** re-derives §22.3.1's curve literal from the shipped legs
(P1's regression guard), routes **all 8** executable `(thesis_type, direction)`
pairs through the **real** `ProductionUniverse`, confirms both sentinels carry a
**computed** `0.5` rather than a literal, and asserts the curve legs come from
**config**. Print: `LIVE CHECK PASSED`.

**Opened:** **O-53** (sev 2 — two `ThesisType` members return sentinels by
construction, and the sentinel reaches `TradeIdea.instrument` as an unrecognised
string, so the two "no instrument" spellings are confusable with an instrument
and with each other); **O-54** (sev 1 — the `Protocol` is
not runtime-enforced); **O-55** (sev 1 — a third inert class with no tag).
**CORRECTED (D-071):** this sentence originally read *"`"NONE"` is a legal
`TradeIdea.instrument` value"*, which is true of `NO_PRODUCTION_INSTRUMENT` but
**not** of this sentinel — the two are different strings in the shipped code.
The corrected risk is the *opposite* one and is worse: not a sentinel that reads
as a no-trade, but a sentinel that reads as **nothing the system recognises**.
See **O-93**.

### D-057 — Kelly's real formula replaces a labelled placeholder, and the unit trap moves three modules away

**Tier 3 closes — 14/15 → 15/15 ✅ COMPLETE.** One function,
`apply_fractional_kelly` (Module 17.3, §20.14/§22.6), appended to
`portfolio/risk_budget.py` with a **new test module** (**52 tests**), a mutation
sweep (**25 mutations, 10 groups**) and an **offline-by-design** live check.
Eleven defects. **The failure direction is new: toward prudence.**

**Added**

- `generalized_kelly_fraction` — the **real** Kelly: the grid-search
  expected-log-growth optimum `f* = argmax_f SUM_i [p_i · log(1 + f·r_i)]`.
  Publishes `at_search_edge`.
- `apply_fractional_kelly` — applies the **mandatory** fractional divisor and the
  position cap. Published keys include `full_kelly_fraction`,
  `requested_fraction`, `final_fraction`, `clipped`, `direction`,
  **`limits_declared_but_not_enforced`**.
- `KellyInputs`, `SizingOutcome`, `_expected_log_growth` in
  `src/macro_engine/portfolio/risk_budget.py`. `__all__` 12 → **15**.
- `tests/portfolio/test_fractional_kelly.py` — **52 tests**, every expected value
  hand-computed, including §20.14's mandatory golden test.
- `scripts/mutation_kelly.py` — **25 mutations, 10 groups**; `check_targets`
  **0 problems** on the final run.
- `scripts/live_kelly_check.py` — **offline by design**: a cross-check against an
  **arithmetic oracle**, not a provider pull.
- `config/settings.yaml`: `kelly.grid_points: 100001` (`mechanical_rule`, the
  leaf's note records the **400×** measurement).
- `config.py`: `KellySettings.search_points` with a `points < 2` floor, plus
  `kelly_fraction_multiplier = 1.0 / divisor`.

**Fixed — a placeholder the specification had shipped in prose, and a unit contract three modules away**

1. **§17.3's `raw_kelly = ev / 100` is a placeholder incorrectly labelled
   Kelly.** §22.6 defines the real criterion as the expected-log-growth optimum;
   §22.13 makes the deletion mandatory. Deleted. **Only
   `generalized_kelly_fraction` may call itself Kelly** — and the deletion itself
   is **not mutation-testable**, which the sweep's docstring states rather than
   obscures.
2. **The grid resolution was a literal.** `n_grid = 1000` was specified; the
   shipped grid is **100001** points read from config. `fraction = index /
   (grid_points - 1)` gives a step of exactly `1e-5` and lands **exactly** on the
   binary closed-form optima.
3. **The divisor was a literal.** `kelly_fraction_multiplier` is now
   `1.0 / divisor`, with a load-time floor (`k >= 2`) that refuses a
   non-fractional Kelly.
4. **§22.6's payoff-unit contract is contradicted by the schema the payoffs
   arrive on.** `thesis_layer.schemas.ScenarioOutcome.unit` **defaults** to
   `"bp_pnl_proxy"` — the exact unit §22.6 forbids. The guard catches the loss
   side and is silent on `+120`, a legal 12000% gain. **The wrong unit produces a
   SMALLER, safer-looking number** — the project's fourth failure direction, and
   the hardest to see because the error *removes* the signal rather than
   corrupting it. → **O-50**.
5. **Two classes are both named `ScenarioOutcome`** — a class-level collision
   `mypy --strict` demonstrably does not detect. → **O-51**.
6. **The sweep now carries three inert-proof exemptions**, two of them
   **unreachability** proofs whose truth is bound-dependent, and the harness
   records **presence** of a proof, not its **strength**. → **O-52**.

**The sweep — 25 applied / 21 killed / 4 survivors, 0 defects**

Three survivors are **proven inert**: `M5.4` by **EQUIVALENCE** (`min(a, b)` and
its guarded form are the same function written two ways), `M3.3` and `M7.1` by
**UNREACHABILITY**. `M9.1` is the **honesty control** and survived as required.
`M7.1`'s proof is a **finding**: the state `SizingOutcome` documents as
`clipped_by_position_limit` **with a zero result** is unreachable, because the cap
carries a field bound `gt=0.0` (verified over **200 000** draws, **0**
disagreements). The closing test asserts that reachability fact.

**The sweep found three genuine coverage gaps** — `M1.2` (the context-string claim
was untested), `CX1` (`search_points` was never read from config; the fixture must
use **777** points, because **1001's step is exactly `1e-3` and would not
discriminate**) and `CX2` (the `points < 2` floor). All three closed with new
tests; `CX` re-ran **3 / 3 killed**.

**The harness had to be fixed twice while this ran.** Without `-x` the selection
takes **~40 minutes** rather than **~95 s**; and when the run was killed,
**`SIGTERM` bypassed the `finally` that restores the mutated file** — D-049's
failure mode recurring — leaving `M5.2` (a hardcoded divisor) then `M9.1` applied
in `src/`. Both repaired by hand. `-x` is now **unconditional** and the harness
installs a **SIGTERM/SIGINT handler** that restores the in-flight mutation.
`check_targets` refused **twice**, both **self-inflicted** (an AMBIGUOUS anchor
appearing twice; an anchor written on the **wrong side of its own swap**).

**The live check is offline by design.** Kelly's input is a caller-supplied
distribution, so no series could falsify it — the honest check is a **cross-check
against an oracle**. The shipped grid versus the binary closed form
`f* = (p·b − q·a)/(a·b)`: **3.33e-16** worst absolute error over 80 combinations.
It then refutes the deleted placeholder on the live config, reads the divisor out
of the shipped YAML, and reproduces the P5b search-edge collapse
(`distinct REQUESTS: 1 of 3`, `distinct GROWTHS: 3 of 3`).

### D-056 — A constraint that is inert exactly where the risk is, and four limits nothing read

**Tier 3 continues — 13/15 → 14/15.** One function, `volatility_target_scaling`
(Module 17.2, §20.13), appended to the existing `portfolio/risk_budget.py` with a
**new test module** (**45 tests**), a mutation sweep (**23 mutations, 9 groups**)
and a live check (five real ETFs, 1 938 sessions). Six defects, and **the entire
constraint enforcement is one one-sided `min`**.

**Added**

- `volatility_target_scaling`, plus `RiskLimits` (4 fields, `from_settings()`,
  `unread_by_vol_targeting`) and `VolTargetInputs` (4 fields, all bounded `gt=0`),
  in `src/macro_engine/portfolio/risk_budget.py`. Published keys:
  `raw_scale`, `requested_exposure`, `final_exposure`,
  `clipped_by_leverage_ceiling`, `pre_existing_leverage_breach`,
  **`de_risking_fraction`**, `direction`, `leverage_ceiling`,
  **`limits_declared_but_not_enforced`**.
- `tests/portfolio/test_volatility_target.py` — **45 tests**, every expected value
  hand-computed, including §20.14's mandatory golden test
  (`test_vol_target_respects_hard_limits`).
- `scripts/mutation_voltarget.py` — **23 mutations, 9 groups**; the **first**
  increment to carry an entry through the `_INERT_PROOFS` no-proof-no-certification
  gate.
- `scripts/live_voltarget_check.py` — five sections and **two** cross-checks, both
  real calls.
- `config/settings.yaml`: five new hard-limit leaves under a
  `Module 17.2 / 17.3 — the hard risk limits (RiskLimits)` block, all
  `institutional_convention` — `max_position_pct_of_portfolio: 0.15` (**fraction**),
  `max_factor_exposure_pct: 0.30` (**fraction**), `max_leverage: 3.0` (**multiple**),
  `min_liquidity_days_to_unwind: 2` (**days**),
  `vol_target_reflexivity_scale: 0.8` (**scale**, previously a literal in the body).
- `config.py`: five accessors and `_reject_percent_in_fraction_field`, a unit guard
  that raises a message naming the unit.

**Fixed — the only enforced limit is inert where the risk is, and four others have no reader**

1. **`final = min(scaled, max_leverage)` is a one-sided upper bound.** On the
   de-risking side — the side a vol target exists for — it cannot bind. Measured
   live: the clip fires on **0 of 444 sessions** while the reflexivity warning
   fires on **13.1%**. Repaired by publishing `de_risking_fraction`, because a
   **94%** cut was reporting `clipped=False`, which reads as "no constraint
   engaged". The failure **direction** is D-054's — toward silence.
2. **Four of five declared `RiskLimits` had zero references anywhere in the
   repository** (`max_position_pct_of_portfolio`, `max_factor_exposure_pct`,
   `max_drawdown_trigger_pct`, `min_liquidity_days_to_unwind`) — the D-037 class.
   The repair is **disclosure** (`limits_declared_but_not_enforced`), and the
   distinction from enforcement is recorded as **O-48**.
3. **§20.14's mandatory golden test is a HIT, not a PARTITION** (lesson 49): it is
   phrased about `max_leverage` alone and passes while four limits stay unenforced.
   A companion test now asserts the untouched limits are *reported*, so "not
   tested" cannot be mistaken for "enforced".
4. **A pre-existing leverage breach was reported as a vol-target adjustment.**
   Gross 5.0 against a 3.0 cap is cut to 3.0 — right arithmetic, wrong
   **attribution**. Now a separate `pre_existing_leverage_breach` flag, and the two
   clip causes produce mutually exclusive warnings.
5. **`current_gross_exposure`'s unit was unstated.** The vol identity
   `realised == target` holds for **every** gross under the multiple reading, which
   is what fixes it; the reading is now documented on `VolTargetInputs`.
6. **`vol_target_reflexivity_scale` was a literal in the function body** (a
   §21 violation). Now a config leaf with an accessor.

**Changed**

- **O-45 resolved by deletion.** `RiskLimits.max_drawdown_trigger_pct` restated the
  ladder's first rung (`10.0` percent, verified equal) and is **unreachable** from a
  signature with no drawdown input. The ladder governs (it is a pre-commitment),
  so the duplicate field is **removed**: `RiskLimits` ships with **4** fields.
- **O-43 discharged.** `live_drawdown_check.py` §4 now **calls**
  `volatility_target_scaling` instead of re-implementing §20.13; its disclosure
  paragraph is replaced by one that says so, recorded rather than deleted.
- Four pre-existing tests in `tests/portfolio/test_risk_budget.py` were repaired —
  three because `RiskSettings` gained five required leaves (a shared
  `_HARD_LIMIT_LEAVES` dict replaces five repeated literals), one because `__all__`
  legitimately grew by six names across D-055 and D-056.

**Tooling**

- `scripts/mutation_voltarget.py` — `check_targets` **0 problems** on the first
  run; `check_tests_collect` clean; FOREGROUND ONLY; re-run at close.
- The first sweep run was **16 killed / 7 survivors**: **five real gaps** closed
  with new tests, **one harness defect** (`M7.1` inserted a second `model_config`
  above the class docstring and the real one below shadowed it — INERT BY
  CONSTRUCTION), and `M6.1`, which ships as the first `_INERT_PROOFS` entry.

**Verified**

- `ruff check` clean · `ruff format --check` **131** · `mypy --strict` **131** ·
  `pytest -q` **1383 passed / 1 skipped**.
- `mutation_voltarget.py`: **23/23 applied, 21 killed, 2 survivors** — one proven
  inert (**INERT BY ANCHORING**, conditional proof) and one honesty control that
  **survived as required**; 0 defects.
- `live_voltarget_check.py`: **PASSED** — vol **8.33%** vs a **10.00%** target,
  scale **1.2010×**; clip rate **0.0%**, reflexivity **13.1%**.
- `live_drawdown_check.py`: **PASSED** with the O-43 upgrade.

**Opened**

- **O-48** (severity 3) — the four inert `RiskLimits` fields are **reported**, not
  **enforced**. D1's repair is disclosure; a consumer assuming otherwise repeats
  the mistake.
- **O-49** (severity 2) — the clip has no lower bound and none is needed, but the
  **asymmetry is undocumented in §20.13**.

---

### D-055 — A drift check that could not see an instrument it was not told about, and two proofs of equivalence of deliberately different strength

**Tier 3 continues — 12/15 → 13/15.** One function, `check_rebalancing_drift`
(Module 17.3, §20.13), appended to the existing `portfolio/risk_budget.py` with a
**new test module** (**58 tests**), a mutation sweep (**64 mutations, 12 groups**)
and a live check (five real ETFs, 504-session covariance). **Four defects, all one
shape: an input the function was not given is treated as a confident zero.**

**Added**

- `check_rebalancing_drift`, plus `RiskBudgetTarget`, the `DriftDirection`
  (`over`/`under`) and `RebalancingOutcome` (`balanced`/`rebalance`) `Literal`s,
  in `src/macro_engine/portfolio/risk_budget.py`.
- `tests/portfolio/test_rebalancing_drift.py` — **58 tests**, every expected value
  hand-computed; plus `_values_of` / `_values` narrowing helpers so
  `mypy --strict` can see through `ModelResult.value`'s union.
- `scripts/mutation_rebalancing.py` — **64 mutations, 12 groups**.
- `scripts/live_rebalancing_check.py` — five sections; **calls**
  `evaluate_drawdown_rules` rather than re-implementing the comparison.
- `config/settings.yaml`: `risk.rebalancing_drift: {value: 0.10,
  calibration_status: mechanical_rule}` (**fraction** convention) and its
  `RiskSettings.rebalancing_drift_threshold` accessor.

**Fixed — a book drifted into unbudgeted instruments reported `balanced`**

1. **A target with no current value read as `0.0`**, not as unknown — making an
   omission a **maximal underweight on no evidence**. Now disclosed via the
   published `missing_instruments` census.
2. **A position with no target was never iterated at all**, so a book drifted
   **entirely** into unbudgeted instruments reported `balanced`. Now disclosed via
   `unbudgeted_instruments` — the §15.19-D census discipline, and the same defect
   D-050 found in `four_pillar_scorecard`.
3. **The threshold's unit was unstated for the third consecutive increment** — a
   **fraction** leaf (`0.10`) whose name carries `_threshold` not `_pct`, beside
   `_pct` leaves carrying **percent**. Now named in the **guard message**
   (`"A value above 1.0 is a percent written into a fraction field."`), which is
   the only place that runs.
4. **`>` is strict at the boundary — and the boundary fixture did not sit on it.**
   `0.25 + 0.10 - 0.25 == 0.09999999999999998` is a hair *below* `0.10`, so the
   "exactly at the threshold" test passed while being unable to distinguish `>`
   from `>=`; the mutant swapping them **survived**. Rebuilt on the binary-exact
   pair `0.225 - 0.125 == 0.10` (verified: `>` is `False`, `>=` is `True`).

**Changed**

- The module header now states the **failure direction** rather than only the
  behaviour: D-054's ladder fails toward *silence*, this function fails toward
  **false confidence**. Both are fail-safe-looking outputs produced by a missing
  input, and both are worse than an exception.
- `tests/portfolio/test_risk_budget.py` — three `RiskSettings(...)` constructions
  gained the new required field, a real consequence of the new config leaf and
  caught by `mypy --strict`.

**Tooling — the harness now enforces its own excuses**

- `scripts/mutation_rebalancing.py` is the **first increment in this repository to
  populate `_EXPECTED_INERT` with proven entries** (D-053 and D-054 both shipped
  it deliberately empty, per O-42), and the two proofs are deliberately of
  **different strength**: `M4.6` is inert **unconditionally** — the
  `abs(signed) > threshold > 0` guard removes `signed == 0` from the direction
  test's domain entirely — while `CX3` is inert **conditional on the shipped
  config**, because the `float()` cast is the identity on a `builtins.float` leaf
  and would become load-bearing if the leaf ever became a `str` or `Decimal`.
- The harness **refuses to certify an excused mutation that carries no proof**:
  `_INERT_PROOFS.get(name, "(PROOF MISSING)")` plus an early `return 2`.
- Three harness defects were found by running it: three `check_targets`
  **AMBIGUOUS** anchors (`"outcome": outcome,`, `warnings: list[str] = [`,
  `is_heuristic_not_calibrated=True,` each appear **twice** in the module, once
  per function) were re-anchored; one mutation was **INERT BY ANCHORING** (an
  inserted `model_config` was shadowed nine lines below, so the code under test
  never changed); and one mutant rewrote only **half** a two-part guard message.

**Verified**

- `ruff check src tests tools scripts` — All checks passed (128 files)
- `ruff format --check` — 128 files already formatted
- `mypy --strict src tests tools scripts` — no issues in 128 source files
- `pytest -q` — **1338 passed, 1 skipped** (was 1280/1)
- mutation sweep, re-run **at close** per the increment's brief — **64/64 applied,
  61 killed, 3 survivors, 0 defects** (2 proven inert, 1 honesty control)
- live check — **passes end to end**: `σ_p = 8.33%`; **SPY 35.0% of notional →
  56.14% of RISK**; `UUP` `−1.48%`; trip rate **9.7%** at the configured 10%; the
  cross-check against `evaluate_drawdown_rules` is a **real call**

**Opened**

- **O-46** — `RiskBudgetTarget` can only express **non-negative** shares, so a real
  diversifying leg (`UUP` at `−1.48%`) has no legal target.
- **O-47** — a partitioned risk-contribution vector must be **renormalised**, and
  nothing enforces it; the sum-to-one warning fires *after* the wrong number is
  published.
- **O-45 remains open** and is now sharper: `risk.rebalancing_drift` is a **third**,
  fraction-convention leaf beside percent-convention leaves in the same block.

### D-054 — A de-risking ladder that could never fire, and a failure mode that was silence

**Tier 3 continues — 11/15 → 12/15.** One function, `evaluate_drawdown_rules`
(Module 17.3, §6.6c/§17.3), in a **new package** (`portfolio/`) with a **new test
package** (**65 tests**), a mutation sweep (**47 mutations, 13 groups**) and a live
check (five sections, 2 513 real daily SP500 observations). **Five defects, one of
which is a 100× unit conflict between the specification and its own config.** The
accessor it consumes had **no consumer at all** before this increment.

**Added**

- `src/macro_engine/portfolio/` — **new package**, `risk_budget.py` holding
  `evaluate_drawdown_rules`, `resolve_drawdown_rule`, `DrawdownState`,
  `DrawdownRule`, and the `RuleOutcome` `Literal`.
- `tests/portfolio/` — **new package**, `test_risk_budget.py`, **65 tests**, every
  expected value hand-computed.
- `scripts/mutation_drawdown.py` — **47 mutations, 13 groups**,
  `_EXPECTED_INERT` deliberately **empty**.
- `scripts/live_drawdown_check.py` — five sections, real data only.
- Two module constants in `config.py` (`_MIN_DRAWDOWN_TIER_PCT`,
  `_MIN_RISK_REDUCTION_PCT`).

**Fixed — every ladder rung was unreachable, and the rule failed toward inaction**

§6.6c declares `DrawdownRule.threshold_pct` and `.risk_reduction_pct` as
**fractions** (`gt=0.0, le=1.0`). `config/settings.yaml` writes
`risk.drawdown_thresholds.tiers` as **percents** (`{drawdown_pct: 10.0,
risk_reduction_pct: 50.0}`). Read across with no conversion that is a **100×**
error, and the consequence is not an aggressive ladder — it is a **silent** one:
no threshold can ever be crossed, so the function reports *"no risk-reduction rule
triggered"* **at a 90% drawdown**. For a **de-risking** rule, failing toward
inaction is the worst available failure mode, and it is the **opposite** of the
direction the probe predicted. Normalised at **exactly one boundary** (`_tiers()`)
and made checkable at load time: `DrawdownTier._reject_fraction_scale_entry` now
**refuses** a tier written in fraction convention inside a percent field.

**Fixed — four further specification defects**

- `risk_reduction_pct` was **unbounded**; a 500% "reduction" was a legal config.
  Now `(0.0, 100.0]` in the percent field, `(0.0, 1.0]` after conversion.
- §6.6c's "evaluated in order" **contradicts** its own "most severe wins". The
  resolution is a **max**, and the result is **permutation-invariant** — pinned by
  a test that reorders the ladder, so an "early break" implementation is now
  provably a different function.
- `max(key=severity)` and `max(key=threshold)` are **indistinguishable on the
  shipped ladder** and divergent off it, so shipped config alone could never tell
  them apart.
- `0.0` was ambiguous between *"nothing fired"* and *"fired, prescribed zero"* —
  repaired with a `RuleOutcome` `Literal`, which then required **two kinds of
  test**: a runtime value assertion *and* a `typing.get_args()` assertion, because
  a `Literal` is **not enforced at runtime**.

**Recorded — the defect class that does NOT apply**

`docs/PROGRESS.md` had predicted this function (and `volatility_target_scaling`)
were **"gate chains over a path"** — the compositional shape behind D-050/051/052.
The probe showed it is **neither**: no path, no chain, and a **max rather than an
accumulating ladder**. The base-state rule (lesson 5g) **also does not apply** —
this is not a classifier and its modal label (`no_action`, **82.9%**) is
**correct**. Both non-applications ship as tests asserting the **reason**, because
**an unrecorded non-application is indistinguishable from an oversight**.

**Fixed — the sweep found four genuine coverage gaps, then three of its own bugs**

The first run was **42 / 47**. `M5.1`/`M5.2` (a `Literal` losing a member — no
runtime value assertion can see this), `M5.3` (the stop gate at `0.99`, which only
differs inside `[0.99, 1.0)`), and `CX3` (the tier **ceiling** — the floor was
tested, the ceiling was not) were each closed with a new test. The harness itself
discarded `expect_killed` while rebuilding mutations from a 4-tuple, so the
correctly-surviving honesty control was reported as an unexplained defect.
`check_targets` then refused **three** runs — two `ruff format` reflows and one
mis-transcribed constant that was **INERT BY CONSTRUCTION** — the concrete warrant
for re-running the sweep at close. Final: **46 / 47 killed, 1 survivor (the
control)**.

**Fixed — two bugs in the live check itself**

A hardcoded 2007–2010 episode FRED does not serve (`SP500` is a **rolling ~10-year
window**, already recorded in `series_registry.yaml`), and a monotonicity
assertion over consecutive path observations that reported **52 violations — every
one a recovery**. That assertion is simply wrong: a recovery **is** a shallower
drawdown. The property that holds over a path is **path-independence** (2 154
distinct drawdowns, **0** disagreements), not time-monotonicity.

**New carry-overs:** **O-43** (the cross-check against §20.13 is a
re-implementation and must become a real call), **O-44** (`.probe/` makes the
unscoped `ruff check` count unusable), **O-45** (`RiskLimits.max_drawdown_trigger_pct`
restates this ladder's first rung in a different convention, with no precedence).

### D-053 — A threshold that made `stable` the base state, and a config pair that was not independently choosable

**Tier 3 continues — 10/15 → 11/15.** One function,
`project_inflation_trajectory` (Module 3.6, §16.2/§18.6), in a **new model module**
with its config group, test module (**47 tests**, new file), mutation sweep (**24
mutations, 10 groups**) and live check (five sections). **Seven specification
defects**, a **7× config error caught by the live check before the record set was
written**, and a sweep that found a **genuine coverage gap of a new shape**.

**Added**

- `models/inflation_trajectory.py` — `project_inflation_trajectory` and its
  `InflationTrajectoryInputs` contract.
- `InflationTrajectorySettings` / `InflationTrajectoryBands` in `config.py`, wired
  into `PhillipsSettings` as `phillips.trajectory`.
- `config/settings.yaml` — `phillips.trajectory` block.
- `tests/models/test_inflation_trajectory.py` — **47 tests**.
- `scripts/mutation_inflation_trajectory.py` — **24 mutations, 10 groups**.
- `scripts/live_projection_check.py` — five sections.

**Fixed — the specification negates twice and the negations cancel**

§16.2 writes `slack = -score/100` then `pc = -beta*slack`, so
`pc = -beta * (-score/100) = +beta * score / 100`. **Positive in the score.** The
first implementation followed the prose and wrote `beta * (-score)`; the first
functional run returned `reaccelerating` for a score of `-100`, the **loosest
possible** labor market. It had passed the config-load smoke test, mypy, and every
unit test written at that point — because the helper `_change_pp` was the same
expression, so the suite asserted the function matched itself. Only **running it on
real input** caught it. Docstring now carries the substitution.

**Fixed — the band and `beta` were not independent configuration choices**

```text
reaccelerating  ⟺  beta*score*fiscal_scale >  upper_pp  ⟺  score >  upper_pp / beta
```

The band's **score-width is exactly `band_pp / beta`**, so the two leaves jointly
fix the partition *and* the slope, and neither can be validated against the other.
**A parameter whose value is only defined relative to another parameter is not a
parameter.** Repaired by giving each its own **estimand**, plus a test asserting
they are independently settable.

**Fixed — §16.2's own thresholds made `stable` the base state at 79.1%**

Measured over **296 real months**. This is **D-047's base-state failure** in a
module with no structural relation to D-047, and a **new sub-shape**: every
`TrajectoryDirection` member *is* reachable, so a reachability enumeration passes,
yet the classifier is effectively two-member. Reachability cannot catch it; the
**base-rate measurement** can.

**Fixed — a 7× config error in a leaf that had already shipped**

`beta_core_inflation_pp_per_score_point` read **0.043**; re-derived from the OLS
slope of the **6-month forward core-inflation change on the labor score**:
**+0.00598** (se 0.00159, t +3.76, R² 0.047, n 290; subsamples +0.0078 / +0.0028 /
+0.0074). Band `±0.15 → ±0.05pp`. **The live check's first estimator failed** —
it re-measured `beta` from the **band corners**, i.e. a contemporaneous *level
spread* for a parameter on a *forward change*, and it partly read back the
configuration it was meant to test. Every other gate passed with `0.043` in place.

**Changed — label mix**

| Direction | Before (§16.2 thresholds) | After |
|---|---|---|
| `reaccelerating` | — | **40.5%** |
| `stable` | **79.1%** | **31.4%** |
| `decelerating` | — | **28.0%** |

**Fixed — five further specification defects.** `fiscal_response_active` used as a
binary gate rather than §18.6's multiplier (effect now published as
`fiscal_scale_applied`); the two agreement branches of `growth_corroboration`
carrying one evidential content; `confidence` a literal (§22.8 → routed through
`compute_confidence()`); an unnamed **estimand**; and a `pykalman`-style
unreachable-parameter shape that is now disclosed rather than implicit.

**Harness — a genuine coverage gap, of a new shape**

All four corroboration states had a test and **`M5.2` still survived**, because
each test drove **one quadrant** and nothing placed the *disagreeing* inputs
against both *agreeing* branches. `probe_m52.py` enumerated the difference: **2
reachable cases**. Repaired with a quadrant-grid test plus a reachability
companion. **Lesson 49: N states with N tests is a hit, not a partition.**
Sweep: **21/24 killed, 3 expected survivors, 0 unexplained**; `_EXPECTED_INERT`
deliberately **empty**.

**Harness — `check_targets` refused twice, both formatter drift**

First `M10.2`'s mis-transcribed leading whitespace (authoring run); then, at
**close**, `source_independence_count` reflowed from one line to three. **Lesson
50: a transcribed harness target is a copy of the source that no gate keeps in
sync — only re-running the harness at close does.** This is the second
formatter-drift in one increment, and it is the concrete warrant for the standing
close-out re-run rule.

**The two brief honours.** The cross-check was built **from the start** against
`cross_asset_transmission` on the **shared labor leg** and is what surfaced the
config error; it required refining lesson 46, since the two functions are *not*
disjoint — a shared input is circular when both sides *consume* it, and
informative when it is what both sides are *claimed to agree about*. The sweep was
**re-run at close** and **refused on a drifted target**.

**Gates:** `ruff check` clean · `ruff format --check` **120 files** · `mypy
--strict` **120 source files** · `pytest` **1215 passed / 1 skipped** (was 1168/1)
· sweep **21/24** · live check **PASSED**.

### D-052 — A gold rule that did not run its own stated trigger, and two base rates no population reproduced

**Tier 3 continues — 9/15 → 10/15.** One function, `cross_asset_transmission`
(Module 5.6, §20.5), with its config group, test module (**52 tests**, new file),
mutation sweep (**58 mutations, 13 groups**) and live check. Seven specification
defects, a composition defect of the D-050 shape **proven by enumeration**, and a
live check that indicted **two config values that had already shipped**.

**The gold rule's stated trigger and its implemented trigger are not the same
one.** §20.5 says gold falls when the **nominal** yield rises. The shipped rule
keys on the **real** leg — which is the correct economics and the **opposite** of
the prose, because the section's own next sentence describes the breakeven-driven
nominal rise that the naive reading gets wrong.

```python
driver = _driver_of(real_change, breakeven_change, settings)
# gold follows the REAL leg: a nominal rise with a falling real yield is the
# "hot CPI, gold up" case Section 20.5's own paragraph says the rule misses.
```

Rather than leave a reader to infer the trigger from the direction of a call,
every output now publishes `driver_channel`, naming the single leg the three
correlated calls came from.

**The composition defect the brief asked to look for was found and proven.** The
driver split tests `both_channels` **before** `real_driven`, so every input that
would reach `real_driven` is consumed earlier — D-050's shape exactly. Two mutants
survived (`M2.7`, `M2.8`) and neither was recorded as a weak test: the prover
**enumerates the admissible space, 643 200 cases, 0 differences** for each, and the
proof re-executes on demand via `--probe-inert`.

**Added**

- `models/inflation_dynamics.py` — Module 5.6: `ASSET_KEYS`,
  `TransmissionDirection`, `SurpriseDriver`, `InflationTransmissionInputs`
  (`extra="forbid"`, with a `_check_change_signs_are_not_degenerate` validator),
  `_driver_of`, `_leg_direction`, `cross_asset_transmission`,
  `_transmission_warnings`. Twelve published keys.
- `config/settings.yaml` — `inflation_transmission:` block: `real_driven_share`,
  `breakeven_driven_share`, `trivial_move_bp`,
  `measured_gold_down_on_nominal_rise_share` (**0.7556**),
  `measured_breakeven_negative_share` (**0.2652**), each with its provenance note.
- `config.py` — `TransmissionSettings` with six accessors and
  `_check_change_signs_are_not_degenerate`.
- `tests/models/test_transmission.py` — **52 tests**, including
  `_value(result) -> dict[str, object]` to narrow `ModelResult.value` once, and
  `_warning_branches()` as a dict of **mutually non-colliding** markers.
- `scripts/mutation_transmission.py` — 58 mutations in 13 groups, with
  `check_targets`, `check_tests_collect`, `_EXPECTED_INERT` with **executed**
  proofs, an honesty control, and a `--probe-inert` mode.
- `scripts/live_transmission_check.py` — eight steps, including the identity
  proof and the disjoint cross-check.
- `config/series_registry.yaml` — `inflation_surprise_bp` registered as
  `blocked:`, with four verbatim `fred_search` probes (O-39).

**Fixed**

- **`gold_call_base_rate` was `0.7779` and is `0.7556`.** The live check's
  recomputation showed a **2.23pp** drift against the monthly figure (daily
  **0.8846**), four times the 0.5pp bar — and **no population reproduced the
  shipped number**. `measured_breakeven_negative_share` was wrong the same way
  (**0.2754 → 0.2652**, 1.02pp). Both were written from the authoring probe rather
  than fetched: **O-30's class, arriving in the config layer instead of the
  registry.** Every gate passed while they were wrong — the unit tests read the
  same config the code reads, the registry loaded, and the population lived in a
  note nothing reads.
- **A config note quoted a daily denominator under a monthly heading** — "5 520 of
  5 910 observations" became **264 of 284 monthly (92.96%)**, with the daily
  figure (**4 347 of 5 930, 73.31%**) stated separately and labelled.
- The increment's own harness: the sweep mis-classified its inert survivors as
  `[DEFECT]` because the classifier tested `mutation.inert_proof` and not
  membership in `_EXPECTED_INERT`.

**The request's two honours, both discharged**

- **The sweep was re-run at close**, not only at authoring (D-051's lesson 43).
  Clean: `check_targets` clean, all proofs hold, **55/58 killed, 3 proven-inert,
  0 defects**.
- **The cross-check was built from the start** — and it had to be *adjusted*,
  which is the subtle part. Comparing the derived real yield against observed
  `DFII10` is **arithmetic, not evidence**: the check's own first step proves the
  identity `DGS10 − T10YIE − DFII10` is exact (**max error 0.000000 over 5 931
  observations**). It was repurposed as the **proof that the derivation is a
  restatement rather than a proxy**, and the real cross-check runs against
  `inversion_probability_adjustment` (D-049) — **disjoint by construction**: a
  same-day long-end decomposition against a short-end level, directional calls
  against a probability, **no shared series** — with a one-year window-overlap
  guard.

**A third kind of inertness got named.** D-050 established *threshold* inertness
and *composition* inertness. `M9.2` — "published value key
`long_duration_growth_equities` altered" — is neither: it rewrites a key's **name**,
and the consumer resolves it under a second alias, so the mutant changes the
namespace and not the value. Three kinds, three remedies.

**Harness finding: a wording collision masquerading as coverage.** `M10.3`
survived with a warning-coverage guard in place, because the guard matched
substrings and `"below the"` occurred in **two** branch texts — deleting one
branch left the guard matching its neighbour. Fixed with mutually non-colliding
markers plus a guard asserting each warning matches **exactly one** marker.

**Note**

- The three correlated equity keys count as **one vote** in the §15.19-D census,
  and `driver_channel` publishes the coupling. Whether the `value` schema should
  carry a machine-readable `derived_from` per key is **O-37**.
- The two `measured_*` leaves now name their population in the note, but the leaf
  still cannot state it as **data** — **O-38**.

### D-051 — A cross-check that indicted a closed module, and a census that counted the wrong inputs

**Tier 3 continues — 8/15 → 9/15.** One function, `classify_convergence`
(Module 12, §22.10 / Finding #10), with its config group, test module (47 → 54
tests), mutation sweep and live check. Seven specification defects in four
groups, the seventh found by this increment's own tests.

**The wiring defect was in a module already shipped and signed off.** The live
cross-check put `four_pillar_scorecard` (D-050) and `classify_convergence`
side by side over **761 real monthly readings** and they **disagreed on 95 of
them**. The cause was not the new function: `four_pillar_scorecard`'s census
handed `count_independent_families()` **all four pillars, including neutral
ones**, so a read with one directional pillar and three neutrals counted three
extra families and reached `HIGH` — where the same directional content alone
reaches `LOW`. The census contract is about which inputs *corroborate*, and a
neutral pillar corroborates nothing:

```python
directional = [
    (name, read)
    for name, read in zip(_PILLARS, inputs.pillar_reads(), strict=True)
    if read.direction != 0
]
```

After the fix the two classifiers agree on **all 81 cells of the 3⁴ space** and
**761 / 761** months. Recorded as lesson 41: *a cross-check between a new
function and an old one is a test of both, and the older one has no reason to
be the correct one.*

**The seventh defect was found by writing a test that asserted the opposite.**
`classify_convergence` accepted an arbitrary `list[ModelResult]` — the shape
`build_us_macro_thesis` Q7 actually holds — and the census was computed over
**every** signal rather than the directional subset, while the agreement
fraction was computed over the directional subset. Two different denominators
in one published object, reachable whenever a neutral signal is tagged.

**Added**

- `models/convergence.py` — `classify_convergence`, `ConvergenceInputs`
  (`signals: list[ModelResult]`, `extra="forbid"`, `min_length=1`),
  `ConvergenceVerdict`. Direction is derived position-independently; `bool` is
  explicitly excluded from the numeric branch, since a flag is not a level.
  Nine published keys plus `directions`. Verdict order:
  `NO_SIGNAL → CONFLICTED → HIGH → MEDIUM → (redundancy LOW) → (weak-agreement LOW)`.
- `config/settings.yaml` — `convergence:` block, five `CalibratedValue` leaves:
  `max_dissenting_signals_high`, `max_dissenting_signals_medium`,
  `min_independent_families_high`, `min_independent_families_medium`, and
  `measured_conflicted_share: 0.6173`, each with its provenance note.
- `config.py` — `ConvergenceSettings` with five properties and a
  `_gates_must_be_ordered` validator.
- `scripts/mutation_convergence.py` — 56 mutations in 9 groups, with
  `check_targets`, `check_tests_collect`, `_EXPECTED_INERT` proofs and an
  honesty control.
- `scripts/live_convergence_check.py` — the cross-check above, plus a re-measure
  of the input space at **0.6173**, matching config to 4 dp.

**Fixed**

- `models/scorecard.py` — the census now counts only directional pillars
  (defect above). Two tests added to `test_scorecard.py`.
- `scripts/live_scorecard_check.py` — one assertion had gone stale against the
  corrected count.
- `scripts/mutation_scorecard.py` — three targets re-anchored after the fix;
  `_CENSUS_DIRECTIONAL` and three mutations added. **84/87 killed, 3
  proven-inert** (was 81/84).

**Two harness defects found by the sweep's own machinery**

- `PYTEST_TARGETS` named `tests/test_config.py`, which **does not exist**.
  pytest exits **4** for a missing path, which the sweep counted as a kill — a
  false **56/56**. Exposed only because the honesty control mutant (which must
  survive) was reported killed. Fixed by removing the path, adding
  `check_tests_collect()`, and redefining `killed` as
  `exit_code not in (0, 4)`.
- Four `check_targets` targets became **ambiguous** once `ConvergenceSettings`
  duplicated `ScorecardSettings`'s validator and accessor bodies verbatim, so
  `str.replace(..., 1)` would have rewritten the wrong class. Anchored on
  class-specific context.

**And a third harness defect, found at record-set close — a test that guarded the
MUTATION instead of the contract.**

Re-running the sweep after the record set was written, `check_targets` refused
the run: `M8.5`'s target was **ABSENT**. The cause was not drift — `M8.5`'s
`old`/`new` arguments were **transposed**, so the sweep was asserting the
presence of the *mutated* string in the shipped source. Correcting the argument
order applied the mutation for the first time, and it **survived**.

The reason it survived is the finding. The test meant to guard this behaviour
asserted:

```python
assert result.inputs_used == ["signal[0]", "signal[1]", "signal[2]", "signal[3]"]
```

— which is the **mutation's output**. The shipped code returns
`["s0", "s1", "s2", "s3"]` (the fixture names), so the test **failed on the real
code and passed only under the mutation**. It had never been run against the
shipped form, because the transposed arguments meant the sweep never applied the
mutation it was named for.

**A test written from a mutation's replacement string guards the mutation, not
the contract, and inverts the sweep meant to detect it.** The test now asserts
against the fixture's own names, with a comment saying why. `M8.5` is killed;
the sweep reads **53/56, 3 classified** (2 deliberate controls + the proven-inert
`M5.7`). Generalised as lesson 42.

**Note**

- The three dissent ceilings are, as in D-050, **the same predicate past the
  `CONFLICTED` gate**. Rather than delete them, they are kept with tripwire
  tests, because deleting them would freeze the current gate order as
  permanent. `measured_conflicted_share` and a uniform-draw space share are
  stored under **different names** (O-33).

### D-050 — A blocking verdict that missed 32 of 50 splits, and a gate order that made its own thresholds inert

**Tier 3 continues — 7/15 → 8/15.** One function, `four_pillar_scorecard`
(Module 12.2, §20.11), with its config group, test module (36 → 51 tests),
mutation sweep and live check.

**The blocking verdict did not block.** §20.11's form classifies a read as
`CONFLICTED` only when the **net** score is zero, so `+1, +1, −1, −1` — genuinely
opposed — was not conflicted, and neither was `+1, +1, +1, −1`. The shipped gate
tests whether **both directions are present at all**:

```python
opposed = up > 0 and down > 0
```

Enumerating all 50 opposed pillar configurations: the specification form
**misses 32 of them**, the shipped form misses none.

**Five specification defects, four found before implementation and one found by
the sweep.** The dissent ceilings (`<= 0 / <= 1 / <= 2`), the family floors, the
`NO_SIGNAL` opt-in, and two hardcoded confidences were the other four. The
`0.7 / 0.6 / 0.4` confidences are refused per §22.8; confidence comes from
`compute_confidence()` and is **flat across all three verdicts at the same family
count** because the verdict is a fact about the world and confidence is a fact
about the measurement.

**The fifth defect is D-047's "declared, unreachable" class inside the repair.**
Because `CONFLICTED` is tested **first** and consumes every opposed read, a read
reaching the dissent gates has `max(up, down) == n`, so
**`dissent = n − max(up, down) == 0` always**. The three dissent ceilings are
therefore the same predicate in practice, the MEDIUM ceiling **cannot bind**, and
the `LOW` "weak agreement" branch is **unreachable by construction**. Enumerating
all **80** non-neutral pillar combinations against three family sets, the
reachable dissent set past the gate is exactly **`{0}`**.

**The gates were kept, with tripwires, not deleted.** Deleting them would freeze
the current gate *order* as permanent; `test_no_read_reaches_the_dissent_gates_with_a_dissenter`
and `test_the_weak_agreement_low_branch_is_unreachable_by_construction` fail if
that structure ever changes.

**Two shares that disagree, and both are right.** `CONFLICTED` is **61.7%** of
the admissible input space (350 of 567) but **66.2%** of **761 real monthly
readings** (1963-01 … 2026-09). The historical share is *higher* because real
pillars are **correlated** — a uniform draw over the space over-represents
mixed-direction configurations the economy rarely produces. `HIGH` 33.0%,
`NO_SIGNAL` 0.8%. Six all-neutral readings occur in real history
(`1963-05 … 2017-10`), reachable only through an explicit `allow_all_neutral=True`
(**O-32**).

**§15.19-D discharged, and it changes the number.** Four unanimous pillars all
tagged `BLS_CPI` are **one vote**: the function tags its inputs, calls
`count_independent_families()`, and passes `distinct_families` — not the pillar
count — to `compute_confidence()`. Measured: 4 families **0.700**, 2 **0.600**,
1 **0.500**. Second §15.19-D consumer to ship.

**The sweep's own lesson.** `mutation_scorecard.py` — 84 mutations, **81 killed,
3 proven-inert** with written proofs in `_EXPECTED_INERT`. The first run left
**17 survivors**, and diagnosing them produced both the fifth defect and a
testing blind spot: **four config accessors were replaceable by their own shipped
literals with the suite green**, because a test that asserts an accessor's
*current value* cannot tell a live config read from a hardcoded copy of that same
number. The replacement asserts against a **perturbed** settings object.
`check_targets` **refused the second run with two ABSENT targets** — self-inflicted,
from line-length rewrapping inside the sweep file itself — which is the gate
catching a mis-target it was written to catch.

Gates: ruff clean, 109 files formatted, mypy --strict clean across 109 files,
**1060 passed / 1 skipped**, sweep 81/84, live check PASSED (761 readings).

### D-049 — A base rate 3.1x too low, two dimensions that are not the same shape, and a window error nearly invisible

**Tier 3 continues.** One function, `inversion_probability_adjustment`
(Module 8, §15.20-B), with its config group, test module, mutation sweep and live
check.

**The specification's base rate does not survive measurement.** §15.20-B supplies
`base_rate = 0.15`. Measured over **592** monthly observations of real
`DGS2`/`DGS10` against `USREC`:

| conditioning set | 12-month-forward recession rate |
|---|---|
| unconditional | 0.209 |
| curve **not** inverted | 0.157 |
| curve inverted | **0.489** |

`0.15` is not a rounded `0.489`; it is **3.1×** low. The literal was not shipped.
`base_rate_recession_prob_12mo` is now a **required input with no default**, so a
caller must supply the number and cannot silently inherit one the data
contradicts. The specification's two hardcoded confidences (`0.3`, `0.35`) are
refused per §22.8; the function returns **0.700 flat across every branch**.

**Two dimensions, two different shapes — and the cap sits at the turning point.**

```
depth is MONOTONE      -0..-25bp 0.412   -25..-50bp 0.417
                       -50..-100bp 0.552  -100bp+   0.857
duration is HUMP-SHAPED  0-4wk 0.250   4-13wk 0.286   13-26wk 0.412
                         26-52wk 0.769  >=52wk  0.520
```

The function multiplies a depth factor by a duration factor, so it assumes both
are monotone. **Depth is; duration is not.** The configured 26-week cap is the
26-52 week boundary — the peak — so the mechanism never reaches the region where
its own assumption fails. The `>=52wk` bucket is dominated by the 2022-07 …
2024-09 inversion (**113 weeks**), whose forward window is open, so the check runs
a **censoring control**; the hump survives it. Recorded as an open calibration
item (**O-31**) rather than absorbed by the cap.

**The forward window is `t+1 .. t+12`, and the off-by-one was nearly invisible.**
Including `t` moves the unconditional rate `0.2095 → 0.2196` and the not-inverted
rate `0.1566 → 0.1687`, while the **inverted** rate — the only one the function
consumes — is **unchanged**. Validating only the consumed rate would have passed
with the wrong window. Caught because the check reconciles all three.

**Three corrections inside the increment's own work.** A **dead warning branch**
(`if base_rate > 0.0 and ceiling <= 0.80:` — always true and config-derived, so it
described a clamp that had not happened) is now driven by a computed
`ceiling_binding`. A **field/property name collision** in `YieldCurveSettings`
made a setting resolve to its `CalibratedValue` wrapper
(`TypeError: ... 'int' and 'CalibratedValue'`); renamed and guarded by two
structural tests. And **four stale figures from the first probe** — the reference
episode dates (wrong by up to six weeks, because the first probe segmented monthly
when the config dates are claims about a *daily* series), the `-25..-50bp` bucket,
the duration table's top two rows, and the 2022-24 episode's length — were
corrected, with the correction recorded in the config docstring.

**Sweeps and gates.** `mutation_yield_curve.py` — 68 mutations, **67 killed, 1
proven-inert** with its proof written into `_EXPECTED_INERT`. The `check_targets`
gate was written in from the start and **refused to run three times** on
mistranscribed or reflowed targets, which is the gate working. `live_inversion_check.py`
PASSED, drift `0.0005`. Gates: ruff clean, 105 files formatted, mypy --strict
clean across 105 files, **1009 passed / 1 skipped**.

### D-048 — A crisis detector that reports no crisis, and a sweep that measured the wrong function

**Tier 3 continues.** One function, `check_trilemma_tension` (Module 1), plus a
structural repair to the mutation harness that is arguably the larger result.

**The function's headline finding.** §15.20-A's rule is a 3-month reserves change
below −10%, and §18.1's reference episode is Black Wednesday (1992-09-16). On
`TRESEGGBM052N` the UK's 3-month reading that month is **−5.37%** — *inside* the
threshold. The specified rule does not fire during the crisis it exists to
detect. D-048 adds a **1-month acute-break test** (−7%, fires on 7.8% of months)
alongside it:

```python
depleted_3mo = trend_3mo is not None and trend_3mo < depletion_threshold
broke_1mo    = break_1mo is not None and break_1mo < break_threshold
```

and reaches `CRITICAL_PEG_STRESS` through either. The two are **not nested** —
verified on real history, the UK breaches each alone in 53 and 30 months, Korea
in 35 and 14 — which is why the acute branch tests the 1-month measure rather
than "either".

**Two further corrections to the specification.** The confidences
(`0.7/0.6/0.4/0.8`) are gone per §22.8, replaced by a value that is **flat across
severities** because severity is a fact about the world and confidence is a fact
about the measurement. And the `or 0` trap — `(x or 0) < -0.10` — is replaced by
an explicit `is not None` guard, so an **absent** reading stops counting as
evidence of calm.

**The cadence finding.** The live check's gap-free assertion **failed on its
first run**: `TRESEGGBM052N` reports **843 observations but only 837 are
monthly** — the first six are annual. Every threshold here names a number of
months, so a "3-month change" across that prefix spans *years*. Indonesia is
worse (700 → 668). Base rates re-measured over the monthly span only:
**10.6% / 7.8% over 834** (from 10.8% / 8.2% over 842). Generalised rule: **a
series' observation count is not its measurement window.**

**The sweep repair.** The rebuilt mutation table reported six survivors that
looked like weak tests. They were **rewriting the wrong function**:
`country="us",`, `source_independence_count=0,`,
`depends_on_unobservable=True,` and the `measured` property body each occur
**twice** in their file, and `str.replace(old, new, 1)` takes the first. A
mis-target is worse than a pattern-miss — the file changes, so it looks applied;
the tests pass, because they never exercised the mutated path; and "the suite is
weak" is then concluded about code nobody touched. The runner now **refuses to
start** on an ambiguous or absent target, and the majority of the table is
generated from a behavioural matrix. **60/62 killed, 0 pattern-misses,
2 proven-inert with written proofs.**

**Scope, stated.** §22.3 makes this a US-only build and the dollar floats, so the
fixed-FX leg is never satisfied and the function **can only ever return
`NO_TENSION`** on its supported path. The crisis logic is validated live against
the UK's 1992 and Korea's 1997 history through a labelled fixture; the whole
admissible US input plane is asserted calm, so making it reachable on `us` forces
the change to be stated.

**Amendment, added while closing the record.** Registering the three reserves
series exposed two errors in the increment's own prose and one in its numbers:

1. **Two `verified_value`s were wrong** — GB written as `93221.49` (actual
   `169355.66`) and KR as `411301.2` (actual `421968.56`), because they were
   recalled rather than fetched. §21.0's failure mode reproduced inside the
   record set §21.0 protects: plausible values, no error raised.
2. **The cadence exclusion's SHAPE was wrong where its SIZE was right.** GB and
   KR change cadence once; **Indonesia changes twice** — 16 annual points
   (1950-12..1964-12), then a continuous quarterly block (1965-03..1968-12), then
   monthly. The note said "annual to 1964-11, then quarterly to 1969-11", a
   four-year mis-dating of the usable window.
3. **The exclusion convention was implicit.** GB/KR's first **seven** points are
   annual (`1950-12 … 1956-12`); **six are dropped and the last is retained** as
   the first monthly observation, so the span does not open with a 12-month hole.
   That convention is what makes "6 dropped / 837 monthly" consistent, and it is
   now stated at `_monthly_history` and printed on every run. The live check had
   also printed `monthly from 1956-12`; it now prints `monthly span opens at …`.

All three registry values were re-fetched and match the provider to `< 1e-6` on
both value and date; the live check re-runs **PASSED** with **0.000** base-rate
drift, and the full suite is unchanged at **975 passed / 1 skipped**.

<details>
<summary>Files</summary>

- `src/macro_engine/models/regime.py` — `TRILEMMA_SEVERITIES`, `TrilemmaSeverity`,
  `PolicyDirection`, `TrilemmaInputs`, `_depletion_severity`,
  `check_trilemma_tension`, `_trilemma_thresholds_calibrated`,
  `_trilemma_base_rates`, plus two D-045a two-halves assertions.
- `src/macro_engine/config.py` — `TrilemmaBaseRates`, `TrilemmaReferenceEpisode`,
  `TrilemmaSettings` (with the threshold-ordering validator), and
  `RegimeSettings.trilemma`.
- `config/settings.yaml` — the `regime.trilemma` block.
- `config/series_registry.yaml` — the `trilemma_reserves_gb/kr/id` provenance
  entries (amendment).
- `tests/models/test_trilemma.py` — **new**, 55 tests.
- `tests/models/test_regime.py` — supplies the now-required `trilemma` block.
- `scripts/live_trilemma_check.py` — **new**; cadence wording corrected in the
  amendment.
- `scripts/mutation_trilemma.py` — **new**, 62 mutations, with `check_targets`.
- `scripts/mutation_inflation_convergence.py` — `check_targets` back-ported.

</details>

### D-047 — The conflict gate read two measures and ignored the rest

**Tier 3 continues.** One function, `inflation_convergence_classifier`
(Module 5.3). It is **the first function obligated by §15.19-D**, and the
increment's subject is the discharge of that obligation: D-046 built the
supplier, warned that *the supplier is not the wiring*, and this is the wiring.

```python
tagged, _ = _tagged_measures(inputs, directions)
census = count_independent_families(tagged)
independent_families = int(census.value["distinct_families"])   # FAMILIES
...
confidence=compute_confidence(
    ConfidenceInputs(
        is_heuristic_not_calibrated=True,
        source_independence_count=independent_families,   # not len(directions)
    )
)
```

Six measures spanning two families now score as **two families**. The published
verdict carries `independent_families` and `family_names` **alongside**
`measures_used`, so the divergence between the two numbers is visible rather
than implied.

**Added**

- `inflation_convergence_classifier(inputs: InflationConvergenceInputs) -> ModelResult`.
  `value` is an `InflationConvergenceVerdict` carrying `classification`
  (`HIGH` / `MEDIUM` / `LOW` / `CONFLICTED`), `agreeing` / `opposing` / `flat`,
  `measures_used`, `frac_agreeing`, `attainable_fracs`, `independent_families`,
  `family_names`, `bands_available` and `base_rates`.
- `InflationConvergenceInputs` — three **required** directions (`headline_cpi`,
  `core_cpi`, `core_pce`) and three optional (median CPI, trimmed-mean PCE,
  sticky-price CPI).
- `config/settings.yaml`'s `inflation.convergence` block: `high_threshold`,
  `medium_threshold`, `deep_conflict_share_threshold`,
  `min_independent_families_per_band`, `confidence_ceiling_by_independent_families`,
  and `measured_base_rates` (three-measure `0.866`, six-measure `0.895`).
- 54 tests; live check `scripts/live_inflation_convergence_check.py` (both
  **passed**); mutation sweep `scripts/mutation_inflation_convergence.py`,
  **25/25 killed, 2 inert by design**.

**Three corrections to the specification's own logic, measured on 522 real months**

1. **The conflict gate examined two measures and ignored the rest.** It read
   `headline` and `core`; the other four were decorative with respect to the
   conflict decision. **Measured effect: 6 months, 1.15%** — `2008-12`,
   `2017-03`, `2020-03`, `2020-04`, `2020-05`, `2026-06`. It now asks whether the
   **losing side** reaches `deep_conflict_share` of the whole set, so a 5–1 split
   with one dissenter no longer passes as agreement.
2. **`HIGH` is the base state, not a finding.** It fires **89.5%** of the time at
   six measures and **86.6%** at three — reproducing the config to the decimal,
   because the config was measured from this function. The base rate now travels
   with the verdict. D-029's rule, reached from a new direction: there, a boolean
   carried its frequency; here the whole *classification* is the modal case.
3. **The thresholds are degenerate below `n = 5`.** At `n = 3`, `>= 0.8` demands
   **unanimity** and `MEDIUM` has exactly one attainable value (`2/3`), so
   `MEDIUM` is unreachable at `n = 3` and the conflict gate fires on a **single**
   dissenter (`1 >= 0.25 * 3`). Disclosed at `n < 5` rather than retuned — a
   retune would have hidden the degeneracy behind a number that happens to work
   at one `n`. The reachability proof moved to `n = 6`.

**Changed**

- `config.py` gains `InflationConvergenceSettings` with a **derived and
  cross-checking** `families_for_full_credit` property. The configured
  `confidence_ceiling_by_independent_families` said **3**; the confidence
  constants saturate at **5** (`cap 0.25 / bonus 0.05`). Nothing read the
  configured value, so **no test could fail**. It now derives itself from the
  constants and **raises on disagreement**, so drift is a startup error.

**Data discovery — the O-21 defect class, third occurrence.** §21.1 declared
three inflation dispersion measures blocked. The probe found **two live**:
`MEDCPIM157SFRBCLE` (524 obs) and `PCETRIM1M158SFRBDAL` (594 obs). The function
therefore runs at **six measures, not three** — which is why the `n < 5`
degeneracy had to be measured rather than assumed. `supercore_direction` remains
blocked; the four `blocked:` entries flagged in O-21 are still un-re-probed.

**Known limitations, recorded not hidden.** `core_pce_direction` is required, so
the floor is 3 measures spanning **2 families** and `independent_families` can
only ever be **{2, 3}**. §15.19-D's single-family warning and the confidence
ceiling are therefore **unreachable through the public API** — pinned as
unreachable by tests. The verdict is heuristic, not calibrated; the family
assignment (notably `median_cpi_direction` → `BLS_CPI` rather than `DALLAS_FED`)
is a judgement encoded in the config, not a measurement.

### D-046 — Five signals are not five votes

**Tier 3 continues.** Two functions, `tag_evidence_source` and
`count_independent_families`, plus the vocabulary they share (Module 13,
Section 15.19-D).

**The contract this closes was already in the signature and empty.**
`compute_confidence(ConfidenceInputs)` has consumed a `source_independence_count`
argument since Phase 2. Before this change it was **`0` at every one of its ~15
call sites** in `models/`, because **no function could produce a non-zero value
for it.** Every confidence the system has published was computed as though no
model result had ever had an independent source. Same shape as D-045a's
`at_trend`, one layer up: declared, consumed, unreachable.

The arithmetic: headline, core, trimmed-mean, median and supercore CPI are
**five measures of one BLS survey**. They agree because they are one measurement
reported five ways. Five sub-measures count as **one** family; core PCE is a
separate BEA release and counts as a **second**; a TIPS breakeven is market
pricing and counts as a **third**.

**Changed**

- `ModelResult` gains `source_family: EvidenceSourceFamily | None` and
  `data_quality_flags_present: bool`.
- `EvidenceSourceFamily` (31 members) **moved from `thesis_layer/schemas.py` to
  `models/evidence_family.py`**. It had shipped as an **orphan** there — no
  constructor, no importing test, in a layer that model-layer convergence
  classifiers cannot reach downward. `thesis_layer` now **re-exports** it, so
  `ConfirmationSignal.source_family` and every existing import are unchanged.
  The two paths resolve to the **same object**, asserted as such.

**Added**

- `tag_evidence_source(model_result, family, *, data_quality_flags_present=False)`
  — returns a **copy**; a conflicting re-tag is **refused**, not overwritten;
  records the quality flag **without** rewriting confidence (§22.8).
- `count_independent_families(tagged_results) -> ModelResult` — `value` is an
  `EvidenceTally` carrying `distinct_families`, the sorted `families`
  membership, `tagged`, `untagged` and `duplicate_results`.
- 23 tests; mutation sweep `scripts/mutation_evidence.py`, **17/17 killed**.

**Five corrections to §15.19-D**, each pinned by a test and a mutation:

1. **The tag is a typed field, not a warning string.** The specification appends
   `source_family=<value>` to `warnings` and parses it back with `startswith`.
   Any caller that rewrites, deduplicates or filters warnings destroys the tag
   **silently**, and a hand-written warning can **forge** one.
2. **`count_independent_families` returns a `ModelResult`**, not a bare `int` —
   and substantively, because the count is uninterpretable without its
   **untagged denominator**. Three families from five signals and three from
   nine are different situations.
3. **Tagging does not mutate its argument** — the specification appends to the
   caller's list and returns the same object, relabelling it everywhere.
4. **A conflicting re-tag is refused**, not silently overwritten.
5. **The census's own confidence is not credited for the families it found** —
   the D-027 circularity class. Crediting it would invert the ranking, making
   nine independent sources out-score the same census finding five redundant
   ones.

**The first sweep returned 12/17**, and the five survivors were not one problem:
two **broken** mutations (`object | None` is broader than the enum, so pydantic
still accepted it; and a replacement that was a comment-only no-op), two
**inert** ones (patching an f-string's `{untagged}` while the asserted phrase
survived), and one **weak test** — an invariance test that compared the function
to **itself**, so both sides moved together and dropping the heuristic penalty
was invisible. Fixed by pinning the **absolute** value.

**Not done, stated plainly:** §15.19-D obliges every convergence classifier to
call `count_independent_families()` and use that count rather than the number of
agreeing signals. No such caller exists yet, so the ~15 sites are *suppliable*
but not *supplied*. **The supplier is not the wiring.**

### D-045a — A published axis advertised a member the function could not produce

`GrowthAxis` declared four members and `_growth_axis` returned three. `at_trend`
was a **published contract member no input could produce** — the same
declared-but-unreachable shape as the state grid, one level down. The one test
that touched it asserted the value *is* an axis member, which any member
satisfies; nothing asserted the converse.

**Underneath it, a docstring describing a guard that did not exist.** The
function claimed its final bucket was "explicitly `>= settings_late` rather than
a fallthrough". There is no `settings_late` — the parameter does not exist and
could not be tested against.

**Fixed**

- `at_trend` removed from `GrowthAxis`, with the reason at the declaration. The
  near-trend strip is a sub-split of `above_trend` inside `_select_state`, not a
  fourth bucket; three is the honest count.
- `_growth_axis`'s docstring corrected to describe the code, and the
  fallthrough's safety attributed to the three-band partition rather than to a
  guard.
- `_select_state`'s grid docstring now distinguishes the **cell grid** from the
  **axis vocabulary**, which the three-row presentation had conflated.

**Added**

- `test_the_growth_axis_has_no_at_trend_member`.
- `test_every_growth_axis_member_is_reachable_and_the_boundary_belongs_to_the_upper_band`
  — each declared member is produced by some reading, and a gap sitting
  **exactly** on each configured threshold is assigned to the upper band.
  Nothing previously sat exactly on a threshold, so the strict `<` was
  unobservable.
- Mutation `M7a` re-declares `at_trend` and is **killed** — 39/39 → **40/40**.

**A process finding, recorded because it cost real damage**

The mutation sweep was run **in the background** concurrently with source edits.
It applies a mutation, tests, and restores from a pre-sweep in-memory copy, so
the edits were silently reverted and a test run read `M4b` mid-application.
Terminating it hard then left `M5b` applied — the momentum disclosure replaced
by `"See documentation."`, which broke the string concatenation so the following
sentence became a discarded expression. The `try/finally` restore does not run
under a hard kill. `repair_leftover_mutations()` healed it on the next clean run.
**The sweep owns the source file for its whole duration; it must not run in the
background.**

### D-045 — Tier 3 begins: a regime grid reaching six of nine states, and an axis that is a near-constant

**First Tier 3 function.** Tier 1 and 2 take measurements in and return a number,
so a defect there is arithmetic. Tier 3 composes them, so a defect is a number
that is arithmetically correct and measures the wrong thing at a higher level of
abstraction. Section 6.2's sample code had three; the live check found a fourth.

**The specification's own logic reaches 6 of its 9 declared states**

`slowdown`, `recovery` and `reflation` are unreachable. Their territory is not
merely empty — it is **occupied and mislabelled**: the chain's `else` catches the
entire `trend < 0, -1.5 <= gap < -0.5` band, the textbook slowdown zone, and
labels it `early_expansion`.

Two more, both pinned by tests:

- the `recession` branch requires *falling* inflation, so a 3% negative gap with
  rising inflation returns `stagflation` — the 1974/1980 shape is not called a
  recession;
- `inflation_yoy` and `unemployment_gap` are declared, listed in `inputs_used`,
  and **read by nothing**. `unemployment_gap` is the only independent
  corroboration of slack in the input set (the D-037 inert-input class).

**A fourth defect, upstream, found only by running it**

Over **240 real quarters** (1966-07 … 2026-04) the inflation axis reads `rising`
in **225 of them — 93.75%**. It is defined on the sign of a **3-month
annualized** change, which is a month-over-month measure of the price level, and
the level falls in only a small minority of months. An axis defined on its sign
is therefore near-constant by construction — D-029's pathology (a boolean firing
80% of the time) arriving through a continuous input.

Measured state frequencies:

| state | /240 | | state | /240 |
|---|---|---|---|---|
| `late_expansion` | **117** | | `recovery` | 3 |
| `recession` | 63 | | `slowdown` | 2 |
| `stagflation` | 37 | | `disinflation` | 2 |
| `reflation` | 15 | | `mid_expansion` | 1 |
| | | | **`early_expansion`** | **0** |

Two confirmations that this is the axis, not the grid: **1985-Q3 and 1986-Q1 are
definitionally the disinflation era** and the model returns `reflation` for both;
and the negative at-trend strip defining `early_expansion` was entered by **eight**
real quarters, **every one** with rising momentum.

Measured alternatives: the 12-month change of the YoY rate gives **124 rising /
10 flat / 106 falling**; the 3-month annualized reading relative to the YoY rate
gives **121 / 18 / 101**. Swapping the input redefines a §6.2-declared input, so
it is **disclosed on every output and tracked as O-23** rather than silently
changed.

**Added**

- `models/regime.py` — `REGIME_STATES`, `RegimeState`, `GrowthAxis`,
  `InflationAxis`, `RegimeInputs`, `classify_regime_rule_based`. The published
  `value` carries the state **and both bucketed axes**, so the label is auditable
  rather than an oracle.
- `RegimeSettings` / `RegimeBaseRates` / `RegimeRateValues` in `config.py`, with
  two startup validators (band ordering; non-negative half-widths).
- A `regime:` block in `settings.yaml` — six thresholds, the nine measured state
  frequencies, and `measured_rising_inflation_rate`.
- `tests/models/test_regime.py` — **54 tests**.
- `scripts/mutation_regime.py` — **39 mutations, 39 killed**.
- `scripts/live_regime_check.py` — builds all four inputs from raw FRED
  (`GDPC1`, `GDPPOT`, `CPIAUCSL`, `UNRATE`), applying the O-7 filter and the
  D-009 common-quarter pairing; measures the nine base rates; fails on drift.
- **`docs/MODULE_MAPPING.md`** — the longest-standing carry-over (Session 4),
  generated from the code rather than the specification.
- **The property-vs-field structural guard** in `tests/test_infrastructure.py` —
  the other named carry-over, asserted against a deliberately broken model.
- **O-23** — the near-constant inflation axis.

**Fixed**

- Two stale carry-overs closed; `PROGRESS.md` Tier 2 corrected to 29/29.
- The live check's CPI alignment now uses **calendar-month** arithmetic. An index
  offset silently measured a different span: `cpi[-13]` is **396 days** back, not
  365, because FRED omits **2025-10** from `CPIAUCSL` as it does from `UNRATE`
  (D-025). The absent month is disclosed, never imputed.
- A live check assertion that "CPIAUCSL is monthly" was **wrong on real data** —
  it failed on the first run. Cadence is now a disclosure with the gap printed.
- Mutation **M4b** survived a fixture that chose the one zero configuration where
  the naive replacement agrees. The test now asserts all four.
- The unmeasured-base-rate test would have silently stopped covering its branch
  once the config shipped measured rates; it now patches an unmeasured record.

**Verification**

```
ruff check        All checks passed
ruff format       92 files already formatted
mypy --strict     no issues in 92 source files
pytest -q         841 passed, 1 skipped, 0 failed
mutation sweep    39/39 killed
live check        passes — late_expansion, confidence 0.3
```

### D-043 — two blocks lifted; all 29 Tier 2 functions now run against real data

**The registry carried a false blocking reason for two increments.**

> `risky_credit_growth_pct` | **BLOCKED** | No clean free series for leveraged-loan growth.

**That was wrong.** `obb.economy.fred_search` — a route this build exposes and
which had **never been used** — returns `BOGZ1FL623069503Q`, *Hedge Funds
(Domestic); Leveraged Loans; Asset*, from the Fed's Z.1 accounts, with
observations back to **1945**. D-041 then reasoned *from* that false premise:
"cannot be validated live", a block-check instead of a live run, and a stage base
rate reported as **unmeasurable**. Every one of those was downstream of a claim
nobody re-tested.

**Why it happened:** symbols were guessed rather than searched. A whole increment
was spent on a block-check because one query was never run.

**What the lift bought**

| | before | after |
|---|---|---|
| `minsky_composition_drift` | live check **did not run the model** | **runs it** |
| its stage base rate | **unmeasurable** | **31.4% / 43.1% / 25.5%** over 51 quarters |
| `credit_spread_attribution`'s trend | **MANUAL** | **derived** from `DRALACBS` |
| its `fundamental` predicate rate | **unmeasurable** | **25.9% / 21.0% / 53.1%** over 162 quarters |

**Added**

- `leveraged_loan_holdings`, `total_bank_credit`, `delinquency_rate` in the
  registry; the two Minsky `blocked:` entries **removed** with the reason
  recorded.
- Minsky's three stage base rates; the credit model's delinquency band and three
  trend base rates.
- `CreditTrendBaseRates`; `MinskyBaseRates` extended.
- **O-21** — a block is a claim about the world and it decays.

**Changed**

- Minsky's live check **is now a real run**, not a block-check.
- The credit check **derives** the trend and recomputes its base rates.
- The model's `default_rate_trend_is_manual_entry` → `default_rate_trend_is_caller_supplied`,
  plus `default_rate_trend_derived_route_available`. The "MANUAL ENTRY" warning
  becomes a "CALLER INPUT" warning — the model cannot know which route was used.

**Two proxies, and what each does not measure**

- **`BOGZ1FL623069503Q` is hedge funds' holdings**, a narrower holder base than
  the whole leveraged-loan market — and it **reads exactly zero for 90 of 145
  quarters (1990-Q2 → 2012-Q3)**, a structural break in the Z.1 accounts. Growth
  is undefined across it, so those quarters are **dropped, never imputed**, the
  usable window is **51 quarters from 2013-Q4**, and **the model has never been
  exercised through a systemic banking crisis.** The live check asserts the zeros
  still exist, so a backfill fails loudly rather than going quietly stale.
- **`DRALACBS` is delinquency, not default** — it *leads* the quantity the model
  names. The trend is defensible; the level must not be read as a default rate.

**The trend band, chosen so STABLE stays reachable**

At ±0.02pp the stable state occurs **3.1%** of the time — the dead-branch problem
D-037 and D-040 both found, arrived at from the opposite direction. The shipped
**±0.10pp** gives 25.9% / 21.0% / 53.1%. The skew is disclosed: `falling` is
modal because the sample spans 1985-2026 and the GFC spike dominates.

**Gates**

```
ruff check        All checks passed
ruff format       88 files already formatted
mypy --strict     no issues in 88 source files
pytest -q         788 passed, 1 skipped, 0 failed
mutation sweep    25 / 25 killed
live check        passes end to end — both functions now run live
```

### Tier 2 COMPLETE — 29/29

The last three functions closed together.

**`marginal_risk_contributions` was already done.** It turned out to be complete
and to standard in `models/risk.py` — `compute_confidence()` rather than a
literal, `utc_now()`, full shape/symmetry/normalisation validation, the **Euler
identity** check, and **6 passing tests** — while `PROGRESS.md` still listed it as
`- [ ]`. The checkbox was stale, so the Tier 2 count had been **one low**. No code
changed; the checkbox did.

**`bayesian_update` and `expected_value` shipped** as `models/probability.py`
(**D-042**), with §11.1's three mandated tests by name.

**Three defects corrected in §20.11**

- **No input bounds at all.** `BayesInputs` accepted a prior of 1.5 or a
  likelihood of −0.2. Worse, `ScenarioOutcome` accepted a **negative
  probability** — which passes the sum-to-one check whenever another scenario
  exceeds one: `1.5 + (−0.5) = 1.0`. **A sum test is not a per-value test**, and
  relying on it was the gap.
- **The likelihood-ratio band was asymmetric by accident.** `0.8 < lr < 1.25`
  treats two equally-uninformative ratios as 0.2 and 0.25 apart. Now
  `|lr − 1| < band`, symmetric and externalized.
- **Confidence was hardcoded (0.8 and 0.6).** The Bayesian constant asserts that
  an uninformative update and a decisive one are equally reliable. Both now go
  through `compute_confidence()`.

**Added**

- `BayesInputs`, `ScenarioOutcome`, `bayesian_update`, `expected_value`.
- `ProbabilitySettings` — the LR band, the sum tolerance, the tail multiple.
- 28 tests, including §11.1's `test_bayesian_update_matches_hand_calculation`,
  `test_bayesian_update_lr_near_one_warns` and
  `test_expected_value_rejects_bad_probabilities`.
- `scripts/mutation_probability.py` — 29 mutations, crash-safe runner.
- `_check_probability_models` — a **verification**, not a live check.

**The verification, because these functions have no data dependency**

No series, no wiring, no units, no nulls — the usual live check has nothing to
do. What replaces it is **an independent recomputation by a different
formulation**: the mandated posterior is recomputed via the **odds form**
(`posterior_odds = prior_odds × LR`), algebraically identical and computationally
different, so an arithmetic error in the direct form cannot survive it.

```
posterior (direct form) = 0.7
posterior (odds form)   = 0.7000000000   -> AGREE to 1e-9
tail boundary: EV +5.0000, worst -10.0000, multiple 2 -> strict, exactly on the multiple
```

The boundary fixture is **derived from the configured multiple**. The first
version used payoffs of +10 / −10·m, giving **EV = −5** — negative, so
`tail_dominates` (which requires `EV > 0`) could never be reached and the boundary
was **untestable**. The check failed on its own fixture rather than passing
vacuously.

**What "Tier 2 complete" does not mean**

Every one of the 29 functions is written, tested and mutation-swept. **One has
never been run against real data:** `minsky_composition_drift` has two BLOCKED
inputs (§21.1), so its live check is a block-check (**O-20**). Two others ship
with stated validation limits — the auction tail (O-15) and the credit model's
manual trend (D-037).

**Gates**

```
ruff check        All checks passed
ruff format       88 files already formatted
mypy --strict     no issues in 88 source files
pytest -q         788 passed, 1 skipped, 0 failed
mutation sweep    29 / 29 killed
live check        passes end to end
Tier 2            29 / 29 ✅ COMPLETE
```

### `minsky_composition_drift` (Module 3.4) — Tier 2 → 26/29 · INPUTS BLOCKED

**The registry blocks two of the three inputs, and forbids the obvious
workaround.** §21.1:

> `risky_credit_growth_pct`, `total_credit_growth_pct` | **BLOCKED** | No clean
> free series for leveraged-loan growth … **Do NOT substitute total credit growth
> as a proxy.**

**My first instinct was to proxy it** with C&I loans or total bank credit —
precisely the substitution the specification anticipates and forbids. The
registry caught it before any code was written.

Per the user's decision the logic ships and is fully tested; the **live check is
a block-check that deliberately does not run the model**. Running it with a
stand-in would be the forbidden substitution, and a green run would then read as
validation of something unvalidated. The check verifies both inputs sit in the
registry's first-class **`blocked:`** list and have no `series` entry,
recomputes the one measurable frequency, and measures the defect's exposure on a
series the model may **not** consume.

**The defect: the comparison inverts when credit contracts.** §20.3 tests
`risky > total * 1.2`, and multiplying a **negative** base by 1.2 makes it *more*
negative — so the flag fires when risky credit is shrinking **fastest**:

```
total -10.0%  risky -11.0%  ->  -11 > -12  ->  "outgrowing"   WRONG (de-risking)
```

Measured over **2739 weeks**, total credit growth is negative in **91 (3.3%)**,
worst **−5.45%**, including **2009-09** — the crisis the module exists to flag.
The margin now applies to the **gap**: `(risky - total) > margin * |total|`,
algebraically identical to the specification for positive growth and sign-safe
otherwise.

**And confidence was biased toward alarm.** §20.3 hardcodes 0.6 / 0.45 / 0.5 for
PONZI / SPECULATIVE / HEDGE, so the model was *more* confident when it said
something was wrong. Confidence now comes from `compute_confidence()`, and a test
asserts all three stages produce the **same** confidence.

**Added**

- `MinskyCompositionInputs`, `MinskyStage`, `minsky_composition_drift`.
- `MinskyBaseRates`, `MinskySettings`, with the margin and the one measurable
  base rate (SLOOS net loosening, 46.6% over 146 quarters).
- `sloos_net_tightening` (FRED `DRTSCILM`) in the registry; `total_credit_growth_pct`
  added to the **`blocked:`** list as *blocked by association* — a total-credit
  series exists, so that block is a dependency rather than a data gap.
- 22 tests (57 in the file), including §11.1's mandated
  `test_minsky_ponzi_drift_flags`.
- `scripts/mutation_minsky.py` — 25 mutations, crash-safe runner.
- `_check_minsky_composition_drift` — a block-check, not a model run.
- **O-20** — the model cannot be validated live and its stage base rate is
  unmeasurable.

**Two defects in my own test file, caught this increment**

- **Four test names collided** with the `policy_mix_classifier` tests added
  earlier in the same file. Python silently kept the *later* definition, so four
  policy_mix tests had **stopped running** while the suite stayed green. Caught
  by ruff's `F811`; the later definitions were renamed and no duplicates remain.
- The sweep's `C1b` pointed at **another model's property** (D-040's lesson), so
  the sweep now checks a mutation's target belongs to the model under test.

**Gates**

```
ruff check        All checks passed
ruff format       85 files already formatted
mypy --strict     no issues in 85 source files
pytest -q         760 passed, 1 skipped, 0 failed
mutation sweep    25 / 25 killed
live check        passes end to end (Module 3.4 is a BLOCK-CHECK)
```

### `qe_qt_stance` (Module 4.1) — Tier 2 → 25/29

**The specification's neutral branch requires a balance sheet that never moves.**
Section 20.4 decides the stance with `> 0` / `< 0` / `else`, so `NEUTRAL_HOLD`
needs a thirteen-week change of **exactly zero**. Measured over **1226 weeks** of
`WALCL`: **0 occurrences, 0.00%.** Dead code — D-037's class, for the second time
in four increments.

Corrected to a **relative band** (±0.5% of the level). Relative rather than
absolute because the balance sheet has ranged from **$0.7T to $9.0T**: a $34bn
change is 0.5% of $6.7T and 5% of $0.7T.

**The correction changes today's answer.** The latest thirteen weeks are
**+0.226%** → `NEUTRAL_HOLD`. The specification's `> 0` test reads the same data
as `QE_EXPANDING`.

**And two of four inputs were declared, listed in `inputs_used`, and never
read** — `balance_sheet_level` and `reserve_balances` appear in neither the logic
nor the `value` dict. The stance was decided by one number while the output
claimed three.

**Added**

- `BalanceSheetInputs`, `QEStance`, `qe_qt_stance` in `policy_rules.py`.
- `QEStanceBaseRates` and `QEStanceSettings`, with `neutral_band_pct` and
  `rrp_drained_threshold_bn`.
- Base rates under the band: **48.7% QE / 31.2% QT / 20.1% neutral** over 1226
  weeks, plus **76.8% of QT weeks also had reserves falling**.
- `fed_total_assets` (`WALCL`), `reserve_balances` (`WRESBAL`) and
  `on_rrp_level` (`RRPONTSYD`) in `series_registry.yaml`, provenance-only
  (D-033), each carrying its **units** warning.
- 27 tests (54 in the file), including an all-three-stances-reachable
  enumeration and a relative-vs-absolute band test.
- `scripts/mutation_qe_stance.py` — 27 mutations, crash-safe runner.
- `_check_qe_qt_stance` in the live check.

**The scarcity assessment, made specific**

The specification warns reserves can hit scarcity unexpectedly and says to
monitor `repo_stress_check()` — a sentence that fires identically on every QT
reading. **The mechanism is the ON RRP facility**: while it holds a buffer, QT
drains *that*; once empty, the same QT comes out of reserves. September 2019.

So the model flags `direct_reserve_drain` (QT **and** reserves falling), reports
the ON RRP level against a drained threshold, and **discloses when the RRP level
was not supplied** — silence must not read as reassurance. `on_rrp_level` is an
optional addition to the specification's four inputs.

**The units are a 1000× trap:** `WALCL` and `WRESBAL` are in **millions**,
`RRPONTSYD` in **billions**. The RRP is compared against a billions threshold and
the balance-sheet level is the *denominator* of the relative change — so a units
error moves the answer while every number stays plausible. The live check asserts
each series' order of magnitude first.

**Gates**

```
ruff check        All checks passed
ruff format       84 files already formatted
mypy --strict     no issues in 84 source files
pytest -q         738 passed, 1 skipped, 0 failed
mutation sweep    27 / 27 killed
live check        passes end to end
```

The sweep's one survivor exposed a **new failure mode**: `C1c` was a
**mis-targeted mutation** — it edited `PolicyMixSettings.quadrant_base_rates`, a
*different model's* property not covered by this sweep's tests, so it survived
for a reason unrelated to QE. Not a weak test, not inert, not broken: aimed at
the wrong symbol.

### `policy_mix_classifier` (Module 3.2) — Tier 2 → 24/29

**The source deficit series is negative for a deficit, and my own probe fell
into the trap.** FRED `FYFSGDA188S` reads **−5.77** for 2025 and **−14.48** for
2020, and is negative in 83 of its 97 observations. The model's field is named
`fiscal_deficit_pct_gdp` and compares it with `>`, so **fed in raw the
comparison inverts** — a larger deficit is *more* negative, and `deficit >
average` reports the most stimulative budgets in the sample as the tightest
fiscal policy. Silent and plausible: D-034's failure mode, for the second time
in three increments.

**And two measurement defects were caught before the model shipped:**

1. The deficit series is **annual**, so the common keys with the quarterly
   policy/inflation/output series are one per year. The first probe stepped back
   four *observations* for a year-over-year rate — a **four-year** rate on
   annual data — inflating the Taylor-implied rate and making `monetary_loose`
   true in **100%** of the sample.
2. With the window fixed, the probe still fed the **raw** series in and reported
   four quadrant frequencies — **all four wrong**. The live check, which
   sign-verifies first, produced the correct figures.

> **The lesson: a rate measured by the same code path that carries the sign
> error cannot detect it.** The check recomputes from a series it has
> *independently* sign-verified, and the disagreement is what exposed the probe.

**Added**

- `PolicyMixInputs`, `PolicyMixQuadrant`, `policy_mix_classifier` in
  `national_accounts.py` (Module 3.2 joins 3.1 there, as §20.3 specifies).
- `PolicyMixBaseRates` and an extended `PolicyMixSettings`.
- The four quadrant base rates: **22.8% / 31.6% / 19.3% / 26.3%** over 57 years,
  stored at 5dp so they sum to exactly 1.00000. The two MIXED quadrants are
  **50.9%** — a mixed policy mix is the *ordinary* case, not an exception.
- `federal_deficit_pct_gdp` (FRED `FYFSGDA188S`) in `series_registry.yaml`,
  provenance-only (D-033), carrying the sign warning.
- 26 tests (35 in the file), including the sign trap, the strict boundaries and
  an all-four-quadrants-reachable enumeration.
- `scripts/mutation_policy_mix.py` — 23 mutations, crash-safe runner.
- `_check_policy_mix` in the live check, which derives the Taylor rate live.

**Corrected**

- `value=quadrant` — a **bare string** — replaced by a dict carrying the
  quadrant **and both predicates**, so the D-009 cross-field identity is
  possible at all.
- `inputs_used` listed **three** inputs; `fiscal_deficit_avg_pct_gdp` decides
  half the quadrant and is now declared.
- `"MIXED" in quadrant` → `fiscal_loose != monetary_loose`.
- `confidence=0.6` → `compute_confidence()`, with
  `depends_on_unobservable=True` because the Taylor-implied rate rests on `r*`
  and potential GDP.
- `datetime.utcnow()` → `utc_now()`.

**Gates**

```
ruff check        All checks passed
ruff format       83 files already formatted
mypy --strict     no issues in 83 source files
pytest -q         718 passed, 1 skipped, 0 failed
mutation sweep    23 / 23 killed
live check        passes end to end
```

The sweep's first run was **21/24**, with three survivors and three different
diagnoses — one **inert** (a substring test and a boolean test are
behaviourally identical on the four current names, so the mutation was
*removed* per D-031), and two **weak tests** (nothing asserted the raw inputs
were republished; and a patch value sat *inside* the tolerance the mutation was
supposed to trip).

### `compute_fci` (Module 12, §22.7) — Tier 2 → 23/29

**A backfill, not a new function.** `compute_fci` had never been implemented and
never even stubbed — it is in §21.3's Tier 2 list and nowhere in `src/`. §22.7
says it *"must be retroactively added now, not deferred to Phase 5+"*, and
§22.13 requires the **raw-deviation placeholder** be deleted rather than left
alongside the corrected version. Nothing had been written, so nothing needed
deleting, but the placeholder form must never appear.

**The finding: the config's frozen denominators were wrong by two standard
deviations.** `fci.averages` held trailing means for **three of five**
components, **no standard deviations at all**, and **no window**:

| component | stored | measured | std | error |
|---|---|---|---|---|
| `credit_spread_hy` | **4.0** | **3.12** | 0.42 | **2.1 sigma** |
| `term_premium` | 0.3 | 0.132 | 0.35 | 0.48 sigma |
| `policy_rate` | 2.5 | 2.286 | 1.88 | 0.11 sigma |

The live spread of 2.65 scores **z = −1.12** against the measured mean and
**z = −3.2** against the stored one — dramatic looseness versus mild looseness,
with the output looking entirely normal either way.

**Removed, not corrected.** A corrected constant drifts on the same schedule;
§22.7 takes mean and std as parameters, so the caller computes them over the
configured window and nothing is frozen. `average_for()` went with the block —
it raised `KeyError` for `equity_index` and `usd_index`, the two components it
had no entry for.

**Added**

- `src/macro_engine/models/financial_conditions.py` — `FCIComponent`,
  `FCIInputs`, `FCIComponentName`, `compute_fci`.
- `fci.standardization_window_years_value` and
  `fci.nfci_divergence_threshold_value` in `settings.yaml`.
- 29 tests, including the **scale-invariance property** that distinguishes a
  z-scored composite from the raw-deviation placeholder.
- `scripts/mutation_financial_conditions.py` — 31 mutations, crash-safe runner.
- `_check_financial_conditions` in the live check, performing the **mandatory
  NFCI cross-check**.
- **O-17** (the window is forced to ~3 years by provider availability) and
  **O-18** (the weights are uncalibrated and NFCI agreement would not validate
  them).

**Corrected**

- `FCISettings.averages` and `average_for()` **removed**; `FCISettings` now
  **refuses to load** a weight set that does not sum to 1.0 — a non-summing set
  silently rescales the composite while the output still looks like an FCI.
- `confidence=0.4` → `compute_confidence()`; `datetime.utcnow()` → `utc_now()`.
- §20.12's caller-supplied `weights: dict[str, float]` override → weights read
  from config, so a call cannot silently change the model's definition.

**Found**

- **The window §22.7 suggests (10 years) is unattainable.** `BAMLH0A0HYM2`
  returns **786 observations (~3.0 years)** and that is a **provider limit, not
  a fetch window** — `start_date=1990-01-01` returns the identical rows. The
  window is the **common** span of all five components plus NFCI, not each
  series' own maximum, because different windows make the z-scores
  incomparable — the very defect Finding #7 corrects.
- **The NFCI cross-check is now part of the model's contract.** §21.1 calls it
  mandatory and NFCI is reachable, so the model takes an optional `nfci_value`,
  publishes the divergence, and — the more important half — **warns when the
  cross-check is absent**, because silence must not read as corroboration.
- **A vacuous test.** The cross-field identity test *iterated* `z_scores`, so a
  mutation emptying that dict made the loop body never run and the test passed.
  The key set is now asserted before the loop (D-035's absence lesson, again).
- **A redundant guard, proven inert by the sweep.** The empty-weights check
  could never fire — `sum({}.values()) == 0.0`, so the sum-to-one guard already
  raised. Per D-031 the **code** was deleted, not the test.

**Gates**

```
ruff check        All checks passed
ruff format       82 files already formatted
mypy --strict     no issues in 82 source files
pytest -q         701 passed, 1 skipped, 0 failed
mutation sweep    31 / 31 killed
live check        passes end to end (NFCI cross-check: divergence +0.5493, inside the bar)
```

### `credit_spread_attribution` (Module 8.3) — Tier 2 → 22/29

**The specification's own logic forbids the state it has a branch for.** As
written, `fundamental` requires `default_rate_trend == "rising"` while
`technical` requires it **not** to be, so the two predicates are mutually
exclusive and the branch reporting `BOTH` / `elevated_concern` **could never
execute**. Measured by enumerating the specification over its entire declared
input space — three attributions reachable, never four.

**And three of its five inputs were inert.** `hy_spread_change_bp` and
`ig_spread_change_bp` appear only inside `inputs_used`; `hy_spread_bp` is only
echoed. So the function attributed **widening without ever checking that spreads
widened** — a tightening week would still have been given a cause.

**Added**

- `src/macro_engine/models/credit_spread.py` — `CreditSpreadInputs`,
  `Attribution`, `Durability`, `DefaultRateTrend` (a `Literal`, per D-029),
  `credit_spread_attribution`.
- `CreditSpreadSettings` and `CreditSpreadBaseRates` in `config.py`, plus a
  `credit_spread` block in `settings.yaml`: the change window (Section 20.8
  names none), the volatility-spike threshold, the differentiation threshold,
  and three measured base rates.
- `equity_volatility` (FRED `VIXCLS`) in `series_registry.yaml`, via the
  provenance-only path (D-033) — the model takes a float and the live check
  fetches it, so no snapshot field is needed.
- 30 tests, including a **reachability regression** that enumerates the whole
  input space and fails if the dead branch is restored.
- `scripts/mutation_credit_spread.py` — 33 mutations, crash-safe runner.
- `_check_credit_spread` in the live check.
- **O-16** — the confidence rule has no factor for dependence on a manual input.

**Corrected**

- The `BOTH` branch is reachable: the exclusion is dropped.
- `NO_WIDENING` added as a fifth attribution — the specification's four all fit
  a *cause*, and none fits "there was nothing to attribute".
- `confidence=0.45` → `compute_confidence()`; `datetime.utcnow()` → `utc_now()`;
  the inline `> 20` → a config leaf; `default_rate_trend: str` → `Literal`.
- The change window, unspecified in the specification, is now config. It is the
  most consequential omitted parameter: the same 20% threshold fires on **1.8%**
  of one-day windows, **10.2%** of five-day and **18.2%** of twenty-one-day.

**Found**

- **Two adjacent inputs need opposite unit conversions.** The credit spreads are
  in *percent* (×100 to reach basis points); VIX is a *level* in index points
  whose input is a percent *change*. One conversion applied to both is a
  **100×** error producing a plausible attribution of the wrong kind — the D-035
  pairing-axis defect. The live check asserts the raw magnitudes first; a unit
  test pins that the model converts nothing.
- **A third function with a MANUAL, verdict-deciding input.** §21.1 lists
  `default_rate_trend` as manual ("no clean free real-time series"), and it
  decides half the attribution. The live check therefore runs **all three
  trends** and prints three verdicts rather than inventing one (§21.0 rule 3).
- **A config leaf no code path read, again.** `parallel_widening_rate` was
  consumed only by the live check, so swapping its accessor changed nothing the
  tests could see. It is now published in the model's output — the same gap
  D-036 found in `trailing_window_auctions`.

**Decision (user, 2026-09-17)**

The HY-minus-IG differentiation ships as a **disclosed diagnostic, not a
predicate**. The two spread changes imply a discriminator the specification
never wrote, and adding one would invent a model it does not describe — while
the two candidate causes have *opposite* forward implications, which is exactly
the distinction this module exists to protect. A test patches the threshold to
a value that flips the flag and asserts the attribution is **unchanged**.

**Gates**

```
ruff check        All checks passed
ruff format       79 files already formatted
mypy --strict     no issues in 79 source files
pytest -q         672 passed, 1 skipped, 0 failed
mutation sweep    33 / 33 killed
live check        passes end to end (which trend is TRUE is not validated)
```

### `auction_demand_signal` (Module 8.2) — Tier 2 → 21/29

**One of the function's five inputs has no source, contrary to the registry.**
§21.1 assigns `stop_through_bp` to the "TreasuryDirect auction results API" as
a LIVE input, but that route carries **no when-issued or expected-yield field
in any of its 91 columns**, and its three yield fields are within-auction
statistics — `high_yield - avg_median_yield` spans only 0.0000 to 0.0011 across
**all 703** note auctions, so the median bid and the clearing yield are the same
number to a rounding error. A tail compares the clearing yield with the market's
expectation *before* the auction, which the Treasury does not publish.

The input ships as **MANUAL**, per §21.1's own type for "human-entered, no API
exists". A secondary-market proxy was considered and rejected on measurement: a
Treasury tail is 0-2bp and the proxy's error is several bp, so the proxy would
have produced a plausible number measuring the wrong thing (the D-035 defect).
**The live check cannot exercise the tailed branch and says so in its own
output**; the branch is covered by unit tests. See **D-036**, **O-15**.

**Added**

- `src/macro_engine/models/auctions.py` — `AuctionInputs`, `AuctionVerdict`
  (a `Literal`, per D-029), `auction_demand_signal`.
- `AuctionDemandSettings` and `AuctionBaseRates` in `config.py`, plus an
  `auction_demand` block in `settings.yaml`: the trailing window (Section 20.8
  specifies none), the two decision thresholds, the definitional tail boundary,
  and the two measured base rates.
- 27 tests, including a hand-computed case for each verdict branch, boundary
  cases built so the comparison's strictness is observable, the cross-field
  identity, and the refusals.
- `scripts/mutation_auction_demand.py` — 32 mutations with the crash-safe
  runner.
- `_check_auction_demand` in the live check, plus a `read_int` helper.
- **O-14** (a fraction passed as a percentage is undetectable) and **O-15**
  (no when-issued yield source) in `OPEN_ISSUES.md`.

**Found**

- **The indirect share has two bases that differ by 27pp.** The route exposes
  both `indirect_bidder_accepted` and `indirect_bidder_tendered`: mean **58.17%**
  on the accepted basis against **29.25%** on the tendered basis, with a largest
  single-auction gap of **45.19pp**. The model takes the accepted basis — the
  market convention — and the input contract states it, because the wrong basis
  would move the flag by nine times the 3pp threshold it is compared against.
- **`security_term` splits one nominal tenor across three labels.** A 10-Year
  note appears as `"10-Year"`, `"9-Year 11-Month"` and `"9-Year 10-Month"`
  depending on whether the auction is an original or a reopening, so grouping on
  the raw string builds each trailing average from **a third of the history**.
  The grouping key is `original_security_term`.
- **`bid_to_cover_ratio` is not reproducible from the feed's own totals** —
  `total_tendered / total_accepted` differs on **703 of 703** note rows.
- **The sign convention inverts the verdict silently.** `stop_through_bp` is
  `(expected - clearing)`, so negative is a tail. A caller supplying the more
  intuitive `(clearing - expected)` would invert every verdict while producing
  plausible output — D-034's failure mode. It is now stated in the field
  description, published as a flag beside the raw value, asserted at five points
  spanning zero, and warned about.
- **A config leaf no code path read.** The first mutation sweep left
  `C1a` (the trailing window hardcoded) alive because `trailing_window_auctions`
  was consumed only by the live check, so mutating it changed nothing the unit
  tests could see. It is now published in the model's output.
- **A test that claimed a defence it did not have.** The `[0, 100]` bound on
  `indirect_bidder_pct` does *not* catch `0.55` meaning 55% — 0.55 is a legal
  percentage. The first test asserted it would raise, and it does not. The
  behaviour is now recorded in a test that states the limitation (O-14).

**Corrected**

- `pyproject.toml`'s mypy scope now reports **76** files (was 73); the three new
  files are `models/auctions.py`, `tests/models/test_auctions.py` and
  `scripts/mutation_auction_demand.py`.
- `OPEN_ISSUES.md`'s **O-12** still carried D-034's superseded figures
  (`mean_abs_error_pp` 7.747, `correlation_with_realised` 0.108) and named
  `GDPC1` as the series the live check recomputes from. Corrected to 3.026 and
  −0.092, and to `A191RL1Q225SBEA`.
- `docs/PROGRESS.md` mislabelled `auction_demand_signal` as **Module 9**; it is
  **Module 8.2** (§20.8 — Term Premium Decomposition, Auctions, Credit Spread
  Attribution).

**Gates**

```
ruff check        All checks passed
ruff format       76 files already formatted
mypy --strict     no issues in 76 source files
pytest -q         642 passed, 1 skipped, 0 failed
mutation sweep    32 / 32 killed
live check        passes end to end (tail not validated — D-036)
```

### `simple_gdp_nowcast` accuracy record corrected — D-035

**Every accuracy figure in the D-034 entry below was measured on the wrong
estimand and has been recomputed.** The original probe gave each historical
reconstruction the whole window of monthly changes available at that time
(a cumulative form); the shipped function nowcasts **one quarter ahead**, and a
cumulative reconstruction measures a different, flattering model. The live
check's recomputation caught the discrepancy on the next run and the tolerance
was **tightened (0.5pp → 0.15pp), not widened**. See **D-035**.

| figure | as recorded (D-034) | corrected (D-035) |
|---|---|---|
| corrected form mean \|err\| | 7.747pp | **3.026pp** |
| persistence benchmark | 2.915pp | **2.915pp** |
| spec's form mean \|err\| | 3.558pp | **3.558pp** |
| corr(corrected, realised) | +0.108 | **−0.092** |
| corr(spec, realised) | −0.169 | **−0.169** |
| quarters measured | 137 | **137** |
| realised positive share | 0.898 | **0.898** |

D-034's benchmark, specification figure, sample size and base rate were all
correct; only the corrected form's error was wrong, and it was wrong in the
direction that flattered the correction.

**A second correction was needed inside this one.** A first pass reconstructed
realised growth from `GDPC1` levels — which gives a *different sample* (n=136)
and materially different figures — instead of `A191RL1Q225SBEA`, the series the
function's own `prior_quarter_annualized` field declares and the one the live
check consumes. The live check rejected that pass too. **Derive a measurement
from the series the function actually consumes, not from a series that measures
the same concept.**

**The correction exposed a stronger finding than the one it replaced.** With
both sides on the same estimand:

| form | corr | mean \|err\| | sign agree |
|---|---|---|---|
| specification as written | −0.169 | 3.558pp | 83.2% |
| prior quarter's print alone | −0.168 | **2.915pp** | 85.4% |
| this corrected form | −0.092 | 3.026pp | 89.1% |

The corrected form is **0.11pp WORSE than repeating the prior quarter's print**,
and it does not beat the specification's error by enough to clear the 0.5pp bar
either. The adjustment it adds is **over-weighted, not inert**: it runs at
**0.505×** the magnitude of the change it predicts (mean \|delta\| 1.4727pp
against 2.9153pp of movement) while correlating with that change at only
**r = +0.1727** — an **R² of 0.030**. Applying a 3% signal at unit weight costs
more in noise than it adds in information. A scale sweep finds the best
achievable scale is ≈0.498, recovering **0.0395pp** — inside the noise on 137
points and fitted on the same sample that measures it (D-027's circularity), so
the weights remain **unfitted** and the shipped form is reported as worse than
persistence rather than quietly repaired.

The *sign* correction did work: `corr(delta, realised change)` is **+0.1727**
where the specification's is **−0.0565**. D-034's four corrections were real
defects; it is the magnitude that remains wrong, not the direction.

**Added**

- `delta_overweighting_ratio_value` on `GdpNowcastAccuracy`, published from the
  model as `delta_overweighting_ratio` — the disclosure that the model's
  agreement with persistence is structural rather than earned. Named for the
  finding: the delta is over-weighted, and "inert" would have recommended the
  opposite remedy.
- A **structural-reason warning** carrying that ratio, so a reader who sees the
  delta does not go hunting for a better weight — the sweep shows the best one
  recovers 0.0395pp and is fitted on the measuring sample.
- Two tests: the headline warning must **quantify** the negative result, and the
  over-weighting ratio must be published *and* explained as structural.
- Four live-check assertions: the spec's form must agree with the corrected form,
  the over-weighting ratio must be recomputed from live output, it must be
  published identically by the model, and it must sit below 1.0 (a ratio at or
  above 1.0 would be a different defect requiring a different remedy).
- **O-12** and **O-13** in `OPEN_ISSUES.md` — the accuracy block is a snapshot
  over a fixed window, and FRED `GDPNOW` is a settled record rather than a
  real-time nowcast.

**Corrected**

- `pyproject.toml`'s mypy `files` gained `scripts`. The documented gate
  (`mypy --strict src tests scripts`) was **stricter than the configured
  default**, so `scripts/live_labor_check.py` — which contains real logic — had
  never been checked by a plain `uv run mypy --strict`. Source-file count
  65 → **73**.
- The accuracy test rewrote its expectation source. It had read from the same
  accessors the model reads, so an accessor **swap** moved both sides together;
  five of the sweep's survivors were this. It now patches in a synthetic record
  with all-distinct leaves. **PROGRESS.md rule 7 generalised: a test reading its
  expectation from the same config the code reads cannot detect a swap any more
  than a literal.**
- Three mutations in `mutation_gdp_nowcast.py` re-pinned to full multi-line
  warning blocks. They had held only each warning's first line, so the mutation
  rephrased rather than removed it and could not be detected — **inert by
  construction**, not weak instruments.
- The headline warning now says the model **ties** the persistence benchmark
  rather than failing to beat it. A 0.003pp margin is a tie; asserting a loss the
  data does not show is a different inaccuracy from the one being corrected.
- `interpretation`, `context`, the `prior_quarter_annualized` field description,
  the module header and the accuracy docstring table all rewritten to the
  corrected figures.
- `pytest` 607 → **608 passed**; `mypy` 70 → **73 files** (`scripts/` added to
  the configured scope); the mutation sweep extended to **39 mutations** and
  taken to **39 / 39 killed**.
- **The live check's specification-form assertion rewritten.** It required the
  specification's form and the corrected form to be within 0.15pp of each other
  — true only under the superseded `GDPC1` figures, where both scored ≈2.93pp.
  On the authoritative figures they differ by **0.53pp**, so the assertion was
  false by construction. It is replaced by two **directional** assertions: the
  correction must beat the specification materially, and must still not beat
  persistence.
- **Two correlation leaves are now recomputed by live evidence.**
  `correlation_with_realised` and `spec_form_correlation_with_realised` were
  recorded but never checked against the data — the unit tests pin them against
  a *synthetic* record, which proves the model reads them, not that they
  describe anything. Live: **−0.0922** and **−0.1685** against recorded
  −0.0922 and −0.1690.
- **`mutation_gdp_nowcast.py` made crash-safe.** It now repairs any mutation left
  applied by an interrupted run, executes the sweep under `try/finally`, and
  refuses to report success while a mutation is still in the tree.

**Found**

- **A mutation left in the source by a power loss.** A laptop shutdown mid-sweep
  left `M5b` — *the no-usable-quarter refusal removed* — applied in
  `gdp_nowcast.py`, disabling the §21.0-rule-4 guard against annualizing a
  partial quarter. It passed `mypy` and 30 tests. A re-run would have adopted the
  corrupted file as the baseline and baked it in permanently. Detection needs
  `old` **absent** *and* `new` **present** — the `new`-only test reports seven
  false positives, because several mutations' replacement strings are substrings
  of legitimate code.
- **A new pairing axis: estimand.** Two computations can share the series, the
  window, the weights and the arithmetic, and still measure different quantities
  because they differ in *what is being predicted*. This is the ninth axis and
  the rule is generalised into `PROGRESS.md`.
- **The field-shadows-its-own-property trap, hit a FIFTH time** — in the same
  class, in the same session, with the warning sitting eight lines above. The
  lesson recorded is that a project which keeps hitting this needs a **test**, not
  another docstring; flagged as a carry-over for `test_infrastructure.py`.
- **Two fixture defects whose outcome was invariant under the change**, found
  only on the second attempt: a test passing `published_gdpnow=None` explicitly
  (so the field default it meant to test was never read), and a threshold
  patched to a value no improvement could straddle. Generalised as PROGRESS.md
  rule 18.

### `simple_gdp_nowcast` (Module 7.5) — Tier 2 → 20/29

**The specification's formula was measured before it was implemented, and it
does not work.** On 137 quarters of live data, Section 6.5's eleven-line
placeholder correlates **−0.169** with the quarterly growth it claims to
nowcast, and is beaten by simply reporting the prior quarter's realised print
(2.915pp mean absolute error against the model's 3.558pp). Its 83.2% sign
agreement is *worse* than always predicting "positive", because realised growth
was positive in 89.8% of the measured quarters. Four defects, each producing a
plausible number: a sign-inverted trade term (wrong on **414/414** months), a
monthly change added to a quarterly annualized rate, nominal components added to
a real base, and weights summing to 1.0 against actual GDP shares of
~67.9/18.2/−3.1. See **D-034**.

**Added**

- `SimpleGDPNowcastInputs` and `simple_gdp_nowcast()` in
  `models/gdp_nowcast.py`. The specification's name and input surface are
  retained (§22.1/§22.13), so the thesis layer consumes what Section 6.5
  promises. `value` reports `nowcast_annualized`, `delta`, the three
  contributions, `quarters_used`, `quarters_dropped`, and the **measured
  accuracy record**: `mean_abs_error_pp`, `persistence_mean_abs_error_pp`,
  `beats_persistence` (computed, never asserted), `improvement_pp`,
  `correlation_with_realised`, `quarters_measured`, `realised_positive_share`,
  and — only when a published figure is supplied — `gdpnow_cross_check_pp`.
- `_quarter_annualized_mom()` — averages a quarter's monthly changes and
  annualizes, so both sides of the addition are quarterly annualized rates.
- `_is_complete_quarter()` — a partial quarter is dropped and disclosed, never
  annualized short (§21.0 rule 4).
- `tests/models/test_gdp_nowcast.py` — **27 tests**, including the sign checked
  against the raw **level** rather than the percent change (a cross-series
  identity, not a restatement), the cross-field identity, both refusal paths,
  and presence-and-absence assertions for every warning.
- `scripts/mutation_gdp_nowcast.py` — **37 mutations, 36/37 killed** on the
  sweep. The one `PATTERN MISSING` (M5a) was proved to be a **false negative
  caused by a concurrent `ruff format`** rewriting the file mid-sweep, not a
  broken pattern: applied standalone it fails two tests as intended.
- `_check_gdp_nowcast()` in `scripts/live_labor_check.py` — asserts the three
  inputs are monthly, that `BOPGSTB` is negative in **every** observation, the
  sign against the raw level, the cross-field identity, and **recomputes** the
  accuracy record and the `beats_persistence` flag so neither can go stale.
- Registry: `retail_sales` (`RSAFS`), `durable_goods_orders` (`DGORDER`),
  `trade_balance` (`BOPGSTB`), `gdpnow_published` (`GDPNOW`) — all verified
  against live data, all `not_a_snapshot_field: true` (so the three-part D-030
  change is satisfied by the provenance path).
- `GdpNowcastSettings` + `GdpNowcastAccuracy` in `config.py`; `gdp_nowcast:`
  block in `settings.yaml` with the BEA expenditure shares (net exports
  **negative**), the rejected 0.6/0.3/0.1 recorded in the note, and the full
  accuracy record.

**Corrected**

- **The net-exports sign.** The specification's `+0.1` weight on a *percent
  change* of the all-negative `BOPGSTB` inverted the term on every month. For
  `v = -|v|`, `pct = |v[t]|/|v[t-1]| - 1` — the minus signs cancel, so `pct` is
  the percent change of the absolute value, and `pct > 0` means the deficit
  **widened** (contractionary). The weight must therefore be negative.
- **The cadence.** `months_per_quarter` is a config leaf, not a literal 12.
- **The confidence literal.** Section 6.5's `confidence=0.35` is replaced by
  `compute_confidence()` (§22.8).

**Found**

- A **property that shadowed its own config field**. `GdpNowcastAccuracy`
  defined both a field and a property named `realised_positive_share`, so the
  accessor returned the whole `CalibratedValue` envelope instead of a float —
  and every downstream comparison would have compared a float to a model.
  Pydantic does not reject the collision at class-definition time. Renamed the
  field to `realised_positive_rate`; this is the **fourth** occurrence of the
  config-accessor trap.
- Section 6.5's docstring asserts the published GDPNow has "no free API" and
  prescribes manual entry. **That is false on this build**: FRED `GDPNOW`
  returns 61 live observations. It is a *final per-quarter record* rather than a
  real-time nowcast (one observation per quarter, zero consecutive repeats, its
  own error 1.364pp), so the cross-check ships with that caveat attached and
  the manual-entry route is unnecessary.
- Three registry `verified_value`s were written from recollection and were
  **wrong in three of four cases** (`RSAFS` 765199→773947, `DGORDER`
  339829→339392, `BOPGSTB` −60263→−88576, `GDPNOW` 1.6→5.1028). Caught by
  fetching the live values rather than trusting the recall — the project's own
  "compute the fixture, don't recall it" rule.

### `leading_indicator_proxy` (Module 7.3) — Tier 2 → 19/29

**Added**

- `models/lei_proxy.py` — `LeadingIndicatorProxyInputs` and
  `leading_indicator_proxy()`. Renamed from the specification's `lei_composite`
  per §21.1: an in-house composite over free components must not be called
  "LEI". `value` reports `composite_6mo_annualized`, `breadth_declining`,
  `n_declining`, `n_components`, `broad_based`, the three-state `lead_direction`,
  `breadth_threshold`, `breadth_null_rate`, and `equal_weighted`.
- `tests/models/test_lei_proxy.py` — 55 tests.
- `scripts/mutation_lei_proxy.py` — **36 mutations spanning four files** (the
  model plus the three the D-033 guards live in), **36/36 killed**. Two first-sweep
  survivors were both diagnosed as **weak tests** and closed: the suite passed
  the tolerance *explicitly* everywhere, so nothing exercised the default, and
  nothing combined `forward_looking=True` with a non-zero tolerance.
- `_check_leading_indicator()` in `scripts/live_labor_check.py` — asserts all
  four components are live, the `ICSA` **inversion**, the `SP500` window span,
  the cross-field identity (composite = equal-weighted mean), breadth
  recomputed from live signs, a **corrected span per component**, and the
  naming rule.
- `_six_month_change_pct()` returning **both** dates of each pair, so a reader
  can verify the span.
- Registry: `building_permits` (`PERMIT`), `curve_slope_10y3m` (`T10Y3M`),
  `sp500_index` (`SP500`) — all verified against live data, all declared
  `not_a_snapshot_field`. `conference_board_lei` added to **`blocked:`**.
- `LeadingIndicatorSettings` in `config.py`; `leading_indicator:` block in
  `settings.yaml` with the four-component mapping, **per-component
  orientations**, and documented `known_limitations`.

**Changed**

- `confidence` is `compute_confidence(ConfidenceInputs(
  is_heuristic_not_calibrated=True, depends_on_unobservable=True))` → **0.30**,
  replacing the specification's `0.5 if broad_based else 0.3` (§22.8).
- `breadth_threshold` and the null rate are read from config via `.property`
  accessors, not written as literals.
- The `weights` argument is validated to **cover the component set exactly**;
  the specification's `w.get(k, 0)` silently weighted a missing component at
  zero rather than failing.
- `ORIENTATION` is now documented in the input model and asserted live. `ICSA`
  is a claims **level**, so a rising level means a weakening labour market;
  entered direct it inverts the whole reading.

**Fixed**

- **A registry entry has exactly two resolution paths (D-033).**
  `resolve_snapshot_field` gained an explicit second path for
  provenance-only entries, and the three new Module 7.3 entries declare
  `not_a_snapshot_field: true`. Previously the `snapshot_field or field_name`
  fallback resolved them to themselves and failed with advice that was wrong
  for their purpose.
- **A daily series may outrun the UTC clock (D-030, third recurrence).**
  Retired the record-without-patching posture in favour of the deliberate
  decision it was waiting for: `future_date_tolerance_days` is now a per-series
  registry property (**1** on `iorb` and `sofr`, 0 elsewhere). A point inside
  it collapses to one **INFO** finding
  (`SAME_DAY_PUBLICATION_AHEAD_OF_CLOCK`); outside it the ERROR pair is
  unchanged, and the message now names the tolerance.
- **Unit mismatch across two branches of one field.** `T10Y3M` has 1,252
  non-positive observations, so the spread branch is live. The level branch
  produced percent and the spread branch a raw difference — the curve
  component would have entered the composite 100× too small. Both now produce
  percent.
- **A degenerate span diagnostic.** The change helper returned the latest date
  where the caller printed the prior one, so every component appeared paired
  with itself. The arithmetic was right and the *diagnostic* was wrong, which a
  reader cannot distinguish from a real bug.
- **A three-state read that fired on a negative composite.** 3 of 4 components
  rising labelled the "one big fall" fixture `broad_based_advance` while the
  composite printed −4.12. The advance label now requires `composite > 0`.

**Findings**

- **D-032.** §21.1 gives Module 7.3 a genuine fork — manual entry of the
  published composite, or an in-house composite that must not be called "LEI" —
  and it was resolved with live evidence. FRED `USLEI` returns an **empty
  frame** through both the local API and the in-process package (three attempts
  each), so the licensed route is BLOCKED; manual entry was refused on §21.0
  grounds (no refresh, no vintage, no observation date). All four named
  components resolve live.
- **The composite is a mixed-unit sum; breadth is the signal.** The four
  components arrive in persons, thousands, percentage points and index points,
  so their weighted sum is additively meaningless and dominated by the most
  volatile member. Breadth is unit-free and is what `broad_based` is computed
  from.
- **D-029 applied.** `breadth >= 0.6` over four components requires 3 of 4,
  which under a sign-symmetric null happens **31.25%** of the time. The base
  rate is computed **exactly** and is explicitly **combinatorial, not
  historical** — the output says so, because inventing a track record would be
  its own fabrication.
- **O-11.** FRED `SP500` is a rolling ~10-year window (2,512 obs from
  2016-09-16) whose start date advances; a longer lookback **truncates
  silently** rather than erroring.
- Both defects the live check found were invisible to all 55 unit tests and to
  the mutation sweep, because neither is an arithmetic error — §21.0 in its
  purest form.
- **D-033's methodology note.** The two failures that closed this increment were
  found by the **full** suite, not by the increment's own evidence, which was
  green first. Per-increment green lights validate new code, not the absence of
  collateral damage; run the full suite after every registry or schema change.

**Notes**

- Neither `leading_indicator_proxy`'s own 55 tests nor its 28-mutation sweep
  could see either live-check defect; the mutation sweep's contribution was
  proving the *guards* are load-bearing, which is a different property.

### `gdp_gdi_divergence` (Module 7.1) — Tier 2 → 18/29

**Added**

- `models/gdp_nowcast.py` — `GdpGdiInputs` and `gdp_gdi_divergence()`. `value`
  reports both growth rates, the signed `divergence_pp`, `average_growth_pct`,
  the `significant` flag, its **measured base rate**, and the **measured level
  wedge** so the growth and level quantities can never be conflated.
- `tests/models/test_gdp_gdi_divergence.py` — 35 tests.
- `scripts/mutation_gdp_gdi_divergence.py` — 30 mutations, 30/30 killed.
- `_check_gdp_gdi()` in `scripts/live_labor_check.py` — asserts both series are
  live, that the two dead alternatives stay dead, the common-date pairing, the
  cross-field identities, and **recomputes all three base rates from raw data**
  against config.
- Registry: `gdi` (FRED `GDI`, nominal, verified 2026-09-17 against 318
  quarterly observations).
- `MacroDataSnapshot.gdi` and `"gdi"` in `SCALAR_SERIES_FIELDS` — the third and
  second parts of the three-part registry change (D-030).
- `GdpGdiSettings` / `GdpGdiBaseRate` in `config.py`; `gdp_gdi:` block in
  `settings.yaml` with five documented calibrated leaves.

**Changed**

- `confidence` is now `compute_confidence(ConfidenceInputs(
  is_heuristic_not_calibrated=True, depends_on_unobservable=True))` → **0.30**,
  constant in the inputs, replacing the specification's hardcoded
  `0.4 if significant else 0.7` (§22.8).
- The significance threshold and revision window are read from config rather
  than written as literals in the model.
- The warning set is now **unconditional and four strong** (residual + base
  rate; sign is a coin flip; growth-average vs level wedge; revision vintages),
  plus one path-specific warning. Previously the specification emitted a
  warning only on the significant path, so the typical case was silent.

**Fixed**

- The output key is `average_growth_pct`, not the specification's bare
  `average`. The name states the unit, because the claim that the average is
  "the better read" holds only for growth rates: the level wedge averages
  **−0.459%** and is negative in seven of nine decades.

**Findings**

- **D-031.** Section 20.7's four substantive claims were measured against live
  data; three do not survive.
  1. The `1.0pp` threshold fires **68/314 = 21.7%** of quarters — a routine
     event, so the flag now travels with its base rate (D-029's rule).
  2. The **sign of the divergence carries no information**: GDP leads 47.8%,
     GDI leads 52.2%, mean −0.009pp, median −0.026pp. That is the signature of
     a residual, not a signal, so the model reports the magnitude and refuses
     to interpret the direction.
  3. "The average is often the better read" is true for growth rates and
     **false for levels**.
  4. `gdi_growth_pct` was marked "VERIFY series" and verifies: FRED `GDI`
     returns 318 fully-populated quarters. Two plausible alternatives
     (`GDINC1`, `A261RC1Q027SBEA`) are **dead**, so neither may be substituted.
- The pairing rule gained an eighth axis: **common unit**. Two differenced inputs
  must share a basis (nominal-vs-nominal or real-vs-real), which is
  undetectable from two bare floats.
- Mutation-sweep methodology: an initial 19/30 was diagnosed as **three**
  distinct causes — 3 broken mutations (a `ruff format` change made the pattern
  not apply), 6 inert mutations (only the first line of a multi-line f-string
  was replaced), and 3 genuine weak tests. Only the last group is a test gap.
  Recorded as a rule in D-031.

**Notes**

- The three weak tests shared one shape: the assertion and the implementation
  both read the same config, so a literal equal to the shipped value was
  invisible. Fixed with an in-process config-patch pattern that breaks the
  symmetry — now applied to the threshold, the revision window, and the
  confidence penalties.
- `M1d` exposed a mutation-scoping hazard: `depends_on_unobservable=True`
  appears three times in `gdp_nowcast.py`, and the mutation hit the copy in
  `output_gap` rather than the code under test. Bare strings repeated across a
  module must be anchored by their surrounding block.

### `ppi_pipeline_signal` (Module 5.4) — Tier 2 → 17/29

**Added**

- `models/ppi_pipeline.py` — `PPIPipelineInputs`, `MarginTrend` /
  `DemandCondition` / `PipelinePassThrough` `Literal` aliases, and
  `ppi_pipeline_signal()`. `value` reports the specification's boolean **plus**
  a four-state `gradient_direction`, `expected_pass_through`, both **measured
  base rates**, and `stage_spread_pp`.
- `tests/models/test_ppi_pipeline.py` — 51 tests.
- `scripts/mutation_ppi_pipeline.py` — 32 mutations, 32/32 killed.
- `_check_ppi_pipeline()` in `scripts/live_labor_check.py` — asserts the
  stage mapping, the common-date pairing, the cross-field identities, and
  **recomputes both base rates from scratch** against config.
- Registry: `ppi_stage_crude` (`WPSID62`), `ppi_stage_intermediate` (`WPSID61`);
  `ppi` (`PPIFIS`) gained a `decision_note`.
- `MacroDataSnapshot.ppi_stage_crude` / `.ppi_stage_intermediate` — without
  these the two new series fetch successfully and are then silently dropped.
- `docs/PROGRESS.md` — a live build-tracking file with tier checkboxes and
  percentages, updated in place at each milestone.
- 51 offline tests.

**Changed**

- `inflation.pipeline_base_rate` and `inflation.pipeline_gradient_tolerance_pp`
  added to `config/settings.yaml`; `InflationSettings` gained the matching
  fields and `pipeline_gradient_tolerance` property.

**Fixed / corrected (specification's Section 20.5 sample)**

- The two assessment fields were free `str` with their permitted values in a
  comment. A typo (`"compress"`, `"Compressing"`) was **accepted** and fell
  through to the `else` branch, reporting the optimistic `"fuller"`
  pass-through. Now `Literal` — an unrecognised value is a construction error
  naming the permitted set. See D-029.
- `confidence=0.4` replaced by `compute_confidence()` (Section 22.8) → `0.30`.
- `corporate_margin_trend` is a **human assessment** (Section 21.4 item 10) and
  is now disclosed as such unconditionally.
- The strict ordering test gained a configured dead band (`no_clear_gradient`)
  and a fourth state (`non_monotonic`) — the most common real outcome, which the
  specification's boolean reports as `False` and therefore reads as "no gradient".

**Findings**

- **D-029** — the specification's `crude > intermediate > final demand` test
  fires in **57 of 190 usable months (30.0%)**; the loose `crude > final` in
  **84/190 (44.2%)**. Both are coin flips. The boolean is retained but now
  always travels with its own measured base rate, so the rarer of two
  near-equal outcomes is not read as an unusual state.
- **D-030** — `calibration_status` is a **closed vocabulary**: an invented
  `measured` was rejected, and the correct existing member (`fitted_assumption`)
  already covered the meaning. Separately, adding a registry entry is a
  three-part change — file, snapshot schema, verification record — and the entry
  alone is silently dropped; `note` is not a registry field (`decision_note` is);
  and an unquoted `description` containing a colon breaks the YAML.
- `PPICRM` ("crude materials for further processing") is **discontinued**, last
  observation `2015-12-01` — confirmed live and asserted in the check. Using it
  would have truncated every crude-stage reading by a decade. `WPSID62` is the
  live crude stage.
- `PPIFIS` starts `2009-11`, so the three-stage common window is **202
  observations**, not 953.

**Notes**

- The `PPIFIS` route returned a **502 HTML error** on first probe, then
  succeeded **8/8** on repetition. Recorded because concluding a series is dead
  from a single failure would have discarded a working route — and because the
  transient failure mode (HTML instead of JSON) is worth recognising.
- A boundary fixture written as `2.0 - tolerance` **failed against a correct
  model**: `2.0 - 1.9 == 0.10000000000000009`, which exceeds the tolerance. Edge
  fixtures must be built by addition. Two mutation survivors were real test gaps
  and became tests; a third was an **inert mutation** and was removed.

---

### Phase 1 complete — data layer, snapshot builder, thesis schema

**Added**

- `data_layer/snapshot_builder.py` — the single place a `MacroDataSnapshot` is
  assembled. Returns `(snapshot, report)`; the report is not optional, because a
  caller that ignores it cannot distinguish a complete snapshot from a
  half-empty one.
- `SnapshotBuildReport` — records requested / succeeded / failed /
  skipped-unverified fields and renders four flag kinds (`FETCH_FAILED`,
  `UNVERIFIED_SERIES_SKIPPED`, `EMPTY_SERIES`, and validation findings).
- `snapshot_builder.resolve_snapshot_field()` — resolves a registry key to its
  schema attribute via the new `snapshot_field` config key.
- `tools/probe_money_market.py` — read-only discovery probe for money-market
  routes. Writes nothing; exists so a question about a series mapping is
  grounded in measured values.
- `tools/record_verification.py` — records verification evidence into the
  registry, so status and evidence change together.
- `forward_looking` on registry entries — marks series whose published values
  are projections rather than measurements.
- `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/OPEN_ISSUES.md`,
  `docs/CHANGELOG.md`.
- 7 new offline tests and 2 new live tests.

**Changed**

- `validate_observations()` gained `forward_looking`. A projection series
  reports one INFO `FORWARD_LOOKING_HORIZON` instead of one ERROR per future
  point.
- `use_local_api_first` default changed `true` → `false` on measurement
  (223.6 s → 9.5 s for a full build, identical results). See D-003.
- `RegistrySeries` gained `snapshot_field`, `decision_note`, `forward_looking`,
  `verified_on`, `verified_value`, `verified_curve`, plus two validators:
  verification requires recorded evidence, and the evidence must satisfy its own
  `plausible_range`.
- `SeriesRegistry` now applies its `defaults:` block to every entry that omits
  `provider` / `endpoint`. See D-004.
- `is_local_api_available()` now probes `/openapi.json` and requires exactly
  200, instead of requesting a non-existent route and accepting any
  `status_code < 500`.
- `persistence.SCALAR_SERIES_FIELDS` / `CURVE_SERIES_FIELDS` /
  `MAPPING_SERIES_FIELDS` are now shared constants consumed by both the write
  and read paths. Previously two parallel literal tuples, where a field added to
  one and forgotten in the other would vanish silently.
- `MacroDataSnapshot` gained `on_rrp_volume_bn`.

**Fixed**

- `snapshot_from_long_frame()` discarded every curve on load. Curves were
  written correctly and never reconstructed. See D-006.
- `build_snapshot()` appended validation flags twice (once via `attach_flags`,
  once directly), doubling every finding.
- `fed_funds_rate` was declared twice on `MacroDataSnapshot` — caught by
  `mypy --strict` `no-redef`.
- `treasury_curve` → `yield_curve` name mismatch silently dropped the entire
  Treasury curve from the snapshot.
- Registry `defaults:` were parsed but never applied, so every scalar fetch
  failed with "no endpoint configured".

**Verified**

- All **21 / 21** LIVE registry routes verified against live data, with observed
  values recorded in the registry. Full evidence in
  `docs/SERIES_VERIFICATION.md`.
- Full live snapshot: 21/21 fields, 0 failures, 1 expected flag. All
  cross-series plausibility checks pass, including the three-symbol GDP
  deflator identity and the SOFR/IORB/ON-RRP corridor.
- Quality gates: ruff clean, ruff-format clean, `mypy --strict` clean on 31
  source files, 42 offline tests passing, 4 live tests passing.

### Phase 2 — first model: `output_gap()`, and two real defects found by running it

**Added**

- `models/as_of.py` — the shared as-of discipline. `observation_as_of()` filters
  an observation series to `observation_date <= as_of`, returns an `AsOfSeries`
  that reports how many points it withheld and the furthest withheld horizon,
  and returns **empty rather than zero** when nothing qualifies. Placed here and
  not inside one model because the obligation is general: every consumer of a
  forward-looking series owes it. Closes O-7.
- `models/gdp_nowcast.py` — `output_gap()` verbatim per Section 6.5, plus
  `output_gap_from_snapshot()` (the adapter where the pairing rule and the
  warnings actually live) and `OutputGapSeriesReport`, which makes the pairing
  date, the withheld counts and the staleness *inspectable* rather than
  inferable.
- `tests/models/test_output_gap.py` — 20 tests plus one conditional skip,
  including the two Section 11.1-mandated sign cases with hand-computed values.
- `models/__init__.py` — states the one structural rule the package enforces:
  **models do not fetch data.**

**Changed**

- `RegistrySeries` gained `seasonality` and `verified_observation_date`, and
  `verified_curve` widened from `dict[str, float]` to `dict[str, Any]` (PyYAML
  auto-parses ISO dates, so `float` rejected the field's own content).
- New `RegistrySeries` validator
  `_forward_looking_evidence_must_be_a_realised_observation`: a series marked
  both `forward_looking` and verified must name a `verified_observation_date`
  that falls **before** its own projection block.
- `output_gap()` computes confidence via `compute_confidence()` rather than
  Section 6.5's `confidence=0.5` literal — Section 22.8 makes
  `compute_confidence()` the sole producer of confidence, so the literal cannot
  ship. With the current uncalibrated config the two values coincide at 0.5;
  see the finding below.
- `gdp_potential` registry entry: `verified_value` corrected, `plausible_range`
  narrowed from `[1000, 100000]` to `[1000, 40000]`.

**Fixed**

- `gdp_potential` reported the **Q4 2036 projection** (`29443.0227`) as its
  `verified_value` — the evidence for its own verification claim was a
  forecast. Corrected to `24070.9386484 @ 2026-04-01`. See D-010.
- **O-7 / D-009 — the gap was measuring growth, not slack.** `GDPPOT` publishes
  one quarter ahead of `GDPC1`. Pairing each series' own latest observation
  produced `+0.29%`; the same-quarter pair produces `+0.83%`. The 20-quarter
  history of correctly-paired gaps runs **+0.57% to +2.02%** (mean +1.12%), and
  the unpaired reading was the lowest value in that entire window — the
  numerical signature of a different quantity, not a different economy.
- `_quarters_between()` was wrong twice before it was right (first counting the
  whole projection block, then using day-count division). Now computed from
  year/month arithmetic against the latest *realised* potential observation.

**Verified**

- Live `output_gap`: `value=0.83`, `confidence=0.25`, pair date `2026-04-01`,
  actual `24,269.613`, potential `24,070.9386484`, 42 points withheld (41
  projections + 1 unpaired), horizon `2036-10-01`, staleness 1 quarter.
- Plausibility assessed on three independent grounds, including agreement with
  the labour market (unemployment 4.10% vs NAIRU 4.4% — tight by 0.30pp).
- Mutation testing of every guard: removing the as-of filter fails 4 tests,
  inverting the sign fails 6, reverting to own-latest pairing fails 4, removing
  the D-010 guard fails 2.
- Quality gates: ruff clean, ruff-format clean, `mypy --strict` clean on 34
  files, 66 offline tests passing / 1 skipped, 5 live tests passing.

**Note**

- Hardcoding `confidence=0.5` fails **0** tests. Under the uncalibrated config
  the formula's output for this model coincides exactly with the illustrative
  literal. Recorded as a finding rather than papered over; a test now measures
  the discrimination gap and activates the moment calibration widens it.

### Decision D-001 — `on_rrp_rate` rebound to `RRPONTSYAWARD`

**Fixed**

- Section 21.1 names FRED `RRPONTSYD` as the `on_rrp_rate` source. A live probe
  measured **0.70** — the ON-RRP *volume* in USD billions, not a rate. The
  administered offering rate `RRPONTSYAWARD` measured **3.50%** and slots
  correctly into the observed corridor.

**Added**

- `on_rrp_volume_bn` → FRED `RRPONTSYD`, supplying the
  `repo_volume_change_pct` corroboration Section 22.11 requires before
  `repo_stress_check` may escalate to `ACUTE_REPO_STRESS`. Without it, the
  corrected rule has no source.

**Note**

- Section 21.0 rule 3 forbids resolving this by assumption, so the fork was put
  to the user and approved before implementation. Recorded as D-001.

---

## [1.0.0] — 2026-09-16

### Phase 0 — skeleton, tooling, verification

**Added**

- `pyproject.toml` — `uv`-managed. Ruff with `DTZ` (bans naive datetimes) and
  `T20` (bans stray prints); `mypy` strict with `python_version = "3.12"`.
- `config/settings.yaml` — every parameter in a `{value, calibration_status,
  note}` envelope. `calibration_status` feeds `is_heuristic_not_calibrated` into
  `compute_confidence()`, so an uncalibrated parameter mechanically lowers the
  confidence of every model using it.
- `config/series_registry.yaml` — the only source of series routing. No
  provider, symbol or endpoint literal appears in application code.
- `config/logging.yaml`, `.env.example`.
- `models/contracts.py` — `ModelResult`, `compute_confidence()`, `utc_now()`,
  `ModelValue` per Section 22.9.
- `thesis_layer/schemas.py` — `MacroThesis` with five validation gates;
  `NO TRADE` as a first-class outcome.
- `extensions/*.py` — six correctly-signed Phase 4+ stubs, each raising
  `NotImplementedError` naming its phase.
- `.github/workflows/quality-gates.yml` — `quality` job on push, scheduled
  `live-data` job.
- `tools/manual_series_check.py` — route verification CLI reading plausibility
  bounds from the registry.

**Note on the initial design**

- `compute_confidence()`'s `source_independence_bonus_cap` was originally 0.15,
  which made the documented 0.95 ceiling **arithmetically unreachable** — the
  clamp was decorative rather than binding. Raised to 0.25, and
  `ConfidenceSettings._ceiling_must_be_reachable` now rejects a config where the
  ceiling cannot be reached, so this class of silent inconsistency cannot
  return.
