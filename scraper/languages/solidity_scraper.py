"""Solidity-specific scraper implementation."""

from typing import Dict, Any, List
from ..base_scraper import BaseScraper


class SolidityScraper(BaseScraper):
    """Solidity-specific scraper with language-specific parsing rules."""
    
    def __init__(self, language: str, source_config: Dict[str, Any]):
        super().__init__(language, source_config)
        self.language = "solidity"
    
    def parse_solidity_specific_content(self, parsed_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse Solidity-specific content patterns."""
        chunks = self.normalize_content(parsed_data)
        
        for chunk in chunks:
            chunk["tags"].extend([
                "solidity", "ethereum", "smart-contract", "blockchain"
            ])
            
            content = chunk.get("content", "")
            if "contract " in content:
                chunk["tags"].append("contract-declaration")
            if "function " in content:
                chunk["tags"].append("function-declaration")
            if "modifier " in content:
                chunk["tags"].append("modifier")
            if "event " in content:
                chunk["tags"].append("event-declaration")
            if "mapping(" in content:
                chunk["tags"].append("mapping")
            if "address " in content:
                chunk["tags"].append("address-type")
            if "wei" in content or "ether" in content:
                chunk["tags"].append("currency-unit")
            if "payable" in content:
                chunk["tags"].append("payable-function")
            if "gas" in content:
                chunk["tags"].append("gas-management")
        
        return chunks
    
    async def scrape_url(self, url: str) -> None:
        """Override to use Solidity-specific parsing."""
        html = await self.fetch_page(url)
        if not html:
            return
        
        parsed_data = self.parse_html(html, url)
        chunks = self.parse_solidity_specific_content(parsed_data)
        self.insert_knowledge(chunks)
