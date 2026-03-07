#!/usr/bin/env python3
"""
Step 11 verification: Deterministic request-local index DB built from snapshots only.

Proof:
- build index twice => index.db/index.meta.json/index.sha256 are byte-identical
- query determinism (same results/snippets across runs)
- replay (NLC_REPRO=1) build+query => byte-identical outputs, no network access
- corruption: flip one external source byte => verifier FAIL with external:snapshot_hash_mismatch
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


def die(msg: str, code: int = 2):
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(cmd, env=None, allow_fail: bool = False):
    p = subprocess.run(cmd, cwd=str(BASE), env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if not allow_fail and p.returncode != 0:
        die(f"command failed (exit {p.returncode}): {' '.join(cmd)}\nSTDERR:\n{p.stderr}\nSTDOUT:\n{p.stdout}", p.returncode)
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request-id", default="STEP11-AUDIT")
    ap.add_argument("--external-snapshot-id", default="STEP11-EXT-AUDIT")
    ap.add_argument("--knowledge-snapshot-id", default="")
    ap.add_argument("--policy", default="v1")
    ap.add_argument("--requests-root", help="Requests dir (default: BASE/state/requests)")
    args = ap.parse_args()

    req_id = args.request_id
    ext_id = args.external_snapshot_id
    know_id = (args.knowledge_snapshot_id or os.environ.get("DCS_PROOF_SNAPSHOT_ID") or os.environ.get("AUDIT_CLOSURE_SNAPSHOT") or "").strip()
    if not know_id:
        die("MISSING_SNAPSHOT_ID: set DCS_PROOF_SNAPSHOT_ID or pass --knowledge-snapshot-id")
    policy = args.policy
    req_root = Path(args.requests_root) if args.requests_root else BASE / "state" / "requests"

    # Clean
    req_dir = req_root / req_id
    if req_dir.exists():
        shutil.rmtree(req_dir, ignore_errors=True)
    ext_dir = BASE / "snapshots" / "external" / ext_id
    if ext_dir.exists():
        shutil.rmtree(ext_dir, ignore_errors=True)

    # Create minimal external snapshot (no network)
    from nlc.external_snapshot import write_external_source, try_load_toolchain_pins
    pins = try_load_toolchain_pins()
    write_external_source(
        snapshot_id=ext_id,
        policy_version=policy,
        toolchain_pins=pins,
        source_id="step11://source",
        content_type="text/plain",
        fetch_timestamp="1970-01-01T00:00:00Z",
        raw_bytes=b"obj\nhello from step11\n",
    )

    env = os.environ.copy()
    env["NLC_REQUESTS_ROOT"] = str(req_root)
    env["NLC_POLICY_VERSION"] = policy
    env["NLC_DB_SNAPSHOT_ID"] = know_id
    env["NLC_SNAPSHOT_ID"] = know_id
    env["NLC_KB_SNAPSHOT_ID"] = know_id
    env["NLC_EXTERNAL_SNAPSHOT_ID"] = ext_id
    env["DEV_DB_URL"] = f"sqlite:////tmp/llmhub_step11_{os.getpid()}.db"
    env["NLC_NET_LOG"] = str(req_dir / "NET_LOG.txt")

    # gate0_init
    run(
        [
            sys.executable,
            str(BASE / "orchestrator" / "orchestrator.py"),
            "gate0_init",
            req_id,
                json.dumps("Make a CLI that counts from 1 to 2 by 1"),
            json.dumps([]),
            json.dumps([]),
            json.dumps([]),
        ],
        env=env,
    )

    # Patch payload: CLI --knowledge-snapshot-id is authoritative (must exist in proof kit)
    payload_path = req_dir / "payload.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8", errors="replace"))
    payload["policy_version"] = policy
    payload["knowledge_snapshot_id"] = know_id
    from nlc.reproducibility import get_manifest_hashes
    manifest_info = get_manifest_hashes(know_id)
    if not manifest_info or not manifest_info.get("manifest_bundle_hash"):
        die(f"missing knowledge snapshot manifest bundle hash for {know_id}")
    payload["manifest_bundle_hash"] = manifest_info["manifest_bundle_hash"]
    payload["external_snapshot_id"] = ext_id
    payload["external_sources_required"] = ["step11://source"]
    payload_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Freeze snapshot resolution (Step 10)
    from nlc.snapshot_resolver import write_snapshot_resolution
    write_snapshot_resolution(req_dir)

    # Build index twice and assert byte-identical (db/meta/sha)
    run([sys.executable, str(BASE / "scripts" / "build_index_db.py"), req_id], env=env)
    idx = req_dir / "index"
    db1 = (idx / "index.db").read_bytes()
    meta1 = (idx / "index.meta.json").read_bytes()
    sha1 = (idx / "index.sha256").read_bytes()

    shutil.rmtree(idx, ignore_errors=True)
    run([sys.executable, str(BASE / "scripts" / "build_index_db.py"), req_id], env=env)
    db2 = (idx / "index.db").read_bytes()
    meta2 = (idx / "index.meta.json").read_bytes()
    sha2 = (idx / "index.sha256").read_bytes()

    if db1 != db2:
        die("index.db not byte-identical across builds")
    if meta1 != meta2:
        die("index.meta.json not byte-identical across builds")
    if sha1 != sha2:
        die("index.sha256 not byte-identical across builds")

    # Query determinism (no ad-hoc parsing): use index_query API
    from nlc.index.index_query import open_index, search
    conn = open_index(req_dir)
    try:
        r1 = search(conn, "obj", limit=10)
        r2 = search(conn, "obj", limit=10)
    finally:
        conn.close()
    if r1 != r2:
        die("query results not deterministic across runs")

    # Replay build + query (NLC_REPRO=1) -> byte-identical
    env_repro = env.copy()
    env_repro["DCS_REPRO"] = "1"
    net_log = Path(env_repro["NLC_NET_LOG"])
    if net_log.exists():
        net_log.unlink()

    shutil.rmtree(idx, ignore_errors=True)
    run([sys.executable, str(BASE / "scripts" / "build_index_db.py"), req_id], env=env_repro)
    if (idx / "index.db").read_bytes() != db1:
        die("replay index.db differs from live build")
    if (idx / "index.meta.json").read_bytes() != meta1:
        die("replay index.meta.json differs from live build")
    if (idx / "index.sha256").read_bytes() != sha1:
        die("replay index.sha256 differs from live build")

    conn = open_index(req_dir)
    try:
        rr = search(conn, "obj", limit=10)
    finally:
        conn.close()
    if rr != r1:
        die("replay query results differ from live query")
    if net_log.exists() and net_log.read_text(encoding="utf-8", errors="replace").strip():
        die("network access detected during replay (NLC_NET_LOG not empty)")

    # Forced failure: corrupt external snapshot source bytes -> verifier must FAIL with external:snapshot_hash_mismatch
    manifest = ext_dir / "sources.manifest.json"
    mobj = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
    entries = mobj.get("entries", [])
    ent = None
    for e in entries:
        if isinstance(e, dict) and e.get("source_id") == "step11://source":
            ent = e
            break
    if not ent:
        die("missing step11://source entry in external manifest")
    fn = str(ent.get("filename", "")).strip()
    if not fn:
        die("missing filename in external manifest entry")
    fp = ext_dir / fn
    b = bytearray(fp.read_bytes())
    if not b:
        die("external source bytes empty")
    b[0] = (b[0] + 1) % 256
    fp.write_bytes(bytes(b))

    # Run verifier on gate3 to exercise external snapshot hash check
    run([sys.executable, str(BASE / "workers" / "run_verifier.py"), req_id, str(req_dir), "gate3_execution"], env=env_repro, allow_fail=True)
    failures_path = req_dir / "verifier" / "failures.json"
    fobj = json.loads(failures_path.read_text(encoding="utf-8", errors="replace"))
    failures = fobj.get("failures", [])
    ok = any(isinstance(f, dict) and f.get("kind") == "external_input_violation" and f.get("repro") == "external:snapshot_hash_mismatch" for f in failures)
    if not ok:
        die("expected external:snapshot_hash_mismatch failure after corruption")

    print("✓ Step 11 index DB is deterministic and snapshot-pinned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


