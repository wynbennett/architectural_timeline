from unittest.mock import patch

from sqlalchemy import select

from app import create_app
from app.config import Config
from app.models import Repo
from app.ratelimit import LeakyBucket


def test_leaky_bucket_burst_then_leak():
    b = LeakyBucket(capacity=3, leak_seconds=10)
    assert [b.check("ip", now=0)[0] for _ in range(3)] == [True, True, True]
    allowed, retry = b.check("ip", now=0)
    assert not allowed and retry == 10
    assert b.check("ip", now=10)[0] is True          # one unit leaked
    assert b.check("other", now=10)[0] is True       # separate client


def test_rate_limit_returns_429(seeded_repo):
    from app import ratelimit
    app = create_app()
    c = app.test_client()
    with session_scope_repo_id() as repo_id, \
         patch.object(Config, "RATE_LIMIT_ENABLED", True), patch.object(Config, "LLM_RATE_CAPACITY", 1.0), patch.object(Config, "LLM_RATE_LEAK_SECONDS", 60.0):
        ratelimit._bucket = None
        first = c.post(f"/api/repos/{repo_id}/tags/v0.2.0/overview", headers={"X-Forwarded-For": "203.0.113.5"})
        assert first.status_code == 200            # cached overview, still counts as a model-capable call
        second = c.post(f"/api/repos/{repo_id}/tags/v0.2.0/overview", headers={"X-Forwarded-For": "203.0.113.5"})
        assert second.status_code == 429 and "Retry-After" in second.headers
        assert c.post(f"/api/repos/{repo_id}/tags/v0.2.0/overview", headers={"X-Forwarded-For": "203.0.113.6"}).status_code == 200
    ratelimit._bucket = None


def test_demo_mode_blocks_loading_and_generation(seeded_repo):
    app = create_app()
    c = app.test_client()
    with session_scope_repo_id() as repo_id, patch.object(Config, "DEMO_MODE", True):
        assert c.get("/api/health").get_json()["demo_mode"] is True
        r = c.post("/api/repos", json={"url": "https://github.com/psf/requests"})
        assert r.status_code == 403 and "demo mode" in r.get_json()["error"]
        assert c.post(f"/api/repos/{repo_id}/tags/v0.1.0/generate").status_code == 403
        assert c.post("/api/jobs/1/step").status_code == 403
        assert c.get(f"/api/repos/{repo_id}/tags/v0.2.0/graph").status_code == 200  # viewing still works


def test_repo_list_counts(seeded_repo):
    body = create_app().test_client().get("/api/repos").get_json()
    demo = next(r for r in body if r["name"] == "demo")
    assert demo["tag_count"] == 2 and demo["generated_count"] == 2


from contextlib import contextmanager


@contextmanager
def session_scope_repo_id():
    from app.db import session_scope
    with session_scope() as s:
        yield s.scalar(select(Repo).where(Repo.url == "https://github.com/acme/demo")).id
