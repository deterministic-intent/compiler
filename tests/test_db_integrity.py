"""Database integrity tests."""

import pytest
from sqlalchemy.orm import Session

from db.engine import get_session
from db.models import Node, Relation
from db.schema import NodeIn, RelationIn
from db.api import upsert_node, link_nodes
from db.validate import validate_database, check_orphan_nodes, check_cyclic_relations, check_required_fields


class TestDatabaseIntegrity:
    """Test database integrity and validation."""
    
    def test_orphan_node_detection(self):
        """Test detection of orphan nodes."""
        # Create a node with no relations
        orphan_node = upsert_node(NodeIn(
            title="Orphan Node",
            content="This node has no relations",
            node_type="concept",
            language="python"
        ))
        
        # Check for orphan nodes
        orphans = check_orphan_nodes()
        
        # Should find our orphan node
        orphan_ids = [orphan["id"] for orphan in orphans]
        assert orphan_node.id in orphan_ids
    
    def test_cyclic_relation_detection(self):
        """Test detection of cyclic relations."""
        # Create two nodes
        node1 = upsert_node(NodeIn(
            title="Node 1",
            content="First node",
            node_type="syntax",
            language="python"
        ))
        
        node2 = upsert_node(NodeIn(
            title="Node 2",
            content="Second node",
            node_type="syntax",
            language="python"
        ))
        
        # Create a self-reference (cycle)
        self_relation = link_nodes(RelationIn(
            source_id=node1.id,
            target_id=node1.id,
            relation_type="self_reference",
            weight=1
        ))
        
        # Check for cycles
        cycles = check_cyclic_relations()
        
        # Should find our self-reference
        cycle_node_ids = [cycle["node_id"] for cycle in cycles]
        assert node1.id in cycle_node_ids
    
    def test_required_fields_validation(self):
        """Test validation of required fields."""
        # Create a valid node first
        valid_node = upsert_node(NodeIn(
            title="Valid Node",
            content="Valid content",
            node_type="syntax",
            language="python"
        ))
        
        # Check required fields
        invalid_nodes = check_required_fields()
        
        # Should not find any invalid nodes
        invalid_node_ids = [node["id"] for node in invalid_nodes]
        assert valid_node.id not in invalid_node_ids
    
    def test_invalid_node_type_detection(self):
        """Test detection of invalid node types."""
        # This test would require direct database access to insert invalid data
        # For now, we'll test the validation function with valid data
        validation_result = validate_database()
        
        # Should return a dictionary with validation results
        assert isinstance(validation_result, dict)
        assert "orphan_nodes" in validation_result
        assert "cyclic_relations" in validation_result
        assert "invalid_nodes" in validation_result
    
    def test_relation_integrity(self):
        """Test relation integrity constraints."""
        # Create two nodes
        node1 = upsert_node(NodeIn(
            title="Source Node",
            content="Source node content",
            node_type="syntax",
            language="python"
        ))
        
        node2 = upsert_node(NodeIn(
            title="Target Node",
            content="Target node content",
            node_type="syntax",
            language="python"
        ))
        
        # Create a valid relation
        relation = link_nodes(RelationIn(
            source_id=node1.id,
            target_id=node2.id,
            relation_type="references",
            weight=1
        ))
        
        # Verify the relation was created
        assert relation.id is not None
        assert relation.source_id == node1.id
        assert relation.target_id == node2.id
    
    def test_cascade_operations(self):
        """Test cascade operations when nodes are deleted."""
        # Create a node with relations
        node1 = upsert_node(NodeIn(
            title="Parent Node",
            content="Parent content",
            node_type="syntax",
            language="python"
        ))
        
        node2 = upsert_node(NodeIn(
            title="Child Node",
            content="Child content",
            node_type="syntax",
            language="python"
        ))
        
        # Create relation
        relation = link_nodes(RelationIn(
            source_id=node1.id,
            target_id=node2.id,
            relation_type="contains",
            weight=1
        ))
        
        # Test that relation exists
        assert relation.id is not None
        
        # Note: Testing actual deletion would require additional setup
        # This is a placeholder for cascade delete testing


class TestDataConsistency:
    """Test data consistency across the database."""
    
    def test_node_relation_consistency(self):
        """Test consistency between nodes and relations."""
        # Create nodes
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
        relation = link_nodes(RelationIn(
            source_id=node1.id,
            target_id=node2.id,
            relation_type="calls",
            weight=1
        ))
        
        # Verify both nodes exist and relation is valid
        assert node1.id is not None
        assert node2.id is not None
        assert relation.source_id == node1.id
        assert relation.target_id == node2.id
    
    def test_tag_consistency(self):
        """Test consistency of tags across nodes."""
        # Create nodes with consistent tags
        node1 = upsert_node(NodeIn(
            title="Python Function",
            content="Python function example",
            node_type="syntax",
            language="python",
            tags=["python", "function", "syntax"]
        ))
        
        node2 = upsert_node(NodeIn(
            title="JavaScript Function",
            content="JavaScript function example",
            node_type="syntax",
            language="javascript",
            tags=["javascript", "function", "syntax"]
        ))
        
        # Verify tags are consistent
        assert "function" in node1.tags
        assert "function" in node2.tags
        assert "syntax" in node1.tags
        assert "syntax" in node2.tags
        assert node1.language in node1.tags
        assert node2.language in node2.tags
