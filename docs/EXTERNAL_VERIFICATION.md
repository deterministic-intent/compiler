# External Verification Guide

This document explains how an independent engineer can reproduce the deterministic proof for this repository.

Verification is successful if the generated proof hashes match the expected values in `dcs/expected_proof_hashes_v1.json`.

Expected runtime: ~5–15 minutes depending on hardware.

### Sealed state and drift

- **Golden hashes** are defined only for the commit where `dcs/expected_proof_hashes_v1.json` was last updated. If you are not on that commit (or a descendant that did not change proof inputs), hashes may legitimately differ.
- **Record the commit** after a successful run so the result is auditable:

  ```bash
  git rev-parse HEAD
  ```

- **Drift across commits**: Any change to proof inputs (Dockerfile, audit scripts, golden fixtures, snapshot pins) can change `PROOF_BUNDLE_SHA256` or related outputs. The project updates `dcs/expected_proof_hashes_v1.json` only when intentionally re-baselining v1.

### Proof profile and coverage

- **Single public profile (v1)**: The supported independent verification path is `./scripts/proof/run_clean_proof_v1.sh`. There is no alternate “light” or “internal-only” profile documented for external replay; other scripts under `scripts/` are development and CI helpers unless explicitly referenced from governance docs.
- **What the proof covers**: The script builds the tier3 Docker image, runs the full audit battery (binding matrix, step verifiers, validation hash generation, proof bundle assembly), and asserts byte-identical hashes across two consecutive runs. It does **not** replace all unit tests under `tests/` or every script under `scripts/`—those are supplementary. Freeze and scope boundaries are summarized in `governance/` and `docs/V1_FREEZE.md`.

## Requirements

You need:

- `git`
- `docker`
- `bash`

Docker must be installed and running.

## 1. Clone the repository

```bash
git clone <REPO_URL>
cd <REPO_DIR>
```

Replace `<REPO_URL>` and `<REPO_DIR>` with the actual repository URL and directory name.

## 2. Confirm the working tree is clean

```bash
git status
```

Expected result:

```text
nothing to commit, working tree clean
```

## 3. Run the proof

```bash
./scripts/proof/run_clean_proof_v1.sh
```

This script builds the deterministic execution environment, runs the proof pipeline, and writes the resulting hashes to:

```text
out/proof_hashes.json
```

## 4. Compare the output hashes

Display the generated hashes:

```bash
cat out/proof_hashes.json
```

Expected values:

```text
DIST_SHA256
dd06c68476dce155a3418160efdbf17380268fae267a721fcff615a023297740

VALIDATION_HASHES_SHA256
80f98ba15515ed00cefef97a7a3a19d65c00f99a8d225783b9dd85af4179992a

PROOF_BUNDLE_SHA256
702f3c49a4b5d600c8e5d3a470e29d32e61e5f62489a0b849d782f50aa29ff79
```

Verification succeeds if:

```text
out/proof_hashes.json == dcs/expected_proof_hashes_v1.json
```

A direct check:

```bash
diff -u dcs/expected_proof_hashes_v1.json out/proof_hashes.json
```

Expected result: no differences.

## What this verifies

A successful run demonstrates that:

* the deterministic execution environment builds correctly
* the proof pipeline reproduces the same artifact hash
* the validation hash set matches the expected result
* the proof bundle hash is reproducible

## If verification fails

Check the following first:

1. Docker is installed and running
2. the repository is on the intended commit
3. the working tree is clean
4. no local modifications were made before running proof

If the proof completes but the hashes differ, the run did not reproduce the expected deterministic result.
