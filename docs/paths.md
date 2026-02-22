Canonical paths (v1)
=====================

## Request State Paths

- REQUESTS_ROOT: `state/requests/<request_id>/`
- DELIVERABLES_ROOT: the request directory itself (all deliverables are relative to `state/requests/<request_id>/`)
- VERIFIER_ROOT: `state/requests/<request_id>/verifier/`
- REPAIR_ROOT: `state/requests/<request_id>/repair/`

These roots are shared by orchestrator, verifier, repair, and the E2E harness. Deliverable checks, repair patches, and staged proposals must all resolve paths relative to the request directory (DELIVERABLES_ROOT).

## Core Module Paths

- CLI entrypoint: `scripts/bin/dcs`
- Replay runner: `scripts/run_replay.py`
- Contract checker: `workers/contract_checker.py`
- Path constants: `nlc/paths.py`
- External snapshot: `nlc/external_snapshot.py`
- Snapshot resolver: `nlc/snapshot_resolver.py`

