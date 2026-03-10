#!/usr/bin/env python3
"""Repair Loop Runner - Step 5: Bounded, deterministic repair with trace."""

import sys
import json
import hashlib
import subprocess
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass, asdict

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
from nlc.paths import deliverables_root, repair_root  # canonical roots
RUN_VERIFIER = BASE / "workers" / "run_verifier.py"

def _stop_reason_short(stop_reason: str) -> str:
    """
    Stable coarse stop reason category for Milestone 2.1 proofs.
    Does NOT replace existing stop_reason (back-compat); adds a summarized field.
    """
    r = (stop_reason or "").strip().upper()
    if r in ("PASS",):
        return "pass"
    if r in ("NO_PROPOSAL",):
        return "no_proposal"
    if r in ("REJECTED_SCOPE", "REJECTED_BUDGET", "REJECTED_PATCH_INVALID"):
        return "scope"
    if r in ("REJECTED_NO_IMPROVEMENT", "NO_PROGRESS", "MAX_ITERS"):
        return "no_improve"
    if r in ("REJECTED_VERIFIER_ERROR",):
        return "contract"
    return "other"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(p.read_bytes())


def compute_workspace_hashes(workspace_root: Path) -> Dict[str, str]:
    """
    Compute deterministic hashes of request workspace files.
    
    Excludes:
    - repair/ and verifier/ internal dirs
    - orchestrator gate/state bookkeeping files (gate*.status, gate*.result.json, state.json)
    - top-level verifier artifacts (VERIFY.md, verifier.* at top level)
    
    Rationale: rollback verification should cover the patchable workspace/content, not gate bookkeeping.
    """
    hashes: Dict[str, str] = {}
    if not workspace_root.exists():
        return hashes
    
    for file_path in sorted(workspace_root.rglob("*")):
        if not file_path.is_file():
            continue
        rel_path = str(file_path.relative_to(workspace_root)).replace("\\", "/")
        if rel_path.startswith("repair/") or rel_path.startswith("verifier/"):
            continue
        if rel_path == "state.json":
            continue
        if rel_path.startswith("gate") and (rel_path.endswith(".status") or rel_path.endswith(".result.json")):
            continue
        if rel_path == "VERIFY.md":
            continue
        if rel_path.startswith("verifier."):
            continue
        hashes[rel_path] = sha256_file(file_path)
    
    return hashes


def restore_workspace_from_hashes(workspace_root: Path, target_hashes: Dict[str, str], source_hashes: Dict[str, str]) -> Tuple[bool, str]:
    """
    Restore workspace to match target_hashes by copying from source state.
    
    This is a simplified rollback - in production, would use git or backup mechanism.
    For stub mode, we'll restore by comparing and reverting changed files.
    
    Returns: (success, error_message)
    """
    try:
        # Find files that changed
        changed_files = []
        for rel_path, target_hash in target_hashes.items():
            current_path = workspace_root / rel_path
            if current_path.exists():
                current_hash = sha256_file(current_path)
                if current_hash != target_hash:
                    changed_files.append(rel_path)
        
        # For stub mode: we need a backup mechanism
        # In production, would use git checkout or restore from backup
        # For now, we'll just verify the hashes match (rollback verification)
        
        # If we had a backup, we would restore here
        # For now, return success if we can verify (actual restore would need backup)
        return (True, "")
        
    except Exception as e:
        return (False, str(e))


def backup_files_for_patch(workspace_root: Path, file_paths: List[str], backup_dir: Path) -> Tuple[bool, str]:
    """Backup only files touched by the patch (avoids recursive copy of request dir)."""
    try:
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        meta = {"files": []}
        for fp in sorted(set(file_paths)):
            if fp in ("/dev/null", ""):
                continue
            rel = fp.replace("\\", "/").lstrip("/")
            full = workspace_root / rel
            entry = {"path": rel, "existed": full.exists()}
            if full.exists() and full.is_file():
                dest = backup_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(full, dest)
            meta["files"].append(entry)
        (backup_dir / "backup_meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return (True, "")
    except Exception as e:
        return (False, str(e))


def restore_files_from_backup(workspace_root: Path, backup_dir: Path) -> Tuple[bool, str]:
    """Restore only files touched by the patch."""
    try:
        meta_path = backup_dir / "backup_meta.json"
        if not meta_path.exists():
            return (False, "backup_meta.json missing")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        for entry in meta.get("files", []):
            rel = entry.get("path", "")
            existed = bool(entry.get("existed", False))
            if not rel:
                continue
            full = workspace_root / rel
            backup_file = backup_dir / rel
            if existed:
                if backup_file.exists():
                    full.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup_file, full)
            else:
                if full.exists():
                    try:
                        full.unlink()
                    except Exception:
                        pass
        return (True, "")
    except Exception as e:
        return (False, str(e))


def compute_failure_bundle_hash(failures: List[Dict[str, Any]]) -> str:
    """Compute deterministic hash of failure bundle."""
    if not failures:
        return sha256_bytes(b"no_failures")[:16]
    
    # Sort by failure_id for deterministic ordering
    sorted_failures = sorted(failures, key=lambda f: f.get("failure_id", ""))
    combined = "\n".join(f.get("failure_id", "") for f in sorted_failures)
    return sha256_bytes(combined.encode("utf-8"))[:16]


def compute_severity_score(failures: List[Dict[str, Any]], severity_ranks: Dict[str, int]) -> Tuple[int, int, int]:
    """
    Compute deterministic severity score.
    
    Returns: (max_severity_rank, failure_count, total_bytes)
    Lower rank = worse (0 is worst). Higher rank = better.
    """
    if not failures:
        return (999, 0, 0)  # No failures = best score
    
    # Unknown kinds are treated as worst (0) to avoid "unknown == best" behavior.
    worst_rank = min(
        severity_ranks.get(f.get("kind", ""), 0)
        for f in failures
    )
    
    failure_count = len(failures)
    
    # Total bytes is placeholder (would need to compute from actual diffs)
    total_bytes = 0
    
    return (worst_rank, failure_count, total_bytes)


def parse_unified_diff(diff_text: str) -> Tuple[bool, List[str], Dict[str, Any]]:
    """
    Parse unified diff and extract file paths.
    
    Returns: (is_valid, file_paths, metadata)
    """
    if not diff_text.strip():
        return (False, [], {"error": "empty diff"})
    
    # Basic unified diff validation
    lines = diff_text.splitlines()
    if not lines[0].startswith("---") and not lines[0].startswith("+++"):
        # Try to find first diff header
        found_header = False
        for i, line in enumerate(lines):
            if line.startswith("---") or line.startswith("+++"):
                found_header = True
                break
        if not found_header:
            return (False, [], {"error": "not a unified diff format"})
    
    file_paths = []
    for line in lines:
        if line.startswith("--- ") or line.startswith("+++ "):
            # Extract file path (skip a/ b/ prefixes)
            path = line[4:].strip()
            if path.startswith("a/") or path.startswith("b/"):
                path = path[2:]
            if path and path not in file_paths:
                file_paths.append(path)
    
    metadata = {
        "total_lines": len(lines),
        "files_touched": len(file_paths),
    }
    
    return (True, file_paths, metadata)


def validate_patch_scope(
    file_paths: List[str],
    workspace_roots: List[str],
    forbidden_scopes: List[str],
    request_dir: Path,
) -> Tuple[bool, List[str]]:
    """
    Validate patch scope against policy.
    
    Returns: (is_valid, errors)
    """
    errors = []
    
    for file_path in file_paths:
        # Check if file is under allowed workspace root
        in_allowed = False
        for root in workspace_roots:
            normalized_root = root.strip("/")
            if normalized_root == "" or normalized_root == ".":
                in_allowed = True
                break
            if file_path.startswith(normalized_root):
                in_allowed = True
                break
        
        if not in_allowed:
            errors.append(f"File {file_path} not under allowed workspace root")
        
        # Check forbidden scopes
        for forbidden in forbidden_scopes:
            if forbidden in file_path or file_path.startswith(forbidden):
                errors.append(f"File {file_path} is in forbidden scope: {forbidden}")
    
    return (len(errors) == 0, errors)


def validate_patch_budget(
    file_paths: List[str],
    diff_text: str,
    max_files: int,
    max_lines: int,
    max_bytes: int,
) -> Tuple[bool, List[str]]:
    """Validate patch against budget constraints."""
    errors = []
    
    if len(file_paths) > max_files:
        errors.append(f"Too many files touched: {len(file_paths)} > {max_files}")
    
    diff_lines = len(diff_text.splitlines())
    if diff_lines > max_lines:
        errors.append(f"Too many lines changed: {diff_lines} > {max_lines}")
    
    diff_bytes = len(diff_text.encode("utf-8"))
    if diff_bytes > max_bytes:
        errors.append(f"Diff too large: {diff_bytes} > {max_bytes}")
    
    return (len(errors) == 0, errors)


def apply_patch(diff_text: str, workspace_root: Path) -> Tuple[bool, str]:
    """
    Apply unified diff to workspace using patch command.
    
    Returns: (success, error_message)
    """
    try:
        import tempfile
        import subprocess
        
        # Write diff to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.diff', delete=False) as f:
            f.write(diff_text)
            diff_file = Path(f.name)
        
        try:
            # Use patch command (standard Unix tool)
            # -p1: strip one leading slash from paths
            # -d: change to workspace_root directory
            # --dry-run first to validate
            cmd = ["patch", "-p1", "-d", str(workspace_root), "--dry-run", "-f", str(diff_file)]
            p = subprocess.run(cmd, capture_output=True, text=True)
            
            if p.returncode != 0:
                return (False, f"Patch dry-run failed: {p.stderr or p.stdout}")
            
            # Apply for real
            # NOTE: -i is required; passing the diff path as a positional argument can be treated as an origfile.
            cmd = ["patch", "-p1", "-d", str(workspace_root), "-f", "-i", str(diff_file)]
            p = subprocess.run(cmd, capture_output=True, text=True)
            
            if p.returncode != 0:
                return (False, f"Patch apply failed: {p.stderr or p.stdout}")
            
            return (True, "")
            
        finally:
            diff_file.unlink()
            
    except FileNotFoundError:
        return (False, "patch command not found (install patch utility)")
    except Exception as e:
        return (False, str(e))


def main():
    if len(sys.argv) < 3:
        print("Usage: run_repair.py <REQUEST_ID> <REQUEST_DIR> [GATE_NAME]", file=sys.stderr)
        sys.exit(2)
    
    request_id = sys.argv[1].strip()
    request_dir = Path(sys.argv[2]).resolve()
    gate_name = sys.argv[3].strip() if len(sys.argv) > 3 else "gate3_execution"
    
    if not request_dir.exists():
        print(f"ERROR: Request directory not found: {request_dir}", file=sys.stderr)
        sys.exit(1)
    
    # Load policy
    try:
        from policy import load_policy, get_default_policy_version
        
        payload_path = request_dir / "payload.json"
        policy_version = get_default_policy_version()
        if payload_path.exists():
            payload = json.loads(payload_path.read_text(encoding="utf-8", errors="replace"))
            policy_version = payload.get("policy_version", policy_version)
        
        policy = load_policy(policy_version)
        repair_policy = policy.get_repair_policy()
    except Exception as e:
        print(f"ERROR: Failed to load policy: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Check if repair is enabled
    if not repair_policy.get("enabled", False):
        print("Repair is disabled by policy", file=sys.stderr)
        sys.exit(0)
    
    # Check verifier result
    verifier_dir = request_dir / "verifier"
    result_path = verifier_dir / "verifier.result.json"
    failures_path = verifier_dir / "failures.json"
    
    if not result_path.exists():
        print("ERROR: verifier.result.json not found", file=sys.stderr)
        sys.exit(1)
    
    result = json.loads(result_path.read_text(encoding="utf-8"))
    status = result.get("status", "")
    
    # Repair triggers only on FAIL (not ERROR)
    if status != "FAIL":
        print(f"Repair not triggered: verifier status is {status} (only FAIL triggers repair)", file=sys.stderr)
        sys.exit(0)
    
    # Load failures
    if not failures_path.exists():
        print("ERROR: failures.json not found", file=sys.stderr)
        sys.exit(1)
    
    failures_obj = json.loads(failures_path.read_text(encoding="utf-8"))
    initial_failures = failures_obj.get("failures", [])
    initial_failure_hash = compute_failure_bundle_hash(initial_failures)
    
    # Create repair directory
    repair_dir = repair_root(request_dir)
    repair_dir.mkdir(parents=True, exist_ok=True)
    
    # Load metadata for status.json
    payload_path = request_dir / "payload.json"
    knowledge_snapshot_id = None
    manifest_bundle_hash = None
    artifact_class = ""
    if payload_path.exists():
        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8", errors="replace"))
            knowledge_snapshot_id = payload.get("knowledge_snapshot_id")
            manifest_bundle_hash = payload.get("manifest_bundle_hash")
            artifact_class = str(payload.get("artifact_class", "")).strip()
        except Exception:
            pass
    
    # Initialize iter_0 (baseline)
    iter_0_dir = repair_dir / "iter_0"
    iter_0_dir.mkdir(parents=True, exist_ok=True)
    
    # Copy initial failures and verifier result
    shutil.copy(failures_path, iter_0_dir / "failures.json")
    shutil.copy(result_path, iter_0_dir / "verifier.result.json")

    # Milestone 5.6: Preserve pre-repair debug artifacts for evidence
    debug_dir = request_dir / "debug"
    if debug_dir.exists():
        debug_snapshot = iter_0_dir / "debug_pre"
        if debug_snapshot.exists():
            shutil.rmtree(debug_snapshot)
        shutil.copytree(debug_dir, debug_snapshot)
    
    # Compute initial workspace hashes (over entire deliverables root for consistency)
    workspace_root = deliverables_root(request_dir)
    initial_hashes = compute_workspace_hashes(workspace_root)
    (iter_0_dir / "workspace_hashes.json").write_text(
        json.dumps(initial_hashes, indent=2, sort_keys=True) + "\n",
        encoding="utf-8"
    )
    
    # Repair loop
    max_iters = repair_policy.get("max_iterations", 10)
    no_progress_count = 0
    severity_ranks = repair_policy.get("severity_ranks", {})
    initial_score = compute_severity_score(initial_failures, severity_ranks)
    accepted_patches = []
    rejected_patches = []
    
    for iteration in range(1, max_iters + 1):
        iter_dir = repair_dir / f"iter_{iteration}"
        iter_dir.mkdir(parents=True, exist_ok=True)
        
        # Check for proposal.diff
        proposal_path = iter_dir / "proposal.diff"
        diff_text = None
        
        # For python_debug_script, allow proposal.diff from debug/
        if artifact_class == "python_debug_script" and not proposal_path.exists():
            debug_proposal = request_dir / "debug" / "proposal.diff"
            if debug_proposal.exists():
                shutil.copy(debug_proposal, proposal_path)
        
        if proposal_path.exists():
            diff_text = proposal_path.read_text(encoding="utf-8", errors="replace")
        
        if not diff_text:
            # No proposal - stop deterministically
            stop_reason = "NO_PROPOSAL"
            
            status_json = {
                "final_status": "FAIL_NO_PROPOSAL",
                "iters_run": iteration - 1,
                "stop_reason": stop_reason,
                "stop_reason_short": _stop_reason_short(stop_reason),
                "policy_version": policy_version,
                "knowledge_snapshot_id": knowledge_snapshot_id,
                "manifest_bundle_hash": manifest_bundle_hash,
                "initial_failure_bundle_hash": initial_failure_hash,
                "final_failure_bundle_hash": initial_failure_hash,
                "accepted_patches": accepted_patches,
                "rejected_patches": rejected_patches,
            }
            (repair_dir / "status.json").write_text(
                json.dumps(status_json, indent=2, sort_keys=True) + "\n",
                encoding="utf-8"
            )
            print(f"Stopped at iteration {iteration - 1}: no proposal.diff found", file=sys.stderr)
            break

        # Record workspace state before any gating/apply for this iteration (even if we reject pre-apply).
        workspace_hashes_before = compute_workspace_hashes(workspace_root)
        (iter_dir / "workspace_hashes.before.json").write_text(
            json.dumps(workspace_hashes_before, indent=2, sort_keys=True) + "\n",
            encoding="utf-8"
        )
        decision = None
        
        # Parse and validate diff
        is_valid, file_paths, diff_metadata = parse_unified_diff(diff_text)
        
        patch_gate = {
            "accepted": False,
            "reasons": [],
        }
        
        if not is_valid:
            patch_gate["reasons"].append(diff_metadata.get("error", "Invalid diff format"))
            rejected_patches.append(iteration)
            (iter_dir / "apply_result.json").write_text(
                json.dumps({"applied": False, "error": "SKIPPED_INVALID_DIFF"}, indent=2, sort_keys=True) + "\n",
                encoding="utf-8"
            )
            decision = {"accepted": False, "reason": "PATCH_INVALID", "rollback_verified": True}
        else:
            # Validate scope
            workspace_roots = repair_policy.get("allowed_workspace_roots", [".", "workspace/project/"])
            forbidden_scopes = repair_policy.get("forbidden_file_scopes", [])
            scope_valid, scope_errors = validate_patch_scope(
                file_paths, workspace_roots, forbidden_scopes, request_dir
            )
            
            if not scope_valid:
                patch_gate["reasons"].extend(scope_errors)
                rejected_patches.append(iteration)
                (iter_dir / "apply_result.json").write_text(
                    json.dumps({"applied": False, "error": "SKIPPED_SCOPE_INVALID"}, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8"
                )
                decision = {"accepted": False, "reason": "SCOPE_INVALID", "rollback_verified": True}
            else:
                # Validate budget
                max_files = repair_policy.get("max_files_per_iteration", 5)
                max_lines = repair_policy.get("max_lines_per_iteration", 100)
                max_bytes = repair_policy.get("max_total_diff_bytes", 10000)
                
                budget_valid, budget_errors = validate_patch_budget(
                    file_paths, diff_text, max_files, max_lines, max_bytes
                )
                
                if not budget_valid:
                    patch_gate["reasons"].extend(budget_errors)
                    rejected_patches.append(iteration)
                    (iter_dir / "apply_result.json").write_text(
                        json.dumps({"applied": False, "error": "SKIPPED_BUDGET_INVALID"}, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8"
                    )
                    decision = {"accepted": False, "reason": "BUDGET_INVALID", "rollback_verified": True}
                else:
                    # Apply patch with backup for rollback
                    # Backup workspace before applying
                    backup_dir = iter_dir / "workspace_backup"
                    backup_success, backup_error = backup_files_for_patch(workspace_root, file_paths, backup_dir)
                    
                    if not backup_success:
                        patch_gate["reasons"].append(f"Backup failed: {backup_error}")
                    else:
                        apply_success, apply_error = apply_patch(diff_text, workspace_root)
                        
                        apply_result = {
                            "applied": apply_success,
                            "error": apply_error if not apply_success else None,
                        }
                        (iter_dir / "apply_result.json").write_text(
                            json.dumps(apply_result, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8"
                        )
                        
                        if not apply_success:
                            patch_gate["reasons"].append(f"Patch apply failed: {apply_error}")
                            rejected_patches.append(iteration)
                            # Restore from backup
                            restore_files_from_backup(workspace_root, backup_dir)
                        else:
                            # Milestone 5.6: For python_debug_script, rerun debug runner before verifier
                            if artifact_class == "python_debug_script":
                                run_debug = BASE / "workers" / "run_debug.py"
                                subprocess.run([sys.executable, str(run_debug), request_id], capture_output=True, text=True)
                            # Rerun verifier
                            cmd = [sys.executable, str(RUN_VERIFIER), request_id, str(request_dir), gate_name]
                            p = subprocess.run(cmd, capture_output=True, text=True)
                            
                            # Load new verifier results
                            new_result_path = verifier_dir / "verifier.result.json"
                            new_failures_path = verifier_dir / "failures.json"
                            
                            if new_result_path.exists() and new_failures_path.exists():
                                new_result = json.loads(new_result_path.read_text(encoding="utf-8"))
                                new_failures_obj = json.loads(new_failures_path.read_text(encoding="utf-8"))
                                new_failures = new_failures_obj.get("failures", [])
                                
                                # Copy verifier results to iter dir
                                shutil.copy(new_result_path, iter_dir / "verifier.result.json")
                                shutil.copy(new_failures_path, iter_dir / "failures.json")
                                
                                # Compute new score
                                new_score = compute_severity_score(new_failures, severity_ranks)
                                
                                # Monotonic improvement gate:
                                # higher score is better (less severe / fewer failures)
                                if new_score > initial_score:
                                    # Improvement - accept
                                    patch_gate["accepted"] = True
                                    accepted_patches.append(iteration)
                                    workspace_hashes_after = compute_workspace_hashes(workspace_root)
                                    (iter_dir / "workspace_hashes.after.json").write_text(
                                        json.dumps(workspace_hashes_after, indent=2, sort_keys=True) + "\n",
                                        encoding="utf-8"
                                    )
                                    
                                    decision = {
                                        "accepted": True,
                                        "reason": "MONOTONIC_IMPROVEMENT",
                                        "score_before": list(initial_score),
                                        "score_after": list(new_score),
                                    }
                                    
                                    # Check if PASS
                                    if new_result.get("status") == "PASS":
                                        # Persist iteration artifacts before exiting the loop.
                                        (iter_dir / "patch_gate.json").write_text(
                                            json.dumps(patch_gate, indent=2, sort_keys=True) + "\n",
                                            encoding="utf-8"
                                        )
                                        (iter_dir / "decision.json").write_text(
                                            json.dumps(decision, indent=2, sort_keys=True) + "\n",
                                            encoding="utf-8"
                                        )
                                        status_json = {
                                            "final_status": "PASS_AFTER_REPAIR",
                                            "iters_run": iteration,
                                            "stop_reason": "PASS",
                                            "stop_reason_short": _stop_reason_short("PASS"),
                                            "policy_version": policy_version,
                                            "knowledge_snapshot_id": knowledge_snapshot_id,
                                            "manifest_bundle_hash": manifest_bundle_hash,
                                            "initial_failure_bundle_hash": initial_failure_hash,
                                            "final_failure_bundle_hash": compute_failure_bundle_hash(new_failures),
                                            "accepted_patches": accepted_patches,
                                            "rejected_patches": rejected_patches,
                                        }
                                        (repair_dir / "status.json").write_text(
                                            json.dumps(status_json, indent=2, sort_keys=True) + "\n",
                                            encoding="utf-8"
                                        )
                                        print(f"PASS after {iteration} iterations", file=sys.stderr)
                                        break
                                    
                                    # Update for next iteration
                                    initial_failures = new_failures
                                    initial_score = new_score
                                    initial_failure_hash = compute_failure_bundle_hash(new_failures)
                                    no_progress_count = 0
                                else:
                                    # No improvement - rollback
                                    rejected_patches.append(iteration)
                                    patch_gate["reasons"].append("NO_MONOTONIC_IMPROVEMENT")
                                    no_progress_count += 1
                                    
                                    # Restore workspace from backup (exact rollback)
                                    restore_success, restore_error = restore_files_from_backup(workspace_root, backup_dir)
                                    
                                    if not restore_success:
                                        patch_gate["reasons"].append(f"Rollback failed: {restore_error}")
                                    
                                    # Verify rollback restored exact hashes
                                    restored_hashes = compute_workspace_hashes(workspace_root)
                                    (iter_dir / "workspace_hashes.after_rollback.json").write_text(
                                        json.dumps(restored_hashes, indent=2, sort_keys=True) + "\n",
                                        encoding="utf-8"
                                    )
                                    if restored_hashes != workspace_hashes_before:
                                        patch_gate["reasons"].append("Rollback verification failed: hashes do not match")
                                    
                                    decision = {
                                        "accepted": False,
                                        "reason": "NO_IMPROVEMENT",
                                        "score_before": list(initial_score),
                                        "score_after": list(new_score),
                                        "rollback_verified": restored_hashes == workspace_hashes_before,
                                    }
                            else:
                                patch_gate["reasons"].append("Verifier did not produce results")
                                decision = {
                                    "accepted": False,
                                    "reason": "VERIFIER_ERROR",
                                }
        
        # Write patch gate result
        (iter_dir / "patch_gate.json").write_text(
            json.dumps(patch_gate, indent=2, sort_keys=True) + "\n",
            encoding="utf-8"
        )
        
        # Write decision
        if decision is not None:
            (iter_dir / "decision.json").write_text(
                json.dumps(decision, indent=2, sort_keys=True) + "\n",
                encoding="utf-8"
            )

        # If rejected (pre-apply or post-apply), stop deterministically with REJECTED_* stop reasons.
        if patch_gate.get("accepted") is False:
            stop_reason = "REJECTED"
            if decision and isinstance(decision, dict):
                r = str(decision.get("reason", "")).upper()
                if r == "SCOPE_INVALID":
                    stop_reason = "REJECTED_SCOPE"
                elif r == "BUDGET_INVALID":
                    stop_reason = "REJECTED_BUDGET"
                elif r == "PATCH_INVALID":
                    stop_reason = "REJECTED_PATCH_INVALID"
                elif r == "NO_IMPROVEMENT":
                    stop_reason = "REJECTED_NO_IMPROVEMENT"
                elif r == "VERIFIER_ERROR":
                    stop_reason = "REJECTED_VERIFIER_ERROR"
            status_json = {
                "final_status": "FAIL_PATCH_REJECTED",
                "iters_run": iteration,
                "stop_reason": stop_reason,
                "stop_reason_short": _stop_reason_short(stop_reason),
                "policy_version": policy_version,
                "knowledge_snapshot_id": knowledge_snapshot_id,
                "manifest_bundle_hash": manifest_bundle_hash,
                "initial_failure_bundle_hash": initial_failure_hash,
                "final_failure_bundle_hash": compute_failure_bundle_hash(initial_failures),
                "accepted_patches": accepted_patches,
                "rejected_patches": rejected_patches,
            }
            (repair_dir / "status.json").write_text(
                json.dumps(status_json, indent=2, sort_keys=True) + "\n",
                encoding="utf-8"
            )
            break
        
        # Add budget numbers to patch_gate
        if "files_touched" in diff_metadata:
            patch_gate["files_touched"] = diff_metadata["files_touched"]
        if "total_lines" in diff_metadata:
            patch_gate["total_lines"] = diff_metadata["total_lines"]
        
        # Check stop conditions
        if no_progress_count >= 3:  # Policy-defined threshold
            status_json = {
                "final_status": "FAIL_NO_PROGRESS",
                "iters_run": iteration,
                "stop_reason": "NO_PROGRESS",
                "stop_reason_short": _stop_reason_short("NO_PROGRESS"),
                "policy_version": policy_version,
                "knowledge_snapshot_id": knowledge_snapshot_id,
                "manifest_bundle_hash": manifest_bundle_hash,
                "initial_failure_bundle_hash": initial_failure_hash,
                "final_failure_bundle_hash": compute_failure_bundle_hash(initial_failures),
                "accepted_patches": accepted_patches,
                "rejected_patches": rejected_patches,
            }
            (repair_dir / "status.json").write_text(
                json.dumps(status_json, indent=2, sort_keys=True) + "\n",
                encoding="utf-8"
            )
            print(f"Stopped at iteration {iteration}: no progress", file=sys.stderr)
            break
    
    # Final status if loop completed
    if not (repair_dir / "status.json").exists():
        status_json = {
            "final_status": "FAIL_MAX_ITERS",
            "iters_run": max_iters,
            "stop_reason": "MAX_ITERS",
            "stop_reason_short": _stop_reason_short("MAX_ITERS"),
            "policy_version": policy_version,
            "knowledge_snapshot_id": knowledge_snapshot_id,
            "manifest_bundle_hash": manifest_bundle_hash,
            "initial_failure_bundle_hash": initial_failure_hash,
            "final_failure_bundle_hash": compute_failure_bundle_hash(initial_failures),
            "accepted_patches": accepted_patches,
            "rejected_patches": rejected_patches,
        }
        (repair_dir / "status.json").write_text(
            json.dumps(status_json, indent=2, sort_keys=True) + "\n",
            encoding="utf-8"
        )
    
    print("OK")


if __name__ == "__main__":
    main()

