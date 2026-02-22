"""Pydantic models for API input/output validation."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class NodeIn(BaseModel):
    """Input model for creating/updating nodes."""
    title: str = Field(..., max_length=500)
    content: str
    node_type: str = Field(..., max_length=50)
    language: Optional[str] = Field(None, max_length=50)
    stack: Optional[str] = Field(None, max_length=100)
    tags: List[str] = Field(default_factory=list)
    source_url: Optional[str] = Field(None, max_length=1000)
    source_title: Optional[str] = Field(None, max_length=500)
    lang_hints: List[str] = Field(default_factory=list)  # Append-only: language IDs
    lang_sources: List[str] = Field(default_factory=list)  # Append-only: source types


class NodeOut(BaseModel):
    """Output model for nodes."""
    id: int
    title: str
    content: str
    node_type: str
    language: Optional[str]
    stack: Optional[str]
    tags: List[str]
    url: Optional[str] = Field(None, alias="source_url")  # Alias for backward compatibility
    source_url: Optional[str]
    lang_hints: List[str] = Field(default_factory=list)
    lang_sources: List[str] = Field(default_factory=list)
    source_title: Optional[str]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class RelationIn(BaseModel):
    """Input model for creating relations."""
    source_id: int
    target_id: int
    relation_type: str = Field(..., max_length=100)
    weight: int = Field(default=1, ge=1, le=10)


class RelationOut(BaseModel):
    """Output model for relations."""
    id: int
    source_id: int
    target_id: int
    relation_type: str
    weight: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class SearchQuery(BaseModel):
    """Search query model."""
    query: str
    language: Optional[str] = None
    stack: Optional[str] = None
    node_type: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=100)
