#!/usr/bin/env python3
"""
Step 13 verification: deterministic answer artifact + evidence lock.
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
    ap.add_argument("--request-id", default="STEP13-AUDIT")
    ap.add_argument("--external-snapshot-id", default="STEP13-EXT-AUDIT")
    ap.add_argument("--knowledge-snapshot-id", default=os.environ.get("DCS_PROOF_SNAPSHOT_ID", "20260103T060637Z"))
    ap.add_argument("--policy", default="v1")
    ap.add_argument("--requests-root", help="Requests dir (default: BASE/state/requests)")
    args = ap.parse_args()

    req_id = args.request_id
    ext_id = args.external_snapshot_id
    know_id = args.knowledge_snapshot_id or os.environ.get("AUDIT_CLOSURE_SNAPSHOT", "20260103T060637Z")
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
        source_id="step13://source",
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
    env["DEV_DB_URL"] = f"sqlite:////tmp/llmhub_step13_{os.getpid()}.db"

    # Gate0 init with unambiguous objective (must not CLARIFY).
    run(
        [
            sys.executable,
            str(BASE / "orchestrator" / "orchestrator.py"),
            "gate0_init",
            req_id,
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
    payload["external_sources_required"] = ["step13://source"]
    payload["answer_mode"] = "index_backed"
    payload["answer_queries"] = [{"op": "search", "args": {"q": "fixture_term", "limit": 3}}]
    payload_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Step10 resolution + Step11 index build
    from nlc.snapshot_resolver import write_snapshot_resolution

    write_snapshot_resolution(req_dir)
    run([sys.executable, str(BASE / "scripts" / "build_index_db.py"), req_id], env=env)

    # Run planning (must also build answer/answer.json via Step 13 wiring)
    run([sys.executable, str(BASE / "orchestrator" / "orchestrator.py"), "gate1_planning", req_id], env=env, allow_fail=True)
    answer_path = req_dir / "answer" / "answer.json"
    if not answer_path.exists():
        die("answer/answer.json missing after planning")
    answer_bytes_before = answer_path.read_bytes()

    # Verifier twice, must PASS both times and answer.json bytes stable
    p1 = run([sys.executable, str(BASE / "workers" / "run_verifier.py"), req_id, str(req_dir), "gate1_planning"], env=env)
    f1 = (req_dir / "verifier" / "failures.json").read_bytes()
    r1 = (req_dir / "verifier" / "verifier.result.json").read_bytes()
    if (req_dir / "verifier" / "verifier.result.json").read_text(encoding="utf-8", errors="replace").find('"status": "PASS"') == -1:
        die("expected verifier PASS (run 1)")
    if answer_path.read_bytes() != answer_bytes_before:
        die("answer.json bytes changed after verifier run 1")

    p2 = run([sys.executable, str(BASE / "workers" / "run_verifier.py"), req_id, str(req_dir), "gate1_planning"], env=env)
    if (req_dir / "verifier" / "failures.json").read_bytes() != f1:
        die("failures.json not byte-identical across verifier runs")
    if (req_dir / "verifier" / "verifier.result.json").read_bytes() != r1:
        die("verifier.result.json not byte-identical across verifier runs")
    if (req_dir / "verifier" / "verifier.result.json").read_text(encoding="utf-8", errors="replace").find('"status": "PASS"') == -1:
        die("expected verifier PASS (run 2)")
    if answer_path.read_bytes() != answer_bytes_before:
        die("answer.json bytes changed after verifier run 2")

    # Forced failure 1: corrupt answer_sha256 -> answer:sha_mismatch
    good = json.loads(answer_bytes_before.decode("utf-8", errors="replace"))
    bad = dict(good)
    bad["answer_sha256"] = "0" * 64
    answer_path.write_text(json.dumps(bad, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    run([sys.executable, str(BASE / "workers" / "run_verifier.py"), req_id, str(req_dir), "gate1_planning"], env=env, allow_fail=True)
    fails = read_failures(req_dir)
    if not any(isinstance(f, dict) and f.get("kind") == "answer_violation" and f.get("repro") == "answer:sha_mismatch" for f in fails):
        die("expected answer:sha_mismatch")

    # Forced failure 2: delete answer.json -> answer:missing
    answer_path.unlink()
    run([sys.executable, str(BASE / "workers" / "run_verifier.py"), req_id, str(req_dir), "gate1_planning"], env=env, allow_fail=True)
    fails = read_failures(req_dir)
    if not any(isinstance(f, dict) and f.get("kind") == "answer_violation" and f.get("repro") == "answer:missing" for f in fails):
        die("expected answer:missing")

    # Restore good answer
    answer_path.parent.mkdir(parents=True, exist_ok=True)
    answer_path.write_bytes(answer_bytes_before)

    # Forced failure 3: modify evidence excerpt but keep excerpt sha consistent -> answer:evidence_mismatch
    good2 = json.loads(answer_bytes_before.decode("utf-8", errors="replace"))
    ev = good2.get("evidence", [])
    if not isinstance(ev, list) or not ev:
        die("expected non-empty evidence list in answer.json")
    if not isinstance(ev[0], dict):
        die("expected dict evidence entry")
    ev0 = dict(ev[0])
    ev0["excerpt"] = (str(ev0.get("excerpt", "")) + "X")
    ev0["excerpt_sha256"] = hashlib.sha256(ev0["excerpt"].encode("utf-8")).hexdigest()
    ev[0] = ev0
    good2["evidence"] = ev
    # Keep bundle sha consistent with modified evidence to avoid sha mismatch token
    evidence_canon = json.dumps(ev, indent=2, sort_keys=True) + "\n"
    good2["evidence_bundle_sha256"] = hashlib.sha256(evidence_canon.encode("utf-8")).hexdigest()
    # Recompute answer and its sha to avoid sha mismatch token
    good2["answer"] = "\n\n".join([str(e.get("excerpt", "") or "") for e in ev])
    good2["answer_sha256"] = hashlib.sha256(good2["answer"].encode("utf-8")).hexdigest()
    answer_path.write_text(json.dumps(good2, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    run([sys.executable, str(BASE / "workers" / "run_verifier.py"), req_id, str(req_dir), "gate1_planning"], env=env, allow_fail=True)
    fails = read_failures(req_dir)
    if not any(isinstance(f, dict) and f.get("kind") == "answer_violation" and f.get("repro") == "answer:evidence_mismatch" for f in fails):
        die("expected answer:evidence_mismatch")

    print("✓ Step 13 answer artifact is deterministic and evidence-locked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


