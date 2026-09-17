from unittest.mock import patch

from sqlalchemy import select

from app import create_app
from app.db import session_scope
from app.llm.diff import diff_digest, diff_graphs
from app.models import Repo
from app.routes import compare as compare_route
from app.schemas import ChangeSummary as ChangeSummarySchema


def test_diff_graphs():
    prev = {"tier1": {"nodes": [{"id": "a", "name": "A", "kind": "api", "paths": ["a"]}, {"id": "gone", "name": "G", "kind": "worker", "paths": []}],
                      "edges": [{"source": "a", "target": "gone", "kind": "calls"}]},
            "tier2": {"a": {"nodes": [{"id": "m1", "name": "M1", "paths": ["a/x.py"]}], "edges": []}}, "tier3": {}}
    cur = {"tier1": {"nodes": [{"id": "a", "name": "A", "kind": "api", "paths": ["a", "a2"]}, {"id": "new", "name": "N", "kind": "datastore", "paths": []}],
                     "edges": [{"source": "a", "target": "new", "kind": "reads"}]},
           "tier2": {"a": {"nodes": [{"id": "m1", "name": "M1", "paths": ["a/x.py"]}, {"id": "m2", "name": "M2", "paths": ["a/y.py"]}], "edges": []}}, "tier3": {}}
    d = diff_graphs(cur, prev)
    assert d["tier1"]["nodes"] == {"a": "changed", "new": "added", "gone": "removed"}
    assert d["tier1"]["edge_counts"] == {"added": 1, "removed": 1, "unchanged": 0}
    assert d["tier1"]["edges"] == {"a|new|reads": "added", "a|gone|calls": "removed"}
    assert d["tier1"]["counts"]["added"] == 1
    assert d["tier2"]["a"]["nodes"] == {"m1": "unchanged", "m2": "added"}
    # modified: same paths, different file content under them
    prev2 = {"tier1": {"nodes": [{"id": "a", "name": "A", "kind": "api", "paths": ["a"]}], "edges": []}, "tier2": {}, "tier3": {}}
    cur2 = {"tier1": {"nodes": [{"id": "a", "name": "A", "kind": "api", "paths": ["a"]}], "edges": []}, "tier2": {}, "tier3": {}}
    same = diff_graphs(cur2, prev2, {"a/x.py": "111"}, {"a/x.py": "111"})
    assert same["tier1"]["nodes"] == {"a": "unchanged"}
    mod = diff_graphs(cur2, prev2, {"a/x.py": "222"}, {"a/x.py": "111"})
    assert mod["tier1"]["nodes"] == {"a": "modified"} and mod["tier1"]["counts"]["modified"] == 1
    assert diff_graphs(cur2, prev2)["tier1"]["nodes"] == {"a": "unchanged"}  # no hashes: never guesses
    digest = diff_digest(cur, prev, d)
    assert "systems added: N (new)" in digest and "removed: G (gone)" in digest and "modules of A: added: m2" in digest


def test_compare_routes(seeded_repo):
    app = create_app()
    c = app.test_client()
    with session_scope() as s:
        repo_id = s.scalar(select(Repo).where(Repo.url == "https://github.com/acme/demo")).id
    r = c.get(f"/api/repos/{repo_id}/compare", query_string={"from": "v0.2.0", "to": "v0.1.0"})  # reversed order is fine
    assert r.status_code == 200
    body = r.get_json()
    assert body["from"] == "v0.1.0" and body["to"] == "v0.2.0" and body["summary"] is None
    assert set(body["diff"]["tier1"]["nodes"]) == {"api-service", "worker", "db"}
    assert c.get(f"/api/repos/{repo_id}/compare", query_string={"from": "v0.1.0", "to": "nope"}).status_code == 404

    with patch.object(compare_route, "structured_call", return_value=ChangeSummarySchema(summary="The worker was added.")) as m:
        r = c.post(f"/api/repos/{repo_id}/compare/summary", json={"from": "v0.1.0", "to": "v0.2.0"})
        assert r.status_code == 200 and r.get_json()["summary"] == "The worker was added." and r.get_json()["cached"] is False
        r = c.post(f"/api/repos/{repo_id}/compare/summary", json={"from": "v0.1.0", "to": "v0.2.0"})
        assert r.get_json()["cached"] is True
        assert m.call_count == 1
    assert c.get(f"/api/repos/{repo_id}/compare", query_string={"from": "v0.1.0", "to": "v0.2.0"}).get_json()["summary"] == "The worker was added."
