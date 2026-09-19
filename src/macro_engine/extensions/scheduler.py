"""Phase 5+ extension: scheduled thesis refresh via APScheduler.

Interface contract (AGENTS.md Section 12):
``build_us_macro_thesis(snapshot)`` is a **pure function of a snapshot**, which
makes it trivially schedulable — this module calls it on a cron-like schedule
with zero changes to the function itself.

The purity requirement is load-bearing, not stylistic. A function that fetched
its own data or read global state could not be re-run against a stored
snapshot to reproduce a past thesis, and Section 5.5's point-in-time audit
trail would be worthless.
"""

from __future__ import annotations

from typing import Any

__all__ = ["build_scheduler"]


def build_scheduler(*, cron: dict[str, str], job_kwargs: dict[str, Any] | None = None) -> Any:
    """Construct a scheduler that refreshes the US thesis on a cron schedule.

    Phase 5+. ``APScheduler`` is not permitted before its phase (Section 4).
    Deriving the schedule's trigger times is not the hard part here — deciding
    what to do when a scheduled run *fails* is, and that belongs with the
    operational tooling rather than being guessed at here.
    """
    raise NotImplementedError("Phase 5+ — requires the `apscheduler` dependency (Section 4).")
