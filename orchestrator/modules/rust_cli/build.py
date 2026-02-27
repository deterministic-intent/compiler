#!/usr/bin/env python3
"""Build rust_cli artifact: cargo build --release --locked, cp target/release/main dist/, RUSTFLAGS with path remap"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
DIST = ROOT / "dist"

ENV = {
    **os.environ,
    "SOURCE_DATE_EPOCH": "1700000000",
    "TZ": "UTC",
    "LC_ALL": "C",
    "LANG": "C",
    "RUSTFLAGS": f"--remap-path-prefix {ROOT}=.",
}


def main() -> int:
    r = subprocess.run(
        ["cargo", "build", "--release", "--locked"],
        env=ENV,
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        return r.returncode
    DIST.mkdir(parents=True, exist_ok=True)
    exe = ROOT / "target" / "release" / "main"
    if not exe.exists():
        # Try binary name from Cargo.toml package name
        for p in (ROOT / "target" / "release").iterdir():
            if p.is_file() and os.access(p, os.X_OK):
                shutil.copy2(p, DIST / "main")
                return 0
        print("error: no main binary found in target/release", file=sys.stderr)
        return 1
    shutil.copy2(exe, DIST / "main")
    return 0


if __name__ == "__main__":
    sys.exit(main())
