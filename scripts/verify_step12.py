#!/usr/bin/env python3
"""
Step 12 verification: deterministic answering via index queries only.
"""

import argparse
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


def run(cmd, env=None, allow_fail: bool = False):
    p = subprocess.run(cmd, cwd=str(BASE), env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if not allow_fail and p.returncode != 0:
        die(f"command failed (exit {p.returncode}): {' '.join(cmd)}\nSTDERR:\n{p.stderr}\nSTDOUT:\n{p.stdout}", p.returncode)
    return p


def read_failures(req_dir: Path):
    fp = req_dir / "verifier" / "failures.json"
    if not fp.exists():
        return []
    obj = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
    return obj.get("failures", [])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request-id", default="STEP12-AUDIT")
    ap.add_argument("--external-snapshot-id", default="STEP12-EXT-AUDIT")
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

    req_dir = req_root / req_id
    if req_dir.exists():
        shutil.rmtree(req_dir, ignore_errors=True)
    ext_dir = BASE / "snapshots" / "external" / ext_id
    if ext_dir.exists():
        shutil.rmtree(ext_dir, ignore_errors=True)

    # Minimal external snapshot with known token
    from nlc.external_snapshot import write_external_source, try_load_toolchain_pins
    pins = try_load_toolchain_pins()
    write_external_source(
        snapshot_id=ext_id,
        policy_version=policy,
        toolchain_pins=pins,
        source_id="step12://source",
        content_type="text/plain",
        fetch_timestamp="1970-01-01T00:00:00Z",
        raw_bytes=b"fixture_term\n",
    )

    env = os.environ.copy()
    env["NLC_REQUESTS_ROOT"] = str(req_root)
    env["NLC_POLICY_VERSION"] = policy
    env["NLC_DB_SNAPSHOT_ID"] = know_id
    env["NLC_SNAPSHOT_ID"] = know_id
    env["NLC_KB_SNAPSHOT_ID"] = know_id
    env["NLC_EXTERNAL_SNAPSHOT_ID"] = ext_id
    env["DEV_DB_URL"] = f"sqlite:////tmp/llmhub_step12_{os.getpid()}.db"

    # Gate0 init
    run(
        [
            sys.executable,
            str(BASE / "orchestrator" / "orchestrator.py"),
            "gate0_init",
            req_id,
            # Use a known unambiguous objective (must not emit CLARIFY in gate1_planning).
            json.dumps("Make a CLI that counts from 1 to 3 by 1"),
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
    payload["external_sources_required"] = ["step12://source"]
    payload["answer_mode"] = "index_backed"
    payload["answer_queries"] = [{"op": "search", "args": {"q": "fixture_term", "limit": 3}}]
    payload_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Step10 resolution + Step11 index build
    from nlc.snapshot_resolver import write_snapshot_resolution
    write_snapshot_resolution(req_dir)
    run([sys.executable, str(BASE / "scripts" / "build_index_db.py"), req_id], env=env)

    # Run gate1 planning (produces planner/plan.json in answer_mode)
    run([sys.executable, str(BASE / "orchestrator" / "orchestrator.py"), "gate1_planning", req_id], env=env, allow_fail=True)

    # Verifier on gate1 twice must be byte-identical (PASS case)
    run([sys.executable, str(BASE / "workers" / "run_verifier.py"), req_id, str(req_dir), "gate1_planning"], env=env)
    f1 = (req_dir / "verifier" / "failures.json").read_bytes()
    r1 = (req_dir / "verifier" / "verifier.result.json").read_bytes()
    run([sys.executable, str(BASE / "workers" / "run_verifier.py"), req_id, str(req_dir), "gate1_planning"], env=env)
    if (req_dir / "verifier" / "failures.json").read_bytes() != f1:
        die("failures.json not byte-identical across verifier runs")
    if (req_dir / "verifier" / "verifier.result.json").read_bytes() != r1:
        die("verifier.result.json not byte-identical across verifier runs")

    # Forced failures
    plan_path = req_dir / "planner" / "plan.json"
    if not plan_path.exists():
        die("planner/plan.json missing in PASS path")

    # 1) delete plan.json -> planner:plan_missing
    plan_bytes = plan_path.read_bytes()
    plan_path.unlink()
    run([sys.executable, str(BASE / "workers" / "run_verifier.py"), req_id, str(req_dir), "gate1_planning"], env=env, allow_fail=True)
    fails = read_failures(req_dir)
    if not any(isinstance(f, dict) and f.get("kind") == "planner_violation" and f.get("repro") == "planner:plan_missing" for f in fails):
        die("expected planner:plan_missing")
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_bytes(plan_bytes)

    # 2) set index_used=false -> planner:not_index_backed
    obj = json.loads(plan_bytes.decode("utf-8", errors="replace"))
    obj["index_used"] = False
    plan_path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    run([sys.executable, str(BASE / "workers" / "run_verifier.py"), req_id, str(req_dir), "gate1_planning"], env=env, allow_fail=True)
    fails = read_failures(req_dir)
    if not any(isinstance(f, dict) and f.get("kind") == "planner_violation" and f.get("repro") == "planner:not_index_backed" for f in fails):
        die("expected planner:not_index_backed")
    plan_path.write_bytes(plan_bytes)

    # 3) inject snapshots/external/ string -> planner:raw_access_detected
    bad = plan_bytes.decode("utf-8", errors="replace") + "\n\"snapshots/external/\"\n"
    plan_path.write_text(bad, encoding="utf-8")
    run([sys.executable, str(BASE / "workers" / "run_verifier.py"), req_id, str(req_dir), "gate1_planning"], env=env, allow_fail=True)
    fails = read_failures(req_dir)
    if not any(isinstance(f, dict) and f.get("kind") == "planner_violation" and f.get("repro") == "planner:raw_access_detected" for f in fails):
        die("expected planner:raw_access_detected")

    print("✓ Step 12 planner answers via index only and is deterministic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


