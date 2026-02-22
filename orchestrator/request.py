#!/usr/bin/env python3
# $REPO_ROOT/orchestrator/request.py
#
# Deterministic helper to create $REPO_ROOT/state/requests/<REQUEST_ID> via:
#   $REPO_ROOT/orchestrator/orchestrator.py gate0_init ...
#
# Goal: "even cleaner" UX:
# - --from-md REQUEST.md parses Objective/Constraints/Non-goals/Definition of Done from a markdown file
# - no hand-written JSON on CLI
# - optional --auto-id
# - optional --print-request-md to generate a canonical REQUEST.md template
#
# Examples:
#   # 1) Create request directly from a markdown file you wrote
#   $REPO_ROOT/orchestrator/request.py --id TEST-001 --from-md ./REQUEST.md
#
#   # 2) Auto-id + from-md
#   $REPO_ROOT/orchestrator/request.py --auto-id --from-md ./REQUEST.md
#
#   # 3) Generate a REQUEST.md template to stdout
#   $REPO_ROOT/orchestrator/request.py --print-request-md \
#     --objective "Build a minimal backend API" \
#     -c "Deterministic outputs" -n "No extra roles" -d "Planner artifacts exist"
#
#   # 4) Or create from flags (still supported)
#   $REPO_ROOT/orchestrator/request.py --id TEST-002 \
#     --objective "Build X" -c "Deterministic" -d "DoD line 1"
#
# Contract:
# - This helper never guesses. If required sections are missing/empty -> hard error.
# - Lists are only read from "- " bullet lines under the matching section heading.
# - Objective is first non-empty line after "## Objective" up to next heading.

import argparse
import json
import re
import sys
from pathlib import Path
import subprocess
from datetime import datetime, timezone


BASE = Path(__file__).resolve().parents[1]
ORCH = BASE / "orchestrator" / "orchestrator.py"


def die(msg: str, code: int = 2):
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def now_utc_compact() -> str:
    # e.g. 20260102T103045Z
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def validate_request_id(s: str) -> str:
    s = (s or "").strip()
    if not s:
        die("REQUEST_ID is empty")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", s):
        die("REQUEST_ID must match: [A-Za-z0-9][A-Za-z0-9_-]{0,63}")
    return s


def normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def md_extract_list_under_heading(md: str, heading: str) -> list[str]:
    """
    Extract list items under a '## <heading>' section: lines starting with '- '.
    Deterministic: ignores other list markers.
    """
    s = normalize_newlines(md)
    pat = re.compile(rf"(?m)^##\s+{re.escape(heading)}\s*$")
    m = pat.search(s)
    if not m:
        return []
    start = m.end()
    m2 = re.compile(r"(?m)^##\s+").search(s, start)
    end = m2.start() if m2 else len(s)
    block = s[start:end]

    items: list[str] = []
    for line in block.splitlines():
        t = line.strip()
        if t.startswith("- "):
            v = t[2:].strip()
            if v:
                items.append(v)
    return items


def md_extract_objective(md: str) -> str:
    """
    Objective is first non-empty line after '## Objective' until blank line or next heading.
    If written as '- foo', returns 'foo'.
    """
    s = normalize_newlines(md)
    m = re.search(r"(?m)^##\s+Objective\s*$", s)
    if not m:
        return ""
    rest = s[m.end():]
    m2 = re.search(r"(?m)^##\s+", rest)
    block = rest[:m2.start()] if m2 else rest

    for line in block.splitlines():
        t = line.strip()
        if not t:
            continue
        if t.startswith("- "):
            return t[2:].strip()
        return t
    return ""


def parse_request_md(path: Path) -> tuple[str, list[str], list[str], list[str]]:
    if not path.exists():
        die(f"--from-md not found: {path}")
    md = path.read_text(encoding="utf-8", errors="replace")
    md = normalize_newlines(md)

    objective = md_extract_objective(md).strip()
    constraints = md_extract_list_under_heading(md, "Constraints")
    non_goals = md_extract_list_under_heading(md, "Non-goals")
    dod = md_extract_list_under_heading(md, "Definition of Done")

    # Enforce determinism: missing/empty objective is an error.
    if not objective:
        die("REQUEST.md parse error: missing or empty '## Objective' section")
    # Constraints/non-goals/DoD can be empty lists if the section exists but has no '- ' items.
    # BUT if the heading itself is missing, that is almost always accidental, so enforce presence.
    # Presence check: heading must exist even if empty.
    for h in ["Constraints", "Non-goals", "Definition of Done"]:
        if not re.search(rf"(?m)^##\s+{re.escape(h)}\s*$", md):
            die(f"REQUEST.md parse error: missing required heading '## {h}'")

    return objective, constraints, non_goals, dod


def build_request_md(objective: str, constraints: list[str], non_goals: list[str], dod: list[str]) -> str:
    lines = []
    lines.append("# REQUEST\n\n")
    lines.append("## Objective\n")
    lines.append(objective.strip() + "\n\n")

    lines.append("## Constraints\n")
    if constraints:
        for c in constraints:
            lines.append(f"- {c}\n")
    else:
        lines.append("- (none)\n")
    lines.append("\n")

    lines.append("## Non-goals\n")
    if non_goals:
        for ng in non_goals:
            lines.append(f"- {ng}\n")
    else:
        lines.append("- (none)\n")
    lines.append("\n")

    lines.append("## Definition of Done\n")
    if dod:
        for d in dod:
            lines.append(f"- {d}\n")
    else:
        lines.append("- (none)\n")
    lines.append("")
    return "".join(lines)


def read_objective_from_flags(args) -> str:
    modes = sum(
        1 for x in [args.objective is not None, args.objective_file is not None, args.objective_stdin]
        if x
    )
    if modes == 0:
        die("Provide objective via --objective, --objective-file, or --objective-stdin (or use --from-md).")
    if modes > 1:
        die("Provide only one objective source: --objective OR --objective-file OR --objective-stdin.")

    if args.objective is not None:
        obj = args.objective
    elif args.objective_file is not None:
        p = Path(args.objective_file)
        if not p.exists():
            die(f"--objective-file not found: {p}")
        obj = p.read_text(encoding="utf-8", errors="replace")
    else:
        obj = sys.stdin.read()

    obj = (obj or "").strip()
    if not obj:
        die("Objective is empty")
    return obj


def main():
    ap = argparse.ArgumentParser(
        prog="request.py",
        description="Deterministic helper to create a request via orchestrator gate0_init without hand-written JSON.",
    )

    rid = ap.add_mutually_exclusive_group(required=True)
    rid.add_argument("--id", help="Request ID (e.g. TEST-001).")
    rid.add_argument("--auto-id", action="store_true", help="Auto-generate a request ID like REQ-<UTC>.")

    ap.add_argument("--from-md", help="Parse Objective/Constraints/Non-goals/DoD from a REQUEST.md file.")
    ap.add_argument("--print-request-md", action="store_true", help="Print a canonical REQUEST.md and exit (no execution).")

    ap.add_argument("--objective", help="Objective text (quoted).")
    ap.add_argument("--objective-file", help="Path to file containing objective text.")
    ap.add_argument("--objective-stdin", action="store_true", help="Read objective text from stdin.")

    ap.add_argument("-c", "--constraint", action="append", default=[], help="Constraint (repeatable).")
    ap.add_argument("-n", "--non-goal", action="append", default=[], help="Non-goal (repeatable).")
    ap.add_argument("-d", "--dod", action="append", default=[], help="Definition of Done line (repeatable).")

    ap.add_argument("--dry-run", action="store_true", help="Print the orchestrator command; do not execute.")
    ap.add_argument("--python", default=sys.executable, help="Python interpreter to use (default: current).")

    args = ap.parse_args()

    if not ORCH.exists():
        die(f"orchestrator.py not found at: {ORCH}")

    request_id = args.id
    if args.auto_id:
        request_id = f"REQ-{now_utc_compact()}"
    request_id = validate_request_id(request_id)

    if args.from_md:
        if args.objective or args.objective_file or args.objective_stdin:
            die("Do not mix --from-md with --objective/--objective-file/--objective-stdin.")
        if args.constraint or args.non_goal or args.dod:
            die("Do not mix --from-md with -c/-n/-d flags (REQUEST.md is the source of truth).")
        objective, constraints, non_goals, dod = parse_request_md(Path(args.from_md))
    else:
        objective = read_objective_from_flags(args)
        constraints = [str(x).strip() for x in (args.constraint or []) if str(x).strip()]
        non_goals = [str(x).strip() for x in (args.non_goal or []) if str(x).strip()]
        dod = [str(x).strip() for x in (args.dod or []) if str(x).strip()]

    if args.print_request_md:
        print(build_request_md(objective, constraints, non_goals, dod))
        return

    cmd = [
        args.python,
        str(ORCH),
        "gate0_init",
        request_id,
        json.dumps(objective),
        json.dumps(constraints),
        json.dumps(non_goals),
        json.dumps(dod),
    ]

    if args.dry_run:
        # Print a deterministic, shell-safe-ish form
        print(" ".join([json.dumps(x) for x in cmd]))
        return

    p = subprocess.run(cmd, text=True)
    raise SystemExit(p.returncode)


if __name__ == "__main__":
    main()
