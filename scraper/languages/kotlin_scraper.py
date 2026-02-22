"""Kotlin-specific scraper implementation."""

from typing import Dict, Any, List
from ..base_scraper import BaseScraper


class KotlinScraper(BaseScraper):
    """Kotlin-specific scraper with language-specific parsing rules."""
    
    def __init__(self, language: str, source_config: Dict[str, Any]):
        super().__init__(language, source_config)
        self.language = "kotlin"
    
    def parse_kotlin_specific_content(self, parsed_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse Kotlin-specific content patterns."""
        chunks = self.normalize_content(parsed_data)
        
        for chunk in chunks:
            chunk["tags"].extend([
                "kotlin", "android", "jvm", "interoperable", "null-safety"
            ])
            
            content = chunk.get("content", "")
            if "fun " in content:
                chunk["tags"].append("function-declaration")
            if "class " in content:
                chunk["tags"].append("class-declaration")
            if "data class " in content:
                chunk["tags"].append("data-class")
            if "object " in content:
                chunk["tags"].append("object-declaration")
            if "interface " in content:
                chunk["tags"].append("interface-declaration")
            if "val " in content or "var " in content:
                chunk["tags"].append("variable-declaration")
            if "?" in content:
                chunk["tags"].append("nullable-type")
            if "!!" in content:
                chunk["tags"].append("non-null-assertion")
            if "when " in content:
                chunk["tags"].append("when-expression")
            if "by " in content:
                chunk["tags"].append("delegation")
        
        return chunks
    
    async def scrape_url(self, url: str) -> None:
        """Override to use Kotlin-specific parsing."""
        html = await self.fetch_page(url)
        if not html:
            return
        
        parsed_data = self.parse_html(html, url)
        chunks = self.parse_kotlin_specific_content(parsed_data)
        self.insert_knowledge(chunks)
