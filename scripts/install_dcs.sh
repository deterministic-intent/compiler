#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="${HOME}/.local/bin"
mkdir -p "${BIN_DIR}"
ln -sf "${ROOT_DIR}/scripts/bin/dcs" "${BIN_DIR}/dcs"
echo "Installed dcs -> ${BIN_DIR}/dcs"
echo "Ensure ${BIN_DIR} is on PATH (e.g., export PATH=\"${BIN_DIR}:\$PATH\")"

