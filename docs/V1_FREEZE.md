# DCS v1 Freeze

Canonical freeze surface for v1: what is sealed and how it is verified.

## Frozen surface

v1 is defined by:

- **Freeze manifest:** `governance/freeze_manifest_v1.json` — pins REQ schema, IR schema, artifact contract, and failure taxonomy (by SHA256).
- **Proof hashes:** `dcs/expected_proof_hashes_v1.json` — golden values for deterministic proof verification (`DIST_SHA256`, `VALIDATION_HASHES_SHA256`, `PROOF_BUNDLE_SHA256`).
- **Proof seal:** `governance/decisions/v1_proof_seal.md` — records the sealed snapshot and proof state.
- **Schemas and contracts:** Versions and hashes in the freeze manifest; see [Reproducibility and schemas](REPRODUCIBILITY_AND_SCHEMAS.md) for the authority chain (REQ → IR → artifact contract → verifier).

## Verification

- Run `./scripts/proof/run_clean_proof_v1.sh` on a clean tree; verification succeeds when `out/proof_hashes.json` matches `dcs/expected_proof_hashes_v1.json`.
- See [EXTERNAL_VERIFICATION.md](EXTERNAL_VERIFICATION.md) for independent reproduction.

## Freeze rules

- The freeze manifest and expected proof hashes define the v1 baseline. Changing proof inputs or golden hashes requires an intentional re-baseline and governance decision.
- Schema and contract files referenced by the freeze manifest are part of the frozen spec set for v1.
- For release tagging: use a commit where `governance/freeze_manifest_v1.json` and `dcs/expected_proof_hashes_v1.json` are in the intended state; see [REPRODUCIBILITY_AND_SCHEMAS.md](REPRODUCIBILITY_AND_SCHEMAS.md).
