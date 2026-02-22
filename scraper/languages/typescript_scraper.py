"""TypeScript-specific scraper implementation."""

from typing import Dict, Any, List
from ..base_scraper import BaseScraper


class TypeScriptScraper(BaseScraper):
    """TypeScript-specific scraper with language-specific parsing rules."""
    
    def __init__(self, language: str, source_config: Dict[str, Any]):
        super().__init__(language, source_config)
        self.language = "typescript"
    
    def parse_typescript_specific_content(self, parsed_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse TypeScript-specific content patterns."""
        chunks = self.normalize_content(parsed_data)
        
        for chunk in chunks:
            chunk["tags"].extend([
                "typescript", "ts", "static-typing", "superset"
            ])
            
            content = chunk.get("content", "")
            if "interface " in content:
                chunk["tags"].append("interface-declaration")
            if "type " in content and "=" in content:
                chunk["tags"].append("type-alias")
            if "enum " in content:
                chunk["tags"].append("enum-declaration")
            if ": " in content and ("string" in content or "number" in content or "boolean" in content):
                chunk["tags"].append("type-annotation")
            if "<" in content and ">" in content:
                chunk["tags"].append("generic")
            if "extends " in content:
                chunk["tags"].append("inheritance")
            if "implements " in content:
                chunk["tags"].append("interface-implementation")
        
        return chunks
    
    async def scrape_url(self, url: str) -> None:
        """Override to use TypeScript-specific parsing."""
        html = await self.fetch_page(url)
        if not html:
            return
        
        parsed_data = self.parse_html(html, url)
        chunks = self.parse_typescript_specific_content(parsed_data)
        self.insert_knowledge(chunks)
