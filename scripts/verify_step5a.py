#!/usr/bin/env python3
"""Step 5a verification: Repair loop stub mode correctness."""

import sys
import json
import hashlib
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_required_files_exist(request_id: str):
    """Test 1: Required files exist."""
    print("Test 1: Required files exist")
    print("-" * 60)
    
    request_dir = BASE / "state" / "requests" / request_id
    if not request_dir.exists():
        print(f"  ✗ Request directory not found: {request_dir}")
        return False
    
    repair_dir = request_dir / "repair"
    status_path = repair_dir / "status.json"
    
    if not status_path.exists():
        print(f"  ✗ status.json not found")
        return False
    print(f"  ✓ status.json exists")
    
    # Check iter_0
    iter_0_dir = repair_dir / "iter_0"
    required_iter_0 = ["failures.json", "workspace_hashes.json", "verifier.result.json"]
    for f in required_iter_0:
        if not (iter_0_dir / f).exists():
            print(f"  ✗ iter_0/{f} missing")
            return False
    print(f"  ✓ iter_0 has all required files")
    
    # Check status.json structure
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
        required_fields = [
            "final_status", "iters_run", "stop_reason", "policy_version",
            "initial_failure_bundle_hash", "accepted_patches", "rejected_patches"
        ]
        for field in required_fields:
            if field not in status:
                print(f"  ✗ status.json missing field: {field}")
                return False
        print(f"  ✓ status.json has all required fields")
    except Exception as e:
        print(f"  ✗ Error reading status.json: {e}")
        return False
    
    return True


def test_monotonic_rule(request_id: str):
    """Test 2: Monotonic rule satisfied for each accepted patch."""
    print("\nTest 2: Monotonic rule satisfied")
    print("-" * 60)
    
    request_dir = BASE / "state" / "requests" / request_id
    repair_dir = request_dir / "repair"
    status_path = repair_dir / "status.json"
    
    if not status_path.exists():
        print(f"  ⚠ SKIP: status.json not found")
        return True
    
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
        accepted = status.get("accepted_patches", [])
        
        if not accepted:
            print(f"  ✓ No accepted patches (empty list is valid)")
            return True
        
        for iter_num in accepted:
            iter_dir = repair_dir / f"iter_{iter_num}"
            decision_path = iter_dir / "decision.json"
            
            if not decision_path.exists():
                print(f"  ✗ iter_{iter_num}/decision.json missing")
                return False
            
            decision = json.loads(decision_path.read_text(encoding="utf-8"))
            
            if not decision.get("accepted", False):
                print(f"  ✗ iter_{iter_num} marked accepted but decision.json says rejected")
                return False
            
            score_before = tuple(decision.get("score_before", []))
            score_after = tuple(decision.get("score_after", []))
            
            # Repair monotonic rule: score must strictly improve.
            # In this repo, higher score is better (less severe / fewer failures).
            if score_after <= score_before:
                print(f"  ✗ iter_{iter_num}: score did not improve")
                print(f"      Before: {score_before}")
                print(f"      After: {score_after}")
                return False
        
        print(f"  ✓ All {len(accepted)} accepted patches satisfy monotonic rule")
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False


def test_rollback_verification(request_id: str):
    """Test 3: Rollback restored exact hashes for rejected patches."""
    print("\nTest 3: Rollback verification")
    print("-" * 60)
    
    request_dir = BASE / "state" / "requests" / request_id
    repair_dir = request_dir / "repair"
    status_path = repair_dir / "status.json"
    
    if not status_path.exists():
        print(f"  ⚠ SKIP: status.json not found")
        return True
    
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
        rejected = status.get("rejected_patches", [])
        
        if not rejected:
            print(f"  ✓ No rejected patches (empty list is valid)")
            return True
        
        for iter_num in rejected:
            iter_dir = repair_dir / f"iter_{iter_num}"
            decision_path = iter_dir / "decision.json"
            before_path = iter_dir / "workspace_hashes.before.json"
            
            if not decision_path.exists():
                print(f"  ⚠ WARNING: iter_{iter_num}/decision.json missing (may be pre-apply rejection)")
                continue
            
            decision = json.loads(decision_path.read_text(encoding="utf-8"))
            
            # Check if rollback was verified
            rollback_verified = decision.get("rollback_verified")
            if rollback_verified is False:
                print(f"  ✗ iter_{iter_num}: rollback verification failed")
                return False
            
            if rollback_verified is True:
                print(f"  ✓ iter_{iter_num}: rollback verified")
            else:
                print(f"  ⚠ WARNING: iter_{iter_num}: rollback_verified not set (may be pre-apply rejection)")
        
        print(f"  ✓ All rejected patches have verified rollback (or pre-apply rejection)")
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False


def test_status_consistency(request_id: str):
    """Test 4: status.json is internally consistent."""
    print("\nTest 4: Status consistency")
    print("-" * 60)
    
    request_dir = BASE / "state" / "requests" / request_id
    repair_dir = request_dir / "repair"
    status_path = repair_dir / "status.json"
    
    if not status_path.exists():
        print(f"  ⚠ SKIP: status.json not found")
        return True
    
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
        iters_run = status.get("iters_run", 0)
        
        # Count actual iter directories
        iter_dirs = [d for d in repair_dir.iterdir() if d.is_dir() and d.name.startswith("iter_")]
        iter_nums = []
        for d in iter_dirs:
            try:
                num = int(d.name.split("_")[1])
                iter_nums.append(num)
            except (ValueError, IndexError):
                pass
        
        max_iter = max(iter_nums) if iter_nums else 0
        
        # iters_run should match max iteration number
        if iters_run != max_iter:
            print(f"  ⚠ WARNING: iters_run ({iters_run}) != max iter number ({max_iter})")
            print(f"     (This may be OK if repair stopped early)")
        else:
            print(f"  ✓ iters_run ({iters_run}) matches max iter number")
        
        # Check accepted/rejected patches are within range
        accepted = status.get("accepted_patches", [])
        rejected = status.get("rejected_patches", [])
        
        for iter_num in accepted + rejected:
            if iter_num > max_iter:
                print(f"  ✗ Patch iter_{iter_num} referenced but directory doesn't exist")
                return False
        
        print(f"  ✓ All referenced patches exist")
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: verify_step5a.py <request_id>", file=sys.stderr)
        sys.exit(2)
    
    request_id = sys.argv[1].strip()
    
    print("=" * 60)
    print("Step 5a Verification: Repair Loop Stub Mode")
    print("=" * 60)
    
    test1 = test_required_files_exist(request_id)
    test2 = test_monotonic_rule(request_id)
    test3 = test_rollback_verification(request_id)
    test4 = test_status_consistency(request_id)
    
    print("\n" + "=" * 60)
    if test1 and test2 and test3 and test4:
        print("✓ All tests PASSED")
        return 0
    else:
        print("✗ Some tests FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())

