"""Bash-specific scraper implementation."""

from typing import Dict, Any, List
from ..base_scraper import BaseScraper


class BashScraper(BaseScraper):
    """Bash-specific scraper with language-specific parsing rules."""
    
    def __init__(self, language: str, source_config: Dict[str, Any]):
        super().__init__(language, source_config)
        self.language = "bash"
    
    def parse_bash_specific_content(self, parsed_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse Bash-specific content patterns."""
        chunks = self.normalize_content(parsed_data)
        
        for chunk in chunks:
            chunk["tags"].extend([
                "bash", "shell", "scripting", "unix", "command-line"
            ])
            
            content = chunk.get("content", "")
            if "#!/bin/bash" in content:
                chunk["tags"].append("shebang")
            if "function " in content:
                chunk["tags"].append("function-definition")
            if "if [" in content or "if [[ " in content:
                chunk["tags"].append("conditional-statement")
            if "for " in content and "in " in content:
                chunk["tags"].append("for-loop")
            if "while " in content:
                chunk["tags"].append("while-loop")
            if "case " in content:
                chunk["tags"].append("case-statement")
            if "$(" in content or "`" in content:
                chunk["tags"].append("command-substitution")
            if "export " in content:
                chunk["tags"].append("environment-variable")
            if "source " in content or ". " in content:
                chunk["tags"].append("file-sourcing")
        
        return chunks
    
    async def scrape_url(self, url: str) -> None:
        """Override to use Bash-specific parsing."""
        html = await self.fetch_page(url)
        if not html:
            return
        
        parsed_data = self.parse_html(html, url)
        chunks = self.parse_bash_specific_content(parsed_data)
        self.insert_knowledge(chunks)
