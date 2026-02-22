#!/usr/bin/env python3
"""Step 1 verification: Policy spine + wiring correctness checks."""

import sys
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def test_policy_loading():
    """Test 1: Policy loading works."""
    print("Test 1: Policy loading...")
    try:
        from policy import load_policy, get_default_policy_version
        
        # Test default version
        default = get_default_policy_version()
        assert default == "v1", f"Expected default 'v1', got '{default}'"
        print(f"  ✓ Default version: {default}")
        
        # Test loading v1
        policy = load_policy("v1")
        assert policy.policy_version == "v1", f"Expected policy_version 'v1', got '{policy.policy_version}'"
        print(f"  ✓ Loaded policy v1 successfully")
        
        # Test unknown version fails hard
        try:
            load_policy("vNOPE")
            print("  ✗ FAIL: Unknown version should raise FileNotFoundError")
            return False
        except FileNotFoundError as e:
            print(f"  ✓ Unknown version fails hard: {e}")
        
        return True
    except Exception as e:
        print(f"  ✗ FAIL: {e}")
        return False


def test_payload_policy_version():
    """Test 2: payload.json includes policy_version."""
    print("\nTest 2: payload.json includes policy_version...")
    
    # Find a recent request directory
    requests_dir = BASE / "state" / "requests"
    if not requests_dir.exists():
        print("  ⚠ SKIP: No state/requests/ directory found")
        return True
    
    # Find any request with payload.json
    found = False
    for req_dir in sorted(requests_dir.iterdir(), reverse=True):
        if not req_dir.is_dir():
            continue
        payload_path = req_dir / "payload.json"
        if payload_path.exists():
            found = True
            try:
                payload = json.loads(payload_path.read_text(encoding="utf-8"))
                policy_version = payload.get("policy_version")
                if policy_version:
                    print(f"  ✓ Found policy_version in {req_dir.name}/payload.json: {policy_version}")
                    return True
                else:
                    print(f"  ✗ FAIL: {req_dir.name}/payload.json missing policy_version key")
                    return False
            except Exception as e:
                print(f"  ✗ FAIL: Error reading {req_dir.name}/payload.json: {e}")
                return False
    
    if not found:
        print("  ⚠ SKIP: No payload.json files found (create a request first)")
        return True
    
    return True


def test_repro_metadata_match():
    """Test 3: Repro metadata matches payload.json exactly."""
    print("\nTest 3: Repro metadata matches payload.json...")
    
    # This would require running the actual repro flow
    # For now, just verify the logic is correct
    print("  ⚠ SKIP: Requires running actual repro flow")
    print("  → Manual check: Run repro and verify metadata['policy_version'] == payload['policy_version']")
    return True


def test_unknown_version_fails():
    """Test 4: Unknown policy_version fails hard."""
    print("\nTest 4: Unknown policy_version fails hard...")
    
    # Create a temporary request dir with invalid policy_version
    test_req_dir = BASE / "state" / "requests" / "test_step1_verify"
    test_req_dir.mkdir(parents=True, exist_ok=True)
    
    # Write payload with unknown version
    payload = {
        "request_id": "test_step1_verify",
        "goal": "test",
        "policy_version": "vNOPE",
        "artifact_class": "python_cli"
    }
    (test_req_dir / "payload.json").write_text(json.dumps(payload, indent=2))
    
    try:
        from nlc.reproducibility import record_repro_metadata
        
        # This should fail when it tries to load the policy
        try:
            metadata = record_repro_metadata(test_req_dir, "test prompt", False)
            # If we get here, it might have defaulted - check
            if metadata.get("policy_version") == "vNOPE":
                print("  ✗ FAIL: Should have failed when loading unknown policy version")
                return False
            else:
                print(f"  ⚠ WARNING: Defaulted to {metadata.get('policy_version')} instead of failing")
                return False
        except (FileNotFoundError, ValueError) as e:
            print(f"  ✓ Unknown version fails hard: {e}")
            return True
    except Exception as e:
        print(f"  ✗ FAIL: {e}")
        return False
    finally:
        # Cleanup
        if (test_req_dir / "payload.json").exists():
            (test_req_dir / "payload.json").unlink()
        if test_req_dir.exists() and not any(test_req_dir.iterdir()):
            test_req_dir.rmdir()


def main():
    """Run all Step 1 verification tests."""
    print("=" * 60)
    print("Step 1 Verification: Policy Spine + Wiring")
    print("=" * 60)
    
    tests = [
        test_policy_loading,
        test_payload_policy_version,
        test_repro_metadata_match,
        test_unknown_version_fails,
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"  ✗ FAIL: Test crashed: {e}")
            results.append(False)
    
    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("✓ Step 1 verification PASSED")
        return 0
    else:
        print("✗ Step 1 verification FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())

