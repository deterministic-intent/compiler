#!/usr/bin/env python3
"""Initialize database tables and seed minimal data."""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from db.engine import get_engine
from db.models import Base
from db.seed import seed_minimal_data


def main():
    """Create tables and seed minimal data."""
    engine = get_engine()
    
    print("Creating database tables...")
    Base.metadata.create_all(engine)
    
    print("Seeding minimal data...")
    seed_minimal_data()
    
    print("Database initialization complete!")


if __name__ == "__main__":
    main()
