"""Phase 5+ extension: rapid rule-based backtesting via ``vectorbt``.

Interface contract (AGENTS.md Section 12): the return-series shapes produced by
``models/`` already match vectorbt's expected ``pd.Series`` / ``pd.DataFrame``
inputs, so this extension consumes model outputs directly. It must not require
an adapter layer — if it does, the models layer's output shapes were wrong.

This is the case-study-informed validation path referenced in Section 3.1:
running a rule set across the historical windows the crisis playbooks
(Section 18) cover is how a rule gets tested against the episodes it was
designed from, rather than only against the regime that happened to be current.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

__all__ = ["run_rule_backtest"]


def run_rule_backtest(
    *,
    returns: pd.Series,
    entry_signals: pd.Series,
    exit_signals: pd.Series,
    fees_bp: float = 1.0,
) -> Any:
    """Backtest a signal pair and return a vectorbt portfolio object.

    Phase 5+ only. Section 4 does not permit installing ``vectorbt`` before its
    phase, and there is no Phase 1-4 substitute: an approximate backtester
    would produce numbers that look like backtest results while being wrong in
    ways that are expensive to detect.
    """
    raise NotImplementedError(
        "Phase 5+ — requires the `vectorbt` dependency (Section 4). See docs/DECISIONS.md."
    )
