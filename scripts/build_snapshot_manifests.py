#!/usr/bin/env python3
"""Build manifests for a DB snapshot - Step 2 tool."""

import sys
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

try:
    from nlc.db.manifest_builder import build_all_manifests, compute_manifest_bundle_hash
    from policy import get_default_policy_version
except ImportError as e:
    print(f"ERROR: Import failed: {e}", file=sys.stderr)
    sys.exit(1)


def print_usage() -> None:
    print("Usage: build_snapshot_manifests.py <snapshot_id> [policy_version]", file=sys.stderr)
    print("  snapshot_id: Snapshot ID (directory name under nlc/db/snapshots/)", file=sys.stderr)
    print("  policy_version: Optional policy version (defaults to v1)", file=sys.stderr)


def main():
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(2)
    
    if sys.argv[1] in ("-h", "--help"):
        print_usage()
        sys.exit(0)
    
    snapshot_id = sys.argv[1].strip()
    policy_version = sys.argv[2].strip() if len(sys.argv) > 2 else None
    
    if not snapshot_id:
        print("ERROR: snapshot_id is required", file=sys.stderr)
        sys.exit(2)
    
    if policy_version is None:
        policy_version = get_default_policy_version()
    
    try:
        # Build all manifests
        manifest_hashes = build_all_manifests(BASE, snapshot_id, policy_version)
        
        # Compute bundle hash
        bundle_hash = compute_manifest_bundle_hash(manifest_hashes)
        
        # Output results
        result = {
            "snapshot_id": snapshot_id,
            "policy_version": policy_version,
            "manifest_hashes": manifest_hashes,
            "manifest_bundle_hash": bundle_hash,
        }
        
        print(json.dumps(result, indent=2, sort_keys=True))
        print(f"\n✓ Manifests built successfully for snapshot {snapshot_id}", file=sys.stderr)
        print(f"  Manifest directory: nlc/db/snapshots/{snapshot_id}/manifest/", file=sys.stderr)
        print(f"  Bundle hash: {bundle_hash}", file=sys.stderr)
        
        sys.exit(0)
        
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Failed to build manifests: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

