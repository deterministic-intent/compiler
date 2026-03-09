# Deterministic Compiler Systems (DCS)

Deterministic Compilation of Structured Intent into Reproducible Software Artifacts

**Author:** Justin Wilsey

---

# Abstract

Software artifacts produced by modern build pipelines frequently lack reproducibility. Identical builds executed across machines may yield different outputs due to dependency resolution drift, toolchain differences, environmental variation, or nondeterministic packaging behavior.

Deterministic Compiler Systems (DCS) introduce a constrained compilation architecture that deterministically converts structured intent into reproducible multi-file software artifacts. The system enforces explicit request contracts, canonical intermediate representations, sealed execution environments, snapshot-pinned dependencies, and deterministic packaging rules.

The deterministic compilation pipeline is:

```
Intent → REQ → IR → Generators → Validation → Deterministic Artifact
```

Under this architecture, artifacts become deterministic consequences of explicit input surfaces executed within controlled environments. This document defines the system architecture, request contract model, intermediate representation, artifact class admission rules, replay verification model, deterministic packaging requirements, and verification proof bundles required for independent reproducibility.

---

# 1. Introduction

Software distribution increasingly relies on artifacts whose production pipelines cannot be independently verified. Even when source code and dependency versions appear identical, artifacts frequently differ across machines due to environment differences, toolchain behavior, or nondeterministic packaging processes.

These inconsistencies undermine reproducibility and make independent verification difficult.

Deterministic Compiler Systems address this problem by redefining artifact production as deterministic compilation of structured intent. Instead of executing arbitrary project build scripts, DCS compiles explicit request contracts into artifacts under strictly controlled execution conditions.

The result is a deterministic artifact pipeline in which outputs can be reproduced independently across machines.

---

# 2. Design Principle

DCS enforces a single governing architectural rule:

**Determinism takes precedence over capability.**

System flexibility is intentionally constrained in order to guarantee reproducible artifact generation.

Key system constraints include:

* strict request contracts
* canonical intermediate representations
* snapshot-pinned dependency inputs
* sealed toolchain environments
* deterministic packaging rules
* explicit validation contracts

Features that introduce nondeterministic behavior are intentionally excluded.

---

# 3. Threat Model

DCS is designed to prevent artifact divergence caused by:

* dependency resolution drift
* toolchain version differences
* environment variation
* filesystem ordering differences
* nondeterministic packaging behavior
* timestamp variance

The system assumes trusted cryptographic primitives and trusted container images.

DCS does not attempt to defend against:

* compromised toolchains
* malicious container registries
* compromised cryptographic primitives

These threats fall outside the scope of the system.

---

# 4. Non-Goals

DCS intentionally does not attempt to:

* compile unconstrained natural language directly
* replace general-purpose build systems
* execute nondeterministic generators
* resolve mutable dependencies during artifact generation

These exclusions preserve deterministic guarantees.

---

# 5. Repository Architecture

The reference implementation organizes system responsibilities across the following repository structure:

```
/nlc           — Intent normalization, indexing, prompt compilation, snapshot metadata
/orchestrator  — Pipeline coordination, gate sequencing, request emission
/workers       — Planning, generation, validation, packaging, verification
/dcs_cli       — User-facing command interface
/scripts       — Verification, audit, operational tooling
/policy        — Governance configuration
/contracts     — Contract schemas
/state         — Persistent system state
/suites        — Golden request coverage, deterministic validation
/tests         — Unit and integration tests
/proof         — Proof kit, seal evidence, run scripts
/dcs           — Expected hashes, snapshot manifests
/governance    — Governance artifacts
/schemas       — Schema definitions
```

---

# 6. System Architecture

DCS operates as a deterministic compilation pipeline with explicit gate stages:

```
Structured Intent
        │
        ▼
REQ (Typed Request Contract) — payload.json
        │
        ▼
Gate 0: Init
        │
        ▼
Gate 1: Planning (IR)
        │
        ▼
Gate 2: Delegation
        │
        ▼
Gate 3: Execution (Generators)
        │
        ▼
Gate 4: Review
        │
        ▼
Gate 5: Finalize
        │
        ▼
Gate 6: Complete
        │
        ▼
Deterministic Artifact
```

**Gates:** gate0_init, gate1_planning, gate2_delegation, gate3_execution, gate4_review, gate5_finalize, gate6_complete. Each gate produces deterministic status and result artifacts. Failures terminate execution.

---

# 7. Structured Intent

DCS compiles structured intent rather than unconstrained natural language.

Intent describes artifact requirements through explicit parameters such as:

* artifact class
* artifact configuration
* snapshot identity (knowledge, external, db)

Intent is compiled into a deterministic request contract (payload.json).

---

# 8. REQ — Typed Request Contract

REQ is the canonical deterministic request representation, stored as `payload.json`.

REQ properties:

* schema versioned
* strict validation
* unknown fields rejected
* no implicit defaults
* replay-critical inputs explicit

Required request surfaces include:

```
artifact_class
policy_version
knowledge_snapshot_id
manifest_bundle_hash
```

When external data is required:

```
external_snapshot_id
external_sources_required
```

Additional surfaces depend on artifact class contracts:

```
schema_version
request_id
goal
inputs
constraints
module_refs
```

Example payload (minimal):

```json
{
  "schema_version": "ir_v1",
  "request_id": "LANG_python__python_cli",
  "artifact_class": "python_cli",
  "policy_version": "v1",
  "knowledge_snapshot_id": "20260215T120000Z",
  "manifest_bundle_hash": "<sha256>",
  "module_refs": ["python_cli/project_v1.json"]
}
```

Any modification to REQ invalidates replay equality.

---

# 9. Snapshot Types

DCS distinguishes three snapshot categories with deterministic resolution order:

1. **External** — Raw external inputs (web fetch, file capture). Stored under `snapshots/external/<id>/`.
2. **Knowledge** — Indexed knowledge base. Stored under `nlc/db/snapshots/<id>/`.
3. **DB** — Database snapshot (future).

Resolution order: external → knowledge → db. Snapshot resolution is written to `snapshot_resolution.json` per request.

**External snapshot path resolution** (proof-root precedence):

1. `DCS_EXTERNAL_SNAPSHOT_ROOT` if set
2. else `$DCS_PROOF_STATE_ROOT/snapshots/external` if `DCS_PROOF_STATE_ROOT` is set
3. else legacy `BASE/snapshots/external`

When running inside a container (workspace at `/workspace`), paths starting with `/opt/dcs-public` are forbidden (`CONTAINER_HOST_PATH_FORBIDDEN`). Proof runs must use proof-root paths.

---

# 10. IR — Intermediate Representation

REQ is compiled into an Intermediate Representation (IR).

IR defines the deterministic generation plan executed by the system.

IR properties:

* canonical serialization
* deterministic execution ordering
* explicit execution contracts
* no implicit behavior

Execution rules:

1. Steps execute strictly in declared order.
2. Generators may not introduce undeclared steps.
3. Adapter execution occurs only through declared module bindings.
4. Failures terminate execution.
5. Parallel execution is prohibited unless introduced by a future IR version.

Replay requires byte-identical IR.

---

# 11. Generator Modules

Generator modules translate IR instructions into filesystem outputs.

Generators construct artifact structures deterministically and must not:

* resolve dependencies implicitly
* modify execution ordering
* introduce undeclared filesystem outputs

All behavior derives directly from IR.

---

# 12. Artifact Classes

Artifacts belong to declared artifact classes.

Artifact classes define:

* artifact structure
* validation rules
* packaging contracts
* deterministic invariants

Representative artifact classes include:

```
python_cli
bash_cli
go_cli
java_cli
rust_cli
python_api
python_gui
webview
typescript_cli
```

Artifact classes are admitted only when they have:

* IR binding
* generator implementation
* validator integration
* replay proof
* audit coverage
* golden request coverage

---

# 13. Artifact Validation

Artifact validators enforce artifact class contracts.

Validation checks may include:

* required file presence
* directory structure verification
* dependency lock enforcement
* packaging contract validation

Artifacts failing validation are rejected.

---

# 14. Toolchain Identity

Execution occurs inside a sealed container environment referenced by immutable digest.

Example:

```
ghcr.io/org/dcs-tier3@sha256:<digest>
```

The container environment fixes:

* compiler versions
* runtime versions
* locale
* timezone
* filesystem ordering
* umask

Toolchain identity participates in replay verification.

---

# 15. Snapshot Identity

Snapshot identity is mandatory.

Rules:

* snapshot identity must be explicit
* snapshot identity must appear in replay manifests
* replay must succeed offline
* missing snapshot identity causes deterministic failure

Replay verification validates `snapshot_manifest_hash` (or `manifest_bundle_hash` for knowledge snapshots), binding dependency state to the replay surface.

---

# 16. Deterministic Packaging

Executable artifact classes require deterministic archive output.

Packaging contracts include:

* sorted checksums
* deterministic zip archive
* normalized metadata
* fresh-directory replay success

Normalization requirements include:

* lexicographic file ordering
* normalized UID/GID
* normalized permissions
* normalized archive metadata
* timestamp normalization via `SOURCE_DATE_EPOCH`

---

# 17. Replay Surface

Replay verification requires equality across the replay surface:

```
REQ (payload.json)
IR
knowledge_snapshot_id
external_snapshot_id (when used)
manifest_bundle_hash
policy_version
adapter_versions
toolchain_manifest
freeze_manifest
```

Replay verification fails if any replay surface element differs.

---

# 18. Replay Verification

Replay verification ensures artifact hashes match across independent executions.

Verification requires:

* identical replay surface
* deterministic execution environment
* canonical packaging rules

The generated artifact hash must equal the reference artifact hash.

---

# 19. Replay Proof Bundle

Replay verification artifacts are distributed as `proof_bundle.zip`.

**Actual bundle structure** (per `_create_proof_bundle`):

```
proof_bundle.zip
├── dist/artifact.zip
├── dist/checksums.sha256
├── dist/ENTRYPOINT.md
├── dist/EXECUTE.json
├── verifier/          (verifier outputs)
├── validation/        (validation outputs)
├── repair/            (repair outputs, if any)
├── replay/            (replay outputs)
└── PROOF.md           (included files + sha256 per entry)
```

Verification procedure:

1. Extract proof_bundle.zip.
2. Validate included file hashes per PROOF.md.
3. Execute deterministic generation with identical replay surface.
4. Recompute artifact hash.
5. Confirm hash equality.

Replay succeeds only if all replay surfaces and artifact hashes match.

---

# 20. Proof Hashes

The proof kit produces three component hashes:

* **DIST_SHA256** — First artifact.zip (or site.zip) in state/requests, sorted for determinism.
* **VALIDATION_HASHES_SHA256** — validation_hashes.json from the knowledge snapshot.
* **PROOF_BUNDLE_SHA256** — First proof_bundle.zip in state/requests, sorted for determinism.

These are written to `proof_hashes.json` and `proof_hashes.sha256`. CI compares against `dcs/expected_proof_hashes_v1.json`.

---

# 21. CLI Interface

The v1 deterministic operator surface is:

```
dcs build --intent ...
dcs build --req <REQ.json>
```

Requirements:

* `--intent` compiles structured intent into deterministic REQ and IR
* `--req` executes generation from explicit request input
* both paths produce artifacts
* canonical parity cases must produce identical artifact hashes

---

# 22. Independent Verification Scenario

DCS enables third parties to verify artifacts without trusting the producing environment.

Given a distributed proof bundle and artifact:

1. The verifier loads the proof bundle.
2. Replay surfaces are validated.
3. The verifier executes deterministic generation using the specified toolchain container.
4. Artifact hashes are recomputed.
5. Output hashes are compared with the reference artifact.

If hashes match, the verifier has independently reproduced the artifact.

No trust in the original producer is required.

---

# Conclusion

Deterministic Compiler Systems redefine software artifact production as deterministic compilation of structured intent.

By enforcing strict request contracts, canonical intermediate representations, sealed execution environments, snapshot-pinned dependencies, and deterministic packaging rules, DCS enables byte-identical artifact reproduction across independent machines.

This architecture establishes deterministic compilation as a foundation for verifiable software production and independently reproducible artifact distribution.
