#!/usr/bin/env python3
import sys
import re

EXPECTED_CPU = "12th Gen Intel(R) Core(TM) i9-12900H"
EXPECTED_OS  = 'PRETTY_NAME="Ubuntu 24.04.3 LTS"'
EXPECTED_READY = "READY"

FORBIDDEN_WORDS = [
    r"\bprobably\b",
    r"\bmaybe\b",
    r"\bshould\b",
    r"\btry\b",
]

def block(reason: str) -> int:
    print("STATUS: BLOCKED")
    print(f"REASON: {reason}")
    return 2

def main():
    text = sys.stdin.read().strip()

    for pat in FORBIDDEN_WORDS:
        if re.search(pat, text, flags=re.IGNORECASE):
            return block(f"Forbidden hedge word matched: {pat}")

    # If the model explicitly says UNKNOWN, that is allowed and correct
    if text.startswith("UNKNOWN"):
        print("STATUS: PASS")
        return 0

    # Otherwise, it is making claims — enforce exact matches
    if EXPECTED_CPU not in text:
        return block(f"CPU claim missing or incorrect. Expected to include: {EXPECTED_CPU}")

    if EXPECTED_OS not in text:
        return block(f"OS claim missing or incorrect. Expected to include: {EXPECTED_OS}")

    if re.search(r"\bready\b", text) and EXPECTED_READY not in text:
        return block("READY casing is wrong. Must be exactly: READY")

    print("STATUS: PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
