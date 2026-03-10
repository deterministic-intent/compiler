# External Verification Guide

This document explains how an independent engineer can reproduce the deterministic proof for this repository.

Verification is successful if the generated proof hashes match the expected values in `dcs/expected_proof_hashes_v1.json`.

Expected runtime: ~5–15 minutes depending on hardware.

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
