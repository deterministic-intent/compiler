"""Data normalization utilities."""

import re
from typing import List, Dict, Any


def normalize_content(parsed_data: Dict[str, Any], language: str) -> List[Dict[str, Any]]:
    """Normalize parsed content into atomic knowledge chunks."""
    chunks = []
    
    # Split content by headings
    content_sections = split_by_headings(parsed_data["content"])
    
    for section in content_sections:
        if section["content"].strip():
            chunk = create_knowledge_chunk(section, parsed_data, language)
            if chunk:
                chunks.append(chunk)
    
    # Process code blocks separately (limit to first 10 to avoid too many chunks)
    code_blocks = parsed_data.get("code_blocks", [])[:10]
    for code_block in code_blocks:
        if code_block["content"].strip():
            chunk = create_code_chunk(code_block, parsed_data, language)
            if chunk:
                chunks.append(chunk)
    
    # Limit total chunks to avoid overwhelming the system
    if len(chunks) > 200:  # Increased limit for better coverage
        chunks = chunks[:200]
    
    return chunks


def split_by_headings(content: str) -> List[Dict[str, Any]]:
    """Split content by heading markers."""
    sections = []
    lines = content.split("\n")
    current_section = {"title": "", "content": "", "level": 0}
    
    for line in lines:
        # Check if line is a heading (only use main headings # and ##)
        heading_match = re.match(r"^(#{1,2})\s+(.+)$", line)
        
        if heading_match:
            # Save previous section if it has content
            if current_section["content"].strip():
                sections.append(current_section)
            
            # Start new section
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            current_section = {
                "title": title,
                "content": "",
                "level": level
            }
        else:
            # Add line to current section
            current_section["content"] += line + "\n"
    
    # Add the last section
    if current_section["content"].strip():
        sections.append(current_section)
    
    # Filter out very short sections and limit total sections
    sections = [section for section in sections if len(section["content"].strip()) >= 200]
    
    # Limit to first 20 sections to avoid too many chunks
    sections = sections[:20]
    
    return sections


def clean_content(content: str) -> str:
    """Clean content by removing HTML artifacts and normalizing whitespace."""
    if not content:
        return content
    
    # Remove HTML tags more aggressively
    content = re.sub(r'<[^>]*>', '', content)
    
    # Remove HTML entities
    content = re.sub(r'&[a-zA-Z]+;', '', content)
    content = re.sub(r'&#\d+;', '', content)
    content = re.sub(r'&[#x][0-9a-fA-F]+;', '', content)
    
    # Remove common HTML artifacts
    content = re.sub(r'javascript:', '', content, flags=re.IGNORECASE)
    content = re.sub(r'on\w+\s*=', '', content, flags=re.IGNORECASE)
    
    # Remove markdown code block artifacts that might contain HTML
    content = re.sub(r'```[^`]*```', '', content)
    
    # Normalize whitespace
    content = re.sub(r'\s+', ' ', content)
    
    # Remove leading/trailing whitespace
    content = content.strip()
    
    return content


def split_long_content(content: str, title: str, language: str, parsed_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Split long content into smaller, manageable chunks."""
    # Target 800-1500 tokens per node with 100-150 token overlap
    # Roughly 1 token = 4 characters, so 3200-6000 chars per chunk
    target_chunk_size = 4000  # ~1000 tokens
    overlap_size = 400  # ~100 tokens
    
    if len(content) <= target_chunk_size:
        return [{
            "title": title,
            "content": content,
            "node_type": determine_node_type(title, content),
            "language": language,
            "stack": None,
            "tags": extract_tags(title, content, language),
            "source_url": parsed_data.get("url"),
            "source_title": parsed_data.get("title")
        }]
    
    chunks = []
    paragraphs = content.split('\n\n')
    current_chunk = ""
    chunk_title = title
    
    for paragraph in paragraphs:
        if len(current_chunk) + len(paragraph) > target_chunk_size:
            if current_chunk:
                chunks.append({
                    "title": chunk_title,
                    "content": current_chunk.strip(),
                    "node_type": determine_node_type(chunk_title, current_chunk.strip()),
                    "language": language,
                    "stack": None,
                    "tags": extract_tags(chunk_title, current_chunk.strip(), language),
                    "source_url": parsed_data.get("url"),
                    "source_title": parsed_data.get("title")
                })
            # Start new chunk with overlap
            current_chunk = current_chunk[-overlap_size:] + "\n\n" + paragraph if current_chunk else paragraph
            chunk_title = f"{title} (Part {len(chunks) + 2})"
        else:
            current_chunk += "\n\n" + paragraph if current_chunk else paragraph
    
    # Add the last chunk
    if current_chunk:
        chunks.append({
            "title": chunk_title,
            "content": current_chunk.strip(),
            "node_type": determine_node_type(chunk_title, current_chunk.strip()),
            "language": language,
            "stack": None,
            "tags": extract_tags(chunk_title, current_chunk.strip(), language),
            "source_url": parsed_data.get("url"),
            "source_title": parsed_data.get("title")
        })
    
    return chunks


def create_knowledge_chunk(section: Dict[str, Any], parsed_data: Dict[str, Any], language: str) -> Dict[str, Any]:
    """Create a knowledge chunk from a content section."""
    # Handle both old and new section formats
    if "content" in section:
        content = clean_content(section["content"])
    else:
        # New format from improved extraction
        content = clean_content(section.get("content", ""))
    
    if not content or len(content) < 100:  # Minimum 100 chars for meaningful content
        return None
    
    # Skip very long content that might be too large for a single chunk
    if len(content) > 3000:  # Reduced threshold for better chunking
        # Split long content into smaller chunks
        chunks = split_long_content(content, section["title"], language, parsed_data)
        if chunks:
            return chunks[0]  # Return first chunk, others can be processed separately
        return None
    
    # Determine node type based on content
    node_type = determine_node_type(section["title"], content)
    
    # Extract tags
    tags = extract_tags(section["title"], content, language)
    
    return {
        "title": section["title"] or "Untitled Section",
        "content": content,
        "node_type": node_type,
        "language": language,
        "stack": None,  # Will be determined by mappers
        "tags": tags,
        "source_url": parsed_data["url"],
        "source_title": parsed_data["title"]
    }


def create_code_chunk(code_block: Dict[str, Any], parsed_data: Dict[str, Any], language: str) -> Dict[str, Any]:
    """Create a knowledge chunk from a code block."""
    content = clean_content(code_block["content"])
    if not content:
        return None
    
    # Determine node type
    node_type = "syntax" if code_block["language"] else "example"
    
    # Extract tags
    tags = extract_code_tags(content, language)
    
    return {
        "title": f"Code Example: {code_block.get('language', 'Unknown')}",
        "content": f"```{code_block.get('language', '')}\n{content}\n```",
        "node_type": node_type,
        "language": language,
        "stack": None,
        "tags": tags,
        "source_url": parsed_data["url"],
        "source_title": parsed_data["title"]
    }


def determine_node_type(title: str, content: str) -> str:
    """Determine the type of knowledge node based on content."""
    title_lower = title.lower()
    content_lower = content.lower()
    
    # Check for syntax patterns
    syntax_keywords = ["syntax", "grammar", "declaration", "statement", "expression"]
    if any(keyword in title_lower for keyword in syntax_keywords):
        return "syntax"
    
    # Check for capability patterns
    capability_keywords = ["function", "method", "api", "interface", "class"]
    if any(keyword in title_lower for keyword in capability_keywords):
        return "capability"
    
    # Check for abstraction patterns
    abstraction_keywords = ["concept", "pattern", "paradigm", "architecture", "design"]
    if any(keyword in title_lower for keyword in abstraction_keywords):
        return "abstraction"
    
    # Check for example patterns
    example_keywords = ["example", "tutorial", "demo", "sample", "usage"]
    if any(keyword in title_lower for keyword in example_keywords):
        return "example"
    
    # Default to concept
    return "concept"


def extract_tags(title: str, content: str, language: str) -> List[str]:
    """Extract relevant tags from content."""
    tags = [language]
    
    # Extract common programming terms
    programming_terms = [
        "function", "variable", "class", "object", "method", "property",
        "loop", "condition", "array", "string", "number", "boolean",
        "error", "exception", "module", "package", "import", "export"
    ]
    
    content_lower = content.lower()
    for term in programming_terms:
        if term in content_lower:
            tags.append(term)
    
    # Extract language-specific terms
    language_tags = get_language_specific_tags(language)
    tags.extend(language_tags)
    
    return list(set(tags))  # Remove duplicates


def extract_code_tags(content: str, language: str) -> List[str]:
    """Extract tags from code content."""
    tags = [language, "code", "example"]
    
    # Add language-specific tags
    language_tags = get_language_specific_tags(language)
    tags.extend(language_tags)
    
    return list(set(tags))


def get_language_specific_tags(language: str) -> List[str]:
    """Get language-specific tags."""
    language_tag_map = {
        "python": ["python", "indentation", "def", "class", "import"],
        "javascript": ["javascript", "js", "function", "var", "let", "const"],
        "typescript": ["typescript", "ts", "interface", "type", "enum"],
        "java": ["java", "public", "private", "static", "void"],
        "go": ["go", "golang", "func", "package", "import"],
        "rust": ["rust", "fn", "let", "mut", "struct", "enum"],
        "c": ["c", "include", "int", "char", "pointer"],
        "cpp": ["cpp", "c++", "class", "template", "namespace"],
        "php": ["php", "function", "class", "namespace"],
        "ruby": ["ruby", "def", "class", "module", "end"],
        "swift": ["swift", "func", "class", "struct", "enum"],
        "kotlin": ["kotlin", "fun", "class", "data", "object"],
        "solidity": ["solidity", "contract", "function", "mapping"],
        "bash": ["bash", "shell", "script", "command"],
        "sql": ["sql", "database", "query", "table", "select"]
    }
    
    return language_tag_map.get(language, [])
