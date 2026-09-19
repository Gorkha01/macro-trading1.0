"""The evidence source-family vocabulary (Module 13, Section 15.19-D).

Split into its own module so that ``contracts.ModelResult`` can carry a typed
``source_family`` field without a circular import: ``evidence.py`` needs
``contracts.py`` for ``ModelResult`` and ``compute_confidence``, so the enum
cannot live there.

A family is a **shared upstream production process** — two series share one when
a single failure (survey redesign, rebenchmarking, outage, methodology
revision) would corrupt both at once. That is the test for adding a member, and
it is why ``BLS_CPI`` and ``BLS_PPI`` are separate while headline and core CPI
are one: the redundancy that defeats convergence logic is production-process
redundancy, not topic overlap.
"""

from __future__ import annotations

from enum import Enum

__all__ = ["EvidenceSourceFamily"]


class EvidenceSourceFamily(str, Enum):
    """Independent families of macro evidence (Module 13).

    A family is a **shared upstream production process**, not a topic and not a
    publisher. Two series belong to the same family when a single failure — a
    survey redesign, a rebenchmarking, a collection outage, a methodology
    revision — would corrupt both at once. That is the test to apply when adding
    a member.

    The grouping below is by domain for readability, but the *identity* of a
    family is its independence structure, which is why ``BLS_CPI`` and
    ``BLS_PPI`` are separate (separate surveys with separate samples) while
    headline and core CPI are the same member.
    """

    # --- Inflation ---
    BLS_CPI = "bls_cpi"
    BEA_PCE = "bea_pce"
    BLS_PPI = "bls_ppi"
    CLEVELAND_FED = "cleveland_fed"
    DALLAS_FED = "dallas_fed"
    MARKET_BREAKEVEN = "market_breakeven"
    SURVEY_EXPECTATIONS = "survey_expectations"
    PRIVATE_RENT = "private_rent"

    # --- Labor ---
    BLS_EMPLOYMENT_SITUATION = "bls_employment_situation"
    BLS_JOLTS = "bls_jolts"
    DOL_CLAIMS = "dol_claims"

    # --- Activity ---
    BEA_NIPA = "bea_nipa"
    CENSUS_RETAIL = "census_retail"
    CENSUS_DURABLE = "census_durable"
    CBO_POTENTIAL = "cbo_potential"
    CONFERENCE_BOARD = "conference_board"
    FED_SLOOS = "fed_sloos"

    # --- Rates & markets ---
    TREASURY_OFFICIAL = "treasury_official"
    FED_H41 = "fed_h41"
    FED_NY_ACM = "fed_ny_acm"
    TREASURY_AUCTIONS = "treasury_auctions"
    MARKET_CREDIT_SPREADS = "market_credit_spreads"
    MARKET_EQUITY_VOL = "market_equity_vol"
    MARKET_FX = "market_fx"
    MARKET_COMMODITY = "market_commodity"

    # --- Surveys & institutional ---
    UMICH = "umich"
    IMF = "imf"
    WORLD_BANK = "world_bank"
    NY_FED_HLW = "ny_fed_hlw"
    WGC = "wgc"
    MANUAL_ASSESSMENT = "manual_assessment"
