import os

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db import make_engine
from app.models import ChangeSummary, File, Graph, Repo, Tag
from app.sync import sync


def test_sync_is_idempotent(seeded_repo, tmp_path):
    target = f"sqlite:///{tmp_path / 'target.db'}"
    source = os.environ["DATABASE_URL"]

    r1 = sync(source, target, repo_filter="acme/demo")
    assert r1.repos == 1 and r1.tags == 2 and r1.graphs == 2 and r1.files > 0

    # second run replaces rather than duplicates
    r2 = sync(source, target, repo_filter="acme/demo")
    assert (r2.repos, r2.tags, r2.graphs) == (1, 2, 2)

    S = sessionmaker(bind=make_engine(target))
    with S() as s:
        repos = s.scalars(select(Repo)).all()
        assert len(repos) == 1 and repos[0].url == "https://github.com/acme/demo"
        tags = s.scalars(select(Tag).where(Tag.repo_id == repos[0].id).order_by(Tag.order_index)).all()
        assert [t.name for t in tags] == ["v0.1.0", "v0.2.0"] and all(t.graph is not None for t in tags)
        assert s.scalar(select(Graph).where(Graph.tag_id == tags[1].id)).tier1["nodes"]
        assert len(s.scalars(select(File).where(File.tag_id == tags[1].id)).all()) == 4
        assert s.scalars(select(Graph)).all().__len__() == 2  # no duplicates

    dry = sync(source, target, repo_filter="acme/demo", dry_run=True)
    assert dry.graphs == 2

    try:
        sync(source, target, repo_filter="nobody/nothing")
        assert False, "expected ValueError"
    except ValueError:
        pass
