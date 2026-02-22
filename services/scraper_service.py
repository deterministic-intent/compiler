#!/usr/bin/env python3
"""
Scraper Service - API endpoint for running knowledge base scrapers
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.run_scrapers import run_all_scrapers, run_language_scrapers, run_single_scraper, load_registry

app = FastAPI(title="Scraper Service", version="1.0.0")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ScrapeRequest(BaseModel):
    languages: Optional[List[str]] = None
    source_id: Optional[str] = None


class ScrapeStatus:
    """Track scraping status."""
    _status = {}
    _results = {}
    
    @classmethod
    def set_running(cls, task_id: str):
        cls._status[task_id] = "running"
    
    @classmethod
    def set_complete(cls, task_id: str, result: Dict[str, Any]):
        cls._status[task_id] = "complete"
        cls._results[task_id] = result
    
    @classmethod
    def set_error(cls, task_id: str, error: str):
        cls._status[task_id] = "error"
        cls._results[task_id] = {"error": error}
    
    @classmethod
    def get_status(cls, task_id: str) -> Dict[str, Any]:
        status = cls._status.get(task_id, "unknown")
        result = cls._results.get(task_id, {})
        return {"status": status, "result": result}


async def run_scraping_task(task_id: str, languages: Optional[List[str]] = None, source_id: Optional[str] = None):
    """Background task to run scrapers."""
    try:
        ScrapeStatus.set_running(task_id)
        logger.info(f"Starting scraping task {task_id}")
        
        if source_id:
            registry = load_registry()
            source = None
            for s in registry.get('sources', []):
                if s.get('id') == source_id:
                    source = s
                    break
            
            if not source:
                raise ValueError(f"Source {source_id} not found")
            
            success = await run_single_scraper(source)
            result = {"success": success, "source_id": source_id}
        elif languages:
            result = await run_language_scrapers(languages)
        else:
            result = await run_all_scrapers()
        
        ScrapeStatus.set_complete(task_id, result)
        logger.info(f"Completed scraping task {task_id}: {result}")
    except Exception as e:
        logger.error(f"Error in scraping task {task_id}: {e}")
        ScrapeStatus.set_error(task_id, str(e))


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "scraper"}


@app.post("/scrape/run")
async def scrape_run(request: ScrapeRequest, background_tasks: BackgroundTasks):
    """Trigger scraping (runs in background)."""
    import uuid
    task_id = str(uuid.uuid4())
    
    background_tasks.add_task(
        run_scraping_task,
        task_id=task_id,
        languages=request.languages,
        source_id=request.source_id
    )
    
    return {
        "task_id": task_id,
        "status": "started",
        "languages": request.languages,
        "source_id": request.source_id
    }


@app.get("/scrape/status/{task_id}")
async def scrape_status(task_id: str):
    """Get scraping task status."""
    status = ScrapeStatus.get_status(task_id)
    if status["status"] == "unknown":
        raise HTTPException(status_code=404, detail="Task not found")
    return status


@app.get("/scrape/sources")
async def list_sources():
    """List available sources."""
    registry = load_registry()
    sources = []
    for source in registry.get('sources', []):
        sources.append({
            "id": source.get('id'),
            "name": source.get('name'),
            "language": source.get('language'),
            "url": source.get('url')
        })
    return {"sources": sources}


@app.get("/scrape/languages")
async def list_languages():
    """List available languages."""
    registry = load_registry()
    languages = set()
    for source in registry.get('sources', []):
        languages.add(source.get('language'))
    return {"languages": sorted(list(languages))}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8702)
