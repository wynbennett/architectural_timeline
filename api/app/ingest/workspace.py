"""Where the generator reads source files from at one commit.

GitWorkspace  - a local partial clone (git ls-tree / git show).          local mode
DirWorkspace  - an extracted GitHub tarball under a temp dir.            chunked (Vercel) mode
"""
from __future__ import annotations

import io
import os
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import requests

from ..config import Config
from . import git


class Workspace(Protocol):
    sha: str

    def list_files(self) -> list[tuple[str, int]]: ...  # (path, size); size -1 when unavailable
    def read(self, path: str) -> str: ...


@dataclass
class GitWorkspace:
    repo_path: Path
    sha: str

    def list_files(self) -> list[tuple[str, int]]:
        return [(e.path, e.size) for e in git.ls_tree(self.repo_path, self.sha)]

    def read(self, path: str) -> str:
        try:
            return git.read_blob(self.repo_path, self.sha, path).decode("utf-8", errors="replace")
        except git.GitError:
            return ""


@dataclass
class DirWorkspace:
    root: Path
    sha: str

    def list_files(self) -> list[tuple[str, int]]:
        out: list[tuple[str, int]] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            for f in filenames:
                full = Path(dirpath) / f
                if full.is_symlink():
                    continue
                out.append((full.relative_to(self.root).as_posix(), full.stat().st_size))
        return out

    def read(self, path: str) -> str:
        full = (self.root / path)
        try:
            if not full.resolve().is_relative_to(self.root.resolve()):
                return ""
            return full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""


def tarball_root() -> Path:
    return Path(os.environ.get("TARBALL_CACHE_DIR") or Path(tempfile.gettempdir()) / "arch-timeline-src")


def fetch_tarball(owner: str, name: str, sha: str, session: requests.Session | None = None) -> DirWorkspace:
    """Download and extract the repo at `sha` (public repos). Cached per sha while the
    instance stays warm; ~seconds for a typical repo. Files over the inventory cap are
    kept on disk but excluded by the inventory as usual."""
    dest = tarball_root() / f"{owner}_{name}_{sha[:12]}"
    marker = dest / ".complete"
    if marker.exists():
        return DirWorkspace(root=dest, sha=sha)
    url = f"https://codeload.github.com/{owner}/{name}/tar.gz/{sha}"
    resp = (session or requests).get(url, timeout=120)
    resp.raise_for_status()
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tar:
        for member in tar.getmembers():
            # strip the leading "<name>-<sha>/" directory and refuse anything that escapes
            parts = Path(member.name).parts[1:]
            if not parts or ".." in parts:
                continue
            member.name = str(Path(*parts))
            if member.isfile() or member.isdir():
                tar.extract(member, dest, filter="data")
    marker.write_text("ok")
    return DirWorkspace(root=dest, sha=sha)


def open_workspace(owner: str, name: str, sha: str) -> Workspace:
    """Local mode: the clone (cloning on demand). Chunked mode: the tarball."""
    if Config.GENERATION_MODE == "chunked":
        return fetch_tarball(owner, name, sha)
    repo_path = git.repo_dir(owner, name)
    if not (repo_path / ".git").exists():
        repo_path = git.clone_or_fetch(f"https://github.com/{owner}/{name}")
    return GitWorkspace(repo_path=repo_path, sha=sha)
