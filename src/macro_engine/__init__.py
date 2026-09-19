"""Global Macro Reasoning Engine.

A reasoning layer, not a trading system (AGENTS.md Section 1.1). It ingests
macro and market data, runs quantitative macro models, and synthesizes their
outputs into a structured, machine-readable ``MacroThesis``.

Scope discipline (AGENTS.md Section 22.3 / Finding #3): Phases 0-4 are
US-ONLY. ``country="us"`` is not a generalization; it is a label on a system
that currently works for exactly one value of it.
"""

from __future__ import annotations

__version__ = "1.0.0"

__all__ = ["__version__"]
