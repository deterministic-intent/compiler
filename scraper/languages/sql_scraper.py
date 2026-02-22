"""SQL-specific scraper implementation."""

from typing import Dict, Any, List
from ..base_scraper import BaseScraper


class SqlScraper(BaseScraper):
    """SQL-specific scraper with language-specific parsing rules."""
    
    def __init__(self, language: str, source_config: Dict[str, Any]):
        super().__init__(language, source_config)
        self.language = "sql"
    
    def parse_sql_specific_content(self, parsed_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse SQL-specific content patterns."""
        chunks = self.normalize_content(parsed_data)
        
        for chunk in chunks:
            chunk["tags"].extend([
                "sql", "database", "query-language", "relational"
            ])
            
            content = chunk.get("content", "")
            if "SELECT " in content.upper():
                chunk["tags"].append("select-statement")
            if "INSERT " in content.upper():
                chunk["tags"].append("insert-statement")
            if "UPDATE " in content.upper():
                chunk["tags"].append("update-statement")
            if "DELETE " in content.upper():
                chunk["tags"].append("delete-statement")
            if "CREATE TABLE" in content.upper():
                chunk["tags"].append("create-table")
            if "ALTER TABLE" in content.upper():
                chunk["tags"].append("alter-table")
            if "DROP TABLE" in content.upper():
                chunk["tags"].append("drop-table")
            if "JOIN " in content.upper():
                chunk["tags"].append("join-operation")
            if "WHERE " in content.upper():
                chunk["tags"].append("where-clause")
            if "GROUP BY" in content.upper():
                chunk["tags"].append("group-by")
            if "ORDER BY" in content.upper():
                chunk["tags"].append("order-by")
            if "HAVING " in content.upper():
                chunk["tags"].append("having-clause")
            if "INDEX" in content.upper():
                chunk["tags"].append("index")
            if "TRANSACTION" in content.upper():
                chunk["tags"].append("transaction")
        
        return chunks
    
    async def scrape_url(self, url: str) -> None:
        """Override to use SQL-specific parsing."""
        html = await self.fetch_page(url)
        if not html:
            return
        
        parsed_data = self.parse_html(html, url)
        chunks = self.parse_sql_specific_content(parsed_data)
        self.insert_knowledge(chunks)
