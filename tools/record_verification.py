"""Record Phase 0 verification evidence into config/series_registry.yaml.

Section 21.0 rule 5: "Real-data validation must be recorded, not just
performed." The registry's `verified_on` / `verified_value` fields are that
record. Flipping a status by hand is exactly the shortcut that rule forbids, so
this script exists to make the evidence and the status change together.

It takes the observed values as input (the constants below) rather than
fetching them, so it cannot silently re-derive or "plausibly fill" a value: the
numbers written are the ones a human saw in tools/manual_series_check.py output.

Usage:
    uv run python tools/record_verification.py --check   # report what is missing
    uv run python tools/record_verification.py           # write the records
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

import yaml

from macro_engine.config import get_registry, project_root

REGISTRY = project_root() / "config" / "series_registry.yaml"

# Observed values from the 2026-09-16 live run of tools/manual_series_check.py.
VERIFIED_VALUES: dict[str, float] = {
    "gdp_real": 24269.6130,
    "gdp_nominal": 32486.0660,
    "gdp_potential": 29443.0227,
    "cpi_core": 337.7650,
    "pce_core": 130.6580,
    "ppi": 157.4110,
    "continuing_claims": 1_774_000.0,
    "jolts_openings": 7271.0,
    "jolts_quits": 1.9,
    "fed_funds_rate": 3.6300,
    "sofr": 3.6400,
    "iorb": 3.6500,
    "credit_spread_hy": 2.7600,
    "credit_spread_ig": 0.8000,
    "treasury_curve": 4.9700,
    "tips_yields": 2.6000,
}

# Full curve readings: a single leg does not evidence the whole route, since any
# tenor could be mis-mapped while the 10yr looks correct.
CURVE_VALUES: dict[str, dict[str, float]] = {
    "treasury_curve": {
        "1mo": 3.94,
        "3mo": 4.11,
        "6mo": 4.18,
        "1yr": 4.37,
        "2yr": 4.65,
        "3yr": 4.73,
        "5yr": 4.80,
        "7yr": 4.88,
        "10yr": 4.97,
        "20yr": 5.37,
        "30yr": 5.34,
    },
    "tips_yields": {"5yr": 2.40, "7yr": 2.49, "10yr": 2.60, "20yr": 2.89, "30yr": 3.05},
}


def _needs_evidence(entry: object) -> bool:
    return not getattr(entry, "status", "").startswith("verified")


def main() -> int:
    parser = argparse.ArgumentParser(description="Record series verification evidence.")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    registry = get_registry()
    outstanding = [n for n, e in registry.series.items() if _needs_evidence(e)]

    if args.check or not outstanding:
        if not outstanding:
            print("All registry entries carry verification evidence.")
            return 0
        print(f"{len(outstanding)} entries lack verification evidence:")
        for name in outstanding:
            print(f"  - {name}")
        return 0

    lines = REGISTRY.read_text(encoding="utf-8").splitlines(keepends=True)
    today = datetime.now(tz=UTC).date().isoformat()

    # Walk line by line, tracking which top-level entry we are inside. This is
    # unambiguous: the block ends the moment another 2-space-indented key
    # appears, so a status line can never be attributed to the wrong series.
    current: str | None = None
    out: list[str] = []
    changed: list[str] = []

    for line in lines:
        # A new entry starts at exactly two spaces of indent followed by `name:`.
        if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":"):
            candidate = line.strip()[:-1]
            current = candidate if candidate in registry.series else None

        stripped = line.strip()
        if current is not None and stripped == "status: unverified" and current in VERIFIED_VALUES:
            indent = line[: len(line) - len(line.lstrip())]
            value = VERIFIED_VALUES[current]
            out.append(f"{indent}status: verified\n")
            out.append(f"{indent}verified_on: {today}\n")
            out.append(f"{indent}verified_value: {value}\n")
            if current in CURVE_VALUES:
                legs = CURVE_VALUES[current]
                leg_text = ", ".join(f"{k}: {v}" for k, v in legs.items())
                out.append(f"{indent}verified_curve: {{{leg_text}}}\n")
            changed.append(current)
            continue

        out.append(line)

    if changed:
        text = "".join(out)
        yaml.safe_load(text)  # fail before writing, not after
        REGISTRY.write_text(text, encoding="utf-8", newline="")
        print(f"Wrote {len(changed)} verification record(s):")
        for name in changed:
            suffix = ""
            if name in CURVE_VALUES:
                suffix = "  " + ", ".join(f"{k}={v}" for k, v in CURVE_VALUES[name].items())
            print(f"  {name:<22} {VERIFIED_VALUES[name]}{suffix}")
    else:
        print("Nothing to write.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
