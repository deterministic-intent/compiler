"""Ruby-specific scraper implementation."""

from typing import Dict, Any, List
from ..base_scraper import BaseScraper


class RubyScraper(BaseScraper):
    """Ruby-specific scraper with language-specific parsing rules."""
    
    def __init__(self, language: str, source_config: Dict[str, Any]):
        super().__init__(language, source_config)
        self.language = "ruby"
    
    def parse_ruby_specific_content(self, parsed_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse Ruby-specific content patterns."""
        chunks = self.normalize_content(parsed_data)
        
        for chunk in chunks:
            chunk["tags"].extend([
                "ruby", "object-oriented", "dynamic-typing", "metaprogramming"
            ])
            
            content = chunk.get("content", "")
            if "def " in content:
                chunk["tags"].append("method-definition")
            if "class " in content:
                chunk["tags"].append("class-definition")
            if "module " in content:
                chunk["tags"].append("module-definition")
            if "attr_accessor" in content or "attr_reader" in content or "attr_writer" in content:
                chunk["tags"].append("attribute-accessor")
            if "include " in content:
                chunk["tags"].append("module-inclusion")
            if "extend " in content:
                chunk["tags"].append("module-extension")
            if "require " in content or "load " in content:
                chunk["tags"].append("file-loading")
            if "yield " in content:
                chunk["tags"].append("block-yielding")
            if "do |" in content or "{|" in content:
                chunk["tags"].append("block")
        
        return chunks
    
    async def scrape_url(self, url: str) -> None:
        """Override to use Ruby-specific parsing."""
        html = await self.fetch_page(url)
        if not html:
            return
        
        parsed_data = self.parse_html(html, url)
        chunks = self.parse_ruby_specific_content(parsed_data)
        self.insert_knowledge(chunks)
