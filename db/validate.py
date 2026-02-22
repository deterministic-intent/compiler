"""Database validation and integrity checks."""

from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from .engine import get_session
from .models import Node, Relation

# Policy loader (optional - for future policy-aware validation)
try:
    from policy import load_policy, get_default_policy_version
except ImportError:
    load_policy = None
    get_default_policy_version = None


def get_policy_for_validation(policy_version: Optional[str] = None):
    """
    Get policy for validation. Step 1: wiring only - no enforcement yet.
    
    Helper only locates policy_version and calls load_policy().
    All enforcement logic lives elsewhere (not in helpers).
    
    Args:
        policy_version: Optional explicit version (if None, uses default)
    
    Returns:
        Policy object or None if policy module unavailable or load fails
    """
    if load_policy is None:
        return None
    
    if policy_version is None:
        if get_default_policy_version:
            policy_version = get_default_policy_version()
        else:
            return None
    
    try:
        return load_policy(policy_version)
    except Exception:
        return None


def check_orphan_nodes() -> List[Dict[str, Any]]:
    """Find nodes that have no incoming or outgoing relations."""
    with get_session() as session:
        # Find nodes with no relations
        orphan_nodes = session.query(Node).outerjoin(
            Relation, or_(
                Node.id == Relation.source_id,
                Node.id == Relation.target_id
            )
        ).filter(Relation.id.is_(None)).all()
        
        return [
            {
                "id": node.id,
                "title": node.title,
                "language": node.language,
                "node_type": node.node_type
            }
            for node in orphan_nodes
        ]


def check_cyclic_relations() -> List[Dict[str, Any]]:
    """Find cyclic relations in the graph."""
    with get_session() as session:
        # Find self-references
        self_refs = session.query(Relation).filter(
            Relation.source_id == Relation.target_id
        ).all()
        
        cycles = []
        for rel in self_refs:
            cycles.append({
                "relation_id": rel.id,
                "node_id": rel.source_id,
                "type": "self_reference"
            })
        
        # TODO: Implement more complex cycle detection using graph algorithms
        return cycles


def check_required_fields() -> List[Dict[str, Any]]:
    """Check for nodes with missing required fields."""
    with get_session() as session:
        invalid_nodes = []
        
        # Check for empty titles
        empty_titles = session.query(Node).filter(
            or_(Node.title.is_(None), Node.title == "")
        ).all()
        
        for node in empty_titles:
            invalid_nodes.append({
                "id": node.id,
                "issue": "empty_title",
                "field": "title"
            })
        
        # Check for empty content
        empty_content = session.query(Node).filter(
            or_(Node.content.is_(None), Node.content == "")
        ).all()
        
        for node in empty_content:
            invalid_nodes.append({
                "id": node.id,
                "issue": "empty_content",
                "field": "content"
            })
        
        # Check for invalid node types
        valid_types = ["abstraction", "syntax", "capability", "concept", "example"]
        invalid_types = session.query(Node).filter(
            ~Node.node_type.in_(valid_types)
        ).all()
        
        for node in invalid_types:
            invalid_nodes.append({
                "id": node.id,
                "issue": "invalid_node_type",
                "field": "node_type",
                "value": node.node_type
            })
        
        return invalid_nodes


def validate_database() -> Dict[str, Any]:
    """Run all validation checks and return results."""
    return {
        "orphan_nodes": check_orphan_nodes(),
        "cyclic_relations": check_cyclic_relations(),
        "invalid_nodes": check_required_fields()
    }
