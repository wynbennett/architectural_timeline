from unittest.mock import patch

from app import create_app
from app.config import Config
from app.ratelimit import LeakyBucket


def test_leaky_bucket_burst_then_leak():
    b = LeakyBucket(capacity=3, leak_seconds=10)
    assert [b.check("ip", now=0)[0] for _ in range(3)] == [True, True, True]
    allowed, retry = b.check("ip", now=0)
    assert not allowed and retry == 10
    assert b.check("ip", now=10)[0] is True          # one unit leaked
    assert b.check("other", now=10)[0] is True       # separate client
    assert LeakyBucket(capacity=0, leak_seconds=0).check("x", now=0)[0] is True  # bad config is clamped, never divides by zero


def test_rate_limit_charges_only_real_model_calls(seeded_repo):
    from app import ratelimit
    from app.llm import overview as overview_mod
    from app.schemas import Overview

    c = create_app().test_client()
    repo_id = seeded_repo
    url = f"/api/repos/{repo_id}/tags/v0.2.0/overview"
    a, b = {"REMOTE_ADDR": "203.0.113.5"}, {"REMOTE_ADDR": "203.0.113.6"}
    with patch.object(Config, "RATE_LIMIT_ENABLED", True), patch.object(Config, "LLM_RATE_CAPACITY", 1.0), patch.object(Config, "LLM_RATE_LEAK_SECONDS", 60.0), \
         patch.object(overview_mod, "structured_call", return_value=Overview(markdown="# x")):
        ratelimit._bucket = None
        for _ in range(3):  # cached answers are free
            assert c.post(url, environ_base=a).status_code == 200
        assert c.post(url, json={"force": True}, environ_base=a).status_code == 200      # one real call: allowed
        r = c.post(url, json={"force": True}, environ_base=a)
        assert r.status_code == 429 and "Retry-After" in r.headers                       # second real call: limited
        assert c.post(url, json={"force": True}, environ_base=b).status_code == 200      # other client unaffected
        # a spoofed X-Forwarded-For does not change the bucket key without a trusted proxy
        assert c.post(url, json={"force": True}, environ_base=a, headers={"X-Forwarded-For": "198.51.100.9"}).status_code == 429
    ratelimit._bucket = None


def test_demo_mode_blocks_loading_and_generation(seeded_repo):
    c = create_app().test_client()
    repo_id = seeded_repo
    with patch.object(Config, "DEMO_MODE", True):
        assert c.get("/api/health").get_json()["demo_mode"] is True
        r = c.post("/api/repos", json={"url": "https://github.com/psf/requests"})
        assert r.status_code == 403 and "demo mode" in r.get_json()["error"]
        assert c.post(f"/api/repos/{repo_id}/tags/v0.1.0/generate").status_code == 403
        assert c.post("/api/jobs/1/step").status_code == 403
        assert c.get(f"/api/repos/{repo_id}/tags/v0.2.0/graph").status_code == 200  # viewing still works


def test_http_errors_are_json_and_keep_headers():
    c = create_app().test_client()
    r = c.get("/api/chat")  # POST-only
    assert r.status_code == 405 and r.is_json and "POST" in r.headers.get("Allow", "")
    r = c.get("/api/repos/999999")
    assert r.status_code == 404 and r.is_json and r.get_json()["status"] == 404


def test_repo_list_counts(seeded_repo):
    body = create_app().test_client().get("/api/repos").get_json()
    demo = next(r for r in body if r["name"] == "demo")
    assert demo["tag_count"] == 2 and demo["generated_count"] == 2


def test_unknown_status_value_loads_as_string(seeded_repo):
    from sqlalchemy import text
    from app.db import session_scope
    from app.models import Tag, TagStatus

    with session_scope() as s:
        tag = s.query(Tag).filter_by(repo_id=seeded_repo, name="v0.1.0").one()
        tag_id = tag.id
        s.execute(text("update tags set status='weird' where id=:id"), {"id": tag_id})
    with session_scope() as s:
        tag = s.get(Tag, tag_id)
        assert tag.status == "weird"          # tolerated rather than raising
        tag.status = TagStatus.DONE
    with session_scope() as s:
        assert s.get(Tag, tag_id).status is TagStatus.DONE


def test_chat_system_prompt_renders(seeded_repo):
    from sqlalchemy import select
    from app.db import session_scope
    from app.llm import chat as chat_llm
    from app.models import Tag

    with session_scope() as s:
        tag = s.scalar(select(Tag).where(Tag.repo_id == seeded_repo, Tag.name == "v0.2.0"))
        ctx = chat_llm.ChatContext.from_tag(tag, tier=2, system_id="api-service", module_id=None, selected_node=None, open_file="api/app.py")
    text = ctx.system_prompt()
    assert "acme/demo" in text and "api-service" in text and "api/app.py" in text
