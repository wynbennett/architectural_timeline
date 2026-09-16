from __future__ import annotations

import json

from flask import Blueprint, abort, jsonify, request
from sqlalchemy import select

from ..config import Config
from ..db import session_scope
from ..ingest.filesource import get_file_source
from ..ingest.inventory import head_lines
from ..llm.client import structured_call
from ..llm.generate import load_prompt, render
from ..models import Tag
from ..schemas import Overview

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
def write_overview(repo_id: int, tag_name: str):
    """Generate (or regenerate with {"force": true}) the written overview for a tag. One model call, cached."""
    body = request.get_json(silent=True) or {}
    with session_scope() as s:
        tag = s.scalar(select(Tag).where(Tag.repo_id == repo_id, Tag.name == tag_name))
        if tag is None or tag.graph is None:
            return jsonify({"error": "no graph for this tag"}), 404
        if tag.graph.overview and not body.get("force"):
            return jsonify({"overview": tag.graph.overview, "cached": True})
        owner, name, sha = tag.repo.owner, tag.repo.name, tag.commit_sha
        readme_path = next((f.path for f in tag.files if f.path.lower().startswith("readme")), None)
        arch = {"summary": tag.graph.tier1["summary"], "systems": tag.graph.tier1["nodes"], "edges": tag.graph.tier1["edges"],
                "modules": {sid: [{"id": m["id"], "name": m["name"], "description": m["description"], "paths": m["paths"]} for m in t2["nodes"]] for sid, t2 in tag.graph.tier2.items()}}
    readme = ""
    if readme_path:
        readme = head_lines(get_file_source().read(owner, name, sha, readme_path, allowed={readme_path}) or "", 150)
    prompt = render(load_prompt("overview"), owner=owner, name=name, tag=tag_name, readme=readme or "(no README)", architecture=json.dumps(arch, indent=1))
    out = structured_call(load_prompt("system"), prompt, Overview, max_tokens=6000, effort="medium")
    with session_scope() as s:
        tag = s.scalar(select(Tag).where(Tag.repo_id == repo_id, Tag.name == tag_name))
        tag.graph.overview = out.markdown
    return jsonify({"overview": out.markdown, "cached": False, "model": Config.MODEL})
