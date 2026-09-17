"""ORM models. File contents are never stored; see ingest/filesource.py."""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TagStatus(enum.StrEnum):
    NONE = "none"        # no graph, nothing scheduled
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class JobStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


def _enum_column(kind: type[enum.StrEnum], default: enum.StrEnum):
    # stored as its string value (not the member name), portable across sqlite and Postgres
    return mapped_column(Enum(kind, native_enum=False, length=16, values_callable=lambda e: [m.value for m in e]), default=default)


class Repo(Base):
    __tablename__ = "repos"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(512), unique=True)
    owner: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(128))
    default_branch: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    tags: Mapped[list["Tag"]] = relationship(
        back_populates="repo", cascade="all, delete-orphan", order_by="Tag.order_index"
    )

    @property
    def slug(self) -> str:
        return f"{self.owner}_{self.name}"


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("repo_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(256))
    commit_sha: Mapped[str] = mapped_column(String(64))
    tagged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer)  # 0 = oldest
    status: Mapped[TagStatus] = _enum_column(TagStatus, TagStatus.NONE)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    repo: Mapped[Repo] = relationship(back_populates="tags")
    graph: Mapped["Graph | None"] = relationship(
        back_populates="tag", uselist=False, cascade="all, delete-orphan"
    )
    files: Mapped[list["File"]] = relationship(back_populates="tag", cascade="all, delete-orphan")


class Graph(Base):
    __tablename__ = "graphs"

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"))
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), unique=True)
    tier1: Mapped[dict] = mapped_column(JSON)
    tier2: Mapped[dict] = mapped_column(JSON)
    tier3: Mapped[dict] = mapped_column(JSON)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)  # written overview, generated on demand
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    tag: Mapped[Tag] = relationship(back_populates="graph")


class File(Base):
    """Path inventory for a tag. No content."""

    __tablename__ = "files"
    __table_args__ = (UniqueConstraint("repo_id", "tag_id", "path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"))
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(String(1024))
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    size: Mapped[int] = mapped_column(Integer)
    blob_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)  # lets a later tag reuse unchanged work

    tag: Mapped[Tag] = relationship(back_populates="files")


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"))
    tag_id: Mapped[int | None] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), nullable=True)
    status: Mapped[JobStatus] = _enum_column(JobStatus, JobStatus.QUEUED)
    step: Mapped[str] = mapped_column(String(64), default="queued")
    progress: Mapped[float] = mapped_column(default=0.0)  # 0..1
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # resumable progress, see llm/generate.py
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChangeSummary(Base):
    """LLM narrative for one tag transition (earlier -> later). Generated on demand and cached."""

    __tablename__ = "change_summaries"
    __table_args__ = (UniqueConstraint("from_tag_id", "to_tag_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"))
    from_tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"))
    to_tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"))
    summary: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(64))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
