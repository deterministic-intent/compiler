#!/usr/bin/env python3
"""Full scraper runner for the dev knowledge base."""

import asyncio
import json
import logging
import sys
import os
import time
from pathlib import Path
from typing import Dict, Any, List

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from scraper.base_scraper import BaseScraper, SkipURL
from scraper.crawler import crawl_source
from db.api import list_nodes
from nlc.intent_miner import load_supported_classes_from_modules, mine_intents_from_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
PROGRESS_PATH = BASE / "state" / "scrape_progress.json"


def _write_progress(obj: Dict[str, Any]) -> None:
    try:
        PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PROGRESS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(PROGRESS_PATH)
    except Exception:
        pass


def _update_progress(patch: Dict[str, Any]) -> None:
    try:
        if PROGRESS_PATH.exists():
            obj = json.loads(PROGRESS_PATH.read_text(encoding="utf-8", errors="replace"))
        else:
            obj = {}
        if not isinstance(obj, dict):
            obj = {}
        obj.update(patch)
        _write_progress(obj)
    except Exception:
        pass


def _db_path_from_env() -> str:
    url = str(os.environ.get("DEV_DB_URL", "")).strip()
    if url.startswith("sqlite:////"):
        rest = url[len("sqlite:////") :]
        return rest if rest.startswith("/") else ("/" + rest)
    if url.startswith("sqlite:///"):
        p = url[len("sqlite:///") :]
        return str(Path(p).resolve())
    if url.startswith("sqlite://"):
        p = url[len("sqlite://") :]
        if p == "/:memory:":
            return ":memory:"
    return ""


def _min_evidence_from_policy(policy_version: str) -> int:
    try:
        from policy import load_policy
        pol = load_policy(policy_version)
        suites = pol.get("suites", {})
        cfg = suites.get("intent_mining", {}) if isinstance(suites, dict) else {}
        v = int(cfg.get("min_evidence", 1))
        return max(v, 1)
    except Exception:
        return 1


def load_registry() -> Dict[str, Any]:
    """Load the sources registry."""
    registry_path = Path("sources/registry.json")
    with open(registry_path, "r") as f:
        return json.load(f)


class RegistryScraper(BaseScraper):
    """Scraper that works with our registry format."""
    
    def __init__(
        self,
        language: str,
        source_config: dict,
        *,
        mode: str,
        max_pages: int,
        max_seconds: int,
        stop_after_no_new_intents: int,
        policy_version: str,
        max_seconds_per_page: int,
    ):
        super().__init__(language, source_config)
        self.source_url = source_config.get("url")
        self.mode = mode
        self.max_pages = max_pages
        self.max_seconds = max_seconds
        self.stop_after_no_new_intents = stop_after_no_new_intents
        self.policy_version = policy_version
        self.cutoff_reason = ""
        self.processed_count = 0
        self.inserted_pages = 0
        self.max_seconds_per_page = max_seconds_per_page
    
    async def run(self) -> None:
        """Run the scraper for this source."""
        logger.info(f"Starting scraper for {self.source_config['name']} ({self.language})")
        
        try:
            # Initialize the frontier with the base URL
            from db.frontier import frontier
            frontier.enqueue_url(self.source_url, self.source_config.get('id', self.language), 0)
            
            # Process URLs as they become available
            processed_count = 0
            max_processed = 5000  # Safety limit
            if self.mode == "discover" and self.max_pages > 0:
                max_processed = min(max_processed, self.max_pages)
            _update_progress({
                "current_source_processed": processed_count,
                "current_source_max_processed": max_processed,
                "current_source_started_at": time.time(),
            })
            
            start_t = time.monotonic()
            pages_since_new_intents = 0
            last_intent_sig = ""
            supported_classes = load_supported_classes_from_modules()
            min_evidence = _min_evidence_from_policy(self.policy_version)
            db_path = _db_path_from_env()
            while processed_count < max_processed:
                if self.mode == "discover" and self.max_seconds > 0:
                    if (time.monotonic() - start_t) >= self.max_seconds:
                        self.cutoff_reason = "max_seconds"
                        break
                # Get queued URLs from frontier
                source_id = self.source_config.get('id', self.language)
                batch_limit = 10
                if self.mode == "discover" and self.max_pages > 0:
                    remaining = max_processed - processed_count
                    batch_limit = min(batch_limit, max(1, remaining))
                if self.mode == "discover":
                    queued_urls = frontier.get_queued_urls_breadth(source_id, max_urls=batch_limit)
                else:
                    queued_urls = frontier.get_queued_urls(source_id, limit=batch_limit)
                
                if not queued_urls:
                    # Check if source is complete
                    if frontier.is_source_complete(self.source_config.get('id', self.language)):
                        logger.info(f"Source {self.source_config['name']} is complete")
                        break
                    else:
                        # Wait a bit and try again
                        await asyncio.sleep(1)
                        continue
                
                # Process each URL
                for url_info in queued_urls:
                    url = url_info['url']
                    logger.info(f"Scraping URL {processed_count + 1}: {url}")
                    
                    # Mark as fetching
                    frontier.mark_url_fetching(url)
                    
                    try:
                        # Scrape the URL (with optional per-page timeout)
                        inserted = 0
                        if self.max_seconds_per_page > 0:
                            inserted = await asyncio.wait_for(self.scrape_url(url), timeout=self.max_seconds_per_page)
                        else:
                            inserted = await self.scrape_url(url)
                        frontier.mark_url_done(url)
                        processed_count += 1
                        self.processed_count = processed_count
                        pages_inserted = 1 if inserted > 0 else 0
                        self.inserted_pages = getattr(self, "inserted_pages", 0) + pages_inserted
                    except SkipURL as e:
                        logger.info(f"SkipURL: {url} reason={e}")
                        frontier.mark_url_done(url)
                        processed_count += 1
                        self.processed_count = processed_count
                        pages_inserted = 0
                        self.inserted_pages = getattr(self, "inserted_pages", 0) + pages_inserted
                        stats = frontier.get_source_stats(self.source_config.get('id', self.language))
                        _update_progress({
                            "current_source_processed": processed_count,
                            "current_source_pages_seen": processed_count,
                            "current_source_pages_inserted": getattr(self, "inserted_pages", 0),
                            "current_source_last_update": time.time(),
                            "current_url": url,
                            "current_source_urls_remaining": stats.get("urls_remaining", 0),
                            "current_source_urls_done": stats.get("urls_done", 0),
                            "current_source_urls_error": stats.get("urls_error", 0),
                            "current_source_urls_fetching": stats.get("urls_fetching", 0),
                            "current_source_urls_total": stats.get("total_urls", 0),
                        })
                        if self.mode == "discover" and self.stop_after_no_new_intents > 0 and db_path:
                            try:
                                intents = mine_intents_from_db(
                                    Path(db_path),
                                    policy_version=self.policy_version,
                                    supported_classes=supported_classes,
                                    min_evidence=min_evidence,
                                )
                                intent_sig = json.dumps([i.get("intent_id") for i in intents], sort_keys=True)
                                if intent_sig == last_intent_sig:
                                    pages_since_new_intents += 1
                                else:
                                    pages_since_new_intents = 0
                                    last_intent_sig = intent_sig
                                if pages_since_new_intents >= self.stop_after_no_new_intents:
                                    self.cutoff_reason = "stability_stop"
                                    break
                            except Exception:
                                pass
                        stats = frontier.get_source_stats(self.source_config.get('id', self.language))
                        _update_progress({
                            "current_source_processed": processed_count,
                            "current_source_pages_seen": processed_count,
                            "current_source_pages_inserted": getattr(self, "inserted_pages", 0),
                            "current_source_last_update": time.time(),
                            "current_url": url,
                            "current_source_urls_remaining": stats.get("urls_remaining", 0),
                            "current_source_urls_done": stats.get("urls_done", 0),
                            "current_source_urls_error": stats.get("urls_error", 0),
                            "current_source_urls_fetching": stats.get("urls_fetching", 0),
                            "current_source_urls_total": stats.get("total_urls", 0),
                        })
                    except Exception as e:
                        logger.error(f"Failed to scrape {url}: {e}")
                        frontier.mark_url_error(url)
                        self.processed_count = processed_count
                        try:
                            stats = frontier.get_source_stats(self.source_config.get('id', self.language))
                            _update_progress({
                                "current_source_processed": processed_count,
                                "current_source_pages_seen": processed_count,
                                "current_source_pages_inserted": getattr(self, "inserted_pages", 0),
                                "current_source_last_update": time.time(),
                                "current_url": url,
                                "current_source_urls_remaining": stats.get("urls_remaining", 0),
                                "current_source_urls_done": stats.get("urls_done", 0),
                                "current_source_urls_error": stats.get("urls_error", 0),
                                "current_source_urls_fetching": stats.get("urls_fetching", 0),
                                "current_source_urls_total": stats.get("total_urls", 0),
                            })
                        except Exception:
                            pass
                    
                    # Small delay between requests
                    await asyncio.sleep(0.5)
                    if self.cutoff_reason:
                        break
                if self.cutoff_reason:
                    break
            if not self.cutoff_reason and processed_count >= max_processed:
                self.cutoff_reason = "max_pages"
                
        except Exception as e:
            logger.error(f"Error in {self.language} scraper: {e}")
            raise
        finally:
            await self.session.aclose()


async def run_single_scraper(
    source: Dict[str, Any],
    *,
    mode: str,
    max_pages: int,
    max_seconds: int,
    stop_after_no_new_intents: int,
    policy_version: str,
    max_seconds_per_page: int,
) -> Dict[str, Any]:
    """Run scraper for a single source."""
    try:
        language = source["language"]
        scraper = RegistryScraper(
            language,
            source,
            mode=mode,
            max_pages=max_pages,
            max_seconds=max_seconds,
            stop_after_no_new_intents=stop_after_no_new_intents,
            policy_version=policy_version,
            max_seconds_per_page=max_seconds_per_page,
        )
        await scraper.run()
        logger.info(f"✅ Successfully scraped {source['name']}")
        return {
            "success": True,
            "cutoff_reason": scraper.cutoff_reason,
            "pages_seen": scraper.processed_count,
            "pages_inserted": getattr(scraper, "inserted_pages", 0),
        }
    except Exception as e:
        logger.error(f"❌ Failed to scrape {source['name']}: {e}", exc_info=True)
        return {"success": False, "cutoff_reason": "error", "pages_seen": 0, "pages_inserted": 0}


async def run_all_scrapers(
    *,
    mode: str,
    max_pages: int,
    max_seconds: int,
    stop_after_no_new_intents: int,
    policy_version: str,
    priority_sources: List[str],
    max_seconds_per_page: int,
):
    """Run scrapers for all sources in the registry."""
    registry = load_registry()
    sources = registry.get("sources", [])
    
    logger.info(f"Starting full scraper run for {len(sources)} sources")
    # Report external snapshot target (if any) to make rescrape intent explicit.
    try:
        import os
        from nlc.external_snapshot import EXTERNAL_ROOT
        ext_id = str(os.environ.get("NLC_EXTERNAL_SNAPSHOT_ID", "")).strip()
        if ext_id:
            manifest = EXTERNAL_ROOT / ext_id / "sources.manifest.json"
            if manifest.exists():
                logger.info(f"External snapshot: {ext_id} (manifest exists; live fetch will overwrite same source_ids)")
            else:
                logger.info(f"External snapshot: {ext_id} (new snapshot)")
    except Exception:
        pass
    
    # Get initial node count
    initial_nodes = list_nodes(limit=10000)
    logger.info(f"Initial database nodes: {len(initial_nodes)}")
    
    # Track results
    successful = 0
    failed = 0
    
    def _fmt_eta(seconds: float) -> str:
        if seconds < 0:
            seconds = 0
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}h{m:02d}m{s:02d}s"
        if m:
            return f"{m}m{s:02d}s"
        return f"{s}s"

    if priority_sources:
        ps = [p.strip().lower() for p in priority_sources if p.strip()]
        if ps:
            prioritized = [s for s in sources if str(s.get("language", "")).lower() in ps]
            rest = [s for s in sources if s not in prioritized]
            sources = prioritized + rest

    start = time.monotonic()
    _write_progress({
        "started_at": time.time(),
        "total_sources": len(sources),
        "completed_sources": 0,
        "current_source_index": 0,
        "mode": mode,
    })
    per_source_times: list[float] = []
    for i, source in enumerate(sources, 1):
        src_name = source.get("name", "")
        src_lang = source.get("language", "")
        src_id = source.get("id", "")
        eta = ""
        if per_source_times:
            avg = sum(per_source_times) / len(per_source_times)
            remaining = (len(sources) - i + 1) * avg
            eta = f" ETA {_fmt_eta(remaining)}"
        else:
            eta = " ETA pending"
        logger.info(f"[{i}/{len(sources)}] {src_name} ({src_lang}) id={src_id}{eta}")
        _update_progress({
            "current_source_index": i,
            "current_source_id": src_id,
            "current_source_name": src_name,
            "current_source_language": src_lang,
            "current_source_started_at": time.time(),
        })
        
        t0 = time.monotonic()
        result = await run_single_scraper(
            source,
            mode=mode,
            max_pages=max_pages,
            max_seconds=max_seconds,
            stop_after_no_new_intents=stop_after_no_new_intents,
            policy_version=policy_version,
            max_seconds_per_page=max_seconds_per_page,
        )
        dt = time.monotonic() - t0
        per_source_times.append(dt)
        if result.get("success"):
            successful += 1
        else:
            failed += 1
        cutoff_reason = str(result.get("cutoff_reason", "")).strip() or "complete"
        _update_progress({
            "completed_sources": i,
            "last_completed_source_id": src_id,
            "last_completed_source_name": src_name,
            "last_completed_duration_s": round(dt, 3),
            f"source_summary::{src_id}": {
                "cutoff_reason": cutoff_reason,
                "duration_s": round(dt, 3),
                "pages_seen": int(result.get("pages_seen", 0) or 0),
                "pages_inserted": int(result.get("pages_inserted", 0) or 0),
                "mode": mode,
            },
        })
        avg = sum(per_source_times) / len(per_source_times)
        remaining = (len(sources) - i) * avg
        logger.info(
            f"[checkpoint] {src_name} ({src_lang}) id={src_id} "
            f"took {_fmt_eta(dt)} | updated ETA {_fmt_eta(remaining)} | cutoff={cutoff_reason}"
        )
        
        # Small delay between scrapers to be respectful
        await asyncio.sleep(2)
    
    # Final summary
    final_nodes = list_nodes(limit=10000)
    new_nodes = len(final_nodes) - len(initial_nodes)
    
    elapsed = time.monotonic() - start
    logger.info("="*60)
    logger.info("SCRAPING RUN COMPLETE")
    logger.info("="*60)
    logger.info(f"Sources processed: {len(sources)}")
    logger.info(f"Successful: {successful}")
    logger.info(f"Failed: {failed}")
    logger.info(f"New nodes added: {new_nodes}")
    logger.info(f"Total nodes in database: {len(final_nodes)}")
    logger.info(f"Elapsed: {_fmt_eta(elapsed)}")
    _update_progress({
        "finished_at": time.time(),
        "status": "DONE",
    })
    
    return successful, failed, new_nodes


async def run_language_scrapers(
    languages: List[str],
    *,
    mode: str,
    max_pages: int,
    max_seconds: int,
    stop_after_no_new_intents: int,
    policy_version: str,
    max_seconds_per_page: int,
):
    """Run scrapers for specific languages."""
    registry = load_registry()
    sources = registry.get("sources", [])
    
    # Filter sources by language
    filtered_sources = [s for s in sources if s["language"] in languages]
    
    logger.info(f"Running scrapers for languages: {languages}")
    logger.info(f"Found {len(filtered_sources)} sources")
    
    successful = 0
    failed = 0
    
    for source in filtered_sources:
        result = await run_single_scraper(
            source,
            mode=mode,
            max_pages=max_pages,
            max_seconds=max_seconds,
            stop_after_no_new_intents=stop_after_no_new_intents,
            policy_version=policy_version,
            max_seconds_per_page=max_seconds_per_page,
        )
        if result.get("success"):
            successful += 1
        else:
            failed += 1
        
        await asyncio.sleep(2)
    
    logger.info(f"Language scraping complete: {successful} successful, {failed} failed")
    return successful, failed


def main():
    """Main entry point."""
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["discover", "full"], default="full")
    ap.add_argument("--max-pages-per-source", type=int, default=0)
    ap.add_argument("--max-seconds-per-source", type=int, default=0)
    ap.add_argument("--max-seconds-per-page", type=int, default=0)
    ap.add_argument("--stop-after-no-new-intents", type=int, default=0)
    ap.add_argument("--priority-sources", default="")
    ap.add_argument("--policy", default="v1")
    ap.add_argument("languages", nargs="*")
    args = ap.parse_args()

    mode = str(args.mode).strip()
    max_pages = int(args.max_pages_per_source or 0)
    max_seconds = int(args.max_seconds_per_source or 0)
    max_seconds_per_page = int(args.max_seconds_per_page or 0)
    stop_after = int(args.stop_after_no_new_intents or 0)
    if mode == "discover":
        if max_pages <= 0:
            max_pages = 200
        if max_seconds <= 0:
            max_seconds = 60
        if max_seconds_per_page <= 0:
            max_seconds_per_page = 10
        if stop_after <= 0:
            stop_after = 50
    policy_version = str(args.policy).strip() or "v1"
    priority_sources = [s.strip() for s in str(args.priority_sources or "").split(",") if s.strip()]

    if args.languages:
        languages = args.languages
        logger.info(f"Running scrapers for: {languages}")
        asyncio.run(
            run_language_scrapers(
                languages,
                mode=mode,
                max_pages=max_pages,
                max_seconds=max_seconds,
                stop_after_no_new_intents=stop_after,
                policy_version=policy_version,
                max_seconds_per_page=max_seconds_per_page,
            )
        )
    else:
        logger.info("Running all scrapers")
        asyncio.run(
            run_all_scrapers(
                mode=mode,
                max_pages=max_pages,
                max_seconds=max_seconds,
                stop_after_no_new_intents=stop_after,
                policy_version=policy_version,
                priority_sources=priority_sources,
                max_seconds_per_page=max_seconds_per_page,
            )
        )


if __name__ == "__main__":
    main()
