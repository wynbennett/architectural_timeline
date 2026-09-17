"""Deterministic diff between two generated graphs, by node id. No LLM involved."""
from __future__ import annotations

from typing import Any

Status = str  # added | removed | changed | modified | unchanged
#   changed  = the node's paths (or kind / line range) differ: it was re-scoped or moved
#   modified = same paths, but the content of files under them differs (by blob hash)

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


def _content_modified(n: dict, cur_files: dict[str, str] | None, prev_files: dict[str, str] | None) -> bool:
    """Same scope, different bytes: any file under the node's paths (or its single file) changed."""
    if not cur_files or not prev_files:
        return False
    paths = n.get("paths") or ([n["file_path"]] if n.get("file_path") else [])
    return _under(cur_files, paths) != _under(prev_files, paths)


def diff_scope(cur: dict | None, prev: dict | None, fields: tuple[str, ...], cur_files: dict[str, str] | None = None, prev_files: dict[str, str] | None = None) -> dict[str, Any]:
    cur_nodes = {n["id"]: n for n in (cur or {}).get("nodes", [])}
    prev_nodes = {n["id"]: n for n in (prev or {}).get("nodes", [])}
    nodes: dict[str, Status] = {}
    for nid, n in cur_nodes.items():
        if nid not in prev_nodes:
            nodes[nid] = "added"
        elif any(n.get(f) != prev_nodes[nid].get(f) for f in fields):
            nodes[nid] = "changed"
        elif _content_modified(n, cur_files, prev_files):
            nodes[nid] = "modified"
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
