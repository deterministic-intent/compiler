# NLC Orchestrator Contract (Option A, Locked)

> “The orchestrator is a deterministic state machine and gate enforcer. It never creates content, never fixes output, and never advances without verifier PASS.”

## Authoritative End-to-End Flow (Gates 0–6)

### Gate 0 — Intake
- ORCHESTRATOR writes: REQUEST.md
- VERIFIER validates request is bounded and testable
- PASS -> Gate 1, else stop

### Gate 1 — Planning
- PLANNER (deterministic) writes: SPEC.md, TASKS.yaml, PLAN.md
- VERIFIER checks scope + acceptance criteria completeness
- PASS -> Gate 2, else stop

### Gate 2 — Delegation
- ORCHESTRATOR writes: TASKS.json
- VERIFIER checks role assignment + conflicts + offline compliance
- PASS -> execution gates, else stop

### Gate 3 — Backend Implementation (conditional)
- GENERATOR implements backend + tests
- VERIFIER validates SPEC + tests
- PASS -> Gate 4 if needed, else proceed

### Gate 4 — Frontend Implementation (conditional)
- GENERATOR implements frontend against verified backend
- VERIFIER validates SPEC + contract alignment
- PASS -> Gate 5 if infra touched, else proceed

### Gate 5 — Infra / Deploy Readiness (conditional)
- SYSTEMS writes RUNBOOK.md (deploy, rollback, health checks, expected logs/config diffs)
- VERIFIER validates safety/reversibility/observability
- PASS -> Gate 6, else stop

### Gate 6 — Merge / Release
- ORCHESTRATOR merges/releases only if all required gates are PASS

---

## Filesystem Contract (Canonical)

Base per request:
  $REPO_ROOT/state/requests/<REQUEST_ID>/

ORCHESTRATOR creates the request dir and writes ONLY:
- REQUEST.md
- TASKS.json
- state.json (gate + timestamps + task ids + hashes/pointers)
- gate0.status … gate6.status
- WEB_EVIDENCE/ (only when internet research is used)
  - raw snapshots
  - sources.json (url, retrieved_at, sha256, allowlist match)

ORCHESTRATOR must NOT write:
- SPEC.md
- TASKS.yaml
- PLAN.md
- RUNBOOK.md
- any code/tests
- any “fixed” version of agent outputs

PLANNER (deterministic) MUST write:
- SPEC.md
- TASKS.yaml
- PLAN.md

VERIFIER MUST write:
- VERIFY.md (first non-empty line is PASS or FAIL/BLOCKED)

SYSTEMS MUST write when applicable:
- RUNBOOK.md

GENERATOR writes code/tests only in repo paths allowed by TASKS.json (and any future output contracts).

---

## Deterministic Gate Rule (Non-negotiable)
A gate advances only if verifier output’s first non-empty line is exactly:
PASS

Anything else (FAIL, BLOCKED, garbage, missing file) -> gate FAIL and stop.

---

## TASKS.yaml Format (Locked for determinism)
Despite the filename, TASKS.yaml MUST be valid JSON and follow:

{
  "tasks": [
    {
      "id": "T1",
      "type": "backend|frontend|infra|doc|test|other",
      "owner": "GENERATOR|SYSTEMS|PLANNER (deterministic)|ORCHESTRATOR",
      "acceptance": ["..."],
      "touches": ["path/or/area", "..."],
      "blocking": false
    }
  ]
}

---

## Official-only Web Policy (Orchestrator only)
- Allowlist: official docs + upstream repos only (contracts/web_allowlist.txt)
- No blogs, no random scrapes
- All retrieved content must be snapshotted into WEB_EVIDENCE/ with sources.json
- Offline agents may reference WEB_EVIDENCE files only and must label it as WEB_EVIDENCE in their outputs.
