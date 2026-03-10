#!/usr/bin/env bash
# Clean-room proof v1: refuses dirty trees, runs full battery in order.
# Must run from /opt/dcs-public only. Never run as root.
set -euo pipefail
export LC_ALL=C
export LANG=C
export PYTHONHASHSEED=0

REQUIRED_ROOT="/opt/dcs-public"
SNAPSHOT_ID="20260215T120000Z"
STATE_ROOT="$REQUIRED_ROOT/out/proof"
REQUESTS_DIR="$STATE_ROOT/state/requests"
FORBIDDEN_STATE="$REQUIRED_ROOT/state/requests"

# 0) Forbid root; proof must run as normal user
if [[ "$(id -u)" -eq 0 ]]; then
  echo "PROOF_ROOT_FORBIDDEN" >&2
  exit 2
fi

# 0b) Forbidden: repo state/requests must not be used (single state root: out/proof)
if [[ -d "$FORBIDDEN_STATE" ]] && [[ "$(ls -A "$FORBIDDEN_STATE" 2>/dev/null | wc -l)" -gt 0 ]]; then
  echo "PROOF_FORBIDDEN_STATE_ROOT_USED" >&2
  exit 2
fi

# 0c) REQUESTS_DIR must be writable
mkdir -p "$REQUESTS_DIR"
if ! touch "$REQUESTS_DIR/.proof_write_test_$$" 2>/dev/null; then
  echo "PROOF_STATE_NOT_WRITABLE" >&2
  exit 2
fi
rm -f "$REQUESTS_DIR/.proof_write_test_$$"

# 0d) Guard: no root-owned files under out/proof (from prior Docker runs)
if [[ -d "$STATE_ROOT" ]]; then
  bad=$(find "$STATE_ROOT" -not -user "$(id -u)" -print -quit 2>/dev/null || true)
  if [[ -n "$bad" ]]; then
    echo "PROOF_OUT_PROOF_ROOT_OWNED: out/proof contains root-owned files from a previous Docker run." >&2
    echo "Run: sudo chown -R \$(id -u):\$(id -g) $STATE_ROOT" >&2
    exit 2
  fi
fi

# 1) Verify repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT_ROOT_INIT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ACTUAL_ROOT="$(cd "$KIT_ROOT_INIT" && git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ "$ACTUAL_ROOT" != "$REQUIRED_ROOT" ]]; then
  echo "WRONG_REPO_ROOT" >&2
  exit 2
fi

# 2) Verify clean working tree
if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
  echo "DIRTY_WORKTREE_FORBIDDEN" >&2
  exit 2
fi

cd "$REQUIRED_ROOT"
KIT_ROOT="$REQUIRED_ROOT"
# Tier3 is default; set DCS_SKIP_TIER3_BUILD=1 to opt out
export DCS_PROOF_SNAPSHOT_ID="$SNAPSHOT_ID"
export DCS_PROOF_STATE_ROOT="$STATE_ROOT"
export DCS_PROOF_REQUESTS_DIR="$REQUESTS_DIR"
export DCS_EXTERNAL_SNAPSHOT_ROOT="$STATE_ROOT/snapshots/external"

echo "=== Clean-room proof v1 ==="
echo "repo_root=$REQUIRED_ROOT"
echo "snapshot_id=$SNAPSHOT_ID"
echo "state_root=$STATE_ROOT"
echo "requests_dir=$REQUESTS_DIR"
echo ""

# 3) E2E0 battery
echo "--- E2E0-A/B/C/D ---"
NLC_DB_SNAPSHOT_ID=$SNAPSHOT_ID NLC_SNAPSHOT_ID=$SNAPSHOT_ID NLC_KB_SNAPSHOT_ID=$SNAPSHOT_ID \
  python3 scripts/e2e/run_e2e0.py --snapshot "$SNAPSHOT_ID" --policy v1 --request-id AUDIT --state-root "$STATE_ROOT" \
  || { echo "E2E0 FAIL"; exit 2; }
echo ""

# 4) Binding matrix surface verify (19 LANG + NEG dirs; not Golden Suite 20-50)
echo "--- verify_binding_matrix_surface ---"
python3 scripts/verify_golden_suite_surface.py --suite-dir suites/golden/v1/requests --snapshot-id "$SNAPSHOT_ID" \
  || { echo "verify_binding_matrix_surface FAIL"; exit 2; }
echo ""

# 5) Proof run 1
echo "--- proof run 1 ---"
proof/run_proof.sh "$SNAPSHOT_ID" "$STATE_ROOT" || { echo "proof run 1 FAIL"; exit 2; }
# Composite: COMPOSITE_SHA256 if present, else sha256 of proof_hashes.json
HASH1="$(jq -r '.COMPOSITE_SHA256 // empty' out/proof_hashes.json 2>/dev/null)"
[[ -z "$HASH1" ]] && HASH1="$(sha256sum out/proof_hashes.json 2>/dev/null | cut -d' ' -f1)"
echo "run1 hash: ${HASH1:-unknown}"
echo ""

# 6) Proof run 2
echo "--- proof run 2 ---"
proof/run_proof.sh "$SNAPSHOT_ID" "$STATE_ROOT" || { echo "proof run 2 FAIL"; exit 2; }
HASH2="$(jq -r '.COMPOSITE_SHA256 // empty' out/proof_hashes.json 2>/dev/null)"
[[ -z "$HASH2" ]] && HASH2="$(sha256sum out/proof_hashes.json 2>/dev/null | cut -d' ' -f1)"
echo "run2 hash: ${HASH2:-unknown}"
echo ""

# 7) Compare hashes
if [[ -z "$HASH1" || -z "$HASH2" ]]; then
  echo "FAIL: could not extract composite hash"
  exit 2
fi
if [[ "$HASH1" != "$HASH2" ]]; then
  echo "FAIL: proof hash mismatch run1=$HASH1 run2=$HASH2"
  exit 2
fi
echo "✓ proof hash match: $HASH1"
echo ""

# 8) Full audit battery (same execution path as proof: inside Tier3)
echo "--- audit battery ---"
HOST_WS="$(pwd)"
CONTAINER_STATE="/workspace/out/proof"
docker run --rm \
  --user "$(id -u):$(id -g)" \
  -v "$HOST_WS:/workspace" \
  -w /workspace \
  -e HOME=/tmp \
  -e AUDIT_SCOPE=v1 \
  -e AUDIT_POLICY=v1 \
  -e DCS_EXTERNAL_SNAPSHOT_ROOT="$CONTAINER_STATE/snapshots/external" \
  -e AUDIT_CLOSURE_SNAPSHOT=$SNAPSHOT_ID \
  -e DCS_PROOF_SNAPSHOT_ID=$SNAPSHOT_ID \
  -e DCS_PROOF_STATE_ROOT="$CONTAINER_STATE" \
  -e DCS_PROOF_REQUESTS_DIR="$CONTAINER_STATE/state/requests" \
  -e NLC_REQUESTS_ROOT="$CONTAINER_STATE/state/requests" \
  -e NLC_DB_SNAPSHOT_ID=$SNAPSHOT_ID \
  -e NLC_SNAPSHOT_ID=$SNAPSHOT_ID \
  -e NLC_KB_SNAPSHOT_ID=$SNAPSHOT_ID \
  dcs-tier3 \
  python3 scripts/audit/run_audit.py --policy v1 --state-root "$CONTAINER_STATE" --snapshot-id "$SNAPSHOT_ID" \
  || { echo "audit battery FAIL"; exit 2; }
echo ""

# 9) Final guard: repo state/requests must still be clean
if [[ -d "$FORBIDDEN_STATE" ]] && [[ "$(ls -A "$FORBIDDEN_STATE" 2>/dev/null | wc -l)" -gt 0 ]]; then
  echo "PROOF_FORBIDDEN_STATE_ROOT_USED" >&2
  exit 2
fi

# 10) Summary
BINDING_COUNT="$(find suites/golden/v1/requests -mindepth 1 -maxdepth 1 -type d \( -name 'LANG_*' -o -name 'NEG_*' \) 2>/dev/null | wc -l)"
echo "=== SUMMARY ==="
echo "snapshot_id: $SNAPSHOT_ID"
echo "binding_matrix_dirs: $BINDING_COUNT"
echo "proof_hash_run1: $HASH1"
echo "proof_hash_run2: $HASH2"
echo "PASS"
