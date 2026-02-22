"""Database CRUD operation tests."""

import pytest
from sqlalchemy.orm import Session

from db.engine import get_session
from db.models import Node, Relation
from db.schema import NodeIn, RelationIn
from db.api import upsert_node, list_nodes, link_nodes, search_nodes


class TestNodeCRUD:
    """Test node CRUD operations."""
    
    def test_create_node(self):
        """Test creating a new node."""
        node_data = NodeIn(
            title="Test Function",
            content="This is a test function for demonstration.",
            node_type="syntax",
            language="python",
            tags=["function", "test", "python"]
        )
        
        node = upsert_node(node_data)
        
        assert node.id is not None
        assert node.title == "Test Function"
        assert node.language == "python"
        assert node.node_type == "syntax"
        assert "function" in node.tags
    
    def test_update_node(self):
        """Test updating an existing node."""
        # Create initial node
        node_data = NodeIn(
            title="Original Title",
            content="Original content",
            node_type="concept",
            language="python"
        )
        
        node = upsert_node(node_data)
        original_id = node.id
        
        # Update the node
        updated_data = NodeIn(
            title="Updated Title",
            content="Updated content",
            node_type="syntax",
            language="python"
        )
        
        updated_node = upsert_node(updated_data)
        
        assert updated_node.id == original_id
        assert updated_node.title == "Updated Title"
        assert updated_node.content == "Updated content"
        assert updated_node.node_type == "syntax"
    
    def test_list_nodes_with_filters(self):
        """Test listing nodes with various filters."""
        # Create test nodes
        node1 = upsert_node(NodeIn(
            title="Python Function",
            content="Python function example",
            node_type="syntax",
            language="python"
        ))
        
        node2 = upsert_node(NodeIn(
            title="JavaScript Function",
            content="JavaScript function example",
            node_type="syntax",
            language="javascript"
        ))
        
        # Test filtering by language
        python_nodes = list_nodes(language="python")
        assert len(python_nodes) >= 1
        assert all(node.language == "python" for node in python_nodes)
        
        # Test filtering by node type
        syntax_nodes = list_nodes(node_type="syntax")
        assert len(syntax_nodes) >= 2
        assert all(node.node_type == "syntax" for node in syntax_nodes)
    
    def test_search_nodes(self):
        """Test searching nodes by content."""
        # Create a node with specific content
        node_data = NodeIn(
            title="Async Function",
            content="An async function is a function that can be awaited.",
            node_type="syntax",
            language="javascript",
            tags=["async", "function", "await"]
        )
        
        upsert_node(node_data)
        
        # Search for "async"
        results = search_nodes(SearchQuery(query="async"))
        assert len(results) >= 1
        assert any("async" in node.content.lower() for node in results)
        
        # Search for "function"
        results = search_nodes(SearchQuery(query="function"))
        assert len(results) >= 1
        assert any("function" in node.content.lower() for node in results)


class TestRelationCRUD:
    """Test relation CRUD operations."""
    
    def test_create_relation(self):
        """Test creating a relation between nodes."""
        # Create two nodes
        node1 = upsert_node(NodeIn(
            title="Function",
            content="A function definition",
            node_type="syntax",
            language="python"
        ))
        
        node2 = upsert_node(NodeIn(
            title="Call",
            content="A function call",
            node_type="syntax",
            language="python"
        ))
        
        # Create relation
        relation_data = RelationIn(
            source_id=node1.id,
            target_id=node2.id,
            relation_type="calls",
            weight=1
        )
        
        relation = link_nodes(relation_data)
        
        assert relation.id is not None
        assert relation.source_id == node1.id
        assert relation.target_id == node2.id
        assert relation.relation_type == "calls"
        assert relation.weight == 1
    
    def test_relation_constraints(self):
        """Test relation constraints and validation."""
        # Try to create relation with non-existent nodes
        relation_data = RelationIn(
            source_id=99999,
            target_id=99998,
            relation_type="test",
            weight=1
        )
        
        # This should raise an exception due to foreign key constraint
        with pytest.raises(Exception):
            link_nodes(relation_data)


class TestDatabaseConstraints:
    """Test database constraints and validation."""
    
    def test_required_fields(self):
        """Test that required fields are enforced."""
        # Try to create node without title
        with pytest.raises(Exception):
            node_data = NodeIn(
                title="",  # Empty title
                content="Some content",
                node_type="syntax",
                language="python"
            )
            upsert_node(node_data)
        
        # Try to create node without content
        with pytest.raises(Exception):
            node_data = NodeIn(
                title="Valid Title",
                content="",  # Empty content
                node_type="syntax",
                language="python"
            )
            upsert_node(node_data)
    
    def test_unique_constraints(self):
        """Test unique constraints if any."""
        # This would depend on your specific unique constraints
        pass
