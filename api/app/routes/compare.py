from __future__ import annotations

import json

from flask import Blueprint, jsonify, request
from sqlalchemy import select

from ..config import Config
from ..db import session_scope
from ..llm.client import structured_call
from ..llm.diff import diff_digest, diff_graphs
from ..llm.prompts import render_prompt, system_prompt
from ..models import ChangeSummary, Tag
from ..ratelimit import rate_limit_response
from ..schemas import ChangeSummary as ChangeSummarySchema

bp = Blueprint("compare", __name__)


def _graph_dict(t: Tag) -> dict:
    return {"tier1": t.graph.tier1, "tier2": t.graph.tier2, "tier3": t.graph.tier3}


def _files(t: Tag) -> dict[str, str]:
    return {f.path: f.blob_sha for f in t.files if f.blob_sha}


def _load_pair(s, repo_id: int, from_name: str, to_name: str) -> tuple[Tag, Tag] | None:
    a = s.scalar(select(Tag).where(Tag.repo_id == repo_id, Tag.name == from_name))
    b = s.scalar(select(Tag).where(Tag.repo_id == repo_id, Tag.name == to_name))
    if a is None or b is None or a.graph is None or b.graph is None:
        return None
    # "from" is the earlier tag by convention; swap if the caller had them reversed
    if a.order_index > b.order_index:
        a, b = b, a
    return a, b


@bp.get("/repos/<int:repo_id>/compare")
def compare(repo_id: int):
    from_name, to_name = request.args.get("from", ""), request.args.get("to", "")
    with session_scope() as s:
        pair = _load_pair(s, repo_id, from_name, to_name)
        if pair is None:
            return jsonify({"error": "both tags need a generated graph"}), 404
        a, b = pair
        d = diff_graphs(_graph_dict(b), _graph_dict(a), _files(b), _files(a))
        cached = s.scalar(select(ChangeSummary).where(ChangeSummary.from_tag_id == a.id, ChangeSummary.to_tag_id == b.id))
        return jsonify({"from": a.name, "to": b.name, "diff": d, "summary": cached.summary if cached else None})


@bp.post("/repos/<int:repo_id>/compare/summary")
def summarize(repo_id: int):
    body = request.get_json(silent=True) or {}
    with session_scope() as s:
        pair = _load_pair(s, repo_id, body.get("from", ""), body.get("to", ""))
        if pair is None:
            return jsonify({"error": "both tags need a generated graph"}), 404
        a, b = pair
        cached = s.scalar(select(ChangeSummary).where(ChangeSummary.from_tag_id == a.id, ChangeSummary.to_tag_id == b.id))
        if cached and not body.get("force"):
            return jsonify({"from": a.name, "to": b.name, "summary": cached.summary, "cached": True})
        ga, gb = _graph_dict(a), _graph_dict(b)
        fa, fb = _files(a), _files(b)
        owner, name, a_id, b_id, a_name, b_name = a.repo.owner, a.repo.name, a.id, b.id, a.name, b.name
    if (limited := rate_limit_response()) is not None:
        return limited

    d = diff_graphs(gb, ga, fb, fa)
    slim = lambda g: {"tier1": g["tier1"], "tier2": g["tier2"]}  # noqa: E731  (tier 3 is too large and not needed)
    prompt = render_prompt(
        "change_summary",
        owner=owner, name=name, prev_tag=a_name, tag=b_name,
        previous_graph=json.dumps(slim(ga)), current_graph=json.dumps(slim(gb)),
        computed_diff=diff_digest(gb, ga, d),
    )
    out = structured_call(system_prompt(), prompt, ChangeSummarySchema, max_tokens=4000, effort="medium")
    with session_scope() as s:
        existing = s.scalar(select(ChangeSummary).where(ChangeSummary.from_tag_id == a_id, ChangeSummary.to_tag_id == b_id))
        if existing:
            existing.summary, existing.model = out.summary, Config.MODEL
        else:
            s.add(ChangeSummary(repo_id=repo_id, from_tag_id=a_id, to_tag_id=b_id, summary=out.summary, model=Config.MODEL))
    return jsonify({"from": a_name, "to": b_name, "summary": out.summary, "cached": False})
