#!/usr/bin/env python3
"""
Step 17 proof: deterministic NL -> .dcs compiler (intake only).

Assertions:
- Same NL input produces byte-identical .dcs
- knowledge_snapshot_id resolves deterministically and exists
- manifest_bundle_hash matches snapshot manifests
- Ambiguous input returns CLARIFY and does not write output file
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))


def die(msg: str, code: int = 1) -> None:
    sys.stderr.write(f"ERROR: {msg}\n")
    sys.stderr.flush()
    raise SystemExit(code)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def run(cmd: list[str], env: dict | None = None) -> tuple[int, str, str]:
    env = env or os.environ
    p = subprocess.run(cmd, cwd=str(BASE), env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    return p.returncode, p.stdout or "", p.stderr or ""


def load_json_strict(p: Path) -> dict:
    obj = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        die(f"{p} must be a JSON object")
    return obj


def assert_dcs_schema(obj: dict) -> None:
    required = [
        "request_id",
        "artifact_class",
        "goal",
        "constraints",
        "non_goals",
        "policy_version",
        "knowledge_snapshot_id",
        "manifest_bundle_hash",
        "answer_mode",
    ]
    if sorted(obj.keys()) != sorted(required):
        die(f".dcs keys mismatch. got={sorted(obj.keys())} required={sorted(required)}")
    if obj.get("policy_version") != "v1":
        die("policy_version must be v1")
    if obj.get("answer_mode") != "index_backed":
        die("answer_mode must be index_backed")
    if not isinstance(obj.get("constraints"), list) or not isinstance(obj.get("non_goals"), list):
        die("constraints and non_goals must be arrays")
    if not str(obj.get("knowledge_snapshot_id") or "").strip():
        die("knowledge_snapshot_id must be non-empty")
    if not str(obj.get("manifest_bundle_hash") or "").strip():
        die("manifest_bundle_hash must be non-empty")


def verify_bundle_hash(snapshot_id: str, expected_bundle_hash: str) -> None:
    try:
        from nlc.reproducibility import get_manifest_hashes
    except Exception as e:
        die(f"cannot import nlc.reproducibility.get_manifest_hashes: {e}")
    info = get_manifest_hashes(snapshot_id)
    got = str(info.get("manifest_bundle_hash", "")).strip()
    if not got:
        die(f"manifest_bundle_hash not found for snapshot {snapshot_id}")
    if got != expected_bundle_hash:
        die(f"manifest_bundle_hash mismatch: expected {expected_bundle_hash} got {got}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", default="build a python cli that counts from 1 to 5")
    ap.add_argument("--out-a", default="/tmp/step17_a.dcs")
    ap.add_argument("--out-b", default="/tmp/step17_b.dcs")
    ap.add_argument("--snapshot-id", default="20260208T190113Z", help="Knowledge snapshot (must exist in proof kit)")
    args = ap.parse_args()

    snapshot_id = args.snapshot_id
    env = os.environ.copy()
    env["NLC_DB_SNAPSHOT_ID"] = snapshot_id
    env["NLC_SNAPSHOT_ID"] = snapshot_id
    env["NLC_KB_SNAPSHOT_ID"] = snapshot_id

    out_a = Path(args.out_a)
    out_b = Path(args.out_b)
    for p in (out_a, out_b):
        if p.exists():
            p.unlink()

    # Ensure compile does not create request directories (intake only).
    req_root = BASE / "state" / "requests"
    before = sorted([p.name for p in req_root.iterdir() if p.is_dir()]) if req_root.exists() else []

    dcs_bin = str(BASE / "scripts" / "bin" / "dcs")
    cmd_a = [dcs_bin, "--no-banner", "--no-color", "compile", args.text, "--out", str(out_a), "--snapshot", snapshot_id]
    rc, out, err = run(cmd_a, env=env)
    if rc != 0:
        die(f"compile run A failed rc={rc}\nSTDOUT:\n{out}\nSTDERR:\n{err}", rc)
    if not out_a.exists():
        die(f"expected output file missing: {out_a}")

    cmd_b = [dcs_bin, "--no-banner", "--no-color", "compile", args.text, "--out", str(out_b), "--snapshot", snapshot_id]
    rc, out, err = run(cmd_b, env=env)
    if rc != 0:
        die(f"compile run B failed rc={rc}\nSTDOUT:\n{out}\nSTDERR:\n{err}", rc)
    if not out_b.exists():
        die(f"expected output file missing: {out_b}")

    a_bytes = out_a.read_bytes()
    b_bytes = out_b.read_bytes()
    if not a_bytes.endswith(b"\n") or not b_bytes.endswith(b"\n"):
        die("output must end with trailing newline")
    if sha256_bytes(a_bytes) != sha256_bytes(b_bytes):
        die("outputs not byte-identical across identical inputs")

    obj = load_json_strict(out_a)
    assert_dcs_schema(obj)

    sid = str(obj["knowledge_snapshot_id"]).strip()
    snap_dir = BASE / "nlc" / "db" / "snapshots" / sid
    if not snap_dir.exists():
        die(f"resolved snapshot does not exist: {snap_dir}")
    manifest_dir = snap_dir / "manifest"
    if not manifest_dir.exists():
        die(f"resolved snapshot missing manifest/: {manifest_dir}")
    verify_bundle_hash(sid, str(obj["manifest_bundle_hash"]).strip())

    after = sorted([p.name for p in req_root.iterdir() if p.is_dir()]) if req_root.exists() else []
    if before != after:
        die("compile modified state/requests/ (must not create request dirs)")

    # Ambiguous input must CLARIFY and must not write file.
    ambiguous_out = Path("/tmp/step17_ambiguous.dcs")
    if ambiguous_out.exists():
        ambiguous_out.unlink()
    cmd_c = [dcs_bin, "--no-banner", "--no-color", "compile", "build something", "--out", str(ambiguous_out), "--snapshot", snapshot_id]
    rc, out, err = run(cmd_c, env=env)
    if rc == 0:
        die("expected CLARIFY for ambiguous input, got success")
    if ambiguous_out.exists():
        die("ambiguous compile must not emit a .dcs output file")

    sys.stdout.write("✓ Step 17 compile is deterministic and pinned (and refuses ambiguity)\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


