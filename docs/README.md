# Documentation index

**Read this before adding or removing a file in `docs/`.** Several documents here
are cited **by path from production code, tests, scripts and `config/*.yaml`** as
the provenance of a specific decision or defect. A file that is quoted from
`src/` cannot be deleted without leaving a dangling reference inside the code
that justified it.

## Where to start

| Document | What it is |
|---|---|
| [`../AGENTS.md`](../AGENTS.md) | **The single authority.** Specification, standing rules, phases, and the Tier tables. |
| [`DECISIONS.md`](./DECISIONS.md) | The decision record (`D-001` onward). **Cited from `src/` and `config/`** by number. |
| [`PROGRESS.md`](./PROGRESS.md) | The live tracker. **A *live count surface***: `tests/test_openbb_command_inventory.py` reads it and fails if the stated command census is stale. |
| [`OPEN_ISSUES.md`](./OPEN_ISSUES.md) | Open issues (`O-*`). **Also a live count surface**, same test. |
| [`BUILD_STATE.md`](./BUILD_STATE.md) | Per-function completion records. **Mandated by `AGENTS.md` Step 9** — append here to close a function. |
| [`CHANGELOG.md`](./CHANGELOG.md) | What changed, per release. |
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | Module layout and data flow. |
| [`MODULE_MAPPING.md`](./MODULE_MAPPING.md) | Spec section → module map. |

## Cited from production code — do not delete

These are referenced by path from `src/`, `config/`, `tests/`, `scripts/` or CI.
Removing one leaves a dangling provenance reference. If the content is
superseded, correct the content **in place**.

| Document | Cited from (non-exhaustive) |
|---|---|
| `DECISIONS.md` | 14 files incl. `config/series_registry.yaml`, `src/macro_engine/config.py` |
| `OPEN_ISSUES.md` | 10 files incl. `config/series_registry.yaml`, `config/settings.yaml` |
| `PROGRESS.md` | 6 files incl. `scripts/mutation_command_inventory.py` (which **parses it**) |
| `DEFECTS_2026-09-19.md` | `.github/workflows/quality-gates.yml`, `thesis_layer/builder.py`, `api_layer/orchestration.py`, `tests/test_reachability_gate.py` |
| `PLAN_ppp_source.md` | `data_layer/world_bank_client.py`, `models/fx_carry.py`, `config/series_registry.yaml` |
| `OPENBB_UTILIZATION_AUDIT.md` | `data_layer/snapshot_builder.py`, `thesis_layer/catalysts.py` |
| `CODE_REVIEW_PHASE0-4.md` | `data_layer/openbb_client.py`, `tests/data_layer/test_unit_scale_and_single_call_curve.py` |
| `SERIES_VERIFICATION.md` | `config/series_registry.yaml`, `tools/manual_series_check.py` |
| `INTEGRITY_2026-09-19.md` | `tools/integrity_audit.py` |
| `MODULE_MAPPING.md` | `api_layer/app.py` |

## Audit reports (historical records)

These are **dated measurement records**, not live references. They are kept
because each states *what was measured, when, and with what method* — which is
the evidence behind a `D-*` entry, and cannot be reconstructed after the fact.
Treat them as read-only history: read them to see how a defect was found, but
never look here for the system's current state (that is `PROGRESS.md`).

| Document | Covers |
|---|---|
| `AUDIT_2026-09-19.md` | Ground-up Phase 0–3, function-by-function |
| `INTEGRITY_2026-09-19.md` | Economic-integrity pass, Phase 0–3 |
| `DEFECTS_2026-09-19.md` | **Cited by code** — call-graph + live-run defect report |
| `AUDIT_2026-09-20_PHASE_0_4_FINAL.md` | Phase 0–4 final (`D-074`) |
| `CODE_REVIEW_PHASE0-4.md` | **Cited by code** — read-only review |
| `FINDINGS_value_provenance.md` | The §6 point-in-time provenance contract |
| `OPENBB_ENDPOINT_RECONCILIATION.md` | Availability measurement, not a plan |
| `AUDIT_PHASE04_FINDINGS.md` | Phase 0–4 defect cards + the fix pass |
| `AUDIT_PHASE04_LAYERS_FINDINGS.md` | Per-layer (data/thesis/api/root) 8-class cards |
| `AUDIT_PHASE5_TIER5_BRIEF.md` | Tier-5 23-function work list |
| `AUDIT_PHASE5_TIER5_FINDINGS.md` | Tier-5 audit, 23 cards |
| `AUDIT_PHASE5_TIER5_REAUDIT.md` | Tier-5 re-audit (found 2 defects the first pass rated CLEAN) |

## Rules for this directory

1. **Dated audit reports are immutable.** A new audit is a new dated file that
   supersedes the old one by being newer — never an edit to the old one.
2. **Live state lives in exactly two places** (`PROGRESS.md`, `OPEN_ISSUES.md`),
   because a test reads both. Do not restate the current census anywhere else.
3. **A defect report cited from code is a citation, not a to-do list.** Fixing
   the defect does not license deleting the file; it makes the citation more
   valuable.
4. **Prefer a note in `DECISIONS.md`** over a new top-level document. A new
   `docs/*.md` costs a future reader a file to open; a `D-*` entry does not.
