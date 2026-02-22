#!/usr/bin/env python3
"""
Deterministic capability-bound classifier.

Purpose:
- Choose an artifact_class and language ONLY from snapshot-derived capabilities.json
- No silent fallback-to-default behavior
- Ambiguous/unspecified -> CLARIFY-style result (caller decides how to surface)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class CapabilityDecision:
    status: str  # "PASS" | "CLARIFY" | "UNSUPPORTED"
    artifact_class: Optional[str]
    language: Optional[str]
    reason: str
    questions: List[str]


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _contains_any(text: str, needles: List[str]) -> bool:
    for n in needles:
        if n and n in text:
            return True
    return False


def _artifact_class_to_language(ac: str) -> str:
    if ac.startswith("python_"):
        return "python"
    if ac == "webview":
        return "web"
    return ac


def classify_request(
    request_text: str,
    *,
    capabilities: Dict[str, Any],
) -> CapabilityDecision:
    """
    Deterministically classify request_text into an artifact class constrained by capabilities.

    Rules:
    - If request clearly signals a category and that artifact_class is supported => PASS
    - If request signals multiple categories => CLARIFY (no guess)
    - If request signals a category but it's not supported => UNSUPPORTED
    - If request doesn't signal any category => CLARIFY (no default)
    """
    txt = " " + _norm(request_text) + " "
    reachable = capabilities.get("reachable_artifact_classes_from_text", [])
    if isinstance(reachable, list) and reachable:
        supported_list = [str(x).strip() for x in reachable]
    else:
        supported = capabilities.get("supported_artifact_classes", [])
        supported_list = [str(x).strip() for x in supported] if isinstance(supported, list) else []
    supported_set = {x for x in supported_list if x}

    # Category signals (deterministic, minimal v1 rules)
    hits: List[str] = []
    if _contains_any(txt, [" web ", "web ui", "web app", " frontend ", " html ", " javascript ", " browser "]):
        hits.append("webview")
    if _contains_any(txt, [" api ", " rest ", " endpoint ", " server ", " flask ", " fastapi "]):
        hits.append("python_api")
    if _contains_any(txt, [" gui ", " tkinter ", " desktop window ", " desktop gui ", " window "]):
        hits.append("python_gui")
    if _contains_any(txt, [" cli ", " command line ", " argparse ", " terminal "]):
        hits.append("python_cli")

    # Deduplicate while preserving deterministic order
    seen = set()
    hits = [h for h in hits if not (h in seen or seen.add(h))]

    if len(hits) == 1:
        ac = hits[0]
        if supported_set and ac not in supported_set:
            return CapabilityDecision(
                status="UNSUPPORTED",
                artifact_class=ac,
                language=_artifact_class_to_language(ac),
                reason="UNSUPPORTED_CAPABILITY",
                questions=[],
            )
        return CapabilityDecision(
            status="PASS",
            artifact_class=ac,
            language=_artifact_class_to_language(ac),
            reason="OK",
            questions=[],
        )

    if len(hits) > 1:
        return CapabilityDecision(
            status="CLARIFY",
            artifact_class=None,
            language=None,
            reason="AMBIGUOUS_CAPABILITY",
            questions=[
                "Which artifact class should this request target? Choose exactly one from supported_artifact_classes.",
            ],
        )

    # No signal => CLARIFY (no default)
    return CapabilityDecision(
        status="CLARIFY",
        artifact_class=None,
        language=None,
        reason="MISSING_CAPABILITY_HINT",
        questions=[
            "This request does not specify an artifact class (CLI, API, GUI, or web UI). Which should it be?",
        ],
    )


