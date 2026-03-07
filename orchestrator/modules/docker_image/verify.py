#!/usr/bin/env python3
"""
docker_image verify: Dockerfile constraints + context.tar structure.
Hard-fail on forbidden directives. Validate tar contents.
"""
from __future__ import annotations

import os
import re
import tarfile
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
DIST = ROOT / "dist"
EPOCH = int(os.environ.get("SOURCE_DATE_EPOCH", "1700000000"))

ALLOWLIST = ["Dockerfile", "app", "app/README.txt"]


def _die(code: str) -> None:
    print(f"ERROR: {code}", file=sys.stderr)
    sys.exit(2)


def _verify_dist_exists() -> None:
    for name in ["Dockerfile", "context.tar", "base_image_ref.txt"]:
        if not (DIST / name).exists():
            _die("DOCKER_DIST_MISSING")


def _verify_dockerfile(dockerfile_path: Path) -> None:
    content = dockerfile_path.read_text(encoding="utf-8")
    lines = content.split("\n")
    first_nonblank = None
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if first_nonblank is None:
            first_nonblank = s
        upper = s.upper()
        if "ARG" in upper and re.search(r"\bARG\b", upper):
            _die("DOCKER_FORBIDDEN_ARG")
        if "RUN" in upper and re.search(r"\bRUN\b", upper):
            _die("DOCKER_FORBIDDEN_RUN")
        if "ADD" in upper and re.search(r"\bADD\b", upper):
            _die("DOCKER_FORBIDDEN_ADD")
        if "ONBUILD" in upper:
            _die("DOCKER_FORBIDDEN_ONBUILD")
        if "COPY --FROM=" in upper or "COPY--FROM=" in upper.replace(" ", ""):
            _die("DOCKER_FORBIDDEN_MULTISTAGE")
        if "LABEL" in upper and re.search(r"\bLABEL\b", upper):
            _die("DOCKER_FORBIDDEN_LABEL")
    from_count = sum(1 for ln in content.split("\n") if re.search(r"^\s*FROM\s+", ln, re.I))
    if from_count > 1:
        _die("DOCKER_FORBIDDEN_MULTISTAGE")
    if first_nonblank is not None:
        if not re.match(r"^FROM\s+[^@\s]+@sha256:[a-f0-9]{64}\s*$", first_nonblank, re.I):
            _die("DOCKER_FROM_NOT_DIGEST_PINNED")


def _verify_context_tar(tar_path: Path) -> None:
    try:
        with tarfile.open(tar_path, "r:*") as tf:
            names = sorted(tf.getnames())
            expected = sorted(ALLOWLIST)
            if names != expected:
                _die("DOCKER_CONTEXT_INVALID")
            for member in tf.getmembers():
                if member.uid != 0 or member.gid != 0:
                    _die("DOCKER_CONTEXT_INVALID")
                if member.mtime != EPOCH:
                    _die("DOCKER_CONTEXT_INVALID")
                if member.isdir():
                    if (member.mode & 0o777) != 0o755:
                        _die("DOCKER_CONTEXT_INVALID")
                else:
                    if member.isfile() and (member.mode & 0o111) != 0:
                        _die("DOCKER_CONTEXT_EXECUTABLE_FORBIDDEN")
                    if (member.mode & 0o777) != 0o644:
                        _die("DOCKER_CONTEXT_INVALID")
    except tarfile.TarError:
        _die("DOCKER_CONTEXT_INVALID")


def main() -> int:
    _verify_dist_exists()
    _verify_dockerfile(DIST / "Dockerfile")
    _verify_context_tar(DIST / "context.tar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
