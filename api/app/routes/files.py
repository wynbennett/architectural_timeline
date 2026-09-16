from __future__ import annotations

from flask import Blueprint, abort, jsonify, request
from sqlalchemy import select

from ..db import session_scope
from ..ingest.filesource import get_file_source
from ..ingest.inventory import language_for
from ..models import File, Tag

bp = Blueprint("files", __name__)


@bp.get("/repos/<int:repo_id>/tags/<path:tag_name>/files")
def files(repo_id: int, tag_name: str):
    path = request.args.get("path")
    with session_scope() as s:
        tag = s.scalar(select(Tag).where(Tag.repo_id == repo_id, Tag.name == tag_name))
        if tag is None:
            abort(404)
        if not path:
            rows = s.scalars(select(File).where(File.tag_id == tag.id).order_by(File.path)).all()
            return jsonify([{"path": f.path, "language": f.language, "size": f.size} for f in rows])
        row = s.scalar(select(File).where(File.tag_id == tag.id, File.path == path))
        if row is None:
            abort(404)
        owner, name, sha = tag.repo.owner, tag.repo.name, tag.commit_sha
    content = get_file_source().read(owner, name, sha, path, allowed={path})
    if content is None:
        return jsonify({"error": "file content unavailable"}), 404
    return jsonify({"path": path, "language": language_for(path), "content": content, "sha": sha})
