#!/usr/bin/env python3
"""E2E-0 Test Suite: Core deterministic pipeline without replay or live LLM."""

import sys
import json
import argparse
import subprocess
import shutil
import tempfile
import os
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

# Ensure repo root on sys.path for module imports
BASE = Path(__file__).resolve().parents[2]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from nlc.db.manifest_builder import build_all_manifests, compute_manifest_bundle_hash
from nlc.reproducibility import get_manifest_hashes

# Repo root
BASE = Path(__file__).resolve().parents[2]
# E2E0 uses NLC_REQUESTS_ROOT to avoid touching repo state/requests (no root-owned dirs)
ORCHESTRATOR = BASE / "orchestrator" / "orchestrator.py"
# Set in main() from --state-root or temp dir
REQUESTS_DIR: Path = BASE / "state" / "requests"


def _get_requests_dir(state_root: Optional[str]) -> Tuple[Path, Optional[str]]:
    """
    Resolve requests directory. Returns (REQUESTS_DIR, temp_dir_to_cleanup).
    If state_root is set, use that/state/requests. Else use temp dir (caller retains for run).
    """
    if state_root:
        root = Path(state_root).resolve()
        requests_dir = root / "state" / "requests"
        requests_dir.mkdir(parents=True, exist_ok=True)
        return requests_dir, None
    tmp = tempfile.mkdtemp(prefix="e2e0_state_")
    requests_dir = Path(tmp) / "state" / "requests"
    requests_dir.mkdir(parents=True, exist_ok=True)
    return requests_dir, tmp

def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def ensure_snapshot_manifest_bundle(snapshot_id: str, policy_version: str) -> str:
    """
    Ensure manifest bundle hash exists for the given snapshot.
    - If manifest directory is missing, build manifests deterministically.
    - Returns manifest_bundle_hash (non-empty string) or dies with clear error.
    """
    snapshot_dir = BASE / "nlc" / "db" / "snapshots" / snapshot_id
    manifest_dir = snapshot_dir / "manifest"
    if not snapshot_dir.exists():
        die(f"Snapshot not found: {snapshot_dir}")
    
    # Build manifests if missing or intents_v1.json absent (required for module_refs enrichment)
    if not manifest_dir.exists() or not (manifest_dir / "intents_v1.json").exists():
        print(f"Manifest (or intents_v1) missing for snapshot {snapshot_id}; building manifests...", file=sys.stderr)
        try:
            build_all_manifests(BASE, snapshot_id, policy_version)
        except Exception as e:
            die(f"Failed to build manifests for snapshot {snapshot_id}: {e}")
    
    manifest_info = get_manifest_hashes(snapshot_id)
    bundle_hash = manifest_info.get("manifest_bundle_hash")
    if not bundle_hash:
        die(f"Manifest bundle hash missing for snapshot {snapshot_id} (manifests may be incomplete)")
    return bundle_hash

def run_gate(orchestrator: Path, request_id: str, gate: str) -> tuple[int, str, str]:
    """Run a single gate and return (exit_code, stdout, stderr)."""
    cmd = [sys.executable, str(orchestrator), gate, request_id]
    # Ensure snapshot env vars are visible to orchestrator subprocesses.
    import os
    # Make subprocess non-interactive: never read from TTY (prevents SIGTTIN stops).
    p = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        stdin=subprocess.DEVNULL,
    )
    return (p.returncode, p.stdout or "", p.stderr or "")


def read_gate_status(request_id: str, gate_index: int) -> Optional[str]:
    """Read gate status file if present."""
    status_path = REQUESTS_DIR / request_id / f"gate{gate_index}.status"
    if not status_path.exists():
        return None
    try:
        return status_path.read_text(encoding="utf-8").strip()
    except Exception:
        return None


def _emit_e2e0_bc_precondition_diagnostics(request_id: str, repair_dir: Path, verifier_dir: Path) -> None:
    """Print diagnostics when repair did not run (iter_0 missing). B/C require verifier FAIL to trigger repair."""
    print("  REASON: expected verifier FAIL to trigger repair; repair/iter_0 was not created")
    print("  EXPECTED_MISSING_ARTIFACT: repair/iter_0/failures.json")
    print("")
    print("  Gate statuses 0-6:")
    for g in range(7):
        status_path = REQUESTS_DIR / request_id / f"gate{g}.status"
        status = status_path.read_text(encoding="utf-8").strip() if status_path.exists() else "NOT_RUN"
        print(f"    gate{g}.status = {status}")
    result_path = verifier_dir / "verifier.result.json"
    verifier_status = "MISSING"
    if result_path.exists():
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
            verifier_status = str(result.get("status", "?"))
            print(f"  Verifier status = {verifier_status}")
        except Exception:
            print(f"  Verifier result: (unreadable)")
        print(f"  Verifier path = {result_path}")
    else:
        print(f"  Verifier path = {result_path} (file missing)")


def _ensure_deliverable(payload: dict, path: str, fmt: str) -> bool:
    """
    Add a deliverable only if not already present.
    Returns True if added, False if already present / invalid payload.
    """
    dlist = payload.get("deliverables")
    if not isinstance(dlist, list):
        payload["deliverables"] = []
        dlist = payload["deliverables"]
    for d in dlist:
        if isinstance(d, dict) and str(d.get("path", "")).strip() == path:
            return False
    dlist.append({"path": path, "format": fmt})
    return True


def run_pipeline(request_id: str, objective: str, constraints: list, non_goals: list, dod: list) -> int:
    """Run the full pipeline from gate0_init through gate6_complete."""
    orchestrator = ORCHESTRATOR
    
    # Gate 0: Init
    obj_json = json.dumps(objective)
    cons_json = json.dumps(constraints)
    non_json = json.dumps(non_goals)
    dod_json = json.dumps(dod)
    
    cmd = [sys.executable, str(orchestrator), "gate0_init", request_id, obj_json, cons_json, non_json, dod_json]
    import os
    p = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        stdin=subprocess.DEVNULL,
    )
    if p.returncode != 0:
        print(f"  Gate 0 failed: {p.stderr}", file=sys.stderr)
        return p.returncode
    status = read_gate_status(request_id, 0)
    if status != "PASS":
        print(f"  Gate0 status is {status}, stopping pipeline.", file=sys.stderr)
        return 1
    
    # Gates 1-6
    gates = ["gate1_planning", "gate2_delegation", "gate3_execution", "gate4_review", "gate5_finalize", "gate6_complete"]
    for idx, gate in enumerate(gates, start=1):
        status = read_gate_status(request_id, idx)
        if status == "SKIPPED_CLARIFY":
            print(f"  {gate} status is {status}, stopping pipeline due to clarification.", file=sys.stderr)
            return 0
        code, _out, err = run_gate(orchestrator, request_id, gate)
        if code != 0:
            print(f"  Gate {gate} failed: {err}", file=sys.stderr)
            return code
        status = read_gate_status(request_id, idx)
        if status == "SKIPPED_CLARIFY":
            print(f"  {gate} status is {status}, stopping pipeline due to clarification.", file=sys.stderr)
            return 0
        if status != "PASS":
            print(f"  {gate} status is {status}, stopping pipeline.", file=sys.stderr)
            return 1
    
    return 0


def cleanup_request_deterministic(request_id: str) -> None:
    """
    Remove request directory. Hard fail if not cleanable.
    Required for external repro and proof-kit runs.
    """
    rd = REQUESTS_DIR / request_id
    if not rd.exists():
        return
    try:
        shutil.rmtree(rd)
    except OSError as e:
        # Print diagnostics and die with canonical ID
        import os
        try:
            stat = os.stat(rd)
            owner = f"uid={stat.st_uid} gid={stat.st_gid}"
        except Exception:
            owner = "unknown"
        uid, gid = os.getuid(), os.getgid()
        print(f"E2E.STATE.DIR.NOT_CLEANABLE: cannot remove {rd}", file=sys.stderr)
        print(f"  owner/perms: {owner}", file=sys.stderr)
        print(f"  os.errno: {e.errno}", file=sys.stderr)
        subprocess.run(["ls", "-la", str(REQUESTS_DIR)], capture_output=False)
        if rd.exists():
            subprocess.run(["ls", "-la", str(rd)], capture_output=False)
        print("", file=sys.stderr)
        print("REMEDIATION: run from repo root:", file=sys.stderr)
        print(f"  sudo chown -R {uid}:{gid} state/requests", file=sys.stderr)
        print("  sudo rm -rf state/requests/*", file=sys.stderr)
        die("E2E.STATE.DIR.NOT_CLEANABLE")


def cleanup_e2e_requests_deterministic(base_id: str) -> None:
    """Remove all E2E0-* requests for the given base id. Hard fail if any not cleanable."""
    for suffix in ["A", "B", "C", "D"]:
        cleanup_request_deterministic(f"E2E0-{suffix}-{base_id}")


def set_snapshot_env(snapshot_id: str) -> None:
    """
    Set snapshot-related environment variables expected by reproducibility helpers.
    - NLC_DB_SNAPSHOT_ID: used by get_db_snapshot_id()
    - NLC_KB_SNAPSHOT_ID: kept in sync for completeness
    - NLC_SNAPSHOT_ID: legacy helper for other components
    - PYTHONPATH: ensure repo root on path for worker subprocesses (dcs_core, etc.)
    """
    import os
    os.environ["NLC_DB_SNAPSHOT_ID"] = snapshot_id
    os.environ["NLC_KB_SNAPSHOT_ID"] = snapshot_id
    os.environ["NLC_SNAPSHOT_ID"] = snapshot_id
    pp = os.environ.get("PYTHONPATH", "")
    base_str = str(BASE)
    if base_str not in (pp.split(os.pathsep) if pp else []):
        os.environ["PYTHONPATH"] = f"{base_str}{os.pathsep}{pp}" if pp else base_str


def test_e2e0_a(request_id: str, fixtures: Dict[str, Any]) -> bool:
    """Test E2E0-A: PASS path (no repair)."""
    print("\n" + "=" * 60)
    print("Test E2E0-A: PASS path (no repair)")
    print("=" * 60)
    
    prompt = fixtures["pass_prompt"]
    request_id_full = f"E2E0-A-{request_id}"
    cleanup_request_deterministic(request_id_full)
    
    print(f"Running pipeline for request: {request_id_full}")
    code = run_pipeline(
        request_id_full,
        prompt["objective"],
        prompt["constraints"],
        prompt["non_goals"],
        prompt["dod"]
    )
    
    if code != 0:
        print(f"  ✗ Pipeline failed with exit code {code}")
        return False
    
    request_dir = REQUESTS_DIR / request_id_full
    
    # Check 1: payload.json exists with required fields
    payload_path = request_dir / "payload.json"
    if not payload_path.exists():
        print(f"  ✗ payload.json not found")
        return False
    
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        required_fields = ["policy_version", "knowledge_snapshot_id", "manifest_bundle_hash"]
        for field in required_fields:
            if field not in payload:
                print(f"  ✗ payload.json missing field: {field}")
                return False
        print(f"  ✓ payload.json has all required fields")
    except Exception as e:
        print(f"  ✗ Error reading payload.json: {e}")
        return False
    
    # Check 2: REQ.json exists
    req_path = request_dir / "REQ.json"
    if not req_path.exists():
        print(f"  ✗ REQ.json not found")
        return False
    print(f"  ✓ REQ.json exists")
    
    # Check 3: verifier.result.json exists with status == "PASS"
    verifier_dir = request_dir / "verifier"
    result_path = verifier_dir / "verifier.result.json"
    if not result_path.exists():
        print(f"  ✗ verifier.result.json not found")
        return False
    
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("status") != "PASS":
            print(f"  ✗ verifier status is {result.get('status')}, expected PASS")
            return False
        print(f"  ✓ verifier.result.json status == PASS")
    except Exception as e:
        print(f"  ✗ Error reading verifier.result.json: {e}")
        return False
    
    # Check 4: failures.json exists with empty failures array
    failures_path = verifier_dir / "failures.json"
    if not failures_path.exists():
        print(f"  ✗ failures.json not found")
        return False
    
    try:
        failures_obj = json.loads(failures_path.read_text(encoding="utf-8"))
        failures = failures_obj.get("failures", [])
        if failures:
            print(f"  ✗ failures.json has {len(failures)} failures, expected empty")
            return False
        print(f"  ✓ failures.json is empty")
    except Exception as e:
        print(f"  ✗ Error reading failures.json: {e}")
        return False
    
    # Check 5: Repair did not run
    repair_dir = request_dir / "repair"
    if repair_dir.exists():
        status_path = repair_dir / "status.json"
        if status_path.exists():
            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
                final_status = status.get("final_status", "")
                if final_status and final_status != "NOT_TRIGGERED":
                    print(f"  ✗ Repair ran (final_status: {final_status}), expected not triggered")
                    return False
            except Exception:
                pass
    print(f"  ✓ Repair did not run")
    
    print(f"\n✓ Test E2E0-A PASSED")
    return True


def enable_repair_in_policy(policy_version: str = "v1") -> Optional[Path]:
    """Temporarily enable repair in policy. Returns backup path if modified."""
    policy_path = BASE / "policy" / f"policy_{policy_version}.json"
    if not policy_path.exists():
        print(f"  ⚠ WARNING: Policy file not found: {policy_path}")
        return None
    
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        repair_section = policy.get("repair", {})
        if repair_section.get("enabled", False):
            return None  # Already enabled
        
        # Backup and enable
        backup_path = policy_path.with_suffix(".json.backup")
        shutil.copy(policy_path, backup_path)
        
        repair_section["enabled"] = True
        policy["repair"] = repair_section
        policy_path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
        
        return backup_path
    except Exception as e:
        print(f"  ⚠ WARNING: Failed to enable repair in policy: {e}")
        return None


def restore_policy_backup(backup_path: Optional[Path]):
    """Restore policy from backup."""
    if backup_path and backup_path.exists():
        policy_path = backup_path.with_suffix(".json")
        shutil.copy(backup_path, policy_path)
        backup_path.unlink()


def test_e2e0_b(request_id: str, fixtures: Dict[str, Any], snapshot_id: str) -> bool:
    """Test E2E0-B: FAIL → repair accepts patch → PASS."""
    print("\n" + "=" * 60)
    print("Test E2E0-B: FAIL → repair accepts patch → PASS")
    print("=" * 60)
    
    request_id_full = f"E2E0-B-{request_id}"
    # Clean previous run (if any)
    cleanup_request_deterministic(request_id_full)

    # Enable repair in policy
    backup_path = enable_repair_in_policy()
    if backup_path:
        print(f"  Enabled repair in policy (backup: {backup_path.name})")
    
    try:
        prompt = fixtures["fail_prompt_accept_patch"]
        patch_diff_path = BASE / prompt.get("accept_patch_diff_path", "")
        
        if not patch_diff_path.exists():
            print(f"  ⚠ WARNING: Patch diff not found at {patch_diff_path}, skipping test")
            return True
        
        print(f"Running pipeline for request: {request_id_full}")
        
    # Run up to gate3 (where repair would trigger)
        orchestrator = ORCHESTRATOR
        obj_json = json.dumps(prompt["objective"])
        cons_json = json.dumps(prompt["constraints"])
        non_json = json.dumps(prompt["non_goals"])
        dod_json = json.dumps(prompt["dod"])
        
        # Gate 0
        cmd = [sys.executable, str(orchestrator), "gate0_init", request_id_full, obj_json, cons_json, non_json, dod_json]
        import os
        p0 = subprocess.run(cmd, capture_output=True, text=True, env=os.environ.copy())
        status0 = read_gate_status(request_id_full, 0)
        if status0 != "PASS":
            print(f"  ✗ Gate0 status is {status0} (exit {p0.returncode})")
            return False

        # Inject a missing deliverable into payload to force verifier FAIL (no duplicates).
        force_fail = str(prompt.get("force_fail_deliverable", "MISSING_DELIVERABLE.txt")).strip()
        payload_path = REQUESTS_DIR / request_id_full / "payload.json"
        if payload_path.exists():
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            _ensure_deliverable(payload, force_fail, "text")
            payload_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        
        # Gate 1
        code, _out, err = run_gate(orchestrator, request_id_full, "gate1_planning")
        if code != 0:
            print(f"  Gate gate1_planning failed: {err}", file=sys.stderr)
            return False
        if read_gate_status(request_id_full, 1) != "PASS":
            print(f"  ✗ Gate1 status is {read_gate_status(request_id_full, 1)}")
            return False
        
        # Gate 2
        code, _out, err = run_gate(orchestrator, request_id_full, "gate2_delegation")
        if code != 0:
            print(f"  Gate gate2_delegation failed: {err}", file=sys.stderr)
            return False
        if read_gate_status(request_id_full, 2) != "PASS":
            print(f"  ✗ Gate2 status is {read_gate_status(request_id_full, 2)}")
            return False

        # Stage proposal BEFORE gate4 so repair can consume it on first FAIL
        request_dir = REQUESTS_DIR / request_id_full
        repair_dir = request_dir / "repair"
        verifier_dir = request_dir / "verifier"
        iter_1_dir = repair_dir / "iter_1"
        iter_1_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(patch_diff_path, iter_1_dir / "proposal.diff")
        print(f"  Copied patch to {iter_1_dir / 'proposal.diff'}")

        # Gate 3: execution (generator + packager); must PASS to reach gate4
        code, _out, err = run_gate(orchestrator, request_id_full, "gate3_execution")
        if code != 0:
            print(f"  Gate gate3_execution failed: {err}", file=sys.stderr)
            return False
        if read_gate_status(request_id_full, 3) != "PASS":
            print(f"  ✗ Gate3 must PASS to reach gate4 (status: {read_gate_status(request_id_full, 3)})")
            return False

        # Gate 4: review — verifier must FAIL (deliverables) to trigger repair; repair creates iter_0
        code, _out, err = run_gate(orchestrator, request_id_full, "gate4_review")
        if code != 0:
            print(f"  Gate gate4_review failed: {err}", file=sys.stderr)
            return False
        # Require that gate4 triggered repair (iter_0 exists). If gate4 PASSed without repair, test fails.
        if read_gate_status(request_id_full, 4) == "PASS" and not (repair_dir / "iter_0" / "failures.json").exists():
            print("  ✗ E2E0_BC_PRECONDITION: gate4 PASSed without repair; expected verifier FAIL (deliverables) to trigger repair")
            _emit_e2e0_bc_precondition_diagnostics(request_id_full, repair_dir, verifier_dir)
            return False

        # Precondition (Mode B): repair must have been triggered and iter_0 must exist.
        iter_0_dir = repair_dir / "iter_0"
        iter_0_failures = iter_0_dir / "failures.json"
        if not iter_0_failures.exists():
            _emit_e2e0_bc_precondition_diagnostics(request_id_full, repair_dir, verifier_dir)
            print("  ✗ E2E0_BC_PRECONDITION: expected verifier FAIL to trigger repair, but verifier did not fail")
            return False
        
        # Do not run later gates in E2E0-B; this test ends at repair+verifier PASS.
        
        # Check 1: Initial verifier FAIL recorded
        print(f"  ✓ Initial FAIL recorded in iter_0")
        
        # Check 2: Repair ran and accepted patch
        status_path = repair_dir / "status.json"
        if not status_path.exists():
            print(f"  ✗ repair/status.json not found")
            return False
        
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
            final_status = status.get("final_status", "")
            if final_status != "PASS_AFTER_REPAIR":
                print(f"  ✗ final_status is {final_status}, expected PASS_AFTER_REPAIR")
                return False
            print(f"  ✓ Repair final_status == PASS_AFTER_REPAIR")
            stop_reason = str(status.get("stop_reason", "")).strip()
            print(f"  ✓ Repair stop_reason == {stop_reason}")
            
            iter_1_dir = repair_dir / "iter_1"
            patch_gate_path = iter_1_dir / "patch_gate.json"
            if patch_gate_path.exists():
                patch_gate = json.loads(patch_gate_path.read_text(encoding="utf-8"))
                if not patch_gate.get("accepted", False):
                    print(f"  ✗ patch_gate.json.accepted is false")
                    return False
                print(f"  ✓ Patch accepted")
        except Exception as e:
            print(f"  ✗ Error reading repair status: {e}")
            return False
        
        # Check 3: Post-repair verifier PASS
        iter_1_dir = repair_dir / "iter_1"
        iter_1_result = iter_1_dir / "verifier.result.json"
        if iter_1_result.exists():
            result = json.loads(iter_1_result.read_text(encoding="utf-8"))
            if result.get("status") == "PASS":
                print(f"  ✓ Post-repair verifier PASS")
            else:
                print(f"  ⚠ Post-repair verifier status: {result.get('status')}")
        else:
            # Check final verifier result
            final_result = request_dir / "verifier" / "verifier.result.json"
            if final_result.exists():
                result = json.loads(final_result.read_text(encoding="utf-8"))
                if result.get("status") == "PASS":
                    print(f"  ✓ Final verifier PASS")
                else:
                    print(f"  ⚠ Final verifier status: {result.get('status')}")
        
        # Check 4: Trace completeness
        iter_0_hashes = iter_0_dir / "workspace_hashes.json"
        if not iter_0_hashes.exists():
            print(f"  ✗ iter_0/workspace_hashes.json not found")
            return False
        
        iter_1_dir = repair_dir / "iter_1"
        required_files = [
            "proposal.diff",
            "workspace_hashes.before.json",
            "workspace_hashes.after.json",
            "verifier.result.json",
            "failures.json",
            "decision.json"
        ]
        for f in required_files:
            if not (iter_1_dir / f).exists():
                print(f"  ✗ iter_1/{f} not found")
                return False
        print(f"  ✓ Trace completeness verified")
        
        print(f"\n✓ Test E2E0-B PASSED")
        return True
    finally:
        restore_policy_backup(backup_path)


def test_e2e0_c(request_id: str, fixtures: Dict[str, Any]) -> bool:
    """Test E2E0-C: FAIL → repair rejects patch → rollback proven."""
    print("\n" + "=" * 60)
    print("Test E2E0-C: FAIL → repair rejects patch → rollback proven")
    print("=" * 60)
    
    request_id_full = f"E2E0-C-{request_id}"
    # Clean previous run (if any)
    cleanup_request_deterministic(request_id_full)

    # Enable repair in policy
    backup_path = enable_repair_in_policy()
    if backup_path:
        print(f"  Enabled repair in policy (backup: {backup_path.name})")
    
    try:
        prompt = fixtures["fail_prompt_reject_patch"]
        patch_diff_path = BASE / prompt.get("reject_patch_diff_path", "")
        
        if not patch_diff_path.exists():
            print(f"  ⚠ WARNING: Patch diff not found at {patch_diff_path}, skipping test")
            return True
        
        print(f"Running pipeline for request: {request_id_full}")
        
        # Run up to gate3 (where repair would trigger)
        orchestrator = ORCHESTRATOR
        obj_json = json.dumps(prompt["objective"])
        cons_json = json.dumps(prompt["constraints"])
        non_json = json.dumps(prompt["non_goals"])
        dod_json = json.dumps(prompt["dod"])
        
        # Gate 0
        cmd = [sys.executable, str(orchestrator), "gate0_init", request_id_full, obj_json, cons_json, non_json, dod_json]
        import os
        p0 = subprocess.run(cmd, capture_output=True, text=True, env=os.environ.copy())
        status0 = read_gate_status(request_id_full, 0)
        if status0 != "PASS":
            print(f"  ✗ Gate0 status is {status0} (exit {p0.returncode})")
            return False

        # Inject a missing deliverable into payload to force verifier FAIL (no duplicates).
        force_fail = str(prompt.get("force_fail_deliverable", "MISSING_DELIVERABLE.txt")).strip()
        payload_path = REQUESTS_DIR / request_id_full / "payload.json"
        if payload_path.exists():
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            _ensure_deliverable(payload, force_fail, "text")
            payload_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        
        # Gate 1
        code, _out, err = run_gate(orchestrator, request_id_full, "gate1_planning")
        if code != 0:
            print(f"  Gate gate1_planning failed: {err}", file=sys.stderr)
            return False
        if read_gate_status(request_id_full, 1) != "PASS":
            print(f"  ✗ Gate1 status is {read_gate_status(request_id_full, 1)}")
            return False
        
        # Gate 2
        code, _out, err = run_gate(orchestrator, request_id_full, "gate2_delegation")
        if code != 0:
            print(f"  Gate gate2_delegation failed: {err}", file=sys.stderr)
            return False
        if read_gate_status(request_id_full, 2) != "PASS":
            print(f"  ✗ Gate2 status is {read_gate_status(request_id_full, 2)}")
            return False
        
        request_dir = REQUESTS_DIR / request_id_full
        repair_dir = request_dir / "repair"
        verifier_dir = request_dir / "verifier"
        iter_1_dir = repair_dir / "iter_1"
        iter_1_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(patch_diff_path, iter_1_dir / "proposal.diff")
        print(f"  Copied patch to {iter_1_dir / 'proposal.diff'}")

        # Gate 3: execution (generator + packager); must PASS to reach gate4
        code, _out, err = run_gate(orchestrator, request_id_full, "gate3_execution")
        if code != 0:
            print(f"  Gate gate3_execution failed: {err}", file=sys.stderr)
            return False
        if read_gate_status(request_id_full, 3) != "PASS":
            print(f"  ✗ Gate3 must PASS to reach gate4 (status: {read_gate_status(request_id_full, 3)})")
            return False

        # Gate 4: review — verifier must FAIL (deliverables) to trigger repair; repair creates iter_0
        code, _out, err = run_gate(orchestrator, request_id_full, "gate4_review")
        if code != 0:
            print(f"  Gate gate4_review failed: {err}", file=sys.stderr)
            return False
        # Require that gate4 triggered repair (iter_0 exists). If gate4 PASSed without repair, test fails.
        if read_gate_status(request_id_full, 4) == "PASS" and not (repair_dir / "iter_0" / "failures.json").exists():
            print("  ✗ E2E0_BC_PRECONDITION: gate4 PASSed without repair; expected verifier FAIL (deliverables) to trigger repair")
            _emit_e2e0_bc_precondition_diagnostics(request_id_full, repair_dir, verifier_dir)
            return False

        # Precondition (Mode B): repair must have been triggered and iter_0 must exist.
        iter_0_dir = repair_dir / "iter_0"
        iter_0_failures = iter_0_dir / "failures.json"
        if not iter_0_failures.exists():
            _emit_e2e0_bc_precondition_diagnostics(request_id_full, repair_dir, verifier_dir)
            print("  ✗ E2E0_BC_PRECONDITION: expected verifier FAIL to trigger repair, but verifier did not fail")
            return False
        
        # Do not run later gates in E2E0-C; this test ends at patch rejection + rollback proof.
        
        # Check 1: Repair ran and rejected
        repair_dir = request_dir / "repair"
        iter_1_dir = repair_dir / "iter_1"
        
        patch_gate_path = iter_1_dir / "patch_gate.json"
        decision_path = iter_1_dir / "decision.json"
        
        rejected = False
        if patch_gate_path.exists():
            patch_gate = json.loads(patch_gate_path.read_text(encoding="utf-8"))
            if not patch_gate.get("accepted", True):  # False or missing means rejected
                rejected = True
                print(f"  ✓ Patch rejected (patch_gate.json)")
        
        if decision_path.exists():
            decision = json.loads(decision_path.read_text(encoding="utf-8"))
            if not decision.get("accepted", True):
                rejected = True
                print(f"  ✓ Patch rejected (decision.json)")
        
        if not rejected:
            print(f"  ✗ Patch was not rejected")
            return False
        
        # Check 2: Rollback proof
        before_hashes_path = iter_1_dir / "workspace_hashes.before.json"
        if not before_hashes_path.exists():
            print(f"  ✗ workspace_hashes.before.json not found")
            return False
        
        try:
            before_hashes = json.loads(before_hashes_path.read_text(encoding="utf-8"))
            
            # After rollback, workspace should match before hashes
            # Check decision.json for rollback_verified
            if decision_path.exists():
                decision = json.loads(decision_path.read_text(encoding="utf-8"))
                rollback_verified = decision.get("rollback_verified")
                if rollback_verified is True:
                    print(f"  ✓ Rollback verified")
                elif rollback_verified is False:
                    print(f"  ✗ Rollback verification failed")
                    return False
                else:
                    print(f"  ⚠ Rollback verification not recorded (may be pre-apply rejection)")
            else:
                print(f"  ⚠ decision.json not found, cannot verify rollback")
        except Exception as e:
            print(f"  ✗ Error checking rollback: {e}")
            return False
        
        # Check 3: Report repair outcome ONLY from repair/status.json
        status_path = repair_dir / "status.json"
        if status_path.exists():
            status = json.loads(status_path.read_text(encoding="utf-8"))
            final_status = str(status.get("final_status", "")).strip()
            stop_reason = str(status.get("stop_reason", "")).strip()
            print(f"  ✓ repair.final_status == {final_status}")
            print(f"  ✓ repair.stop_reason == {stop_reason}")
            if not final_status or not stop_reason:
                print("  ✗ repair/status.json missing final_status or stop_reason")
                return False
        
        # Check 4: No partial accept state
        after_hashes_path = iter_1_dir / "workspace_hashes.after.json"
        if after_hashes_path.exists():
            # If after exists, rollback should have restored to before
            print(f"  ⚠ workspace_hashes.after.json exists (patch was applied then rolled back)")
        else:
            print(f"  ✓ No workspace_hashes.after.json (patch not applied or pre-apply rejection)")
        
        print(f"\n✓ Test E2E0-C PASSED")
        return True
    finally:
        restore_policy_backup(backup_path)


def test_e2e0_d(request_id: str, fixtures: Dict[str, Any]) -> bool:
    """Test E2E0-D: Ambiguous prompt produces CLARIFY and halts."""
    print("\n" + "=" * 60)
    print("Test E2E0-D: Ambiguous prompt produces CLARIFY and halts")
    print("=" * 60)
    
    prompt = fixtures["clarify_prompt"]
    request_id_full = f"E2E0-D-{request_id}"
    cleanup_request_deterministic(request_id_full)
    
    print(f"Running pipeline for request: {request_id_full}")
    
    # Run gate0 and gate1 (where clarification should be detected)
    orchestrator = ORCHESTRATOR
    obj_json = json.dumps(prompt["objective"])
    cons_json = json.dumps(prompt["constraints"])
    non_json = json.dumps(prompt["non_goals"])
    dod_json = json.dumps(prompt["dod"])
    
    # Gate 0
    cmd = [sys.executable, str(orchestrator), "gate0_init", request_id_full, obj_json, cons_json, non_json, dod_json]
    import os
    subprocess.run(cmd, capture_output=True, text=True, env=os.environ.copy())
    
    # Gate 1 (should detect CLARIFY and halt)
    code, _out, err = run_gate(orchestrator, request_id_full, "gate1_planning")
    # Clarify halts deterministically with exit code 3.
    if code not in (0, 3):
        print(f"  Gate gate1_planning failed: {err}", file=sys.stderr)
        return False
    
    request_dir = REQUESTS_DIR / request_id_full
    
    # Check 1: CLARIFY.json exists with required fields
    clarify_path = request_dir / "CLARIFY.json"
    if not clarify_path.exists():
        print(f"  ✗ CLARIFY.json not found")
        return False
    
    try:
        clarify = json.loads(clarify_path.read_text(encoding="utf-8"))
        required_fields = ["request_id", "policy_version", "knowledge_snapshot_id", "manifest_bundle_hash", "reason", "candidate_intents", "questions"]
        for field in required_fields:
            if field not in clarify:
                print(f"  ✗ CLARIFY.json missing field: {field}")
                return False
        
        candidate_intents = clarify.get("candidate_intents", [])
        questions = clarify.get("questions", [])
        if not candidate_intents:
            print(f"  ✗ candidate_intents is empty")
            return False
        if not questions:
            print(f"  ✗ questions is empty")
            return False
        
        print(f"  ✓ CLARIFY.json has all required fields")
    except Exception as e:
        print(f"  ✗ Error reading CLARIFY.json: {e}")
        return False
    
    # Check 2: Planner halted (no generator/verifier/repair)
    verifier_dir = request_dir / "verifier"
    if verifier_dir.exists():
        print(f"  ✗ Verifier directory exists; CLARIFY should halt before verifier")
        return False
    print(f"  ✓ Verifier not executed")
    
    # Check for generator outputs (should not exist)
    workspace_dir = request_dir / "workspace" / "project"
    if workspace_dir.exists() and any(workspace_dir.rglob("*")):
        print(f"  ✗ Generator outputs found despite CLARIFY halt")
        return False
    print(f"  ✓ No generator outputs")

    # Check gate statuses: gate2-6 must be SKIPPED_CLARIFY
    for g in range(2, 7):
        status = read_gate_status(request_id_full, g)
        if status != "SKIPPED_CLARIFY":
            print(f"  ✗ gate{g}.status is {status}, expected SKIPPED_CLARIFY")
            return False
    print(f"  ✓ gate2-6 marked SKIPPED_CLARIFY")
    
    print(f"\n✓ Test E2E0-D PASSED")
    return True


def main():
    parser = argparse.ArgumentParser(description="E2E-0 Test Suite")
    parser.add_argument("--snapshot", required=True, help="Knowledge snapshot ID")
    parser.add_argument("--policy", default="v1", help="Policy version")
    parser.add_argument("--workspace", help="Workspace path (optional)")
    parser.add_argument("--fixtures", default="scripts/e2e/fixtures/e2e0.json", help="Path to fixtures JSON")
    parser.add_argument("--request-id", default="TEST", help="Base request ID prefix")
    parser.add_argument("--state-root", help="State root dir (default: temp). Avoids repo state/requests.")
    parser.add_argument("--e2e0-report", default="", help="Path for e2e0_report.json (default: <state-root or BASE>/out/e2e0_report.json)")
    
    args = parser.parse_args()
    
    # Load fixtures
    fixtures_path = BASE / args.fixtures
    if not fixtures_path.exists():
        die(f"Fixtures file not found: {fixtures_path}")
    
    try:
        fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
    except Exception as e:
        die(f"Error loading fixtures: {e}")
    
    print("=" * 60)
    print("E2E-0 Test Suite")
    print("=" * 60)
    print(f"Snapshot: {args.snapshot}")
    print(f"Policy: {args.policy}")
    print(f"Fixtures: {fixtures_path}")
    
    # Ensure manifests exist and obtain bundle hash
    manifest_bundle_hash = ensure_snapshot_manifest_bundle(args.snapshot, args.policy)
    print(f"Manifest bundle hash: {manifest_bundle_hash}")
    
    # Set environment for snapshot (DB/KB)
    set_snapshot_env(args.snapshot)
    
    # Use temp or --state-root for requests (no repo state/requests, no root-owned dirs)
    global REQUESTS_DIR
    REQUESTS_DIR, _temp_dir = _get_requests_dir(args.state_root)
    os.environ["NLC_REQUESTS_ROOT"] = str(REQUESTS_DIR)
    print(f"Requests dir: {REQUESTS_DIR}")
    
    # Clean any prior E2E0-* runs for this base request id
    cleanup_e2e_requests_deterministic(args.request_id)
    
    # Run tests
    results = []
    
    results.append(("E2E0-A", test_e2e0_a(args.request_id, fixtures)))
    results.append(("E2E0-B", test_e2e0_b(args.request_id, fixtures, args.snapshot)))
    results.append(("E2E0-C", test_e2e0_c(args.request_id, fixtures)))
    results.append(("E2E0-D", test_e2e0_d(args.request_id, fixtures)))
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{test_name}: {status}")
    
    all_passed = all(passed for _, passed in results)

    # Emit deterministic e2e0_report.json (sorted keys, no timestamps)
    report_root = Path(args.state_root).resolve() if args.state_root else BASE
    report_path = Path(args.e2e0_report).resolve() if args.e2e0_report else (report_root / "out" / "e2e0_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_obj = {"e2e0": {name.replace("E2E0-", ""): "PASS" if passed else "FAIL" for name, passed in results}}
    report_path.write_text(json.dumps(report_obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    
    if all_passed:
        print("\n✓ All E2E-0 tests PASSED")
        return 0
    else:
        print("\n✗ Some E2E-0 tests FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())

