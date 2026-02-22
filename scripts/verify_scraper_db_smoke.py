#!/usr/bin/env python3
"""
Scraper + DB smoke test (no full pipeline).

Goal: prove scrapers still work against a fresh sqlite DB without relying on repo-root dev.db.

What it does:
- Ensures scraper deps are installed (uses scripts/check_scraper_deps.py)
- Creates a fresh sqlite DB via DEV_DB_URL pointing to /tmp (isolated)
- Creates DB tables (no seed) to avoid legacy seed drift
- Starts the deterministic fixture HTTP server
- Runs a real scraper fetch+insert via RegistryScraper against a local fixture URL
- Asserts DB now contains at least one Node (via db.api.list_nodes)

Locked failure tokens (exact):
  FAIL scraper_smoke:deps_missing
  FAIL scraper_smoke:init_db_failed
  FAIL scraper_smoke:fixture_server_failed
  FAIL scraper_smoke:scrape_failed
  FAIL scraper_smoke:no_nodes_inserted
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


def _fail(tok: str) -> None:
    sys.stdout.write(tok.strip() + "\n")
    sys.stdout.flush()
    raise SystemExit(1)


def _run(cmd: list[str], *, env: dict[str, str], timeout_s: int = 120, allow_fail: bool = False) -> subprocess.CompletedProcess:
    p = subprocess.run(
        cmd,
        cwd=str(BASE),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    if p.returncode != 0 and not allow_fail:
        sys.stdout.write((p.stdout or "") + (p.stderr or ""))
        sys.stdout.flush()
        raise SystemExit(p.returncode or 2)
    return p


def _start_fixture_server(*, env: dict[str, str], port: int = 8765) -> subprocess.Popen:
    cmd = [
        sys.executable,
        str(BASE / "scripts" / "fixtures" / "http_server.py"),
        "--port",
        str(int(port)),
        "--max-requests",
        "50",
    ]
    p = subprocess.Popen(
        cmd,
        cwd=str(BASE),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.time() + 10.0
    buf = ""
    while time.time() < deadline:
        if p.poll() is not None:
            break
        if p.stdout is not None:
            ln = p.stdout.readline()
            if ln:
                buf += ln
                if "FIXTURE_HTTP_READY:" in ln:
                    return p
        time.sleep(0.05)
    try:
        p.terminate()
    except Exception:
        pass
    _fail("FAIL scraper_smoke:fixture_server_failed")


def main() -> int:
    env = os.environ.copy()
    env.setdefault("NLC_POLICY_VERSION", "v1")

    # 1) deps check
    p = _run([sys.executable, str(BASE / "scripts" / "check_scraper_deps.py")], env=env, allow_fail=True)
    if p.returncode != 0:
        _fail("FAIL scraper_smoke:deps_missing")

    # 2) fresh DB path (isolated)
    db_path = Path(f"/tmp/llmhub_scraper_smoke_{os.getpid()}.db")
    if db_path.exists():
        db_path.unlink()
    env["DEV_DB_URL"] = f"sqlite:////{db_path}"

    # 3) init DB tables (no seed)
    code_init = (
        "from db.engine import get_engine\n"
        "from db.models import Base\n"
        "e = get_engine()\n"
        "Base.metadata.create_all(e)\n"
        "print('OK_CREATE_ALL')\n"
    )
    p = _run([sys.executable, "-c", code_init], env=env, allow_fail=True, timeout_s=120)
    if p.returncode != 0:
        _fail("FAIL scraper_smoke:init_db_failed")

    # 4) Start fixture server and run a real scraper fetch+insert.
    srv = _start_fixture_server(env=env, port=8765)
    try:
        url = "http://127.0.0.1:8765/sample_python_page.html"
        code_scrape = (
            "import asyncio, os\n"
            "from scraper.run_scrapers import RegistryScraper\n"
            "cfg = {'id':'smoke','name':'smoke','language':'python','url': os.environ.get('SMOKE_URL')}\n"
            "scr = RegistryScraper('python', cfg)\n"
            "async def run():\n"
            "    await scr.scrape_url(os.environ.get('SMOKE_URL'))\n"
            "    await scr.session.aclose()\n"
            "asyncio.run(run())\n"
            "print('OK_SCRAPE_INSERT')\n"
        )
        env2 = env.copy()
        env2["SMOKE_URL"] = url
        p = _run([sys.executable, "-c", code_scrape], env=env2, allow_fail=True, timeout_s=120)
        if p.returncode != 0:
            _fail("FAIL scraper_smoke:scrape_failed")
    finally:
        try:
            srv.terminate()
            srv.wait(timeout=3)
        except Exception:
            try:
                srv.kill()
            except Exception:
                pass

    # 5) assert nodes exist
    code2 = (
        "from db.api import list_nodes\n"
        "nodes = list_nodes(limit=5)\n"
        "print(len(nodes))\n"
    )
    p = _run([sys.executable, "-c", code2], env=env, allow_fail=True, timeout_s=60)
    if p.returncode != 0:
        _fail("FAIL scraper_smoke:no_nodes_inserted")
    try:
        n = int((p.stdout or '').strip() or '0')
    except Exception:
        n = 0
    if n <= 0:
        _fail("FAIL scraper_smoke:no_nodes_inserted")

    sys.stdout.write("✓ Scraper DB smoke: PASS\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


