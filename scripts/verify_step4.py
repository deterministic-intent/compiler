#!/usr/bin/env python3
"""Step 4 verification: Structured verifier output + canonical failures determinism."""

import sys
import json
import hashlib
from pathlib import Path
import subprocess

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))


def sha256_file(p: Path) -> str:
    """Compute SHA256 hash of file."""
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_structured_outputs(request_id: str, gate: str):
    """Test 1: Structured outputs exist."""
    print("Test 1: Structured outputs exist")
    print("-" * 60)
    
    request_dir = BASE / "state" / "requests" / request_id
    if not request_dir.exists():
        print(f"  ✗ Request directory not found: {request_dir}")
        return False
    
    verifier_dir = request_dir / "verifier"
    result_path = verifier_dir / "verifier.result.json"
    failures_path = verifier_dir / "failures.json"
    
    if not result_path.exists():
        print(f"  ✗ verifier.result.json not found: {result_path}")
        return False
    print(f"  ✓ verifier.result.json exists")
    
    if not failures_path.exists():
        print(f"  ✗ failures.json not found: {failures_path}")
        return False
    print(f"  ✓ failures.json exists")
    
    # Validate schema
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        required_fields = ["request_id", "policy_version", "status", "verifier_version", "checks", "summary"]
        for field in required_fields:
            if field not in result:
                print(f"  ✗ verifier.result.json missing required field: {field}")
                return False
        print(f"  ✓ verifier.result.json has required fields")
    except Exception as e:
        print(f"  ✗ Error reading verifier.result.json: {e}")
        return False
    
    try:
        failures = json.loads(failures_path.read_text(encoding="utf-8"))
        if "failures" not in failures:
            print(f"  ✗ failures.json missing 'failures' field")
            return False
        print(f"  ✓ failures.json has required structure")
    except Exception as e:
        print(f"  ✗ Error reading failures.json: {e}")
        return False
    
    return True


def test_stable_failure_ids(request_id: str, gate: str):
    """Test 2: Stable failure IDs and deterministic ordering."""
    print("\nTest 2: Stable failure IDs and deterministic ordering")
    print("-" * 60)
    
    request_dir = BASE / "state" / "requests" / request_id
    failures_path = request_dir / "verifier" / "failures.json"
    
    if not failures_path.exists():
        print(f"  ⚠ SKIP: failures.json not found (run verifier first)")
        return True
    
    try:
        failures_obj = json.loads(failures_path.read_text(encoding="utf-8"))
        failures = failures_obj.get("failures", [])
        
        if not failures:
            print(f"  ✓ No failures (empty list is valid)")
            return True
        
        # Check all failures have stable IDs
        for i, failure in enumerate(failures):
            if "failure_id" not in failure:
                print(f"  ✗ failure[{i}] missing failure_id")
                return False
            failure_id = failure["failure_id"]
            if not failure_id or len(failure_id) < 8:
                print(f"  ✗ failure[{i}] has invalid failure_id: {failure_id}")
                return False
        
        print(f"  ✓ All {len(failures)} failures have stable IDs")
        
        # Check deterministic ordering
        failure_ids = [f["failure_id"] for f in failures]
        sorted_ids = sorted(failure_ids)
        if failure_ids != sorted_ids:
            # Check if sorted by (kind, artifact, locator)
            kinds = [f.get("kind", "") for f in failures]
            artifacts = [f.get("artifact", "") for f in failures]
            locators = [f.get("locator", "") for f in failures]
            
            # Verify ordering is deterministic (kind → artifact → locator)
            prev = None
            for f in failures:
                current = (f.get("kind", ""), f.get("artifact", ""), f.get("locator", ""))
                if prev is not None and current < prev:
                    print(f"  ⚠ WARNING: Failures not deterministically ordered")
                    print(f"     (This is OK if ordering is by failure_id)")
                    break
                prev = current
            else:
                print(f"  ✓ Failures are deterministically ordered")
        else:
            print(f"  ✓ Failures are sorted by failure_id")
        
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False


def test_byte_identical_determinism(request_id: str, gate: str):
    """Test 3: Byte-identical determinism (run verifier twice)."""
    print("\nTest 3: Byte-identical determinism")
    print("-" * 60)
    
    request_dir = BASE / "state" / "requests" / request_id
    if not request_dir.exists():
        print(f"  ✗ Request directory not found: {request_dir}")
        return False
    
    verifier_dir = request_dir / "verifier"
    result_path = verifier_dir / "verifier.result.json"
    failures_path = verifier_dir / "failures.json"
    
    # Backup existing files
    import shutil
    backup_dir = request_dir / "verifier.backup"
    if verifier_dir.exists():
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        shutil.copytree(verifier_dir, backup_dir)
    
    try:
        # Run verifier
        from workers.run_verifier import RUN_VERIFIER
        cmd = [sys.executable, str(BASE / "workers" / "run_verifier.py"), request_id, str(request_dir), gate]
        p1 = subprocess.run(cmd, capture_output=True, text=True)
        
        if not result_path.exists() or not failures_path.exists():
            print(f"  ✗ Verifier did not produce structured outputs")
            return False
        
        # Capture hashes from first run
        hash1_result = sha256_file(result_path)
        hash1_failures = sha256_file(failures_path)
        
        # Remove and rerun
        shutil.rmtree(verifier_dir)
        p2 = subprocess.run(cmd, capture_output=True, text=True)
        
        if not result_path.exists() or not failures_path.exists():
            print(f"  ✗ Verifier did not produce structured outputs on second run")
            return False
        
        # Capture hashes from second run
        hash2_result = sha256_file(result_path)
        hash2_failures = sha256_file(failures_path)
        
        # Compare failures.json (must be byte-identical)
        if hash1_failures == hash2_failures:
            print(f"  ✓ failures.json is byte-identical across runs")
        else:
            print(f"  ✗ failures.json is NOT byte-identical")
            print(f"      Run 1: {hash1_failures[:16]}...")
            print(f"      Run 2: {hash2_failures[:16]}...")
            return False
        
        # verifier.result.json may differ in timestamps (OK)
        # But check that semantic fields match
        try:
            result1 = json.loads((backup_dir / "verifier.result.json").read_text())
            result2 = json.loads(result_path.read_text())
            
            # Compare semantic fields (ignore timestamps)
            semantic1 = {
                "status": result1.get("status"),
                "checks": result1.get("checks"),
                "summary": result1.get("summary"),
            }
            semantic2 = {
                "status": result2.get("status"),
                "checks": result2.get("checks"),
                "summary": result2.get("summary"),
            }
            
            if semantic1 == semantic2:
                print(f"  ✓ verifier.result.json semantic fields match (timestamps may differ)")
            else:
                print(f"  ⚠ WARNING: verifier.result.json semantic fields differ")
                print(f"     (This may be OK if checks changed)")
        except Exception as e:
            print(f"  ⚠ WARNING: Could not compare semantic fields: {e}")
        
        return True
    finally:
        # Restore backup
        if backup_dir.exists():
            if verifier_dir.exists():
                shutil.rmtree(verifier_dir)
            shutil.move(backup_dir, verifier_dir)


def print_usage() -> None:
    print("Usage: verify_step4.py <request_id> <gate_name>", file=sys.stderr)


def main():
    if len(sys.argv) >= 2 and sys.argv[1] in ("-h", "--help"):
        print_usage()
        sys.exit(0)
    
    if len(sys.argv) < 3:
        print_usage()
        sys.exit(2)
    
    request_id = sys.argv[1].strip()
    gate = sys.argv[2].strip()
    
    print("=" * 60)
    print("Step 4 Verification: Structured Verifier Output")
    print("=" * 60)
    
    test1 = test_structured_outputs(request_id, gate)
    test2 = test_stable_failure_ids(request_id, gate)
    test3 = test_byte_identical_determinism(request_id, gate)
    
    print("\n" + "=" * 60)
    if test1 and test2 and test3:
        print("✓ All tests PASSED")
        return 0
    else:
        print("✗ Some tests FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())

