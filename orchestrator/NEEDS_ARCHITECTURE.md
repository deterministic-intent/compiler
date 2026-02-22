# NEEDS.json Architecture

## Two Use Cases

### 1. Gate 1 (Planning) - Research Needs (Auto-satisfiable)

**Who writes**: deterministic compiler/planner  
**Types**: `web_fetch`, `package`, `tool`, `doc`  
**Purpose**: Request external information for planning/research  
**Satisfaction**: Automatically fetched by `satisfy_needs()` into `WEB_EVIDENCE/`  
**Flow**:
1. Planner writes NEEDS.json with research needs
2. Orchestrator calls `satisfy_needs()` (up to 3 rounds)
3. Web content fetched into WEB_EVIDENCE/
4. Planner re-runs with new evidence
5. Continues until no more needs or max rounds

**Example**:
```json
{
  "needs": [
    {
      "type": "web_fetch",
      "url": "https://example.com/api-docs",
      "detail": "Need API documentation for planning"
    }
  ]
}
```

### 2. Gate 3 (Execution) - Missing Module Needs (Human-actionable)

**Who writes**: Orchestrator (when Generator fails, no fixer available)  
**Types**: `module`  
**Purpose**: Signal missing deterministic module/fixer capability  
**Satisfaction**: NOT auto-satisfiable - requires human to add module  
**Flow**:
1. Generator runs (deterministic, uses modules)
2. Verifier FAILs
3. Try deterministic fixer - if available, apply and re-verify
4. If no fixer available: write NEEDS.json with type "module" and STOP
5. Human reads NEEDS.json, adds module to `orchestrator/modules/`
6. Human re-runs request (or system auto-retries if module added)

**Example**:
```json
{
  "needs": [
    {
      "type": "module",
      "name": "missing_module_missing_dom_manipulation",
      "detail": "Generator failed with signature: MISSING_DOM_MANIPULATION. Missing deterministic module/fixer to address this failure pattern."
    }
  ]
}
```

## Key Differences

| Aspect | Planning Needs | Module Needs |
|--------|---------------|--------------|
| **Source** | deterministic compiler/planner | Orchestrator (Generator failure) |
| **Auto-satisfiable** | ✅ Yes (web fetch) | ❌ No (human action) |
| **Purpose** | Research/planning | Signal missing capability |
| **Resolution** | Fetched to WEB_EVIDENCE/ | Add module to orchestrator/modules/ |
| **Retries** | Up to 3 rounds | Manual (after module added) |

## Implementation

- `satisfy_needs()` handles `web_fetch`, `package`, `tool`, `doc` (auto-satisfiable)
- `satisfy_needs()` recognizes `module` type but does NOT satisfy it (returns ok: False with explanation)
- Gate 3 writes `module` type needs and STOPS (no retries)
- Gate 1 satisfies research needs and re-runs Planner (bounded retries)

## Adding New Modules

When NEEDS.json contains `"type": "module"`:
1. Read the `name` and `detail` fields
2. Identify the failure signature (e.g., `MISSING_DOM_MANIPULATION`)
3. Create appropriate module in `orchestrator/modules/<artifact_class>/<module_name>.json`
4. Optionally add fixer logic to `inject_deterministic_patch()` in orchestrator.py
5. Re-run the request

This makes failures actionable: "missing module X" is clear and fixable.
