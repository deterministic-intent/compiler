#!/usr/bin/env bash
# CI guard: no raw /tmp/ or absolute host paths in proof artifacts.
# Proof artifacts must contain only normalized placeholders (TMP_STAB_ROOT, <PROOF_ROOT>, <REPO_ROOT>).
set -euo pipefail

cd "${GITHUB_WORKSPACE:-.}"

SNAPSHOT_ID="${SNAPSHOT_ID:-20260215T120000Z}"
VH_PATH="nlc/db/snapshots/${SNAPSHOT_ID}/reports/validation_hashes.json"

fail() {
  echo "FAIL: $*" >&2
  exit 2
}

# 1) validation_hashes.json must not contain raw /tmp/stab_run or other /tmp/ paths
if [[ -f "$VH_PATH" ]]; then
  if grep -q '/tmp/stab_run' "$VH_PATH"; then
    fail "Raw /tmp/stab_run path in $VH_PATH (path normalization missing)"
  fi
  if grep -qE '"/tmp/[^"]+' "$VH_PATH"; then
    fail "Raw /tmp/ path in $VH_PATH (proof artifact must use normalized placeholders)"
  fi
  # Reject absolute host paths that should have been normalized
  if grep -qE '"/__w/[^/]+/[^/]+/' "$VH_PATH"; then
    fail "Absolute GitHub Actions path in $VH_PATH (use <REPO_ROOT> or <PROOF_ROOT>)"
  fi
  if grep -q '"/opt/dcs-public' "$VH_PATH"; then
    fail "Absolute local path in $VH_PATH (use <REPO_ROOT> or <PROOF_ROOT>)"
  fi
  echo "OK: $VH_PATH contains no raw paths"
else
  echo "SKIP: $VH_PATH not found (pre-provision?)"
fi

# 2) proof_hashes.json is small and path-free; spot-check
if [[ -f "out/proof_hashes.json" ]]; then
  if grep -qE '"/tmp/|/__w/|/opt/dcs-public' out/proof_hashes.json; then
    fail "Absolute or tmp path in out/proof_hashes.json"
  fi
  echo "OK: out/proof_hashes.json contains no raw paths"
fi

echo "OK: no raw paths in proof artifacts"
