"""SQLAlchemy engine/session shared by the app, the generator and the CLI."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import Config


class Base(DeclarativeBase):
    pass


def _normalize_url(url: str) -> str:
    # Vercel/Neon hand out postgres:// or postgresql://; SQLAlchemy + psycopg3 wants postgresql+psycopg://
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def make_engine(url: str | None = None):
    url = _normalize_url(url or Config.DATABASE_URL)
    if url.startswith("sqlite"):
        db_path = url.replace("sqlite:///", "", 1)
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=3)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db(target_engine=None) -> None:
    from . import models  # noqa: F401  (register tables)

    eng = target_engine or engine
    Base.metadata.create_all(eng)
    # demo-grade forward migration: add columns introduced after a table already existed
    from sqlalchemy import inspect, text

    insp = inspect(eng)
    for table, column, ddl_type in (("generation_jobs", "state", "JSON"), ("graphs", "overview", "TEXT"), ("files", "blob_sha", "VARCHAR(64)")):
        if column not in {c["name"] for c in insp.get_columns(table)}:
            with eng.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))


@contextmanager
def session_scope(factory: sessionmaker | None = None) -> Iterator[Session]:
    session = (factory or SessionLocal)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
