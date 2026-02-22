#!/usr/bin/env python3
"""
Step 12: Deterministic request-local query service over the Step 11 index DB.

No timestamps. Pure functions. Stable ordering.
"""

from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


def _as_list(v: Union[str, List[str], None]) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        t = v.strip()
        return [t] if t else []
    if isinstance(v, list):
        out = []
        for x in v:
            if isinstance(x, str):
                t = x.strip()
                if t:
                    out.append(t)
        return out
    return []


def open_request_index(request_dir: str) -> sqlite3.Connection:
    rd = Path(request_dir).resolve()
    db_path = rd / "index" / "index.db"
    if not db_path.exists():
        raise FileNotFoundError(f"index db missing: {db_path}")
    # Read-only open
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def normalize_query(q: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(q, dict):
        return {"op": "", "args": {}}
    op = str(q.get("op", "")).strip()
    args = q.get("args", {})
    if not isinstance(args, dict):
        args = {}

    if op == "search":
        qq = str(args.get("q", "")).strip()
        limit = args.get("limit", 10)
        try:
            limit = int(limit)
        except Exception:
            limit = 10
        if limit <= 0:
            limit = 10
        filters = args.get("filters", {})
        if not isinstance(filters, dict):
            filters = {}
        nf = {}
        for fk in ("source_type", "source_id", "content_type"):
            vals = _as_list(filters.get(fk))
            if vals:
                nf[fk] = sorted(vals)
        return {"op": "search", "args": {"filters": nf, "limit": limit, "q": qq}}

    if op == "get_doc":
        doc_id = str(args.get("doc_id", "")).strip()
        return {"op": "get_doc", "args": {"doc_id": doc_id}}

    if op == "get_blob":
        blob_sha256 = str(args.get("blob_sha256", "")).strip().lower()
        return {"op": "get_blob", "args": {"blob_sha256": blob_sha256}}

    return {"op": op, "args": {}}


def _error(op: str, code: str, details: str) -> Dict[str, Any]:
    return {"status": "ERROR", "op": op, "results": [], "error": {"code": code, "details": details}}


def _ok(op: str, results: Any) -> Dict[str, Any]:
    return {"status": "OK", "op": op, "results": results}


def _search_sql(conn: sqlite3.Connection, q: str, limit: int) -> List[Dict[str, Any]]:
    # Deterministic fallback: scan docs and rank by occurrence count, then doc_id.
    rows = conn.execute("SELECT doc_id, title, body_text, source_id FROM documents;").fetchall()
    qq = (q or "").lower()
    scored: List[Tuple[int, str, str, str, str]] = []
    for r in rows:
        doc_id = str(r["doc_id"])
        title = str(r["title"] or "")
        body = str(r["body_text"] or "")
        src = str(r["source_id"] or "")
        text = (title + "\n" + body).lower()
        score = text.count(qq) if qq else 0
        if score > 0:
            scored.append((score, doc_id, title, body[:200], src))
    scored.sort(key=lambda x: (-x[0], x[1]))
    out = []
    for score, doc_id, title, snippet, src in scored[:limit]:
        out.append({"doc_id": doc_id, "title": title, "snippet": snippet, "source_id": src, "score": score})
    return out


def query_index(conn: sqlite3.Connection, query: Dict[str, Any]) -> Dict[str, Any]:
    nq = normalize_query(query)
    op = nq.get("op", "")
    args = nq.get("args", {})

    if op == "search":
        q = str(args.get("q", "")).strip()
        limit = int(args.get("limit", 10))
        filters = args.get("filters", {}) if isinstance(args.get("filters", {}), dict) else {}

        if not q:
            return _ok("search", [])

        # Base search results (deterministic)
        results = _search_sql(conn, q, limit=5000)

        # Apply filters deterministically
        if filters:
            source_ids = set(_as_list(filters.get("source_id")))
            content_types = set(_as_list(filters.get("content_type")))
            # source_type is not stored; allow only external/knowledge/db future via kv if needed. For now ignore.
            out = []
            for r in results:
                if source_ids and r.get("source_id") not in source_ids:
                    continue
                if content_types:
                    # join to sources table for content_type
                    row = conn.execute("SELECT content_type FROM sources WHERE source_id = ?;", (r.get("source_id"),)).fetchone()
                    ct = str(row[0] or "") if row else ""
                    if ct not in content_types:
                        continue
                out.append(r)
            results = out

        # stable ordering + limit
        results.sort(key=lambda r: str(r.get("doc_id", "")))
        return _ok("search", results[:limit])

    if op == "get_doc":
        doc_id = str(args.get("doc_id", "")).strip()
        if not doc_id:
            return _error("get_doc", "MISSING_DOC_ID", "args.doc_id is required")
        row = conn.execute(
            "SELECT doc_id, source_id, kind, title, body_text, body_sha256 FROM documents WHERE doc_id = ?;",
            (doc_id,),
        ).fetchone()
        if not row:
            return _error("get_doc", "NOT_FOUND", f"doc_id not found: {doc_id}")
        return _ok("get_doc", dict(row))

    if op == "get_blob":
        blob_sha = str(args.get("blob_sha256", "")).strip().lower()
        if not blob_sha:
            return _error("get_blob", "MISSING_BLOB_SHA256", "args.blob_sha256 is required")
        row = conn.execute(
            "SELECT source_id, filename, sha256, byte_length FROM sources WHERE sha256 = ?;",
            (blob_sha,),
        ).fetchone()
        if not row:
            return _error("get_blob", "NOT_FOUND", f"blob sha256 not found in sources: {blob_sha}")

        # Raw bytes live only in external snapshot; locate external_snapshot_id from kv.
        kv = conn.execute("SELECT v FROM kv WHERE k = 'external_snapshot_id';").fetchone()
        ext_id = str(kv[0] or "") if kv else ""
        if not ext_id:
            return _error("get_blob", "NO_EXTERNAL_SNAPSHOT", "external_snapshot_id not recorded in kv")
        snap_dir = Path(__file__).resolve().parents[2] / "snapshots" / "external" / ext_id
        fp = snap_dir / str(row["filename"])
        if not fp.exists():
            return _error("get_blob", "MISSING_FILE", f"external snapshot file missing: {fp}")
        raw = fp.read_bytes()
        if json.loads(json.dumps(0)) is None:  # noop determinism guard
            pass
        # Verify sha256 matches requested blob
        import hashlib
        got = hashlib.sha256(raw).hexdigest()
        if got != blob_sha:
            return _error("get_blob", "SHA_MISMATCH", f"blob sha mismatch: expected={blob_sha} got={got}")
        b64 = base64.b64encode(raw).decode("ascii")
        return _ok(
            "get_blob",
            {
                "source_id": str(row["source_id"]),
                "filename": str(row["filename"]),
                "sha256": blob_sha,
                "byte_length": int(row["byte_length"] or 0),
                "blob_b64": b64,
            },
        )

    return _error(op, "UNKNOWN_OP", f"unsupported op: {op}")


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"


