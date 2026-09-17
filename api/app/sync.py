"""Copy generated data from one database to another (typically local sqlite -> Vercel Postgres).

Rows are matched on natural keys (repo url, tag name, file path, summary tag pair), never on
ids, so it is safe to re-run: existing graphs/inventories on the target are replaced tag by
tag. Generation jobs are not copied.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from .db import init_db, make_engine
from .models import ChangeSummary, File, Graph, Repo, Tag, TagStatus

log = logging.getLogger(__name__)


@dataclass
class SyncReport:
    repos: int = 0
    tags: int = 0
    graphs: int = 0
    files: int = 0
    summaries: int = 0
    skipped: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        s = f"repos={self.repos} tags={self.tags} graphs={self.graphs} inventory_rows={self.files} summaries={self.summaries}"
        if self.skipped:
            s += f" skipped={len(self.skipped)}"
        return s


def _upsert_repo(dst: Session, src_repo: Repo) -> Repo:
    repo = dst.scalar(select(Repo).where(Repo.url == src_repo.url))
    if repo is None:
        repo = Repo(url=src_repo.url, owner=src_repo.owner, name=src_repo.name, default_branch=src_repo.default_branch, created_at=src_repo.created_at)
        dst.add(repo)
        dst.flush()
    else:
        repo.default_branch = src_repo.default_branch
    return repo


def _upsert_tag(dst: Session, repo: Repo, src_tag: Tag) -> Tag:
    tag = dst.scalar(select(Tag).where(Tag.repo_id == repo.id, Tag.name == src_tag.name))
    # in-flight states are meaningless on another database
    status = src_tag.status if src_tag.status in {TagStatus.DONE, TagStatus.FAILED} else TagStatus.NONE
    if tag is None:
        tag = Tag(repo_id=repo.id, name=src_tag.name, commit_sha=src_tag.commit_sha, tagged_at=src_tag.tagged_at, order_index=src_tag.order_index, status=status, error=src_tag.error)
        dst.add(tag)
        dst.flush()
    else:
        tag.commit_sha, tag.tagged_at, tag.order_index = src_tag.commit_sha, src_tag.tagged_at, src_tag.order_index
        if src_tag.graph is not None or tag.graph is None:
            tag.status, tag.error = status, src_tag.error
    return tag


def sync(source_url: str, target_url: str, repo_filter: str | None = None, dry_run: bool = False, graphs_only: bool = False) -> SyncReport:
    """repo_filter: "owner/name" to limit to one repo. graphs_only: skip tags without a graph."""
    src_engine, dst_engine = make_engine(source_url), make_engine(target_url)
    init_db(dst_engine)
    SrcSession, DstSession = sessionmaker(bind=src_engine), sessionmaker(bind=dst_engine)
    report = SyncReport()

    with SrcSession() as src, DstSession() as dst:
        repos = src.scalars(select(Repo).order_by(Repo.id)).all()
        if repo_filter:
            repos = [r for r in repos if f"{r.owner}/{r.name}" == repo_filter]
            if not repos:
                raise ValueError(f"no local repo matches {repo_filter!r}")
        for src_repo in repos:
            log.info("repo %s/%s: %d tags, %d generated", src_repo.owner, src_repo.name, len(src_repo.tags), sum(1 for t in src_repo.tags if t.graph))
            report.repos += 1
            if dry_run:
                report.tags += len(src_repo.tags)
                report.graphs += sum(1 for t in src_repo.tags if t.graph)
                continue
            repo = _upsert_repo(dst, src_repo)
            tag_ids: dict[str, int] = {}
            for src_tag in src_repo.tags:
                if graphs_only and src_tag.graph is None:
                    continue
                tag = _upsert_tag(dst, repo, src_tag)
                tag_ids[src_tag.name] = tag.id
                report.tags += 1
                g = src_tag.graph
                if g is None:
                    continue
                # replace the graph and inventory for this tag
                dst.execute(delete(Graph).where(Graph.tag_id == tag.id))
                dst.execute(delete(File).where(File.tag_id == tag.id))
                dst.add(Graph(repo_id=repo.id, tag_id=tag.id, tier1=g.tier1, tier2=g.tier2, tier3=g.tier3, change_summary=g.change_summary, overview=g.overview, model=g.model, prompt_version=g.prompt_version, generated_at=g.generated_at))
                dst.add_all([File(repo_id=repo.id, tag_id=tag.id, path=f.path, language=f.language, size=f.size, blob_sha=f.blob_sha) for f in src_tag.files])
                report.graphs += 1
                report.files += len(src_tag.files)
            # change summaries for tag pairs that exist on the target
            src_tag_by_id = {t.id: t for t in src_repo.tags}
            for cs in src.scalars(select(ChangeSummary).where(ChangeSummary.repo_id == src_repo.id)).all():
                a, b = src_tag_by_id.get(cs.from_tag_id), src_tag_by_id.get(cs.to_tag_id)
                if a is None or b is None or a.name not in tag_ids or b.name not in tag_ids:
                    report.skipped.append(f"summary {a.name if a else '?'}->{b.name if b else '?'}")
                    continue
                existing = dst.scalar(select(ChangeSummary).where(ChangeSummary.from_tag_id == tag_ids[a.name], ChangeSummary.to_tag_id == tag_ids[b.name]))
                if existing:
                    existing.summary, existing.model, existing.generated_at = cs.summary, cs.model, cs.generated_at
                else:
                    dst.add(ChangeSummary(repo_id=repo.id, from_tag_id=tag_ids[a.name], to_tag_id=tag_ids[b.name], summary=cs.summary, model=cs.model, generated_at=cs.generated_at))
                report.summaries += 1
            dst.commit()
    return report
