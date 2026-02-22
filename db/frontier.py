#!/usr/bin/env python3
"""Frontier table for tracking URL crawling state."""

import sqlite3
import time
import os
from typing import List, Dict, Any
from pathlib import Path


def _default_frontier_db_path() -> str:
    """
    Default frontier DB path aligned with db/engine.py default (state/dev/db/dev.db).
    """
    base = Path(__file__).resolve().parents[1]
    p = base / "state" / "dev" / "db" / "dev.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def _frontier_db_path_from_env() -> str:
    """
    If DEV_DB_URL is a sqlite file URL, use the same file for frontier.
    Otherwise fall back to the default state/dev/db/dev.db path.
    """
    url = str(os.environ.get("DEV_DB_URL", "")).strip()
    if url.startswith("sqlite:////"):
        # SQLAlchemy absolute file URL: sqlite:////absolute/path.db
        rest = url[len("sqlite:////") :]
        return rest if rest.startswith("/") else ("/" + rest)
    if url.startswith("sqlite:///"):
        # sqlite:///relative_or_abs; treat as path from CWD if relative.
        p = url[len("sqlite:///") :]
        return str(Path(p).resolve())
    if url.startswith("sqlite://"):
        # e.g. sqlite:///:memory:
        p = url[len("sqlite://") :]
        if p == "/:memory:":
            return ":memory:"
    return _default_frontier_db_path()


class FrontierManager:
    """Manage the crawling frontier with safe completion logic."""
    
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or _frontier_db_path_from_env()
        self.init_frontier_table()
    
    def init_frontier_table(self):
        """Initialize the frontier table."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create frontier table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS frontier (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                source TEXT NOT NULL,
                status TEXT CHECK(status IN ('queued', 'fetching', 'done', 'error')) DEFAULT 'queued',
                ts_added INTEGER DEFAULT (strftime('%s','now')),
                ts_updated INTEGER DEFAULT (strftime('%s','now')),
                depth INTEGER DEFAULT 0,
                retries INTEGER DEFAULT 0
            )
        """)
        
        # Create indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS frontier_src_status_ts 
            ON frontier(source, status, ts_added)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS frontier_url 
            ON frontier(url)
        """)
        
        conn.commit()
        conn.close()
    
    def enqueue_url(self, url: str, source: str, depth: int = 0) -> bool:
        """Add URL to frontier queue."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO frontier(url, source, status, depth, ts_added, ts_updated)
                VALUES (?, ?, 'queued', ?, strftime('%s','now'), strftime('%s','now'))
                ON CONFLICT(url) DO NOTHING
            """, (url, source, depth))
            
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error enqueueing URL {url}: {e}")
            return False
        finally:
            conn.close()
    
    def get_queued_urls(self, source: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get queued URLs for a source."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT url, depth, retries
            FROM frontier 
            WHERE source = ? AND status = 'queued'
            ORDER BY ts_added ASC
            LIMIT ?
        """, (source, limit))
        
        urls = []
        for row in cursor.fetchall():
            urls.append({
                "url": row[0],
                "depth": row[1],
                "retries": row[2]
            })
        
        conn.close()
        return urls

    def get_queued_urls_breadth(self, source: str, max_urls: int) -> List[Dict[str, Any]]:
        """
        Deterministic breadth sampling over queued URLs (ordered by URL).
        Returns up to max_urls evenly spaced across the queue.
        """
        if max_urls <= 0:
            return []
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM frontier WHERE source = ? AND status = 'queued'",
            (source,),
        )
        total = int(cursor.fetchone()[0] or 0)
        if total == 0:
            conn.close()
            return []
        limit = min(max_urls, total)
        # stride ensures deterministic spread across the sorted URL list
        stride = max(1, total // limit)
        urls: List[Dict[str, Any]] = []
        for i in range(limit):
            offset = i * stride
            cursor.execute(
                """
                SELECT url, depth, retries
                FROM frontier
                WHERE source = ? AND status = 'queued'
                ORDER BY url ASC
                LIMIT 1 OFFSET ?
                """,
                (source, offset),
            )
            row = cursor.fetchone()
            if not row:
                break
            urls.append({"url": row[0], "depth": row[1], "retries": row[2]})
        conn.close()
        return urls
    
    def mark_url_fetching(self, url: str):
        """Mark URL as being fetched."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE frontier 
            SET status = 'fetching', ts_updated = strftime('%s','now')
            WHERE url = ?
        """, (url,))
        
        conn.commit()
        conn.close()
    
    def mark_url_done(self, url: str):
        """Mark URL as successfully processed."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE frontier 
            SET status = 'done', ts_updated = strftime('%s','now')
            WHERE url = ?
        """, (url,))
        
        conn.commit()
        conn.close()
    
    def mark_url_error(self, url: str):
        """Mark URL as failed."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE frontier 
            SET status = 'error', retries = retries + 1, ts_updated = strftime('%s','now')
            WHERE url = ?
        """, (url,))
        
        conn.commit()
        conn.close()
    
    def get_source_stats(self, source: str) -> Dict[str, Any]:
        """Get statistics for a source."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) as urls_remaining,
                SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) as urls_done,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as urls_error,
                SUM(CASE WHEN status = 'fetching' THEN 1 ELSE 0 END) as urls_fetching,
                COUNT(*) as total_urls
            FROM frontier 
            WHERE source = ?
        """, (source,))
        
        row = cursor.fetchone()
        stats = {
            "urls_remaining": row[0] or 0,
            "urls_done": row[1] or 0,
            "urls_error": row[2] or 0,
            "urls_fetching": row[3] or 0,
            "total_urls": row[4] or 0
        }
        
        conn.close()
        return stats
    
    def is_source_complete(self, source: str, grace_period_seconds: int = 60) -> bool:
        """Check if source is safely complete (no queued URLs + grace period)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            WITH now_ts AS (SELECT strftime('%s','now') AS t)
            SELECT 
                SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) as urls_remaining,
                COALESCE(MAX(CASE WHEN status = 'queued' THEN ts_added END), 0) as last_queued_ts
            FROM frontier f, now_ts n
            WHERE f.source = ?
        """, (source,))
        
        row = cursor.fetchone()
        urls_remaining = row[0] or 0
        last_queued_ts = row[1] or 0
        current_ts = int(time.time())
        
        conn.close()
        
        # Source is complete if no queued URLs and no new URLs added in grace period
        return urls_remaining == 0 and (current_ts - last_queued_ts) > grace_period_seconds
    
    def get_completed_sources(self, grace_period_seconds: int = 60) -> List[str]:
        """Get list of sources that are safely complete."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            WITH now_ts AS (SELECT strftime('%s','now') AS t)
            SELECT f.source
            FROM frontier f, now_ts n
            GROUP BY f.source
            HAVING SUM(CASE WHEN f.status = 'queued' THEN 1 ELSE 0 END) = 0
               AND COALESCE(MAX(CASE WHEN f.status = 'queued' THEN f.ts_added END), 0) < (n.t - ?)
        """, (grace_period_seconds,))
        
        sources = [row[0] for row in cursor.fetchall()]
        conn.close()
        return sources
    
    def get_all_stats(self) -> Dict[str, Any]:
        """Get overall frontier statistics."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                COUNT(DISTINCT source) as total_sources,
                SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) as total_queued,
                SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) as total_done,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as total_error,
                SUM(CASE WHEN status = 'fetching' THEN 1 ELSE 0 END) as total_fetching
            FROM frontier
        """)
        
        row = cursor.fetchone()
        stats = {
            "total_sources": row[0] or 0,
            "total_queued": row[1] or 0,
            "total_done": row[2] or 0,
            "total_error": row[3] or 0,
            "total_fetching": row[4] or 0
        }
        
        conn.close()
        return stats

# Global frontier manager instance
frontier = FrontierManager()
