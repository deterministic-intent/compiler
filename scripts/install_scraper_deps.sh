#!/usr/bin/env bash
set -euo pipefail

# Step 19: deterministic install behavior for scraper deps (harness-only).
#
# - Refuse unless in a venv
# - Install from pinned file only
# - Print the exact pip command run
# - Exit nonzero on any mismatch

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQ_FILE="${ROOT}/scripts/requirements/scraper.txt"

if [[ ! -f "${REQ_FILE}" ]]; then
  echo "ERROR: missing pinned requirements file: ${REQ_FILE}" >&2
  exit 1
fi

PY="${PYTHON:-python3}"

if ! command -v "${PY}" >/dev/null 2>&1; then
  echo "ERROR: python not found: ${PY}" >&2
  exit 1
fi

# Refuse to run outside a venv.
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
  # Secondary check: sys.prefix differs from base_prefix in venv.
  if ! "${PY}" -c 'import sys; raise SystemExit(0 if getattr(sys,"base_prefix",sys.prefix)!=sys.prefix else 1)'; then
    echo "ERROR: not in a virtualenv (VIRTUAL_ENV not set). Refusing to install." >&2
    exit 1
  fi
fi

CMD=( "${PY}" -m pip install -r "${REQ_FILE}" --disable-pip-version-check --no-input )
echo "+ ${CMD[*]}"
"${CMD[@]}"

# Verify exact pins are satisfied.
"${PY}" - <<'PY'
import sys
from importlib.metadata import version, PackageNotFoundError

PINS = {
    "sqlalchemy": "2.0.30",
    "httpx": "0.27.0",
    "beautifulsoup4": "4.12.3",
    "markdownify": "0.12.1",
    "pydantic": "2.6.4",
}

bad = []
for pkg, want in PINS.items():
    try:
        got = version(pkg)
    except PackageNotFoundError:
        bad.append(f"{pkg}=={want} (missing)")
        continue
    if str(got).strip() != want:
        bad.append(f"{pkg}=={want} (got {got})")

if bad:
    sys.stderr.write("ERROR: pinned deps mismatch:\n")
    for b in bad:
        sys.stderr.write("  - " + b + "\n")
    raise SystemExit(1)
PY

echo "OK: scraper deps installed and pinned versions match."


