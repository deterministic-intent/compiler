#!/usr/bin/env python3
"""
Step 16 verification: first real PASS usage (non-example, end-to-end).
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


def die(msg: str, code: int = 2):
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_snapshot_manifest_bundle(snapshot_id: str, policy_version: str) -> str:
    """Ensure manifest bundle hash exists for the given snapshot (build if missing)."""
    from nlc.db.manifest_builder import build_all_manifests
    from nlc.reproducibility import get_manifest_hashes

    snapshot_dir = BASE / "nlc" / "db" / "snapshots" / snapshot_id
    manifest_dir = snapshot_dir / "manifest"
    if not snapshot_dir.exists():
        die(f"Snapshot not found: {snapshot_dir}")
    if not manifest_dir.exists():
        try:
            build_all_manifests(BASE, snapshot_id, policy_version)
        except Exception as e:
            die(f"Failed to build manifests for snapshot {snapshot_id}: {e}")
    manifest_info = get_manifest_hashes(snapshot_id)
    bundle_hash = manifest_info.get("manifest_bundle_hash")
    if not bundle_hash:
        die(f"Manifest bundle hash missing for snapshot {snapshot_id}")
    return bundle_hash


def run_dcs(spec_path: Path, env: dict | None = None) -> tuple[int, bytes]:
    env = dict(env or os.environ)
    cmd = [str(BASE / "scripts" / "bin" / "dcs"), "--no-banner", "--no-color", "run", str(spec_path)]
    p = subprocess.run(cmd, cwd=str(BASE), env=env, stdin=subprocess.DEVNULL, capture_output=True)
    out = (p.stdout or b"") + (p.stderr or b"")
    return p.returncode, out


def parse_deliverable_path(out: bytes) -> Path:
    txt = out.decode("utf-8", errors="replace")
    for ln in txt.splitlines():
        if ln.startswith("path: "):
            return Path(ln[len("path: ") :].strip())
    die("could not find deliverable DETAILS path in output")

def _run(cmd: list[str], cwd: Path | None = None) -> int:
    p = subprocess.run(cmd, cwd=str(cwd or BASE), stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if p.returncode != 0:
        die(f"command failed: {' '.join(cmd)}\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}", p.returncode)
    return p.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default="demo/real_pass.dcs")
    ap.add_argument("--snapshot-id", default=os.environ.get("DCS_PROOF_SNAPSHOT_ID") or os.environ.get("AUDIT_CLOSURE_SNAPSHOT", ""), help="Knowledge snapshot (must exist in proof kit)")
    ap.add_argument("--policy", default="v1")
    ap.add_argument("--requests-root", help="Requests dir (default: BASE/state/requests); sets NLC_REQUESTS_ROOT")
    args = ap.parse_args()

    spec_path = (BASE / args.spec).resolve()
    if not spec_path.exists():
        die(f"missing spec: {spec_path}")

    snapshot_id = args.snapshot_id or ""
    if not snapshot_id:
        die("--snapshot-id required (or set DCS_PROOF_SNAPSHOT_ID / AUDIT_CLOSURE_SNAPSHOT)")
    bundle_hash = ensure_snapshot_manifest_bundle(snapshot_id, args.policy)

    # Build spec with audit snapshot (spec file may reference legacy snapshot not in proof kit)
    spec = json.loads(spec_path.read_text(encoding="utf-8", errors="replace"))
    spec["knowledge_snapshot_id"] = snapshot_id
    spec["manifest_bundle_hash"] = bundle_hash

    env = os.environ.copy()
    env["NLC_DB_SNAPSHOT_ID"] = snapshot_id
    env["NLC_SNAPSHOT_ID"] = snapshot_id
    env["NLC_KB_SNAPSHOT_ID"] = snapshot_id
    if args.requests_root:
        env["NLC_REQUESTS_ROOT"] = args.requests_root

    with tempfile.NamedTemporaryFile(mode="w", suffix=".dcs", delete=False, dir=str(BASE)) as f:
        f.write(json.dumps(spec, indent=2, sort_keys=True) + "\n")
        tmp_spec = Path(f.name)
    try:
        # Run twice; must be byte-identical output and exit 0.
        rc1, out1 = run_dcs(tmp_spec, env=env)
        if rc1 != 0:
            die(f"run1 exit={rc1}\n{out1.decode('utf-8', errors='replace')}", rc1)
        # Locked UX: gate 7 uses OK/FAIL wording and lower-case label.
        if b"[gate 7] deliver" not in out1 or b"OK" not in out1:
            die("run1 missing gate7 OK line")

        deliverable1 = parse_deliverable_path(out1)
        if not deliverable1.exists():
            die(f"deliverable missing after run1: {deliverable1}")
        h1 = sha256_file(deliverable1)

        # Sidecar docs must exist for real PASS.
        dist_dir = deliverable1.parent
        for name in ("ENTRYPOINT.md", "manifest.json", "checksums.sha256"):
            p = dist_dir / name
            if not p.exists():
                die(f"missing dist sidecar: {p}")

        # artifact.zip must be a valid zip and match checksums.
        _run([sys.executable, "-m", "zipfile", "-t", str(deliverable1)])
        _run(["sha256sum", "-c", "checksums.sha256"], cwd=dist_dir)

        rc2, out2 = run_dcs(tmp_spec, env=env)
        if rc2 != 0:
            die(f"run2 exit={rc2}\n{out2.decode('utf-8', errors='replace')}", rc2)
        if out1 != out2:
            die("outputs are not byte-identical across runs")

        deliverable2 = parse_deliverable_path(out2)
        if not deliverable2.exists():
            die(f"deliverable missing after run2: {deliverable2}")
        h2 = sha256_file(deliverable2)
        if h1 != h2:
            die("deliverable bytes not deterministic across runs")

        print("✓ Step 16 real PASS produces deliverable deterministically")
        return 0
    finally:
        tmp_spec.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())


