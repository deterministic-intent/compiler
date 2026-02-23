#!/usr/bin/env bash
# Build tier3 image for GHCR publish. Run from repo root: bash scripts/ci/build_tier3.sh
# Then: bash scripts/ci/publish_tier3_ghcr.sh dist/tier3/dcs-tier3.oci.tar
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir -p "$REPO_ROOT/dist/tier3"
OUT="$REPO_ROOT/dist/tier3/dcs-tier3.oci.tar"

echo "Building tier3 from $REPO_ROOT..."
docker build --no-cache -t dcs-tier3 -f "$REPO_ROOT/Dockerfile.tier3" "$REPO_ROOT"
echo "Saving to $OUT..."
docker save dcs-tier3 -o "$OUT"
echo "Done. Publish with: bash scripts/ci/publish_tier3_ghcr.sh $OUT"
