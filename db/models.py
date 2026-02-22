"""SQLAlchemy models for the dev knowledge base."""

import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Index, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class NodeType(enum.Enum):
    """Types of knowledge nodes."""
    CONCEPT = "concept"
    SYNTAX = "syntax"
    API = "api"
    PATTERN = "pattern"
    EXAMPLE = "example"
    CAPABILITY = "capability"


class RelationType(enum.Enum):
    """Types of relations between nodes."""
    CONTAINS = "contains"
    REFERENCES = "references"
    DEFINES = "defines"
    EXAMPLE_OF = "example_of"
    VERSION_OF = "version_of"


class Node(Base):
    """Knowledge node representing a piece of documentation or code."""
    __tablename__ = "nodes"
    
    id = Column(Integer, primary_key=True)
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    node_type = Column(String(50), nullable=False)
    language = Column(String(50))
    stack = Column(String(100))
    tags = Column(JSON, default=list)
    lang_hints = Column(JSON, default=list)  # Append-only: list of language IDs
    lang_sources = Column(JSON, default=list)  # Append-only: list of source types
    source_url = Column(String(1000))
    source_title = Column(String(500))
    unit_hash = Column(String(64))  # SHA256 of normalized content
    version = Column(String(50))  # Version info
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    source_relations = relationship("Relation", foreign_keys="Relation.source_id", back_populates="source")
    target_relations = relationship("Relation", foreign_keys="Relation.target_id", back_populates="target")
    events = relationship("Event", back_populates="node")


class Relation(Base):
    """Relation between two nodes."""
    __tablename__ = "relations"
    
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("nodes.id"), nullable=False)
    target_id = Column(Integer, ForeignKey("nodes.id"), nullable=False)
    relation_type = Column(String(100), nullable=False)
    weight = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    source = relationship("Node", foreign_keys=[source_id], back_populates="source_relations")
    target = relationship("Node", foreign_keys=[target_id], back_populates="target_relations")


class SnapshotMeta(Base):
    """Metadata for database snapshots."""
    __tablename__ = "snapshot_meta"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, unique=True)
    description = Column(Text)
    node_count = Column(Integer, default=0)
    relation_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class Blob(Base):
    """Content-addressed storage for raw fetched content."""
    __tablename__ = "blobs"
    
    blob_key = Column(String(64), primary_key=True)  # SHA256 of content
    bytes = Column(Text, nullable=False)  # Raw content
    etag = Column(String(200))
    last_modified = Column(String(200))
    status_code = Column(Integer)
    fetched_at = Column(DateTime, default=datetime.utcnow)
    
    # Index for efficient lookups
    __table_args__ = (
        Index('idx_blob_etag', 'etag'),
        Index('idx_blob_fetched', 'fetched_at'),
    )


class DocUnit(Base):
    """Normalized document units (pages/sections)."""
    __tablename__ = "doc_units"
    
    doc_key = Column(String(64), primary_key=True)  # SHA256 of URL
    source_id = Column(String(100), nullable=False)
    url = Column(String(1000), nullable=False)
    blob_key = Column(String(64), ForeignKey("blobs.blob_key"), nullable=False)
    unit_hash = Column(String(64), nullable=False)  # SHA256 of parsed content
    parsed_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    blob = relationship("Blob")
    
    # Indexes
    __table_args__ = (
        Index('idx_docunit_source', 'source_id'),
        Index('idx_docunit_hash', 'unit_hash'),
        Index('idx_docunit_parsed', 'parsed_at'),
    )


class Event(Base):
    """Timeline events for nodes."""
    __tablename__ = "events"
    
    id = Column(Integer, primary_key=True)
    node_id = Column(Integer, ForeignKey("nodes.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    kind = Column(String(50), nullable=False)  # 'fetched', 'parsed', 'changed'
    event_data = Column(JSON, default=dict)  # Renamed from metadata to avoid SQLAlchemy conflict
    
    # Relationships
    node = relationship("Node", back_populates="events")
    
    # Indexes
    __table_args__ = (
        Index('idx_event_node_time', 'node_id', 'timestamp'),
        Index('idx_event_kind', 'kind'),
    )
