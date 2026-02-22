"""Swift-specific scraper implementation."""

from typing import Dict, Any, List
from ..base_scraper import BaseScraper


class SwiftScraper(BaseScraper):
    """Swift-specific scraper with language-specific parsing rules."""
    
    def __init__(self, language: str, source_config: Dict[str, Any]):
        super().__init__(language, source_config)
        self.language = "swift"
    
    def parse_swift_specific_content(self, parsed_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse Swift-specific content patterns."""
        chunks = self.normalize_content(parsed_data)
        
        for chunk in chunks:
            chunk["tags"].extend([
                "swift", "ios", "macos", "apple", "static-typing"
            ])
            
            content = chunk.get("content", "")
            if "func " in content:
                chunk["tags"].append("function-declaration")
            if "class " in content:
                chunk["tags"].append("class-declaration")
            if "struct " in content:
                chunk["tags"].append("struct-declaration")
            if "enum " in content:
                chunk["tags"].append("enum-declaration")
            if "protocol " in content:
                chunk["tags"].append("protocol-declaration")
            if "var " in content or "let " in content:
                chunk["tags"].append("variable-declaration")
            if "guard " in content:
                chunk["tags"].append("guard-statement")
            if "defer " in content:
                chunk["tags"].append("defer-statement")
            if "weak " in content or "unowned " in content:
                chunk["tags"].append("memory-management")
        
        return chunks
    
    async def scrape_url(self, url: str) -> None:
        """Override to use Swift-specific parsing."""
        html = await self.fetch_page(url)
        if not html:
            return
        
        parsed_data = self.parse_html(html, url)
        chunks = self.parse_swift_specific_content(parsed_data)
        self.insert_knowledge(chunks)
