#!/usr/bin/env python3
"""
Step 11: Deterministic query API over request-local index DB.

Used by planner/verifier to avoid ad-hoc parsing of snapshots.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


def open_index(request_dir: Path) -> sqlite3.Connection:
    request_dir = Path(request_dir).resolve()
    db_path = request_dir / "index" / "index.db"
    if not db_path.exists():
        raise FileNotFoundError(f"index missing: {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def get_doc(conn: sqlite3.Connection, doc_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT doc_id, source_id, kind, title, body_text, body_sha256 FROM documents WHERE doc_id = ?;",
        (doc_id,),
    ).fetchone()
    return dict(row) if row else None


def _fts_available(conn: sqlite3.Connection) -> bool:
    try:
        r = conn.execute("SELECT sql FROM sqlite_master WHERE name='fts_docs';").fetchone()
        if not r:
            return False
        sql = str(r[0] or "")
        return "VIRTUAL TABLE" in sql.upper() and "FTS5" in sql.upper()
    except Exception:
        return False


def _fallback_search(conn: sqlite3.Connection, query: str, limit: int) -> List[Dict[str, Any]]:
    q = (query or "").lower()
    rows = conn.execute("SELECT doc_id, title, body_text FROM documents;").fetchall()
    scored = []
    for r in rows:
        title = str(r["title"] or "")
        body = str(r["body_text"] or "")
        text = (title + "\n" + body).lower()
        if not q:
            score = 0
        else:
            score = text.count(q)
        if score > 0:
            scored.append((score, str(r["doc_id"]), title, body))
    # Deterministic rank: score desc, then doc_id asc
    scored.sort(key=lambda x: (-x[0], x[1]))
    out = []
    for score, doc_id, title, body in scored[: max(0, int(limit))]:
        snippet = body[:200]
        out.append({"doc_id": doc_id, "title": title, "snippet": snippet, "score": score})
    return out


def search(conn: sqlite3.Connection, query: str, limit: int = 10) -> List[Dict[str, Any]]:
    limit = int(limit)
    if limit <= 0:
        return []
    q = (query or "").strip()
    if not q:
        return []

    if _fts_available(conn):
        try:
            rows = conn.execute(
                "SELECT d.doc_id as doc_id, d.title as title, substr(d.body_text, 1, 200) as snippet "
                "FROM fts_docs f JOIN documents d ON (d.title = f.title AND d.body_text = f.body_text) "
                "WHERE fts_docs MATCH ? ORDER BY d.doc_id ASC LIMIT ?;",
                (q, limit),
            ).fetchall()
            return [{"doc_id": str(r["doc_id"]), "title": str(r["title"] or ""), "snippet": str(r["snippet"] or ""), "score": 1} for r in rows]
        except Exception:
            return _fallback_search(conn, q, limit)

    return _fallback_search(conn, q, limit)


