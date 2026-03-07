#!/usr/bin/env python3
"""
Milestone 4.2: Single-User Acceptance Suite Harness.

Runs as a user would:
- dcs compile
- dcs run
- dcs inspect
- dcs replay

Asserts:
- artifact exists
- runtime validation exists + PASS/FAIL as expected
- replay byte-identical
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


def _run(cmd: list[str], *, env: dict[str, str] | None = None, allow_fail: bool = False) -> subprocess.CompletedProcess:
    p = subprocess.run(
        cmd,
        cwd=str(BASE),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    if p.returncode != 0 and not allow_fail:
        sys.stdout.write((p.stdout or "") + (p.stderr or ""))
        sys.stdout.flush()
        raise SystemExit(p.returncode or 2)
    return p


def _read_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8", errors="replace"))


def main() -> int:
    env = os.environ.copy()
    env["NLC_POLICY_VERSION"] = "v1"
    env.setdefault("NLC_DB_SNAPSHOT_ID", os.environ.get("DCS_PROOF_SNAPSHOT_ID") or os.environ.get("AUDIT_CLOSURE_SNAPSHOT") or "")
    env.setdefault("NLC_SNAPSHOT_ID", env["NLC_DB_SNAPSHOT_ID"])
    env.setdefault("NLC_KB_SNAPSHOT_ID", env["NLC_DB_SNAPSHOT_ID"])
    
    # Load acceptance suite
    suite_path = BASE / "suites" / "acceptance" / "single_user_v1.json"
    if not suite_path.exists():
        sys.stdout.write(f"ERROR: Suite not found: {suite_path}\n")
        sys.stdout.flush()
        return 1
    
    suite = _read_json(suite_path)
    cases = suite.get("cases", [])
    
    dcs_bin = BASE / "scripts" / "bin" / "dcs"
    
    for case in cases:
        case_id = case.get("case_id", "unknown")
        request_text = case.get("request_text", "")
        expected_status = case.get("expected_status", "PASS")
        expected_runtime_status = case.get("expected_runtime_status", "PASS")
        replay_proof = case.get("replay_proof", False)
        
        sys.stdout.write(f"\n=== {case_id} ===\n")
        sys.stdout.flush()
        
        # Step 1: dcs compile
        compile_cmd = [str(dcs_bin), "compile", request_text]
        compile_result = _run(compile_cmd, env=env, allow_fail=True)
        if compile_result.returncode != 0:
            sys.stdout.write(f"FAIL: dcs compile failed for {case_id}\n")
            sys.stdout.flush()
            return 1
        
        # Find the generated .dcs file (last line of compile output should have path)
        compile_output = compile_result.stdout.strip()
        dcs_file = None
        for line in reversed(compile_output.splitlines()):
            if line.strip().endswith(".dcs"):
                dcs_file = Path(line.strip())
                break
        
        if not dcs_file or not dcs_file.exists():
            sys.stdout.write(f"FAIL: No .dcs file generated for {case_id}\n")
            sys.stdout.flush()
            return 1
        
        # Step 2: dcs run
        run_cmd = [str(dcs_bin), "run", str(dcs_file), "--no-banner", "--no-color"]
        run_result = _run(run_cmd, env=env, allow_fail=True)
        
        # Extract request_id from run output or .dcs file
        dcs_content = _read_json(dcs_file)
        request_id = dcs_content.get("request_id", case_id.replace("-", "_").upper())
        request_dir = BASE / "state" / "requests" / request_id
        
        if not request_dir.exists():
            sys.stdout.write(f"FAIL: Request dir not found: {request_dir}\n")
            sys.stdout.flush()
            return 1
        
        # Step 3: Check artifact exists
        dist_dir = request_dir / "dist"
        if not dist_dir.exists():
            sys.stdout.write(f"FAIL: dist/ not found for {case_id}\n")
            sys.stdout.flush()
            return 1
        
        # Step 4: Check runtime validation exists
        runtime_dir = request_dir / "validation" / "runtime"
        if not runtime_dir.exists():
            sys.stdout.write(f"FAIL: validation/runtime/ not found for {case_id}\n")
            sys.stdout.flush()
            return 1
        
        # Check required runtime artifacts
        required_files = ["commands.json", "stdout.txt", "stderr.txt", "stdout.sha256", "stderr.sha256", "exit_code.json", "result.json"]
        for fname in required_files:
            if not (runtime_dir / fname).exists():
                sys.stdout.write(f"FAIL: validation/runtime/{fname} missing for {case_id}\n")
                sys.stdout.flush()
                return 1
        
        # Step 5: Check runtime status
        runtime_result = _read_json(runtime_dir / "result.json")
        runtime_status = runtime_result.get("status", "UNKNOWN")
        if runtime_status != expected_runtime_status:
            sys.stdout.write(f"FAIL: Expected runtime status {expected_runtime_status}, got {runtime_status} for {case_id}\n")
            sys.stdout.flush()
            return 1
        
        # Step 6: Replay proof (if requested)
        if replay_proof:
            replay_cmd = [str(dcs_bin), "replay", request_id, "gate4_review", "--no-banner", "--no-color"]
            env_replay = env.copy()
            env_replay["DCS_REPRO"] = "1"
            replay_result = _run(replay_cmd, env=env_replay, allow_fail=True)
            
            if replay_result.returncode != 0:
                sys.stdout.write(f"FAIL: Replay failed for {case_id}\n")
                sys.stdout.flush()
                return 1
            
            # Check replay runtime artifacts are byte-identical
            replay_runtime_dir = request_dir / "replay" / "replay1" / "validation" / "runtime"
            if replay_runtime_dir.exists():
                original_stdout = (runtime_dir / "stdout.txt").read_bytes()
                replay_stdout = (replay_runtime_dir / "stdout.txt").read_bytes()
                if original_stdout != replay_stdout:
                    sys.stdout.write(f"FAIL: Replay stdout not byte-identical for {case_id}\n")
                    sys.stdout.flush()
                    return 1
        
        sys.stdout.write(f"PASS: {case_id}\n")
        sys.stdout.flush()
    
    sys.stdout.write("\n✓ All acceptance cases passed\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

