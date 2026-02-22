#!/usr/bin/env python3
"""Graph API for presentation layer (Hierarchy/Graph/Timeline)."""

import json
from datetime import datetime
from typing import Dict, Any, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc

from .engine import get_session
from .models import Node, Relation, Event, DocUnit


class GraphAPI:
    """API for graph-based queries and presentation."""
    
    def get_node_hierarchy(self, node_id: Optional[int] = None, source_id: Optional[str] = None) -> Dict[str, Any]:
        """Get hierarchical view of nodes (source → page → section)."""
        with get_session() as session:
            if node_id:
                # Get specific node and its children
                node = session.query(Node).filter(Node.id == node_id).first()
                if not node:
                    return {"error": "Node not found"}
                
                children = session.query(Node).join(Relation, Node.id == Relation.target_id).filter(
                    Relation.source_id == node_id,
                    Relation.relation_type == 'contains'
                ).all()
                
                return {
                    "node": self._node_to_dict(node),
                    "children": [self._node_to_dict(child) for child in children],
                    "type": "hierarchy"
                }
            elif source_id:
                # Get all nodes for a source, organized by hierarchy
                nodes = session.query(Node).filter(Node.source_url.like(f"%{source_id}%")).all()
                
                # Group by document/page
                pages = {}
                for node in nodes:
                    page_key = self._extract_page_key(node.source_url)
                    if page_key not in pages:
                        pages[page_key] = []
                    pages[page_key].append(self._node_to_dict(node))
                
                return {
                    "source_id": source_id,
                    "pages": pages,
                    "type": "hierarchy"
                }
            else:
                # Get top-level sources
                sources = session.query(Node.source_url).distinct().all()
                return {
                    "sources": [url[0] for url in sources if url[0]],
                    "type": "hierarchy"
                }
    
    def get_node_graph(self, node_id: int, depth: int = 2) -> Dict[str, Any]:
        """Get graph view around a specific node."""
        with get_session() as session:
            node = session.query(Node).filter(Node.id == node_id).first()
            if not node:
                return {"error": "Node not found"}
            
            # Get connected nodes within depth
            nodes = {node_id: node}
            edges = []
            
            # BFS to find connected nodes
            queue = [(node_id, 0)]
            visited = {node_id}
            
            while queue:
                current_id, current_depth = queue.pop(0)
                
                if current_depth >= depth:
                    continue
                
                # Get outgoing relations
                outgoing = session.query(Relation).filter(Relation.source_id == current_id).all()
                for rel in outgoing:
                    if rel.target_id not in visited:
                        target_node = session.query(Node).filter(Node.id == rel.target_id).first()
                        if target_node:
                            nodes[rel.target_id] = target_node
                            visited.add(rel.target_id)
                            queue.append((rel.target_id, current_depth + 1))
                    
                    edges.append({
                        "source": current_id,
                        "target": rel.target_id,
                        "type": rel.relation_type,
                        "weight": rel.weight
                    })
                
                # Get incoming relations
                incoming = session.query(Relation).filter(Relation.target_id == current_id).all()
                for rel in incoming:
                    if rel.source_id not in visited:
                        source_node = session.query(Node).filter(Node.id == rel.source_id).first()
                        if source_node:
                            nodes[rel.source_id] = source_node
                            visited.add(rel.source_id)
                            queue.append((rel.source_id, current_depth + 1))
                    
                    edges.append({
                        "source": rel.source_id,
                        "target": current_id,
                        "type": rel.relation_type,
                        "weight": rel.weight
                    })
            
            return {
                "nodes": [self._node_to_dict(n) for n in nodes.values()],
                "edges": edges,
                "type": "graph"
            }
    
    def get_node_timeline(self, node_id: int) -> Dict[str, Any]:
        """Get timeline view for a specific node."""
        with get_session() as session:
            node = session.query(Node).filter(Node.id == node_id).first()
            if not node:
                return {"error": "Node not found"}
            
            events = session.query(Event).filter(Event.node_id == node_id).order_by(Event.timestamp).all()
            
            return {
                "node": self._node_to_dict(node),
                "events": [
                    {
                        "timestamp": event.timestamp.isoformat(),
                        "kind": event.kind,
                        "metadata": json.loads(event.event_data) if event.event_data else {}
                    }
                    for event in events
                ],
                "type": "timeline"
            }
    
    def get_source_timeline(self, source_id: str) -> Dict[str, Any]:
        """Get timeline view for all nodes in a source."""
        with get_session() as session:
            # Get all nodes for the source
            nodes = session.query(Node).filter(Node.source_url.like(f"%{source_id}%")).all()
            
            # Get all events for these nodes
            node_ids = [node.id for node in nodes]
            events = session.query(Event).filter(Event.node_id.in_(node_ids)).order_by(Event.timestamp).all()
            
            # Group events by date
            timeline = {}
            for event in events:
                date_key = event.timestamp.date().isoformat()
                if date_key not in timeline:
                    timeline[date_key] = []
                
                timeline[date_key].append({
                    "node_id": event.node_id,
                    "timestamp": event.timestamp.isoformat(),
                    "kind": event.kind,
                    "metadata": json.loads(event.event_data) if event.event_data else {}
                })
            
            return {
                "source_id": source_id,
                "timeline": timeline,
                "type": "timeline"
            }
    
    def search_nodes_graph(self, query: str, limit: int = 20) -> Dict[str, Any]:
        """Search nodes and return graph view of results."""
        with get_session() as session:
            # Search nodes
            search_terms = query.lower().split()
            conditions = []
            for term in search_terms:
                conditions.append(
                    or_(
                        Node.title.ilike(f"%{term}%"),
                        Node.content.ilike(f"%{term}%"),
                        Node.tags.contains([term])
                    )
                )
            
            nodes = session.query(Node).filter(and_(*conditions)).limit(limit).all()
            
            # Get relations between found nodes
            node_ids = [node.id for node in nodes]
            relations = session.query(Relation).filter(
                and_(
                    Relation.source_id.in_(node_ids),
                    Relation.target_id.in_(node_ids)
                )
            ).all()
            
            return {
                "query": query,
                "nodes": [self._node_to_dict(node) for node in nodes],
                "edges": [
                    {
                        "source": rel.source_id,
                        "target": rel.target_id,
                        "type": rel.relation_type,
                        "weight": rel.weight
                    }
                    for rel in relations
                ],
                "type": "search_graph"
            }
    
    def get_api_surface(self, module: str) -> Dict[str, Any]:
        """Get API surface for a specific module."""
        with get_session() as session:
            # Find API nodes for the module
            api_nodes = session.query(Node).filter(
                and_(
                    Node.node_type == 'api',
                    or_(
                        Node.title.ilike(f"%{module}%"),
                        Node.content.ilike(f"%{module}%")
                    )
                )
            ).all()
            
            # Extract API symbols
            symbols = []
            for node in api_nodes:
                # Parse API information from content
                api_info = self._extract_api_info(node.content, node.title)
                if api_info:
                    symbols.append({
                        "symbol_id": f"{module}.{api_info['name']}",
                        "module": module,
                        "kind": api_info['kind'],
                        "signature": api_info.get('signature', ''),
                        "since": api_info.get('since', 'unknown'),
                        "provenance": node.source_url
                    })
            
            return {
                "module": module,
                "symbols": symbols,
                "count": len(symbols)
            }
    
    def _node_to_dict(self, node: Node) -> Dict[str, Any]:
        """Convert node to dictionary for JSON serialization."""
        return {
            "id": node.id,
            "title": node.title,
            "node_type": node.node_type,
            "language": node.language,
            "stack": node.stack,
            "tags": node.tags,
            "source_url": node.source_url,
            "source_title": node.source_title,
            "unit_hash": node.unit_hash,
            "version": node.version,
            "created_at": node.created_at.isoformat() if node.created_at else None,
            "updated_at": node.updated_at.isoformat() if node.updated_at else None
        }
    
    def _extract_page_key(self, url: str) -> str:
        """Extract page key from URL."""
        if not url:
            return "unknown"
        
        # Extract domain and path
        parts = url.split('/')
        if len(parts) >= 3:
            return f"{parts[2]}/{parts[3]}" if len(parts) > 3 else parts[2]
        return url
    
    def _extract_api_info(self, content: str, title: str) -> Optional[Dict[str, Any]]:
        """Extract API information from node content."""
        # Simple extraction - can be enhanced
        lines = content.split('\n')
        
        # Look for function/class definitions
        for line in lines:
            if 'def ' in line or 'class ' in line:
                parts = line.strip().split()
                if len(parts) >= 2:
                    kind = 'function' if parts[0] == 'def' else 'class'
                    name = parts[1].split('(')[0] if kind == 'function' else parts[1].split(':')[0]
                    
                    return {
                        "name": name,
                        "kind": kind,
                        "signature": line.strip(),
                        "since": "unknown"  # Would need more sophisticated parsing
                    }
        
        return None


# Global instance
graph_api = GraphAPI()
