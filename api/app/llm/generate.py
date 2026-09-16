"""Per-tag generation: inventory -> tier 1 -> tier 2 (fan-out) -> tier 3 (fan-out) -> persist."""
from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select

from ..config import Config
from ..db import session_scope
from ..ingest import git, github
from ..ingest.workspace import Workspace, open_workspace
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
from ..models import File, GenerationJob, Graph, Repo, Tag
from ..schemas import Edge, ModuleNode, SnippetNode, SystemNode, Tier1Graph, Tier2Graph, Tier3Graph
from .client import structured_call

log = logging.getLogger(__name__)

PROMPT_VERSION = "v2"
PROMPTS_DIR = Path(__file__).parent / "prompts"

TIER2_MAX_FILES_WITH_HEADS = 150
TIER2_HEAD_LINES = 60
TIER3_MAX_CHARS = 400_000  # ~100K tokens of file content per module call


# ---------- prompt helpers ----------

def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text()


def render(template: str, **values: object) -> str:
    for k, v in values.items():
        template = template.replace("{" + k + "}", str(v))
    return template


def slugify(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return s or "node"


def tier3_key(system_id: str, module_id: str) -> str:
    return f"{system_id}/{module_id}"


# ---------- job progress ----------

def _job_update(job_id: int | None, **fields: object) -> None:
    if job_id is None:
        return
    with session_scope() as s:
        job = s.get(GenerationJob, job_id)
        if job is None:
            return
        for k, v in fields.items():
            setattr(job, k, v)


def _set_tag_status(tag_id: int, status: str, error: str | None = None) -> None:
    with session_scope() as s:
        tag = s.get(Tag, tag_id)
        if tag is not None:
            tag.status = status
            tag.error = error


# ---------- repo load ----------

def load_repo(repo_id: int, job_id: int | None = None) -> list[int]:
    """Clone/fetch and upsert the tag list. Returns tag ids oldest -> newest."""
    _job_update(job_id, status="running", step="clone", progress=0.0, detail="cloning repository")
    with session_scope() as s:
        repo = s.get(Repo, repo_id)
        if repo is None:
            raise ValueError(f"repo {repo_id} not found")
        url, owner, name = repo.url, repo.owner, repo.name

    if Config.GENERATION_MODE == "chunked":
        tags = github.list_tags(owner, name)
        branch = github.default_branch(owner, name)
    else:
        path = git.clone_or_fetch(url)
        tags = git.list_tags(path)
        branch = git.default_branch(path)

    ids: list[int] = []
    with session_scope() as s:
        repo = s.get(Repo, repo_id)
        repo.default_branch = branch
        existing = {t.name: t for t in repo.tags}
        for idx, info in enumerate(tags):
            t = existing.get(info.name)
            if t is None:
                t = Tag(repo_id=repo_id, name=info.name, commit_sha=info.sha, tagged_at=info.tagged_at, order_index=idx)
                s.add(t)
            else:
                t.commit_sha = info.sha
                t.tagged_at = info.tagged_at
                t.order_index = idx
        s.flush()
        ids = [t.id for t in s.scalars(select(Tag).where(Tag.repo_id == repo_id).order_by(Tag.order_index)).all()]
    _job_update(job_id, step="tags", progress=0.02, detail=f"found {len(ids)} tags")
    return ids


def select_newest(repo_id: int, n: int | None = None, tag_pattern: str | None = None) -> list[int]:
    """Ids of the newest n tags (oldest first). `tag_pattern` is a regex restricting which
    tags count, e.g. r"^v\\d+\\.\\d+\\.\\d+$" to skip pre-releases and per-package tags."""
    n = n or Config.TAGS_ON_LOAD
    rx = re.compile(tag_pattern) if tag_pattern else None
    with session_scope() as s:
        tags = s.scalars(select(Tag).where(Tag.repo_id == repo_id).order_by(Tag.order_index)).all()
        ids = [t.id for t in tags if rx is None or rx.search(t.name)]
    if not ids:
        raise ValueError(f"no tags match {tag_pattern!r}")
    return ids[-n:] if n > 0 else []


def generate_newest(repo_id: int, n: int | None = None, force: bool = False, job_id: int | None = None, tag_pattern: str | None = None) -> None:
    ids = select_newest(repo_id, n, tag_pattern)
    job_id = job_id if job_id is not None else create_job(repo_id, ids, force=force)
    with session_scope() as s:
        job = s.get(GenerationJob, job_id)
        if not (job.state or {}).get("tags"):
            job.state = {**(job.state or {}), "tags": ids, "idx": 0, "force": force}
    run_job(job_id)


def generate_tag(repo_id: int, tag_id: int, force: bool = False, job_id: int | None = None) -> None:
    job_id = job_id if job_id is not None else create_job(repo_id, [tag_id], force=force)
    run_job(job_id)


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

    def files_unchanged(self, paths: list[str]) -> bool:
        """True when the inventory files under `paths` are the same set with identical content
        as at the reference tag, so work done there can be reused verbatim."""
        if not self.prev_files:
            return False
        cur = {f.path: f.sha for f in self.inv.under(paths)}
        if not cur or any(not sha for sha in cur.values()):
            return False
        norm = [p.strip("/") for p in paths if p.strip("/")]
        prev = {p: sha for p, sha in self.prev_files.items() if any(p == n or p.startswith(n + "/") for n in norm)}
        return cur == prev

    @property
    def system_prompt(self) -> str:
        return load_prompt("system")


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
    return render(
        load_prompt("tier1"),
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
    return render(
        load_prompt("tier2"),
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
    return render(
        load_prompt("tier3"),
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


# ---------- job state machine ----------
#
# A job generates a list of tags, oldest first, and records everything it has done in
# `GenerationJob.state` after each unit of work, so it can be resumed by another process.
#   locally : runner.py loops run_job_step() in a background thread (budget = unlimited)
#   Vercel  : POST /api/jobs/<id>/step runs one time-boxed step per HTTP call
#
# state = {tags: [ids], idx: int, force: bool,
#          phase: inventory | tier1 | tier2 | tier3 | persist,
#          prev_tag_id: int|None, tier1: {...}, tier2: {sysId: ...}, tier3: {key: ...},
#          pending_systems: [ids], pending_modules: [[sysId, modId], ...]}

TIER2_BATCH = 4  # one round of the worker pool, so a step overruns its budget by at most one round
TIER3_BATCH = 4


def create_job(repo_id: int, tag_ids: list[int], force: bool = False) -> int:
    with session_scope() as s:
        job = GenerationJob(repo_id=repo_id, status="queued", step="queued", detail="waiting", state={"tags": tag_ids, "idx": 0, "force": force})
        s.add(job)
        s.flush()
        for tid in tag_ids:
            t = s.get(Tag, tid)
            if t is not None and (force or t.graph is None):
                t.status = "queued"
                t.error = None
        return job.id


def run_job(job_id: int) -> None:
    """Run a job to completion in this process (local mode / CLI)."""
    while not run_job_step(job_id, budget_s=float("inf")):
        pass


def _previous_graph_id(s, repo_id: int, order_index: int) -> int | None:
    """Nearest generated tag to use as the id reference: the closest earlier one, or, when
    generating an older tag after newer ones exist, the closest later one."""
    prev = s.scalar(
        select(Tag)
        .join(Graph, Graph.tag_id == Tag.id)
        .where(Tag.repo_id == repo_id, Tag.order_index < order_index)
        .order_by(Tag.order_index.desc())
        .limit(1)
    )
    if prev is None:
        prev = s.scalar(
            select(Tag)
            .join(Graph, Graph.tag_id == Tag.id)
            .where(Tag.repo_id == repo_id, Tag.order_index > order_index)
            .order_by(Tag.order_index.asc())
            .limit(1)
        )
    return prev.id if prev is not None else None


def _build_ctx(repo_id: int, tag_id: int, state: dict) -> TagContext:
    with session_scope() as s:
        tag = s.get(Tag, tag_id)
        owner, name, tag_name, sha = tag.repo.owner, tag.repo.name, tag.name, tag.commit_sha
        prev_tag, prev_graph, prev_files = None, None, None
        if state.get("prev_tag_id"):
            p = s.get(Tag, state["prev_tag_id"])
            if p is not None and p.graph is not None:
                prev_tag, prev_graph = p.name, {"tier1": p.graph.tier1, "tier2": p.graph.tier2, "tier3": p.graph.tier3}
                prev_files = {f.path: f.blob_sha for f in p.files if f.blob_sha}
    ws = open_workspace(owner, name, sha)
    inv = build_inventory(ws)
    return TagContext(ws=ws, owner=owner, name=name, tag=tag_name, sha=sha, inv=inv, prev_tag=prev_tag, prev_graph=prev_graph, prev_files=prev_files)


def run_job_step(job_id: int, budget_s: float | None = None) -> bool:
    """Do up to `budget_s` seconds of work on the job and persist. Returns True when the job is done."""
    budget_s = Config.STEP_BUDGET_S if budget_s is None else budget_s
    started = time.monotonic()
    ctx: TagContext | None = None

    def save(state: dict, **fields: object) -> None:
        with session_scope() as s:
            job = s.get(GenerationJob, job_id)
            job.state = json.loads(json.dumps(state))  # fresh object so the JSON column is marked dirty
            for k, v in fields.items():
                setattr(job, k, v)

    with session_scope() as s:
        job = s.get(GenerationJob, job_id)
        if job is None:
            raise ValueError(f"job {job_id} not found")
        if job.status in {"done", "failed"}:
            return True
        repo_id = job.repo_id
        state = dict(job.state or {})
        job.status = "running"

    tags: list[int] = state.get("tags", [])
    force = bool(state.get("force"))
    tag_id: int | None = None
    try:
        while True:
            idx = int(state.get("idx", 0))
            if idx >= len(tags):
                save(state, status="done", step="done", progress=1.0, tag_id=None, finished_at=datetime.now(timezone.utc))
                return True
            tag_id = tags[idx]
            prefix = f"[{idx + 1}/{len(tags)}] " if len(tags) > 1 else ""
            phase = state.get("phase", "inventory")

            with session_scope() as s:
                tag = s.get(Tag, tag_id)
                tag_name, order_index, has_graph = tag.name, tag.order_index, tag.graph is not None

            if phase == "inventory":
                if has_graph and not force:
                    log.info("tag %s already generated, skipping", tag_name)
                    state = {**state, "idx": idx + 1, "phase": "inventory"}
                    save(state)
                    continue
                with session_scope() as s:
                    tag = s.get(Tag, tag_id)
                    tag.status, tag.error = "running", None
                    prev_id = _previous_graph_id(s, repo_id, order_index)
                state = {**state, "prev_tag_id": prev_id, "tier2": {}, "tier3": {}}
                save(state, tag_id=tag_id, step="inventory", progress=0.03, detail=f"{prefix}{tag_name}: scanning files")
                ctx = _build_ctx(repo_id, tag_id, state)
                with session_scope() as s:
                    s.execute(delete(File).where(File.tag_id == tag_id))
                    s.add_all([File(repo_id=repo_id, tag_id=tag_id, path=f.path, language=f.language, size=f.size, blob_sha=f.sha or None) for f in ctx.inv.files])
                state = {**state, "phase": "tier1"}
                save(state, step="systems", progress=0.08, detail=f"{prefix}{tag_name}: identifying systems ({len(ctx.inv.files)} files)")

            elif phase == "tier1":
                ctx = ctx or _build_ctx(repo_id, tag_id, state)
                t1 = run_tier1(ctx)
                state = {**state, "tier1": t1.model_dump(), "pending_systems": [n.id for n in t1.nodes], "phase": "tier2"}
                save(state, step="modules", progress=0.2, detail=f"{prefix}{tag_name}: modules 0 of {len(t1.nodes)}")

            elif phase == "tier2":
                pending: list[str] = list(state.get("pending_systems", []))
                systems = [SystemNode(**n) for n in state["tier1"]["nodes"]]
                if not pending:
                    mods = [[sn.id, m["id"]] for sn in systems for m in state["tier2"].get(sn.id, {}).get("nodes", [])]
                    state = {**state, "pending_modules": mods, "total_modules": len(mods), "phase": "tier3"}
                    save(state, step="snippets", progress=0.5, detail=f"{prefix}{tag_name}: snippets 0 of {len(mods)}")
                    continue
                ctx = ctx or _build_ctx(repo_id, tag_id, state)
                batch = [sn for sn in systems if sn.id in pending[:TIER2_BATCH]]
                with ThreadPoolExecutor(max_workers=Config.FANOUT_WORKERS) as pool:
                    futs = {pool.submit(run_tier2, ctx, sn, [x for x in systems if x.id != sn.id]): sn for sn in batch}
                    for fut in as_completed(futs):
                        state["tier2"][futs[fut].id] = fut.result().model_dump()
                done_ids = {sn.id for sn in batch}
                state = {**state, "pending_systems": [p for p in pending if p not in done_ids]}
                done_n = len(systems) - len(state["pending_systems"])
                save(state, progress=0.2 + 0.3 * done_n / max(1, len(systems)), detail=f"{prefix}{tag_name}: modules {done_n} of {len(systems)}")

            elif phase == "tier3":
                pending_m: list[list[str]] = list(state.get("pending_modules", []))
                total = int(state.get("total_modules", len(pending_m)))
                if not pending_m:
                    state = {**state, "phase": "persist"}
                    save(state, step="persist", progress=0.96)
                    continue
                ctx = ctx or _build_ctx(repo_id, tag_id, state)
                systems = {n["id"]: SystemNode(**n) for n in state["tier1"]["nodes"]}
                batch = pending_m[:TIER3_BATCH]
                pairs = []
                for sys_id, mod_id in batch:
                    mod = next((ModuleNode(**m) for m in state["tier2"][sys_id]["nodes"] if m["id"] == mod_id), None)
                    if mod is not None:
                        pairs.append((systems[sys_id], mod))
                with ThreadPoolExecutor(max_workers=Config.FANOUT_WORKERS) as pool:
                    futs = {pool.submit(run_tier3, ctx, sn, mod): (sn, mod) for sn, mod in pairs}
                    for fut in as_completed(futs):
                        sn, mod = futs[fut]
                        state["tier3"][tier3_key(sn.id, mod.id)] = fut.result().model_dump()
                state = {**state, "pending_modules": pending_m[len(batch):]}
                done_n = total - len(state["pending_modules"])
                save(state, progress=0.5 + 0.45 * done_n / max(1, total), detail=f"{prefix}{tag_name}: snippets {done_n} of {total}")

            elif phase == "persist":
                with session_scope() as s:
                    tag = s.get(Tag, tag_id)
                    if tag.graph is not None:
                        s.delete(tag.graph)
                        s.flush()
                    s.add(Graph(repo_id=repo_id, tag_id=tag_id, tier1=state["tier1"], tier2=state["tier2"], tier3=state["tier3"], model=Config.MODEL, prompt_version=PROMPT_VERSION, generated_at=datetime.now(timezone.utc)))
                    tag.status, tag.error = "done", None
                    repo_name = tag.repo.name
                log.info("generated %s@%s: %d systems, %d modules, %d snippet groups", repo_name, tag_name, len(state["tier1"]["nodes"]), int(state.get("total_modules", 0)), len(state["tier3"]))
                ctx = None
                if idx == len(tags) - 1:
                    # the newest tag of the job also gets its written overview
                    state = {"tags": tags, "idx": idx, "force": force, "phase": "overview"}
                    save(state, step="overview", progress=0.97, detail=f"{prefix}{tag_name}: writing overview")
                else:
                    state = {"tags": tags, "idx": idx + 1, "force": force, "phase": "inventory"}
                    save(state, progress=1.0, detail=f"{prefix}{tag_name}: done")

            elif phase == "overview":
                from .overview import write_overview  # local import: overview imports this module

                try:
                    write_overview(tag_id, force=force)
                except Exception as e:  # the graph is already saved; a failed overview must not fail the tag
                    log.warning("overview for %s failed: %s", tag_name, e)
                state = {"tags": tags, "idx": idx + 1, "force": force, "phase": "inventory"}
                save(state, progress=1.0, detail=f"{prefix}{tag_name}: done")

            else:
                raise RuntimeError(f"unknown phase {phase}")

            if time.monotonic() - started > budget_s:
                return False
    except Exception as e:
        log.exception("generation failed (job %s)", job_id)
        if tag_id is not None:
            _set_tag_status(tag_id, "failed", str(e))
        save(state, status="failed", error=str(e), finished_at=datetime.now(timezone.utc))
        raise
