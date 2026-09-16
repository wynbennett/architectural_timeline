from __future__ import annotations

from flask import Blueprint, abort, jsonify
from sqlalchemy import select

from ..db import session_scope
from ..models import Tag

bp = Blueprint("graphs", __name__)


@bp.get("/repos/<int:repo_id>/tags/<path:tag_name>/graph")
def get_graph(repo_id: int, tag_name: str):
    with session_scope() as s:
        tag = s.scalar(select(Tag).where(Tag.repo_id == repo_id, Tag.name == tag_name))
        if tag is None:
            abort(404)
        if tag.graph is None:
            return jsonify({"error": "no graph for this tag", "status": tag.status}), 404
        g = tag.graph
        return jsonify(
            {
                "tag": tag.name,
                "sha": tag.commit_sha,
                "tier1": g.tier1,
                "tier2": g.tier2,
                "tier3": g.tier3,
                "change_summary": g.change_summary,
                "model": g.model,
                "prompt_version": g.prompt_version,
                "generated_at": g.generated_at.isoformat() if g.generated_at else None,
            }
        )
