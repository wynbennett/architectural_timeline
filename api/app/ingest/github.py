"""GitHub REST access used in chunked mode, where there is no git binary."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

import requests

from ..config import Config

API = "https://api.github.com"


def auth_headers() -> dict[str, str]:
    """Authorization header when GITHUB_TOKEN is set (private repos, higher rate limits)."""
    return {"Authorization": f"Bearer {Config.GITHUB_TOKEN}"} if Config.GITHUB_TOKEN else {}


def _headers() -> dict[str, str]:
    return {"Accept": "application/vnd.github+json", "User-Agent": "arch-timeline", **auth_headers()}


@dataclass
class ApiTag:
    name: str
    sha: str
    tagged_at: datetime | None


def _version_key(name: str):
    nums = [int(x) for x in re.findall(r"\d+", name)]
    return (nums, name)


def list_tags(owner: str, name: str, max_pages: int = 5, session: requests.Session | None = None) -> list[ApiTag]:
    """Tags oldest -> newest. The tags API has no dates, so ordering is by the numbers in the
    tag name (v1.2.10 after v1.2.9), falling back to the name itself."""
    s = session or requests.Session()
    tags: list[ApiTag] = []
    for page in range(1, max_pages + 1):
        r = s.get(f"{API}/repos/{owner}/{name}/tags", params={"per_page": 100, "page": page}, headers=_headers(), timeout=30)
        r.raise_for_status()
        batch = r.json()
        tags.extend(ApiTag(name=t["name"], sha=t["commit"]["sha"], tagged_at=None) for t in batch)
        if len(batch) < 100:
            break
    tags.sort(key=lambda t: _version_key(t.name))
    return tags


def default_branch(owner: str, name: str, session: requests.Session | None = None) -> str | None:
    r = (session or requests).get(f"{API}/repos/{owner}/{name}", headers=_headers(), timeout=30)
    return r.json().get("default_branch") if r.ok else None
