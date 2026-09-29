"""Mutation sweep for Section 20.9's ``intervention_capacity`` — the model, its
reserves client, and its config block.

**One function, one new module, one new client, one sweep** (D-117's shape,
following D-109/D-110/D-112/D-114). The labels are partitioned by FILE, because
this increment introduced a new module *and* a new data-layer client *and* a new
config class, and a mutant's label must tell a human which file it lives in:

* **``I1``-``I9``** and **``N1``** are ``models/intervention.py``'s — the model's
  own decisions plus its config accessors.
* **``R1``-``R8``** are ``data_layer/reserves_client.py``'s — the fetch, the
  lookup, the unit handling and the twelve-month change.
* **``N2``-``N4``** are ``src/macro_engine/config.py``'s ``InterventionSettings``
  — the accessors and the two validators.

⚠️ **This sweep is NOT a sixth ``mutation_fx_carry.py`` segment.** The module is
new, the client is new, and the config class is new, so nothing here widens an
existing anchor — but the sweep follows the same discipline for the same reason:
**every ``old`` string below was measured at exactly one occurrence with
``str.count()`` before being written**, and the measurement (not the author's
belief about the bytes) is what the file records. The first pass of this very
increment caught an O-142-class trap: four multi-line anchors written from the
docstring's prose measured **0** sites, because the rendered text and the source
bytes differed by an em-dash and a line break. A bare anchor is a CLAIM about
bytes, and an unmeasured one certifies nothing.

Why this module is swept at all
--------------------------------
``intervention_capacity`` is the only Module 9 function whose **core claim is a
doctrine rather than an estimate**, and its decisions are exactly the ones a
future edit is most likely to "simplify": the direction branch (which side is
reserve-constrained), the millions→billions conversion (a 1000x error that looks
plausible at either scale), the confidence **product** (which replaced a ``min()``
that made one factor dead code), the direction-INDEPENDENT burn warning (which a
"tidy-up" would push behind the reserve-constrained branch and thereby silence on
the direction whose failure mode is cost-driven), the refusal (which a
"convenience" edit would replace with a ``None``), and the domain guards.

What the grouping means
-----------------------
* **``I1``** breaks the DIRECTION BRANCH — the whole content of the asymmetry.
  ``I1a`` swaps the two arms' labels, ``I1b``/``I1c`` move the branch or its
  guard.
* **``I2``** breaks the ASYMMETRY vocabulary — the ``§22.11`` rename and the
  declared direction tuple.
* **``I3``** breaks the RESERVE RESOLUTION — fetch vs supplied, and the burn
  fallback.
* **``I4``** breaks the REFUSAL — the one place the model declines to answer.
* **``I5``** breaks the CONFIDENCE — the product and each of its four inputs.
* **``I6``** breaks the BURN WARNING — the alert comparison and its two messages.
* **``I7``** breaks the PUBLISHED VALUE — each key, the unit and the source
  family.
* **``I8``** breaks the DOMAIN GUARDS.
* **``I9``** breaks the FETCHER — the millions→billions division and its absence.
* **``R*``** breaks the CLIENT — the map, the lookup, the frame reading, the
  latest-observation selection, the twelve-month change and the error paths.
* **``N1``-``N4``** break the CONFIG — each accessor and each validator.

**⚠️ ``I1a`` and the canary are the two mutations that must NOT survive.**
``I1a`` swaps the labels, which inverts the entire published verdict; the canary
is a syntax error, and if it survives the selection no longer reaches the module
and no kill below is evidence about the suite (O-72, D-051) — the sweep REFUSES
TO CERTIFY rather than reporting health.

**⚠️ THE FIRST RUN LEFT 14 SURVIVORS, AND THE TRIAGE IS THE INCREMENT'S SECOND
DISCOVERY.** Every one was a **weak test** — none was an inert or broken
mutation — and the classes are worth writing down because they are all the same
failure in different costumes: **a test that reproduced the code's own
expression instead of measuring the code's output** (D-050's ``C6b``, again):

* **``I9a``/``I9b``** — the ONLY conversion test patched the model's own
  ``_fetch_reserves_bn`` and supplied the already-divided number
  (``1083420.49 / 1000.0``), so the model's division line **never executed**. A
  build that dropped it published the same figure. Fixed by patching at the
  **client** boundary (``fetch_reserves``) so the division happens in the code
  under test, plus a **leaf perturbation** of the divisor that proves it is
  load-bearing.
* **``R6a``** — the constant it mutates (``_MILLIONS_PER_BILLION``) was **defined
  and never used**: the model divided by a bare ``1000.0``. This is a **CODE
  defect the sweep found**, not a test defect — the docstring claimed the named
  constant existed "so a mutation has to change the constant", and it did not
  exist in the expression. Fixed by promoting it to a public
  ``MILLIONS_PER_BILLION`` in the client and **importing it in the model**, so
  the 1000x step has one definition.
* **``I3c``** — every fixture either supplied the burn rate or supplied the stock,
  so the fetch→burn **fallback** was never executed. Fixed by a fixture that lets
  the reading supply the burn, with a **negative control** that a caller-supplied
  burn is not overwritten.
* **``I2a``/``I5e``/``I6d``/``I6e``/``I7c``/``I7d``/``N1b``/``N3a``** — the
  published/derived fields were asserted only through their **shipped default
  values**, where a swapped tuple, a dropped independence count, an inverted
  message branch, a nulled field, or a hardcoded constant all coincide with the
  truth. Fixed by asserting the **order** of the tuple, the **exact value** of
  the fetched confidence, the **message bodies** of both burn branches, the
  **echoed** inputs, and **leaf-perturbation fixtures** with distinct sentinels.
* **``N4a``/``N4b``** — the two config validators were **never driven to fire**,
  so ``if False:`` replaced them unnoticed. Fixed by tests that pass an
  out-of-range cap and a non-positive alert and require the refusal.

**The re-run returns 60/60 killed**, and no mutation was deleted or weakened —
each was strengthened-toward (D-031). The tree was verified clean with the
sidecar ABSENT before and after (O-131).

A survivor is one of three things (D-031): a weak test, an **inert** mutation, or
a **broken** mutation. The runner heals before it measures — an interrupted run
leaves the mutated file on disk, and a naive re-run would adopt it as the
baseline (D-035 rule 19).
"""

from __future__ import annotations

import sys
from pathlib import Path

from _sweep_gate import (
    check_only_requested,
    check_targets,
    format_problems,
    sweep_lifecycle,
)
from _sweep_gate import run_pytest as _run_pytest_inproc

SRC = Path("src/macro_engine/models/intervention.py")
CLIENT = Path("src/macro_engine/data_layer/reserves_client.py")
CONFIG = Path("src/macro_engine/config.py")

# --------------------------------------------------------------------------
# I1: the direction branch — the whole content of the asymmetry.
# --------------------------------------------------------------------------

# The branch line and the two label assignments. Each is a separate span so a
# mutation can flip ONE arm: a single block would move both labels together and
# hide a real defect.
_DIRECTION_BRANCH = '    if inputs.direction == "strengthen_own_currency":'
_RESERVE_CONSTRAINED_LABEL = "        capacity = intervention.reserve_constrained_label"
_UNCONSTRAINED_LABEL = "        capacity = intervention.mechanically_unconstrained_label"

# --------------------------------------------------------------------------
# I2: the asymmetry vocabulary.
# --------------------------------------------------------------------------

# The declared direction tuple. The `tuple[str, str]` annotation is unique to
# this line (the config side uses `CalibratedValue`), so a bare tuple body is
# safe but the annotated form is unambiguous.
_DIRECTIONS_TUPLE = (
    "INTERVENTION_DIRECTIONS: tuple[str, str] = (\n"
    '    "strengthen_own_currency",\n'
    '    "weaken_own_currency",\n'
    ")"
)
# The field's Literal. This is the guard against Section 20.9's bare-`else`
# fall-through, so a mutation that widens it back to `str` is the specification's
# original defect reappearing.
_DIRECTION_LITERAL = (
    '    direction: Literal["strengthen_own_currency", "weaken_own_currency"] = Field('
)

# --------------------------------------------------------------------------
# I3: the reserve resolution — fetch vs supplied.
# --------------------------------------------------------------------------

_FETCH_CALL = (
    "        reserves_bn, fetched_burn_pct, reserves_provenance = "
    "_fetch_reserves_bn(inputs.country)"
)
# WIDENED: `    if reserves_bn is None:` alone is AMBIGUOUS (2 occurrences) — it
# opens both the fetch branch AND the refusal guard inside the direction branch.
# The fetch branch's distinguishing feature is the line it guards: the refusal
# guard is followed by `raise ValueError(`, the fetch branch by the fetcher call.
# Anchoring on the branch line PLUS its follower resolves it to one site — the
# D-055/D-060 remedy, never a deletion.
_FETCH_BRANCH = (
    "    if reserves_bn is None:\n"
    "        reserves_bn, fetched_burn_pct, reserves_provenance = _fetch_reserves_bn("
)
# The burn-rate fallback: the fetched change is adopted only when the caller
# supplied none. Narrowed by its two-line span because `if burn_pct is None:`
# alone ALSO opens the "no change available" warning block below (2 sites).
_BURN_FALLBACK = "        if burn_pct is None:\n            burn_pct = fetched_burn_pct"
_SUPPLIED_PROVENANCE = (
    '            "SUPPLIED BY THE CALLER — the unit is billions of USD as declared "'
)

# --------------------------------------------------------------------------
# I4: the refusal.
# --------------------------------------------------------------------------

_REFUSAL_RAISE = (
    "            raise ValueError(\n"
    "                \"A 'strengthen_own_currency' verdict is a claim that a FINITE \""
)
_REFUSAL_GUARD = "        if reserves_bn is None:\n            raise ValueError("

# --------------------------------------------------------------------------
# I5: the confidence — the product and its four inputs.
# --------------------------------------------------------------------------

_CONFIDENCE_PRODUCT = "    confidence = computed * intervention.reliability_value"
_COMPUTED_CALL = "    computed = compute_confidence(\n        ConfidenceInputs("
_FLAGS_PRESENT = "            data_quality_flags_present=not fetched,"
_HEURISTIC_FLAG = (
    "            is_heuristic_not_calibrated=not intervention.reliability_cap_is_calibrated,"
)
_SOURCE_INDEP = "            source_independence_count=1 if fetched else 0,"
_FETCHED_FLAG = (
    '    fetched = reserves_bn is not None and reserves_provenance.startswith("FETCHED")'
)

# --------------------------------------------------------------------------
# I6: the burn warning — the alert comparison and its messages.
# --------------------------------------------------------------------------

# The alert condition. `<= -value` is the sign convention the config leaf's
# docstring pins; `>=` or a dropped negation both make the warning fire the wrong
# way round.
_BURN_ALERT = "    if burn_pct is not None and burn_pct <= -intervention.burn_alert_value:"
_BURN_ALERT_MSG = (
    '                "This is the CRITICAL_PEG_STRESS setup check_trilemma_tension() names."'
)
_BURN_ALERT_BRANCH = (
    "                if capacity == intervention.reserve_constrained_label\n                else ("
)
# The "no change available" warning. `if burn_pct is None:` alone is AMBIGUOUS
# (the burn fallback above shares it), so the span carries the warning's own
# opening text.
_BURN_NONE_WARN = (
    "    if burn_pct is None:\n"
    "        warnings.append(\n"
    '            "No twelve-month reserve change is available'
)
# The direction-specific warning's two arms.
_WARN_CONSTRAINED = (
    "    if capacity == intervention.reserve_constrained_label:\n"
    "        warnings.append(\n"
    '            "Reserve-constrained defences are BREAKABLE'
)

# --------------------------------------------------------------------------
# I7: the published value and the contract.
# --------------------------------------------------------------------------

_CAPACITY_KEY = '            "capacity": capacity,'
_RESERVES_KEY = '            "reserves_usd_bn": reserves_bn,'
_BURN_KEY = '            "reserves_change_12m_pct": burn_pct,'
_DIRECTION_KEY = '            "direction": inputs.direction,'
_UNIT = '        unit="usd_billions",'
_SOURCE_FAMILY = (
    "            EvidenceSourceFamily.IMF if fetched else EvidenceSourceFamily.MANUAL_ASSESSMENT"
)

# --------------------------------------------------------------------------
# I8: the domain guards.
# --------------------------------------------------------------------------

# The positivity guard. D-142 deleted `_FINITE_LOOP` and `_ISFINITE_GUARD`
# together with the I8a/I8b mutations that anchored on them: the local
# finiteness loop is gone (the class inherits `contracts.FiniteInputs`), so an
# anchor on it would resolve to nothing and this sweep would refuse to run.
_POSITIVE_GUARD = (
    "        if self.fx_reserves_usd_bn is not None and self.fx_reserves_usd_bn <= 0.0:"
)

# --------------------------------------------------------------------------
# I9: the fetcher — the millions to billions conversion.
# --------------------------------------------------------------------------

_MILLIONS_DIV = "        reading.reserves_usd_mn / MILLIONS_PER_BILLION,"

# --------------------------------------------------------------------------
# R1-R8: the reserves client.
# --------------------------------------------------------------------------

_R_LOOKUP = "    entry = RESERVE_SERIES.get(key)"
_R_KEY_NORMALIZE = "    key = country.strip().lower()"
_R_ENTRY_NONE = "    if entry is None:"
_R_FETCH_SERIES = "        frame = active.fetch_series("
_R_PROVIDER = '            provider="fred",'
_R_EMPTY_FRAME = "    if frame.empty:"
_R_COLUMNS_GUARD = '    if "date" not in frame.columns or "value" not in frame.columns:'
_R_DROPNA = '    cleaned = frame.loc[:, ["date", "value"]].dropna(subset=["value"])'
_R_SORT = '    cleaned = cleaned.sort_values("date")'
_R_LAST_VALUE = "    last_value = float(values[-1])"
_R_LAG_GUARD = "    if len(values) > _CHANGE_LAG_MONTHS:"
_R_PRIOR_INDEX = "        prior = float(values[-(_CHANGE_LAG_MONTHS + 1)])"
_R_ZERO_PRIOR = "        if prior != 0.0:"
_R_CHANGE_CALC = "            change_12m_pct = (last_value - prior) / prior * 100.0"
_R_MILLIONS_PER_BILLION = "MILLIONS_PER_BILLION = 1000.0"
_R_CHANGE_LAG = "_CHANGE_LAG_MONTHS = 12"

# --------------------------------------------------------------------------
# N1-N4: the config.
#
# ⚠️ D-119: `EMVulnerabilitySettings` was added to config.py with accessors and
# a validator whose bodies are TEXTUALLY IDENTICAL to InterventionSettings' —
# `return float(self.reliability_cap.value)`,
# `return self.reliability_cap.is_trustworthy`, and
# `if not 0.0 <= self.reliability_value <= 1.0:` each occur TWICE now. Every
# mutation that hardcodes a constant is a WEAK test (D-031). A name-grep is not
# a coverage proxy (O-133) — and an anchor that matches two sites is not a
# mutation, it is an ambiguity. Each of the three below is therefore WIDENED
# with a distinguishing NEIGHBOUR line that exists only in InterventionSettings:
# the accessors include their unique docstring tail, the validator includes its
# `intervention.reliability_cap` error message. WIDEN, never delete (D-109).
# --------------------------------------------------------------------------

_N1_RELIABILITY_PROP = (
    "        Deliberately **below** both parity caps — see the class docstring.\n"
    '        """\n'
    "        return float(self.reliability_cap.value)"
)
_N1_CALIBRATED_READ = (
    "        of assuming it. ``CalibratedValue.is_trustworthy`` is False for\n"
    "        ``uncalibrated_illustrative``, which is what this leaf is.\n"
    '        """\n'
    "        return self.reliability_cap.is_trustworthy"
)
_N2_UNCONSTRAINED_PROP = "        return str(self.unconstrained_label.value)"
_N2_CONSTRAINED_PROP = "        return str(self.reserve_constrained_label_text.value)"
_N3_BURN_PROP = "        return float(self.burn_alert_pct.value)"
_N4_RELIABILITY_VALIDATOR = (
    "        if not 0.0 <= self.reliability_value <= 1.0:\n"
    "            raise ValueError(\n"
    '                f"intervention.reliability_cap is {self.reliability_value}. A "'
)
_N4_BURN_VALIDATOR = "        if self.burn_alert_value <= 0.0:"


_MUTATIONS: list[tuple[str, Path, str, str]] = [
    # -- canary (CONTROL) -------------------------------------------------
    # NOT a revert of a project decision: a mutation CERTAIN to be caught, so
    # the sweep can REFUSE TO CERTIFY when it survives. The anchor is the
    # module's FIRST STATEMENT — the future import — so it does not churn the
    # way `__all__` does (O-119/O-126).
    (
        "CANARY1 the module literal is replaced with a syntax error (CONTROL)",
        SRC,
        "from __future__ import annotations",
        "__CANARY__ = <<<SYNTAX ERROR>>>",
    ),
    # --- I1: the direction branch ----------------------------------------
    (
        "I1a the two direction arms publish each other's label",
        SRC,
        _RESERVE_CONSTRAINED_LABEL,
        "        capacity = intervention.mechanically_unconstrained_label",
    ),
    (
        "I1b the strengthening arm takes the weakening branch",
        SRC,
        _DIRECTION_BRANCH,
        '    if inputs.direction == "weaken_own_currency":',
    ),
    (
        "I1c the weakening arm publishes the reserve-constrained label",
        SRC,
        _UNCONSTRAINED_LABEL,
        "        capacity = intervention.reserve_constrained_label",
    ),
    # --- I2: the asymmetry vocabulary ------------------------------------
    (
        "I2a the direction tuple's two members are swapped",
        SRC,
        _DIRECTIONS_TUPLE,
        "INTERVENTION_DIRECTIONS: tuple[str, str] = (\n"
        '    "weaken_own_currency",\n'
        '    "strengthen_own_currency",\n'
        ")",
    ),
    (
        "I2b the field is widened to accept any string (Section 20.9's bare-else defect)",
        SRC,
        _DIRECTION_LITERAL,
        "    direction: str = Field(",
    ),
    # --- I3: the reserve resolution --------------------------------------
    (
        "I3a the fetcher is never called (reserves silently null)",
        SRC,
        _FETCH_CALL,
        "        reserves_bn, fetched_burn_pct, reserves_provenance = None, None, 'NOT FETCHED'",
    ),
    (
        "I3b the fetch branch is unreachable (a supplied value is never fetched for)",
        SRC,
        _FETCH_BRANCH,
        "    if False:\n"
        "        reserves_bn, fetched_burn_pct, reserves_provenance = _fetch_reserves_bn(",
    ),
    (
        "I3c the fetched burn rate is discarded (never adopted)",
        SRC,
        _BURN_FALLBACK,
        "        if False:\n            burn_pct = fetched_burn_pct",
    ),
    (
        "I3d a supplied figure is disclosed as if it were fetched",
        SRC,
        _SUPPLIED_PROVENANCE,
        '            "FETCHED — the unit is billions of USD as declared "',
    ),
    # --- I4: the refusal --------------------------------------------------
    (
        "I4a the refusal is removed (a null travels as a value)",
        SRC,
        _REFUSAL_GUARD,
        "        if False:\n            raise ValueError(",
    ),
    (
        "I4b the refusal's message is detached from the branch it guards",
        SRC,
        _REFUSAL_RAISE,
        "            raise ValueError(\n"
        "                \"A 'weaken_own_currency' verdict is a claim that a FINITE \"",
    ),
    # --- I5: the confidence ----------------------------------------------
    (
        "I5a the confidence is summed instead of multiplied (the cap stops bounding)",
        SRC,
        _CONFIDENCE_PRODUCT,
        "    confidence = computed + intervention.reliability_value",
    ),
    (
        "I5b the computed half is dropped (a bare cap literal)",
        SRC,
        _CONFIDENCE_PRODUCT,
        "    confidence = intervention.reliability_value",
    ),
    (
        "I5c the data-quality flag is inverted (a fetched figure looks worse)",
        SRC,
        _FLAGS_PRESENT,
        "            data_quality_flags_present=fetched,",
    ),
    (
        "I5d the heuristic penalty is dropped",
        SRC,
        _HEURISTIC_FLAG,
        "            is_heuristic_not_calibrated=False,",
    ),
    (
        "I5e a fetched figure contributes no independent family",
        SRC,
        _SOURCE_INDEP,
        "            source_independence_count=0,",
    ),
    (
        "I5f the fetched flag ignores the provenance (every reserve reads as fetched)",
        SRC,
        _FETCHED_FLAG,
        "    fetched = reserves_bn is not None",
    ),
    (
        "I5g the computed confidence never runs",
        SRC,
        _COMPUTED_CALL,
        "    computed = 0.5\n    _unused = compute_confidence(\n        ConfidenceInputs(",
    ),
    # --- I6: the burn warning --------------------------------------------
    (
        "I6a the burn comparison is reversed (fires on ACCUMULATION)",
        SRC,
        _BURN_ALERT,
        "    if burn_pct is not None and burn_pct >= -intervention.burn_alert_value:",
    ),
    (
        "I6b the burn alert threshold is dropped (fires on any decline)",
        SRC,
        _BURN_ALERT,
        "    if burn_pct is not None and burn_pct <= 0.0:",
    ),
    (
        "I6c the burn warning is gated behind the reserve-constrained branch",
        SRC,
        _BURN_ALERT,
        "    if (\n"
        "        capacity == intervention.reserve_constrained_label\n"
        "        and burn_pct is not None\n"
        "        and burn_pct <= -intervention.burn_alert_value\n"
        "    ):",
    ),
    (
        "I6d the burn message's branch condition is inverted",
        SRC,
        _BURN_ALERT_BRANCH,
        "                if capacity != intervention.reserve_constrained_label\n"
        "                else (",
    ),
    (
        "I6e the CRITICAL_PEG_STRESS message is replaced with the generic one",
        SRC,
        _BURN_ALERT_MSG,
        '                "A cost-driven defence can also exhaust the stock."',
    ),
    (
        "I6f the unknown-burn warning is removed",
        SRC,
        _BURN_NONE_WARN,
        "    if False:\n"
        "        warnings.append(\n"
        '            "No twelve-month reserve change is available',
    ),
    (
        "I6g the reserve-constrained warning is removed",
        SRC,
        _WARN_CONSTRAINED,
        "    if False:\n"
        "        warnings.append(\n"
        '            "Reserve-constrained defences are BREAKABLE',
    ),
    # --- I7: the published value and the contract -------------------------
    (
        "I7a the published capacity is a constant",
        SRC,
        _CAPACITY_KEY,
        '            "capacity": "UNKNOWN",',
    ),
    (
        "I7b the published reserves are nulled",
        SRC,
        _RESERVES_KEY,
        '            "reserves_usd_bn": None,',
    ),
    (
        "I7c the published burn rate is nulled",
        SRC,
        _BURN_KEY,
        '            "reserves_change_12m_pct": None,',
    ),
    (
        "I7d the published direction is a constant",
        SRC,
        _DIRECTION_KEY,
        '            "direction": "strengthen_own_currency",',
    ),
    (
        "I7e the unit is published as millions",
        SRC,
        _UNIT,
        '        unit="usd_millions",',
    ),
    (
        "I7f a manual figure is published as an IMF source family",
        SRC,
        _SOURCE_FAMILY,
        "            EvidenceSourceFamily.IMF",
    ),
    # --- I8: the domain guards -------------------------------------------
    # D-142 REMOVED I8a ("the finiteness guard removed") and I8b ("the
    # finiteness loop guards no field") rather than retargeting them: the local
    # `for name, value in (...)` finiteness loop they mutated NO LONGER EXISTS.
    # `InterventionCapacityInputs` now inherits `contracts.FiniteInputs`, which
    # derives its field list from `model_fields`, so there is no hardcoded loop
    # left to mutate. The D-078 behaviour those mutations probed is covered by
    # `tests/models/test_finite_inputs_repo_wide.py`, which builds EVERY
    # float-bearing input group, contaminates each field at its declared shape,
    # and asserts refusal — a strictly stronger check than two mutations of one
    # hand-written loop. Keeping a mutation anchored on deleted text would make
    # this sweep refuse to run at all (O-138), which is the failure mode it is
    # designed to surface.
    (
        "I8c a zero reserve stock is admitted",
        SRC,
        _POSITIVE_GUARD,
        "        if self.fx_reserves_usd_bn is not None and self.fx_reserves_usd_bn < 0.0:",
    ),
    # --- I9: the fetcher's conversion ------------------------------------
    (
        "I9a the fetched reserves are not converted (millions published as billions)",
        SRC,
        _MILLIONS_DIV,
        "        reading.reserves_usd_mn,",
    ),
    (
        "I9b the conversion multiplies instead of divides (1000x inverted)",
        SRC,
        _MILLIONS_DIV,
        "        reading.reserves_usd_mn * 1000.0,",
    ),
    # --- R1-R8: the reserves client --------------------------------------
    (
        "R1a the country lookup key is not normalised (case-sensitive miss)",
        CLIENT,
        _R_KEY_NORMALIZE,
        "    key = country",
    ),
    (
        "R1b the map lookup is replaced with a constant series",
        CLIENT,
        _R_LOOKUP,
        '    entry = RESERVE_SERIES.get("jp")',
    ),
    (
        "R1c an unregistered country borrows a series instead of returning None",
        CLIENT,
        _R_ENTRY_NONE,
        '    if entry is None:\n        entry = ("TRESEGJPM052N", "japan")\n    if False:',
    ),
    (
        "R2a the FRED provider is replaced with another",
        CLIENT,
        _R_PROVIDER,
        '            provider="oecd",',
    ),
    (
        "R2b the series symbol is dropped from the request",
        CLIENT,
        _R_FETCH_SERIES,
        "        frame = active.fetch_series(\n"
        '            provider="fred",\n'
        '            endpoint="economy.fred_series",\n'
        "            params={},\n"
        '            series_label=f"fx_reserves_{key}",\n'
        "        )\n"
        "        frame = frame.iloc[:0].assign(date=[], value=[])\n"
        "        _dead = active.fetch_series(",
    ),
    (
        "R3a an empty frame is returned as a reading rather than refused",
        CLIENT,
        _R_EMPTY_FRAME,
        "    if False:",
    ),
    (
        "R3b the tidy-column guard is removed (the date column read as the value)",
        CLIENT,
        _R_COLUMNS_GUARD,
        "    if False:",
    ),
    (
        "R3c missing values are not dropped (nan reaches the arithmetic)",
        CLIENT,
        _R_DROPNA,
        '    cleaned = frame.loc[:, ["date", "value"]]',
    ),
    (
        "R4a the frame is not sorted (latest becomes oldest)",
        CLIENT,
        _R_SORT,
        "    cleaned = cleaned",
    ),
    (
        "R4b the oldest observation is published as the latest",
        CLIENT,
        _R_LAST_VALUE,
        "    last_value = float(values[0])",
    ),
    (
        "R5a the twelve-month change is not computed (always None)",
        CLIENT,
        _R_LAG_GUARD,
        "    if False:",
    ),
    (
        "R5b the change is measured one step back, not twelve",
        CLIENT,
        _R_PRIOR_INDEX,
        "        prior = float(values[-1])",
    ),
    (
        "R5c the change's sign is flipped",
        CLIENT,
        _R_CHANGE_CALC,
        "            change_12m_pct = (prior - last_value) / prior * 100.0",
    ),
    (
        "R5d a zero prior is divided by (an infinite percentage published)",
        CLIENT,
        _R_ZERO_PRIOR,
        "        if True:",
    ),
    (
        "R6a the millions-per-billion constant is changed (a 1000x error at its root)",
        CLIENT,
        _R_MILLIONS_PER_BILLION,
        "MILLIONS_PER_BILLION = 100.0",
    ),
    (
        "R6b the twelve-month lag is changed to one month",
        CLIENT,
        _R_CHANGE_LAG,
        "_CHANGE_LAG_MONTHS = 1",
    ),
    # --- N1-N4: the config -----------------------------------------------
    (
        "N1a the reliability accessor returns the burn-alert leaf",
        CONFIG,
        _N1_RELIABILITY_PROP,
        "        return float(self.burn_alert_pct.value)",
    ),
    (
        "N1b the calibration helper reports calibrated unconditionally",
        CONFIG,
        _N1_CALIBRATED_READ,
        "        return True",
    ),
    (
        "N2a the unconstrained accessor returns the reserve-constrained leaf",
        CONFIG,
        _N2_UNCONSTRAINED_PROP,
        "        return str(self.reserve_constrained_label_text.value)",
    ),
    (
        "N2b the reserve-constrained accessor returns the unconstrained leaf",
        CONFIG,
        _N2_CONSTRAINED_PROP,
        "        return str(self.unconstrained_label.value)",
    ),
    (
        "N3a the burn-alert accessor returns the reliability cap",
        CONFIG,
        _N3_BURN_PROP,
        "        return float(self.reliability_cap.value)",
    ),
    (
        "N4a the cap-range validator removed",
        CONFIG,
        _N4_RELIABILITY_VALIDATOR,
        "        if False:",
    ),
    (
        "N4b the positive burn-alert validator removed",
        CONFIG,
        _N4_BURN_VALIDATOR,
        "        if False:",
    ),
]


def run_tests() -> bool:
    proc = _run_pytest_inproc(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_intervention.py",
            "tests/data_layer/test_reserves_client.py",
            "tests/test_infrastructure.py",
            "-q",
            "--no-header",
            # `-x` is D-057's rule, not a preference: a kill is a kill, the
            # first failing test is sufficient evidence, and an interrupted
            # long run on win32 leaves every mutant applied so far on disk
            # (D-082).
            "-x",
            "-m",
            "not live",
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _check_targets_only() -> int:
    """Print the anchor verdict and STOP, touching nothing (O-138).

    **Must run BEFORE ``sweep_lifecycle``.** That helper writes a sidecar and
    installs the interrupt defence — i.e. it writes to the tree. A mode whose
    entire purpose is to be the SAFE pre-flight must not enter the path that
    mutates, or it recreates the very hazard it exists to avoid.

    Exit code is **0 for a clean verdict and 4 for problems** — the same 4 the
    sweep itself returns on a refusal, so a caller that already handles 4 needs
    no new case.
    """
    originals = {p: p.read_text(encoding="utf-8") for p in (SRC, CLIENT, CONFIG) if p.exists()}
    problems = check_targets(originals, _MUTATIONS)
    print(
        f"check_targets: {len(_MUTATIONS)} mutations, {len(problems)} problem(s)",
        flush=True,
    )
    if problems:
        print(format_problems(problems))
        print()
        print("ANCHORS UNSOUND: fix the anchors above before sweeping. A sweep that")
        print("cannot prove it mutates the site it names certifies nothing.")
        return 4
    print()
    print("Anchors sound: every mutation resolves to exactly one site. No mutation")
    print("was applied and no sidecar was written (O-138 — this mode stops here).")
    return 0


def main() -> int:
    # O-138: the check-only mode must be answered BEFORE the lifecycle writes
    # anything.
    if check_only_requested():
        return _check_targets_only()

    # The whole interrupt defence in one call (O-103): heal any sidecar a killed
    # previous run left behind, write the pristine text to a sidecar BEFORE the
    # first mutation, and consume it on the way out. On win32 no Python signal
    # handler runs for SIGTERM/SIGINT, so the sidecar — not a handler — is the
    # defence that actually has reach here.
    with sweep_lifecycle([SRC, CLIENT, CONFIG]) as originals:
        return _run_sweep(originals)


def _run_sweep(originals: dict[Path, str]) -> int:
    problems = check_targets(originals, _MUTATIONS)
    print(f"check_targets: {len(_MUTATIONS)} mutations, {len(problems)} problem(s)", flush=True)
    if problems:
        print(format_problems(problems))
        print()
        print("REFUSING TO RUN: fix the anchors above first. A sweep that cannot")
        print("prove it mutates the site it names certifies nothing.")
        return 4

    survivors: list[tuple[str, str]] = []
    try:
        for name, target, old, new in _MUTATIONS:
            pristine = originals[target]
            if old not in pristine:
                print(f"PATTERN MISSING   {name}  [{target.name}]", flush=True)
                survivors.append((name, "pattern-not-found"))
                continue
            target.write_text(pristine.replace(old, new, 1), encoding="utf-8", newline="")
            caught = not run_tests()
            target.write_text(pristine, encoding="utf-8", newline="")
            print(f"{'KILLED' if caught else 'SURVIVED':17} {name}", flush=True)
            if not caught:
                survivors.append((name, "survived"))
    finally:
        # Belt and braces: an exception mid-mutation must never leave the tree
        # mutated. A SIGTERM on win32 still can — no handler and no ``finally``
        # gets a turn — which is the case the sidecar covers, not this.
        for path, text in originals.items():
            path.write_text(text, encoding="utf-8", newline="")

    print()
    print("=" * 74)
    total = len(_MUTATIONS)
    killed = total - len(survivors)
    print(
        f"MUTATION SWEEP — intervention (intervention_capacity + reserves_client "
        f"+ InterventionSettings): {killed}/{total} killed",
        flush=True,
    )
    print("=" * 74)
    if survivors:
        print("SURVIVORS (each is a weak test, an inert mutation, or a broken one):")
        for name, reason in survivors:
            print(f"  [{reason}] {name}")
    # O-72's canary gate. A canary that SURVIVES means the sweep ran but tested
    # nothing (D-051). CANARY1 is REQUIRED to be killed, not tolerated.
    if any(name.startswith("CANARY1 ") for name, _ in survivors):
        print()
        print("REFUSING TO CERTIFY: the honesty canary SURVIVED.")
        print("  !! CANARY1 -- the test selection no longer reaches the mutated")
        print("     module, so no kill above is evidence about the suite (O-72).")
        return 3
    if survivors:
        return 1
    print("  every mutation killed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
