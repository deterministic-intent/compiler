#!/usr/bin/env python3
import sys
import json
import hashlib
import os
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.request import Request, urlopen

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
ALLOWLIST_JSON = BASE / "orchestrator" / "allowlist.json"
ALLOWLIST_TXT = BASE / "contracts" / "web_allowlist.txt"  # fallback

def die(msg: str, code: int = 2):
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)

def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"

def sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()

def load_allowlist() -> list[str]:
    """Load allowlist from JSON (preferred) or fallback to text file."""
    if ALLOWLIST_JSON.exists():
        try:
            obj = json.loads(ALLOWLIST_JSON.read_text(encoding="utf-8", errors="replace"))
            domains = obj.get("domains", [])
            if isinstance(domains, list):
                return [str(d).strip().lower() for d in domains if d]
        except Exception:
            pass
    
    # Fallback to text file
    if ALLOWLIST_TXT.exists():
        out = []
        for line in ALLOWLIST_TXT.read_text(encoding="utf-8", errors="replace").splitlines():
            t = line.strip().lower()
            if not t or t.startswith("#"):
                continue
            out.append(t)
        return out
    
    die(f"missing allowlist: {ALLOWLIST_JSON} or {ALLOWLIST_TXT}")

def host_allowed(host: str, allow: list[str]) -> bool:
    h = host.lower()
    for a in allow:
        if h == a or h.endswith("." + a):
            return True
    return False

def main():
    if len(sys.argv) != 4:
        die("Usage: web_fetch.py <REQUEST_ID> <REQUEST_DIR> <URL>")

    request_id = sys.argv[1].strip()
    request_dir = Path(sys.argv[2]).resolve()
    url = sys.argv[3].strip()

    # Hard ban: no network in repro mode (deterministic failure).
    from dcs_core.repro_env import is_repro_mode
    if is_repro_mode():
        log = os.environ.get("NLC_NET_LOG")
        if log:
            try:
                lp = Path(log)
                lp.parent.mkdir(parents=True, exist_ok=True)
                prev = lp.read_text(encoding="utf-8", errors="replace") if lp.exists() else ""
                lp.write_text(prev + f"web_fetch:{url}\\n", encoding="utf-8")
            except Exception:
                pass
        die("Network access forbidden in repro mode")

    if not request_id:
        die("REQUEST_ID empty")
    if not request_dir.exists():
        die(f"REQUEST_DIR not found: {request_dir}")

    allow = load_allowlist()
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        die("Only http/https allowed")
    if not u.hostname:
        die("URL missing hostname")
    if not host_allowed(u.hostname, allow):
        die(f"Host not allowed: {u.hostname}")

    we = request_dir / "WEB_EVIDENCE"
    we.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snap = we / f"snapshot_{ts}.bin"

    req = Request(url, headers={"User-Agent": "nlc-orchestrator/1.0"})
    with urlopen(req, timeout=30) as resp:
        body = resp.read()
        ctype = resp.headers.get("Content-Type", "")
        status = getattr(resp, "status", None)

    snap.write_bytes(body)
    digest = sha256_bytes(body)

    # Step 9: External raw snapshot capture (no behavior change unless enabled).
    ext_snap_id = str(os.environ.get("NLC_EXTERNAL_SNAPSHOT_ID", "")).strip()
    if ext_snap_id:
        try:
            from nlc.external_snapshot import write_external_source, try_load_toolchain_pins
            # Prefer explicit policy version; fallback to v1.
            policy_version = str(os.environ.get("NLC_POLICY_VERSION", "v1")).strip() or "v1"
            pins = try_load_toolchain_pins()
            write_external_source(
                snapshot_id=ext_snap_id,
                policy_version=policy_version,
                toolchain_pins=pins,
                source_id=url,
                content_type=ctype,
                fetch_timestamp=now_utc(),
                raw_bytes=body,
            )
        except Exception as e:
            # If snapshotting was explicitly enabled, failing to write it must fail deterministically.
            die(f"External snapshot write failed: {e}")

    sources = we / "sources.json"
    if sources.exists():
        obj = json.loads(sources.read_text(encoding="utf-8"))
    else:
        obj = {"entries": []}

    obj["entries"].append({
        "url": url,
        "host": u.hostname,
        "retrieved_at_utc": now_utc(),
        "filename": snap.name,
        "sha256": digest,
        "content_type": ctype,
        "http_status": status,
        "allowlist": str(ALLOWLIST_JSON),
    })
    sources.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")

    print("OK: WEB_EVIDENCE_SAVED")
    print(digest)

if __name__ == "__main__":
    main()
