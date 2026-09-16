from __future__ import annotations

import re

from flask import Blueprint, abort, jsonify, request
from sqlalchemy import select

from ..config import Config
from ..db import session_scope
from ..ingest.git import GitError, parse_github_url
from ..llm import runner
from ..models import Repo, Tag

bp = Blueprint("repos", __name__)


def _tag_dict(t: Tag) -> dict:
    return {
        "name": t.name,
        "sha": t.commit_sha,
        "tagged_at": t.tagged_at.isoformat() if t.tagged_at else None,
        "order_index": t.order_index,
        "status": t.status,
        "has_graph": t.graph is not None,
        "error": t.error,
    }


def _repo_dict(r: Repo, with_tags: bool = True) -> dict:
    d = {"id": r.id, "url": r.url, "owner": r.owner, "name": r.name, "default_branch": r.default_branch}
    if with_tags:
        d["tags"] = [_tag_dict(t) for t in r.tags]
    return d


def _require_generation() -> None:
    if not Config.GENERATION_ENABLED:
        abort(403, description="generation is disabled on this deployment; run it locally and sync")


@bp.get("/repos")
def list_repos():
    with session_scope() as s:
        repos = s.scalars(select(Repo).order_by(Repo.created_at.desc())).all()
        return jsonify([_repo_dict(r, with_tags=False) | {"tag_count": len(r.tags), "generated_count": sum(1 for t in r.tags if t.graph)} for r in repos])


@bp.post("/repos")
def create_repo():
    _require_generation()
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or "").strip()
    try:
        owner, name = parse_github_url(url)
    except GitError as e:
        return jsonify({"error": str(e)}), 400
    canonical = f"https://github.com/{owner}/{name}"
    with session_scope() as s:
        repo = s.scalar(select(Repo).where(Repo.url == canonical))
        if repo is None:
            repo = Repo(url=canonical, owner=owner, name=name)
            s.add(repo)
            s.flush()
        repo_id = repo.id
    pattern = (body.get("tag_pattern") or "").strip() or None
    if pattern:
        try:
            re.compile(pattern)
        except re.error as e:
            return jsonify({"error": f"bad tag_pattern: {e}"}), 400
    job_id = runner.enqueue_repo_load(repo_id, n_tags=int(body.get("tags") or Config.TAGS_ON_LOAD), tag_pattern=pattern)
    return jsonify({"repo_id": repo_id, "job_id": job_id}), 202


@bp.get("/repos/<int:repo_id>")
def get_repo(repo_id: int):
    with session_scope() as s:
        repo = s.get(Repo, repo_id)
        if repo is None:
            abort(404)
        return jsonify(_repo_dict(repo))


@bp.post("/repos/<int:repo_id>/tags/<path:tag_name>/generate")
def generate_tag(repo_id: int, tag_name: str):
    _require_generation()
    with session_scope() as s:
        tag = s.scalar(select(Tag).where(Tag.repo_id == repo_id, Tag.name == tag_name))
        if tag is None:
            abort(404)
        if tag.status in {"queued", "running"}:
            return jsonify({"error": "already in progress"}), 409
        tag_id = tag.id
    job_id = runner.enqueue_tag(repo_id, tag_id)
    return jsonify({"job_id": job_id}), 202
