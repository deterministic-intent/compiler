#!/usr/bin/env python3
"""Run all scrapers except HTML sources."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, Any, List

from scraper.run_scrapers import run_single_scraper
from db.api import list_nodes

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def load_registry() -> Dict[str, Any]:
    """Load the sources registry."""
    registry_path = Path("sources/registry.json")
    with open(registry_path, "r") as f:
        return json.load(f)

async def run_non_html_scrapers():
    """Run scrapers for all sources except HTML."""
    registry = load_registry()
    sources = registry.get("sources", [])
    
    # Filter out HTML sources
    non_html_sources = [s for s in sources if s.get("language") != "html"]
    
    logger.info(f"Starting non-HTML scraper run for {len(non_html_sources)} sources")
    
    # Get initial node count
    initial_nodes = list_nodes()
    logger.info(f"Initial database nodes: {len(initial_nodes)}")
    
    # Track results
    successful = 0
    failed = 0
    
    for i, source in enumerate(non_html_sources, 1):
        logger.info(f"Processing {i}/{len(non_html_sources)}: {source['name']} ({source['language']})")
        
        success = await run_single_scraper(source)
        if success:
            successful += 1
        else:
            failed += 1
        
        # Small delay between scrapers to be respectful
        await asyncio.sleep(2)
    
    # Final summary
    final_nodes = list_nodes()
    new_nodes = len(final_nodes) - len(initial_nodes)
    
    logger.info("="*60)
    logger.info("NON-HTML SCRAPING RUN COMPLETE")
    logger.info("="*60)
    logger.info(f"Sources processed: {len(non_html_sources)}")
    logger.info(f"Successful: {successful}")
    logger.info(f"Failed: {failed}")
    logger.info(f"New nodes added: {new_nodes}")
    logger.info(f"Total nodes: {len(final_nodes)}")

if __name__ == "__main__":
    asyncio.run(run_non_html_scrapers())
