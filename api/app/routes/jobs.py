from __future__ import annotations

from flask import Blueprint, abort, jsonify

from ..config import Config
from ..db import session_scope
from ..llm import generate as gen
from ..models import GenerationJob, Tag

bp = Blueprint("jobs", __name__)


def job_dict(j: GenerationJob, tag_name: str | None) -> dict:
    return {
        "id": j.id,
        "repo_id": j.repo_id,
        "tag": tag_name,
        "status": j.status,
        "step": j.step,
        "progress": j.progress,
        "detail": j.detail,
        "error": j.error,
        "started_at": j.started_at.isoformat() if j.started_at else None,
        "finished_at": j.finished_at.isoformat() if j.finished_at else None,
    }


@bp.get("/jobs/<int:job_id>")
def get_job(job_id: int):
    with session_scope() as s:
        job = s.get(GenerationJob, job_id)
        if job is None:
            abort(404)
        tag = s.get(Tag, job.tag_id) if job.tag_id else None
        return jsonify(job_dict(job, tag.name if tag else None))


@bp.post("/jobs/<int:job_id>/step")
def step_job(job_id: int):
    """Chunked mode: run one time-boxed slice of the job. The client calls this until done."""
    if Config.GENERATION_MODE != "chunked":
        return jsonify({"error": "step is only used in chunked generation mode"}), 409
    with session_scope() as s:
        if s.get(GenerationJob, job_id) is None:
            abort(404)
    err = None
    try:
        done = gen.run_job_step(job_id)
    except Exception as e:  # the job is already marked failed
        done, err = True, str(e)
    with session_scope() as s:
        job = s.get(GenerationJob, job_id)
        tag = s.get(Tag, job.tag_id) if job.tag_id else None
        body = job_dict(job, tag.name if tag else None) | {"done": done}
    if err:
        body["error"] = err
    return jsonify(body)
