"""Go-specific scraper implementation."""

from typing import Dict, Any, List
from ..base_scraper import BaseScraper


class GoScraper(BaseScraper):
    """Go-specific scraper with language-specific parsing rules."""
    
    def __init__(self, language: str, source_config: Dict[str, Any]):
        super().__init__(language, source_config)
        self.language = "go"
    
    def parse_go_specific_content(self, parsed_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse Go-specific content patterns."""
        chunks = self.normalize_content(parsed_data)
        
        for chunk in chunks:
            chunk["tags"].extend([
                "go", "golang", "static-typing", "compiled"
            ])
            
            content = chunk.get("content", "")
            if "func " in content:
                chunk["tags"].append("function-declaration")
            if "type " in content and "struct" in content:
                chunk["tags"].append("struct-declaration")
            if "type " in content and "interface" in content:
                chunk["tags"].append("interface-declaration")
            if "go " in content:
                chunk["tags"].append("goroutine")
            if "chan " in content:
                chunk["tags"].append("channel")
            if "defer " in content:
                chunk["tags"].append("defer-statement")
            if "package " in content:
                chunk["tags"].append("package-declaration")
            if "import " in content:
                chunk["tags"].append("import-statement")
        
        return chunks
    
    async def scrape_url(self, url: str) -> None:
        """Override to use Go-specific parsing."""
        html = await self.fetch_page(url)
        if not html:
            return
        
        parsed_data = self.parse_html(html, url)
        chunks = self.parse_go_specific_content(parsed_data)
        self.insert_knowledge(chunks)
