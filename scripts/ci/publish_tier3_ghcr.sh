#!/usr/bin/env bash
# Publish tier3 to GHCR (required for Phase 4 CI).
# Run on Docker-capable host: bash scripts/ci/publish_tier3_ghcr.sh
set -euo pipefail

TARBALL="${1:-/opt/llm-hub/dist/tier3/llm-hub-tier3.oci.tar}"
TARGET="ghcr.io/deterministic-intent/dcs-tier3:rc"

echo "Loading $TARBALL..."
OUT=$(docker load -i "$TARBALL" 2>&1)
echo "$OUT"
LOADED=$(echo "$OUT" | grep "Loaded image:" | sed 's/Loaded image: //')
if [ -z "$LOADED" ]; then
  echo "FAIL: could not parse loaded image from docker load output"
  exit 1
fi

echo "Tagging $LOADED -> $TARGET"
docker tag "$LOADED" "$TARGET"

echo "Pushing to GHCR..."
docker push "$TARGET"

echo ""
echo "Digest — update .github/workflows/dcs.yml container.image to:"
docker inspect --format='{{index .RepoDigests 0}}' "$TARGET"
