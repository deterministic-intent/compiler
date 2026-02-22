#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import time
import pty
import shutil
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def _fail(msg: str) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(1)


def _run(cmd, input_text=None, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        input=input_text.encode("utf-8") if isinstance(input_text, str) else input_text,
        capture_output=True,
        env=env,
        text=False,
    )


def _pty_run(cmd, input_text: str, env=None) -> str:
    master_fd, slave_fd = pty.openpty()
    p = subprocess.Popen(
        cmd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=env,
        cwd=str(BASE),
    )
    os.close(slave_fd)
    os.write(master_fd, (input_text + "\n").encode("utf-8"))
    out = b""
    while True:
        try:
            chunk = os.read(master_fd, 4096)
            if not chunk:
                break
            out += chunk
        except OSError:
            break
        if p.poll() is not None:
            break
    # allow any remaining output
    time.sleep(0.1)
    try:
        while True:
            chunk = os.read(master_fd, 4096)
            if not chunk:
                break
            out += chunk
    except OSError:
        pass
    os.close(master_fd)
    p.wait(timeout=60)
    return out.decode("utf-8", errors="replace")


def _extract_summary(stdout: str) -> dict:
    res = {"request_id": None, "status": None, "artifact": None, "proof_bundle": None, "run_this": None}
    for line in stdout.splitlines():
        if line.startswith("request_id: "):
            res["request_id"] = line[12:].strip()
        elif line.startswith("status: "):
            res["status"] = line[8:].strip()
        elif line.startswith("artifact: "):
            res["artifact"] = line[10:].strip()
        elif line.startswith("proof_bundle: "):
            res["proof_bundle"] = line[14:].strip()
        elif line.startswith("RUN THIS: "):
            res["run_this"] = line[10:].strip()
    return res


def _dcs_cmd() -> list[str]:
    cmd = shutil.which("dcs")
    if cmd:
        return [cmd]
    return [sys.executable, "-m", "dcs_cli.main"]


def main() -> int:

    env = os.environ.copy()
    prompt = "Make a CLI that counts from 1 to 5 by 1"

    # Case A: non-TTY (pipe)
    dcs_cmd = _dcs_cmd()
    p1 = _run(dcs_cmd, input_text=prompt, env=env)
    out1 = p1.stdout.decode("utf-8", errors="replace")
    if "Deterministic Compiler System" in out1:
        _fail("FAIL cli_branding_r1:A: banner should not appear in non-TTY")
    for label in ["wiring + context", "snapshot + manifests", "deterministic selection", "verifier", "repair loop", "contract enforcement", "replay readiness"]:
        if f"[loading] {label}" not in out1:
            _fail(f"FAIL cli_branding_r1:A: missing loading line for {label}")
    if "request_id: " not in out1 or "status: " not in out1:
        _fail("FAIL cli_branding_r1:A: missing summary lines")
    summary = _extract_summary(out1)
    if not summary.get("request_id"):
        _fail("FAIL cli_branding_r1:A: missing request_id")
    if not summary.get("run_this"):
        _fail("FAIL cli_branding_r1:A: missing RUN THIS line")

    request_id = summary["request_id"]

    # Case B: TTY via PTY
    out2 = _pty_run(dcs_cmd, prompt, env=env)
    if "Deterministic Compiler System" not in out2:
        _fail("FAIL cli_branding_r1:B: banner missing in TTY")
    if "[loading] wiring + context" not in out2:
        _fail("FAIL cli_branding_r1:B: missing loading output in TTY")

    # Case C: --json
    p3 = _run(dcs_cmd + ["--json", "run", "--request-id", request_id], env=env)
    out3 = p3.stdout.decode("utf-8", errors="replace").strip()
    if not out3.startswith("{"):
        _fail("FAIL cli_branding_r1:C: JSON output expected")
    if "Deterministic Compiler System" in out3 or "[loading]" in out3:
        _fail("FAIL cli_branding_r1:C: banner/progress should not appear in JSON mode")

    # Case D: replay clamp
    replay_id = f"{request_id}-BRAND"
    env_replay = env.copy()
    env_replay["DCS_REPRO"] = "1"
    p4 = _run(dcs_cmd + ["replay", request_id, "gate6_complete", "--replay-id", replay_id], env=env_replay)
    out4 = p4.stdout.decode("utf-8", errors="replace")
    if "Deterministic Compiler System" in out4 or "[loading]" in out4:
        _fail("FAIL cli_branding_r1:D: replay must suppress banner/progress")

    print("PASS cli_branding_r1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

