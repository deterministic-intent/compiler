#!/usr/bin/env python3
import hashlib
import json
import os
import shlex
import subprocess
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
REQUESTS_ROOT = BASE / "state" / "requests"


def _fail(msg: str) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(1)


def _run_command(cmd, input_text=None, env=None):
    return subprocess.run(
        cmd,
        input=input_text.encode("utf-8") if isinstance(input_text, str) else input_text,
        capture_output=True,
        env=env,
        text=False,
    )

def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()

def _hash_tree(root: Path) -> dict:
    items = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(root)).replace("\\", "/")
            items[rel] = _sha256_file(p)
    return items

def _parse_output(stdout_bytes: bytes) -> dict:
    lines = stdout_bytes.decode("utf-8", errors="replace").strip().split("\n")
    result = {"request_id": None, "status": None, "artifact": None, "proof_bundle": None, "run_this": None}
    for line in lines:
        if line.startswith("request_id: "):
            result["request_id"] = line[12:].strip()
        elif line.startswith("status: "):
            result["status"] = line[8:].strip()
        elif line.startswith("artifact: "):
            result["artifact"] = line[10:].strip()
        elif line.startswith("proof_bundle: "):
            result["proof_bundle"] = line[14:].strip()
        elif line.startswith("RUN THIS: "):
            result["run_this"] = line[10:].strip()
    return result

def _format_run_this(request_id: str, artifact_path: Path, execute_contract: dict) -> str:
    out_root = BASE / "out" / "user_run" / request_id
    cwd_rel = str(execute_contract.get("cwd_rel", ".")).strip() or "."
    entry_cmd = execute_contract.get("entry_command", [])
    unzip_cmd = f"python3 -m zipfile -e {shlex.quote(str(artifact_path))} {shlex.quote(str(out_root))}"
    run_dir = str(out_root / cwd_rel)
    run_cmd = " ".join([shlex.quote(str(x)) for x in entry_cmd])
    return f"{unzip_cmd} && (cd {shlex.quote(run_dir)} && {run_cmd})"


def _dcs_cmd() -> list[str]:
    cmd = shutil.which("dcs")
    if cmd:
        return [cmd]
    return [sys.executable, "-m", "dcs_cli.main"]


def main() -> int:

    env = os.environ.copy()
    prompt_text = "Make a CLI that counts from 1 to 5 by 1"
    dcs_cmd = _dcs_cmd()
    p1 = _run_command(dcs_cmd, input_text=prompt_text, env=env)
    if p1.returncode != 0:
        _fail(f"FAIL user_truth: dcs exited with code {p1.returncode}")

    out1 = _parse_output(p1.stdout)
    request_id = out1["request_id"]
    status = out1["status"]
    artifact = out1["artifact"]
    proof_bundle = out1["proof_bundle"]
    run_this = out1["run_this"]

    if not request_id:
        _fail("FAIL user_truth: Missing request_id")
    if status != "PASS":
        _fail(f"FAIL user_truth: Unexpected status: {status}")
    if not run_this or run_this == "NONE":
        _fail("FAIL user_truth: RUN THIS missing")

    request_dir = REQUESTS_ROOT / request_id
    dist_dir = request_dir / "dist"
    execute_path = dist_dir / "EXECUTE.json"
    if not execute_path.exists():
        _fail("FAIL user_truth: EXECUTE.json missing")
    if not artifact or artifact == "NONE":
        _fail("FAIL user_truth: artifact missing")
    if not proof_bundle or proof_bundle == "NONE":
        _fail("FAIL user_truth: proof_bundle missing")

    artifact_path = BASE / artifact
    proof_bundle_path = BASE / proof_bundle
    if not artifact_path.exists():
        _fail("FAIL user_truth: artifact.zip missing")
    if not proof_bundle_path.exists():
        _fail("FAIL user_truth: proof_bundle.zip missing")
    try:
        execute_contract = json.loads(execute_path.read_text(encoding="utf-8"))
    except Exception:
        _fail("FAIL user_truth: EXECUTE.json invalid JSON")
    expected_run_this = _format_run_this(request_id, artifact_path, execute_contract)
    if run_this != expected_run_this:
        _fail("FAIL user_truth: RUN THIS not derived from EXECUTE.json")

    execute_bytes = execute_path.read_bytes()
    p1b = _run_command(dcs_cmd, input_text=prompt_text, env=env)
    if p1b.returncode != 0:
        _fail(f"FAIL user_truth: second dcs run exited with code {p1b.returncode}")
    out2 = _parse_output(p1b.stdout)
    request_id_2 = out2["request_id"]
    if not request_id_2:
        _fail("FAIL user_truth: Missing request_id on second run")
    execute_path_2 = REQUESTS_ROOT / request_id_2 / "dist" / "EXECUTE.json"
    if not execute_path_2.exists():
        _fail("FAIL user_truth: EXECUTE.json missing on second run")
    if execute_path_2.read_bytes() != execute_bytes:
        _fail("FAIL user_truth: EXECUTE.json not deterministic across runs")

    pre_hash = _hash_tree(request_dir)
    p2 = _run_command(dcs_cmd + ["user-verify", "--request-id", request_id], env=env)
    if p2.returncode != 0:
        _fail(f"FAIL user_truth: user-verify exited with code {p2.returncode}")
    post_hash = _hash_tree(request_dir)
    if pre_hash != post_hash:
        _fail("FAIL user_truth: user-verify mutated state/requests data")

    user_verify_path = BASE / "out" / "user_verify" / request_id / "user_verify.json"
    if not user_verify_path.exists():
        _fail("FAIL user_truth: user_verify.json missing")
    try:
        obj = json.loads(user_verify_path.read_text(encoding="utf-8"))
    except Exception:
        _fail("FAIL user_truth: user_verify.json invalid JSON")
    if obj.get("exit_code") != 0:
        _fail("FAIL user_truth: user_verify exit_code != 0")

    print("PASS user_truth")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

