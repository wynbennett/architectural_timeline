"""Orchestration test with the LLM mocked out."""
from unittest.mock import patch

from sqlalchemy import select

from app.db import init_db, session_scope
from app.ingest import git
from app.llm import generate as gen
from app.models import GenerationJob, Graph, Repo, Tag
from app.schemas import Edge, ModuleNode, SnippetNode, SystemNode, Tier1Graph, Tier2Graph, Tier3Graph


def test_generate_tag_end_to_end(seeded_repo):
    repo_id = seeded_repo
    with session_scope() as s:
        tags = s.scalars(select(Tag).where(Tag.repo_id == repo_id).order_by(Tag.order_index)).all()
        assert [t.status for t in tags] == ["done", "done"]
        g = s.scalar(select(Graph).where(Graph.tag_id == tags[1].id))
        ids1 = {n["id"] for n in g.tier1["nodes"]}
        assert ids1 == {"api-service", "worker", "db"}          # slugified
        api = next(n for n in g.tier1["nodes"] if n["id"] == "api-service")
        assert api["paths"] == ["api"]                           # unknown path dropped
        assert [(e["source"], e["target"]) for e in g.tier1["edges"]] == [("api-service", "db")]  # dangling edge dropped
        assert g.tier2["db"] == {"nodes": [], "edges": []}       # no files -> no call
        api_mods = g.tier2["api-service"]["nodes"]
        assert [m["id"] for m in api_mods] == ["core"]           # module with no valid paths dropped
        assert api_mods[0]["paths"] == ["api/app.py"]            # path outside the system dropped
        snippets = g.tier3["api-service/core"]["nodes"]
        assert [sn["id"] for sn in snippets] == ["index"]        # unknown file dropped; worker file not in this module
        assert snippets[0]["end_line"] == 6                      # clamped to file length
        assert g.tier3["api-service/core"]["edges"] == []        # edge to dropped snippet removed
        # inventory persisted, no content
        assert {f.path for f in tags[1].files} == {"README.md", "api/app.py", "requirements.txt", "worker/main.py"}


def test_tag_pattern_filters(monkeypatch, seeded_repo):
    ran = []
    monkeypatch.setattr(gen, "run_job", lambda job_id: ran.append(job_id))
    with session_scope() as s:
        repo = s.scalar(select(Repo).where(Repo.url == "https://github.com/acme/demo"))
        ids = {t.name: t.id for t in repo.tags}
    assert gen.select_newest(repo.id, n=3, tag_pattern=r"^v0\.1\.") == [ids["v0.1.0"]]
    assert gen.select_newest(repo.id, n=1) == [ids["v0.2.0"]]
    try:
        gen.select_newest(repo.id, n=3, tag_pattern=r"^nomatch")
        assert False, "expected ValueError"
    except ValueError:
        pass
    gen.generate_newest(repo.id, n=3, tag_pattern=r"^v0\.1\.")
    assert len(ran) == 1
    with session_scope() as s:
        job = s.get(GenerationJob, ran[0])
        assert job.state["tags"] == [ids["v0.1.0"]] and job.status == "queued"


def test_step_machine_resumes(monkeypatch, seeded_repo, fixture_repo):
    """budget 0 => exactly one unit of work per call; state carries across calls."""
    from unittest.mock import patch as _patch
    from tests.conftest import fake_structured_call

    monkeypatch.setattr(git, "repo_dir", lambda owner, name: fixture_repo)
    with session_scope() as s:
        repo = s.scalar(select(Repo).where(Repo.url == "https://github.com/acme/demo"))
        tag_id = next(t.id for t in repo.tags if t.name == "v0.2.0")
        repo_id = repo.id
    job_id = gen.create_job(repo_id, [tag_id], force=True)
    phases = []
    with _patch.object(gen, "structured_call", side_effect=fake_structured_call):
        for _ in range(30):
            with session_scope() as s:
                phases.append(s.get(GenerationJob, job_id).state.get("phase", "inventory"))
            if gen.run_job_step(job_id, budget_s=0):
                break
    assert phases[:3] == ["inventory", "tier1", "tier2"] and "tier3" in phases and len(phases) >= 5
    with session_scope() as s:
        job = s.get(GenerationJob, job_id)
        assert job.status == "done" and job.progress == 1.0
        tag = s.get(Tag, tag_id)
        assert tag.status == "done" and "api-service" in tag.graph.tier2
