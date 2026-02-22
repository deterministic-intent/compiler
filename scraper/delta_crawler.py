#!/usr/bin/env python3
"""Delta-aware crawler with ETag/Last-Modified support."""

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import httpx
from sqlalchemy.orm import Session

from db.engine import get_session
from db.models import Blob, DocUnit, Node, Event
from db.frontier import FrontierManager
from scraper.base_scraper import BaseScraper
from scraper.normalizer import normalize_content


class DeltaCrawler:
    """Delta-aware crawler that only processes changed content."""
    
    def __init__(self, source_config: Dict[str, Any]):
        self.source_config = source_config
        self.source_id = source_config.get('id', source_config.get('language', 'unknown'))
        self.source_url = source_config.get('url')
        self.max_depth = source_config.get('crawl', {}).get('depth', 2)
        self.max_urls_per_source = 5000
        self.min_body_length = 800
        self.frontier = FrontierManager()
        
        # Performance tracking
        self.fetch_times = []
        self.parse_times = []
        self.stats = {
            'urls_fetched': 0,
            'urls_unchanged': 0,
            'urls_changed': 0,
            'urls_error': 0,
            'blobs_created': 0,
            'nodes_created': 0,
            'nodes_updated': 0
        }
    
    def compute_hash(self, content: str) -> str:
        """Compute SHA256 hash of content."""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    def get_existing_blob(self, blob_key: str) -> Optional[Blob]:
        """Get existing blob by hash."""
        with get_session() as session:
            return session.query(Blob).filter(Blob.blob_key == blob_key).first()
    
    def get_existing_doc_unit(self, doc_key: str) -> Optional[DocUnit]:
        """Get existing doc unit by URL hash."""
        with get_session() as session:
            return session.query(DocUnit).filter(DocUnit.doc_key == doc_key).first()
    
    def store_blob(self, content: str, etag: Optional[str], last_modified: Optional[str], status_code: int) -> str:
        """Store content in blob table, return blob_key."""
        blob_key = self.compute_hash(content)
        
        # Check if blob already exists
        existing = self.get_existing_blob(blob_key)
        if existing:
            return blob_key
        
        # Create new blob
        with get_session() as session:
            blob = Blob(
                blob_key=blob_key,
                bytes=content,
                etag=etag,
                last_modified=last_modified,
                status_code=status_code,
                fetched_at=datetime.utcnow()
            )
            session.add(blob)
            session.commit()
            self.stats['blobs_created'] += 1
        
        return blob_key
    
    def store_doc_unit(self, url: str, blob_key: str, unit_hash: str) -> str:
        """Store document unit, return doc_key."""
        doc_key = self.compute_hash(url)
        
        with get_session() as session:
            existing = session.query(DocUnit).filter(DocUnit.doc_key == doc_key).first()
            
            if existing:
                if existing.unit_hash == unit_hash:
                    # No change
                    return doc_key
                else:
                    # Update existing
                    existing.blob_key = blob_key
                    existing.unit_hash = unit_hash
                    existing.parsed_at = datetime.utcnow()
                    session.commit()
                    self.stats['nodes_updated'] += 1
            else:
                # Create new
                doc_unit = DocUnit(
                    doc_key=doc_key,
                    source_id=self.source_id,
                    url=url,
                    blob_key=blob_key,
                    unit_hash=unit_hash,
                    parsed_at=datetime.utcnow()
                )
                session.add(doc_unit)
                session.commit()
                self.stats['nodes_created'] += 1
            
            return doc_key
    
    def create_nodes_from_content(self, content: str, url: str, title: str) -> List[Node]:
        """Create knowledge nodes from parsed content."""
        # Parse content using existing pipeline
        parsed_data = {
            'title': title,
            'content': content,
            'url': url
        }
        
        chunks = normalize_content(parsed_data, self.source_config.get('language', 'unknown'))
        
        nodes = []
        with get_session() as session:
            for chunk in chunks:
                # Check if node already exists (by title and language)
                existing = session.query(Node).filter(
                    Node.title == chunk['title'],
                    Node.language == chunk['language']
                ).first()
                
                if existing:
                    # Update existing node
                    for field, value in chunk.items():
                        if hasattr(existing, field):
                            setattr(existing, field, value)
                    existing.unit_hash = self.compute_hash(chunk['content'])
                    existing.updated_at = datetime.utcnow()
                    nodes.append(existing)
                else:
                    # Create new node
                    node = Node(
                        title=chunk['title'],
                        content=chunk['content'],
                        node_type=chunk['node_type'],
                        language=chunk['language'],
                        stack=chunk.get('stack'),
                        tags=chunk.get('tags', []),
                        source_url=chunk.get('source_url'),
                        source_title=chunk.get('source_title'),
                        unit_hash=self.compute_hash(chunk['content'])
                    )
                    session.add(node)
                    nodes.append(node)
            
            session.commit()
        
        return nodes
    
    def add_event(self, node_id: int, kind: str, metadata: Dict[str, Any] = None):
        """Add timeline event for a node."""
        with get_session() as session:
            event = Event(
                node_id=node_id,
                kind=kind,
                event_data=metadata or {}
            )
            session.add(event)
            session.commit()
    
    async def fetch_with_conditional_headers(self, session: httpx.AsyncClient, url: str) -> Tuple[Optional[str], Optional[str], Optional[str], int]:
        """Fetch URL with conditional headers for delta updates."""
        # Get existing blob info
        doc_key = self.compute_hash(url)
        existing_doc = self.get_existing_doc_unit(doc_key)
        
        headers = {}
        if existing_doc and existing_doc.blob:
            if existing_doc.blob.etag:
                headers['If-None-Match'] = existing_doc.blob.etag
            if existing_doc.blob.last_modified:
                headers['If-Modified-Since'] = existing_doc.blob.last_modified
        
        try:
            response = await session.get(url, headers=headers, timeout=30.0)
            
            etag = response.headers.get('etag')
            last_modified = response.headers.get('last-modified')
            
            if response.status_code == 304:
                # Not modified
                return None, etag, last_modified, 304
            
            return response.text, etag, last_modified, response.status_code
            
        except Exception as e:
            print(f"Failed to fetch {url}: {e}")
            return None, None, None, 0
    
    async def process_url(self, session: httpx.AsyncClient, url: str) -> bool:
        """Process a single URL with delta awareness."""
        fetch_start = time.time()
        
        # Fetch with conditional headers
        content, etag, last_modified, status_code = await self.fetch_with_conditional_headers(session, url)
        
        fetch_time = time.time() - fetch_start
        self.fetch_times.append(fetch_time)
        
        if status_code == 304:
            # Not modified - skip processing
            self.stats['urls_unchanged'] += 1
            return True
        
        if not content or status_code != 200:
            self.stats['urls_error'] += 1
            return False
        
        # Check body length
        if len(content) < self.min_body_length:
            return True
        
        # Store blob
        blob_key = self.store_blob(content, etag, last_modified, status_code)
        
        # Parse content
        parse_start = time.time()
        
        # Extract title from content (simplified)
        title = f"Page: {url.split('/')[-1]}"  # Simplified title extraction
        
        # Create nodes
        nodes = self.create_nodes_from_content(content, url, title)
        
        # Compute unit hash from all node content
        all_content = "\n".join([node.content for node in nodes])
        unit_hash = self.compute_hash(all_content)
        
        # Store doc unit
        doc_key = self.store_doc_unit(url, blob_key, unit_hash)
        
        # Add events for timeline
        for node in nodes:
            self.add_event(node.id, 'parsed', {
                'url': url,
                'blob_key': blob_key,
                'doc_key': doc_key
            })
        
        parse_time = time.time() - parse_start
        self.parse_times.append(parse_time)
        
        self.stats['urls_fetched'] += 1
        return True
    
    def update_stats_file(self):
        """Update stats.json with current progress."""
        stats_file = Path("stats.json")
        
        # Load existing stats or create new
        if stats_file.exists():
            try:
                stats = json.loads(stats_file.read_text())
            except:
                stats = {"sources": {}, "updated_at": ""}
        else:
            stats = {"sources": {}, "updated_at": ""}
        
        # Calculate averages
        avg_fetch_sec = sum(self.fetch_times) / len(self.fetch_times) if self.fetch_times else 0.3
        avg_parse_sec = sum(self.parse_times) / len(self.parse_times) if self.parse_times else 0.1
        
        # Get frontier stats
        frontier_stats = self.frontier.get_source_stats(self.source_id)
        
        # Update source stats
        stats["sources"][self.source_config.get('name', self.source_id)] = {
            "urls_fetched": self.stats['urls_fetched'],
            "urls_unchanged": self.stats['urls_unchanged'],
            "urls_changed": self.stats['urls_changed'],
            "urls_error": self.stats['urls_error'],
            "urls_remaining": frontier_stats['urls_remaining'],
            "blobs_created": self.stats['blobs_created'],
            "nodes_created": self.stats['nodes_created'],
            "nodes_updated": self.stats['nodes_updated'],
            "avg_fetch_sec": round(avg_fetch_sec, 3),
            "avg_parse_sec": round(avg_parse_sec, 3),
            "concurrency": 1
        }
        
        stats["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        # Write stats
        stats_file.write_text(json.dumps(stats, indent=2))
    
    async def run(self):
        """Run the delta-aware crawler."""
        print(f"Starting delta crawler for {self.source_config.get('name', self.source_id)}")
        
        # Initialize frontier
        self.frontier.enqueue_url(self.source_url, self.source_id, 0)
        
        async with httpx.AsyncClient() as session:
            processed_count = 0
            
            while processed_count < self.max_urls_per_source:
                # Get queued URLs
                queued_urls = self.frontier.get_queued_urls(self.source_id, limit=10)
                
                if not queued_urls:
                    if self.frontier.is_source_complete(self.source_id):
                        print(f"Source {self.source_id} is complete")
                        break
                    else:
                        await asyncio.sleep(1)
                        continue
                
                # Process URLs
                for url_info in queued_urls:
                    url = url_info['url']
                    
                    # Mark as fetching
                    self.frontier.mark_url_fetching(url)
                    
                    try:
                        success = await self.process_url(session, url)
                        if success:
                            self.frontier.mark_url_done(url)
                        else:
                            self.frontier.mark_url_error(url)
                        
                        processed_count += 1
                        
                        # Update stats periodically
                        if processed_count % 10 == 0:
                            self.update_stats_file()
                        
                    except Exception as e:
                        print(f"Error processing {url}: {e}")
                        self.frontier.mark_url_error(url)
                    
                    # Politeness delay
                    await asyncio.sleep(0.5)
        
        # Final stats update
        self.update_stats_file()
        print(f"Delta crawler complete. Stats: {self.stats}")


async def run_delta_crawler(source_config: Dict[str, Any]):
    """Run delta crawler for a single source."""
    crawler = DeltaCrawler(source_config)
    await crawler.run()
