"""Emit the REVIEW_REPORT.md data-coverage table from measured evidence.

The table's numbers are read from .review-evidence/manifest.json (files,
lines, reviewed lines) and .review-evidence/callgraph.json (WIRED / ORPHAN
function counts per module), never typed by hand. Regenerate after any change
to the manifest or the call graph.

Run:  uv run python tools/layer_table.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / ".review-evidence"


def layer_of(rel: str) -> str:
    """Bucket a `src/macro_engine/...` path into a report layer."""
    rest = rel[len("src/macro_engine/") :]
    if "/" in rest:
        head = rest.split("/", 1)[0]
        if head + "/" in ("data_layer/", "models/", "portfolio/", "thesis_layer/", "api_layer/"):
            return head + "/"
    return "top level + extensions/"


def main() -> int:
    manifest = json.loads((EVIDENCE / "manifest.json").read_text(encoding="utf-8"))
    graph = json.loads((EVIDENCE / "callgraph.json").read_text(encoding="utf-8"))

    # callgraph.json keys nodes by dotted qualified name and stores a dotted
    # module, not a path. Convert: macro_engine.models.x -> src/macro_engine/models/x.py
    wired: Counter[str] = Counter()
    orphan: Counter[str] = Counter()
    for node in graph["nodes"].values():
        module: str = node["module"]
        if not module.startswith("macro_engine."):
            continue
        rel = "src/" + module.replace(".", "/") + ".py"
        bucket = layer_of(rel)
        if node["classification"] == "WIRED":
            wired[bucket] += 1
        elif node["classification"] == "ORPHAN":
            orphan[bucket] += 1

    rows: list[tuple[str, int, int, int, int, int]] = []
    for entry in manifest["files"]:
        bucket = layer_of(entry["file"])
        rows.append(
            (
                bucket,
                1,
                entry["lines"],
                entry["reviewed_lines"],
                wired.get(bucket, 0),
                orphan.get(bucket, 0),
            )
        )

    agg: dict[str, list[int]] = {}
    for bucket, files, lines, reviewed, w, o in rows:
        cur = agg.setdefault(bucket, [0, 0, 0, 0, 0])
        cur[0] += files
        cur[1] += lines
        cur[2] += reviewed
        cur[3] = w
        cur[4] = o

    order = [
        "data_layer/",
        "models/",
        "portfolio/",
        "thesis_layer/",
        "api_layer/",
        "top level + extensions/",
    ]
    print("| Layer | Files | Lines | Lines reviewed | WIRED | ORPHAN |")
    print("|---|---|---|---|---|---|")
    totals = [0, 0, 0, 0, 0]
    for bucket in order:
        if bucket not in agg:
            continue
        files, lines, reviewed, w, o = agg[bucket]
        label = f"`{bucket}` (reviewed last)" if bucket == "api_layer/" else f"`{bucket}`"
        print(f"| {label} | {files} | {lines:,} | {reviewed:,} | {w} | {o} |")
        for i, v in enumerate((files, lines, reviewed, w, o)):
            totals[i] += v
    print(
        f"| **Total** | **{totals[0]}** | **{totals[1]:,}** | **{totals[2]:,}** "
        f"| **{totals[3]}** | **{totals[4]}** |"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
