#!/usr/bin/env python3
"""Build cpp_cli artifact: g++ -std=c++20 -O2 -Wl,--build-id=none -ffile-prefix-map=$PWD=. -fdebug-prefix-map=$PWD=. -o dist/main src/main.cpp && strip --strip-debug dist/main"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
SRC = ROOT / "src"
DIST = ROOT / "dist"

ENV = {
    **os.environ,
    "SOURCE_DATE_EPOCH": "1700000000",
    "TZ": "UTC",
    "LC_ALL": "C",
    "LANG": "C",
}


def main() -> int:
    DIST.mkdir(parents=True, exist_ok=True)
    pwd = str(ROOT)
    # Assume main.cpp (common for cpp); fallback to main.cc if needed
    main_src = SRC / "main.cpp"
    if not main_src.exists():
        main_src = SRC / "main.cc"
    r = subprocess.run(
        [
            "g++",
            "-std=c++20",
            "-O2",
            "-Wl,--build-id=none",
            f"-ffile-prefix-map={pwd}=.",
            f"-fdebug-prefix-map={pwd}=.",
            "-o",
            str(DIST / "main"),
            str(main_src),
        ],
        env=ENV,
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        return r.returncode
    return subprocess.run(
        ["strip", "--strip-debug", str(DIST / "main")],
        env=ENV,
        cwd=str(ROOT),
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
