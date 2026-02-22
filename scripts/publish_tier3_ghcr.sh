#!/usr/bin/env bash
# Publish dcs-tier3 image to GHCR (required for CI).
# Run on build host with: docker login ghcr.io
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="ghcr.io/deterministic-intent/dcs-tier3"
TAG="rc"

echo "Building tier3 image..."
docker build --no-cache -t "${IMAGE}:${TAG}" -f "$REPO_ROOT/Dockerfile.tier3" "$REPO_ROOT"

echo "Pushing to GHCR..."
docker push "${IMAGE}:${TAG}"

echo ""
echo "Digest (pin this in .github/workflows/dcs.yml):"
docker inspect --format='{{index .RepoDigests 0}}' "${IMAGE}:${TAG}"
