"""Phase 5+ extension: NautilusTrader adapter for event-driven execution.

Interface contract (AGENTS.md Section 12): the thesis layer **never**
auto-executes (Section 9.3), so a clean separation boundary already exists.
This adapter reads ``MacroThesis.trade_idea`` as an external consumer — exactly
as a human trader would — rather than being wired into the pipeline.

That distinction is the point. If this module ever needs a hook *inside*
``build_us_macro_thesis()``, then the separation has been violated and the
reasoning layer has quietly become an execution system, which Section 1.1
explicitly forbids.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - Type-only import, no runtime dependency.
    from macro_engine.thesis_layer.schemas import MacroThesis

__all__ = ["NOT_PERMITTED_AUTOMATICALLY", "thesis_to_order_intent"]


# Rather than a silent no-op, the refusal is named so a caller that reaches for
# automatic execution finds an explicit statement of why it is unavailable.
NOT_PERMITTED_AUTOMATICALLY = (
    "Automatic order submission is prohibited by design (AGENTS.md Section 1.1 / 9.3). "
    "This adapter may only prepare an order intent for human review."
)


def thesis_to_order_intent(thesis: MacroThesis) -> dict[str, Any]:
    """Translate a thesis's ``trade_idea`` into a reviewable order intent.

    Returns a plain dict describing *what would be traded*, for a human to
    approve. It never submits anything, and it will return an explicit
    no-intent marker for a no-trade thesis rather than raising — a no-trade
    thesis is a valid outcome, not an error condition.
    """
    raise NotImplementedError("Phase 5+ — requires the `nautilus_trader` dependency (Section 4).")
