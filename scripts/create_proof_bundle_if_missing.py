#!/usr/bin/env python3
"""Create proof_bundle.zip for requests that have artifact.zip but no proof_bundle.zip."""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
REQUESTS_ROOT = BASE / "state" / "requests"


def main() -> int:
    if str(BASE) not in sys.path:
        sys.path.insert(0, str(BASE))
    from dcs_cli.main import _create_proof_bundle

    created = 0
    for req_dir in sorted(REQUESTS_ROOT.iterdir()) if REQUESTS_ROOT.exists() else []:
        if not req_dir.is_dir():
            continue
        request_id = req_dir.name
        artifact_zip = req_dir / "dist" / "artifact.zip"
        proof_bundle = req_dir / "dist" / "proof_bundle.zip"
        if artifact_zip.exists() and not proof_bundle.exists():
            try:
                _create_proof_bundle(request_id)
                if proof_bundle.exists():
                    print(f"Created proof_bundle for {request_id}")
                    created += 1
            except Exception as e:
                print(f"WARN: could not create proof_bundle for {request_id}: {e}", file=sys.stderr)
    if created:
        print(f"Created {created} proof_bundle(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
