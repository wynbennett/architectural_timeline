import os
import subprocess
import tempfile
from pathlib import Path

import pytest
from unittest.mock import patch

# app.config reads the environment at import time, so this must run before any
# test module imports the app. conftest is imported first by pytest.
_ROOT = Path(tempfile.mkdtemp(prefix="arch-tests-"))
# TEST_DATABASE_URL=postgres://... runs the suite against a real Postgres (see README "Tests")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_ROOT / 'test.db'}"
os.environ["REPO_CACHE_DIR"] = str(_ROOT / "repos")
os.environ["GENERATION_ENABLED"] = "1"
os.environ["FILE_SOURCE"] = "local"
os.environ["ANTHROPIC_API_KEY"] = "test-key"
os.environ["RATE_LIMIT_ENABLED"] = "0"

# Only import the app after the environment above is in place.
from app.schemas import Edge, ModuleNode, SnippetNode, SystemNode, Tier1Graph, Tier2Graph, Tier3Graph  # noqa: E402


@pytest.fixture(scope="session")
def tmp_root():
    return _ROOT


@pytest.fixture(scope="session")
def fixture_repo(tmp_root) -> Path:
    """A tiny local git repo with two tags, used as a stand-in for a GitHub clone."""
    src = tmp_root / "src_repo"
    src.mkdir()

    def git(*args):
        subprocess.run(["git", *args], cwd=src, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (src / "README.md").write_text("# demo\nA tiny service.\n")
    (src / "api").mkdir()
    (src / "api" / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n\n@app.get('/')\ndef index():\n    return 'hi'\n")
    (src / "requirements.txt").write_text("flask\n")
    (src / "node_modules").mkdir()
    (src / "node_modules" / "junk.js").write_text("x")
    (src / "logo.png").write_bytes(b"\x89PNG\r\n")
    git("add", "-A")
    git("commit", "-q", "-m", "v1")
    git("tag", "v0.1.0")
    (src / "worker").mkdir()
    (src / "worker" / "main.py").write_text("import time\n\ndef run():\n    while True:\n        time.sleep(1)\n")
    git("add", "-A")
    git("commit", "-q", "-m", "v2")
    git("tag", "-a", "v0.2.0", "-m", "second")
    return src


def fake_structured_call(system, user, output_type, **kw):
    if output_type is Tier1Graph:
        return Tier1Graph(
            summary="demo",
            nodes=[
                SystemNode(id="Api Service", name="API", kind="api", description="d", paths=["api", "ghost/"]),
                SystemNode(id="worker", name="Worker", kind="worker", description="d", paths=["worker"]),
                SystemNode(id="db", name="DB", kind="datastore", description="d", paths=[]),
            ],
            edges=[Edge(source="api-service", target="db", kind="reads"), Edge(source="api-service", target="nope", kind="calls")],
        )
    if output_type is Tier2Graph:
        return Tier2Graph(
            nodes=[ModuleNode(id="core", name="Core", description="d", paths=["api/app.py", "worker/main.py"]), ModuleNode(id="empty", name="E", description="d", paths=["zzz"])],
            edges=[],
        )
    if output_type is Tier3Graph:
        return Tier3Graph(
            nodes=[
                SnippetNode(id="index", title="index", description="d", file_path="api/app.py", start_line=4, end_line=999),
                SnippetNode(id="bad", title="bad", description="d", file_path="missing.py", start_line=1, end_line=2),
                SnippetNode(id="run", title="run", description="d", file_path="worker/main.py", start_line=3, end_line=5),
            ],
            edges=[Edge(source="index", target="run", kind="calls")],
        )
    raise AssertionError(output_type)



@pytest.fixture(scope="session")
def seeded_repo(fixture_repo) -> int:
    """acme/demo with both tags generated through the mocked LLM. Returns the repo id."""
    from sqlalchemy import delete, select
    from app.db import init_db, session_scope
    from app.ingest import git
    from app.llm import generate as gen, jobs
    from app.models import ChangeSummary, GenerationJob, Repo

    init_db()
    with session_scope() as s:
        # start clean even on a persistent database (TEST_DATABASE_URL)
        old = s.scalar(select(Repo).where(Repo.url == "https://github.com/acme/demo"))
        if old is not None:
            s.execute(delete(ChangeSummary).where(ChangeSummary.repo_id == old.id))
            s.execute(delete(GenerationJob).where(GenerationJob.repo_id == old.id))
            s.delete(old)
            s.flush()
        repo = Repo(url="https://github.com/acme/demo", owner="acme", name="demo")
        s.add(repo)
        s.flush()
        repo_id = repo.id
    from app.llm import overview as overview_mod
    from app.schemas import Overview

    with patch.object(git, "clone_or_fetch", lambda url: fixture_repo), patch.object(git, "repo_dir", lambda owner, name: fixture_repo), \
         patch.object(gen, "structured_call", side_effect=fake_structured_call), \
         patch.object(overview_mod, "structured_call", return_value=Overview(markdown="# seeded overview")):
        jobs.load_repo(repo_id)
        jobs.generate_newest(repo_id, n=2)
    return repo_id
