"""The written per-tag overview: one model call from the tier 1/2 map plus the README."""
from __future__ import annotations

import json
import logging

from sqlalchemy import select

from ..db import session_scope
from ..ingest.filesource import get_file_source
from ..ingest.inventory import head_lines
from ..models import Tag
from ..schemas import Overview
from .client import structured_call
from .prompts import render_prompt, system_prompt

log = logging.getLogger(__name__)


def write_overview(tag_id: int, force: bool = False) -> str:
    """Generate (or return the cached) overview for a tag that has a graph."""
    with session_scope() as s:
        tag = s.get(Tag, tag_id)
        if tag is None or tag.graph is None:
            raise ValueError("no graph for this tag")
        if tag.graph.overview and not force:
            return tag.graph.overview
        owner, name, sha, tag_name = tag.repo.owner, tag.repo.name, tag.commit_sha, tag.name
        readme_path = next((f.path for f in tag.files if f.path.lower().startswith("readme")), None)
        g = tag.graph
        arch = {
            "summary": g.tier1["summary"], "systems": g.tier1["nodes"], "edges": g.tier1["edges"],
            "modules": {sid: [{"id": m["id"], "name": m["name"], "description": m["description"], "paths": m["paths"]} for m in t2["nodes"]] for sid, t2 in g.tier2.items()},
        }
    readme = ""
    if readme_path:
        readme = head_lines(get_file_source().read(owner, name, sha, readme_path, allowed={readme_path}) or "", 150)
    prompt = render_prompt("overview", owner=owner, name=name, tag=tag_name, readme=readme or "(no README)", architecture=json.dumps(arch, indent=1))
    out = structured_call(system_prompt(), prompt, Overview, max_tokens=6000, effort="medium")
    with session_scope() as s:
        tag = s.get(Tag, tag_id)
        tag.graph.overview = out.markdown
    log.info("wrote overview for %s@%s (%d chars)", name, tag_name, len(out.markdown))
    return out.markdown
