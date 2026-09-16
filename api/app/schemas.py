"""Pydantic schemas for the three graph tiers. Used for structured outputs and validation."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EdgeKind = Literal["http", "rpc", "queue", "reads", "writes", "imports", "calls"]
SystemKind = Literal["api", "service", "frontend", "worker", "datastore", "external"]


class Edge(BaseModel):
    source: str = Field(description="id of the source node in this same response")
    target: str = Field(description="id of the target node in this same response")
    kind: EdgeKind
    label: str = Field(default="", description="a few words, may be empty")


class SystemNode(BaseModel):
    id: str = Field(description="lowercase kebab-case slug, reused from the previous tag when the component still exists")
    name: str
    kind: SystemKind
    description: str = Field(description="two sentences")
    paths: list[str] = Field(description="directory prefixes or files from the inventory that implement this component")


class Tier1Graph(BaseModel):
    summary: str = Field(description="one paragraph describing the whole system")
    nodes: list[SystemNode]
    edges: list[Edge]


class ModuleNode(BaseModel):
    id: str = Field(description="lowercase kebab-case slug, reused from the previous tag when the module still exists")
    name: str
    description: str = Field(description="two sentences")
    paths: list[str] = Field(description="files or directory prefixes from the inventory belonging to this module")


class Tier2Graph(BaseModel):
    nodes: list[ModuleNode]
    edges: list[Edge]


class SnippetNode(BaseModel):
    id: str = Field(description="lowercase kebab-case slug, reused from the previous tag when the snippet still exists")
    title: str
    description: str
    file_path: str = Field(description="exact path from the files shown")
    start_line: int = Field(description="1-based inclusive")
    end_line: int = Field(description="1-based inclusive")


class Tier3Graph(BaseModel):
    nodes: list[SnippetNode]
    edges: list[Edge]


class ChangeSummary(BaseModel):
    summary: str
