#!/usr/bin/env python3
"""
Capture toolchain manifest for Tier3 repro. Writes out/toolchain_manifest.json with
image id (if in container), python version, and key compiler versions.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUT_DIR = BASE / "out"


def _safe_run(cmd: list[str], timeout: int = 5) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(BASE))
        if r.returncode == 0 and r.stdout:
            return r.stdout.strip().split("\n")[0]
    except Exception:
        pass
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    args, _ = ap.parse_known_args()
    out_path = Path(args.out).resolve() if args.out else (OUT_DIR / "toolchain_manifest.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    manifest: dict = {"schema_version": "toolchain_manifest_v1"}

    # In-container: docker image id (from hostname or env)
    if (Path("/.dockerenv")).exists():
        manifest["in_container"] = True
        # Image ID not easily available from inside; use placeholder for determinism
        manifest["container_marker"] = "tier3"
    else:
        manifest["in_container"] = False

    manifest["python_version"] = _safe_run([sys.executable, "--version"]) or _safe_run(["python3", "--version"])
    manifest["node_version"] = _safe_run(["node", "-v"])
    manifest["go_version"] = _safe_run(["go", "version"])
    manifest["dotnet_version"] = _safe_run(["dotnet", "--version"])
    manifest["tsc_version"] = _safe_run(["tsc", "-v"])

    out_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
