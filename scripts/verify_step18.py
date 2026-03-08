#!/usr/bin/env python3
"""
Step 18: Full pipeline E2E harness (proof harness only).

Proves:
- One-time external fetch capture into snapshots/external/<id> (network allowed)
- Full pipeline run (gate0->gate6) using pinned external+knowledge snapshots
- Planner is index-backed and evidence is non-empty and mappable to index DB
- Answer artifact evidence-lock matches planner evidence
- Replay run is network-free and produces byte-identical artifacts
- Negative controls: missing external snapshot, corrupted snapshot blob, missing index DB

On PASS prints exactly one line:
  ✓ Step 18 full pipeline E2E is deterministic and replay-pinned
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        return


def die(msg: str, code: int = 1) -> None:
    sys.stderr.write(f"ERROR: {msg}\n")
    sys.stderr.flush()
    raise SystemExit(code)


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(cmd: list[str], env: dict | None = None, cwd: Path | None = None, allow_fail: bool = False) -> subprocess.CompletedProcess:
    p = subprocess.run(
        cmd,
        cwd=str(cwd or BASE),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    if not allow_fail and p.returncode != 0:
        die(f"command failed (exit {p.returncode}): {' '.join(cmd)}\nSTDERR:\n{p.stderr}\nSTDOUT:\n{p.stdout}", p.returncode)
    return p


def start_local_server(directory: Path) -> tuple[ThreadingHTTPServer, int]:
    handler = partial(QuietHandler, directory=str(directory))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port


def orch_gate0(request_id: str, objective: str, env: dict) -> None:
    run(
        [
            sys.executable,
            str(BASE / "orchestrator" / "orchestrator.py"),
            "gate0_init",
            request_id,
            json.dumps(objective),
            json.dumps([]),
            json.dumps([]),
            json.dumps([]),
        ],
        env=env,
    )


def orch_gate(request_id: str, gate_cmd: str, env: dict, allow_fail: bool = False) -> None:
    run([sys.executable, str(BASE / "orchestrator" / "orchestrator.py"), gate_cmd, request_id], env=env, allow_fail=allow_fail)


def patch_payload(req_dir: Path, *, policy: str, know_id: str, ext_id: str, url: str, answer_q: str) -> None:
    """Patch payload: CLI --knowledge-snapshot-id is authoritative (must exist in proof kit)."""
    payload_path = req_dir / "payload.json"
    if not payload_path.exists():
        die("payload.json missing after gate0_init")
    payload = json.loads(payload_path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(payload, dict):
        die("payload.json must be a JSON object")
    payload["policy_version"] = policy
    payload["knowledge_snapshot_id"] = know_id
    from nlc.reproducibility import get_manifest_hashes
    manifest_info = get_manifest_hashes(know_id)
    if not manifest_info or not manifest_info.get("manifest_bundle_hash"):
        die(f"missing knowledge snapshot manifest bundle hash for {know_id}")
    payload["manifest_bundle_hash"] = manifest_info["manifest_bundle_hash"]
    payload["external_snapshot_id"] = ext_id
    payload["external_sources_required"] = [url]
    payload["answer_mode"] = "index_backed"
    payload["answer_queries"] = [{"op": "search", "args": {"q": answer_q, "limit": 3}}]
    payload_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def require_files(req_dir: Path, rels: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for r in rels:
        p = req_dir / r
        if not p.exists():
            die(f"missing required artifact: {p}")
        out[r] = sha256_file(p)
    return out


def read_json(p: Path) -> dict:
    obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(obj, dict):
        die(f"{p} must be a JSON object")
    return obj


def assert_index_usage(req_dir: Path) -> None:
    plan_path = req_dir / "planner" / "plan.json"
    plan = read_json(plan_path)
    if plan.get("index_used") is not True:
        die("planner/plan.json must indicate index_used=true")
    evidence = plan.get("evidence", [])
    if not isinstance(evidence, list) or not evidence:
        die("planner/plan.json evidence must be non-empty")

    dbp = req_dir / "index" / "index.db"
    conn = sqlite3.connect(str(dbp))
    try:
        for e in evidence:
            if not isinstance(e, dict):
                die("planner evidence entry must be an object")
            doc_id = str(e.get("doc_id", "")).strip()
            source_id = str(e.get("source_id", "")).strip()
            if not doc_id or not source_id:
                die("planner evidence must include doc_id and source_id")
            row = conn.execute("SELECT 1 FROM documents WHERE doc_id=? AND source_id=? LIMIT 1;", (doc_id, source_id)).fetchone()
            if not row:
                die(f"planner evidence does not map to index document: doc_id={doc_id} source_id={source_id}")
    finally:
        conn.close()


def assert_answer_evidence_lock(req_dir: Path) -> None:
    plan = read_json(req_dir / "planner" / "plan.json")
    ans = read_json(req_dir / "answer" / "answer.json")

    pe = plan.get("evidence", [])
    ae = ans.get("evidence", [])
    if not isinstance(pe, list) or not isinstance(ae, list):
        die("planner/answer evidence must be arrays")

    pe_norm = []
    for e in pe:
        if not isinstance(e, dict):
            continue
        pe_norm.append(
            {
                "doc_id": str(e.get("doc_id", "")).strip(),
                "source_id": str(e.get("source_id", "")).strip(),
                "excerpt": str(e.get("excerpt", "") or ""),
                "excerpt_sha256": str(e.get("excerpt_sha256", "")).strip().lower(),
            }
        )
    pe_norm.sort(key=lambda x: (x["doc_id"], x["excerpt_sha256"]))

    ae_norm = []
    for e in ae:
        if not isinstance(e, dict):
            continue
        ae_norm.append(
            {
                "doc_id": str(e.get("doc_id", "")).strip(),
                "source_id": str(e.get("source_id", "")).strip(),
                "excerpt": str(e.get("excerpt", "") or ""),
                "excerpt_sha256": str(e.get("excerpt_sha256", "")).strip().lower(),
            }
        )
    ae_norm.sort(key=lambda x: (x["doc_id"], x["excerpt_sha256"]))

    if pe_norm != ae_norm:
        die("answer evidence does not exactly match planner evidence (lock violated)")


def run_full_pipeline(req_id: str, req_dir: Path, env: dict) -> None:
    # Gate sequence: 0 already run; proceed with 1..6.
    for cmd in ("gate1_planning", "gate2_delegation", "gate3_execution", "gate4_review", "gate5_finalize", "gate6_complete"):
        orch_gate(req_id, cmd, env=env)


def read_failures(req_dir: Path) -> list[dict]:
    fp = req_dir / "verifier" / "failures.json"
    if not fp.exists():
        return []
    obj = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
    fails = obj.get("failures", [])
    return fails if isinstance(fails, list) else []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request-id", default="STEP18-E2E")
    ap.add_argument("--external-snapshot-id", default="STEP18-EXT")
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
    from nlc.external_snapshot import EXTERNAL_ROOT
    ext_dir = EXTERNAL_ROOT / ext_id
    if str(BASE).startswith("/workspace") and str(ext_dir).startswith("/opt/dcs-public"):
        die("CONTAINER_HOST_PATH_FORBIDDEN")

    # A) Clean room
    if req_dir.exists():
        shutil.rmtree(req_dir, ignore_errors=True)
    if ext_dir.exists():
        shutil.rmtree(ext_dir, ignore_errors=True)
    for p in (Path("/tmp/llmhub_step18_live.db"), Path("/tmp/llmhub_step18_replay.db")):
        if p.exists():
            p.unlink()

    # Local fixture server with deterministic content
    temp_root = Path("/tmp/llmhub_step18_server")
    if temp_root.exists():
        shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    token = "fixture_term"
    (temp_root / "doc.txt").write_text(f"{token}\nstep18_token=ALPHA\n", encoding="utf-8")
    httpd, port = start_local_server(temp_root)
    url = f"http://127.0.0.1:{port}/doc.txt"

    # B) Capture mode once (network allowed): gate0 + web_fetch writes external snapshot
    env_live = os.environ.copy()
    # Capture mode: explicitly NOT replay (avoid env-dependent behavior).
    env_live.pop("DCS_REPRO", None)
    env_live.pop("NLC_REPRO", None)
    env_live.pop("NLC_NET_LOG", None)
    env_live.pop("NLC_EXTERNAL_REPLAY", None)
    env_live["NLC_REQUESTS_ROOT"] = str(req_root)
    env_live["NLC_POLICY_VERSION"] = policy
    env_live["NLC_DB_SNAPSHOT_ID"] = know_id
    env_live["NLC_SNAPSHOT_ID"] = know_id
    env_live["NLC_KB_SNAPSHOT_ID"] = know_id
    env_live["NLC_EXTERNAL_SNAPSHOT_ID"] = ext_id
    env_live["DEV_DB_URL"] = "sqlite:////tmp/llmhub_step18_live.db"

    orch_gate0(req_id, "Make a CLI that counts from 1 to 5 by 1", env=env_live)
    patch_payload(req_dir, policy=policy, know_id=know_id, ext_id=ext_id, url=url, answer_q=token)
    run([sys.executable, str(BASE / "orchestrator" / "web_fetch.py"), req_id, str(req_dir), url], env=env_live)

    httpd.shutdown()
    httpd.server_close()

    if not ext_dir.exists():
        die(f"external snapshot dir missing after capture: {ext_dir}")
    if not (ext_dir / "snapshot.meta.json").exists() or not (ext_dir / "sources.manifest.json").exists():
        die("external snapshot meta/manifest missing after capture")

    # C) Full pipeline off captured external snapshot
    run_full_pipeline(req_id, req_dir, env=env_live)

    required = [
        "snapshot_resolution.json",
        "index/index.db",
        "index/index.sha256",
        "planner/plan.json",
        "answer/answer.json",
        "dist/artifact.zip",
        "dist/checksums.sha256",
        "dist/manifest.json",
        "dist/ENTRYPOINT.md",
    ]
    baseline = require_files(req_dir, required)

    # Validate deliverable and sidecar integrity
    run([sys.executable, "-m", "zipfile", "-t", str(req_dir / "dist" / "artifact.zip")])
    run(["sha256sum", "-c", "checksums.sha256"], cwd=req_dir / "dist")

    # D) Prove DB/index usage + evidence lock
    assert_index_usage(req_dir)
    assert_answer_evidence_lock(req_dir)

    # E) Replay determinism proof (network forbidden)
    # Replay uses existing request dir + pinned artifacts; it must not call network.
    net_log = Path("/tmp/llmhub_step18_net.log")
    if net_log.exists():
        net_log.unlink()
    env_replay = env_live.copy()
    env_replay["DCS_REPRO"] = "1"
    env_replay["NLC_NET_LOG"] = str(net_log)
    env_replay["DEV_DB_URL"] = "sqlite:////tmp/llmhub_step18_replay.db"

    # Run replay verifier (Step 7 runner) to enforce pins deterministically.
    replay_cmd = [sys.executable, str(BASE / "scripts" / "run_replay.py"), req_id, "gate3_execution"]
    if args.requests_root:
        replay_cmd.extend(["--requests-root", str(req_root)])
    run(replay_cmd, env=env_replay)

    if net_log.exists() and net_log.read_text(encoding="utf-8", errors="replace").strip():
        die("network access detected in replay (NLC_NET_LOG non-empty)")

    # Assert required artifacts remain byte-identical (replay must not mutate them).
    replay = require_files(req_dir, required)
    for k in sorted(required):
        if baseline[k] != replay[k]:
            die(f"replay artifact not byte-identical: {k} baseline={baseline[k]} replay={replay[k]}")

    # F) Negative controls (isolated request ids)
    # Use non-replay env so gate1 can build snapshot_resolution/index for preconditions.
    env_neg = env_live.copy()

    # F1) Delete external snapshot dir -> external:snapshot_missing
    neg1 = f"{req_id}-NEG1"
    neg1_dir = req_root / neg1
    if neg1_dir.exists():
        shutil.rmtree(neg1_dir, ignore_errors=True)
    orch_gate0(neg1, "Make a CLI that counts from 1 to 5 by 1", env=env_neg)
    patch_payload(neg1_dir, policy=policy, know_id=know_id, ext_id=ext_id, url=url, answer_q=token)
    # Freeze snapshot resolution while external snapshot exists, then delete snapshot dir.
    from nlc.snapshot_resolver import write_snapshot_resolution
    write_snapshot_resolution(neg1_dir)
    shutil.rmtree(ext_dir, ignore_errors=True)
    run([sys.executable, str(BASE / "workers" / "run_verifier.py"), neg1, str(neg1_dir), "gate3_execution"], env=env_neg, allow_fail=True)
    fails = read_failures(neg1_dir)
    want1 = {f"snapshot:explicit_missing:{ext_id}", "external:snapshot_missing"}
    if not any(isinstance(f, dict) and f.get("repro") in want1 for f in fails):
        die(f"negative control F1 missing expected snapshot-missing repro (one of {sorted(want1)})")

    # Recreate external snapshot for remaining negatives (deterministic source writer)
    from nlc.external_snapshot import write_external_source, try_load_toolchain_pins
    pins = try_load_toolchain_pins()
    write_external_source(
        snapshot_id=ext_id,
        policy_version=policy,
        toolchain_pins=pins,
        source_id=url,
        content_type="text/plain",
        fetch_timestamp="1970-01-01T00:00:00Z",
        raw_bytes=b"fixture_term\nstep18_token=ALPHA\n",
    )

    # F2) Corrupt 1 byte in external snapshot blob -> external:snapshot_hash_mismatch
    # Pick first entry filename from manifest and flip a byte.
    mobj = json.loads((ext_dir / "sources.manifest.json").read_text(encoding="utf-8", errors="replace"))
    entries = mobj.get("entries", []) if isinstance(mobj, dict) else []
    if not entries:
        die("external sources.manifest.json has no entries")
    fn = str(entries[0].get("filename", "")).strip()
    if not fn:
        die("external manifest entry missing filename")
    fp = ext_dir / fn
    b = bytearray(fp.read_bytes())
    if not b:
        die("external source file empty (cannot corrupt)")
    b[0] = (b[0] + 1) % 256
    fp.write_bytes(bytes(b))
    neg2 = f"{req_id}-NEG2"
    neg2_dir = req_root / neg2
    if neg2_dir.exists():
        shutil.rmtree(neg2_dir, ignore_errors=True)
    orch_gate0(neg2, "Make a CLI that counts from 1 to 5 by 1", env=env_neg)
    patch_payload(neg2_dir, policy=policy, know_id=know_id, ext_id=ext_id, url=url, answer_q=token)
    write_snapshot_resolution(neg2_dir)
    run([sys.executable, str(BASE / "workers" / "run_verifier.py"), neg2, str(neg2_dir), "gate3_execution"], env=env_neg, allow_fail=True)
    fails = read_failures(neg2_dir)
    if not any(isinstance(f, dict) and f.get("repro") == "external:snapshot_hash_mismatch" for f in fails):
        die("negative control F2 missing expected failure repro external:snapshot_hash_mismatch")

    # Restore external snapshot back to valid bytes for remaining negative control
    shutil.rmtree(ext_dir, ignore_errors=True)
    write_external_source(
        snapshot_id=ext_id,
        policy_version=policy,
        toolchain_pins=pins,
        source_id=url,
        content_type="text/plain",
        fetch_timestamp="1970-01-01T00:00:00Z",
        raw_bytes=b"fixture_term\nstep18_token=ALPHA\n",
    )

    # F3) Delete index/index.db before verifier -> index:missing
    neg3 = f"{req_id}-NEG3"
    neg3_dir = req_root / neg3
    if neg3_dir.exists():
        shutil.rmtree(neg3_dir, ignore_errors=True)
    orch_gate0(neg3, "Make a CLI that counts from 1 to 5 by 1", env=env_neg)
    patch_payload(neg3_dir, policy=policy, know_id=know_id, ext_id=ext_id, url=url, answer_q=token)
    # Build snapshot_resolution + index via gate1 (deterministic).
    orch_gate(neg3, "gate1_planning", env=env_neg)
    dbp = neg3_dir / "index" / "index.db"
    if not dbp.exists():
        die("precondition for F3 failed: index/index.db not present after gate1_planning")
    dbp.unlink()
    run([sys.executable, str(BASE / "workers" / "run_verifier.py"), neg3, str(neg3_dir), "gate3_execution"], env=env_neg, allow_fail=True)
    fails = read_failures(neg3_dir)
    if not any(isinstance(f, dict) and f.get("repro") == "index:missing" for f in fails):
        die("negative control F3 missing expected failure repro index:missing")

    sys.stdout.write("✓ Step 18 full pipeline E2E is deterministic and replay-pinned\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


