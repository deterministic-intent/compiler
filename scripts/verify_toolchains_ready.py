#!/usr/bin/env python3
"""
Verify required toolchains are present and executable per policy/toolchains_v1.json.
- For each required tool: binary on PATH, probe command executes, version captured.
- Emits PASS or FAIL with canonical failure IDs (TOOLCHAIN_*_MISSING).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def _fail(msg: str, failure_id: str = "TOOLCHAIN_VERIFY_FAILED") -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    print(f"FAILURE_ID: {failure_id}", file=sys.stderr)
    sys.exit(2)


def _load_toolchains_config() -> dict:
    """Load policy/toolchains_v1.json or fall back to policy_v1 tier3_build.enabled_checks."""
    path = BASE / "policy" / "toolchains_v1.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("tools", {})
        except Exception as e:
            _fail(f"Invalid toolchains_v1.json: {e}", "TOOLCHAIN_POLICY_INVALID")
    # Fallback: load policy_v1 and derive from tier3_build
    policy_path = BASE / "policy" / "policy_v1.json"
    if not policy_path.exists():
        _fail("policy/toolchains_v1.json and policy/policy_v1.json not found", "TOOLCHAIN_POLICY_MISSING")
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        enabled = policy.get("tier3_build", {}).get("enabled_checks", {})
        # Map enabled check names to standard toolchain entries
        tool_map = {
            "typescript": {"binary": "tsc", "probe": ["--version"], "failure_id": "TOOLCHAIN_TYPESCRIPT_MISSING"},
            "php": {"binary": "php", "probe": ["-v"], "failure_id": "TOOLCHAIN_PHP_MISSING"},
            "ruby": {"binary": "ruby", "probe": ["-v"], "failure_id": "TOOLCHAIN_RUBY_MISSING"},
            "c": {"binary": "gcc", "probe": ["--version"], "failure_id": "TOOLCHAIN_C_MISSING"},
            "cpp": {"binary": "g++", "probe": ["--version"], "failure_id": "TOOLCHAIN_CPP_MISSING"},
            "csharp": {"binary": "dotnet", "probe": ["--info"], "failure_id": "TOOLCHAIN_CSHARP_MISSING"},
            "kotlin": {"binary": "kotlinc", "probe": ["-version"], "failure_id": "TOOLCHAIN_KOTLIN_MISSING"},
            "solidity": {"binary": "solc", "probe": ["--version"], "failure_id": "TOOLCHAIN_SOLIDITY_MISSING"},
            "docker": {"binary": "docker", "probe": ["--version"], "failure_id": "TOOLCHAIN_DOCKER_MISSING"},
            "sql": {"binary": "sqlite3", "probe": ["--version"], "failure_id": "TOOLCHAIN_SQL_MISSING"},
            "mongodb": {"binary": "mongosh", "probe": ["--version"], "failure_id": "TOOLCHAIN_MONGODB_MISSING"},
            "html": {"binary": "python3", "probe": ["-c", "import html.parser; print('ok')"], "failure_id": "TOOLCHAIN_HTML_MISSING"},
            "yaml": {"binary": "yamllint", "probe": ["--version"], "failure_id": "TOOLCHAIN_YAML_MISSING"},
        }
        result = {}
        for name, on in enabled.items():
            if on and name in tool_map:
                result[name] = tool_map[name]
        return result if result else tool_map  # if empty, check all known
    except Exception as e:
        _fail(f"Failed to load policy: {e}", "TOOLCHAIN_POLICY_INVALID")


def check_tool(name: str, cfg: dict) -> tuple[bool, str, str]:
    """Check a single tool. Returns (ok, version_or_error, failure_id)."""
    binary = cfg.get("binary", name)
    probe = cfg.get("probe", ["--version"])
    failure_id = cfg.get("failure_id", f"TOOLCHAIN_{name.upper()}_MISSING")

    path = shutil.which(binary)
    if not path:
        return False, f"binary not on PATH: {binary}", failure_id

    cmd = [binary] + probe
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(BASE),
        )
        out = (r.stdout or "").strip()[:200]
        err = (r.stderr or "").strip()[:200]
        version = out or err or "(no output)"
        if r.returncode != 0:
            return False, version or f"exit {r.returncode}", failure_id
        return True, version, failure_id
    except subprocess.TimeoutExpired:
        return False, "probe timeout", failure_id
    except Exception as e:
        return False, str(e), failure_id


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify toolchains per policy")
    ap.add_argument("--snapshot-id", default="20260208T190113Z", help="Snapshot ID (for policy consistency)")
    ap.add_argument("--policy", default="v1", help="Policy version")
    args = ap.parse_args()

    tools = _load_toolchains_config()
    if not tools:
        _fail("No tools defined in policy", "TOOLCHAIN_POLICY_EMPTY")

    failures = []
    for name, cfg in sorted(tools.items()):
        ok, msg, fid = check_tool(name, cfg)
        if ok:
            print(f"PASS: {name} ({msg[:60]}...)")
        else:
            print(f"FAIL: {name}: {msg}", file=sys.stderr)
            failures.append((name, fid))

    if failures:
        ids = sorted(set(f[1] for f in failures))
        print("FAILURE_IDs: " + ", ".join(ids), file=sys.stderr)
        sys.exit(2)

    print("verify_toolchains_ready: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
