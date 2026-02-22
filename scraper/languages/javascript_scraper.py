"""JavaScript-specific scraper implementation."""

from typing import Dict, Any, List
from ..base_scraper import BaseScraper


class JavaScriptScraper(BaseScraper):
    """JavaScript-specific scraper with language-specific parsing rules."""
    
    def __init__(self, language: str, source_config: Dict[str, Any]):
        super().__init__(language, source_config)
        self.language = "javascript"
    
    def parse_javascript_specific_content(self, parsed_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse JavaScript-specific content patterns."""
        chunks = self.normalize_content(parsed_data)
        
        for chunk in chunks:
            chunk["tags"].extend([
                "javascript", "js", "dynamic-typing", "prototype-based"
            ])
            
            content = chunk.get("content", "")
            if "function " in content:
                chunk["tags"].append("function-declaration")
            if "=>" in content:
                chunk["tags"].append("arrow-function")
            if "const " in content or "let " in content or "var " in content:
                chunk["tags"].append("variable-declaration")
            if "class " in content:
                chunk["tags"].append("class-declaration")
            if "import " in content or "export " in content:
                chunk["tags"].append("module-system")
            if "async " in content:
                chunk["tags"].append("async-function")
            if "await " in content:
                chunk["tags"].append("await-expression")
            if "Promise" in content:
                chunk["tags"].append("promise")
        
        return chunks
    
    async def scrape_url(self, url: str) -> None:
        """Override to use JavaScript-specific parsing."""
        html = await self.fetch_page(url)
        if not html:
            return
        
        parsed_data = self.parse_html(html, url)
        chunks = self.parse_javascript_specific_content(parsed_data)
        self.insert_knowledge(chunks)
