#!/usr/bin/env python3
"""
Step 13: Deterministic answer artifact builder (index-backed, evidence-locked).

Builds answer.json using ONLY:
- payload.json
- index/index.db (presence only; no ad-hoc parsing)
- planner/plan.json (evidence excerpts are source of truth)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List


def _dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"


def _sha256_utf8(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def build_answer(request_dir: str) -> Dict[str, Any]:
    rd = Path(request_dir).resolve()

    payload_path = rd / "payload.json"
    plan_path = rd / "planner" / "plan.json"
    index_path = rd / "index" / "index.db"

    payload = {}
    if payload_path.exists():
        payload = json.loads(payload_path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(payload, dict):
        payload = {}

    plan = {}
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(plan, dict):
        plan = {}

    # Presence check only (verifier enforces sha pinning via Step 11 check)
    if not index_path.exists():
        raise FileNotFoundError(f"index missing: {index_path}")

    evidence_in = plan.get("evidence", [])
    if not isinstance(evidence_in, list):
        evidence_in = []

    # Evidence entries must be copied exactly from plan evidence excerpts (no regeneration).
    # Deterministic ordering: (doc_id, excerpt_sha256) then rank assigned 1..n
    normalized: List[Dict[str, Any]] = []
    for e in evidence_in:
        if not isinstance(e, dict):
            continue
        doc_id = str(e.get("doc_id", "")).strip()
        source_id = str(e.get("source_id", "")).strip()
        excerpt = str(e.get("excerpt", "") or "")
        excerpt_sha256 = str(e.get("excerpt_sha256", "")).strip().lower()
        normalized.append(
            {
                "doc_id": doc_id,
                "source_id": source_id,
                "excerpt": excerpt,
                "excerpt_sha256": excerpt_sha256,
            }
        )
    normalized.sort(key=lambda x: (x.get("doc_id", ""), x.get("excerpt_sha256", "")))

    evidence: List[Dict[str, Any]] = []
    for i, e in enumerate(normalized, start=1):
        evidence.append(
            {
                "doc_id": e["doc_id"],
                "source_id": e["source_id"],
                "excerpt": e["excerpt"],
                "excerpt_sha256": e["excerpt_sha256"],
                "rank": i,
            }
        )

    # Enforced sort rule: (rank, doc_id, excerpt_sha256)
    evidence.sort(key=lambda x: (int(x.get("rank", 0)), x.get("doc_id", ""), x.get("excerpt_sha256", "")))

    answer = "\n\n".join([str(e.get("excerpt", "") or "") for e in evidence])
    answer_sha256 = _sha256_utf8(answer)
    evidence_bundle_sha256 = hashlib.sha256(_dump(evidence).encode("utf-8")).hexdigest()

    out = {
        "request_id": str(payload.get("request_id", rd.name)),
        "answer_mode": "index_backed",
        "question": str(payload.get("goal", "")),
        "answer": answer,
        "evidence": evidence,
        "answer_sha256": answer_sha256,
        "evidence_bundle_sha256": evidence_bundle_sha256,
        "created_by": "answer_builder_v1",
    }

    out_dir = rd / "answer"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "answer.json").write_text(_dump(out), encoding="utf-8")
    return out


