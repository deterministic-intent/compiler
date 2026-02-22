# E2E-0 Test Suite

## Overview

E2E-0 is a minimal, binary test suite that proves the **core deterministic pipeline** works end-to-end **without replay**:

- compile → plan → gen → verify
- and (when FAIL) → repair(stub) → verify
- and CLARIFY halts deterministically

No provider calls. No ingestion changes. No contract rules yet.

## Tests

### E2E0-A: PASS path (no repair)
- Fixture: prompt that deterministically selects a single intent and is known to pass verifier
- Verifies: payload.json, REQ.json, verifier.result.json (PASS), empty failures.json, repair not triggered

### E2E0-B: FAIL → repair accepts patch → PASS
- Fixture: prompt/intent that FAILs initially + prepared stub diff that fixes it
- Verifies: initial FAIL recorded, repair ran and accepted patch, post-repair PASS, trace completeness

### E2E0-C: FAIL → repair rejects patch → rollback proven
- Fixture: same failing prompt/intent + "bad" diff that does not improve score
- Verifies: repair rejected patch, rollback restored exact hashes, deterministic stop reason

### E2E0-D: Ambiguous prompt produces CLARIFY and halts
- Fixture: prompt that yields multiple candidate intents or missing required args
- Verifies: CLARIFY.json exists with required fields, planner halted, no generator outputs

## Usage

```bash
python3 scripts/e2e/run_e2e0.py \
  --snapshot <snapshot_id> \
  --policy v1 \
  --request-id TEST
```

## Requirements

- Policy must have `repair.enabled: false` by default (tests B and C will temporarily enable it)
- Snapshot ID must exist in `nlc/db/snapshots/<snapshot_id>/`
- Fixtures must exist in `scripts/e2e/fixtures/e2e0.json`

## Fixtures

Fixtures are defined in `scripts/e2e/fixtures/e2e0.json`:
- `pass_prompt`: Simple prompt that should pass
- `fail_prompt_accept_patch`: Prompt that fails + path to fixing diff
- `fail_prompt_reject_patch`: Prompt that fails + path to non-improving diff
- `clarify_prompt`: Ambiguous prompt that should trigger clarification

Patch diffs are stored in:
- `scripts/e2e/fixtures/accept_patch.diff`
- `scripts/e2e/fixtures/reject_patch.diff`

## Stop Point

Move to Step 6 only when:
- E2E0-A, B, C, D are green on a clean run
- They remain green across two consecutive runs (to catch nondeterministic leakage)

