"""Demo-grade background job runner: one worker thread, jobs run sequentially."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from ..config import Config
from ..db import session_scope
from ..models import GenerationJob, JobStatus, Tag
from . import jobs as gen

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gen")


def _finish(job_id: int, error: str | None = None) -> None:
    with session_scope() as s:
        job = s.get(GenerationJob, job_id)
        if job is None:
            return
        job.status = JobStatus.FAILED if error else JobStatus.DONE
        job.error = error
        job.finished_at = datetime.now(timezone.utc)
        if not error:
            job.progress = 1.0


def _run_repo_load(job_id: int, repo_id: int, n_tags: int, tag_pattern: str | None = None) -> None:
    try:
        gen.load_repo(repo_id, job_id=job_id)
        gen.generate_newest(repo_id, n=n_tags, job_id=job_id, tag_pattern=tag_pattern)
        _finish(job_id)
    except Exception as e:
        _finish(job_id, str(e))


def _run_job(job_id: int) -> None:
    try:
        gen.run_job(job_id)
    except Exception as e:
        _finish(job_id, str(e))


def enqueue_repo_load(repo_id: int, n_tags: int, tag_pattern: str | None = None) -> int:
    """local: clone + generate in a worker thread. chunked: list tags via the GitHub API now,
    create the job, and let the client drive it through POST /api/jobs/<id>/step."""
    if Config.GENERATION_MODE == "chunked":
        gen.load_repo(repo_id)
        ids = gen.select_newest(repo_id, n_tags, tag_pattern)
        return gen.create_job(repo_id, ids)
    with session_scope() as s:
        job = GenerationJob(repo_id=repo_id, status=JobStatus.QUEUED, step="queued", detail="waiting for worker", state={})
        s.add(job)
        s.flush()
        job_id = job.id
    _executor.submit(_run_repo_load, job_id, repo_id, n_tags, tag_pattern)
    return job_id


def enqueue_newest(repo_id: int, n_tags: int) -> int | None:
    """Queue generation for the newest n tags that have no graph yet (tags already fetched).
    Returns None when nothing needs generating."""
    ids = gen.select_newest(repo_id, n_tags)
    with session_scope() as s:
        pending = [tid for tid in ids if s.get(Tag, tid).graph is None]
    if not pending:
        return None
    job_id = gen.create_job(repo_id, pending)
    if Config.GENERATION_MODE != "chunked":
        _executor.submit(_run_job, job_id)
    return job_id


def enqueue_tag(repo_id: int, tag_id: int) -> int:
    job_id = gen.create_job(repo_id, [tag_id], force=True)
    if Config.GENERATION_MODE != "chunked":
        _executor.submit(_run_job, job_id)
    return job_id
