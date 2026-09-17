"""Where file contents come from. Contents are never stored in the database."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Protocol

import requests

from ..config import Config
from . import git
from .github import auth_headers


class FileSource(Protocol):
    def read(self, owner: str, name: str, sha: str, path: str) -> str | None: ...


class LocalGitFileSource:
    def read(self, owner: str, name: str, sha: str, path: str) -> str | None:
        repo = git.repo_dir(owner, name)
        if not (repo / ".git").exists():
            return None
        try:
            return git.read_blob(repo, sha, path).decode("utf-8", errors="replace")
        except git.GitError:
            return None


class GitHubRawFileSource:
    """Public repos only; fetched by commit sha so it is immutable and cacheable."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()

    @lru_cache(maxsize=256)
    def _fetch(self, url: str) -> str | None:
        headers = auth_headers()
        resp = self.session.get(url, headers=headers, timeout=20)
        if resp.status_code != 200 and headers:
            resp = self.session.get(url, timeout=20)  # public repo with a bad token: try anonymously
        if resp.status_code != 200:
            return None
        return resp.text

    def read(self, owner: str, name: str, sha: str, path: str) -> str | None:
        return self._fetch(f"https://raw.githubusercontent.com/{owner}/{name}/{sha}/{path}")


def _safe_path(path: str) -> bool:
    parts = Path(path).parts
    return bool(parts) and not path.startswith("/") and ".." not in parts


class ValidatedFileSource:
    """Wraps a source and refuses paths that are unsafe or not in the given inventory."""

    def __init__(self, inner: FileSource) -> None:
        self.inner = inner

    def read(self, owner: str, name: str, sha: str, path: str, allowed: set[str] | None = None) -> str | None:
        if not _safe_path(path):
            return None
        if allowed is not None and path not in allowed:
            return None
        return self.inner.read(owner, name, sha, path)


class LocalThenGitHubFileSource:
    """Local clone when it exists (fast, offline), otherwise GitHub raw. Lets a database synced
    from another machine still show code for repos that were never cloned here."""

    def __init__(self) -> None:
        self.local, self.remote = LocalGitFileSource(), GitHubRawFileSource()

    def read(self, owner: str, name: str, sha: str, path: str) -> str | None:
        return self.local.read(owner, name, sha, path) or self.remote.read(owner, name, sha, path)


def get_file_source() -> ValidatedFileSource:
    if Config.FILE_SOURCE == "github":
        return ValidatedFileSource(GitHubRawFileSource())
    return ValidatedFileSource(LocalThenGitHubFileSource())
