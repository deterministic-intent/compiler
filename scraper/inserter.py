"""Database insertion utilities."""

import logging
from typing import List, Dict, Any

from db.api import upsert_node
from db.schema import NodeIn
from scraper.lang_detect import extract_lang_hints

logger = logging.getLogger(__name__)


def insert_nodes(chunks: List[Dict[str, Any]]) -> int:
    """Insert knowledge chunks into the database."""
    inserted = 0
    for chunk in chunks:
        try:
            # Truncate source_title to <= 500 chars; drop if still invalid.
            st = chunk.get("source_title")
            if st is not None:
                st = str(st)[:500]
            if st is not None and len(st) > 500:
                continue
            chunk["source_title"] = st
            
            # Extract language hints (deterministic, registry-based)
            url = chunk.get("source_url", "")
            title = chunk.get("title", "")
            content = chunk.get("content", "")
            lang_info = extract_lang_hints(url, title, content)
            
            # Convert chunk to NodeIn format
            node_data = NodeIn(
                title=chunk["title"],
                content=chunk["content"],
                node_type=chunk["node_type"],
                language=chunk["language"],
                stack=chunk["stack"],
                tags=chunk["tags"],
                source_url=chunk["source_url"],
                source_title=chunk["source_title"],
                lang_hints=lang_info.get("lang_hints", []),
                lang_sources=lang_info.get("lang_sources", []),
            )
            
            # Insert into database
            upsert_node(node_data)
            inserted += 1
            
        except Exception as e:
            logger.error(f"Failed to insert chunk '{chunk.get('title', 'Unknown')}': {e}")
    return inserted


def insert_relations(relations: List[Dict[str, Any]]) -> None:
    """Insert relations between nodes."""
    from db.api import link_nodes
    from db.schema import RelationIn
    
    for relation in relations:
        try:
            relation_data = RelationIn(
                source_id=relation["source_id"],
                target_id=relation["target_id"],
                relation_type=relation["relation_type"],
                weight=relation.get("weight", 1)
            )
            
            link_nodes(relation_data)
            
        except Exception as e:
            logger.error(f"Failed to insert relation {relation['source_id']} -> {relation['target_id']}: {e}")


def batch_insert_nodes(chunks: List[Dict[str, Any]], batch_size: int = 100) -> None:
    """Insert nodes in batches for better performance."""
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        insert_nodes(batch)
        logger.info(f"Inserted batch {i//batch_size + 1} ({len(batch)} nodes)")


def create_relations_from_chunks(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Create relations between chunks based on content similarity."""
    relations = []
    
    # Simple relation creation based on shared tags
    for i, chunk1 in enumerate(chunks):
        for j, chunk2 in enumerate(chunks[i+1:], i+1):
            # Check for shared tags
            shared_tags = set(chunk1["tags"]) & set(chunk2["tags"])
            
            if len(shared_tags) >= 2:  # At least 2 shared tags
                relations.append({
                    "source_id": i,  # This would be actual node IDs in practice
                    "target_id": j,
                    "relation_type": "related",
                    "weight": len(shared_tags)
                })
    
    return relations
