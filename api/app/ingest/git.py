"""Thin wrappers over the git CLI. All reads are done against a local clone."""
from __future__ import annotations

import base64
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..config import Config

_GITHUB_RE = re.compile(r"^(?:https?://github\.com/|git@github\.com:)([^/]+)/([^/]+?)(?:\.git)?/?$")


class GitError(RuntimeError):
    pass


def parse_github_url(url: str) -> tuple[str, str]:
    m = _GITHUB_RE.match(url.strip())
    if not m:
        raise GitError(f"not a GitHub repo url: {url}")
    return m.group(1), m.group(2)


def _auth_args() -> list[str]:
    """Send GITHUB_TOKEN as a per-command header so it is never written into .git/config."""
    if not Config.GITHUB_TOKEN:
        return []
    basic = base64.b64encode(f"x-access-token:{Config.GITHUB_TOKEN}".encode()).decode()
    return ["-c", f"http.https://github.com/.extraheader=Authorization: Basic {basic}"]


def _run(args: list[str], cwd: Path | None = None, text: bool = True, stdin: str | None = None, no_lazy_fetch: bool = False, auth: bool = False) -> str | bytes:
    env = None
    if no_lazy_fetch:
        # Never reach out to the remote for a missing object; report it as missing instead.
        env = {**os.environ, "GIT_NO_LAZY_FETCH": "1"}
    proc = subprocess.run(["git", *(_auth_args() if auth else []), *args], cwd=cwd, capture_output=True, input=stdin.encode() if stdin is not None else None, env=env)
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout.decode(errors="replace") if text else proc.stdout


def repo_dir(owner: str, name: str) -> Path:
    return Config.REPO_CACHE_DIR / f"{owner}_{name}"


def _blob_filter() -> str:
    # Partial clone that brings every blob up to the inventory size cap in one transfer and
    # leaves larger ones on the server. Those are excluded from the inventory anyway, so
    # nothing needs a lazy fetch later.
    return f"--filter=blob:limit={Config.MAX_FILE_BYTES}"


def clone_or_fetch(url: str) -> Path:
    owner, name = parse_github_url(url)
    dest = repo_dir(owner, name)
    if (dest / ".git").exists():
        _run(["fetch", "--tags", "--force", "--prune", _blob_filter(), "origin"], cwd=dest, auth=True)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    clean = f"https://github.com/{owner}/{name}.git"
    _run(["clone", _blob_filter(), "--no-checkout", clean, str(dest)], auth=True)
    return dest


@dataclass
class TagInfo:
    name: str
    sha: str
    tagged_at: datetime | None


def list_tags(repo: Path) -> list[TagInfo]:
    """Tags sorted oldest -> newest by creator date (falls back to commit date)."""
    out = _run(
        [
            "for-each-ref",
            "--sort=creatordate",
            "--format=%(refname:short)%09%(*objectname)%09%(objectname)%09%(creatordate:iso-strict)",
            "refs/tags",
        ],
        cwd=repo,
    )
    tags: list[TagInfo] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        name, peeled, obj, date = parts
        sha = peeled or obj  # annotated tags peel to the commit; lightweight tags are the commit
        try:
            tagged_at = datetime.fromisoformat(date) if date else None
        except ValueError:
            tagged_at = None
        tags.append(TagInfo(name=name, sha=sha, tagged_at=tagged_at))
    return tags


def default_branch(repo: Path) -> str | None:
    try:
        ref = _run(["symbolic-ref", "refs/remotes/origin/HEAD"], cwd=repo).strip()
        return ref.rsplit("/", 1)[-1] or None
    except GitError:
        return None


@dataclass
class TreeEntry:
    path: str
    size: int
    sha: str  # git blob id; identical content => identical sha, across clones and tarballs


def ls_tree(repo: Path, sha: str) -> list[TreeEntry]:
    """All blobs at a commit with sizes. Blobs absent from a partial clone (over the size cap)
    are reported with size -1 so the inventory excludes them without any network access."""
    # -z: NUL-separated records with raw paths (otherwise unusual paths come back C-quoted)
    out = _run(["ls-tree", "-r", "-z", "--full-tree", sha], cwd=repo)
    oids: dict[str, list[str]] = {}
    for line in out.split("\0"):
        # "<mode> <type> <object>\t<path>"
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) < 3 or parts[1] != "blob":
            continue
        oids.setdefault(parts[2], []).append(path)
    sizes: dict[str, int] = {}
    if oids:
        check = _run(
            ["cat-file", "--batch-check=%(objectname) %(objectsize)"],
            cwd=repo, stdin="\n".join(oids) + "\n", no_lazy_fetch=True,
        )
        for line in check.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                sizes[parts[0]] = int(parts[1])
            # "<oid> missing" -> not local (over the clone's blob limit); leave it out
    entries: list[TreeEntry] = []
    for oid, paths in oids.items():
        for path in paths:
            entries.append(TreeEntry(path=path, size=sizes.get(oid, -1), sha=oid))
    return entries


def read_blob(repo: Path, sha: str, path: str) -> bytes:
    return _run(["show", f"{sha}:{path}"], cwd=repo, text=False)  # type: ignore[return-value]
