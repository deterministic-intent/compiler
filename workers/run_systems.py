#!/usr/bin/env python3
"""
Deterministic systems runner: NO model.
Packages workspace/project/ into dist/ artifacts with checksums and entrypoint docs.
"""
import sys
import json
import hashlib
import shutil
import zipfile
from pathlib import Path
from datetime import datetime, timezone

def die(msg: str, code: int = 2):
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()

def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")

def write_text(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")

def _repro_mode() -> bool:
    from dcs_core.repro_env import is_repro_mode
    return is_repro_mode()


def now_utc() -> str:
    if _repro_mode():
        return "1970-01-01T00:00:00Z"
    return datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"


def _extract_intent_id(request_dir: Path) -> str:
    """Extract intent_id from REQ.json for manifest."""
    req_path = request_dir / "REQ.json"
    if not req_path.exists():
        return ""
    try:
        req = json.loads(read_text(req_path))
        intents = req.get("intents", [])
        if intents:
            return str(intents[0].get("intent_type") or intents[0].get("intent_id", "")).strip()
        return str(req.get("intent_id", "")).strip()
    except Exception:
        return ""


def _toolchain_fingerprint_hash(snapshot_id: str, request_dir: Path) -> str:
    """Deterministic hash of toolchain boundary for reproducibility."""
    base = request_dir.resolve().parents[2]  # repo root
    if snapshot_id:
        pins_path = base / "nlc" / "db" / "snapshots" / snapshot_id / "manifest" / "toolchain_pins.json"
        if pins_path.exists():
            try:
                return sha256_bytes(pins_path.read_bytes())
            except Exception:
                pass
    tc_path = base / "policy" / "toolchains_v1.json"
    if tc_path.exists():
        try:
            return sha256_bytes(f"{snapshot_id or ''}\n".encode() + tc_path.read_bytes())
        except Exception:
            pass
    return sha256_bytes(f"toolchain:{snapshot_id or 'none'}".encode())


def _stable_request_id(request_dir: Path) -> str:
    """Derive stable request_id from REQ content for repro mode (replay byte-identical)."""
    req_path = request_dir / "REQ.json"
    if not req_path.exists():
        return request_dir.name
    try:
        raw = req_path.read_bytes()
        h = hashlib.sha256(raw).hexdigest()
        return f"REPRO_{h[:16]}"
    except Exception:
        return request_dir.name

def detect_project_type(project_dir: Path) -> str:
    """Detect project type from files present."""
    if (project_dir / "package.json").exists():
        return "node_app"
    if (project_dir / "requirements.txt").exists() or (project_dir / "pyproject.toml").exists() or (project_dir / "setup.py").exists() or any(project_dir.glob("*.py")):
        return "python_app"
    if (project_dir / "Cargo.toml").exists():
        return "rust_app"
    if (project_dir / "go.mod").exists():
        return "go_app"
    if (project_dir / "foundry.toml").exists():
        return "solidity_foundry"
    if (project_dir / "index.html").exists() or (project_dir / "index.htm").exists():
        return "web_static"
    if list(project_dir.glob("*.csproj")):
        return "csharp_app"
    return "unknown"

def create_entrypoint_md(request_dir: Path, project_type: str, dist_dir: Path, project_dir: Path) -> str:
    """Create ENTRYPOINT.md with deterministic instructions."""
    lines = []
    lines.append("# ENTRYPOINT\n\n")
    lines.append(f"Project Type: {project_type}\n\n")
    lines.append("## Artifacts\n\n")
    
    artifacts = sorted([f.name for f in dist_dir.iterdir() if f.is_file()])
    for art in artifacts:
        lines.append(f"- {art}\n")
    
    lines.append("\n## Usage\n\n")
    
    if project_type == "python_app":
        lines.append("1. Extract artifact.zip\n")
        lines.append("2. Install dependencies: `pip install -r requirements.txt`\n")
        # Check for common entry points
        if (project_dir / "api.py").exists():
            lines.append("3. Run: `python api.py`\n")
        elif (project_dir / "main.py").exists():
            lines.append("3. Run: `python main.py`\n")
        elif (project_dir / "app.py").exists():
            lines.append("3. Run: `python app.py`\n")
        else:
            lines.append("3. Run: `python main.py` or `python -m <module>`\n")
    elif project_type == "node_app":
        lines.append("1. Extract artifact.zip\n")
        lines.append("2. Install dependencies: `npm install`\n")
        lines.append("3. Run: `npm start` or `node index.js`\n")
    elif project_type == "web_static":
        lines.append("1. Extract site.zip\n")
        lines.append("2. Serve with any HTTP server: `python -m http.server 8000`\n")
        lines.append("3. Open http://localhost:8000 in browser\n")
    elif project_type == "rust_app":
        lines.append("1. Extract artifact.zip\n")
        lines.append("2. Build: `cargo build --release`\n")
        lines.append("3. Run: `./target/release/<binary>`\n")
    elif project_type == "go_app":
        lines.append("1. Extract artifact.zip\n")
        lines.append("2. Build: `go build`\n")
        lines.append("3. Run: `./<binary>`\n")
    else:
        lines.append("1. Extract artifact.zip\n")
        lines.append("2. Follow project-specific README if present\n")
    
    lines.append("\n## Checksums\n\n")
    lines.append("See checksums.sha256 for file integrity verification.\n")
    
    return "".join(lines)

def build_execute_contract(request_dir: Path, project_dir: Path) -> dict | None:
    """
    Build deterministic EXECUTE.json for artifact classes that claim runtime truth.
    Returns contract dict or None if not applicable.
    """
    payload_path = request_dir / "payload.json"
    artifact_class = ""
    if payload_path.exists():
        try:
            payload = json.loads(read_text(payload_path))
            artifact_class = str(payload.get("artifact_class", "")).strip()
        except Exception:
            artifact_class = ""
    runtime_truth_classes = {"python_cli"}
    if artifact_class not in runtime_truth_classes:
        return None
    entry_file = None
    for candidate in ("main.py", "app.py", "api.py"):
        if (project_dir / candidate).exists():
            entry_file = candidate
            break
    if entry_file is None:
        py_files = sorted([p.name for p in project_dir.glob("*.py")])
        entry_file = py_files[0] if py_files else "main.py"
    command_arg = None
    req_path = request_dir / "REQ.json"
    if req_path.exists():
        try:
            req_obj = json.loads(read_text(req_path))
            intents = req_obj.get("intents", [])
            if intents and isinstance(intents, list) and isinstance(intents[0], dict):
                intent_type = str(intents[0].get("intent_type", "")).strip()
                if intent_type:
                    command_arg = intent_type.replace("_", "-")
        except Exception:
            command_arg = None
    entry_command = ["python3", "-B", entry_file]
    if command_arg:
        entry_command.append(command_arg)
    return {
        "artifact_class": artifact_class,
        "entry_command": entry_command,
        "cwd_rel": ".",
        "expected_exit_code": 0,
    }

def package_project(request_dir: Path, project_dir: Path, dist_dir: Path) -> tuple[str, dict]:
    """Package project into dist/ and return (artifact_name, manifest)."""
    project_type = detect_project_type(project_dir)
    dist_dir.mkdir(parents=True, exist_ok=True)

    # Universal artifact name (contract: artifact.zip for all; web_static keeps site.zip for compatibility)
    if project_type == "web_static":
        artifact_name = "site.zip"
    else:
        artifact_name = "artifact.zip"
    
    artifact_path = dist_dir / artifact_name
    
    # Create zip archive (deterministic ordering + fixed timestamps)
    fixed_dt = (1980, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(artifact_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Deterministic packaging: exclude runtime caches like __pycache__/.
        items = []
        for it in project_dir.rglob("*"):
            if not it.is_file():
                continue
            rel = str(it.relative_to(project_dir)).replace("\\", "/")
            if "/__pycache__/" in f"/{rel}/" or rel.startswith("__pycache__/"):
                continue
            items.append(it)
        items = sorted(items, key=lambda p: p.relative_to(project_dir).as_posix())
        for item in items:
            arcname = item.relative_to(project_dir).as_posix()
            data = item.read_bytes()
            zi = zipfile.ZipInfo(arcname)
            zi.date_time = fixed_dt
            zi.compress_type = zipfile.ZIP_DEFLATED
            # stable file perms
            zi.external_attr = (0o644 & 0xFFFF) << 16
            zf.writestr(zi, data)
    
    # Calculate checksum
    artifact_sha256 = sha256_file(artifact_path)
    
    # Create ENTRYPOINT.md
    entrypoint_md = create_entrypoint_md(request_dir, project_type, dist_dir, project_dir)
    write_text(dist_dir / "ENTRYPOINT.md", entrypoint_md)
    
    # Create EXECUTE.json if applicable
    execute_contract = build_execute_contract(request_dir, project_dir)
    execute_path = dist_dir / "EXECUTE.json"
    if execute_contract:
        write_text(execute_path, json.dumps(execute_contract, indent=2, sort_keys=True) + "\n")
    
    # Create checksums file (sorted lexicographically by path; hash file bytes only)
    checksums = {artifact_name: artifact_sha256, "ENTRYPOINT.md": sha256_bytes(entrypoint_md.encode("utf-8"))}
    if execute_contract and execute_path.exists():
        checksums["EXECUTE.json"] = sha256_file(execute_path)
    checksums_text = "\n".join(f"{h}  {n}" for n, h in sorted(checksums.items())) + "\n"
    write_text(dist_dir / "checksums.sha256", checksums_text)
    
    # Create manifest.json (repro mode: stable request_id, clamped timestamps)
    manifest_request_id = _stable_request_id(request_dir) if _repro_mode() else request_dir.name
    # Reproducibility boundary (v1)
    req_sha256 = ""
    pins_path = request_dir / "replay_pins.json"
    if pins_path.exists():
        try:
            pins = json.loads(read_text(pins_path))
            req_sha256 = pins.get("req_sha256", "")
        except Exception:
            pass
    req_path = request_dir / "REQ.json"
    if not req_sha256 and req_path.exists():
        req_sha256 = sha256_bytes(req_path.read_bytes())
    payload = {}
    if (request_dir / "payload.json").exists():
        try:
            payload = json.loads(read_text(request_dir / "payload.json"))
        except Exception:
            pass
    manifest = {
        "request_id": manifest_request_id,
        "project_type": project_type,
        "artifact": artifact_name,
        "artifact_sha256": artifact_sha256,
        "created_at_utc": now_utc(),
        "req_sha256": req_sha256,
        "snapshot_id": payload.get("knowledge_snapshot_id", ""),
        "manifest_bundle_hash": payload.get("manifest_bundle_hash", ""),
        "policy_version": payload.get("policy_version", "v1"),
        "intent_id": _extract_intent_id(request_dir),
        "adapter_versions": {"generator": "v1", "verifier": "v1"},
        "toolchain_fingerprint_hash": _toolchain_fingerprint_hash(payload.get("knowledge_snapshot_id", ""), request_dir),
        "files": {
            artifact_name: {"sha256": artifact_sha256, "size_bytes": artifact_path.stat().st_size},
            "checksums.sha256": {"sha256": sha256_bytes(checksums_text.encode("utf-8")), "size_bytes": len(checksums_text.encode("utf-8"))},
            "ENTRYPOINT.md": {"sha256": sha256_bytes(entrypoint_md.encode("utf-8")), "size_bytes": len(entrypoint_md.encode("utf-8"))},
        },
    }
    if execute_contract and execute_path.exists():
        manifest["files"]["EXECUTE.json"] = {"sha256": sha256_bytes(execute_path.read_bytes()), "size_bytes": execute_path.stat().st_size}

    n_files = sum(1 for _ in project_dir.rglob("*") if _.is_file() and "__pycache__" not in str(_))
    output_paths = [str(dist_dir / artifact_name), str(dist_dir / "manifest.json"), str(dist_dir / "checksums.sha256"), str(dist_dir / "ENTRYPOINT.md")]
    print(f"packager_called=true output_paths={','.join(output_paths)} files_packaged={n_files}", flush=True)

    return artifact_name, manifest

def main():
    if len(sys.argv) != 3:
        die("Usage: run_systems.py <REQUEST_ID> <REQUEST_DIR>")

    request_id = sys.argv[1].strip()
    request_dir = Path(sys.argv[2]).resolve()
    
    if not request_id:
        die("REQUEST_ID empty")
    if not request_dir.exists():
        die(f"REQUEST_DIR not found: {request_dir}")
    
    workspace_project = request_dir / "workspace" / "project"
    if not workspace_project.exists():
        die(f"workspace/project/ not found: {workspace_project}")
    
    dist_dir = request_dir / "dist"
    
    # Package project
    artifact_name, manifest = package_project(request_dir, workspace_project, dist_dir)
    
    # Write manifest.json (sort_keys for deterministic output)
    write_text(dist_dir / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    
    # Write meta
    wrote = [artifact_name, "checksums.sha256", "ENTRYPOINT.md", "manifest.json"]
    hashes = {
        artifact_name: manifest["artifact_sha256"],
        "checksums.sha256": manifest["files"]["checksums.sha256"]["sha256"],
        "ENTRYPOINT.md": manifest["files"]["ENTRYPOINT.md"]["sha256"],
        "manifest.json": sha256_bytes(json.dumps(manifest, indent=2).encode("utf-8")),
    }
    execute_path = dist_dir / "EXECUTE.json"
    if execute_path.exists():
        wrote.append("EXECUTE.json")
        hashes["EXECUTE.json"] = sha256_bytes(execute_path.read_bytes())
    meta = {
        "REQUEST_ID": _stable_request_id(request_dir) if _repro_mode() else request_id,
        "WROTE": sorted(wrote),
        "AT_UTC": now_utc(),
        "HASHES": {k: hashes[k] for k in sorted(hashes)},
    }
    write_text(request_dir / "systems.meta.json", json.dumps(meta, indent=2, sort_keys=True) + "\n")
    
    print(f"OK: SYSTEMS_PACKAGED_{artifact_name}")

if __name__ == "__main__":
    main()
