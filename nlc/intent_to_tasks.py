#!/usr/bin/env python3
"""
Deterministic converter: REQ.json (intents) → TASKS.json (generator input).
Pure deterministic conversion.
"""
import json
from typing import Dict, Any


def generate_tasks_from_req(req_json: Dict[str, Any]) -> Dict[str, Any]:
    """Generate TASKS.json from REQ.json deterministically."""
    intents = req_json.get("intents", [])
    if not intents:
        return {"tasks": []}
    
    tasks = []
    for i, intent in enumerate(intents, 1):
        intent_type = intent.get("intent_type", "")
        params = intent.get("params", {})
        description = intent.get("description", f"Execute {intent_type}")
        
        task = {
            "id": f"TASK-{i:03d}",
            "type": "implementation",
            "scope": "backend",
            "description": description,
            "intent_type": intent_type,
            "touches": ["main.py", "cli.py"],
            "acceptance_criteria": [
                f"CLI implements {intent_type} intent",
                "Code executes without errors"
            ]
        }
        tasks.append(task)
    
    return {"tasks": tasks}


def generate_spec_from_req(req_json: Dict[str, Any], prompt: str) -> str:
    """Generate SPEC.md from REQ.json deterministically."""
    intents = req_json.get("intents", [])
    intent_descriptions = [intent.get("description", intent.get("intent_type", "")) for intent in intents]
    
    spec = f"""# Specification

## Objective
{prompt}

## Implementation
This CLI implements the following intents:
"""
    for i, desc in enumerate(intent_descriptions, 1):
        spec += f"{i}. {desc}\n"
    
    spec += """
## Constraints
- Must be a Python CLI
- Must use argparse
- Must execute deterministically

## Definition of Done
- All intents are implemented
- CLI executes successfully
- Verification passes
"""
    return spec


def generate_plan_from_tasks(tasks_json: Dict[str, Any]) -> str:
    """Generate PLAN.md from TASKS.json deterministically."""
    tasks = tasks_json.get("tasks", [])
    
    plan = "# Execution Plan\n\n"
    plan += "## Overview\n"
    plan += "Generate Python CLI implementing requested intents.\n\n"
    plan += "## Execution Sequence\n\n"
    
    for task in tasks:
        task_id = task.get("id", "")
        desc = task.get("description", "")
        plan += f"{task_id}: {desc}\n"
    
    return plan
