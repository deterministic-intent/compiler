#!/usr/bin/env python3
"""
Step 11: Deterministic index DB builder (request-local, read-only index).

Builds a SQLite index from snapshots only:
- snapshot_resolution.json (Step 10)
- external snapshot(s): snapshots/external/<id>/
- knowledge snapshot metadata: nlc/db/snapshots/<knowledge_snapshot_id>/manifest/*

Outputs under state/requests/<id>/index/:
- index.db
- index.meta.json
- index.sha256
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE = Path(__file__).resolve().parents[2]


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _read_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8", errors="replace"))


def _write_text(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")


def _write_json(p: Path, obj: Any) -> None:
    _write_text(p, json.dumps(obj, indent=2, sort_keys=True) + "\n")


def _strip_html(text: str) -> str:
    # Deterministic minimal stripper: remove script/style blocks then tags.
    t = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", " ", text)
    t = re.sub(r"(?is)<[^>]+>", " ", t)
    t = unescape(t)
    t = " ".join(t.split())
    return t.strip()


def _extract_html_title(text: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", text)
    if not m:
        return ""
    title = _strip_html(m.group(1))
    return title[:120]


def _extract_title(kind: str, raw_text: str, json_obj: Optional[Any]) -> str:
    if kind == "html":
        return _extract_html_title(raw_text)
    if kind == "json" and isinstance(json_obj, dict) and isinstance(json_obj.get("title"), str):
        return str(json_obj.get("title")).strip()[:120]
    # text/unknown: first non-empty line
    for line in raw_text.splitlines():
        t = line.strip()
        if t:
            return t[:120]
    return ""


def _kind_from_content_type(content_type: str) -> str:
    ct = (content_type or "").lower()
    if "application/json" in ct or ct.endswith("+json"):
        return "json"
    if "text/html" in ct:
        return "html"
    if ct.startswith("text/"):
        return "text"
    return "unknown"


def _body_text(kind: str, raw_bytes: bytes, raw_text: str, json_obj: Optional[Any]) -> str:
    if kind == "json":
        try:
            if json_obj is None:
                json_obj = json.loads(raw_text)
            return json.dumps(json_obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        except Exception:
            return ""
    if kind == "html":
        return _strip_html(raw_text)
    if kind == "text":
        return raw_text
    return ""


def doc_id_for(source_id: str, body_sha256: str) -> str:
    return sha256_bytes((source_id + "\n" + body_sha256).encode("utf-8"))[:32]


def _apply_deterministic_pragmas(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=OFF;")
    cur.execute("PRAGMA synchronous=OFF;")
    cur.execute("PRAGMA temp_store=MEMORY;")
    cur.execute("PRAGMA locking_mode=EXCLUSIVE;")
    cur.execute("PRAGMA foreign_keys=ON;")
    cur.execute("PRAGMA user_version=1;")
    conn.commit()


def _create_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.executescript(
        """
        DROP TABLE IF EXISTS sources;
        DROP TABLE IF EXISTS documents;
        DROP TABLE IF EXISTS kv;
        DROP TABLE IF EXISTS fts_docs;

        CREATE TABLE sources (
          source_id TEXT PRIMARY KEY,
          content_type TEXT,
          sha256 TEXT,
          byte_length INTEGER,
          filename TEXT,
          fetch_timestamp TEXT
        );

        CREATE TABLE documents (
          doc_id TEXT PRIMARY KEY,
          source_id TEXT,
          kind TEXT,
          title TEXT,
          body_text TEXT,
          body_sha256 TEXT,
          created_at TEXT
        );

        CREATE TABLE kv (
          k TEXT PRIMARY KEY,
          v TEXT
        );
        """
    )

    # FTS5 optional. If not available, we keep deterministic fallback search in Python.
    try:
        cur.execute("CREATE VIRTUAL TABLE fts_docs USING fts5(title, body_text);")
    except Exception:
        cur.execute("CREATE TABLE fts_docs (title TEXT, body_text TEXT);")
    conn.commit()


def _load_snapshot_resolution(request_dir: Path) -> Dict[str, Any]:
    p = request_dir / "snapshot_resolution.json"
    if not p.exists():
        raise FileNotFoundError(f"snapshot_resolution.json missing: {p}")
    obj = _read_json(p)
    if not isinstance(obj, dict):
        raise ValueError("snapshot_resolution.json must be an object")
    return obj


def _resolve_ids(sr: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    ext = None
    know = None
    db = None
    ordered = sr.get("ordered_snapshots", [])
    if isinstance(ordered, list):
        for e in ordered:
            if not isinstance(e, dict):
                continue
            t = e.get("type")
            sid = e.get("snapshot_id")
            if t == "external" and isinstance(sid, str):
                ext = sid
            if t == "knowledge" and isinstance(sid, str):
                know = sid
            if t == "db" and isinstance(sid, str):
                db = sid
    return ext, know, db


def _insert_kv(cur: sqlite3.Cursor, pairs: Dict[str, str]) -> None:
    for k in sorted(pairs.keys()):
        cur.execute("INSERT OR REPLACE INTO kv(k, v) VALUES(?, ?);", (k, pairs[k]))


def build_index(request_dir: Path) -> Path:
    request_dir = request_dir.resolve()
    sr = _load_snapshot_resolution(request_dir)
    external_id, knowledge_id, db_id = _resolve_ids(sr)

    index_dir = request_dir / "index"
    if index_dir.exists():
        # full rebuild only (Step 11)
        for child in sorted(index_dir.rglob("*"), key=lambda p: str(p)):
            if child.is_file():
                child.unlink(missing_ok=True)
        # keep directory
    index_dir.mkdir(parents=True, exist_ok=True)

    db_path = index_dir / "index.db"
    meta_path = index_dir / "index.meta.json"
    sha_path = index_dir / "index.sha256"

    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    try:
        _apply_deterministic_pragmas(conn)
        _create_schema(conn)
        cur = conn.cursor()

        # KV metadata from snapshot resolution and knowledge manifests
        kv: Dict[str, str] = {
            "request_id": str(sr.get("request_id", request_dir.name)),
            "policy_version": str((_read_json(request_dir / "payload.json") or {}).get("policy_version", "v1")) if (request_dir / "payload.json").exists() else "v1",
        }

        # Knowledge snapshot metadata (manifest bundle hash + toolchain pins hash)
        if knowledge_id:
            from nlc.reproducibility import get_manifest_hashes
            mi = get_manifest_hashes(knowledge_id)
            kv["knowledge_snapshot_id"] = knowledge_id
            kv["manifest_bundle_hash"] = str(mi.get("manifest_bundle_hash", "")).strip()
            pins_path = BASE / "nlc" / "db" / "snapshots" / knowledge_id / "manifest" / "toolchain_pins.json"
            if pins_path.exists():
                pins_bytes = json.dumps(_read_json(pins_path), sort_keys=True, separators=(",", ":")).encode("utf-8")
                kv["toolchain_pins_sha256"] = sha256_bytes(pins_bytes)

        if external_id:
            kv["external_snapshot_id"] = external_id

        _insert_kv(cur, kv)

        # External sources -> sources + documents
        sources_meta: List[Dict[str, Any]] = []
        if external_id:
            snap_dir = BASE / "snapshots" / "external" / external_id
            manifest_path = snap_dir / "sources.manifest.json"
            if not manifest_path.exists():
                raise FileNotFoundError(f"external sources.manifest.json missing: {manifest_path}")
            mobj = _read_json(manifest_path)
            entries = mobj.get("entries", []) if isinstance(mobj, dict) else []
            if not isinstance(entries, list):
                entries = []

            # Deterministic ordering by source_id
            entries_sorted = sorted(
                [e for e in entries if isinstance(e, dict) and isinstance(e.get("source_id"), str)],
                key=lambda e: str(e.get("source_id")),
            )

            for e in entries_sorted:
                source_id = str(e.get("source_id")).strip()
                content_type = str(e.get("content_type", "")).strip()
                filename = str(e.get("filename", "")).strip()
                sha256 = str(e.get("sha256", "")).strip()
                byte_length = int(e.get("byte_length", 0) or 0)
                fetch_ts = str(e.get("fetch_timestamp", "")).strip()

                # Determinism rule: do not store fetch_timestamp in DB bytes; normalize to empty string.
                cur.execute(
                    "INSERT OR REPLACE INTO sources(source_id, content_type, sha256, byte_length, filename, fetch_timestamp) VALUES(?, ?, ?, ?, ?, ?);",
                    (source_id, content_type, sha256, byte_length, filename, ""),
                )

                sources_meta.append(
                    {
                        "source_id": source_id,
                        "content_type": content_type,
                        "sha256": sha256,
                        "byte_length": byte_length,
                        "filename": filename,
                        "fetch_timestamp": "",  # normalized; timestamps ignored for determinism
                    }
                )

                file_path = snap_dir / filename
                raw = file_path.read_bytes()
                raw_text = raw.decode("utf-8", errors="replace")
                kind = _kind_from_content_type(content_type)

                json_obj = None
                if kind == "json":
                    try:
                        json_obj = json.loads(raw_text)
                    except Exception:
                        json_obj = None
                title = _extract_title(kind, raw_text, json_obj)
                body_text = _body_text(kind, raw, raw_text, json_obj)
                body_sha = sha256_bytes(body_text.encode("utf-8"))
                did = doc_id_for(source_id, body_sha)

                cur.execute(
                    "INSERT OR REPLACE INTO documents(doc_id, source_id, kind, title, body_text, body_sha256, created_at) VALUES(?, ?, ?, ?, ?, ?, ?);",
                    (did, source_id, kind, title, body_text, body_sha, ""),
                )

        # FTS populate deterministically (if virtual table exists)
        try:
            # If fts_docs is virtual FTS5, this will work; if it's a normal table, also works.
            cur.execute("DELETE FROM fts_docs;")
            # Deterministic ordering
            rows = cur.execute("SELECT title, body_text FROM documents ORDER BY doc_id;").fetchall()
            cur.executemany("INSERT INTO fts_docs(title, body_text) VALUES(?, ?);", rows)
        except Exception:
            pass

        conn.commit()
        # Canonicalize file layout
        try:
            cur.execute("VACUUM;")
            conn.commit()
        except Exception:
            pass
    finally:
        conn.close()

    db_bytes = db_path.read_bytes()
    meta_obj = {
        "request_id": str(sr.get("request_id", request_dir.name)),
        "snapshot_resolution_sha256": sha256_bytes((request_dir / "snapshot_resolution.json").read_bytes()),
        "timestamp_fields_ignored": ["sources.fetch_timestamp"],
        "sources": sorted(sources_meta, key=lambda x: x["source_id"]),
    }
    _write_json(meta_path, meta_obj)

    combined = db_bytes + meta_path.read_bytes()
    digest = sha256_bytes(combined)
    _write_text(sha_path, digest + "\n")
    return db_path


