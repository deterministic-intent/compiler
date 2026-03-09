#!/usr/bin/env bash
# v1 Proof Kit: one-command repro runner.
# Requires: Docker. Run from extracted kit root. Never run as root.
set -euo pipefail

# Forbid root on host (prevents permission issues); CI runs in container as root (ephemeral, allowed)
if [[ "$(id -u)" -eq 0 ]] && [[ "${GITHUB_ACTIONS:-}" != "true" ]]; then
  echo "PROOF_ROOT_FORBIDDEN" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT_DIR="$KIT_ROOT/out"

# Snapshot + state root: env or positional args (from run_clean_proof_v1.sh)
SNAPSHOT_ID="${DCS_PROOF_SNAPSHOT_ID:-${1:-}}"
HOST_STATE_ROOT="${DCS_PROOF_STATE_ROOT:-${2:-}}"
REQUESTS_DIR="${DCS_PROOF_REQUESTS_DIR:-}"

# Host path for host-side ops; container path for docker (workspace mounted at /workspace)
STATE_ROOT="$HOST_STATE_ROOT"
REL="${HOST_STATE_ROOT#$KIT_ROOT}"
REL="${REL#/}"
CONTAINER_STATE_ROOT="/workspace/${REL:-out/proof}"
CONTAINER_REQUESTS_DIR="$CONTAINER_STATE_ROOT/state/requests"

if [[ -z "$SNAPSHOT_ID" ]]; then
  echo "PROOF_MISSING_SNAPSHOT_ID" >&2
  exit 2
fi
if [[ -z "$HOST_STATE_ROOT" ]]; then
  echo "PROOF_MISSING_STATE_ROOT" >&2
  exit 2
fi
STATE_ROOT="$HOST_STATE_ROOT"
[[ -z "$REQUESTS_DIR" ]] && REQUESTS_DIR="$STATE_ROOT/state/requests"

if [[ ! -w "$REQUESTS_DIR" ]] 2>/dev/null; then
  echo "PROOF_STATE_NOT_WRITABLE" >&2
  exit 2
fi

# 0) DB destruction guard: path-based, unconditional. Never rely on git.
NLC_DB="$KIT_ROOT/nlc/db"
CLEAN_DIR="$REQUESTS_DIR"
if [[ ! -d "$NLC_DB" ]]; then
  echo "FAIL: nlc/db missing (proof-critical). Refusing to proceed."
  exit 1
fi
case "${STATE_ROOT:-}" in *nlc/db* ) echo "FAIL: STATE_ROOT points into nlc/db"; exit 1 ;; esac
case "${NLC_REQUESTS_ROOT:-}" in *nlc/db* ) echo "FAIL: NLC_REQUESTS_ROOT points into nlc/db"; exit 1 ;; esac
# Ensure clean target cannot touch nlc/db (symlink or misconfigured path)
if [[ -e "$CLEAN_DIR" ]]; then
  if [[ -L "$CLEAN_DIR" ]]; then
    echo "FAIL: state/requests must not be a symlink (could target nlc/db). Refusing to proceed."
    exit 1
  fi
  CLEAN_REAL="" NLC_REAL=""
  if command -v realpath &>/dev/null; then
    CLEAN_REAL=$(realpath "$CLEAN_DIR" 2>/dev/null || true)
    NLC_REAL=$(realpath "$NLC_DB" 2>/dev/null || true)
  fi
  if [[ -n "$CLEAN_REAL" && -n "$NLC_REAL" && "$CLEAN_REAL" == "$NLC_REAL"* ]]; then
    echo "FAIL: Clean target $CLEAN_DIR resolves inside nlc/db. Refusing to proceed."
    exit 1
  fi
fi

# 1) Verify host prerequisites (skip when already in tier3 container)
if [[ -z "${DCS_SKIP_TIER3_BUILD:-}" ]]; then
  if ! command -v docker &>/dev/null; then
    echo "FAIL: docker not found. Install Docker and confirm 'docker version'."
    exit 1
  fi
  docker version &>/dev/null || { echo "FAIL: docker not runnable"; exit 1; }
fi

# 2) Clean state/requests for deterministic run (ownership guard: no sudo dependency)
if [[ -d "$CLEAN_DIR" ]]; then
  bad=$(find "$CLEAN_DIR" -not -user "$(id -u)" -print -quit 2>/dev/null || true)
  if [[ -n "$bad" ]]; then
    echo "FAIL: state/requests contains files not owned by current user. Run: chown -R \$(whoami):\$(id -gn) $CLEAN_DIR"
    echo "PROOF_RUN_STATE_REQUESTS_OWNERSHIP_VIOLATION"
    exit 1
  fi
fi
rm -rf "$CLEAN_DIR"/*
mkdir -p "$CLEAN_DIR"

# 3) Build Tier3 image (no cache) — skip when already in tier3 (e.g. CI job container)
# DOCKER_HOST_WORKSPACE: when CI runs in a container, docker -v needs the host path (not /__w/...)
HOST_WORKSPACE="${DOCKER_HOST_WORKSPACE:-$(pwd)}"
DOCKER_MOUNT_SRC="$HOST_WORKSPACE"
if [[ ! -f "$HOST_WORKSPACE/scripts/audit/run_audit.py" ]]; then
  echo "DOCKER_HOST_WORKSPACE_INVALID: $HOST_WORKSPACE" >&2
  exit 2
fi
if [[ -z "${DCS_SKIP_TIER3_BUILD:-}" ]]; then
  echo "Building Tier3 image..."
  docker build --no-cache -t dcs-tier3 -f "$KIT_ROOT/Dockerfile.tier3" "$KIT_ROOT" || { echo "FAIL: docker build failed"; exit 1; }
fi

# 4) Run v1 audit inside container (--user so host mount writes are owned by current user)
# AUDIT_SCOPE: v1 (default, full battery) | proof (reduced, non-v1).
# Proof hashes (step 5-6) are written ONLY on successful audit; || exit 1 prevents fallthrough on failure.
SCOPE="${AUDIT_SCOPE:-v1}"
echo "Running audit (scope=$SCOPE)..."
EXTERNAL_SNAP_ROOT="${DCS_EXTERNAL_SNAPSHOT_ROOT:-$STATE_ROOT/snapshots/external}"
if [[ -n "${DCS_SKIP_TIER3_BUILD:-}" ]]; then
  # Already in tier3 container (CI); run audit in-process with same env as docker run
  (cd "$KIT_ROOT" && HOME=/tmp AUDIT_SCOPE="$SCOPE" AUDIT_POLICY=v1 \
    DCS_EXTERNAL_SNAPSHOT_ROOT="$EXTERNAL_SNAP_ROOT" \
    AUDIT_CLOSURE_SNAPSHOT=$SNAPSHOT_ID DCS_PROOF_SNAPSHOT_ID=$SNAPSHOT_ID \
    DCS_PROOF_STATE_ROOT=$STATE_ROOT DCS_PROOF_REQUESTS_DIR=$REQUESTS_DIR \
    NLC_DB_SNAPSHOT_ID=$SNAPSHOT_ID NLC_SNAPSHOT_ID=$SNAPSHOT_ID NLC_KB_SNAPSHOT_ID=$SNAPSHOT_ID \
    python3 scripts/audit/run_audit.py --policy v1 --state-root "$STATE_ROOT") || { echo "FAIL: audit exited non-zero"; exit 1; }
elif [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
  # CI: image has repo baked in (COPY in Dockerfile); mount only proof output dir so host sees audit writes
  HOST_WORKSPACE="${DOCKER_HOST_WORKSPACE:?DOCKER_HOST_WORKSPACE not set}"
  HOST_PROOF_ROOT="$HOST_WORKSPACE/out/proof"
  mkdir -p "$HOST_PROOF_ROOT"
  docker run --rm \
    -v "$HOST_PROOF_ROOT:/workspace/out/proof" \
    -e DCS_PROOF_SNAPSHOT_ID="$SNAPSHOT_ID" \
    -e AUDIT_CLOSURE_SNAPSHOT="$SNAPSHOT_ID" \
    -e NLC_DB_SNAPSHOT_ID="$SNAPSHOT_ID" \
    -e NLC_SNAPSHOT_ID="$SNAPSHOT_ID" \
    -e NLC_KB_SNAPSHOT_ID="$SNAPSHOT_ID" \
    -e DCS_PROOF_STATE_ROOT="/workspace/out/proof" \
    -e DCS_PROOF_REQUESTS_DIR="/workspace/out/proof/state/requests" \
    -e NLC_REQUESTS_ROOT="/workspace/out/proof/state/requests" \
    -e DCS_EXTERNAL_SNAPSHOT_ROOT="/workspace/out/proof/snapshots/external" \
    dcs-tier3 \
    bash -lc '
      test -f /workspace/scripts/audit/run_audit.py || { echo TIER3_WORKSPACE_MISSING_AUDIT; exit 2; }
      python3 scripts/audit/run_audit.py --policy v1 --snapshot-id "$DCS_PROOF_SNAPSHOT_ID" --state-root /workspace/out/proof
      echo "=== INSIDE TIER3 PACKAGE SCAN ==="
      find /workspace/out/proof/state/requests -maxdepth 3 \( -name "artifact.zip" -o -name "site.zip" \) | sort || true
      echo "=== INSIDE TIER3 PACKAGE COUNT ==="
      find /workspace/out/proof/state/requests -maxdepth 3 \( -name "artifact.zip" -o -name "site.zip" \) | wc -l
    ' || { echo "FAIL: audit exited non-zero"; exit 1; }
  echo "=== HOST PACKAGE SCAN ==="
  find "$HOST_PROOF_ROOT/state/requests" -maxdepth 3 \( -name "artifact.zip" -o -name "site.zip" \) 2>/dev/null | sort || true
  echo "=== HOST PACKAGE COUNT ==="
  find "$HOST_PROOF_ROOT/state/requests" -maxdepth 3 \( -name "artifact.zip" -o -name "site.zip" \) 2>/dev/null | wc -l
else
  # Local: bind-mount host workspace
  HOST_WORKSPACE="${DOCKER_HOST_WORKSPACE:-$(pwd)}"
  if [[ ! -f "$HOST_WORKSPACE/scripts/audit/run_audit.py" ]]; then
    echo "DOCKER_HOST_WORKSPACE_INVALID: $HOST_WORKSPACE" >&2
    exit 2
  fi
  CONTAINER_EXTERNAL_SNAP="$CONTAINER_STATE_ROOT/snapshots/external"
  docker run --rm \
    --user "$(id -u):$(id -g)" \
    -v "$HOST_WORKSPACE:/workspace" \
    -w /workspace \
    -e HOME=/tmp \
    -e AUDIT_SCOPE="$SCOPE" \
    -e AUDIT_POLICY=v1 \
    -e DCS_EXTERNAL_SNAPSHOT_ROOT="$CONTAINER_EXTERNAL_SNAP" \
    -e AUDIT_CLOSURE_SNAPSHOT=$SNAPSHOT_ID \
    -e DCS_PROOF_SNAPSHOT_ID=$SNAPSHOT_ID \
    -e DCS_PROOF_STATE_ROOT="$CONTAINER_STATE_ROOT" \
    -e DCS_PROOF_REQUESTS_DIR="$CONTAINER_REQUESTS_DIR" \
    -e NLC_REQUESTS_ROOT="$CONTAINER_REQUESTS_DIR" \
    -e NLC_DB_SNAPSHOT_ID=$SNAPSHOT_ID \
    -e NLC_SNAPSHOT_ID=$SNAPSHOT_ID \
    -e NLC_KB_SNAPSHOT_ID=$SNAPSHOT_ID \
    dcs-tier3 \
    bash -lc 'pwd; ls -la /workspace | head -20; ls -la /workspace/scripts/audit 2>/dev/null | head -20; test -f /workspace/scripts/audit/run_audit.py || { echo TIER3_WORKSPACE_MISSING_AUDIT; exit 2; }; python3 scripts/audit/run_audit.py --policy v1 --state-root "$DCS_PROOF_STATE_ROOT"' || { echo "FAIL: audit exited non-zero"; exit 1; }
fi

# 5) Compute three SHA256 values
mkdir -p "$OUT_DIR"

# Requests root: DCS_PROOF_REQUESTS_DIR | NLC_REQUESTS_ROOT | explicit arg (never hardcoded state/requests)
REQUESTS_ROOT="${DCS_PROOF_REQUESTS_DIR:-${NLC_REQUESTS_ROOT:-$REQUESTS_DIR}}"
echo "proof requests root: $REQUESTS_ROOT"

# Non-package-producing dirs (audit controls, gate proofs, negatives) — skip when scanning
_is_excluded() {
  case "$1" in
    E2E0-D-AUDIT|G0-PROOF-BLOCKED|G0-PROOF-PASS|STEP9-AUDIT|STEP10-AUDIT|STEP11-AUDIT|STEP12-AUDIT|STEP13-AUDIT|STEP18-E2E-NEG1|STEP18-E2E-NEG2|STEP18-E2E-NEG3) return 0 ;;
    *) return 1 ;;
  esac
}

# DIST_SHA256: first artifact.zip from positive executable requests (sorted for determinism)
DIST_ZIP=""
for d in $(find "$REQUESTS_ROOT" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort); do
  _is_excluded "$(basename "$d")" && continue
  if [[ -f "$d/dist/artifact.zip" ]]; then
    DIST_ZIP="$d/dist/artifact.zip"
    break
  fi
  if [[ -f "$d/dist/site.zip" ]]; then
    DIST_ZIP="$d/dist/site.zip"
    break
  fi
done
if [[ -z "$DIST_ZIP" || ! -f "$DIST_ZIP" ]]; then
  echo "FAIL: no artifact.zip or site.zip found in positive executable requests (root=$REQUESTS_ROOT)"
  exit 1
fi
DIST_SHA256="$(sha256sum "$DIST_ZIP" | cut -d' ' -f1)"

# VALIDATION_HASHES_SHA256
VH_PATH="$KIT_ROOT/nlc/db/snapshots/$SNAPSHOT_ID/reports/validation_hashes.json"
if [[ ! -f "$VH_PATH" ]]; then
  echo "FAIL: validation_hashes.json not found: $VH_PATH"
  exit 1
fi
VALIDATION_HASHES_SHA256="$(sha256sum "$VH_PATH" | cut -d' ' -f1)"

# PROOF_BUNDLE_SHA256: first proof_bundle.zip from positive executable requests (sorted for determinism)
PROOF_BUNDLE=""
for d in $(find "$REQUESTS_ROOT" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort); do
  _is_excluded "$(basename "$d")" && continue
  if [[ -f "$d/dist/proof_bundle.zip" ]]; then
    PROOF_BUNDLE="$d/dist/proof_bundle.zip"
    break
  fi
done
if [[ -z "$PROOF_BUNDLE" || ! -f "$PROOF_BUNDLE" ]]; then
  echo "FAIL: no proof_bundle.zip found in positive executable requests (root=$REQUESTS_ROOT)"
  exit 1
fi
PROOF_BUNDLE_SHA256="$(sha256sum "$PROOF_BUNDLE" | cut -d' ' -f1)"

# 6) Write outputs
echo "DIST_SHA256=$DIST_SHA256"
echo "VALIDATION_HASHES_SHA256=$VALIDATION_HASHES_SHA256"
echo "PROOF_BUNDLE_SHA256=$PROOF_BUNDLE_SHA256"

cat > "$OUT_DIR/proof_hashes.json" << EOF
{
  "DIST_SHA256": "$DIST_SHA256",
  "VALIDATION_HASHES_SHA256": "$VALIDATION_HASHES_SHA256",
  "PROOF_BUNDLE_SHA256": "$PROOF_BUNDLE_SHA256"
}
EOF

# proof_hashes.sha256: sha256sum -c verifiable manifest (paths relative to KIT_ROOT)
DIST_REL="${DIST_ZIP#$KIT_ROOT/}"
VH_REL="${VH_PATH#$KIT_ROOT/}"
PROOF_REL="${PROOF_BUNDLE#$KIT_ROOT/}"
printf '%s  %s\n' "$DIST_SHA256" "$DIST_REL" > "$OUT_DIR/proof_hashes.sha256"
printf '%s  %s\n' "$VALIDATION_HASHES_SHA256" "$VH_REL" >> "$OUT_DIR/proof_hashes.sha256"
printf '%s  %s\n' "$PROOF_BUNDLE_SHA256" "$PROOF_REL" >> "$OUT_DIR/proof_hashes.sha256"

echo ""
echo "Proof hashes written to $OUT_DIR/proof_hashes.json and $OUT_DIR/proof_hashes.sha256"
