import subprocess

from app.ingest import git
from app.ingest.workspace import DirWorkspace, GitWorkspace
from app.ingest.inventory import build_inventory, directory_tree, entrypoint_paths, is_excluded, manifest_paths, readme_path


def test_exclusions():
    assert is_excluded("node_modules/x/index.js", 10, 1000)
    assert is_excluded("dist/app.min.js", 10, 1000)
    assert is_excluded("logo.png", 10, 1000)
    assert is_excluded("big.py", 5000, 1000)
    assert is_excluded("empty.py", 0, 1000)
    assert not is_excluded("src/app.py", 10, 1000)


def test_inventory_from_fixture(fixture_repo):
    tags = git.list_tags(fixture_repo)
    assert [t.name for t in tags] == ["v0.1.0", "v0.2.0"]
    inv = build_inventory(GitWorkspace(fixture_repo, tags[1].sha))
    paths = {f.path for f in inv.files}
    assert paths == {"README.md", "api/app.py", "requirements.txt", "worker/main.py"}
    assert inv.path_exists("api") and inv.path_exists("api/app.py") and not inv.path_exists("nope")
    assert [f.path for f in inv.under(["api"])] == ["api/app.py"]
    assert readme_path(inv) == "README.md"
    assert manifest_paths(inv) == ["requirements.txt"]
    assert set(entrypoint_paths(inv)) == {"api/app.py", "worker/main.py"}
    tree = directory_tree(inv)
    assert "api/" in tree and "worker/" in tree


def test_read_blob(fixture_repo):
    tags = git.list_tags(fixture_repo)
    assert b"Flask" in git.read_blob(fixture_repo, tags[0].sha, "api/app.py")


def test_dir_workspace(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("print(1)\n")
    (tmp_path / "README.md").write_text("# x\n")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG")
    ws = DirWorkspace(root=tmp_path, sha="abc")
    assert sorted(p for p, _ in ws.list_files()) == ["README.md", "logo.png", "src/a.py"]
    assert ws.read("src/a.py") == "print(1)\n"
    assert ws.read("../etc/passwd") == ""
    inv = build_inventory(ws)
    assert [f.path for f in inv.files] == ["README.md", "src/a.py"]
