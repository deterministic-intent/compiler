#!/usr/bin/env python3
"""
Step 19: Scraper E2E (Deterministic + Audit-Gated).

Flow:
- Dependency check (sqlalchemy/httpx/bs4). If missing, fail with deterministic token.
- Start deterministic local fixture HTTP server (offline target).
- Run a minimal "real scraper fetch" via BaseScraper.fetch_page() once, with external snapshot capture enabled.
- Run full pipeline using that external snapshot (gate0->gate6).
- Prove index-backed planning + answer evidence lock.
- Replay proof: network forbidden + byte-identical artifacts.

On PASS prints exactly one line:
  ✓ Step 19 scrapers→snapshot→index→dist is deterministic and replay-pinned
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _die(msg: str, code: int = 1) -> None:
    sys.stderr.write(f"ERROR: {msg}\n")
    sys.stderr.flush()
    raise SystemExit(code)


def _run(cmd: list[str], env: dict | None = None, cwd: Path | None = None, allow_fail: bool = False) -> subprocess.CompletedProcess:
    p = subprocess.run(
        cmd,
        cwd=str(cwd or BASE),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    if not allow_fail and p.returncode != 0:
        _die(f"command failed (exit {p.returncode}): {' '.join(cmd)}\nSTDERR:\n{p.stderr}\nSTDOUT:\n{p.stdout}", p.returncode)
    return p


def _require_files(req_dir: Path, rels: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for r in rels:
        p = req_dir / r
        if not p.exists():
            _die(f"missing required artifact: {p}")
        out[r] = _sha256_file(p)
    return out


def _read_json_obj(p: Path) -> dict:
    obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(obj, dict):
        _die(f"{p} must be a JSON object")
    return obj


def _assert_index_usage(req_dir: Path) -> None:
    plan = _read_json_obj(req_dir / "planner" / "plan.json")
    if plan.get("index_used") is not True:
        _die("planner/plan.json must indicate index_used=true")
    evidence = plan.get("evidence", [])
    if not isinstance(evidence, list) or not evidence:
        _die("planner/plan.json evidence must be non-empty")

    dbp = req_dir / "index" / "index.db"
    conn = sqlite3.connect(str(dbp))
    try:
        for e in evidence:
            if not isinstance(e, dict):
                _die("planner evidence entry must be an object")
            doc_id = str(e.get("doc_id", "")).strip()
            source_id = str(e.get("source_id", "")).strip()
            if not doc_id or not source_id:
                _die("planner evidence must include doc_id and source_id")
            row = conn.execute("SELECT 1 FROM documents WHERE doc_id=? AND source_id=? LIMIT 1;", (doc_id, source_id)).fetchone()
            if not row:
                _die(f"planner evidence does not map to index document: doc_id={doc_id} source_id={source_id}")
    finally:
        conn.close()


def _assert_answer_evidence_lock(req_dir: Path) -> None:
    plan = _read_json_obj(req_dir / "planner" / "plan.json")
    ans = _read_json_obj(req_dir / "answer" / "answer.json")
    pe = plan.get("evidence", [])
    ae = ans.get("evidence", [])
    if not isinstance(pe, list) or not isinstance(ae, list):
        _die("planner/answer evidence must be arrays")

    def _norm(e: dict) -> dict:
        return {
            "doc_id": str(e.get("doc_id", "")).strip(),
            "source_id": str(e.get("source_id", "")).strip(),
            "excerpt": str(e.get("excerpt", "") or ""),
            "excerpt_sha256": str(e.get("excerpt_sha256", "")).strip().lower(),
        }

    pe_norm = [_norm(e) for e in pe if isinstance(e, dict)]
    ae_norm = [_norm(e) for e in ae if isinstance(e, dict)]
    pe_norm.sort(key=lambda x: (x["doc_id"], x["excerpt_sha256"]))
    ae_norm.sort(key=lambda x: (x["doc_id"], x["excerpt_sha256"]))
    if pe_norm != ae_norm:
        _die("answer evidence does not exactly match planner evidence (lock violated)")


def _orch_gate0(request_id: str, objective: str, env: dict) -> None:
    _run(
        [
            sys.executable,
            str(BASE / "orchestrator" / "orchestrator.py"),
            "gate0_init",
            request_id,
            json.dumps(objective),
            json.dumps([]),
            json.dumps([]),
            json.dumps([]),
        ],
        env=env,
    )


def _orch_gate(request_id: str, gate_cmd: str, env: dict) -> None:
    _run([sys.executable, str(BASE / "orchestrator" / "orchestrator.py"), gate_cmd, request_id], env=env)


def _patch_payload(req_dir: Path, *, policy: str, know_id: str, ext_id: str, url: str) -> None:
    payload_path = req_dir / "payload.json"
    if not payload_path.exists():
        _die("payload.json missing after gate0_init")
    payload = json.loads(payload_path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(payload, dict):
        _die("payload.json must be a JSON object")
    payload["policy_version"] = policy
    payload["knowledge_snapshot_id"] = know_id
    payload["external_snapshot_id"] = ext_id
    payload["external_sources_required"] = [url]
    payload["answer_mode"] = "index_backed"
    payload["answer_queries"] = [{"op": "search", "args": {"q": "step19_token=ALPHA", "limit": 3}}]
    payload_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_full_pipeline(req_id: str, env: dict) -> None:
    for cmd in ("gate1_planning", "gate2_delegation", "gate3_execution", "gate4_review", "gate5_finalize", "gate6_complete"):
        _orch_gate(req_id, cmd, env=env)


def _start_fixture_server(port: int) -> subprocess.Popen:
    p = subprocess.Popen(
        [sys.executable, "-u", "scripts/fixtures/http_server.py", "--port", str(port), "--max-requests", "6"],
        cwd=str(BASE),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert p.stdout is not None
    # Avoid hangs: poll /health with bounded wait.
    try:
        _ = p.stdout.readline().strip()
    except Exception:
        pass
    deadline = time.time() + 3.0
    last_err = ""
    while time.time() < deadline:
        if p.poll() is not None:
            try:
                last_err = (p.stderr.read() or "") if p.stderr else ""
            except Exception:
                last_err = ""
            break
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{int(port)}/health", timeout=0.5) as resp:
                if resp.status == 200:
                    return p
        except Exception:
            time.sleep(0.05)
            continue
    try:
        err = (p.stderr.read() or "") if p.stderr else last_err
    except Exception:
        err = last_err
    p.terminate()
    _die(f"step19:fixture_server_not_ready\nSTDERR:\n{(err or '').strip()}", 1)
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request-id", default="STEP19-E2E")
    ap.add_argument("--external-snapshot-id", default="STEP19-EXT")
    ap.add_argument("--knowledge-snapshot-id", default="")
    ap.add_argument("--policy", default="v1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    # A) Deps gate
    dep = _run([sys.executable, "scripts/check_scraper_deps.py"], allow_fail=True)
    if dep.returncode != 0:
        # Deterministic token required.
        sys.stdout.write("FAIL step19:deps_missing\n")
        sys.stdout.flush()
        return 1

    req_id = args.request_id
    ext_id = args.external_snapshot_id
    know_id = (args.knowledge_snapshot_id or os.environ.get("DCS_PROOF_SNAPSHOT_ID") or os.environ.get("AUDIT_CLOSURE_SNAPSHOT") or "").strip()
    if not know_id:
        sys.stderr.write("MISSING_SNAPSHOT_ID: set DCS_PROOF_SNAPSHOT_ID or pass --knowledge-snapshot-id\n")
        sys.exit(2)
    policy = args.policy
    req_dir = BASE / "state" / "requests" / req_id
    ext_dir = BASE / "snapshots" / "external" / ext_id

    # Clean room
    if req_dir.exists():
        shutil.rmtree(req_dir, ignore_errors=True)
    if ext_dir.exists():
        shutil.rmtree(ext_dir, ignore_errors=True)
    for p in (Path("/tmp/llmhub_step19_live.db"), Path("/tmp/llmhub_step19_replay.db")):
        if p.exists():
            p.unlink()

    # B) Offline deterministic target
    srv = _start_fixture_server(int(args.port))
    url = f"http://127.0.0.1:{int(args.port)}/page1.html"
    try:
        # Confirm reachable
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = resp.read()
        if b"step19_token=ALPHA" not in body:
            _die("fixture content missing expected token")

        # C) Minimal "real scraper fetch" that must trigger Step 9 external snapshot capture
        env_live = os.environ.copy()
        env_live.pop("DCS_REPRO", None)
        env_live.pop("NLC_REPRO", None)
        env_live.pop("NLC_NET_LOG", None)
        env_live.pop("NLC_EXTERNAL_REPLAY", None)
        env_live["NLC_POLICY_VERSION"] = policy
        env_live["NLC_DB_SNAPSHOT_ID"] = know_id
        env_live["NLC_SNAPSHOT_ID"] = know_id
        env_live["NLC_KB_SNAPSHOT_ID"] = know_id
        env_live["NLC_EXTERNAL_SNAPSHOT_ID"] = ext_id
        env_live["DEV_DB_URL"] = "sqlite:////tmp/llmhub_step19_live.db"

        scraper_tmp = Path("/tmp/llmhub_step19_scraper")
        if scraper_tmp.exists():
            shutil.rmtree(scraper_tmp, ignore_errors=True)
        scraper_tmp.mkdir(parents=True, exist_ok=True)

        snippet = (
            "import sys, asyncio; sys.path.insert(0, r'" + str(BASE) + "');\n"
            "from scraper.base_scraper import BaseScraper;\n"
            "url = r'" + url + "';\n"
            "async def _m():\n"
            "  s=BaseScraper(language='python', source_config={'id':'step19_local','name':'step19_local','url':url});\n"
            "  txt = await s.fetch_page(url);\n"
            "  await s.session.aclose();\n"
            "  delattr(s,'session');\n"
            "  assert txt and 'step19_token=ALPHA' in txt;\n"
            "asyncio.run(_m())\n"
        )
        p = _run([sys.executable, "-c", snippet], env=env_live, cwd=scraper_tmp, allow_fail=True)
        shutil.rmtree(scraper_tmp, ignore_errors=True)
        if p.returncode != 0:
            sys.stdout.write("FAIL step19:scraper_import_failed\n")
            sys.stdout.flush()
            return 1

        if not ext_dir.exists() or not (ext_dir / "snapshot.meta.json").exists() or not (ext_dir / "sources.manifest.json").exists():
            sys.stdout.write("FAIL step19:scraper_no_external_snapshot\n")
            sys.stdout.flush()
            return 1

        # D) Full pipeline off captured external snapshot
        _orch_gate0(req_id, "Make a CLI that counts from 1 to 5 by 1", env=env_live)
        _patch_payload(req_dir, policy=policy, know_id=know_id, ext_id=ext_id, url=url)
        _run_full_pipeline(req_id, env=env_live)

        required = [
            "snapshot_resolution.json",
            "index/index.db",
            "index/index.sha256",
            "planner/plan.json",
            "answer/answer.json",
            "dist/artifact.zip",
            "dist/checksums.sha256",
            "dist/manifest.json",
            "dist/ENTRYPOINT.md",
        ]
        baseline = _require_files(req_dir, required)

        _run([sys.executable, "-m", "zipfile", "-t", str(req_dir / "dist" / "artifact.zip")])
        _run(["sha256sum", "-c", "checksums.sha256"], cwd=req_dir / "dist")
        _assert_index_usage(req_dir)
        _assert_answer_evidence_lock(req_dir)

        # E) Replay determinism proof (network forbidden)
        net_log = Path("/tmp/llmhub_step19_net.log")
        if net_log.exists():
            net_log.unlink()
        env_replay = env_live.copy()
        env_replay["DCS_REPRO"] = "1"
        env_replay["NLC_NET_LOG"] = str(net_log)
        env_replay["DEV_DB_URL"] = "sqlite:////tmp/llmhub_step19_replay.db"

        _run([sys.executable, str(BASE / "scripts" / "run_replay.py"), req_id, "gate3_execution"], env=env_replay)
        if net_log.exists() and net_log.read_text(encoding="utf-8", errors="replace").strip():
            _die("network access detected in replay (NLC_NET_LOG non-empty)")

        replay = _require_files(req_dir, required)
        for k in sorted(required):
            if baseline[k] != replay[k]:
                _die(f"replay artifact not byte-identical: {k} baseline={baseline[k]} replay={replay[k]}")

        sys.stdout.write("✓ Step 19 scrapers→snapshot→index→dist is deterministic and replay-pinned\n")
        sys.stdout.flush()
        return 0
    finally:
        try:
            if srv.poll() is None:
                srv.terminate()
            srv.wait(timeout=3)
        except Exception:
            try:
                srv.kill()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())


