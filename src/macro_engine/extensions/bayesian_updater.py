"""Phase 5+ extension: full-posterior Bayesian thesis updating (PyMC).

Interface contract (AGENTS.md Section 12): ``MacroThesis.prior_probability``
and ``MacroThesis.posterior_probability`` already exist as nullable fields, so
this extension populates fields that are already there rather than altering the
thesis schema. Adding this must be a schema no-op.

Phase 1-2 use ``scipy``-based point updates (Module 12.3's ``bayesian_update``)
which are sufficient for a single-evidence update. What PyMC adds is the full
posterior over *jointly* uncertain parameters — most importantly r* and u*,
which are unobservable and correlated in ways a point update cannot represent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - Type-only import, no runtime dependency.
    from macro_engine.thesis_layer.schemas import MacroThesis

__all__ = ["update_thesis_posterior"]


def update_thesis_posterior(
    thesis: MacroThesis,
    *,
    evidence: dict[str, Any],
    draws: int = 2000,
) -> MacroThesis:
    """Return a copy of the thesis with ``posterior_probability`` populated.

    Returns a copy rather than mutating, so that the pre-update thesis remains
    available as the prior for the *next* update — mutating in place would
    destroy the chain that makes a Bayesian sequence meaningful.
    """
    raise NotImplementedError(
        "Phase 5+ — requires the `pymc` dependency (Section 4). "
        "Phase 1-2 must use models/probability.bayesian_update() instead."
    )
