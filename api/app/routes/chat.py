from __future__ import annotations

import json

from flask import Blueprint, Response, jsonify, request, stream_with_context
from sqlalchemy import select

from sqlalchemy import select as _select

from ..db import session_scope
from ..llm import chat as chat_llm
from ..llm.diff import diff_digest, diff_graphs
from ..models import ChangeSummary, Tag
from ..ratelimit import rate_limit_response

bp = Blueprint("chat", __name__)


@bp.post("/chat")
def chat():
    body = request.get_json(silent=True) or {}
    repo_id = body.get("repo_id")
    tag_name = body.get("tag")
    messages = body.get("messages") or []
    if not repo_id or not tag_name or not messages:
        return jsonify({"error": "repo_id, tag and messages are required"}), 400
    if (limited := rate_limit_response()) is not None:
        return limited

    with session_scope() as s:
        tag = s.scalar(select(Tag).where(Tag.repo_id == repo_id, Tag.name == tag_name))
        if tag is None or tag.graph is None:
            return jsonify({"error": "no graph for this tag"}), 404
        ctx = chat_llm.ChatContext.from_tag(
            tag,
            tier=int(body.get("tier") or 1),
            system_id=body.get("system_id"),
            module_id=body.get("module_id"),
            selected_node=body.get("selected_node"),
            open_file=body.get("open_file"),
        )
        cmp_name = body.get("compare_tag")
        if cmp_name and cmp_name != tag_name:
            other = s.scalar(_select(Tag).where(Tag.repo_id == repo_id, Tag.name == cmp_name))
            if other is not None and other.graph is not None:
                earlier, later = (other, tag) if other.order_index < tag.order_index else (tag, other)
                g = lambda t: {"tier1": t.graph.tier1, "tier2": t.graph.tier2, "tier3": t.graph.tier3}  # noqa: E731
                d = diff_graphs(g(later), g(earlier))
                cached = s.scalar(_select(ChangeSummary).where(ChangeSummary.from_tag_id == earlier.id, ChangeSummary.to_tag_id == later.id))
                ctx.comparison = (
                    f"The user is comparing tag {earlier.name} (earlier) with tag {later.name} (later).\n"
                    + diff_digest(g(later), g(earlier), d)
                    + (f"\n\nNarrative summary of the change: {cached.summary}" if cached else "")
                )

    def generate():
        try:
            for event in chat_llm.stream_chat(ctx, messages):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:  # surfaced to the UI rather than a broken stream
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        yield "data: {\"type\": \"done\"}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
