# Audit Battery

Run all required audit checks (static compile, import smoke, help smoke, E2E0 smoke):

```bash
cd /opt/llm-hub
python3 scripts/audit/run_audit.py
```

Checks (in order):
1) compileall (scripts, workers, orchestrator, nlc, policy)
2) Import smoke for entry modules
3) Help/usage smoke for key scripts
4) E2E0 smoke (runs E2E0 harness; logical FAIL allowed, must not crash)

Exit is non-zero on first failing required check (E2E0 is informational).

