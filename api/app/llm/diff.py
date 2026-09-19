"""Deterministic diff between two generated graphs, by node id. No LLM involved."""
from __future__ import annotations

from typing import Any

Status = str  # added | removed | modified | changed | unchanged
#   modified = the code under the node changed (any file under its old or new paths differs by blob hash)
#   changed  = same code, but the node's paths / kind / line range differ: it was re-scoped or moved.
#              Content wins over scope: a regrouping by the model is not reported as a code change.

NODE_FIELDS = {
    "tier1": ("name", "kind", "paths"),
    "tier2": ("name", "paths"),
    "tier3": ("file_path", "start_line", "end_line"),
}


def _edge_key(e: dict) -> str:
    return f"{e['source']}|{e['target']}|{e.get('kind', '')}"


def _under(files: dict[str, str] | None, paths: list[str]) -> dict[str, str]:
    if not files:
        return {}
    norm = [p.strip("/") for p in paths if p.strip("/")]
    return {p: sha for p, sha in files.items() if any(p == n or p.startswith(n + "/") for n in norm)}


def _paths_of(n: dict) -> list[str]:
    return n.get("paths") or ([n["file_path"]] if n.get("file_path") else [])


def _content_modified(cur: dict, prev: dict, cur_files: dict[str, str] | None, prev_files: dict[str, str] | None) -> bool:
    """Different bytes under the node: compare the files under the union of its old and new paths."""
    if not cur_files or not prev_files:
        return False
    paths = list(dict.fromkeys(_paths_of(cur) + _paths_of(prev)))
    return _under(cur_files, paths) != _under(prev_files, paths)


def _same_scope(cur: dict, prev: dict, cur_files: dict[str, str] | None) -> bool:
    """Paths spelled differently but covering the same files (and same kind) are not a re-scope."""
    if not cur_files or "paths" not in cur or cur.get("kind") != prev.get("kind"):
        return False
    return set(_under(cur_files, cur["paths"])) == set(_under(cur_files, prev.get("paths", [])))


def changed_files(cur_files: dict[str, str], prev_files: dict[str, str]) -> dict[str, list[str]]:
    """File-level view of the same comparison, for the file tree."""
    return {
        "added": sorted(p for p in cur_files if p not in prev_files),
        "removed": sorted(p for p in prev_files if p not in cur_files),
        "modified": sorted(p for p in cur_files if p in prev_files and cur_files[p] != prev_files[p]),
    }


def diff_scope(cur: dict | None, prev: dict | None, fields: tuple[str, ...], cur_files: dict[str, str] | None = None, prev_files: dict[str, str] | None = None) -> dict[str, Any]:
    cur_nodes = {n["id"]: n for n in (cur or {}).get("nodes", [])}
    prev_nodes = {n["id"]: n for n in (prev or {}).get("nodes", [])}
    nodes: dict[str, Status] = {}
    for nid, n in cur_nodes.items():
        if nid not in prev_nodes:
            nodes[nid] = "added"
        elif _content_modified(n, prev_nodes[nid], cur_files, prev_files):
            nodes[nid] = "modified"
        elif any(n.get(f) != prev_nodes[nid].get(f) for f in fields) and not _same_scope(n, prev_nodes[nid], cur_files):
            nodes[nid] = "changed"
        else:
            nodes[nid] = "unchanged"
    for nid in prev_nodes:
        if nid not in cur_nodes:
            nodes[nid] = "removed"
    cur_edges = {_edge_key(e): e for e in (cur or {}).get("edges", [])}
    prev_edges = {_edge_key(e): e for e in (prev or {}).get("edges", [])}
    edges: dict[str, Status] = {}
    for k in cur_edges:
        edges[k] = "unchanged" if k in prev_edges else "added"
    for k in prev_edges:
        if k not in cur_edges:
            edges[k] = "removed"
    counts = {s: sum(1 for v in nodes.values() if v == s) for s in ("added", "removed", "changed", "modified", "unchanged")}
    edge_counts = {s: sum(1 for v in edges.values() if v == s) for s in ("added", "removed", "unchanged")}
    return {"nodes": nodes, "edges": edges, "counts": counts, "edge_counts": edge_counts}


def diff_graphs(cur: dict, prev: dict, cur_files: dict[str, str] | None = None, prev_files: dict[str, str] | None = None) -> dict[str, Any]:
    """cur/prev: {"tier1": ..., "tier2": {sysId: ...}, "tier3": {key: ...}}.
    cur_files/prev_files: path -> blob sha at each tag, enabling the "modified" state."""
    f = (cur_files, prev_files)
    t1 = diff_scope(cur["tier1"], prev["tier1"], NODE_FIELDS["tier1"], *f)
    t2 = {sid: diff_scope(cur["tier2"].get(sid), prev["tier2"].get(sid), NODE_FIELDS["tier2"], *f) for sid in set(cur["tier2"]) | set(prev["tier2"])}
    t3 = {k: diff_scope(cur["tier3"].get(k), prev["tier3"].get(k), NODE_FIELDS["tier3"], *f) for k in set(cur["tier3"]) | set(prev["tier3"])}
    return {"tier1": t1, "tier2": t2, "tier3": t3}


def diff_digest(cur: dict, prev: dict, d: dict) -> str:
    """Compact human-readable digest for prompts: what was added/removed/changed at tiers 1 and 2."""
    name1 = {n["id"]: n["name"] for n in prev["tier1"]["nodes"] + cur["tier1"]["nodes"]}
    lines: list[str] = []
    for status in ("added", "removed", "changed", "modified"):
        ids = [i for i, s in d["tier1"]["nodes"].items() if s == status]
        if ids:
            label = {"changed": "re-scoped (paths moved)", "modified": "modified (same paths, code changed)"}.get(status, status)
            lines.append(f"systems {label}: " + ", ".join(f"{name1.get(i, i)} ({i})" for i in ids))
    for k in ("added", "removed"):
        es = [e for e, s in d["tier1"]["edges"].items() if s == k]
        if es:
            lines.append(f"system edges {k}: " + ", ".join(es))
    for sid, sd in sorted(d["tier2"].items()):
        parts = []
        for status in ("added", "removed", "changed", "modified"):
            ids = [i for i, s in sd["nodes"].items() if s == status]
            if ids:
                parts.append(f"{status}: {', '.join(ids)}")
        if parts:
            lines.append(f"modules of {name1.get(sid, sid)}: " + "; ".join(parts))
    return "\n".join(lines) or "no structural changes at the system or module level"
