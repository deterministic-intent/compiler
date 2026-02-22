#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("$REPO_ROOT")
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Strict allowlist for optional command execution (off by default)
DEFAULT_ALLOWED = {
    "lscpu": ["lscpu"],
    "lsb_release": ["lsb_release", "-a"],
    "uname": ["uname", "-a"],
    "ip_br": ["ip", "-br", "a"],
}

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")

def safe_run(argv, timeout=5):
    exe = shutil.which(argv[0])
    if not exe:
        return {"ok": False, "error": f"missing_binary:{argv[0]}", "rc": None, "stdout": "", "stderr": ""}
    try:
        p = subprocess.run([exe, *argv[1:]], capture_output=True, text=True, timeout=timeout)
        return {"ok": p.returncode == 0, "rc": p.returncode, "stdout": p.stdout, "stderr": p.stderr}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "rc": None, "stdout": "", "stderr": ""}

def cpu_usage_percent(sample_ms=250):
    # /proc/stat deltas
    def read_stat():
        line = read_text(Path("/proc/stat")).splitlines()[0]
        parts = line.split()
        vals = list(map(int, parts[1:]))  # user nice system idle iowait irq softirq steal guest guest_nice
        # total = sum all, idle = idle + iowait
        total = sum(vals)
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        return total, idle

    t1, i1 = read_stat()
    time.sleep(max(0.05, sample_ms / 1000.0))
    t2, i2 = read_stat()
    dt = t2 - t1
    di = i2 - i1
    if dt <= 0:
        return None
    usage = (dt - di) / dt * 100.0
    return round(usage, 2)

def mem_info():
    # /proc/meminfo kB
    out = {}
    for line in read_text(Path("/proc/meminfo")).splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k.strip()] = v.strip()
    return out

def disk_root_usage():
    try:
        du = shutil.disk_usage("/")
        return {
            "total_bytes": du.total,
            "used_bytes": du.used,
            "free_bytes": du.free,
        }
    except Exception as e:
        return {"error": str(e)}

def temps_c():
    # Best-effort: read /sys thermal zones
    base = Path("/sys/class/thermal")
    zones = []
    if base.exists():
        for z in sorted(base.glob("thermal_zone*")):
            tfile = z / "temp"
            ttype = z / "type"
            if not tfile.exists():
                continue
            try:
                raw = int(read_text(tfile).strip())
                # common is millidegrees C
                c = raw / 1000.0 if raw > 1000 else float(raw)
                zones.append({
                    "zone": z.name,
                    "type": read_text(ttype).strip() if ttype.exists() else None,
                    "c": round(c, 2),
                })
            except Exception:
                continue

    # Optional: lm-sensors if installed
    sensors = safe_run(["sensors"], timeout=5)
    return {"thermal_zones": zones, "sensors_cmd": sensors}

def loadavg_uptime():
    # /proc/loadavg + /proc/uptime
    la = read_text(Path("/proc/loadavg")).strip()
    up = read_text(Path("/proc/uptime")).strip()
    return {"loadavg_raw": la, "uptime_raw": up}

def os_release():
    p = Path("/etc/os-release")
    if not p.exists():
        return {}
    data = {}
    for line in read_text(p).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k] = v.strip()
    return data

def lscpu_model():
    # Parse /proc/cpuinfo for model name
    p = Path("/proc/cpuinfo")
    if not p.exists():
        return None
    for line in read_text(p).splitlines():
        if line.lower().startswith("model name"):
            _, val = line.split(":", 1)
            return val.strip()
    return None

def snapshot():
    return {
        "ts_utc": utc_now(),
        "cpu": {
            "model_name": lscpu_model(),
            "usage_percent": cpu_usage_percent(),
            "cores_logical": os.cpu_count(),
        },
        "os": {
            "os_release": os_release(),
            "uname": safe_run(["uname", "-a"], timeout=3),
        },
        "mem": mem_info(),
        "disk_root": disk_root_usage(),
        "load": loadavg_uptime(),
        "temps": temps_c(),
        "net": {
            "ip_brief": safe_run(["ip", "-br", "a"], timeout=3),
        },
    }

def log_event(event):
    # Append JSONL
    path = LOG_DIR / "executor.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["snapshot", "run"], default="snapshot")
    ap.add_argument("--cmd", help="Allowed command key (only for --mode run)")
    args = ap.parse_args()

    event = {"ts_utc": utc_now(), "mode": args.mode}

    if args.mode == "snapshot":
        payload = snapshot()
        event["ok"] = True
        event["payload"] = payload
        log_event(event)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    # run mode: disabled unless explicitly enabled
    if os.environ.get("EXECUTOR_ALLOW_RUN", "0") != "1":
        event["ok"] = False
        event["error"] = "run_mode_disabled_set_EXECUTOR_ALLOW_RUN=1"
        log_event(event)
        print(json.dumps(event, indent=2, ensure_ascii=False))
        return 2

    key = args.cmd or ""
    allowed = DEFAULT_ALLOWED
    if key not in allowed:
        event["ok"] = False
        event["error"] = f"cmd_not_allowed:{key}"
        event["allowed_keys"] = sorted(allowed.keys())
        log_event(event)
        print(json.dumps(event, indent=2, ensure_ascii=False))
        return 2

    res = safe_run(allowed[key], timeout=5)
    event["ok"] = res.get("ok", False)
    event["cmd_key"] = key
    event["argv"] = allowed[key]
    event["result"] = res
    log_event(event)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res.get("ok") else 2

if __name__ == "__main__":
    raise SystemExit(main())
