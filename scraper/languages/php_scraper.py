"""PHP-specific scraper implementation."""

from typing import Dict, Any, List
from ..base_scraper import BaseScraper


class PhpScraper(BaseScraper):
    """PHP-specific scraper with language-specific parsing rules."""
    
    def __init__(self, language: str, source_config: Dict[str, Any]):
        super().__init__(language, source_config)
        self.language = "php"
    
    def parse_php_specific_content(self, parsed_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse PHP-specific content patterns."""
        chunks = self.normalize_content(parsed_data)
        
        for chunk in chunks:
            chunk["tags"].extend([
                "php", "web-development", "server-side", "dynamic-typing"
            ])
            
            content = chunk.get("content", "")
            if "<?php" in content:
                chunk["tags"].append("php-tags")
            if "function " in content:
                chunk["tags"].append("function-declaration")
            if "class " in content:
                chunk["tags"].append("class-declaration")
            if "namespace " in content:
                chunk["tags"].append("namespace")
            if "use " in content:
                chunk["tags"].append("use-statement")
            if "$" in content:
                chunk["tags"].append("variable")
            if "echo " in content or "print " in content:
                chunk["tags"].append("output")
            if "require " in content or "include " in content:
                chunk["tags"].append("file-inclusion")
        
        return chunks
    
    async def scrape_url(self, url: str) -> None:
        """Override to use PHP-specific parsing."""
        html = await self.fetch_page(url)
        if not html:
            return
        
        parsed_data = self.parse_html(html, url)
        chunks = self.parse_php_specific_content(parsed_data)
        self.insert_knowledge(chunks)
