from __future__ import annotations

from flask import Blueprint, abort, jsonify, request
from sqlalchemy import select

from ..config import Config
from ..db import session_scope
from ..llm.overview import write_overview
from ..models import Tag
from ..ratelimit import rate_limit_response

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
                "overview": g.overview,
                "model": g.model,
                "prompt_version": g.prompt_version,
                "generated_at": g.generated_at.isoformat() if g.generated_at else None,
            }
        )


@bp.post("/repos/<int:repo_id>/tags/<path:tag_name>/overview")
def write_overview_route(repo_id: int, tag_name: str):
    """Generate (or regenerate with {"force": true}) the written overview for a tag. One model call, cached."""
    body = request.get_json(silent=True) or {}
    with session_scope() as s:
        tag = s.scalar(select(Tag).where(Tag.repo_id == repo_id, Tag.name == tag_name))
        if tag is None or tag.graph is None:
            return jsonify({"error": "no graph for this tag"}), 404
        tag_id, cached = tag.id, bool(tag.graph.overview) and not body.get("force")
    if not cached and (limited := rate_limit_response()) is not None:
        return limited
    text = write_overview(tag_id, force=bool(body.get("force")))
    return jsonify({"overview": text, "cached": cached, "model": Config.MODEL})
