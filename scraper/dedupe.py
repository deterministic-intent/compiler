"""Deduplication utilities."""

import hashlib
import re
from typing import List, Dict, Any, Set
from difflib import SequenceMatcher


def create_content_hash(content: str) -> str:
    """Create a stable hash of content for deduplication."""
    # Normalize content for consistent hashing
    normalized = normalize_for_hashing(content)
    return hashlib.md5(normalized.encode('utf-8')).hexdigest()


def normalize_for_hashing(content: str) -> str:
    """Normalize content for consistent hashing."""
    # Remove extra whitespace
    content = re.sub(r'\s+', ' ', content.strip())
    
    # Remove common boilerplate
    content = re.sub(r'^(#+\s*)?(Introduction|Overview|Summary|Conclusion)', '', content, flags=re.IGNORECASE)
    
    # Remove code block markers
    content = re.sub(r'```\w*\n', '', content)
    content = re.sub(r'```\s*$', '', content)
    
    return content.lower()


def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate similarity between two texts using SequenceMatcher."""
    return SequenceMatcher(None, text1, text2).ratio()


def find_near_duplicates(chunks: List[Dict[str, Any]], similarity_threshold: float = 0.8) -> List[List[int]]:
    """Find near-duplicate chunks based on content similarity."""
    duplicate_groups = []
    processed = set()
    
    for i, chunk1 in enumerate(chunks):
        if i in processed:
            continue
            
        current_group = [i]
        content1 = chunk1.get("content", "")
        
        for j, chunk2 in enumerate(chunks[i+1:], i+1):
            if j in processed:
                continue
                
            content2 = chunk2.get("content", "")
            similarity = calculate_similarity(content1, content2)
            
            if similarity >= similarity_threshold:
                current_group.append(j)
                processed.add(j)
        
        if len(current_group) > 1:
            duplicate_groups.append(current_group)
            processed.update(current_group)
    
    return duplicate_groups


def merge_duplicate_chunks(chunks: List[Dict[str, Any]], duplicate_groups: List[List[int]]) -> List[Dict[str, Any]]:
    """Merge duplicate chunks, keeping the best version."""
    merged_chunks = []
    merged_indices = set()
    
    for group in duplicate_groups:
        # Find the best chunk in the group (longest content, most tags, etc.)
        best_chunk = None
        best_score = 0
        
        for idx in group:
            chunk = chunks[idx]
            score = calculate_chunk_score(chunk)
            
            if score > best_score:
                best_score = score
                best_chunk = chunk
        
        if best_chunk:
            merged_chunks.append(best_chunk)
            merged_indices.update(group)
    
    # Add non-duplicate chunks
    for i, chunk in enumerate(chunks):
        if i not in merged_indices:
            merged_chunks.append(chunk)
    
    return merged_chunks


def calculate_chunk_score(chunk: Dict[str, Any]) -> float:
    """Calculate a score for a chunk to determine the best version."""
    score = 0.0
    
    # Content length (prefer longer, more detailed content)
    content = chunk.get("content", "")
    score += len(content) * 0.1
    
    # Number of tags (more tags = more detailed)
    tags = chunk.get("tags", [])
    score += len(tags) * 10
    
    # Has source URL (prefer chunks with source attribution)
    if chunk.get("source_url"):
        score += 50
    
    # Has title (prefer chunks with clear titles)
    if chunk.get("title"):
        score += 30
    
    # Node type preference
    node_type = chunk.get("node_type", "")
    type_scores = {
        "syntax": 100,
        "api": 90,
        "pattern": 80,
        "concept": 70,
        "example": 60
    }
    score += type_scores.get(node_type, 50)
    
    return score


def check_duplicates(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Check for duplicates and return unique chunks."""
    if not chunks:
        return []
    
    # First pass: exact hash-based deduplication
    seen_hashes = set()
    unique_chunks = []
    
    for chunk in chunks:
        content = chunk.get("content", "")
        content_hash = create_content_hash(content)
        
        if content_hash not in seen_hashes:
            seen_hashes.add(content_hash)
            unique_chunks.append(chunk)
    
    # Second pass: near-duplicate detection
    duplicate_groups = find_near_duplicates(unique_chunks)
    
    if duplicate_groups:
        unique_chunks = merge_duplicate_chunks(unique_chunks, duplicate_groups)
    
    return unique_chunks


def dedupe_by_title(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate chunks based on title similarity."""
    title_groups = {}
    
    for chunk in chunks:
        title = chunk.get("title", "").lower().strip()
        if title:
            if title not in title_groups:
                title_groups[title] = []
            title_groups[title].append(chunk)
    
    # Keep the best chunk from each title group
    deduped_chunks = []
    for title, group in title_groups.items():
        if len(group) == 1:
            deduped_chunks.append(group[0])
        else:
            # Find the best chunk in the group
            best_chunk = max(group, key=calculate_chunk_score)
            deduped_chunks.append(best_chunk)
    
    return deduped_chunks


def dedupe_by_url(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate chunks based on source URL."""
    url_groups = {}
    
    for chunk in chunks:
        url = chunk.get("source_url", "")
        if url:
            if url not in url_groups:
                url_groups[url] = []
            url_groups[url].append(chunk)
    
    # Keep the best chunk from each URL group
    deduped_chunks = []
    for url, group in url_groups.items():
        if len(group) == 1:
            deduped_chunks.append(group[0])
        else:
            # Find the best chunk in the group
            best_chunk = max(group, key=calculate_chunk_score)
            deduped_chunks.append(best_chunk)
    
    return deduped_chunks
