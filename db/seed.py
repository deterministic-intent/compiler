"""Database seeding and initial data population."""

from .engine import get_session
from .models import Node, NodeType
from .schema import NodeIn


def seed_minimal_data():
    """Seed the database with minimal initial data."""
    with get_session() as session:
        # Check if we already have seed data
        existing_nodes = session.query(Node).count()
        if existing_nodes > 0:
            print(f"Database already has {existing_nodes} nodes, skipping seed data")
            return
        
        # Create basic node types as examples
        seed_nodes = [
            NodeIn(
                title="Programming Language",
                content="A formal language used to create computer programs and software applications.",
                node_type=NodeType.CONCEPT,
                language=None,
                stack=None,
                tags=["programming", "language", "computer-science"]
            ),
            NodeIn(
                title="Framework",
                content="A software framework that provides a foundation for developing software applications.",
                node_type=NodeType.CONCEPT,
                language=None,
                stack=None,
                tags=["framework", "software", "development"]
            ),
            NodeIn(
                title="Database",
                content="An organized collection of structured information or data, typically stored electronically.",
                node_type=NodeType.CONCEPT,
                language=None,
                stack=None,
                tags=["database", "data", "storage"]
            ),
            NodeIn(
                title="API",
                content="Application Programming Interface - a set of rules and protocols for building software applications.",
                node_type=NodeType.CONCEPT,
                language=None,
                stack=None,
                tags=["api", "interface", "protocol"]
            ),
            NodeIn(
                title="Function",
                content="A reusable block of code that performs a specific task when called.",
                node_type=NodeType.SYNTAX,
                language=None,
                stack=None,
                tags=["function", "code", "reusable"]
            ),
            NodeIn(
                title="Variable",
                content="A named storage location that can hold data values.",
                node_type=NodeType.SYNTAX,
                language=None,
                stack=None,
                tags=["variable", "data", "storage"]
            ),
            NodeIn(
                title="Class",
                content="A blueprint for creating objects that defines properties and methods.",
                node_type=NodeType.SYNTAX,
                language=None,
                stack=None,
                tags=["class", "object", "oop"]
            ),
            NodeIn(
                title="Loop",
                content="A programming construct that repeats a block of code until a condition is met.",
                node_type=NodeType.SYNTAX,
                language=None,
                stack=None,
                tags=["loop", "iteration", "control-flow"]
            ),
            NodeIn(
                title="Conditional Statement",
                content="A programming construct that executes different code based on whether a condition is true or false.",
                node_type=NodeType.SYNTAX,
                language=None,
                stack=None,
                tags=["conditional", "if", "control-flow"]
            ),
            NodeIn(
                title="Error Handling",
                content="The process of responding to and recovering from error conditions in software.",
                node_type=NodeType.CAPABILITY,
                language=None,
                stack=None,
                tags=["error", "exception", "handling"]
            )
        ]
        
        # Insert seed nodes
        for node_data in seed_nodes:
            from .api import upsert_node
            upsert_node(node_data)
        
        print(f"Seeded database with {len(seed_nodes)} initial nodes")
