"""Mutation sweep for Section 6.9's ``sector_rotation_prior`` — the model and
its config block.

**One function, one new module, one sweep** (D-108/D-118's shape). The labels are
partitioned by concern, not by file, because this increment adds a new model
module and a new config class but **no new data-layer client** (the function
reads no market data — its only input is a regime label):

* **``E1``-``E9``** are ``models/equity_macro.py``'s — the map, the coverage
  constants, the lookup, the fallback, the confidence, the warnings and the
  published contract.
* **``N1``-``N3``** are ``src/macro_engine/config.py``'s ``EquityMacroSettings``
  — the accessors and the two validators.

Why this module is swept at all
--------------------------------
``sector_rotation_prior`` is a LOOKUP, and a lookup's defects are silent by
construction: every row is a plausible list of sectors, and every branch returns
a well-formed result. The decisions a future edit is most likely to "simplify"
are exactly the ones this increment exists to protect:

* **the exhaustiveness of the map** over the classifier's vocabulary — the whole
  reason this function supersedes Section 6.9's six-key reference (three
  reachable states, ``slowdown`` / ``recovery`` / ``reflation``, would silently
  return the generic fallback);
* **the vocabulary refusal** — the field typed as the classifier's ``Literal``,
  which stops a misspelling reaching the ``.get``;
* **the confidence product** — which replaced the ``min()`` that would have made
  one factor dead code;
* **the prior-not-rule caveat** — the model's central claim about itself, which a
  tidy-up would move to prose.

⚠️ **Every ``old`` string below was measured at exactly one occurrence with
``str.count()`` before being written**, and the measurement (not the author's
belief about the bytes) is what this file records. The FIRST measurement pass
found the caveat warning string at **2** sites (it appears in both ``warnings``
and ``context``) and the three config accessor/validator bodies at **6** sites
each (five sibling settings blocks share byte-identical bodies — the O-145
collision). Every one was WIDENED with a distinguishing neighbour, never deleted
(D-109).

**⚠️ ``E1a`` and the canary are the two mutations that must NOT survive.**
``E1a`` removes a specification row, which is the coverage defect this function
was built to close; the canary is a syntax error, and if it survives the
selection no longer reaches the module and no kill below is evidence about the
suite (O-72, D-051) — the sweep REFUSES TO CERTIFY rather than reporting health.
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

SRC = Path("src/macro_engine/models/equity_macro.py")
CONFIG = Path("src/macro_engine/config.py")

# --------------------------------------------------------------------------
# E1: the map and the coverage constants.
# --------------------------------------------------------------------------

# The map declaration itself. A mutation that empties it makes EVERY regime fall
# back, which is the coverage hole in its purest form.
_MAP_DECL = "SECTOR_ROTATION_PRIOR: dict[str, tuple[str, ...]] = {"
# One specification row, removed. This is the increment's headline defect: the
# reference body omits three rows, so removing one from an exhaustive map proves
# the suite measures exhaustiveness rather than asserting it from the code.
_EARLY_ROW = '    "early_expansion": ("financials", "consumer_discretionary", "industrials"),'
# One extension row, removed. Distinct from the above: the extension rows are this
# build's declaration, so a mutation here proves the coverage test covers them too.
_SLOWDOWN_ROW = '    "slowdown": ("staples", "healthcare", "utilities"),'
# The specification tuple. Shortening it makes the partition test fail.
_SPEC_TUPLE = 'SPECIFICATION_REGIMES: tuple[str, ...] = (\n    "early_expansion",'
# The extension tuple. Widening it breaks the partition claim.
_EXT_TUPLE = 'SECTOR_PRIOR_EXTENSION_REGIMES: tuple[str, ...] = (\n    "slowdown",'

# --------------------------------------------------------------------------
# E2: the input field and the vocabulary refusal.
# --------------------------------------------------------------------------

# The field's Literal. Widening it back to `str` reintroduces Section 6.9's bare-
# string defect: a misspelling reaches the `.get` and receives the fallback.
#
# ⚠️ WIDENED AT D-124: adding `FactorTiltInputs` (Section 20.20-E) made the bare
# field line occur TWICE — both input models type `regime_state: RegimeState`.
# The anchor now carries the preceding docstring tail, which is unique to
# `SectorRotationInputs` ("never a confident answer about the wrong regime").
_INPUT_REGIME_FIELD = (
    "    value must produce an error, never a confident answer about the wrong regime.\n"
    '    """\n'
    "\n"
    '    model_config = ConfigDict(extra="forbid", frozen=True)\n'
    "\n"
    "    regime_state: RegimeState = Field("
)

# --------------------------------------------------------------------------
# E3: the lookup, the fallback and the published container.
# --------------------------------------------------------------------------

_GET_CALL = "    sectors = SECTOR_ROTATION_PRIOR.get(regime)"
_HAS_PRIOR = "    has_prior = sectors is not None"
_PUBLISHED = (
    "    published: list[str] = list(sectors) if sectors is not None else "
    "[equity_macro.no_prior_label]"
)

# --------------------------------------------------------------------------
# E4: the confidence — the product and its four inputs.
# --------------------------------------------------------------------------
#
# ⚠️ WIDENED AT D-124. Adding `duration_sensitivity` and `factor_tilt_prior` put
#    THREE `computed = compute_confidence(ConfidenceInputs(...))` blocks in this
#    module, so every bare input line now occurs 2-3 times. Each anchor carries
#    the distinguishing tail it shares with NO other block:
#    * `_COMPUTED_CALL` — prefixed by the sector site's `published`/`has_prior`
#      setup, which no other block has;
#    * `_FLAGS_PRESENT` — the sector block alone passes `not has_prior`; the other
#      two pass `False`. Widened with the following heuristic line, which is also
#      sector-only.
#    * `_SOURCE_INDEP` — the three blocks differ in the trailing product line, so
#      each anchor carries its own:
#      `* equity_macro.reliability_value` (sector), `.duration_reliability_value`,
#      `.factor_tilt_reliability_value`.

_COMPUTED_CALL = (
    "    published: list[str] = list(sectors) if sectors is not None else "
    "[equity_macro.no_prior_label]\n"
    "\n"
    "    # --- confidence: two producers, both load-bearing ------------------------\n"
)
_FLAGS_PRESENT = (
    "            data_quality_flags_present=not has_prior,\n"
    "            is_heuristic_not_calibrated=not equity_macro.reliability_cap_is_calibrated,"
)
# Sector-only: only this block prices the SECTOR cap's calibration status, so the
# bare line is unique despite the two sibling confidence blocks.
_HEURISTIC = (
    "            is_heuristic_not_calibrated=not equity_macro.reliability_cap_is_calibrated,"
)
# Sector-only: the sibling blocks end their products with the duration and
# factor-tilt cap names, so the bare product line is unique.
_CONF_PRODUCT = "    confidence = computed * equity_macro.reliability_value"
_SOURCE_INDEP = (
    "            source_independence_count=1,\n"
    "            depends_on_unobservable=False,\n"
    "        )\n"
    "    )\n"
    "    confidence = computed * equity_macro.reliability_value"
)

# --------------------------------------------------------------------------
# E5: the warnings and the caveat.
# --------------------------------------------------------------------------
#
# ⚠️ WIDENED: the caveat string occurs TWICE in the module — once in `warnings`
# and once in `context`. The `warnings: list[str] = [` opener distinguishes the
# warning site (the `context=(` opener does the same for the other), so each is
# one site.
_CAVEAT_WARNING = (
    "    warnings: list[str] = [\n"
    '        "This is a historical BASE-RATE PRIOR, not a mechanical rule — every "'
)
_FALLBACK_WARNING = (
    '            f"Regime {regime!r} is a declared classifier state with no defined "\n'
    '            f"sector prior, so no rotation is applied.'
)
_EXT_ASSUMPTION = '            f"The row for {regime!r} is this build\'s declaration, NOT Section "'

# --------------------------------------------------------------------------
# E6: the published contract and the module-level import assertion.
#
# ⚠️ WIDENED AT D-124. `value=published,`, `source_family=...` and `country="us",`
#    each now occur THREE times (one per function), so each anchor carries a
#    sibling line unique to the sector result: the sector unit is
#    `"sector_names"` (the others are `"percent_price_change"` and
#    `"tilt_minus1_to_plus1"`), so the contract anchors are pinned through it.
# --------------------------------------------------------------------------

_VALUE_KW = '        value=published,\n        confidence=confidence,\n        unit="sector_names",'
_UNIT_KW = '        unit="sector_names",'
_SOURCE_FAMILY_KW = (
    '        unit="sector_names",\n'
    "        direction=None,\n"
    "        source_family=EvidenceSourceFamily.MANUAL_ASSESSMENT,"
)
_COUNTRY_KW = '        model_name="sector_rotation_prior",\n        country="us",'
_ASSERT_MAP = "assert set(get_args(RegimeState)) == set(REGIME_STATES), ("

# --------------------------------------------------------------------------
# N1-N3: the config.
#
# ⚠️ THE ACCESSOR AND VALIDATOR BODIES ARE SHARED WITH FIVE SIBLING BLOCKS.
#    `return float(self.reliability_cap.value)`,
#    `return self.reliability_cap.is_trustworthy` and
#    `if not 0.0 <= self.reliability_value <= 1.0:` each occur SIX times in
#    `config.py` (Intervention / EMVulnerability / OilBalance / Gold /
#    MetalsComplex / EquityMacro). A mutation that hardcodes a constant is a WEAK
#    test (D-031), and an anchor that matches two sites is not a mutation, it is
#    an AMBIGUITY. Each is WIDENED with a distinguishing neighbour that exists
#    only in EquityMacroSettings. WIDEN, never delete (D-109/O-145).
# --------------------------------------------------------------------------

_N1_CAP_PROP = (
    "        content of the model's own caveat.\n"
    '        """\n'
    "        return float(self.reliability_cap.value)"
)
# WIDENED with the FOLLOWING property's opener: the docstring tail is shared with
# three siblings, but `def no_prior_label` is unique to this block.
_N1_CALIBRATED_READ = (
    "        return self.reliability_cap.is_trustworthy\n"
    "\n"
    "    @property\n"
    "    def no_prior_label(self) -> str:"
)
_N2_LABEL_PROP = "        return str(self.no_prior_label_leaf.value)"
# ⚠️ WIDENED AT D-124: the cap-range check is now a LOOP over the three caps, so
# the old bare `f"equity_macro.reliability_cap is ..."` line no longer exists.
# The anchor is the loop's f-string, which names `{name}`/`{cap}` and so is
# unique to this block.
_N3_CAP_VALIDATOR = '                f"equity_macro.{name} is {cap}. A confidence must lie inside "'
_N3_LABEL_VALIDATOR = (
    '                f"equity_macro.no_prior_label is {self.no_prior_label!r}. It is "'
)

# --- D-124: the duration and factor-tilt leaves ---------------------------
#
# The three new accessors and the three new validator guards are each pinned by a
# mutation. The accessor anchors carry the FOLLOWING property's opener (the
# ``_leaf``-suffix block is unique to EquityMacroSettings), and each validator
# anchor is its own ``f"equity_macro.<leaf> ..."`` message, which is unique.
_N4_GROWTH_PROP = (
    "        return float(self.duration_growth_proxy_years_leaf.value)\n"
    "\n"
    "    @property\n"
    "    def duration_value_proxy_years(self) -> float:"
)
_N4_VALUE_PROP = (
    "        return float(self.duration_value_proxy_years_leaf.value)\n"
    "\n"
    "    @property\n"
    "    def duration_reliability_value(self) -> float:"
)
_N4_DURATION_CAP_PROP = (
    "        return float(self.duration_reliability_cap.value)\n"
    "\n"
    "    @property\n"
    "    def duration_proxy_is_calibrated(self) -> bool:"
)
_N4_PROXY_CALIBRATED_AND = (
    "        return (\n"
    "            self.duration_growth_proxy_years_leaf.is_trustworthy\n"
    "            and self.duration_value_proxy_years_leaf.is_trustworthy\n"
    "        )"
)
_N4_FACTOR_CAP_PROP = (
    "        return float(self.factor_tilt_reliability_cap.value)\n"
    "\n"
    "    @property\n"
    "    def factor_tilt_reliability_cap_is_calibrated(self) -> bool:"
)
_N5_GROWTH_VALIDATOR = '                f"equity_macro.duration_growth_proxy_years is "'
_N5_VALUE_VALIDATOR = '                f"equity_macro.duration_value_proxy_years is "'
_N5_BAND_VALIDATOR = '                f"equity_macro.duration_rate_change band is "'


_MUTATIONS: list[tuple[str, Path, str, str]] = [
    # -- canary (CONTROL) -------------------------------------------------
    # NOT a revert of a project decision: a mutation CERTAIN to be caught, so the
    # sweep can REFUSE TO CERTIFY when it survives. The anchor is the module's
    # FIRST STATEMENT — the future import — so it does not churn (O-119/O-126).
    (
        "CANARY1 the module literal is replaced with a syntax error (CONTROL)",
        SRC,
        "from __future__ import annotations",
        "__CANARY__ = <<<SYNTAX ERROR>>>",
    ),
    # --- E1: the map and the coverage constants --------------------------
    (
        "E1a a specification row is removed (three states fall back)",
        SRC,
        _EARLY_ROW,
        "",
    ),
    (
        "E1b an extension row is removed (a reachable state falls back)",
        SRC,
        _SLOWDOWN_ROW,
        "",
    ),
    (
        "E1c the whole map is emptied (every regime falls back)",
        SRC,
        _MAP_DECL,
        "SECTOR_ROTATION_PRIOR: dict[str, tuple[str, ...]] = {}\n_UNUSED_MAP = {",
    ),
    (
        "E1d the specification-regime tuple is shortened",
        SRC,
        _SPEC_TUPLE,
        'SPECIFICATION_REGIMES: tuple[str, ...] = (\n    "early_expansion",\n    "mid_expansion",',
    ),
    (
        "E1e the extension-regime tuple is widened to include a specification row",
        SRC,
        _EXT_TUPLE,
        'SECTOR_PRIOR_EXTENSION_REGIMES: tuple[str, ...] = (\n    "slowdown",\n    "early_expansion",',
    ),
    # --- E2: the input field and the vocabulary refusal ------------------
    (
        "E2a the field is widened to accept any string (Section 6.9's bare-str defect)",
        SRC,
        _INPUT_REGIME_FIELD,
        "    regime_state: str = Field(",
    ),
    # --- E3: the lookup, the fallback and the container ------------------
    (
        "E3a the lookup always misses (every regime falls back)",
        SRC,
        _GET_CALL,
        "    sectors = None",
    ),
    (
        "E3b the has_prior flag is inverted",
        SRC,
        _HAS_PRIOR,
        "    has_prior = sectors is None",
    ),
    (
        "E3c the fallback label is a constant instead of the config leaf",
        SRC,
        _PUBLISHED,
        "    published: list[str] = list(sectors) if sectors is not None else ['UNKNOWN']",
    ),
    (
        "E3d the published value is the map's own tuple, not a fresh list",
        SRC,
        _PUBLISHED,
        "    published: list[str] = "
        "list(sectors) if sectors is not None else [equity_macro.no_prior_label]\n"
        "    published = sectors  # type: ignore[assignment]",
    ),
    # --- E4: the confidence ----------------------------------------------
    (
        "E4a the confidence is summed instead of multiplied (the cap stops bounding)",
        SRC,
        _CONF_PRODUCT,
        "    confidence = computed + equity_macro.reliability_value",
    ),
    (
        "E4b the computed half is dropped (a bare cap literal)",
        SRC,
        _CONF_PRODUCT,
        "    confidence = equity_macro.reliability_value",
    ),
    (
        "E4c the data-quality flag is inverted (a missing prior looks better)",
        SRC,
        _FLAGS_PRESENT,
        "            data_quality_flags_present=has_prior,\n"
        "            is_heuristic_not_calibrated=not equity_macro.reliability_cap_is_calibrated,",
    ),
    (
        "E4d the heuristic penalty is dropped",
        SRC,
        _HEURISTIC,
        "            is_heuristic_not_calibrated=False,",
    ),
    (
        "E4e the independence credit is removed",
        SRC,
        _SOURCE_INDEP,
        "            source_independence_count=0,",
    ),
    (
        "E4f the computed confidence never runs",
        SRC,
        _COMPUTED_CALL,
        "    published: list[str] = list(sectors) if sectors is not None else "
        "[equity_macro.no_prior_label]\n"
        "\n"
        "    # --- confidence: two producers, both load-bearing ------------------------\n"
        "    computed = 0.5\n"
        "    _unused = compute_confidence(\n        ConfidenceInputs(",
    ),
    # --- E5: the warnings and the caveat ---------------------------------
    (
        "E5a the prior-not-rule caveat warning is removed",
        SRC,
        _CAVEAT_WARNING,
        "    warnings: list[str] = [\n        _dropped_caveat()",
    ),
    (
        "E5b the fallback disclosure warning is removed",
        SRC,
        _FALLBACK_WARNING,
        '            f"Regime {regime!r} has no prior "',
    ),
    (
        "E5c the extension-origin assumption is removed",
        SRC,
        _EXT_ASSUMPTION,
        '            f"The row for {regime!r} is a declaration. "',
    ),
    # --- E6: the published contract and the import assertion -------------
    (
        "E6a the published value is not the looked-up sectors",
        SRC,
        _VALUE_KW,
        "        value=equity_macro.no_prior_label,\n"
        "        confidence=confidence,\n"
        '        unit="sector_names",',
    ),
    (
        "E6b the unit is published as something else",
        SRC,
        _UNIT_KW,
        '        unit="sectors",',
    ),
    (
        "E6c the source family is claimed as market data",
        SRC,
        _SOURCE_FAMILY_KW,
        '        unit="sector_names",\n'
        "        direction=None,\n"
        "        source_family=EvidenceSourceFamily.BLS_EMPLOYMENT_SITUATION,",
    ),
    (
        "E6d the country is a constant other than the US",
        SRC,
        _COUNTRY_KW,
        '        model_name="sector_rotation_prior",\n        country="de",',
    ),
    (
        "E6e the vocabulary-agreement assertion compares against the WRONG set",
        SRC,
        _ASSERT_MAP,
        "assert set(get_args(RegimeState)) == set(SPECIFICATION_REGIMES), (",
    ),
    # --- N1-N3: the config -----------------------------------------------
    (
        "N1a the reliability accessor returns the no-prior label leaf",
        CONFIG,
        _N1_CAP_PROP,
        "        return float(self.no_prior_label_leaf.value)",
    ),
    (
        "N1b the calibration helper reports calibrated unconditionally",
        CONFIG,
        _N1_CALIBRATED_READ,
        "        return True\n\n    @property\n    def no_prior_label(self) -> str:",
    ),
    (
        "N2a the no-prior accessor returns the reliability cap",
        CONFIG,
        _N2_LABEL_PROP,
        "        return str(self.reliability_cap.value)",
    ),
    (
        "N3a the cap-range validator removed",
        CONFIG,
        _N3_CAP_VALIDATOR,
        '                f"equity_macro.{name} is ok "\n'
        "            )\n"
        "        _dead_validator_guard = True",
    ),
    (
        "N3b the empty-label validator removed",
        CONFIG,
        _N3_LABEL_VALIDATOR,
        '                f"equity_macro.no_prior_label is {self.no_prior_label!r}. It is "\n'
        "            )\n"
        "        _dead_validator_guard = True",
    ),
    # --- D1-D5: duration_sensitivity (Section 6.9) ------------------------
    (
        "D1a the growth/value leg is swapped (growth gets the value duration)",
        SRC,
        "    proxy_duration = (\n"
        "        equity_macro.duration_growth_proxy_years\n"
        "        if is_growth\n"
        "        else equity_macro.duration_value_proxy_years\n"
        "    )",
        "    proxy_duration = (\n"
        "        equity_macro.duration_value_proxy_years\n"
        "        if is_growth\n"
        "        else equity_macro.duration_growth_proxy_years\n"
        "    )",
    ),
    (
        "D1b the duration proxy is hardcoded instead of read from config",
        SRC,
        "    proxy_duration = (\n"
        "        equity_macro.duration_growth_proxy_years\n"
        "        if is_growth\n"
        "        else equity_macro.duration_value_proxy_years\n"
        "    )",
        "    proxy_duration = 15.0 if is_growth else 5.0",
    ),
    (
        "D2a the price-move sign is flipped (a rate rise helps)",
        SRC,
        "    est_pct_move = -proxy_duration * (inputs.rate_change_bp / 10000.0)",
        "    est_pct_move = proxy_duration * (inputs.rate_change_bp / 10000.0)",
    ),
    (
        "D2b the percentage scaling is dropped (a factor of 100 lost)",
        SRC,
        "    published = round(est_pct_move * 100.0, 2)",
        "    published = round(est_pct_move, 2)",
    ),
    (
        "D3a the rate-move band check is dropped (any move passes)",
        SRC,
        "        if not low <= value <= high:",
        "        if False:",
    ),
    (
        "D3b the band bounds are swapped (the gate refuses everything)",
        SRC,
        "        low = band.duration_rate_change_min_bp\n"
        "        high = band.duration_rate_change_max_bp",
        "        low = band.duration_rate_change_max_bp\n"
        "        high = band.duration_rate_change_min_bp",
    ),
    (
        "D4a the duration confidence is summed instead of multiplied",
        SRC,
        "    confidence = computed * equity_macro.duration_reliability_value",
        "    confidence = computed + equity_macro.duration_reliability_value",
    ),
    (
        "D4b the duration computed half is dropped (a bare cap)",
        SRC,
        "    confidence = computed * equity_macro.duration_reliability_value",
        "    confidence = equity_macro.duration_reliability_value",
    ),
    (
        "D4c the duration heuristic penalty is dropped",
        SRC,
        "            is_heuristic_not_calibrated=not equity_macro.duration_proxy_is_calibrated,",
        "            is_heuristic_not_calibrated=False,",
    ),
    (
        "D5a the illustrative-proxy warning is removed",
        SRC,
        '            "Proxy duration is ILLUSTRATIVE, not calibrated — refine with a real "',
        '            "Proxy duration is a forecast — "',
    ),
    (
        "D5b the style is ignored in the interpretation (always 'growth')",
        SRC,
        '        unit="percent_price_change",',
        '        unit="percent_price_change",\n        direction=None,',
    ),
    # --- F1-F4: factor_tilt_prior (Section 20.20-E) -----------------------
    (
        "F1a a factor row is removed (a regime falls back)",
        SRC,
        '    "recession": {"value": -0.5, "momentum": -1.0, "quality": 1.0, "low_vol": 1.0, "size": -1.0},\n',
        "",
    ),
    (
        "F1b the whole factor map is emptied (every regime falls back)",
        SRC,
        "FACTOR_REGIME_MAP: dict[str, dict[str, float]] = {",
        "FACTOR_REGIME_MAP: dict[str, dict[str, float]] = {}\n_UNUSED_FACTOR_MAP = {",
    ),
    (
        "F1c the five factor names are truncated to four",
        SRC,
        'FACTOR_NAMES: tuple[str, ...] = ("value", "momentum", "quality", "low_vol", "size")',
        'FACTOR_NAMES: tuple[str, ...] = ("value", "momentum", "quality", "low_vol")',
    ),
    (
        "F2a the momentum tilt's sign is flipped in the recession row",
        SRC,
        '    "recession": {"value": -0.5, "momentum": -1.0, "quality": 1.0, "low_vol": 1.0, "size": -1.0},',
        '    "recession": {"value": -0.5, "momentum": 1.0, "quality": 1.0, "low_vol": 1.0, "size": -1.0},',
    ),
    (
        "F3a the factor-tilt confidence is summed instead of multiplied",
        SRC,
        "    confidence = computed * equity_macro.factor_tilt_reliability_value",
        "    confidence = computed + equity_macro.factor_tilt_reliability_value",
    ),
    (
        "F3b the factor computed half is dropped (a bare cap)",
        SRC,
        "    confidence = computed * equity_macro.factor_tilt_reliability_value",
        "    confidence = equity_macro.factor_tilt_reliability_value",
    ),
    (
        "F3c the factor data-quality flag is inverted",
        SRC,
        "            data_quality_flags_present=not has_prior,\n"
        "            is_heuristic_not_calibrated=not equity_macro.factor_tilt_reliability_cap_is_calibrated,",
        "            data_quality_flags_present=has_prior,\n"
        "            is_heuristic_not_calibrated=not equity_macro.factor_tilt_reliability_cap_is_calibrated,",
    ),
    (
        "F4a the momentum-crash warning is removed",
        SRC,
        '        "Momentum tilts are LEAST reliable precisely at regime turns (momentum "\n'
        '        "crashes) — the moment this prior matters most is when it is weakest "\n'
        '        "(Section 20.20-E).",',
        '        "Momentum tilts are a reliable guide at regime turns.",',
    ),
    (
        "F4b the fallback publishes STALE tilts instead of an empty dict",
        SRC,
        "    published: dict[str, float] = dict(tilts) if tilts is not None else {}",
        "    published: dict[str, float] = dict(tilts) if tilts is not None "
        "else FACTOR_REGIME_MAP['mid_expansion']",
    ),
    # --- N4-N5: the duration / factor config accessors and validators -----
    (
        "N4a the growth-proxy accessor returns the value-proxy leaf",
        CONFIG,
        _N4_GROWTH_PROP,
        "        return float(self.duration_value_proxy_years_leaf.value)\n"
        "\n"
        "    @property\n"
        "    def duration_value_proxy_years(self) -> float:",
    ),
    (
        "N4b the value-proxy accessor returns the growth-proxy leaf",
        CONFIG,
        _N4_VALUE_PROP,
        "        return float(self.duration_growth_proxy_years_leaf.value)\n"
        "\n"
        "    @property\n"
        "    def duration_reliability_value(self) -> float:",
    ),
    (
        "N4c the duration-cap accessor returns the sector reliability cap",
        CONFIG,
        _N4_DURATION_CAP_PROP,
        "        return float(self.reliability_cap.value)\n"
        "\n"
        "    @property\n"
        "    def duration_proxy_is_calibrated(self) -> bool:",
    ),
    (
        "N4d the duration-proxy calibration flag is ORed, not ANDed",
        CONFIG,
        _N4_PROXY_CALIBRATED_AND,
        "        return (\n"
        "            self.duration_growth_proxy_years_leaf.is_trustworthy\n"
        "            or self.duration_value_proxy_years_leaf.is_trustworthy\n"
        "        )",
    ),
    (
        "N4e the factor-tilt cap accessor returns the sector reliability cap",
        CONFIG,
        _N4_FACTOR_CAP_PROP,
        "        return float(self.reliability_cap.value)\n"
        "\n"
        "    @property\n"
        "    def factor_tilt_reliability_cap_is_calibrated(self) -> bool:",
    ),
    (
        "N5a the non-positive growth-proxy guard is removed",
        CONFIG,
        _N5_GROWTH_VALIDATOR,
        '                f"equity_macro.duration_growth_proxy_years is ok "\n'
        "            )\n"
        "        _dead_guard = True",
    ),
    (
        "N5b the non-positive value-proxy guard is removed",
        CONFIG,
        _N5_VALUE_VALIDATOR,
        '                f"equity_macro.duration_value_proxy_years is ok "\n'
        "            )\n"
        "        _dead_guard = True",
    ),
    (
        "N5c the inverted rate-band guard is removed",
        CONFIG,
        _N5_BAND_VALIDATOR,
        '                f"equity_macro.duration_rate_change band is ok "\n'
        "            )\n"
        "        _dead_guard = True",
    ),
]


def run_tests() -> bool:
    proc = _run_pytest_inproc(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_equity_macro.py",
            "tests/test_infrastructure.py",
            "-q",
            "--no-header",
            # `-x` is D-057's rule, not a preference: a kill is a kill, the first
            # failing test is sufficient evidence, and an interrupted long run on
            # win32 leaves every mutant applied so far on disk (D-082).
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
    mutates (O-138).

    Exit code is **0 for a clean verdict and 4 for problems** — the same 4 the
    sweep itself returns on a refusal.
    """
    originals = {p: p.read_text(encoding="utf-8") for p in (SRC, CONFIG) if p.exists()}
    problems = check_targets(originals, _MUTATIONS)
    print(f"check_targets: {len(_MUTATIONS)} mutations, {len(problems)} problem(s)", flush=True)
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
    # O-138: the check-only mode must be answered BEFORE the lifecycle writes.
    if check_only_requested():
        return _check_targets_only()

    # The whole interrupt defence in one call (O-103): heal any sidecar a killed
    # previous run left behind, write the pristine text to a sidecar BEFORE the
    # first mutation, and consume it on the way out.
    with sweep_lifecycle([SRC, CONFIG]) as originals:
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
        f"MUTATION SWEEP — equity_macro (sector_rotation_prior + "
        f"EquityMacroSettings): {killed}/{total} killed",
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
