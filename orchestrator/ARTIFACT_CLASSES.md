# Artifact Classes: Deterministic Intent Grounding

## Core Principle

**Make "what is being built" a deterministic system decision, and let the deterministic decide only "how it's built."**

## Implementation

### 1. Artifact Class Definition (`artifact_classes.json`)

Each artifact class defines:
- **Required observable behaviors**: What the artifact must do
- **Required interaction modes**: How users interact with it
- **Required execution model**: How it runs
- **Disallowed behaviors**: What would make it the wrong class
- **Signals**: Keywords that indicate this class
- **Validation checks**: Specific code patterns to verify

### 2. Deterministic Detection (Orchestrator)

`detect_artifact_class()` in `orchestrator.py`:
- Runs **before any deterministic writes code**
- Scores request objective + constraints against artifact class signals
- Returns highest-scoring class (or default)
- **This is a system decision, not an deterministic decision**

### 3. Locked in Payload (`payload.json`)

The orchestrator includes in `payload.json`:
- `artifact_class`: The locked class name (e.g., "webview", "python_cli")
- `artifact_class_definition`: Full class definition for reference

This ensures the artifact class is **locked for the run** - no drifting.

### 4. Class-Aware Verification (Verifier)

The verifier now answers two questions **in order**:

1. **Is this the correct artifact class?**
   - Checks required file patterns (HTML/JS for webview, Python for CLI/API/GUI)
   - Checks required code patterns (argparse for CLI, Flask for API, tkinter for GUI)
   - Checks disallowed behaviors (no Flask in CLI, no argparse in API)
   - **If artifact class fails → immediate FAIL with class mismatch explanation**

2. **Does it function correctly?**
   - Only checked if artifact class passes
   - Validates acceptance criteria from TASKS.json
   - Checks for placeholders, incomplete implementations

### 5. Self-Healing Convergence

With artifact class locked:
- `NEEDS.json` repairs missing behaviors **within the class**
- `WEB_EVIDENCE` is scoped to the class
- deterministic retries don't "escape" into other implementations
- Small models stop improvising

## Why This Scales

You are **not constraining implementations**. You are only constraining:
- The kind of thing being built (artifact class)
- The observable contract it must satisfy

You can:
- Swap languages
- Swap libraries
- Swap frameworks
- Combine components
- Change architectures

**As long as the artifact class contract is satisfied, the system passes.**

## Current Artifact Classes

1. **python_cli**: Command-line applications (argparse/click)
2. **python_api**: REST APIs (Flask/FastAPI)
3. **python_gui**: Desktop GUIs (tkinter)
4. **webview**: Web interfaces (HTML/JS/CSS)

## Example Flow

1. Request: "Create a webview interface"
2. Orchestrator detects: `artifact_class = "webview"`
3. Payload includes: `artifact_class: "webview"` + full definition
4. Planner/Developer see artifact class in context
5. Verifier checks:
   - ✅ Has HTML file? ✅ Has JS file? → Artifact class PASS
   - ✅ Has fetch()? ✅ Has DOM manipulation? → Functionality PASS
6. If artifact class fails, NEEDS.json requests webview-specific help
7. Self-healing loop stays within webview class

## Files Modified

- `orchestrator/artifact_classes.json`: Class definitions (data, not prompts)
- `orchestrator/orchestrator.py`: `detect_artifact_class()` + payload inclusion
- `workers/run_verifier.py`: Artifact class validation (checks class FIRST, then functionality)
