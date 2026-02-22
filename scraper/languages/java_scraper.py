"""Java-specific scraper implementation."""

from typing import Dict, Any, List
from ..base_scraper import BaseScraper


class JavaScraper(BaseScraper):
    """Java-specific scraper with language-specific parsing rules."""
    
    def __init__(self, language: str, source_config: Dict[str, Any]):
        super().__init__(language, source_config)
        self.language = "java"
    
    def parse_java_specific_content(self, parsed_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse Java-specific content patterns."""
        chunks = self.normalize_content(parsed_data)
        
        for chunk in chunks:
            chunk["tags"].extend([
                "java", "object-oriented", "static-typing", "jvm"
            ])
            
            content = chunk.get("content", "")
            if "public class " in content or "private class " in content:
                chunk["tags"].append("class-declaration")
            if "public static void main" in content:
                chunk["tags"].append("main-method")
            if "extends " in content:
                chunk["tags"].append("inheritance")
            if "implements " in content:
                chunk["tags"].append("interface-implementation")
            if "interface " in content:
                chunk["tags"].append("interface-declaration")
            if "try {" in content and "catch" in content:
                chunk["tags"].append("exception-handling")
            if "synchronized " in content:
                chunk["tags"].append("threading")
        
        return chunks
    
    async def scrape_url(self, url: str) -> None:
        """Override to use Java-specific parsing."""
        html = await self.fetch_page(url)
        if not html:
            return
        
        parsed_data = self.parse_html(html, url)
        chunks = self.parse_java_specific_content(parsed_data)
        self.insert_knowledge(chunks)
