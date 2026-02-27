#!/usr/bin/env bash
# Clean-room proof v1: refuses dirty trees, runs full battery in order.
# Must run from /opt/dcs-public only. Never run as root.
set -euo pipefail
export LC_ALL=C
export LANG=C
export PYTHONHASHSEED=0

REQUIRED_ROOT="/opt/dcs-public"
SNAPSHOT_ID="20260215T120000Z"
STATE_REQUESTS="$REQUIRED_ROOT/state/requests"

# 0) Forbid root; proof must run as normal user
if [[ "$(id -u)" -eq 0 ]]; then
  echo "PROOF_ROOT_FORBIDDEN" >&2
  exit 2
fi

# 0b) state/requests must be writable (no privileged lane; user must repair ownership)
if [[ -e "$STATE_REQUESTS" ]] && [[ ! -w "$STATE_REQUESTS" ]]; then
  echo "PROOF_STATE_NOT_WRITABLE" >&2
  exit 2
fi
if [[ -d "$STATE_REQUESTS" ]]; then
  test_file="$STATE_REQUESTS/.proof_write_test_$$"
  if ! touch "$test_file" 2>/dev/null; then
    echo "PROOF_STATE_NOT_WRITABLE" >&2
    exit 2
  fi
  rm -f "$test_file"
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
export DCS_SKIP_TIER3_BUILD=1

echo "=== Clean-room proof v1 ==="
echo "repo_root=$REQUIRED_ROOT"
echo "snapshot_id=$SNAPSHOT_ID"
echo ""

# 3) E2E0 battery
echo "--- E2E0-A/B/C/D ---"
NLC_DB_SNAPSHOT_ID=$SNAPSHOT_ID NLC_SNAPSHOT_ID=$SNAPSHOT_ID NLC_KB_SNAPSHOT_ID=$SNAPSHOT_ID \
  python3 scripts/e2e/run_e2e0.py --snapshot "$SNAPSHOT_ID" --policy v1 --request-id AUDIT --state-root out/proof \
  || { echo "E2E0 FAIL"; exit 2; }
echo ""

# 4) Golden suite surface verify
echo "--- verify_golden_suite_surface ---"
python3 scripts/verify_golden_suite_surface.py --suite-dir suites/golden/v1/requests --snapshot-id "$SNAPSHOT_ID" \
  || { echo "verify_golden_suite_surface FAIL"; exit 2; }
echo ""

# 5) Proof run 1
echo "--- proof run 1 ---"
DCS_SKIP_TIER3_BUILD=1 proof/run_proof.sh || { echo "proof run 1 FAIL"; exit 2; }
# Composite: COMPOSITE_SHA256 if present, else sha256 of proof_hashes.json
HASH1="$(jq -r '.COMPOSITE_SHA256 // empty' out/proof_hashes.json 2>/dev/null)"
[[ -z "$HASH1" ]] && HASH1="$(sha256sum out/proof_hashes.json 2>/dev/null | cut -d' ' -f1)"
echo "run1 hash: ${HASH1:-unknown}"
echo ""

# 6) Proof run 2
echo "--- proof run 2 ---"
DCS_SKIP_TIER3_BUILD=1 proof/run_proof.sh || { echo "proof run 2 FAIL"; exit 2; }
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

# 8) Full audit battery (optional full run; proof already validated)
echo "--- audit battery ---"
AUDIT_CLOSURE_SNAPSHOT=$SNAPSHOT_ID NLC_DB_SNAPSHOT_ID=$SNAPSHOT_ID NLC_SNAPSHOT_ID=$SNAPSHOT_ID NLC_KB_SNAPSHOT_ID=$SNAPSHOT_ID \
  python3 scripts/audit/run_audit.py 2>/dev/null || true
echo ""

# 9) Summary
REQ_COUNT="$(find suites/golden/v1/requests -mindepth 1 -maxdepth 1 -type d \( -name 'LANG_*' -o -name 'NEG_*' \) 2>/dev/null | wc -l)"
echo "=== SUMMARY ==="
echo "snapshot_id: $SNAPSHOT_ID"
echo "suite_req_count: $REQ_COUNT"
echo "proof_hash_run1: $HASH1"
echo "proof_hash_run2: $HASH2"
echo "PASS"
