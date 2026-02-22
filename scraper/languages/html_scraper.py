"""HTML-specific scraper for HTML documentation."""

import re
from bs4 import BeautifulSoup
from ..base_scraper import BaseScraper
from ..html_ls_optimizer import process_html_ls


class HtmlScraper(BaseScraper):
    """Scraper for HTML documentation."""
    
    def parse_html_specific_content(self, soup, url: str) -> dict:
        """Parse HTML-specific content."""
        # Extract HTML elements and attributes
        elements = []
        attributes = []
        
        # Look for element definitions
        for element in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            text = element.get_text().strip()
            if 'element' in text.lower() or '<' in text:
                elements.append(text)
        
        # Look for attribute definitions
        for attr in soup.find_all(['code', 'pre']):
            text = attr.get_text().strip()
            if '=' in text and any(char in text for char in ['"', "'"]):
                attributes.append(text)
        
        return {
            "html_elements": elements[:10],  # Limit to first 10
            "html_attributes": attributes[:10],  # Limit to first 10
            "language": "html"
        }
    
    def parse_html(self, html: str, url: str) -> dict:
        """Override parse_html to handle complex HTML structure."""
        try:
            # Use a more robust HTML parsing approach
            soup = BeautifulSoup(html, "html.parser")
            
            # Extract basic metadata
            title = soup.find("title")
            title_text = title.get_text().strip() if title else ""
            
            # Clean up complex HTML before markdown conversion
            # Remove problematic elements that cause recursion
            for element in soup.find_all(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                element.decompose()
            
            # Remove deeply nested elements that might cause recursion
            for element in soup.find_all(recursive=True):
                if len(list(element.parents)) > 10:  # Too deeply nested
                    element.decompose()
            
            # Convert to markdown with safer settings
            from markdownify import markdownify
            markdown_content = markdownify(
                str(soup),
                heading_style="ATX",
                strip=['script', 'style', 'nav', 'footer', 'header', 'aside'],
                convert=['p', 'div', 'span', 'a', 'strong', 'em', 'code', 'pre']
            )
            
            # Extract code blocks manually to avoid recursion
            code_blocks = []
            for code in soup.find_all(['code', 'pre']):
                if code.get_text().strip():
                    code_blocks.append({
                        "content": code.get_text().strip(),
                        "language": code.get('class', [''])[0] if code.get('class') else None
                    })
            
            # Extract HTML-specific content
            html_specific = self.parse_html_specific_content(soup, url)
            
            return {
                "title": title_text,
                "content": markdown_content,
                "code_blocks": code_blocks[:10],  # Limit code blocks
                "toc": [],  # Skip TOC for HTML docs
                "url": url,
                **html_specific
            }
            
        except Exception as e:
            # Fallback to simple text extraction if markdownify fails
            soup = BeautifulSoup(html, "html.parser")
            title = soup.find("title")
            title_text = title.get_text().strip() if title else ""
            
            # Extract text content directly
            text_content = soup.get_text()
            # Clean up the text
            text_content = re.sub(r'\s+', ' ', text_content).strip()
            
            return {
                "title": title_text,
                "content": text_content[:5000],  # Limit content length
                "code_blocks": [],
                "toc": [],
                "url": url,
                "language": "html"
            }
    
    async def scrape_url(self, url: str) -> None:
        """Scrape HTML documentation."""
        # Add HTML-specific tags
        self.language = "html"
        self.stack = "web"
        
        # Use optimized processor for HTML Living Standard
        if "html.spec.whatwg.org" in url:
            logger.info("Using optimized HTML Living Standard processor")
            chunks = await process_html_ls()
            
            # Insert chunks directly
            for chunk in chunks:
                try:
                    from scraper.inserter import insert_knowledge_chunk
                    insert_knowledge_chunk(chunk)
                except Exception as e:
                    logger.error(f"Failed to insert chunk: {e}")
            
            logger.info(f"Inserted {len(chunks)} HTML LS chunks")
        else:
            # Use regular scraping for other HTML sources
            await super().scrape_url(url)
