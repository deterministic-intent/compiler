#!/usr/bin/env python3
"""Migration script to add delta-aware schema."""

import os
import sqlite3
from pathlib import Path


def _db_path_from_env_or_default() -> Path:
    url = str(os.environ.get("DEV_DB_URL", "")).strip()
    if url.startswith("sqlite:////"):
        rest = url[len("sqlite:////") :]
        return Path(rest if rest.startswith("/") else ("/" + rest))
    if url.startswith("sqlite:///"):
        return Path(url[len("sqlite:///") :]).resolve()
    # Default: align with db/engine.py default (state/dev/db/dev.db)
    base = Path(__file__).resolve().parents[1]
    p = base / "state" / "dev" / "db" / "dev.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def migrate_delta_schema():
    """Add new tables for delta-aware crawling."""
    db_path = _db_path_from_env_or_default()
    
    if not db_path.exists():
        print("Database not found. Run init_db.py first.")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("Adding delta-aware schema...")
    
    # Create blobs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS blobs (
            blob_key TEXT PRIMARY KEY,
            bytes TEXT NOT NULL,
            etag TEXT,
            last_modified TEXT,
            status_code INTEGER,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create indexes for blobs
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_blob_etag ON blobs(etag)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_blob_fetched ON blobs(fetched_at)")
    
    # Create doc_units table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS doc_units (
            doc_key TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            url TEXT NOT NULL,
            blob_key TEXT NOT NULL,
            unit_hash TEXT NOT NULL,
            parsed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (blob_key) REFERENCES blobs(blob_key)
        )
    """)
    
    # Create indexes for doc_units
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_docunit_source ON doc_units(source_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_docunit_hash ON doc_units(unit_hash)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_docunit_parsed ON doc_units(parsed_at)")
    
    # Create events table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id INTEGER NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            kind TEXT NOT NULL,
            event_data TEXT DEFAULT '{}',
            FOREIGN KEY (node_id) REFERENCES nodes(id)
        )
    """)
    
    # Create indexes for events
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_event_node_time ON events(node_id, timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_event_kind ON events(kind)")
    
    # Add unit_hash column to nodes table if it doesn't exist
    try:
        cursor.execute("ALTER TABLE nodes ADD COLUMN unit_hash TEXT")
        print("Added unit_hash column to nodes table")
    except sqlite3.OperationalError:
        print("unit_hash column already exists in nodes table")
    
    # Add version column to nodes table if it doesn't exist
    try:
        cursor.execute("ALTER TABLE nodes ADD COLUMN version TEXT")
        print("Added version column to nodes table")
    except sqlite3.OperationalError:
        print("version column already exists in nodes table")
    
    conn.commit()
    conn.close()
    
    print("Delta schema migration complete!")

if __name__ == "__main__":
    migrate_delta_schema()
