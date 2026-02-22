"""Parser utilities and helper functions."""

import re
from typing import List, Dict, Any
from bs4 import BeautifulSoup, Tag


def extract_code_blocks(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """Extract code blocks from HTML content."""
    code_blocks = []
    
    # Find <pre><code> blocks
    for pre in soup.find_all("pre"):
        code = pre.find("code")
        if code:
            language = code.get("class", [None])[0] if code.get("class") else None
            code_blocks.append({
                "content": code.get_text(),
                "language": language,
                "type": "pre_code"
            })
    
    # Find standalone <code> blocks
    for code in soup.find_all("code"):
        if not code.find_parent("pre"):
            code_blocks.append({
                "content": code.get_text(),
                "language": None,
                "type": "inline_code"
            })
    
    return code_blocks


def detect_toc(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """Detect table of contents structure."""
    toc = []
    
    # Look for common TOC patterns
    toc_selectors = [
        ".toc", ".table-of-contents", ".contents", 
        "#toc", "#table-of-contents", "#contents",
        "[role='navigation']", ".nav", ".sidebar"
    ]
    
    for selector in toc_selectors:
        toc_element = soup.select_one(selector)
        if toc_element:
            toc = extract_toc_items(toc_element)
            break
    
    # If no explicit TOC found, try to infer from headings
    if not toc:
        toc = infer_toc_from_headings(soup)
    
    return toc


def extract_toc_items(element: Tag) -> List[Dict[str, Any]]:
    """Extract TOC items from a navigation element."""
    items = []
    
    for link in element.find_all("a", href=True):
        items.append({
            "title": link.get_text().strip(),
            "href": link["href"],
            "level": determine_heading_level(link)
        })
    
    return items


def infer_toc_from_headings(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """Infer TOC structure from heading elements."""
    toc = []
    
    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        # Try to find an ID or generate one
        heading_id = heading.get("id") or generate_heading_id(heading.get_text())
        
        toc.append({
            "title": heading.get_text().strip(),
            "href": f"#{heading_id}",
            "level": int(heading.name[1])
        })
    
    return toc


def determine_heading_level(element: Tag) -> int:
    """Determine the heading level based on element structure."""
    # Check if element is in a nested structure
    parent = element.parent
    level = 1
    
    while parent:
        if parent.name in ["li", "ul", "ol"]:
            level += 1
        parent = parent.parent
    
    return min(level, 6)


def generate_heading_id(text: str) -> str:
    """Generate a URL-friendly ID from heading text."""
    # Convert to lowercase and replace spaces with hyphens
    id_text = re.sub(r'[^\w\s-]', '', text.lower())
    id_text = re.sub(r'[-\s]+', '-', id_text)
    return id_text.strip('-')


def extract_metadata(soup: BeautifulSoup) -> Dict[str, Any]:
    """Extract metadata from HTML head section."""
    metadata = {}
    
    # Extract meta tags
    for meta in soup.find_all("meta"):
        name = meta.get("name") or meta.get("property")
        content = meta.get("content")
        if name and content:
            metadata[name] = content
    
    # Extract Open Graph tags
    og_tags = {}
    for meta in soup.find_all("meta", property=re.compile(r"^og:")):
        property_name = meta.get("property", "").replace("og:", "")
        og_tags[property_name] = meta.get("content", "")
    
    if og_tags:
        metadata["og"] = og_tags
    
    return metadata


def clean_html_content(html: str) -> str:
    """Clean HTML content by removing unwanted elements."""
    soup = BeautifulSoup(html, "html.parser")
    
    # Remove script and style elements
    for element in soup(["script", "style", "nav", "footer", "header"]):
        element.decompose()
    
    # Remove comments
    for comment in soup.find_all(string=lambda text: isinstance(text, str) and text.strip().startswith("<!--")):
        comment.extract()
    
    return str(soup)
