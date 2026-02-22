#!/usr/bin/env python3
"""Test manifest builder determinism - Step 2 verification."""

import sys
import hashlib
from pathlib import Path
import shutil

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from nlc.db.manifest_builder import build_all_manifests


def sha256_file(p: Path) -> str:
    """Compute SHA256 hash of file."""
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_byte_identical_determinism(snapshot_id: str):
    """
    Build manifests twice and verify byte-identical output.
    
    Pass condition: sha256sum of each manifest file is identical across both builds.
    """
    print(f"Testing byte-identical determinism for snapshot: {snapshot_id}")
    print("=" * 60)
    
    snapshot_dir = BASE / "nlc" / "db" / "snapshots" / snapshot_id
    if not snapshot_dir.exists():
        print(f"ERROR: Snapshot directory not found: {snapshot_dir}")
        return False
    
    manifest_dir = snapshot_dir / "manifest"
    
    # Backup existing manifests if they exist
    backup_dir = None
    if manifest_dir.exists():
        backup_dir = snapshot_dir / "manifest.backup"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        shutil.copytree(manifest_dir, backup_dir)
        shutil.rmtree(manifest_dir)
    
    try:
        # Build 1
        print("\nBuild 1: Building manifests...")
        hashes1 = build_all_manifests(BASE, snapshot_id, "v1")
        
        # Capture file hashes from Build 1
        build1_hashes = {}
        for filename in ["intents.json", "templates.json", "modules.json", "practices.json", "toolchain_pins.json"]:
            manifest_path = manifest_dir / filename
            if manifest_path.exists():
                build1_hashes[filename] = sha256_file(manifest_path)
                print(f"  {filename}: {build1_hashes[filename]}")
        
        # Remove manifests
        shutil.rmtree(manifest_dir)
        
        # Build 2
        print("\nBuild 2: Rebuilding manifests...")
        hashes2 = build_all_manifests(BASE, snapshot_id, "v1")
        
        # Capture file hashes from Build 2
        build2_hashes = {}
        for filename in ["intents.json", "templates.json", "modules.json", "practices.json", "toolchain_pins.json"]:
            manifest_path = manifest_dir / filename
            if manifest_path.exists():
                build2_hashes[filename] = sha256_file(manifest_path)
                print(f"  {filename}: {build2_hashes[filename]}")
        
        # Compare
        print("\n" + "=" * 60)
        print("Determinism Check:")
        print("=" * 60)
        
        all_match = True
        for filename in sorted(set(build1_hashes.keys()) | set(build2_hashes.keys())):
            hash1 = build1_hashes.get(filename)
            hash2 = build2_hashes.get(filename)
            
            if hash1 is None:
                print(f"  ✗ {filename}: Missing in Build 1")
                all_match = False
            elif hash2 is None:
                print(f"  ✗ {filename}: Missing in Build 2")
                all_match = False
            elif hash1 == hash2:
                print(f"  ✓ {filename}: Byte-identical ({hash1[:16]}...)")
            else:
                print(f"  ✗ {filename}: MISMATCH")
                print(f"      Build 1: {hash1}")
                print(f"      Build 2: {hash2}")
                all_match = False
        
        if all_match:
            print("\n✓ PASS: All manifests are byte-identical across builds")
            return True
        else:
            print("\n✗ FAIL: Manifests are not byte-identical")
            return False
            
    finally:
        # Restore backup if it existed
        if backup_dir and backup_dir.exists():
            if manifest_dir.exists():
                shutil.rmtree(manifest_dir)
            shutil.move(backup_dir, manifest_dir)


def main():
    if len(sys.argv) < 2:
        print("Usage: test_manifest_determinism.py <snapshot_id>", file=sys.stderr)
        sys.exit(2)
    
    snapshot_id = sys.argv[1].strip()
    
    success = test_byte_identical_determinism(snapshot_id)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

