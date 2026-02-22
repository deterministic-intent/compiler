"""Base scraper class and common functionality."""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify

from .parser_utils import extract_code_blocks, detect_toc
from .normalizer import normalize_content
from .inserter import insert_nodes
from .dedupe import check_duplicates

logger = logging.getLogger(__name__)


class SkipURL(RuntimeError):
    """Raised to skip a URL before parse (deterministic)."""
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


_BINARY_EXTS = {
    ".pdf", ".zip", ".tar", ".gz", ".xz", ".7z", ".rar",
    ".mp4", ".webm", ".mov", ".avi", ".mp3", ".wav", ".ogg",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".exe", ".bin", ".dmg", ".iso",
}
_MEDIA_HOSTS = {"youtube.com", "vimeo.com", "audio-video.gnu.org"}
_UNSUPPORTED_CT = {
    "application/pdf",
    "application/octet-stream",
}


class BaseScraper:
    """Base class for all scrapers."""
    
    def __init__(self, language: str, source_config: Dict[str, Any]):
        self.language = language
        self.source_config = source_config
        self.allowed_roots = self._derive_allowed_roots(source_config)
        self.resume_source_ids = self._load_resume_source_ids()
        self.session = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "DevKnowledgeBase/1.0 (Educational Project)"
            }
        )
        self.temp_dir = Path(f"scraper/temp/{language}")
        self.temp_dir.mkdir(parents=True, exist_ok=True)
    def _seed_urls(self, source_config: Dict[str, Any]) -> list[str]:
        urls: list[str] = []
        seed = str(source_config.get("url", "")).strip()
        if seed:
            urls.append(seed)
        for doc in source_config.get("official_docs", []) or []:
            u = str(doc.get("url", "")).strip()
            if u:
                urls.append(u)
        for fw in source_config.get("frameworks", []) or []:
            u = str(fw.get("url", "")).strip()
            if u:
                urls.append(u)
        return urls

    def _derive_allowed_roots(self, source_config: Dict[str, Any]) -> list[str]:
        seeds = self._seed_urls(source_config)
        by_host: dict[tuple[str, str], list[str]] = {}
        for u in seeds:
            pu = urlparse(u)
            if not pu.scheme or not pu.netloc:
                continue
            by_host.setdefault((pu.scheme, pu.netloc), []).append(pu.path or "/")
        roots: list[str] = []
        for (scheme, netloc), paths in sorted(by_host.items()):
            parts = [p.strip("/") for p in paths if p is not None]
            if not parts:
                prefix = ""
            else:
                split = [p.split("/") for p in parts]
                prefix_parts = split[0]
                for s in split[1:]:
                    i = 0
                    while i < min(len(prefix_parts), len(s)) and prefix_parts[i] == s[i]:
                        i += 1
                    prefix_parts = prefix_parts[:i]
                prefix = "/".join([p for p in prefix_parts if p])
            root = f"{scheme}://{netloc}/" + (prefix + "/" if prefix else "")
            roots.append(root)
        return roots

    def _load_resume_source_ids(self) -> set[str]:
        """
        Load URLs that are already in the database (for resume mode).
        
        Resume should check the DB, not the external snapshot, because:
        - External snapshot = what was fetched (may not be in DB)
        - DB = what was actually inserted (ground truth)
        """
        import os
        if str(os.environ.get("NLC_SCRAPE_RESUME", "")).strip().lower() not in ("1", "true", "yes"):
            return set()
        
        # Check DB for existing source_urls (ground truth)
        try:
            from db.engine import get_engine
            from sqlalchemy import text
            engine = get_engine()
            with engine.connect() as conn:
                result = conn.execute(text("SELECT DISTINCT source_url FROM nodes WHERE source_url IS NOT NULL"))
                urls = {str(row[0]).strip() for row in result if row[0]}
                return urls
        except Exception:
            # Fallback: if DB check fails, return empty (don't skip anything)
            return set()

    def _is_in_scope(self, url: str) -> bool:
        if not self.allowed_roots:
            return True
        u = str(url or "").strip()
        for root in self.allowed_roots:
            if not root:
                continue
            root_no_slash = root.rstrip("/")
            if u == root_no_slash or u.startswith(root):
                return True
        return False

    def _skip_reason_for_url(self, url: str) -> str | None:
        u = str(url or "").strip()
        pu = urlparse(u)
        host = (pu.netloc or "").lower()
        for h in _MEDIA_HOSTS:
            if host == h or host.endswith("." + h):
                return "binary_or_media"
        path = (pu.path or "").lower()
        for ext in _BINARY_EXTS:
            if path.endswith(ext):
                return "binary_or_media"
        if not self._is_in_scope(u):
            return "out_of_scope"
        return None

    def _should_resume_skip(self, url: str) -> bool:
        return bool(self.resume_source_ids) and str(url or "").strip() in self.resume_source_ids

    async def fetch_page(self, url: str) -> Optional[str]:
        """Fetch a web page with rate limiting and retry logic."""
        try:
            # Pre-fetch URL admission gate
            reason = self._skip_reason_for_url(url)
            if reason:
                raise SkipURL(reason)

            # Resume mode: skip re-parse for completed URLs
            if self._should_resume_skip(url):
                raise SkipURL("resume_cached")

            # Rate limiting
            await asyncio.sleep(1.0)

            # Step 9: Replay mode wiring (no network).
            # In replay, force read from snapshots/external/<snapshot_id>/sources/ using manifest mapping.
            import os
            from dcs_core.repro_env import is_repro_mode
            if is_repro_mode() or \
               str(os.environ.get("NLC_EXTERNAL_REPLAY", "")).strip().lower() in ("1", "true", "yes"):
                snap_id = str(os.environ.get("NLC_EXTERNAL_SNAPSHOT_ID", "")).strip()
                if not snap_id:
                    raise RuntimeError("external replay enabled but NLC_EXTERNAL_SNAPSHOT_ID is missing")
                from nlc.external_snapshot import EXTERNAL_ROOT
                snap_dir = EXTERNAL_ROOT / snap_id
                manifest = snap_dir / "sources.manifest.json"
                if not manifest.exists():
                    raise RuntimeError(f"external replay missing sources.manifest.json for snapshot {snap_id}")
                obj = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
                entries = obj.get("entries", []) if isinstance(obj, dict) else []
                found = None
                for e in entries:
                    if isinstance(e, dict) and e.get("source_id") == url:
                        found = e
                        break
                if not found:
                    raise RuntimeError(f"external replay missing source_id entry: {url}")
                fn = str(found.get("filename", "")).strip()
                if not fn:
                    raise RuntimeError(f"external replay manifest entry missing filename for source_id: {url}")
                p = snap_dir / fn
                if not p.exists():
                    raise RuntimeError(f"external replay source file missing: {fn} for source_id: {url}")
                raw = p.read_bytes()
                text = raw.decode("utf-8", errors="replace")
                return text

            net_log = str(os.environ.get("NLC_NET_LOG", "")).strip()
            if net_log:
                try:
                    with open(net_log, "a", encoding="utf-8") as f:
                        f.write(f"NETWORK_CALL {url}\n")
                except Exception:
                    pass
            timeout = httpx.Timeout(15.0)
            async with self.session.stream("GET", url, timeout=timeout) as response:
                response.raise_for_status()
                ctype = str(response.headers.get("content-type", "")).lower()
                # Content-type gate: canonical reasons
                if ctype.startswith("video/") or ctype.startswith("audio/"):
                    raise SkipURL("media")
                if ctype.startswith("image/"):
                    raise SkipURL("unsupported_content_type")  # Images are also unsupported
                if ctype == "application/pdf":
                    raise SkipURL("pdf")
                if any(ctype.startswith(ct) or ctype == ct for ct in _UNSUPPORTED_CT):
                    if ctype == "application/pdf":
                        raise SkipURL("pdf")
                    raise SkipURL("unsupported_content_type")
                body = await response.aread()
                text = body.decode("utf-8", errors="replace")

            # Step 9: Snapshot capture (raw bytes) after fetch, before parsing (no behavior change unless enabled).
            snap_id = str(os.environ.get("NLC_EXTERNAL_SNAPSHOT_ID", "")).strip()
            if snap_id:
                try:
                    from datetime import datetime, timezone
                    def now_utc() -> str:
                        return datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"
                    from nlc.external_snapshot import write_external_source, try_load_toolchain_pins
                    policy_version = str(os.environ.get("NLC_POLICY_VERSION", "v1")).strip() or "v1"
                    pins = try_load_toolchain_pins()
                    write_external_source(
                        snapshot_id=snap_id,
                        policy_version=policy_version,
                        toolchain_pins=pins,
                        source_id=url,
                        content_type=str(response.headers.get("content-type", "")).strip(),
                        fetch_timestamp=now_utc(),
                        raw_bytes=body,
                    )
                except Exception:
                    # Snapshotting must not break scraper behavior.
                    pass
            
            # Save to temp directory for debugging
            filename = urlparse(url).path.replace("/", "_") or "index"
            temp_file = self.temp_dir / f"{filename}.html"
            temp_file.write_text(text)
            
            return text
        except SkipURL:
            raise
        except Exception as e:
            logger.error(f"Failed to fetch {url}: {e}")
            return None
    
    def parse_html(self, html: str, url: str) -> Dict[str, Any]:
        """Parse HTML content and extract structured data."""
        soup = BeautifulSoup(html, "html.parser")
        
        # Extract basic metadata
        title = soup.find("title")
        title_text = title.get_text().strip() if title else ""
        
        # Convert to markdown with better HTML handling
        markdown_content = markdownify(
            str(soup), 
            heading_style="ATX",
            strip=['script', 'style', 'nav', 'footer', 'header']  # Remove unwanted elements
        )
        
        # Extract code blocks
        code_blocks = extract_code_blocks(soup)
        
        # Detect table of contents
        toc = detect_toc(soup)
        
        return {
            "title": title_text,
            "content": markdown_content,
            "code_blocks": code_blocks,
            "toc": toc,
            "url": url
        }
    
    def normalize_content(self, parsed_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Normalize parsed content into atomic knowledge chunks."""
        return normalize_content(parsed_data, self.language)
    
    def insert_knowledge(self, chunks: List[Dict[str, Any]]) -> int:
        """Insert knowledge chunks into the database."""
        # Check for duplicates
        unique_chunks = check_duplicates(chunks)
        
        # Insert into database
        inserted = insert_nodes(unique_chunks)
        
        logger.info(f"Inserted {len(unique_chunks)} knowledge chunks for {self.language}")
        return inserted
    
    async def scrape_url(self, url: str) -> int:
        """Scrape a single URL and process its content."""
        html = await self.fetch_page(url)
        if not html:
            return 0
        
        loop = asyncio.get_running_loop()
        parsed_data = await asyncio.wait_for(
            loop.run_in_executor(None, self.parse_html, html, url),
            timeout=10.0,
        )
        chunks = self.normalize_content(parsed_data)
        inserted = self.insert_knowledge(chunks)
        
        # Discover new links and add them to frontier
        try:
            from scraper.crawler import DocumentationCrawler
            from db.frontier import frontier
            
            # Create a temporary crawler to extract links
            temp_crawler = DocumentationCrawler(self.source_config)
            links = temp_crawler.extract_links(html, url)
            
            # Add new links to frontier
            if getattr(self, "mode", "") == "discover" and "html.spec.whatwg.org" in (urlparse(url).netloc or ""):
                # Do not recurse deep sections in discover mode for monolithic spec roots.
                return inserted
            current_depth = 0  # We'll need to track depth properly
            for link in links:
                frontier.enqueue_url(link, self.source_config.get('id', self.language), current_depth + 1)
                
        except Exception as e:
            logger.debug(f"Failed to extract links from {url}: {e}")
        return inserted
    
    async def scrape_official_docs(self) -> None:
        """Scrape official documentation."""
        for doc in self.source_config.get("official_docs", []):
            url = doc["url"]
            logger.info(f"Scraping official docs: {url}")
            await self.scrape_url(url)
    
    async def scrape_frameworks(self) -> None:
        """Scrape framework documentation."""
        for framework in self.source_config.get("frameworks", []):
            url = framework["url"]
            logger.info(f"Scraping framework {framework['name']}: {url}")
            await self.scrape_url(url)
    
    async def run(self) -> None:
        """Run the scraper for this language."""
        logger.info(f"Starting scraper for {self.language}")
        
        try:
            # Check if we have a direct URL in the source config
            if "url" in self.source_config:
                url = self.source_config["url"]
                logger.info(f"Scraping source URL: {url}")
                await self.scrape_url(url)
            else:
                # Fall back to old format
                await self.scrape_official_docs()
                await self.scrape_frameworks()
            
        except Exception as e:
            logger.error(f"Error in {self.language} scraper: {e}")
            raise
        finally:
            await self.session.aclose()
    
    def __del__(self):
        """Cleanup when scraper is destroyed (best-effort, synchronous only)."""
        # Do not use async operations in __del__ - there may be no event loop.
        # The session should be closed explicitly via aclose() or async context manager.
        pass
    
    async def aclose(self):
        """Explicitly close the HTTP session."""
        if hasattr(self, "session"):
            await self.session.aclose()
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.aclose()
