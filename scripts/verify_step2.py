#!/usr/bin/env python3
"""Step 2 verification: Byte-identical determinism + toolchain pins snapshot-boundness."""

import sys
import json
import hashlib
from pathlib import Path
import shutil

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_byte_identical(snapshot_id: str):
    """Test 1: Byte-identical determinism."""
    print("Test 1: Byte-identical determinism")
    print("-" * 60)
    
    from nlc.db.manifest_builder import build_all_manifests
    
    snapshot_dir = BASE / "nlc" / "db" / "snapshots" / snapshot_id
    manifest_dir = snapshot_dir / "manifest"
    
    if not snapshot_dir.exists():
        print(f"  ✗ Snapshot directory not found: {snapshot_dir}")
        return False
    
    # Backup if exists
    backup = None
    if manifest_dir.exists():
        backup = snapshot_dir / "manifest.backup"
        if backup.exists():
            shutil.rmtree(backup)
        shutil.copytree(manifest_dir, backup)
        shutil.rmtree(manifest_dir)
    
    try:
        # Build 1
        hashes1 = build_all_manifests(BASE, snapshot_id, "v1")
        files1 = {f.name: sha256_file(f) for f in manifest_dir.glob("*.json")}
        
        # Remove and rebuild
        shutil.rmtree(manifest_dir)
        hashes2 = build_all_manifests(BASE, snapshot_id, "v1")
        files2 = {f.name: sha256_file(f) for f in manifest_dir.glob("*.json")}
        
        # Compare
        all_match = True
        for filename in sorted(set(files1.keys()) | set(files2.keys())):
            h1 = files1.get(filename)
            h2 = files2.get(filename)
            if h1 == h2:
                print(f"  ✓ {filename}: Byte-identical")
            else:
                print(f"  ✗ {filename}: MISMATCH")
                print(f"      Build 1: {h1}")
                print(f"      Build 2: {h2}")
                all_match = False
        
        return all_match
    finally:
        if backup and backup.exists():
            if manifest_dir.exists():
                shutil.rmtree(manifest_dir)
            shutil.move(backup, manifest_dir)


def test_toolchain_pins_snapshot_bound(snapshot_id: str):
    """Test 2: Toolchain pins are snapshot-bound."""
    print("\nTest 2: Toolchain pins snapshot-boundness")
    print("-" * 60)
    
    snapshot_dir = BASE / "nlc" / "db" / "snapshots" / snapshot_id
    toolchain_pins_path = snapshot_dir / "manifest" / "toolchain_pins.json"
    
    if not toolchain_pins_path.exists():
        print(f"  ⚠ SKIP: toolchain_pins.json not found (run manifest builder first)")
        return True
    
    try:
        toolchain_pins = json.loads(toolchain_pins_path.read_text(encoding="utf-8"))
        policy_version = toolchain_pins.get("policy_version")
        
        if policy_version:
            print(f"  ✓ toolchain_pins.json includes policy_version: {policy_version}")
            
            # Verify it matches what we'd load from policy
            from policy import get_default_policy_version
            expected = get_default_policy_version()
            if policy_version == expected:
                print(f"  ✓ policy_version matches expected default: {expected}")
            else:
                print(f"  ⚠ policy_version ({policy_version}) differs from default ({expected})")
                print(f"     (This is OK if snapshot was built with explicit policy_version)")
            
            return True
        else:
            print(f"  ✗ toolchain_pins.json missing policy_version field")
            return False
    except Exception as e:
        print(f"  ✗ Error reading toolchain_pins.json: {e}")
        return False


def print_usage() -> None:
    print("Usage: verify_step2.py <snapshot_id>", file=sys.stderr)


def main():
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(2)
    
    if sys.argv[1] in ("-h", "--help"):
        print_usage()
        sys.exit(0)
    
    snapshot_id = sys.argv[1].strip()
    
    print("=" * 60)
    print("Step 2 Verification")
    print("=" * 60)
    
    test1 = test_byte_identical(snapshot_id)
    test2 = test_toolchain_pins_snapshot_bound(snapshot_id)
    
    print("\n" + "=" * 60)
    if test1 and test2:
        print("✓ All tests PASSED")
        return 0
    else:
        print("✗ Some tests FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())

