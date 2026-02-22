"""Rust-specific scraper implementation."""

from typing import Dict, Any, List
from ..base_scraper import BaseScraper


class RustScraper(BaseScraper):
    """Rust-specific scraper with language-specific parsing rules."""
    
    def __init__(self, language: str, source_config: Dict[str, Any]):
        super().__init__(language, source_config)
        self.language = "rust"
    
    def parse_rust_specific_content(self, parsed_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse Rust-specific content patterns."""
        chunks = self.normalize_content(parsed_data)
        
        for chunk in chunks:
            chunk["tags"].extend([
                "rust", "systems-programming", "memory-safety", "zero-cost-abstractions"
            ])
            
            content = chunk.get("content", "")
            if "fn " in content:
                chunk["tags"].append("function-declaration")
            if "struct " in content:
                chunk["tags"].append("struct-declaration")
            if "enum " in content:
                chunk["tags"].append("enum-declaration")
            if "trait " in content:
                chunk["tags"].append("trait-declaration")
            if "impl " in content:
                chunk["tags"].append("implementation")
            if "let " in content:
                chunk["tags"].append("variable-declaration")
            if "mut " in content:
                chunk["tags"].append("mutable-binding")
            if "&" in content or "&mut" in content:
                chunk["tags"].append("borrowing")
            if "Box<" in content or "Rc<" in content or "Arc<" in content:
                chunk["tags"].append("smart-pointers")
            if "unsafe " in content:
                chunk["tags"].append("unsafe-block")
        
        return chunks
    
    async def scrape_url(self, url: str) -> None:
        """Override to use Rust-specific parsing."""
        html = await self.fetch_page(url)
        if not html:
            return
        
        parsed_data = self.parse_html(html, url)
        chunks = self.parse_rust_specific_content(parsed_data)
        self.insert_knowledge(chunks)
