# v1 Proof Kit Instructions

## A) Install prereqs

Install Docker. Confirm:

```bash
docker version
```

## B) Run proof

Extract outside /tmp (e.g. under repo or home). From the extracted folder:

```bash
bash proof/run_proof.sh
```

## C) Determinism check (optional)

Extract to a path outside /tmp. Run twice and compare hashes:

```bash
rm -rf out && mkdir -p out
AUDIT_SCOPE=v1 bash proof/run_proof.sh |& tee out/run1.log
cp out/proof_hashes.json out/proof_hashes_run1.json
AUDIT_SCOPE=v1 bash proof/run_proof.sh |& tee out/run2.log
diff -u out/proof_hashes_run1.json out/proof_hashes.json
sha256sum -c out/proof_hashes.sha256
```

Pass if: diff is empty and sha256sum -c succeeds.

## D) What to report back

Paste:

- The three printed SHA256 values (DIST_SHA256, VALIDATION_HASHES_SHA256, PROOF_BUNDLE_SHA256)
- OS + CPU arch
- docker version
