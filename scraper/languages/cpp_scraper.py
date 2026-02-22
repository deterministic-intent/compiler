"""C++-specific scraper implementation."""

from typing import Dict, Any, List
from ..base_scraper import BaseScraper


class CppScraper(BaseScraper):
    """C++-specific scraper with language-specific parsing rules."""
    
    def __init__(self, language: str, source_config: Dict[str, Any]):
        super().__init__(language, source_config)
        self.language = "cpp"
    
    def parse_cpp_specific_content(self, parsed_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse C++-specific content patterns."""
        chunks = self.normalize_content(parsed_data)
        
        for chunk in chunks:
            chunk["tags"].extend([
                "cpp", "c++", "object-oriented", "multi-paradigm"
            ])
            
            content = chunk.get("content", "")
            if "class " in content:
                chunk["tags"].append("class-declaration")
            if "namespace " in content:
                chunk["tags"].append("namespace")
            if "template<" in content:
                chunk["tags"].append("template")
            if "std::" in content:
                chunk["tags"].append("standard-library")
            if "virtual " in content:
                chunk["tags"].append("virtual-function")
            if "const " in content:
                chunk["tags"].append("const-correctness")
            if "&" in content and "int" in content:
                chunk["tags"].append("reference")
            if "new " in content or "delete " in content:
                chunk["tags"].append("dynamic-memory")
        
        return chunks
    
    async def scrape_url(self, url: str) -> None:
        """Override to use C++-specific parsing."""
        html = await self.fetch_page(url)
        if not html:
            return
        
        parsed_data = self.parse_html(html, url)
        chunks = self.parse_cpp_specific_content(parsed_data)
        self.insert_knowledge(chunks)
