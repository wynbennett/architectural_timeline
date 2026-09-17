"""The three tiers: prompt building, model calls, and repair of what comes back.

Orchestration (jobs, resume, persistence) lives in jobs.py."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from ..config import Config
from ..ingest.workspace import Workspace
from ..ingest.inventory import (
    Inventory,
    build_inventory,
    directory_tree,
    entrypoint_paths,
    file_block,
    head_lines,
    manifest_paths,
    numbered,
    read_text,
    readme_path,
)
from ..schemas import Edge, ModuleNode, SnippetNode, SystemNode, Tier1Graph, Tier2Graph, Tier3Graph
from .client import structured_call
from .prompts import PROMPT_VERSION, render_prompt, system_prompt

log = logging.getLogger(__name__)


TIER2_MAX_FILES_WITH_HEADS = 150
TIER2_HEAD_LINES = 60
TIER3_MAX_CHARS = 400_000  # ~100K tokens of file content per module call


# ---------- helpers ----------

def slugify(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return s or "node"


def tier3_key(system_id: str, module_id: str) -> str:
    return f"{system_id}/{module_id}"


# ---------- context dataclasses ----------

@dataclass
class TagContext:
    ws: Workspace
    owner: str
    name: str
    tag: str
    sha: str
    inv: Inventory
    prev_tag: str | None
    prev_graph: dict | None  # {"tier1":..., "tier2":..., "tier3":...}
    prev_files: dict[str, str] | None = None  # path -> blob sha at the reference tag
    prev_prompt_version: str | None = None    # reuse only when the neighbor was made with the current prompts

    def files_unchanged(self, paths: list[str]) -> bool:
        """True when the inventory files under `paths` are the same set with identical content
        as at the reference tag, so work done there can be reused verbatim."""
        if not self.prev_files or self.prev_prompt_version != PROMPT_VERSION:
            return False
        cur = {f.path: f.sha for f in self.inv.under(paths)}
        if not cur or any(not sha for sha in cur.values()):
            return False
        norm = [p.strip("/") for p in paths if p.strip("/")]
        prev = {p: sha for p, sha in self.prev_files.items() if any(p == n or p.startswith(n + "/") for n in norm)}
        return cur == prev

    @property
    def system_prompt(self) -> str:
        return system_prompt()


# ---------- tier 1 ----------

def build_tier1_prompt(ctx: TagContext) -> str:
    inv = ctx.inv
    manifests = "\n\n".join(
        file_block(p, head_lines(read_text(ctx.ws, p), 150)) for p in manifest_paths(inv)
    ) or "(none found)"
    rp = readme_path(inv)
    readme = head_lines(read_text(ctx.ws, rp), 200) if rp else "(no README)"
    entry = "\n\n".join(
        file_block(p, head_lines(read_text(ctx.ws, p), 40)) for p in entrypoint_paths(inv)
    ) or "(none detected)"
    if ctx.prev_graph:
        prev_nodes = [
            {"id": n["id"], "name": n["name"], "kind": n["kind"], "paths": n["paths"]}
            for n in ctx.prev_graph["tier1"]["nodes"]
        ]
        prev_sentence = f"A neighboring tag, {ctx.prev_tag}, was already analyzed; its components are listed below. Reuse its ids for components that also exist here."
        prev_json = json.dumps(prev_nodes, indent=1)
    else:
        prev_sentence = "No neighboring tag has been analyzed yet; there is no component list to align with."
        prev_json = "none"
    return render_prompt("tier1",
        owner=ctx.owner, name=ctx.name, tag=ctx.tag, sha=ctx.sha[:12],
        prev_context_sentence=prev_sentence,
        directory_tree=directory_tree(inv),
        manifests=manifests, readme=readme, entrypoints=entry,
        prev_tag=ctx.prev_tag or "none", previous_components=prev_json,
    )


def repair_tier1(g: Tier1Graph, inv: Inventory) -> Tier1Graph:
    nodes: list[SystemNode] = []
    seen: set[str] = set()
    for n in g.nodes:
        nid = slugify(n.id or n.name)
        while nid in seen:
            nid += "-2"
        seen.add(nid)
        paths = [p.strip("/") for p in n.paths if inv.path_exists(p)]
        dropped = len(n.paths) - len(paths)
        if dropped:
            log.warning("tier1 %s: dropped %d unknown paths", nid, dropped)
        nodes.append(SystemNode(id=nid, name=n.name, kind=n.kind, description=n.description, paths=paths))
    edges = _repair_edges(g.edges, seen, "tier1")
    return Tier1Graph(summary=g.summary, nodes=nodes, edges=edges)


def _repair_edges(edges: list[Edge], ids: set[str], label: str) -> list[Edge]:
    out: list[Edge] = []
    seen: set[tuple[str, str, str]] = set()
    for e in edges:
        src, dst = slugify(e.source), slugify(e.target)
        if src not in ids or dst not in ids or src == dst:
            log.warning("%s: dropped edge %s -> %s", label, e.source, e.target)
            continue
        key = (src, dst, e.kind)
        if key in seen:
            continue
        seen.add(key)
        out.append(Edge(source=src, target=dst, kind=e.kind, label=e.label))
    return out


def run_tier1(ctx: TagContext) -> Tier1Graph:
    raw = structured_call(ctx.system_prompt, build_tier1_prompt(ctx), Tier1Graph)
    return repair_tier1(raw, ctx.inv)


# ---------- tier 2 ----------

def build_tier2_prompt(ctx: TagContext, system: SystemNode, siblings: list[SystemNode]) -> str | None:
    files = ctx.inv.under(system.paths)
    if not files:
        return None
    blocks: list[str] = []
    for f in files[:TIER2_MAX_FILES_WITH_HEADS]:
        text = read_text(ctx.ws, f.path)
        total = len(text.splitlines())
        blocks.append(file_block(f.path, head_lines(text, TIER2_HEAD_LINES), lines=total))
    rest = files[TIER2_MAX_FILES_WITH_HEADS:]
    if rest:
        blocks.append("<more_files_paths_only>\n" + "\n".join(f.path for f in rest) + "\n</more_files_paths_only>")
    prev_json = "none"
    if ctx.prev_graph and system.id in ctx.prev_graph["tier2"]:
        prev_json = json.dumps(
            [{"id": m["id"], "name": m["name"], "paths": m["paths"]} for m in ctx.prev_graph["tier2"][system.id]["nodes"]],
            indent=1,
        )
    return render_prompt("tier2",
        owner=ctx.owner, name=ctx.name, tag=ctx.tag,
        system_name=system.name, system_id=system.id, system_kind=system.kind,
        system_description=system.description, system_paths=", ".join(system.paths),
        sibling_components="\n".join(f"- {s.name} (id: {s.id}, {s.kind})" for s in siblings) or "(none)",
        files="\n\n".join(blocks),
        prev_tag=ctx.prev_tag or "none", previous_modules=prev_json,
    )


def repair_tier2(g: Tier2Graph, inv: Inventory, system: SystemNode) -> Tier2Graph:
    allowed = {f.path for f in inv.under(system.paths)}
    nodes: list[ModuleNode] = []
    seen: set[str] = set()
    for m in g.nodes:
        mid = slugify(m.id or m.name)
        while mid in seen:
            mid += "-2"
        paths: list[str] = []
        for p in m.paths:
            p = p.strip("/")
            if p in allowed or any(a.startswith(p + "/") for a in allowed):
                paths.append(p)
        if not paths:
            log.warning("tier2 %s/%s: no valid paths, dropping module", system.id, mid)
            continue
        seen.add(mid)
        nodes.append(ModuleNode(id=mid, name=m.name, description=m.description, paths=paths))
    return Tier2Graph(nodes=nodes, edges=_repair_edges(g.edges, seen, f"tier2:{system.id}"))


def _reusable_tier2(ctx: TagContext, system: SystemNode) -> Tier2Graph | None:
    """The reference tag's modules for this system, when the system has the same paths and
    none of its files changed."""
    if not ctx.prev_graph:
        return None
    prev_sys = next((n for n in ctx.prev_graph["tier1"]["nodes"] if n["id"] == system.id), None)
    if prev_sys is None or sorted(prev_sys.get("paths", [])) != sorted(system.paths) or system.id not in ctx.prev_graph["tier2"]:
        return None
    if not ctx.files_unchanged(system.paths):
        return None
    return Tier2Graph(**ctx.prev_graph["tier2"][system.id])


def _reusable_tier3(ctx: TagContext, system: SystemNode, module: ModuleNode) -> Tier3Graph | None:
    if not ctx.prev_graph:
        return None
    key = tier3_key(system.id, module.id)
    prev_mod = next((m for m in ctx.prev_graph["tier2"].get(system.id, {}).get("nodes", []) if m["id"] == module.id), None)
    if prev_mod is None or sorted(prev_mod.get("paths", [])) != sorted(module.paths) or key not in ctx.prev_graph["tier3"]:
        return None
    if not ctx.files_unchanged(module.paths):
        return None
    return Tier3Graph(**ctx.prev_graph["tier3"][key])


def run_tier2(ctx: TagContext, system: SystemNode, siblings: list[SystemNode]) -> Tier2Graph:
    if system.kind == "external":
        return Tier2Graph(nodes=[], edges=[])  # not implemented in this repo; nothing to zoom into
    reused = _reusable_tier2(ctx, system)
    if reused is not None:
        log.info("tier2 %s: unchanged since %s, reused", system.id, ctx.prev_tag)
        return reused
    prompt = build_tier2_prompt(ctx, system, siblings)
    if prompt is None:
        return Tier2Graph(nodes=[], edges=[])
    raw = structured_call(ctx.system_prompt, prompt, Tier2Graph)
    return repair_tier2(raw, ctx.inv, system)


# ---------- tier 3 ----------

def _module_files(ctx: TagContext, module: ModuleNode) -> dict[str, str]:
    """path -> content for the module, dropping the largest files if over budget."""
    files = ctx.inv.under(module.paths)
    contents = {f.path: read_text(ctx.ws, f.path) for f in files}
    total = sum(len(v) for v in contents.values())
    omitted: list[str] = []
    for path in sorted(contents, key=lambda p: -len(contents[p])):
        if total <= TIER3_MAX_CHARS:
            break
        total -= len(contents.pop(path))
        omitted.append(path)
    if omitted:
        log.warning("tier3 %s: omitted %d files over budget", module.id, len(omitted))
        contents["__omitted__"] = "\n".join(omitted)
    return contents


def build_tier3_prompt(ctx: TagContext, system: SystemNode, module: ModuleNode, contents: dict[str, str]) -> str | None:
    real = {p: c for p, c in contents.items() if p != "__omitted__"}
    if not real:
        return None
    blocks = [file_block(p, numbered(c)) for p, c in real.items()]
    if "__omitted__" in contents:
        blocks.append("<omitted_files>\n" + contents["__omitted__"] + "\n</omitted_files>")
    prev_json = "none"
    key = tier3_key(system.id, module.id)
    if ctx.prev_graph and key in ctx.prev_graph["tier3"]:
        prev_json = json.dumps(
            [{"id": s["id"], "title": s["title"], "file_path": s["file_path"]} for s in ctx.prev_graph["tier3"][key]["nodes"]],
            indent=1,
        )
    return render_prompt("tier3",
        owner=ctx.owner, name=ctx.name, tag=ctx.tag,
        system_name=system.name, module_name=module.name, module_id=module.id,
        module_description=module.description,
        files="\n\n".join(blocks),
        prev_tag=ctx.prev_tag or "none", previous_snippets=prev_json,
    )


def repair_tier3(g: Tier3Graph, contents: dict[str, str], label: str) -> Tier3Graph:
    line_counts = {p: len(c.splitlines()) for p, c in contents.items() if p != "__omitted__"}
    nodes: list[SnippetNode] = []
    seen: set[str] = set()
    for sn in g.nodes:
        path = sn.file_path.strip("/")
        if path not in line_counts:
            log.warning("tier3 %s: dropped snippet with unknown file %s", label, sn.file_path)
            continue
        n = line_counts[path]
        start = max(1, min(sn.start_line, n))
        end = max(start, min(sn.end_line, n))
        sid = slugify(sn.id or sn.title)
        while sid in seen:
            sid += "-2"
        seen.add(sid)
        nodes.append(SnippetNode(id=sid, title=sn.title, description=sn.description, file_path=path, start_line=start, end_line=end))
    return Tier3Graph(nodes=nodes, edges=_repair_edges(g.edges, seen, f"tier3:{label}"))


def run_tier3(ctx: TagContext, system: SystemNode, module: ModuleNode) -> Tier3Graph:
    reused = _reusable_tier3(ctx, system, module)
    if reused is not None:
        log.info("tier3 %s: unchanged since %s, reused", tier3_key(system.id, module.id), ctx.prev_tag)
        return reused
    contents = _module_files(ctx, module)
    prompt = build_tier3_prompt(ctx, system, module, contents)
    if prompt is None:
        return Tier3Graph(nodes=[], edges=[])
    raw = structured_call(ctx.system_prompt, prompt, Tier3Graph)
    return repair_tier3(raw, contents, tier3_key(system.id, module.id))


