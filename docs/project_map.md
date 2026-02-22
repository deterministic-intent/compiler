# LLM-Hub Project Map (Repo + Directories + Step Proofs)

This is a living map of the **canonical directories, entrypoints, and proof scripts** used by the LLM-Hub “finished product” pipeline. Update this as new steps land.

## Canonical Roots (Do Not Drift)

- **Request root (deliverables root)**: `state/requests/<request_id>/`
- **Verifier outputs (single-writer: verifier runner only)**: `state/requests/<request_id>/verifier/`
- **Repair trace (single-writer: repair runner only)**: `state/requests/<request_id>/repair/`
- **Replay outputs (single-writer: replay runner only)**: `state/requests/<request_id>/replay/<replay_id>/`
- **DB snapshot root (immutable snapshots)**: `nlc/db/snapshots/<snapshot_id>/`
- **Snapshot manifests**: `nlc/db/snapshots/<snapshot_id>/manifest/`

## “Stateful” vs “Immutable”

- **Stateful outputs**: `state/requests/…` (OK to write; gate/runner ownership rules apply)
- **Immutable knowledge**: `nlc/db/snapshots/…` (must not be mutated during request runs; only snapshot build step writes here)

## Repo Top-Level Inventory (Use Case Oriented)

### Policy (Step 1 spine)
- **`policy/`**
  - `policy/policy.py`: policy loader entrypoint (versioned policy selection)
  - `policy/policy_v1.json`: minimal schema-valid policy file

### Knowledge + Reproducibility (Steps 2, 7)
- **`nlc/`**
  - `nlc/kb/`: snapshot builder / KB tooling (if present)
  - `nlc/db/`: DB snapshot root + snapshot selection
  - `nlc/db/snapshots/<id>/manifest/`: snapshot manifests (`intents.json`, `templates.json`, `modules.json`, `practices.json`, `toolchain_pins.json`)
  - `nlc/reproducibility.py`: hashing + manifest bundle hash helper(s)
  - `nlc/paths.py`: canonical path constants
  - `nlc/external_snapshot.py`: external snapshot writer
  - `nlc/snapshot_resolver.py`: snapshot resolution & precedence

### Compiler / Clarification (Step 3)
- **`nlc/prompt_compiler.py`**: prompt → deterministic `REQ.json` or `CLARIFY.json`
- **`nlc/clarification.py`**: `CLARIFY.json` schema + helpers
- **`nlc/llm_parse_adapter.py`**: untrusted parse adapter stub (LLM optional)

### Orchestration / Gate Flow (Pipeline control plane)
- **`orchestrator/`**
  - `orchestrator/orchestrator.py`: gate sequencing + state management + runner invocation (read-only consumption of verifier/repair outputs)
  - `orchestrator/modules/`: generator runtime modules (manifested as `modules.json`)
  - `orchestrator/intent_emitters/`: intent definitions (or registry emitters), used for manifests/selection

### Workers (Runners = single-writers for their domains)
- **`workers/`**
  - `workers/run_planner.py`: emits planning artifacts (e.g. `SPEC.md`, `TASKS.json`, `PLAN.md`, `NEEDS.json`)
  - `workers/run_generator.py`: generator runner (if present)
  - `workers/run_verifier.py`: sole writer of `verifier.result.json` + `failures.json`
  - `workers/failure_canonicalizer.py`: canonical failure schema + stable ID normalization
  - `workers/run_repair.py`: repair loop runner (sole writer under `repair/`)

### Contracts (Step 6)
- **`contracts/`**
  - `contracts/contract_rules.json`: machine-checkable contract rules
- **`workers/contract_checker.py`**: contract enforcement engine (invoked by verifier)

### Replay (Step 7)
- **`scripts/run_replay.py`**: replay runner (pins verification + deterministic reproduction without LLM)

### Scripts (Proof harnesses + audits)
- **`scripts/`**
  - **CLI Entrypoint**
    - `scripts/bin/dcs`: DCS CLI entrypoint (all pipeline operations)
  - **Replay**
    - `scripts/run_replay.py`: replay runner (deterministic reproduction)
  - **Audit**
    - `scripts/audit/run_audit.py`: required "audit battery" (compile, import smoke, help smoke, E2E smoke, Gate0 proof, Step7 proof)
    - `scripts/audit/README.md`: audit documentation
  - **E2E**
    - `scripts/e2e/run_e2e0.py`: E2E-0 suite harness (A/B/C/D)
    - `scripts/e2e/fixtures/`: fixtures + patch diffs
  - **Step verification**
    - `scripts/build_snapshot_manifests.py`: build snapshot manifests for a given snapshot id
    - `scripts/test_manifest_determinism.py`: byte-identical manifest determinism proof
    - `scripts/verify_step2.py`: Step 2 proof
    - `scripts/verify_step4.py`: Step 4 proof
    - `scripts/verify_step5a.py`: Step 5a proof (stub repair)
    - `scripts/verify_step6.py`: Step 6 proof (contract violations → canonical failures; deterministic)
    - `scripts/verify_step7.py`: Step 7 proof (replay pins + byte-identical)
    - `scripts/verify_root_policy.py`: Root policy enforcement proof
    - `scripts/verify_docs_alignment.py`: Documentation alignment proof

### DB / Ingestion (Step 8 target)
- **`db/`**: DB models/api/validation (ingestion quality enforcement lives here)
- **`scraper/`** (if present): crawling/scraping/normalization pipeline
- **`sources/registry.json`** (if present): source registry for ingestion

### Docs
- **`docs/paths.md`**: canonical path conventions (if present)
- **`docs/project_map.md`**: this file

## “Step → Files → Proof” Index

### Step 1 — Policy spine + wiring
- **Core**
  - `policy/policy.py`
  - `policy/policy_v1.json`
- **Wiring touchpoints (read-only)**
  - `orchestrator/orchestrator.py`
  - `db/validate.py` (if used)
  - `nlc/reproducibility.py` (records policy_version)

### Step 2 — Snapshot manifests + manifest bundle hash
- **Core**
  - `nlc/db/manifest_builder.py` (if used)
  - `nlc/db/snapshots/<id>/manifest/*.json`
  - `nlc/reproducibility.py` (`get_manifest_hashes`)
- **Proof**
  - `scripts/build_snapshot_manifests.py`
  - `scripts/test_manifest_determinism.py`
  - `scripts/verify_step2.py`

### Step 3 — Deterministic selection + clarification artifact (LLM optional)
- **Core**
  - `nlc/prompt_compiler.py`
  - `nlc/clarification.py`
  - `nlc/llm_parse_adapter.py`
- **Behavioral invariant**
  - If `CLARIFY.json` is emitted, pipeline halts; downstream gates marked `SKIPPED_CLARIFY`.

### Step 4 — Verifier structured output + canonical failures
- **Core**
  - `workers/run_verifier.py`
  - `workers/failure_canonicalizer.py`
- **Artifacts**
  - `state/requests/<id>/verifier/verifier.result.json`
  - `state/requests/<id>/verifier/failures.json`
- **Proof**
  - `scripts/verify_step4.py`

### Step 5 — Repair loop + trace (stub mode + deterministic gate)
- **Core**
  - `workers/run_repair.py`
- **Artifacts**
  - `state/requests/<id>/repair/status.json`
  - `state/requests/<id>/repair/iter_<n>/...`
- **Proof**
  - `scripts/verify_step5a.py`
  - `scripts/e2e/run_e2e0.py` (B/C exercise accept/reject)

### Step 6 — Contract enforcement (machine-checkable)
- **Core**
  - `contracts/contract_rules.json`
  - `workers/contract_checker.py`
  - `workers/run_verifier.py` (invokes contract checker; single writer)
- **Proof**
  - `scripts/verify_step6.py`

### Step 7 — Replay mode (no LLM, pin verification, byte-identical)
- **Core**
  - `scripts/run_replay.py`
- **Artifacts**
  - `state/requests/<id>/replay/<replay_id>/...`
- **Proof**
  - `scripts/verify_step7.py`
  - `scripts/audit/run_audit.py` (includes Step 7 proof)

### Step 8 — Ingestion quality enforcement (future)
- **Core (expected)**
  - `db/validate.py` (provenance required; deterministic conflict rules)
  - snapshot build fails hard if validation fails

## "Common Tasks → Where to Look"

- **Run DCS CLI**: `scripts/bin/dcs <command>`
- **Run full audit battery**: `scripts/audit/run_audit.py`
- **Run E2E-0 suite**: `scripts/e2e/run_e2e0.py`
- **Build snapshot manifests**: `scripts/build_snapshot_manifests.py`
- **Verify manifest determinism**: `scripts/test_manifest_determinism.py`
- **Verify contract enforcement**: `scripts/verify_step6.py`
- **Verify replay**: `scripts/verify_step7.py`
- **Verify root policy**: `scripts/verify_root_policy.py`
- **Verify docs alignment**: `scripts/verify_docs_alignment.py`


