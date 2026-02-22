"""C-specific scraper implementation."""

from typing import Dict, Any, List
from ..base_scraper import BaseScraper


class CScraper(BaseScraper):
    """C-specific scraper with language-specific parsing rules."""
    
    def __init__(self, language: str, source_config: Dict[str, Any]):
        super().__init__(language, source_config)
        self.language = "c"
    
    def parse_c_specific_content(self, parsed_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse C-specific content patterns."""
        chunks = self.normalize_content(parsed_data)
        
        for chunk in chunks:
            chunk["tags"].extend([
                "c", "procedural", "low-level", "manual-memory-management"
            ])
            
            content = chunk.get("content", "")
            if "#include" in content:
                chunk["tags"].append("preprocessor-directive")
            if "int main" in content:
                chunk["tags"].append("main-function")
            if "struct " in content:
                chunk["tags"].append("struct-declaration")
            if "typedef " in content:
                chunk["tags"].append("type-definition")
            if "malloc(" in content or "free(" in content:
                chunk["tags"].append("memory-management")
            if "*" in content and "int" in content:
                chunk["tags"].append("pointer")
            if "->" in content:
                chunk["tags"].append("pointer-member-access")
        
        return chunks
    
    async def scrape_url(self, url: str) -> None:
        """Override to use C-specific parsing."""
        html = await self.fetch_page(url)
        if not html:
            return
        
        parsed_data = self.parse_html(html, url)
        chunks = self.parse_c_specific_content(parsed_data)
        self.insert_knowledge(chunks)
