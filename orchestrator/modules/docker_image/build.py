#!/usr/bin/env python3
"""
docker_image build: deterministic context pack.
Produces dist/Dockerfile, dist/context.tar, dist/base_image_ref.txt.
No docker build. Python tar only. Snapshot must provide base_image_ref.
"""
from __future__ import annotations

import io
import json
import os
import re
import tarfile
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
BASE = Path(__file__).resolve().parents[3]  # orchestrator/modules/docker_image -> repo root
DIST = ROOT / "dist"
SNAPSHOT_ID = os.environ.get("NLC_DB_SNAPSHOT_ID") or os.environ.get("NLC_SNAPSHOT_ID", "")
SNAP_ROOT = BASE / "nlc" / "db" / "snapshots"
EPOCH = int(os.environ.get("SOURCE_DATE_EPOCH", "1700000000"))


def _die(code: str) -> None:
    print(f"ERROR: {code}", file=sys.stderr)
    sys.exit(2)


def _get_base_image_ref() -> str:
    if not SNAPSHOT_ID:
        _die("DOCKER_BASE_IMAGE_REF_MISSING")
    cfg_path = SNAP_ROOT / SNAPSHOT_ID / "docker_image.json"
    if not cfg_path.exists():
        _die("DOCKER_BASE_IMAGE_REF_MISSING")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    ref = cfg.get("base_image_ref")
    if not ref or not isinstance(ref, str):
        _die("DOCKER_BASE_IMAGE_REF_MISSING")
    ref = ref.strip()
    if not re.match(r"^[^@]+@sha256:[a-f0-9]{64}$", ref):
        _die("DOCKER_BASE_IMAGE_REF_MISSING")
    return ref


def _canonicalize_dockerfile(content: str) -> str:
    """LF only, strip trailing whitespace per line, single trailing newline."""
    try:
        lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        normalized = [line.rstrip() for line in lines]
        result = "\n".join(normalized)
        if result and not result.endswith("\n"):
            result += "\n"
        return result
    except Exception:
        _die("DOCKER_DOCKERFILE_CANONICALIZE_FAIL")


def _write_tar_deterministic(tar_path: Path, members: list[tuple[str, bytes, int]]) -> None:
    """Write deterministic tar. members: (arcname, data, mode). Sort by arcname. Dirs use data=b''."""
    members = sorted(members, key=lambda x: x[0])
    try:
        with tarfile.open(tar_path, "w:", format=tarfile.GNU_FORMAT) as tf:
            for arcname, data, mode in members:
                if not arcname.endswith("/") and (mode & 0o111) != 0:
                    _die("DOCKER_CONTEXT_EXECUTABLE_FORBIDDEN")
                info = tarfile.TarInfo(arcname)
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                info.mtime = EPOCH
                if arcname.endswith("/"):
                    info.type = tarfile.DIRTYPE
                    info.mode = 0o755
                    info.size = 0
                    tf.addfile(info, None)
                else:
                    info.size = len(data)
                    info.mode = 0o644
                    tf.addfile(info, io.BytesIO(data))
    except SystemExit:
        raise
    except Exception:
        _die("DOCKER_CONTEXT_TAR_WRITE_FAIL")


def main() -> int:
    base_ref = _get_base_image_ref()
    dockerfile_content = f"FROM {base_ref}\n"
    dockerfile_canon = _canonicalize_dockerfile(dockerfile_content)
    readme_content = "Docker build context pack (v1).\n"

    DIST.mkdir(parents=True, exist_ok=True)
    (DIST / "Dockerfile").write_text(dockerfile_canon, encoding="utf-8", newline="\n")
    (DIST / "base_image_ref.txt").write_text(base_ref + "\n", encoding="utf-8", newline="\n")

    dockerfile_bytes = dockerfile_canon.encode("utf-8")
    readme_bytes = readme_content.encode("utf-8")
    members = [
        ("Dockerfile", dockerfile_bytes, 0o644),
        ("app/", b"", 0o755),
        ("app/README.txt", readme_bytes, 0o644),
    ]
    tar_path = DIST / "context.tar"
    _write_tar_deterministic(tar_path, members)
    return 0


if __name__ == "__main__":
    sys.exit(main())
