#!/usr/bin/env python3
"""Specialized processor for HTML Living Standard - single page splitter."""

import asyncio
import httpx
from bs4 import BeautifulSoup
from typing import List, Dict, Any
import logging
from markdownify import markdownify

logger = logging.getLogger(__name__)

class HTMLLivingStandardProcessor:
    """Process HTML Living Standard as a single page split by headings."""
    
    def __init__(self):
        self.base_url = "https://html.spec.whatwg.org/"
    
    async def fetch_and_split(self) -> List[Dict[str, Any]]:
        """Fetch the single HTML LS page and split it by headings."""
        logger.info("Fetching HTML Living Standard...")
        
        async with httpx.AsyncClient() as session:
            response = await session.get(self.base_url, timeout=60.0)
            response.raise_for_status()
            
            html = response.text
            logger.info(f"Fetched {len(html)} characters")
            
            return self.split_by_headings(html)
    
    def split_by_headings(self, html: str) -> List[Dict[str, Any]]:
        """Split HTML content by h2/h3 headings into virtual nodes."""
        soup = BeautifulSoup(html, "html.parser")
        
        # Remove non-content elements early
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        
        # Find all h2 and h3 headings
        headings = soup.find_all(["h2", "h3"])
        logger.info(f"Found {len(headings)} headings to split on")
        
        sections = []
        
        for i, heading in enumerate(headings):
            # Get heading text and ID
            heading_text = heading.get_text().strip()
            heading_id = heading.get("id", "")
            
            if not heading_text:
                continue
            
            # Collect content until next heading
            content_elements = []
            current = heading.next_sibling
            
            while current and current.name not in ["h2", "h3"]:
                if hasattr(current, 'name') and current.name:
                    content_elements.append(current)
                current = current.next_sibling
            
                                        # Convert to text directly (avoid markdownify recursion)
            content_text = ""
            if content_elements:
                for elem in content_elements:
                    # Handle different element types
                    if elem.name == 'p':
                        content_text += elem.get_text() + "\n\n"
                    elif elem.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                        content_text += f"## {elem.get_text()}\n\n"
                    elif elem.name == 'code':
                        content_text += f"`{elem.get_text()}` "
                    elif elem.name == 'pre':
                        content_text += f"```\n{elem.get_text()}\n```\n\n"
                    elif elem.name == 'ul':
                        for li in elem.find_all('li'):
                            content_text += f"- {li.get_text()}\n"
                        content_text += "\n"
                    elif elem.name == 'ol':
                        for i, li in enumerate(elem.find_all('li'), 1):
                            content_text += f"{i}. {li.get_text()}\n"
                        content_text += "\n"
                    else:
                        content_text += elem.get_text() + "\n"
                
                # Clean up content
                content_text = self.clean_content(content_text)
            
            if len(content_text.strip()) > 200:  # Minimum content length
                    sections.append({
                        "title": heading_text,
                        "content": content_text,
                        "url": f"{self.base_url}#{heading_id}" if heading_id else self.base_url,
                        "heading_level": heading.name,
                        "heading_id": heading_id
                    })
        
        logger.info(f"Created {len(sections)} sections")
        return sections
    
    def clean_content(self, content: str) -> str:
        """Clean up markdown content."""
        # Remove excessive whitespace
        content = " ".join(content.split())
        
        # Remove common HTML artifacts
        content = content.replace("```None", "```html")
        
        return content
    
    def create_knowledge_chunks(self, sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert sections to knowledge chunks."""
        chunks = []
        
        for section in sections:
            # Split long content
            if len(section["content"]) > 4000:
                # Split by paragraphs
                paragraphs = section["content"].split('\n\n')
                current_chunk = ""
                chunk_num = 1
                
                for paragraph in paragraphs:
                    if len(current_chunk) + len(paragraph) > 4000:
                        if current_chunk:
                            chunks.append({
                                "title": f"{section['title']} (Part {chunk_num})",
                                "content": current_chunk.strip(),
                                "node_type": "syntax",
                                "language": "html",
                                "stack": "web",
                                "tags": ["html", "spec", "living-standard"],
                                "source_url": section["url"],
                                "source_title": "HTML Living Standard"
                            })
                            chunk_num += 1
                        current_chunk = paragraph
                    else:
                        current_chunk += "\n\n" + paragraph if current_chunk else paragraph
                
                # Add final chunk
                if current_chunk:
                    chunks.append({
                        "title": f"{section['title']} (Part {chunk_num})",
                        "content": current_chunk.strip(),
                        "node_type": "syntax",
                        "language": "html",
                        "stack": "web",
                        "tags": ["html", "spec", "living-standard"],
                        "source_url": section["url"],
                        "source_title": "HTML Living Standard"
                    })
            else:
                chunks.append({
                    "title": section["title"],
                    "content": section["content"],
                    "node_type": "syntax",
                    "language": "html",
                    "stack": "web",
                    "tags": ["html", "spec", "living-standard"],
                    "source_url": section["url"],
                    "source_title": "HTML Living Standard"
                })
        
        return chunks

async def process_html_ls():
    """Process HTML Living Standard and return knowledge chunks."""
    processor = HTMLLivingStandardProcessor()
    sections = await processor.fetch_and_split()
    chunks = processor.create_knowledge_chunks(sections)
    return chunks

if __name__ == "__main__":
    async def main():
        chunks = await process_html_ls()
        print(f"Generated {len(chunks)} knowledge chunks")
        for i, chunk in enumerate(chunks[:5], 1):
            print(f"{i}. {chunk['title']} ({len(chunk['content'])} chars)")
    
    asyncio.run(main())
