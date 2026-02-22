#!/usr/bin/env python3
"""Web crawler for scraping documentation sites."""

import asyncio
import re
import logging
import hashlib
import json
import time
from typing import Set, List, Dict, Any
from urllib.parse import urljoin, urlparse
import httpx
from bs4 import BeautifulSoup
from pathlib import Path
from db.frontier import frontier

logger = logging.getLogger(__name__)


class DocumentationCrawler:
    """Crawler that follows links within documentation sites."""
    
    def __init__(self, source_config: Dict[str, Any]):
        self.source_config = source_config
        self.crawl_config = source_config.get("crawl", {})
        self.base_url = source_config["url"]
        self.allowed_patterns = self.crawl_config.get("allowed", [])
        self.deny_patterns = self.crawl_config.get("deny", [])
        
        # Apply per-source depth overrides
        source_id = source_config.get("id", "")
        if source_id in ["html_spec", "mdn_html", "java_jls", "ecmascript_spec"]:
            self.max_depth = self.crawl_config.get("depth", 8)  # Big, cross-linked specs
        elif source_id in ["typescript_docs", "rust_reference"]:
            self.max_depth = self.crawl_config.get("depth", 4)  # SPA/handbooks
        else:
            self.max_depth = self.crawl_config.get("depth", 6)  # Default depth
        
        # Hard stop conditions
        self.max_urls_per_source = 5000
        self.min_body_length = 800
        
        # Performance tracking
        self.fetch_times: List[float] = []
        self.parse_times: List[float] = []
        self.start_time = time.time()
        self.source_name = source_config.get("name", "unknown")
        
        # Initialize frontier for this source
        self.source_id = source_config.get("id", source_config.get("name", "unknown"))
        frontier.enqueue_url(self.base_url, self.source_id, 0)
        
    def should_crawl_url(self, url: str) -> bool:
        """Check if URL should be crawled based on patterns."""
        # Check deny patterns first
        for pattern in self.deny_patterns:
            if re.search(pattern, url):
                return False
        
        # Check allowed patterns
        if not self.allowed_patterns:
            return True  # If no allowed patterns, crawl everything not denied
        
        for pattern in self.allowed_patterns:
            if re.search(pattern, url):
                return True
        
        return False
    
    def extract_links(self, html: str, base_url: str) -> List[str]:
        """Extract all links from HTML content."""
        soup = BeautifulSoup(html, "html.parser")
        links = []
        
        # Extract regular links
        for link in soup.find_all("a", href=True):
            href = link["href"]
            absolute_url = urljoin(base_url, href)
            
            # Only include HTTP/HTTPS links
            if absolute_url.startswith(("http://", "https://")):
                links.append(absolute_url)
        
        # For single-page specs, treat h2/h3 anchors as virtual children
        source_id = self.source_config.get("id", "")
        if source_id in ["html_spec"]:  # WHATWG HTML Living Standard
            for heading in soup.find_all(["h2", "h3"]):
                if heading.get("id"):
                    anchor_url = f"{base_url}#{heading['id']}"
                    links.append(anchor_url)
        
        return links
    
    def get_content_hash(self, html: str) -> str:
        """Generate content hash for deduplication."""
        # Remove dynamic content that changes between requests
        soup = BeautifulSoup(html, "html.parser")
        
        # Remove script and style tags
        for tag in soup(["script", "style"]):
            tag.decompose()
        
        # Get text content
        text = soup.get_text()
        return hashlib.md5(text.encode()).hexdigest()
    
    def get_body_length(self, html: str) -> int:
        """Get the length of the main content body."""
        soup = BeautifulSoup(html, "html.parser")
        
        # Remove navigation, headers, footers
        for tag in soup(["nav", "header", "footer", "aside", "script", "style"]):
            tag.decompose()
        
        # Get text content
        text = soup.get_text()
        return len(text.strip())
    
    async def crawl_site(self, session: httpx.AsyncClient) -> List[str]:
        """Crawl the site using frontier-based approach."""
        logger.info(f"Starting frontier-based crawl of {self.base_url} (max depth: {self.max_depth}, max URLs: {self.max_urls_per_source})")
        
        crawled_urls = []
        cap_hit = False
        
        while True:
            # Get queued URLs from frontier
            queued_urls = frontier.get_queued_urls(self.source_id, limit=10)
            
            if not queued_urls:
                # Check if source is complete
                if frontier.is_source_complete(self.source_id, grace_period_seconds=60):
                    logger.info(f"Source {self.source_id} is safely complete")
                    break
                else:
                    logger.info(f"Waiting for source {self.source_id} to complete (grace period)")
                    await asyncio.sleep(10)
                    continue
            
            # Process queued URLs
            for url_info in queued_urls:
                url = url_info["url"]
                depth = url_info["depth"]
                
                if depth > self.max_depth:
                    frontier.mark_url_done(url)
                    continue
                
                if not self.should_crawl_url(url):
                    frontier.mark_url_done(url)
                    continue
                
                # Check if we've hit the cap
                stats = frontier.get_source_stats(self.source_id)
                if stats["total_urls"] >= self.max_urls_per_source:
                    cap_hit = True
                    logger.warning(f"Cap hit: reached {self.max_urls_per_source} URLs for {self.source_config['name']}")
                    break
                
                try:
                    # Mark as fetching
                    frontier.mark_url_fetching(url)
                    
                    fetch_start = time.time()
                    logger.info(f"Crawling {url} (depth {depth}, total URLs: {stats['total_urls']})")
                    response = await session.get(url, timeout=30.0)
                    fetch_time = time.time() - fetch_start
                    self.fetch_times.append(fetch_time)
                    
                    if response.status_code == 200:
                        # Check body length
                        parse_start = time.time()
                        body_length = self.get_body_length(response.text)
                        if body_length < self.min_body_length:
                            logger.debug(f"Skipping {url} - body too short ({body_length} chars)")
                            frontier.mark_url_done(url)
                            continue
                        
                        # Check for duplicate content
                        content_hash = self.get_content_hash(response.text)
                        
                        # Mark as done and add to crawled URLs
                        frontier.mark_url_done(url)
                        crawled_urls.append(url)
                        
                        # Extract links for next level if not at max depth
                        if depth < self.max_depth:
                            links = self.extract_links(response.text, url)
                            for link in links:
                                frontier.enqueue_url(link, self.source_id, depth + 1)
                        
                        parse_time = time.time() - parse_start
                        self.parse_times.append(parse_time)
                    else:
                        frontier.mark_url_error(url)
                    
                    # Politeness: 1-3 rps/site
                    await asyncio.sleep(0.5)
                    
                except httpx.HTTPStatusError as e:
                    if e.response.status_code in [429, 500, 502, 503, 504]:
                        logger.warning(f"Server error {e.response.status_code} for {url}, backing off...")
                        await asyncio.sleep(5)  # Exponential backoff
                    else:
                        logger.warning(f"HTTP error {e.response.status_code} for {url}")
                    frontier.mark_url_error(url)
                except Exception as e:
                    logger.warning(f"Failed to crawl {url}: {e}")
                    frontier.mark_url_error(url)
            
            if cap_hit:
                break
        
        # Get final stats
        final_stats = frontier.get_source_stats(self.source_id)
        logger.info(f"Crawl complete. Found {len(crawled_urls)} URLs to scrape (cap_hit: {cap_hit})")
        logger.info(f"Final stats: {final_stats['urls_done']} done, {final_stats['urls_error']} errors, {final_stats['urls_remaining']} remaining")
        
        # Update stats
        self.update_stats(len(crawled_urls), final_stats['urls_remaining'])
        
        return crawled_urls
    
    def update_stats(self, urls_fetched: int, urls_remaining: int):
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
        
        # Update source stats
        stats["sources"][self.source_name] = {
            "urls_fetched": urls_fetched,
            "urls_remaining": urls_remaining,
            "avg_fetch_sec": round(avg_fetch_sec, 3),
            "avg_parse_sec": round(avg_parse_sec, 3),
            "concurrency": 1,  # Single-threaded for now
            "cap_hit": self.url_count >= self.max_urls_per_source
        }
        
        stats["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        # Write stats
        stats_file.write_text(json.dumps(stats, indent=2))


async def crawl_source(source_config: Dict[str, Any]) -> List[str]:
    """Crawl a single source and return URLs to scrape."""
    async with httpx.AsyncClient() as session:
        crawler = DocumentationCrawler(source_config)
        return await crawler.crawl_site(session)
