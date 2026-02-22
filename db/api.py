"""Database API for CRUD operations and search."""

import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from .engine import get_session
from .models import Node, Relation, SnapshotMeta
from .schema import NodeIn, NodeOut, RelationIn, RelationOut, SearchQuery


def upsert_node(node_data: NodeIn) -> NodeOut:
    """Create or update a node."""
    with get_session() as session:
        # Check if node exists by title and language
        existing_node = session.query(Node).filter(
            and_(
                Node.title == node_data.title,
                Node.language == node_data.language
            )
        ).first()
        
        if existing_node:
            # Update existing node
            for field, value in node_data.dict(exclude_unset=True).items():
                setattr(existing_node, field, value)
            node = existing_node
        else:
            # Create new node
            node = Node(**node_data.dict())
            session.add(node)
        
        session.commit()
        session.refresh(node)
        return NodeOut.from_orm(node)


def list_nodes(
    language: Optional[str] = None,
    stack: Optional[str] = None,
    node_type: Optional[str] = None,
    limit: int = 50
) -> List[NodeOut]:
    """List nodes with optional filtering."""
    with get_session() as session:
        query = session.query(Node)
        
        if language:
            query = query.filter(Node.language == language)
        if stack:
            query = query.filter(Node.stack == stack)
        if node_type:
            query = query.filter(Node.node_type == node_type)
        
        nodes = query.limit(limit).all()
        return [NodeOut.from_orm(node) for node in nodes]


def link_nodes(relation_data: RelationIn) -> RelationOut:
    """Create a relation between two nodes."""
    with get_session() as session:
        relation = Relation(**relation_data.dict())
        session.add(relation)
        session.commit()
        session.refresh(relation)
        return RelationOut.from_orm(relation)


def search_nodes(query: SearchQuery) -> List[NodeOut]:
    """Search nodes by content and metadata."""
    with get_session() as session:
        search_terms = query.query.lower().split()
        
        # Build search conditions
        conditions = []
        for term in search_terms:
            conditions.append(
                or_(
                    Node.title.ilike(f"%{term}%"),
                    Node.content.ilike(f"%{term}%"),
                    Node.tags.contains([term])
                )
            )
        
        db_query = session.query(Node).filter(and_(*conditions))
        
        # Apply filters
        if query.language:
            db_query = db_query.filter(Node.language == query.language)
        if query.stack:
            db_query = db_query.filter(Node.stack == query.stack)
        if query.node_type:
            db_query = db_query.filter(Node.node_type == query.node_type)
        
        nodes = db_query.limit(query.limit).all()
        return [NodeOut.from_orm(node) for node in nodes]


def save_snapshot(file_path: Path, format: str = "json") -> None:
    """Save database snapshot to file."""
    with get_session() as session:
        # Get all nodes and relations
        nodes = session.query(Node).all()
        relations = session.query(Relation).all()
        
        snapshot_data = {
            "nodes": [node.__dict__ for node in nodes],
            "relations": [rel.__dict__ for rel in relations],
            "metadata": {
                "node_count": len(nodes),
                "relation_count": len(relations),
                "exported_at": str(Path().cwd())
            }
        }
        
        # Remove SQLAlchemy internal attributes
        for node in snapshot_data["nodes"]:
            node.pop("_sa_instance_state", None)
        for rel in snapshot_data["relations"]:
            rel.pop("_sa_instance_state", None)
        
        if format == "json":
            with open(file_path, "w") as f:
                json.dump(snapshot_data, f, indent=2, default=str)
        else:  # jsonl
            with open(file_path, "w") as f:
                for node in snapshot_data["nodes"]:
                    f.write(json.dumps({"type": "node", "data": node}) + "\n")
                for rel in snapshot_data["relations"]:
                    f.write(json.dumps({"type": "relation", "data": rel}) + "\n")


def load_snapshot(file_path: Path, clear_existing: bool = False) -> None:
    """Load database snapshot from file."""
    with get_session() as session:
        if clear_existing:
            session.query(Relation).delete()
            session.query(Node).delete()
            session.commit()
        
        with open(file_path, "r") as f:
            snapshot_data = json.load(f)
        
        # Load nodes first
        for node_data in snapshot_data["nodes"]:
            node = Node(**node_data)
            session.add(node)
        session.commit()
        
        # Then load relations
        for rel_data in snapshot_data["relations"]:
            relation = Relation(**rel_data)
            session.add(relation)
        session.commit()
