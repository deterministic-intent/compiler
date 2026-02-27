#!/usr/bin/env python3
"""
Step 9 verification: External data snapshotting (deterministic inputs).

This script proves:
1) Live fetch + snapshot capture
2) Replay verifier run offline (no network) using snapshot only
3) Verifier conclusions + outputs are byte-identical (failures.json + verifier.result.json)
4) Forced failure: delete a snapshot source -> external_input_violation with correct repro token
5) Forced failure: network access attempt in replay -> external:network_access_detected
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from functools import partial
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


def die(msg: str, code: int = 2):
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        return


FIXED_PORT = 45265


def start_local_server(directory: Path, port: int = FIXED_PORT):
    handler = partial(QuietHandler, directory=str(directory))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port


def run(cmd, env=None, cwd: Path | None = None, allow_fail: bool = False):
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-id", default=os.environ.get("DCS_PROOF_SNAPSHOT_ID", ""), help="Knowledge snapshot (must exist in proof kit)")
    ap.add_argument("--request-id", default="STEP9-AUDIT")
    ap.add_argument("--external-snapshot-id", default="STEP9-EXT-AUDIT", help="External capture storage id (for web_fetch snapshot)")
    ap.add_argument("--policy", default="v1")
    ap.add_argument("--requests-root", help="Requests dir (default: BASE/state/requests)")
    args = ap.parse_args()

    knowledge_snapshot_id = args.snapshot_id or os.environ.get("AUDIT_CLOSURE_SNAPSHOT", "")
    if not knowledge_snapshot_id:
        print("ERROR: --snapshot-id required (or set DCS_PROOF_SNAPSHOT_ID / AUDIT_CLOSURE_SNAPSHOT)", file=sys.stderr)
        sys.exit(2)
    ext_snapshot_id = args.external_snapshot_id
    request_id = args.request_id
    policy_version = args.policy
    req_root = Path(args.requests_root) if args.requests_root else BASE / "state" / "requests"

    # Force all snapshot env vars to CLI value (proof kit only has this snapshot)
    os.environ["NLC_DB_SNAPSHOT_ID"] = knowledge_snapshot_id
    os.environ["NLC_KB_SNAPSHOT_ID"] = knowledge_snapshot_id
    os.environ["NLC_SNAPSHOT_ID"] = knowledge_snapshot_id

    # Clean prior state
    req_dir = req_root / request_id
    if req_dir.exists():
        shutil.rmtree(req_dir, ignore_errors=True)

    ext_dir = BASE / "snapshots" / "external" / ext_snapshot_id
    if ext_dir.exists():
        shutil.rmtree(ext_dir, ignore_errors=True)

    # Local fixture server (no internet) — deterministic port for proof kit
    fixtures_dir = BASE / "scripts" / "e2e" / "fixtures"
    if not fixtures_dir.exists():
        die(f"fixtures dir missing: {fixtures_dir}")
    httpd, port = start_local_server(fixtures_dir)
    fixture_name = "e2e0.json"
    url = f"http://127.0.0.1:{port}/{fixture_name}"

    try:
        # Gate0 init (create request)
        env_live = os.environ.copy()
        env_live["DCS_REPRO"] = "0"  # Capture stage: network allowed for web_fetch
        env_live.pop("NLC_REPRO", None)
        env_live["NLC_REQUESTS_ROOT"] = str(req_root)
        env_live["NLC_POLICY_VERSION"] = policy_version
        env_live["NLC_DB_SNAPSHOT_ID"] = knowledge_snapshot_id
        env_live["NLC_KB_SNAPSHOT_ID"] = knowledge_snapshot_id
        env_live["NLC_SNAPSHOT_ID"] = knowledge_snapshot_id
        env_live["NLC_EXTERNAL_SNAPSHOT_ID"] = ext_snapshot_id
        env_live["DEV_DB_URL"] = f"sqlite:////tmp/llmhub_step9_live_{os.getpid()}.db"

        # orchestrator gate0_init expects JSON-encoded args
        run(
            [
                sys.executable,
                str(BASE / "orchestrator" / "orchestrator.py"),
                "gate0_init",
                request_id,
                json.dumps("Make a CLI that counts from 1 to 2 by 1"),
                json.dumps([]),
                json.dumps([]),
                json.dumps([]),
            ],
            env=env_live,
        )

        # Patch payload.json: CLI --snapshot-id is authoritative (overrides any inherited env/fixture)
        payload_path = req_dir / "payload.json"
        if not payload_path.exists():
            die("payload.json missing after gate0_init")
        payload = json.loads(payload_path.read_text(encoding="utf-8", errors="replace"))
        payload["knowledge_snapshot_id"] = knowledge_snapshot_id
        from nlc.reproducibility import get_manifest_hashes
        manifest_info = get_manifest_hashes(knowledge_snapshot_id)
        if not manifest_info or not manifest_info.get("manifest_bundle_hash"):
            die(f"missing knowledge snapshot manifest bundle hash for {knowledge_snapshot_id}")
        payload["manifest_bundle_hash"] = manifest_info["manifest_bundle_hash"]
        payload["external_snapshot_id"] = ext_snapshot_id
        payload["external_sources_required"] = [url]
        payload_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        # Live fetch + snapshot capture (after fetch, before parsing) via web_fetch boundary.
        # Uses local allowlisted host 127.0.0.1.
        run([sys.executable, str(BASE / "orchestrator" / "web_fetch.py"), request_id, str(req_dir), url], env=env_live)

        # Step 10 dependency: freeze snapshot resolution so verifier can enforce pinning deterministically.
        from nlc.snapshot_resolver import write_snapshot_resolution
        write_snapshot_resolution(req_dir)

        # Verify twice (live mode)
        run([sys.executable, str(BASE / "workers" / "run_verifier.py"), request_id, str(req_dir), "gate3_execution"], env=env_live)
        live_vdir = req_dir / "verifier"
        live_res = live_vdir / "verifier.result.json"
        live_fail = live_vdir / "failures.json"
        if not live_res.exists() or not live_fail.exists():
            die("missing verifier outputs in live run")
        live_res_h1 = sha256_file(live_res)
        live_fail_h1 = sha256_file(live_fail)
        run([sys.executable, str(BASE / "workers" / "run_verifier.py"), request_id, str(req_dir), "gate3_execution"], env=env_live)
        if sha256_file(live_res) != live_res_h1:
            die("live verifier.result.json not byte-identical across runs")
        if sha256_file(live_fail) != live_fail_h1:
            die("live failures.json not byte-identical across runs")
    finally:
        # Always shut server down before replay (no network needed)
        httpd.shutdown()
        httpd.server_close()

    # Replay verifier runs (offline)

    env_replay = env_live.copy()
    env_replay["DCS_REPRO"] = "1"
    env_replay["DEV_DB_URL"] = f"sqlite:////tmp/llmhub_step9_replay_{os.getpid()}.db"
    net_log = req_dir / "NET_LOG.txt"
    if net_log.exists():
        net_log.unlink()
    env_replay["NLC_NET_LOG"] = str(net_log)

    run([sys.executable, str(BASE / "workers" / "run_verifier.py"), request_id, str(req_dir), "gate3_execution"], env=env_replay)
    replay_res_h1 = sha256_file(live_res)
    replay_fail_h1 = sha256_file(live_fail)
    # Replay twice must be byte-identical
    run([sys.executable, str(BASE / "workers" / "run_verifier.py"), request_id, str(req_dir), "gate3_execution"], env=env_replay)
    if sha256_file(live_res) != replay_res_h1:
        die("replay verifier.result.json not byte-identical across runs")
    if sha256_file(live_fail) != replay_fail_h1:
        die("replay failures.json not byte-identical across runs")

    # Replay outputs must match original bytes
    if sha256_file(live_res) != live_res_h1:
        die("replay verifier.result.json differs from original live output bytes")
    if sha256_file(live_fail) != live_fail_h1:
        die("replay failures.json differs from original live output bytes")

    # Forced failure: network access attempt in replay (web_fetch should refuse and log)
    p = run([sys.executable, str(BASE / "orchestrator" / "web_fetch.py"), request_id, str(req_dir), url], env=env_replay, allow_fail=True)
    if p.returncode == 0:
        die("expected web_fetch to fail in replay (NLC_REPRO=1) but it succeeded")
    run([sys.executable, str(BASE / "workers" / "run_verifier.py"), request_id, str(req_dir), "gate3_execution"], env=env_replay, allow_fail=True)
    fail_obj2 = json.loads((req_dir / "verifier" / "failures.json").read_text(encoding="utf-8", errors="replace"))
    failures2 = fail_obj2.get("failures", [])
    ok2 = any(isinstance(f, dict) and f.get("kind") == "external_input_violation" and f.get("repro") == "external:network_access_detected" for f in failures2)
    if not ok2:
        die("missing expected external:network_access_detected failure in replay")

    # Forced failure: delete snapshot source file and assert external:source_missing:<source_id>
    from nlc.external_snapshot import EXTERNAL_ROOT
    snap_dir = EXTERNAL_ROOT / ext_snapshot_id
    manifest = snap_dir / "sources.manifest.json"
    mobj = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
    entries = mobj.get("entries", [])
    if not entries:
        die("external snapshot manifest has no entries")
    target = None
    for e in entries:
        if isinstance(e, dict) and e.get("source_id") == url:
            target = e
            break
    if not target:
        die("did not find expected source_id in manifest")
    fn = str(target.get("filename", "")).strip()
    if not fn:
        die("manifest entry missing filename")
    (snap_dir / fn).unlink(missing_ok=False)

    run([sys.executable, str(BASE / "workers" / "run_verifier.py"), request_id, str(req_dir), "gate3_execution"], env=env_replay, allow_fail=True)
    fail_obj = json.loads((req_dir / "verifier" / "failures.json").read_text(encoding="utf-8", errors="replace"))
    failures = fail_obj.get("failures", [])
    want_repro = f"external:source_missing:{url}"
    ok = any(isinstance(f, dict) and f.get("kind") == "external_input_violation" and f.get("repro") == want_repro for f in failures)
    if not ok:
        die("missing expected external_input_violation failure for deleted source")

    # Clear NET_LOG.txt so verify_network_guard_v1 does not fail on this intentional forced-failure test
    if net_log.exists():
        net_log.unlink()

    print("✓ Step 9 external snapshotting is deterministic and replayable offline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


