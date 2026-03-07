#!/usr/bin/env python3
"""
Build the v1 Proof Kit: a single tarball for machine install + repro run.
Produces: dist/dcs-v1-proof-kit-<snapshot>-<gitsha8>.tar.gz
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DIST_DIR = BASE / "dist"
STAGING = Path("/tmp") / "proof_kit_staging"


def _get_snapshot_id() -> str:
    sid = (os.environ.get("DCS_PROOF_SNAPSHOT_ID") or os.environ.get("AUDIT_CLOSURE_SNAPSHOT") or "").strip()
    if sid:
        return sid
    sys.stderr.write("MISSING_SNAPSHOT_ID: set DCS_PROOF_SNAPSHOT_ID for build_v1_proof_kit\n")
    sys.exit(2)


def _git_sha8() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short=8", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(BASE),
            timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return "00000000"


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _collect_files(staging: Path) -> list[tuple[str, str]]:
    """Return list of (rel_path, sha256) for manifest."""
    out = []
    for f in sorted(staging.rglob("*")):
        if f.is_file():
            rel = str(f.relative_to(staging)).replace("\\", "/")
            out.append((rel, _sha256_file(f)))
    return out


def _copy_tree(src: Path, dst: Path, exclude: set[str] | None = None) -> None:
    exclude = exclude or set()
    for item in src.rglob("*"):
        if item.is_file():
            rel = item.relative_to(src)
            if any(rel.parts[0] == e for e in exclude):
                continue
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def main() -> int:
    snapshot_id = _get_snapshot_id()
    gitsha = _git_sha8()
    tarball_name = f"dcs-v1-proof-kit-{snapshot_id}-{gitsha}.tar.gz"

    # Clean staging; use repo root for tarball if dist not writable
    out_dir = DIST_DIR if (DIST_DIR.exists() and os.access(DIST_DIR, os.W_OK)) else BASE
    tarball_path = out_dir / tarball_name
    if out_dir.exists():
        for p in out_dir.iterdir():
            if p.is_file() and p.name.startswith("dcs-v1-proof-kit-") and p.suffix == ".gz":
                p.unlink(missing_ok=True)
    if STAGING.exists():
        shutil.rmtree(STAGING, ignore_errors=True)
    STAGING.mkdir(parents=True, exist_ok=True)
    for p in STAGING.iterdir():
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()

    snap_src = BASE / "nlc" / "db" / "snapshots" / snapshot_id
    if not snap_src.exists():
        sys.stderr.write(f"FAIL: snapshot not found: {snap_src}\n")
        return 1

    # Copy snapshot (exact structure)
    snap_dst = STAGING / "nlc" / "db" / "snapshots" / snapshot_id
    snap_dst.mkdir(parents=True, exist_ok=True)
    for item in snap_src.iterdir():
        dst_item = snap_dst / item.name
        if item.is_dir():
            shutil.copytree(item, dst_item, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dst_item)

    # Ensure validation_hashes.json exists (run if missing)
    vh_path = snap_dst / "reports" / "validation_hashes.json"
    vh_path.parent.mkdir(parents=True, exist_ok=True)
    if not vh_path.exists():
        v1_script = BASE / "scripts" / "run_validation_hashes_v1.py"
        if v1_script.exists():
            rc = subprocess.run(
                [sys.executable, str(v1_script), "--snapshot-id", snapshot_id, "--out", str(vh_path)],
                cwd=str(BASE),
                capture_output=True,
                timeout=300,
            )
            if rc.returncode != 0:
                sys.stderr.write("FAIL: could not generate validation_hashes.json\n")
                return 1
        else:
            # Fallback: write minimal placeholder when script absent
            vh_path.write_text(json.dumps({}) + "\n", encoding="utf-8")

    # Copy Tier3 Dockerfile as Dockerfile.tier3
    dockerfile_src = BASE / "infra" / "tier3" / "Dockerfile"
    if dockerfile_src.exists():
        (STAGING / "Dockerfile.tier3").write_text(dockerfile_src.read_text(encoding="utf-8"))

    # Copy audit runner and all verify scripts + dependencies
    dirs_to_copy = [
        "scripts",
        "workers",
        "orchestrator",
        "nlc",
        "policy",
        "dcs_cli",
        "dcs_core",
        "verifier",
        "schemas",
        "contracts",
        "suites",
        "demo",
        "state",
        "versions",
        "governance",
    ]
    exclude_dirs = {"__pycache__", ".pyc", "requests", "proof_kit_staging"}
    for d in dirs_to_copy:
        src_d = BASE / d
        if src_d.exists():
            dst_d = STAGING / d
            if src_d.is_dir():
                for item in src_d.rglob("*"):
                    if item.is_file():
                        rel = item.relative_to(src_d)
                        if "requests" in rel.parts and d == "state":
                            continue  # exclude state/requests/*
                        if "__pycache__" in rel.parts or item.suffix == ".pyc":
                            continue
                        target = dst_d / rel
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, target)
            else:
                shutil.copy2(src_d, dst_d)

    # Ensure state/requests exists but is empty
    (STAGING / "state" / "requests").mkdir(parents=True, exist_ok=True)

    # Copy proof/ files (run_proof.sh, PROOF_INSTRUCTIONS.md - created below)
    proof_dir = STAGING / "proof"
    proof_dir.mkdir(parents=True, exist_ok=True)

    # Create run_proof.sh
    run_proof = proof_dir / "run_proof.sh"
    run_proof.write_text(_RUN_PROOF_SH.replace("__SNAPSHOT_ID__", snapshot_id), encoding="utf-8")
    run_proof.chmod(0o755)

    # Create PROOF_INSTRUCTIONS.md
    (proof_dir / "PROOF_INSTRUCTIONS.md").write_text(_PROOF_INSTRUCTIONS, encoding="utf-8")

    # Create manifest.json (no timestamps)
    files_with_sha = _collect_files(STAGING)
    manifest = {
        "commit_hash": gitsha,
        "snapshot_id": snapshot_id,
        "included_files": [{"path": p, "sha256": s} for p, s in files_with_sha],
    }
    (proof_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Create checksums.sha256
    checksum_lines = [f"{s}  {p}" for p, s in sorted(files_with_sha)]
    (proof_dir / "checksums.sha256").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    # Create tarball (arcname = path relative to staging root so extract gives kit structure)
    import tarfile
    with tarfile.open(tarball_path, "w:gz") as tf:
        for f in sorted(STAGING.rglob("*")):
            if f.is_file():
                arcname = str(f.relative_to(STAGING)).replace("\\", "/")
                tf.add(f, arcname=arcname)

    # Cleanup staging
    shutil.rmtree(STAGING, ignore_errors=True)

    sys.stdout.write(f"Proof kit: {tarball_path}\n")
    return 0


_RUN_PROOF_SH = r'''#!/usr/bin/env bash
# v1 Proof Kit: one-command repro runner.
# Requires: Docker. Run from extracted kit root.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT_DIR="$KIT_ROOT/out"
SNAPSHOT_ID="__SNAPSHOT_ID__"

# 0) DB destruction guard: path-based, unconditional. Never rely on git.
NLC_DB="$KIT_ROOT/nlc/db"
CLEAN_DIR="$KIT_ROOT/state/requests"
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

# 1) Verify host prerequisites
if ! command -v docker &>/dev/null; then
  echo "FAIL: docker not found. Install Docker and confirm 'docker version'."
  exit 1
fi
docker version &>/dev/null || { echo "FAIL: docker not runnable"; exit 1; }

# 2) Clean state/requests for deterministic run (ownership guard: no sudo dependency)
if [[ -d "$CLEAN_DIR" ]]; then
  bad=$(find "$CLEAN_DIR" -not -user "$(id -u)" -print -quit 2>/dev/null || true)
  if [[ -n "$bad" ]]; then
    echo "FAIL: state/requests contains files not owned by current user (rerun needs sudo). First: $bad"
    echo "PROOF_RUN_STATE_REQUESTS_OWNERSHIP_VIOLATION"
    exit 1
  fi
fi
rm -rf "$CLEAN_DIR"/*
mkdir -p "$CLEAN_DIR"

# 3) Build Tier3 image (no cache)
echo "Building Tier3 image..."
docker build --no-cache -t dcs-tier3 -f "$KIT_ROOT/Dockerfile.tier3" "$KIT_ROOT" || { echo "FAIL: docker build failed"; exit 1; }

# 4) Run v1 audit inside container (--user so host mount writes are owned by current user)
# AUDIT_SCOPE: v1 (default, full battery) | proof (reduced, non-v1).
# Proof hashes (step 5-6) are written ONLY on successful audit; || exit 1 prevents fallthrough on failure.
SCOPE="${AUDIT_SCOPE:-v1}"
echo "Running audit (scope=$SCOPE)..."
docker run --rm \
  --user "$(id -u):$(id -g)" \
  -v "$KIT_ROOT:/workspace" \
  -w /workspace \
  -e HOME=/tmp \
  -e AUDIT_SCOPE="$SCOPE" \
  -e AUDIT_POLICY=v1 \
  -e AUDIT_CLOSURE_SNAPSHOT=$SNAPSHOT_ID \
  -e NLC_DB_SNAPSHOT_ID=$SNAPSHOT_ID \
  -e NLC_SNAPSHOT_ID=$SNAPSHOT_ID \
  -e NLC_KB_SNAPSHOT_ID=$SNAPSHOT_ID \
  dcs-tier3 \
  python3 scripts/audit/run_audit.py --policy v1 || { echo "FAIL: audit exited non-zero"; exit 1; }

# 5) Compute three SHA256 values
mkdir -p "$OUT_DIR"

# DIST_SHA256: first artifact.zip (sorted for determinism)
DIST_ZIP=""
for d in $(find "$CLEAN_DIR" -mindepth 1 -maxdepth 1 -type d | sort); do
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
  echo "FAIL: no artifact.zip or site.zip found in state/requests"
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

# PROOF_BUNDLE_SHA256: first proof_bundle.zip (sorted for determinism)
PROOF_BUNDLE=""
for d in $(find "$CLEAN_DIR" -mindepth 1 -maxdepth 1 -type d | sort); do
  if [[ -f "$d/dist/proof_bundle.zip" ]]; then
    PROOF_BUNDLE="$d/dist/proof_bundle.zip"
    break
  fi
done
if [[ -z "$PROOF_BUNDLE" || ! -f "$PROOF_BUNDLE" ]]; then
  echo "FAIL: no proof_bundle.zip found in state/requests"
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
'''

_PROOF_INSTRUCTIONS = r'''# v1 Proof Kit Instructions

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
'''


if __name__ == "__main__":
    raise SystemExit(main())
