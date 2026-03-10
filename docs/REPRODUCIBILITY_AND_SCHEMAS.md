# Reproducibility and Schema Governance

Short reference for how release evidence and schema authority are chained in DCS v1.

---

## Release tag → freeze manifest → proof hashes

Many reproducible systems publish a mapping of this form. In this repo the relationship is:

```
release tag (e.g. v1.0.0)
        │
        ▼
governance/freeze_manifest_v1.json   ← pins schema and contract hashes
        │
        ▼
dcs/expected_proof_hashes_v1.json    ← golden proof hashes for verification
```

| Layer | File / artifact | Purpose |
|-------|------------------|---------|
| **Release tag** | Git tag on a commit | Marks the sealed release; that commit’s tree is what was verified. |
| **Freeze manifest** | `governance/freeze_manifest_v1.json` | Records SHA256 of REQ schema, IR schema, artifact contract, failure taxonomy. Defines the frozen spec set for v1. |
| **Proof hashes** | `dcs/expected_proof_hashes_v1.json` | Expected values for `DIST_SHA256`, `VALIDATION_HASHES_SHA256`, `PROOF_BUNDLE_SHA256`. Verification passes when `out/proof_hashes.json` matches after running `./scripts/proof/run_clean_proof_v1.sh`. |

**Practice:** When cutting a release, tag the commit where `expected_proof_hashes_v1.json` and `freeze_manifest_v1.json` were last updated together (or where they are known good). External verifiers clone at that tag, run the proof script, and compare to `dcs/expected_proof_hashes_v1.json`. The freeze manifest documents which schema/contract versions were in effect for that proof.

---

## Schema and contract authority chain

Inputs and artifacts flow through a single authority chain. Schemas and contracts are versioned and frozen in the freeze manifest.

```
REQ schema (req_v1)
      │
      ▼
IR schema (ir_v1)
      │
      ▼
artifact contract (language/artifact matrix + class contracts)
      │
      ▼
verifier
```

| Stage | Location | Role |
|-------|----------|------|
| **REQ schema** | `schemas/req_v1.schema.json`, `schemas/req_schema_v1.json` | Validates incoming request (REQ) structure and fields. |
| **IR schema** | `schemas/ir_v1.schema.json` | Validates the compiled internal representation (IR) produced from REQ. |
| **Artifact contract** | `contracts/`, `schemas/artifact_class_registry_v1.json`, `schemas/artifact_classes/*.json` | Defines allowed artifact types, language bindings, and per-class contracts the verifier checks. |
| **Verifier** | `verifier/` | Runs against the built artifact; behavior and expectations are governed by the artifact contract and failure taxonomy. |

The freeze manifest (`governance/freeze_manifest_v1.json`) stores SHA256 hashes of the REQ schema, IR schema, and artifact contract so that a given proof run is tied to a specific, auditable set of specs.
