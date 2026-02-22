#!/usr/bin/env python3
import subprocess
import sys
import re

FACTS_CMD = ["$REPO_ROOT/facts.sh"]

def get_truth():
    p = subprocess.run(FACTS_CMD, capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"ERROR: facts.sh failed rc={p.returncode}\n{p.stderr}")
    truth = {}
    for line in p.stdout.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        truth[k.strip()] = v.strip()
    return truth

def block(reason: str) -> int:
    print("STATUS: BLOCKED")
    print(f"REASON: {reason}")
    return 2

def main():
    out = sys.stdin.read()

    # Extract FACTS lines
    facts = {}
    for line in out.splitlines():
        m = re.match(r'^\s*([a-zA-Z0-9_.]+)\s*:\s*(.+?)\s*$', line)
        if not m:
            continue
        k, v = m.group(1), m.group(2)
        if k in ("cpu.model_name","os.PRETTY_NAME","cpu.usage_percent","temps.primary_c"):
            facts[k] = v

    # Allow UNKNOWN-only outputs
    if out.strip().startswith("UNKNOWN"):
        print("STATUS: PASS")
        return 0

    required = ["cpu.model_name","os.PRETTY_NAME","cpu.usage_percent","temps.primary_c"]
    for k in required:
        if k not in facts:
            return block(f"Missing required FACTS line: {k}")

    truth = get_truth()
    for k in required:
        tv = truth.get(k)
        if tv is None:
            return block(f"Truth missing key from facts.sh: {k}")
        if facts[k] != tv:
            return block(f"FACT mismatch for {k}. expected='{tv}' got='{facts[k]}'")

    print("STATUS: PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
