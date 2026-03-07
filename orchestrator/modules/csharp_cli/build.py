#!/usr/bin/env python3
"""Build csharp_cli artifact: dotnet build -c Release /p:Deterministic=true /p:ContinuousIntegrationBuild=true, copy dll to dist"""
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
}


def main() -> int:
    r = subprocess.run(
        [
            "dotnet",
            "build",
            "-c",
            "Release",
            "/p:Deterministic=true",
            "/p:ContinuousIntegrationBuild=true",
        ],
        env=ENV,
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        return r.returncode
    DIST.mkdir(parents=True, exist_ok=True)
    # Find built dll in bin/Release/net* (dotnet standard layout)
    bin_release = ROOT / "bin" / "Release"
    copied = 0
    if bin_release.exists():
        for p in sorted(bin_release.rglob("*.dll")):
            if "ref" not in str(p) and "refs" not in str(p):
                shutil.copy2(p, DIST / p.name)
                copied += 1
    if copied == 0:
        print("error: no dll found after dotnet build", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
