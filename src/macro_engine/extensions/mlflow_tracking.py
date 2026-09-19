"""Phase 5+ extension: MLflow experiment tracking.

Interface contract (AGENTS.md Section 12): every ``ModelResult`` already carries
``model_name``, ``confidence`` and ``as_of``, so this extension wraps model
calls with ``mlflow.log_metric()`` and requires **no model code changes**. If
it ever needs one, the ModelResult contract has been violated.

Section 4 is explicit that this is deferred "only once multiple model variants
exist" — logging a single variant produces no comparative information, so
adding it earlier would be infrastructure without a question to answer.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - Type-only import, no runtime dependency.
    from macro_engine.models.contracts import ModelResult

__all__ = ["log_model_result", "track_run"]


@contextmanager
def track_run(*, experiment: str, run_name: str) -> Iterator[Any]:
    """Context manager wrapping a computation in an MLflow run."""
    raise NotImplementedError(
        "Phase 5+ — requires the `mlflow` dependency (Section 4). "
        "Explicitly deferred until multiple model variants exist."
    )


def log_model_result(result: ModelResult, *, step: int | None = None) -> None:
    """Log one ``ModelResult`` as metrics plus a JSON artifact.

    Logs ``confidence`` as a metric and the full result as an artifact, because
    the numeric value alone is not reproducible without its interpretation,
    context and warnings.
    """
    raise NotImplementedError("Phase 5+ — see track_run().")


def wrap_model(model_fn: Callable[..., ModelResult]) -> Callable[..., ModelResult]:
    """Decorator logging every call's ``ModelResult``. Phase 5+."""
    raise NotImplementedError("Phase 5+ — see track_run().")
